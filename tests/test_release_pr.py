import hashlib
import io
import json
from pathlib import Path
import subprocess

import pytest

from tools import release_pr

from test_version_policy import commit, git, repo, start_policy


class SimulatedRelease(release_pr.ReleaseCommand):
    """Run Git locally and model every network, build, and credential boundary in memory."""

    def __init__(self, checkout, head):
        self.pr_data = {
            "baseRefName": "main", "headRefOid": head, "mergeCommit": None,
            "state": "OPEN", "title": "호스트 동작 변경", "body": "변경 설명",
            "url": "https://github.com/fixture/repository/pull/42",
            "headRefName": "feature", "isDraft": False,
        }
        self.tags = {}
        self.draft = None
        self.calls = []
        self.failed_upload = None
        self.uploads = []
        self.packages = {}
        self.viewer_permission = "WRITE"
        self.host_preflight = {"ok": True}
        self.remote_main_before_merge = None
        super().__init__(checkout)

    def upload_host_file(self, args, version, draft_id, name, size, digest):
        assert self.draft["isDraft"] and self.draft["databaseId"] == draft_id
        assert version.commit == self.pr_data["mergeCommit"]["oid"]
        assert self.packages[name] == {"size": size, "sha256": digest}
        assert all(asset["name"] != name for asset in self.draft["assets"])
        self.uploads.append(name)
        if name == self.failed_upload:
            raise subprocess.TimeoutExpired("fixture asset transfer", 1)
        asset = {"name": name, "size": size, "digest": f"sha256:{digest}", "state": "uploaded"}
        self.draft["assets"].append(asset)
        return asset

    def run(self, *args, stdin=None, timeout=120):
        self.calls.append(args)

        def response(stdout="", stderr="", code=0):
            return subprocess.CompletedProcess(args, code, stdout, stderr)

        if args[:3] == ("git", "remote", "get-url"):
            return response("https://github.com/fixture/repository.git")
        if args[:2] == ("git", "fetch"):
            if args[-1].startswith("refs/pull/"):
                (self.repo / ".git/FETCH_HEAD").write_text(self.pr_data["headRefOid"] + "\n", encoding="ascii")
            for name, target in self.tags.items():
                git(self.repo, "update-ref", f"refs/tags/{name}", target)
            return response()
        if args[:2] == ("git", "ls-remote"):
            if "--heads" in args:
                assert args[-1] == "refs/heads/main"
                current = self.remote_main_before_merge or git(self.repo, "rev-parse", "refs/remotes/origin/main")
                return response(f"{current}\trefs/heads/main")
            return response("\n".join(f"{target}\trefs/tags/{name}" for name, target in self.tags.items()))
        if args[:2] == ("git", "push"):
            for spec in args[args.index("origin") + 1:]:
                target, ref = spec.split(":", 1)
                self.tags[ref.removeprefix("refs/tags/")] = target
            return response()
        if args[0] == "git" and args[1] in {
            "status", "rev-parse", "rev-list", "branch", "show", "merge-base", "merge-tree",
        }:
            return subprocess.run(args, cwd=self.repo, capture_output=True, text=True, check=False)
        if args[:3] == ("gh", "pr", "view"):
            return response(json.dumps(self.pr_data))
        if args[:3] == ("gh", "repo", "view"):
            assert args == (
                "gh", "repo", "view", "github.com/fixture/repository", "--json", "viewerPermission",
            )
            return response(json.dumps({"viewerPermission": self.viewer_permission}))
        if args[:3] == ("gh", "pr", "merge"):
            assert args[args.index("--match-head-commit") + 1] == self.pr_data["headRefOid"]
            git(self.repo, "merge", "--no-ff", "-m", args[args.index("--subject") + 1],
                "-m", stdin, self.pr_data["headRefOid"])
            merged = git(self.repo, "rev-parse", "HEAD")
            git(self.repo, "update-ref", "refs/remotes/origin/main", merged)
            self.pr_data.update(state="MERGED", mergeCommit={"oid": merged})
            return response()
        if args[:3] == ("gh", "release", "view"):
            return response(json.dumps(self.draft)) if self.draft else response(stderr="release not found", code=1)
        if args[:3] == ("gh", "release", "create"):
            assert "--draft" in args
            self.draft = {
                "assets": [], "body": stdin, "isDraft": True, "tagName": args[3],
                "databaseId": 42,
                "name": args[args.index("--title") + 1],
                "url": f"https://github.com/fixture/repository/releases/tag/{args[3]}",
            }
            return response()
        if args[:3] == ("gh", "release", "edit"):
            assert "--draft=false" in args
            self.draft["isDraft"] = False
            return response()
        if len(args) > 2 and Path(args[1]).name == "host_operations.py" and args[2] == "release-preflight":
            assert args[args.index("--release-repo") + 1] == "fixture/repository"
            return response(json.dumps(self.host_preflight), code=0 if self.host_preflight["ok"] else 1)
        if len(args) > 2 and Path(args[1]).name == "host_operations.py" and args[2] == "release-build":
            build_commit = args[args.index("--commit") + 1]
            tag = args[args.index("--release-tag") + 1]
            assert build_commit == self.pr_data["mergeCommit"]["oid"]
            if "--reuse-release" in args and not self.packages:
                return response(stderr="fixture has no original package", code=1)
            version = tag.removeprefix("H/v")
            self.packages = {
                f"HomeworkHelper_v{version}_Setup.exe": {"size": 10, "sha256": "a" * 64},
                f"HomeworkHelper_v{version}_Portable.zip": {"size": 12, "sha256": "b" * 64},
            }
            return response(json.dumps({"ok": True, "commit": build_commit, "result": {"assets": self.packages}}))
        pytest.fail(f"격리 fixture에서 허용하지 않은 명령: {args!r}")


