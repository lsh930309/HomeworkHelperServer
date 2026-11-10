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


def check_staged(repo, monkeypatch):
    monkeypatch.chdir(repo)
    monkeypatch.setattr(sys, "argv", ["version_policy.py", "check-staged"])
    return policy.main()


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


def test_unmarked_document_merge_allows_later_patch_and_product_pr(repo):
    start_policy(repo)
    git(repo, "switch", "-c", "documentation")
    commit(repo, "docs/feature.md", "문서 수정")
    git(repo, "switch", "main")
    git(repo, "merge", "--no-ff", "-m", "문서 브랜치 병합", "documentation")
    neutral = git(repo, "rev-parse", "HEAD")
    patch = commit(repo, "src/host.py", "호스트 직접 수정")
    git(repo, "update-ref", "refs/remotes/origin/main", patch)
    ledger = policy.VersionLedger(repo)

    ledger.check_main_ready(patch)
    assert not ledger.path.exists() and not ledger.path.with_suffix(".lock").exists()
    assert ledger.resolve_build("host", patch).version == "1.6.1"
    assert ledger.read_main(neutral)[1] is None

    git(repo, "switch", "-c", "host-feature")
    commit(repo, "src/feature.py", "호스트 새 기능")
    merged = merge_pr(repo, "host-feature", "host", "minor")
    assert ledger.record_main(merged, event="minor", expected_product="host").version == "1.7.0"


def test_main_sync_keeps_dev_number_and_records_only_manual_product_change(repo, monkeypatch):
    start_policy(repo)
    git(repo, "switch", "-c", "host-feature")
    feature = commit(repo, "src/feature.py", "호스트 개발 기능")
    ledger = policy.VersionLedger(repo)
    assert ledger.resolve_build("host", feature).version == "dev.1"
    git(repo, "switch", "main")
    commit(repo, "src/main_host.py", "main 호스트 패치")
    main_tip = commit(repo, "clients/macos/Sources/Main.swift", "main 클라이언트 패치")
    git(repo, "update-ref", "refs/remotes/origin/main", main_tip)
    git(repo, "switch", "host-feature")
    git(repo, "merge", "--no-ff", "--no-commit", "main")
    assert check_staged(repo, monkeypatch) == 0
    git(repo, "commit", "-m", "main 동기화")
    synced = git(repo, "rev-parse", "HEAD")
    policy.validate_commit_range(repo, main_tip, synced)
    assert ledger.resolve_build("host", synced).version == "dev.1"

    git(repo, "switch", "main")
    main_tip = commit(repo, "clients/macos/Sources/Later.swift", "다음 main 클라이언트 패치")
    git(repo, "update-ref", "refs/remotes/origin/main", main_tip)
    git(repo, "switch", "host-feature")
    git(repo, "merge", "--no-ff", "--no-commit", "main")
    (repo / "src/manual.py").write_text("병합 중 호스트 변경", encoding="utf-8")
    (repo / "clients/macos/Sources/Manual.swift").write_text("병합 중 클라이언트 변경", encoding="utf-8")
    git(repo, "add", "src/manual.py", "clients/macos/Sources/Manual.swift")
    assert check_staged(repo, monkeypatch) == 1
    git(repo, "rm", "-f", "clients/macos/Sources/Manual.swift")
    assert check_staged(repo, monkeypatch) == 0
    git(repo, "commit", "-m", "호스트 변경이 포함된 main 동기화")
    edited_sync = git(repo, "rev-parse", "HEAD")
    policy.validate_commit_range(repo, main_tip, edited_sync)
    assert ledger.resolve_build("host", edited_sync).version == "dev.2"


@pytest.mark.parametrize(("symbol", "expected"), [
    ("create_installer", {"host"}), ("create_macos_pkg", {"client"}),
    ("archive_old_files", set()), ("main", {"host", "client"}),
])
def test_build_py_ownership_is_identical_for_commits_and_the_staged_index(repo, monkeypatch, symbol, expected):
    symbols = ("create_installer", "create_macos_pkg", "archive_old_files", "main")
    initial = "\n\n".join(f"def {name}():\n    return {index}" for index, name in enumerate(symbols))
    before = commit(repo, "build.py", initial)
    git(repo, "update-ref", "refs/remotes/origin/main", before)
    start_policy(repo)
    git(repo, "switch", "-c", "build-change")
    changed = initial.replace(f"def {symbol}():\n    return {symbols.index(symbol)}", f"def {symbol}():\n    return 99")
    path = repo / "build.py"
    path.write_text(changed, encoding="utf-8")
    git(repo, "add", "build.py")
    path.write_text("작업 트리의 이 내용은 스테이징하지 않음", encoding="utf-8")
    assert check_staged(repo, monkeypatch) == (1 if len(expected) > 1 else 0)
    git(repo, "commit", "-m", "빌드 함수 변경")
    assert policy.changed_products(repo, before, git(repo, "rev-parse", "HEAD")) == expected


