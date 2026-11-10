import builtins
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

from tools import version_policy as policy


def git(repo, *args):
    return subprocess.run(
        ("git", *args), cwd=repo, capture_output=True, text=True, check=True,
    ).stdout.strip()


def commit(repo, path, contents):
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(contents, encoding="utf-8")
    git(repo, "add", "--", path)
    git(repo, "commit", "-m", f"{path} 변경")
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for key in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_CONFIG_COUNT", "GIT_CONFIG_PARAMETERS"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")
    monkeypatch.setenv("GIT_ALLOW_PROTOCOL", "")
    monkeypatch.setattr(sys, "platform", "darwin")
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.name", "Version Fixture")
    git(tmp_path, "config", "user.email", "fixture@example.invalid")
    commit(tmp_path, "README.md", "시작점")
    git(tmp_path, "update-ref", "refs/remotes/origin/main", "HEAD")
    return tmp_path


def start_policy(repo):
    git(repo, "tag", "H/v1.6.0")
    git(repo, "tag", "C/v1.0.0")


def merge_pr(repo, branch, product, event):
    git(repo, "switch", "main")
    git(repo, "merge", "--no-ff", "-m", "[feat] 시험용 병합",
        "-m", f"HomeworkHelper-Release: PR #42 {product} {event}", branch)
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    return git(repo, "rev-parse", "HEAD")


def test_dev_numbers_follow_product_changes_and_stay_fixed_across_branches(repo):
    start_policy(repo)
    ledger = policy.VersionLedger(repo)
    git(repo, "switch", "-c", "host-a")
    first = commit(repo, "src/first.py", "첫 번째 기능")
    second = commit(repo, "src/second.py", "두 번째 기능")
    docs = commit(repo, "README.md", "설명 보완")
    assert ledger.resolve_build("host", docs) == policy.BuildVersion("host", "dev.2", docs, "1.6.0")
    assert ledger.resolve_build("host", first).version == "dev.1"
    assert ledger.resolve_build("host", second).version == "dev.2"

    git(repo, "switch", "-c", "host-b", "main")
    other_host = commit(repo, "src/other.py", "다른 호스트 기능")
    assert policy.VersionLedger(repo).resolve_build("host", other_host).version == "dev.3"
    git(repo, "switch", "-c", "client-a", "main")
    client = commit(repo, "clients/macos/Sources/App.swift", "클라이언트 기능")
    assert policy.VersionLedger(repo).resolve_build("client", client).version == "dev.1"
    assert policy.VersionLedger(repo).get("host", first).version == "dev.1"


def test_direct_patch_and_published_pr_advance_independent_products(repo):
    start_policy(repo)
    ledger = policy.VersionLedger(repo)
    patch = commit(repo, "src/host.py", "호스트 패치")
    assert ledger.resolve_build("host", patch).version == "1.6.1"
    assert ledger.resolve_build("client", patch).version == "1.0.0"
    docs = commit(repo, "docs/instructions.md", "문서 변경")
    assert ledger.resolve_build("host", docs).version == "1.6.1"
    assert git(repo, "tag", "--list").splitlines() == ["C/v1.0.0", "H/v1.6.0"]

    git(repo, "switch", "-c", "client-feature")
    client_head = commit(repo, "clients/macos/Sources/App.swift", "클라이언트 기능")
    with pytest.raises(policy.VersionPolicyError):
        ledger.record_main(client_head, event="minor", expected_product="client")
    merged = merge_pr(repo, "client-feature", "client", "minor")
    version = ledger.record_main(merged, event="minor", expected_product="client")
    assert version == policy.BuildVersion("client", "1.1.0", merged, "1.1.0")
    assert policy.VersionLedger(repo).record_main(merged, event="minor", expected_product="client") == version
    assert ledger.resolve_build("host", merged).version == "1.6.1"


def test_only_the_start_node_can_have_both_product_tags(repo):
    ledger = policy.VersionLedger(repo)
    git(repo, "tag", "H/v1.6.0")
    with pytest.raises(policy.VersionPolicyError):
        ledger.require_baseline()
    git(repo, "tag", "C/v1.0.0")
    assert ledger.require_baseline() == git(repo, "rev-parse", "HEAD")

    git(repo, "switch", "-c", "feature")
    commit(repo, "src/feature.py", "호스트 변경")
    merged = merge_pr(repo, "feature", "host", "minor")
    git(repo, "tag", "H/v1.7.0", merged)
    git(repo, "tag", "C/v1.1.0", merged)
    with pytest.raises(policy.VersionPolicyError):
        ledger.record_main(merged, event="minor", expected_product="host")
    assert ledger.read_main(merged) is None


def test_mixed_product_commit_cannot_change_versions(repo):
    start_policy(repo)
    (repo / "build.py").write_text("양쪽 패키지 입력", encoding="utf-8")
    git(repo, "add", "build.py")
    git(repo, "commit", "-m", "두 제품에 공통되는 변경")
    ledger = policy.VersionLedger(repo)
    with pytest.raises(policy.VersionPolicyError, match="두 제품"):
        ledger.resolve_build("host", "HEAD")
    assert not ledger.path.exists()


def test_major_requires_approval_and_restarts_minor_and_patch_at_zero(repo):
    start_policy(repo)
    ledger = policy.VersionLedger(repo)
    git(repo, "switch", "-c", "major-feature")
    commit(repo, "src/major.py", "승인 대상 기능")
    merged = merge_pr(repo, "major-feature", "host", "major")
    with pytest.raises(policy.VersionPolicyError, match="승인"):
        ledger.record_main(merged, event="major", expected_product="host")
    assert ledger.read_main(merged) is None
    assert ledger.record_main(merged, event="major", expected_product="host", major_approved=True).version == "2.0.0"


def test_windows_import_and_snapshot_check_do_not_require_fcntl(tmp_path, monkeypatch):
    actual_import = builtins.__import__

    def windows_import(name, *args, **kwargs):
        if name == "fcntl":
            raise ImportError("Windows에는 fcntl이 없습니다")
        return actual_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", windows_import)
    monkeypatch.setattr(sys, "platform", "win32")
    windows_policy = runpy.run_path(str(Path(policy.__file__)))
    path = tmp_path / "build.version.json"
    version = windows_policy["BuildVersion"]("host", "dev.3", "a" * 40, "1.6.0")
    path.write_text(version.to_json(), encoding="utf-8")
    read = windows_policy["read_snapshot"]
    assert read(path, product="host", commit="a" * 40) == version
    for product, commit_id in (("client", "a" * 40), ("host", "b" * 40)):
        with pytest.raises(windows_policy["VersionPolicyError"]):
            read(path, product=product, commit=commit_id)