def prepare_pr(checkout, path="src/feature.py"):
    start_policy(checkout)
    (checkout / ".git/info/exclude").write_text("version.ledger.json\nversion.ledger.lock\n", encoding="utf-8")
    git(checkout, "switch", "-c", "feature")
    head = commit(checkout, path, "변경 내용")
    git(checkout, "switch", "main")
    command = SimulatedRelease(checkout, head)
    baseline = git(checkout, "rev-parse", "HEAD")
    command.tags = {"H/v1.6.0": baseline, "C/v1.0.0": baseline}
    message = checkout / ".git/merge-message.txt"
    message.write_text("[feat] 시험 변경 병합\n\n- 변경 사항:\n  - 기능을 병합합니다.\n\n- 검증:\n  - 격리된 시험을 실행했습니다.\n", encoding="utf-8")
    args = release_pr.parser().parse_args([
        "merge", "42", "--head", head, "--base", baseline, "--message-file", str(message), "--host", "fixture.invalid",
    ])
    return command, args


def test_incomplete_windows_upload_stays_draft_and_retry_keeps_the_merge_version(repo):
    command, args = prepare_pr(repo)
    setup = "HomeworkHelper_v1.7.0_Setup.exe"
    portable = "HomeworkHelper_v1.7.0_Portable.zip"
    command.failed_upload = portable
    with pytest.raises(subprocess.TimeoutExpired):
        command.run_pr(args)
    merged = command.pr_data["mergeCommit"]["oid"]
    assert command.draft["isDraft"]
    assert command.tags["H/v1.7.0"] == merged
    assert command.ledger.read_main(merged)[1].version == "1.7.0"
    assert command.draft["name"] == "HomeworkHelper Host v 1.7.0"
    assert "변경 설명" in command.draft["body"]
    assert command.pr_data["url"] in command.draft["body"]
    assert command.uploads == [setup, portable]
    assert [asset["name"] for asset in command.draft["assets"]] == [setup]

    command.failed_upload = None
    args.base = "b" * 40
    with pytest.raises(ValueError, match="첫 부모"):
        command.run_pr(args)
    assert command.draft["isDraft"]
    args.base = None
    command.run_pr(args)
    assert not command.draft["isDraft"]
    assert command.uploads == [setup, portable, portable]
    assert set(command.tags) == {"H/v1.6.0", "C/v1.0.0", "H/v1.7.0"}
    assert sum(call[:3] == ("gh", "pr", "merge") for call in command.calls) == 1
    assert sum(call[:3] == ("gh", "release", "edit") for call in command.calls) == 1
    uploads = sum(len(call) > 2 and call[2] == "release-build" for call in command.calls)
    command.run_pr(args)
    assert sum(len(call) > 2 and call[2] == "release-build" for call in command.calls) == uploads


def test_merge_only_keeps_release_stages_independent_from_windows(repo):
    command, args = prepare_pr(repo)
    args.merge_only = True
    args.host = None
    command.host_preflight = {"ok": False, "reason": "transport"}
    command.run_pr(args)

    assert command.pr_data["state"] == "MERGED"
    commit_id = command.pr_data["mergeCommit"]["oid"]
    assert git(repo, "show", "-s", "--format=%P", commit_id).split() == [args.base, args.head]
    assert "HomeworkHelper-Release: PR #42 host minor" in git(repo, "show", "-s", "--format=%B", commit_id)
    assert command.ledger.read_main(commit_id) is None
    assert command.draft is None
    assert not any("release-preflight" in call or "release-build" in call for call in command.calls)
    assert set(command.tags) == {"H/v1.6.0", "C/v1.0.0"}