def test_resolving_a_real_host_only_build_conflict_is_a_host_dev_change(repo, monkeypatch):
    def source(value):
        return f"def create_installer():\n    return {value}\n\ndef create_macos_pkg():\n    return 100\n"

    baseline = commit(repo, "build.py", source(1))
    git(repo, "update-ref", "refs/remotes/origin/main", baseline)
    start_policy(repo)
    git(repo, "switch", "-c", "host-feature")
    feature = commit(repo, "build.py", source(2))
    ledger = policy.VersionLedger(repo)
    assert ledger.resolve_build("host", feature).version == "dev.1"
    git(repo, "switch", "main")
    main_tip = commit(repo, "build.py", source(3))
    git(repo, "update-ref", "refs/remotes/origin/main", main_tip)
    git(repo, "switch", "host-feature")
    conflicted = subprocess.run(("git", "merge", "--no-ff", "--no-commit", "main"), cwd=repo,
                                capture_output=True, text=True)
    assert conflicted.returncode == 1
    assert git(repo, "ls-files", "--unmerged", "build.py")

    (repo / "build.py").write_text(source(5), encoding="utf-8")
    git(repo, "add", "build.py")
    assert check_staged(repo, monkeypatch) == 0
    git(repo, "commit", "-m", "호스트 빌드 충돌 해결")
    resolved = git(repo, "rev-parse", "HEAD")
    policy.validate_commit_range(repo, main_tip, resolved)
    assert ledger.resolve_build("host", resolved).version == "dev.2"


def test_reordering_cross_scope_build_definitions_is_shared_but_known_module_keeps_owner(repo, monkeypatch):
    host = "def create_installer():\n    return 1\n"
    client = "def create_macos_pkg(installer=create_installer):\n    return installer\n"
    baseline = commit(repo, "build.py", host + "\n" + client)
    git(repo, "update-ref", "refs/remotes/origin/main", baseline)
    start_policy(repo)
    git(repo, "switch", "-c", "build-order")
    path = repo / "build.py"
    path.write_text(client + "\n" + host, encoding="utf-8")
    git(repo, "add", "build.py")
    assert check_staged(repo, monkeypatch) == 1
    git(repo, "commit", "-m", "다른 제품 정의의 평가 순서 변경")
    reordered = git(repo, "rev-parse", "HEAD")
    assert policy.changed_products(repo, baseline, reordered) == {"host", "client"}

    git(repo, "switch", "-c", "client-packager", "main")
    known = commit(repo, "tools/package_macos_remote_app.py", "version = '1.0.1'")
    assert policy.changed_products(repo, baseline, known) == {"client"}

    git(repo, "switch", "-c", "unknown-packager", "main")
    moved = commit(repo, "build.py", "from tools.unknown_module import create_installer\n\n" + client)
    assert policy.changed_products(repo, baseline, moved) == {"host", "client"}


def test_archive_definition_value_is_neutral_but_dependency_reordering_is_shared(repo, monkeypatch):
    release = 'RELEASE_DIR = "release"\n'
    archives = 'ARCHIVES_DIR = RELEASE_DIR + "/archives"\n'
    baseline = commit(repo, "build.py", release + archives)
    git(repo, "update-ref", "refs/remotes/origin/main", baseline)
    start_policy(repo)
    git(repo, "switch", "-c", "archive-change")
    updated = archives.replace("/archives", "/backups")
    neutral = commit(repo, "build.py", release + updated)
    assert not policy.changed_products(repo, baseline, neutral)

    (repo / "build.py").write_text(updated + release, encoding="utf-8")
    git(repo, "add", "build.py")
    assert check_staged(repo, monkeypatch) == 1
    git(repo, "commit", "-m", "아카이브 선언 순서 변경")
    assert policy.changed_products(repo, neutral, git(repo, "rev-parse", "HEAD")) == {"host", "client"}


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
