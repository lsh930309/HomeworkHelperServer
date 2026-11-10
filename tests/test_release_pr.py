import hashlib
import json
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
        self.complete_upload = False
        super().__init__(checkout)

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
                "name": args[args.index("--title") + 1],
                "url": f"https://github.com/fixture/repository/releases/tag/{args[3]}",
            }
            return response()
        if args[:3] == ("gh", "release", "edit"):
            assert "--draft=false" in args
            self.draft["isDraft"] = False
            return response()
        if len(args) > 2 and args[1:3] == ("tools/host_operations.py", "release-build"):
            build_commit = args[args.index("--commit") + 1]
            tag = args[args.index("--release-tag") + 1]
            assert self.tags[tag] == build_commit and self.draft["isDraft"]
            version = tag.removeprefix("H/v")
            hashes = {f"HomeworkHelper_v{version}_Setup.exe": "a" * 64}
            if self.complete_upload:
                hashes[f"HomeworkHelper_v{version}_Portable.zip"] = "b" * 64
            self.draft["assets"] = [
                {"name": name, "digest": f"sha256:{digest}", "state": "uploaded", "size": 10}
                for name, digest in hashes.items()
            ]
            return response(json.dumps({"ok": True, "commit": build_commit, "result": {"assets": hashes}}))
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
        "merge", "42", "--head", head, "--message-file", str(message), "--host", "fixture.invalid",
    ])
    return command, args


def test_incomplete_windows_upload_stays_draft_and_retry_keeps_the_merge_version(repo):
    command, args = prepare_pr(repo)
    with pytest.raises(ValueError, match="필수 패키지"):
        command.run_pr(args)
    merged = command.pr_data["mergeCommit"]["oid"]
    assert command.draft["isDraft"]
    assert command.tags["H/v1.7.0"] == merged
    assert command.ledger.read_main(merged)[1].version == "1.7.0"
    assert command.draft["name"] == "HomeworkHelper Host v 1.7.0"
    assert "변경 설명" in command.draft["body"]
    assert command.pr_data["url"] in command.draft["body"]

    command.complete_upload = True
    command.run_pr(args)
    assert not command.draft["isDraft"]
    assert set(command.tags) == {"H/v1.6.0", "C/v1.0.0", "H/v1.7.0"}
    assert sum(call[:3] == ("gh", "pr", "merge") for call in command.calls) == 1
    assert sum(call[:3] == ("gh", "release", "edit") for call in command.calls) == 1
    uploads = sum(len(call) > 2 and call[2] == "release-build" for call in command.calls)
    command.run_pr(args)
    assert sum(len(call) > 2 and call[2] == "release-build" for call in command.calls) == uploads


def test_stale_pr_head_and_dry_run_cannot_merge_or_publish(repo):
    command, args = prepare_pr(repo)
    args.dry_run = True
    command.run_pr(args)
    args.head = "a" * 40
    with pytest.raises(ValueError, match="PR head"):
        command.run_pr(args)
    assert command.pr_data["state"] == "OPEN"
    assert set(command.tags) == {"H/v1.6.0", "C/v1.0.0"}
    assert command.draft is None
    assert not command.ledger.path.exists()


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
    head = git(repo, "rev-parse", "HEAD")
    command = SimulatedRelease(repo, head)
    version = release_pr.BuildVersion("client", "1.1.0", head, "1.1.0")
    (repo / ".git/info/exclude").write_text("release/\n", encoding="utf-8")
    path = repo / "release/HomeworkHelperRemote_v1.1.0.pkg"
    path.parent.mkdir()
    path.write_bytes(b"stale local package")
    package = b"package for the exact release commit"
    digest = hashlib.sha256(package).hexdigest()
    command.draft = {"isDraft": True, "assets": []}
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
    assert command.upload_client(version, command.draft) == {path.name: digest}
    assert mutations == ["build", "upload"]

    assert command.upload_client(version, command.draft) == {path.name: digest}
    path.write_bytes(b"different local package")
    with pytest.raises(ValueError, match="SHA-256"):
        command.upload_client(version, command.draft)
    assert mutations == ["build", "upload"]
    assert command.draft["assets"][0]["digest"] == f"sha256:{digest}"