def test_version_build_and_publish_can_each_resume_from_the_verified_merge(repo):
    command, args = prepare_pr(repo)
    args.merge_only = True
    command.run_pr(args)
    merged = command.pr_data["mergeCommit"]["oid"]

    def stage(name, *extra):
        return release_pr.parser().parse_args([name, "42", "--head", args.head, *extra])

    with pytest.raises(ValueError, match="version 단계부터"):
        command.run_stage(stage("publish", "--host", "fixture.invalid"))
    command.run_stage(stage("version"))
    version = command.ledger.read_main(merged)[1]
    assert version.commit == merged and version.tag == "H/v1.7.0"
    assert version.tag not in command.tags and command.draft is None
    assert not any("release-build" in call for call in command.calls)
    with pytest.raises(RuntimeError, match="no original package"):
        command.run_stage(stage("publish", "--host", "fixture.invalid"))
    assert version.tag not in command.tags and command.draft is None

    command.run_stage(stage("build", "--host", "fixture.invalid"))
    assert set(command.packages) == set(release_pr.release_assets(version))
    assert version.tag not in command.tags and command.draft is None and command.uploads == []
    command.run_stage(stage("publish", "--host", "fixture.invalid"))
    assert command.tags[version.tag] == merged and not command.draft["isDraft"]
    assert set(command.uploads) == set(command.packages)
    assert sum(call[:3] == ("gh", "pr", "merge") for call in command.calls) == 1
    assert sum("release-build" in call and "--reuse-release" not in call for call in command.calls) == 1


@pytest.mark.parametrize("name", ["version", "build", "publish"])
def test_post_merge_stage_refuses_an_open_pr_without_mutating_it(repo, name):
    command, args = prepare_pr(repo)
    options = [] if name == "version" else ["--host", "fixture.invalid"]
    stage = release_pr.parser().parse_args([name, "42", "--head", args.head, *options])
    with pytest.raises(ValueError, match="병합 완료가 확인되지 않았습니다"):
        command.run_stage(stage)
    assert command.pr_data["state"] == "OPEN" and command.draft is None
    assert command.ledger.read_main(args.head) is None and command.uploads == []


def test_stale_pr_head_and_dry_run_cannot_merge_or_publish(repo):
    command, args = prepare_pr(repo)
    args.dry_run = True
    command.viewer_permission = "READ"
    command.host_preflight = {"ok": False, "reason": "transport"}
    command.run_pr(args)
    args.head = "a" * 40
    with pytest.raises(ValueError, match="PR head"):
        command.run_pr(args)
    assert command.pr_data["state"] == "OPEN"
    assert set(command.tags) == {"H/v1.6.0", "C/v1.0.0"}
    assert command.draft is None
    assert not command.ledger.path.exists()
    assert not command.ledger.path.with_suffix(".lock").exists()
    assert not any(call[:3] == ("gh", "repo", "view") or "release-preflight" in call for call in command.calls)


def test_merge_access_uses_repo_view_positional_repository(repo):
    command, _ = prepare_pr(repo)

    command.require_merge_access()

    views = [call for call in command.calls if call[:3] == ("gh", "repo", "view")]
    assert views == [(
        "gh", "repo", "view", "github.com/fixture/repository", "--json", "viewerPermission",
    )]
    assert all("--repo" not in call for call in views)
    assert not any("release-preflight" in call for call in command.calls)
    assert not any(call[:3] in {("gh", "pr", "merge"), ("gh", "release", "create")} for call in command.calls)
    assert not any(call[:2] == ("git", "push") for call in command.calls)


@pytest.mark.parametrize(("mode", "message"), [
    ("missing", "전체 SHA를 --base"),
    ("stale", "검토한 --base와 다릅니다"),
    ("race", "병합 준비 중 GitHub main"),
])
def test_open_pr_requires_the_reviewed_main_revision_until_merge(repo, mode, message):
    command, args = prepare_pr(repo)
    if mode == "missing":
        args.base = None
    elif mode == "stale":
        args.base = "b" * 40
    else:
        command.remote_main_before_merge = "b" * 40

    with pytest.raises(ValueError) as raised:
        command.run_pr(args)
    assert message in str(raised.value)
    assert command.pr_data["state"] == "OPEN"
    assert command.draft is None and not command.ledger.path.exists()
    assert not command.ledger.path.with_suffix(".lock").exists()
    assert not any(call[:3] in {("gh", "pr", "merge"), ("gh", "release", "create")} for call in command.calls)
    assert not any(call[:2] == ("git", "push") for call in command.calls)
    assert any(call[:3] == ("git", "ls-remote", "--heads") for call in command.calls) == (mode == "race")


@pytest.mark.parametrize("failure", ["mac_github", "previous_product_merge"])
def test_preflight_failures_leave_pr_and_release_untouched(repo, failure):
    command, args = prepare_pr(repo)
    if failure == "mac_github":
        command.viewer_permission = "READ"
        message = "GitHub CLI"
    else:
        git(repo, "switch", "-c", "previous")
        commit(repo, "src/previous.py", "릴리즈가 없는 제품 변경")
        git(repo, "switch", "main")
        git(repo, "merge", "--no-ff", "-m", "전용 명령을 거치지 않은 제품 병합", "previous")
        git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
        args.base = git(repo, "rev-parse", "HEAD")
        message = "PR 병합 릴리즈를 먼저 재개"

    with pytest.raises((ValueError, RuntimeError)) as raised:
        command.run_pr(args)
    assert message in str(raised.value)
    assert command.pr_data["state"] == "OPEN"
    assert set(command.tags) == {"H/v1.6.0", "C/v1.0.0"}
    assert command.draft is None and not command.ledger.path.exists()
    assert not any(call[:3] in {("gh", "pr", "merge"), ("gh", "release", "create")} for call in command.calls)
    assert not any(call[:2] == ("git", "push") for call in command.calls)
    assert not any("release-preflight" in call for call in command.calls)


def test_windows_preflight_failure_does_not_undo_merge_or_publish(repo):
    command, args = prepare_pr(repo)
    command.host_preflight = {"ok": False, "reason": "transport"}
    from tools.host_operations import RELEASE_PREFLIGHT_FAILURES

    with pytest.raises((ValueError, RuntimeError), match=RELEASE_PREFLIGHT_FAILURES["transport"]):
        command.run_pr(args)
    merged = command.pr_data["mergeCommit"]["oid"]
    assert command.pr_data["state"] == "MERGED"
    assert command.ledger.read_main(merged)[1].version == "1.7.0"
    assert command.uploads == []
    assert not any("release-build" in call or call[:3] == ("gh", "release", "edit") for call in command.calls)


@pytest.mark.parametrize("field", ["size", "digest"])
def test_resume_rejects_draft_assets_that_differ_from_windows_original(repo, field):
    command, args = prepare_pr(repo)
    setup = "HomeworkHelper_v1.7.0_Setup.exe"
    portable = "HomeworkHelper_v1.7.0_Portable.zip"
    command.failed_upload = portable
    with pytest.raises(subprocess.TimeoutExpired):
        command.run_pr(args)
    command.failed_upload = None
    command.draft["assets"][0][field] = 20 if field == "size" else f"sha256:{'0' * 64}"

    with pytest.raises(ValueError, match="기존 초안 자산"):
        command.run_pr(args)

    assert command.draft["isDraft"]
    assert command.uploads == [setup, portable]


@pytest.mark.parametrize("transfer_fails", [False, True])
def test_macos_upload_connects_ssh_bytes_to_github_without_a_local_copy(repo, monkeypatch, transfer_fails):
    command, args = prepare_pr(repo)
    version = release_pr.BuildVersion("host", "1.7.0", args.head, "1.7.0")
    name = "HomeworkHelper_v1.7.0_Setup.exe"
    package = b"MZ\x00\x80\xff\r\n"
    digest = hashlib.sha256(package).hexdigest()
    response = {"name": name, "size": len(package), "digest": f"sha256:{digest}", "state": "uploaded"}

    class Recorder(io.BytesIO):
        def close(self):
            self.transferred = self.getvalue()
            super().close()

    class MacUpload:
        def __init__(self):
            self.pipe = self.stdin = Recorder()
            self.returncode = None
            self.killed = False

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            if not self.pipe.closed:
                self.pipe.close()

        def poll(self):
            return self.returncode

        def kill(self):
            self.returncode = -9
            self.killed = True

        def communicate(self, *, timeout):
            assert not transfer_fails
            assert self.pipe.closed and self.pipe.transferred == package
            self.returncode = 0
            return json.dumps(response).encode(), b""

    upload = MacUpload()

    def popen(argv, **kwargs):
        assert argv[:5] == ("gh", "api", "--hostname", "github.com", "--method")
        assert argv[5] == "POST"
        assert argv[-3:] == ("--input", "-", f"https://uploads.github.com/repos/fixture/repository/releases/42/assets?name={name}")
        assert "Content-Type: application/octet-stream" in argv
        length_header = f"Content-Length: {len(package)}"
        assert argv[argv.index(length_header) - 1] == "--header"
        assert kwargs["cwd"] == repo and kwargs["stdin"] == subprocess.PIPE
        return upload

    def remote(parsed_args, stage, *options, timeout, stdout):
        assert parsed_args is args and stage == "release-asset"
        assert options[options.index("--commit") + 1] == version.commit
        assert options[-4:] == ("--release-file", name, str(len(package)), digest)
        assert stdout is upload.pipe
        stdout.write(package[:2] if transfer_fails else package)
        return subprocess.CompletedProcess([], 1 if transfer_fails else 0, None, "fixture SSH failure" if transfer_fails else "")

    monkeypatch.setattr(command, "run_host", remote)
    monkeypatch.setattr(subprocess, "Popen", popen)
    if transfer_fails:
        with pytest.raises(RuntimeError, match="fixture SSH failure"):
            release_pr.ReleaseCommand.upload_host_file(command, args, version, 42, name, len(package), digest)
        assert upload.killed
    else:
        assert release_pr.ReleaseCommand.upload_host_file(command, args, version, 42, name, len(package), digest) == response
        assert not upload.killed
    assert not (repo / "release").exists()


def test_documentation_pr_merges_without_version_or_release(repo):
    command, args = prepare_pr(repo, path="docs/feature.md")
    command.run_pr(args)
    merged = command.pr_data["mergeCommit"]["oid"]
    assert command.pr_data["state"] == "MERGED"
    assert command.ledger.read_main(merged)[1] is None
    assert set(command.tags) == {"H/v1.6.0", "C/v1.0.0"}
    assert command.draft is None


def test_bootstrap_pushes_two_tags_atomically_from_exact_main(repo):
    head = git(repo, "rev-parse", "HEAD")
    command = SimulatedRelease(repo, head)
    command.bootstrap(head, dry_run=True)
    assert not command.tags
    with pytest.raises(ValueError, match="동일한 전체 커밋"):
        command.bootstrap("a" * 40, dry_run=False)
    command.bootstrap(head, dry_run=False)
    assert command.tags == {"C/v1.0.0": head, "H/v1.6.0": head}
    pushes = [call for call in command.calls if call[:2] == ("git", "push")]
    assert len(pushes) == 1 and "--atomic" in pushes[0]


def test_macos_retry_reuses_matching_asset_and_never_overwrites_different_file(repo, monkeypatch):
    monkeypatch.delattr(hashlib, "file_digest", raising=False)
    head = git(repo, "rev-parse", "HEAD")
    command = SimulatedRelease(repo, head)
    version = release_pr.BuildVersion("client", "1.1.0", head, "1.1.0")
    (repo / ".git/info/exclude").write_text("release/\n", encoding="utf-8")
    path = repo / "release/HomeworkHelperRemote_v1.1.0.pkg"
    path.parent.mkdir()
    path.write_bytes(b"stale local package")
    package = b"package for the exact release commit"
    digest = hashlib.sha256(package).hexdigest()
    command.draft = {"isDraft": True, "assets": [], "tagName": version.tag,
                     "name": release_pr.release_title(version),
                     "body": release_pr.release_notes(command.pr_data, version)}
    real_local_run = command.run
    mutations = []

    def run(*args, stdin=None, timeout=120):
        if args[1:2] == ("build.py",):
            mutations.append("build")
            path.write_bytes(package)
        elif args[:3] == ("gh", "release", "upload"):
            mutations.append("upload")
            assert args[3:5] == ("C/v1.1.0", str(path))
            assert "--clobber" not in args
            command.draft["assets"] = [
                {"name": path.name, "digest": f"sha256:{digest}", "state": "uploaded", "size": len(package)},
            ]
        else:
            return real_local_run(*args, stdin=stdin, timeout=timeout)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(command, "run", run)
    assert command.client_package(version, reuse=False) == (path, digest)
    assert command.upload_client(command.pr_data, version, path, digest) == {path.name: digest}
    assert mutations == ["build", "upload"]

    assert command.client_package(version, reuse=True) == (path, digest)
    assert command.upload_client(command.pr_data, version, path, digest) == {path.name: digest}
    path.write_bytes(b"different local package")
    changed_path, changed_digest = command.client_package(version, reuse=True)
    with pytest.raises(ValueError, match="SHA-256"):
        command.upload_client(command.pr_data, version, changed_path, changed_digest)
    assert mutations == ["build", "upload"]
    assert command.draft["assets"][0]["digest"] == f"sha256:{digest}"
