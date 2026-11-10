#!/usr/bin/env python3
"""Merge a reviewed PR on the Mac and publish its product release."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import platform
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.validate_commit_message import validate_message
from tools.version_policy import BuildVersion, START_TAGS, START_VERSIONS, VersionLedger, changed_products, validate_commit_range


MAIN = "refs/remotes/origin/main"
PR_FIELDS = "baseRefName,headRefOid,mergeCommit,state,title,body,url,headRefName,isDraft"
RELEASE_FIELDS = "assets,body,isDraft,tagName,name,url"
SHA = re.compile(r"[0-9a-f]{40}")
DIGEST = re.compile(r"[0-9a-f]{64}")
TRAILER = re.compile(r"^HomeworkHelper-Release: PR #(\d+) (host|client|none) (minor|major)$", re.M)
ORIGIN = re.compile(r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([\w.-]+/[\w.-]+?)(?:\.git)?/?")


@dataclass(frozen=True)
class MergeRelease:
    number: int
    product: str | None
    event: str

    @property
    def trailer(self) -> str:
        return f"HomeworkHelper-Release: PR #{self.number} {self.product or 'none'} {self.event}"


def release_assets(version: BuildVersion) -> tuple[str, ...]:
    from build import macos_pkg_path, make_policy_version_info, windows_package_paths

    info = make_policy_version_info(version)
    if version.product == "host":
        return tuple(path.name for path in windows_package_paths(info))
    return (macos_pkg_path(info).name,)


def release_title(version: BuildVersion) -> str:
    name = "HomeworkHelper Host" if version.product == "host" else "HomeworkHelper Remote"
    return f"{name} v {version.version}"


def release_source(pr: dict, version: BuildVersion) -> str:
    return f"- 병합 PR: {pr['url']}\n- 병합 브랜치: `{pr['headRefName']}`\n- 병합 커밋: `{version.commit}`"


def release_notes(pr: dict, version: BuildVersion) -> str:
    return f"## {pr['title']}\n\n{(pr['body'] or '').strip()}\n\n{release_source(pr, version)}\n"


def asset_hashes(release: dict, version: BuildVersion) -> dict[str, str]:
    assets = {}
    for asset in release["assets"]:
        name = asset["name"]
        digest = asset.get("digest") or ""
        if (name in assets or asset["state"] != "uploaded" or asset["size"] <= 0
                or not digest.startswith("sha256:") or not DIGEST.fullmatch(digest[7:])):
            raise ValueError(f"업로드된 자산의 상태 또는 SHA-256이 올바르지 않습니다: {name}")
        assets[name] = digest[7:]
    if assets.keys() != set(release_assets(version)):
        raise ValueError("GitHub에 등록된 릴리즈 자산이 이 제품의 필수 패키지와 다릅니다.")
    return assets


class ReleaseCommand:
    def __init__(self, repo: Path):
        self.repo = repo
        self.ledger = VersionLedger(repo)
        fetch = ORIGIN.fullmatch(self.git("remote", "get-url", "origin"))
        push = ORIGIN.fullmatch(self.git("remote", "get-url", "--push", "origin"))
        if not fetch or not push or fetch[1].lower() != push[1].lower():
            raise ValueError("origin fetch와 push 주소가 같은 GitHub 저장소여야 합니다.")
        self.github_repo = fetch[1]

    def run(self, *args: str, stdin: str | None = None, timeout: int = 120) -> subprocess.CompletedProcess:
        return subprocess.run(args, cwd=self.repo, text=True, encoding="utf-8", input=stdin,
                              capture_output=True, timeout=timeout)

    @staticmethod
    def output(result: subprocess.CompletedProcess) -> str:
        if result.returncode:
            message = (result.stderr or result.stdout).strip()
            raise RuntimeError(message or f"{result.args[0]} 명령 실패 (종료 코드 {result.returncode})")
        return result.stdout.strip()

    def git(self, *args: str) -> str:
        return self.output(self.run("git", *args))

    def gh(self, *args: str, stdin: str | None = None) -> str:
        return self.output(self.run("gh", *args, "--repo", f"github.com/{self.github_repo}", stdin=stdin))

    def refresh_main(self) -> str:
        self.git("fetch", "--no-tags", "origin", f"refs/heads/main:{MAIN}")
        return self.git("rev-parse", MAIN)

    def require_clean(self) -> None:
        if self.git("status", "--porcelain"):
            raise ValueError("깨끗한 맥 작업 트리에서 릴리즈 명령을 실행하세요.")

    def require_main_checkout(self, published: str) -> None:
        if self.git("branch", "--show-current") != "main":
            raise ValueError("맥의 main checkout에서 실행하세요.")
        self.git("merge-base", "--is-ancestor", "HEAD", published)

    def product_tags(self) -> dict[str, str]:
        refs = {}
        peeled = {}
        for line in self.git("ls-remote", "--tags", "origin", "refs/tags/H/v*", "refs/tags/C/v*").splitlines():
            sha, ref = line.split("\t", 1)
            tag = ref.removeprefix("refs/tags/")
            if tag.endswith("^{}"):
                peeled[tag[:-3]] = sha
            else:
                refs[tag] = sha
        return refs | peeled

    def refresh_baseline(self) -> str:
        self.git("fetch", "--no-tags", "origin", "refs/tags/H/v*:refs/tags/H/v*", "refs/tags/C/v*:refs/tags/C/v*")
        return self.ledger.require_baseline()

    def bootstrap(self, commit: str, *, dry_run: bool) -> None:
        self.require_clean()
        published = self.refresh_main()
        self.require_main_checkout(published)
        if commit != published or self.git("rev-parse", "HEAD") != commit:
            raise ValueError("시작 태그에는 로컬과 GitHub main이 가리키는 동일한 전체 커밋 SHA를 지정하세요.")
        try:
            for product, version in START_VERSIONS.items():
                release_assets(BuildVersion(product, version, commit, version))
        except ImportError as error:
            raise ValueError("두 제품의 새 버전 빌드를 main에 반영한 뒤 시작 태그를 등록하세요.") from error
        tags = self.product_tags()
        expected = set(START_TAGS.values())
        existing = {tag for tag, target in tags.items() if target == commit}
        if (tags and set(tags) != expected) or any(
            tag in tags and tags[tag] != commit for tag in expected
        ):
            raise ValueError("다른 제품 태그가 이미 있습니다. 새 시작 태그를 만들 수 없습니다.")
        if not dry_run:
            if not existing:
                self.git("push", "--atomic", "origin", *(f"{commit}:refs/tags/{tag}" for tag in sorted(expected)))
            self.refresh_baseline()
        print(f"{commit} {' '.join(sorted(expected))}{' (미리보기)' if dry_run else ''}")

    def pr(self, number: int) -> dict:
        pr = json.loads(self.gh("pr", "view", str(number), "--json", PR_FIELDS))
        if pr["baseRefName"] != "main":
            raise ValueError("main을 대상으로 하는 PR만 이 명령으로 병합할 수 있습니다.")
        return pr

    def preflight(self, args: argparse.Namespace, pr: dict, published: str) -> MergeRelease:
        self.require_main_checkout(published)
        if pr["isDraft"] or pr["state"] != "OPEN":
            raise ValueError("검토가 끝난 열린 PR을 지정하세요.")
        self.ledger.check_main_ready(published)
        self.git("fetch", "--no-tags", "origin", f"refs/pull/{args.number}/head")
        if self.git("rev-parse", "FETCH_HEAD") != args.head:
            raise ValueError("검토한 PR head와 가져온 소스가 다릅니다.")
        branch_base = self.git("merge-base", published, args.head)
        validate_commit_range(self.repo, published, args.head)
        branch_products = changed_products(self.repo, branch_base, args.head)
        result = self.run("git", "merge-tree", "--write-tree", "--no-messages", published, args.head)
        if result.returncode:
            raise ValueError("현재 main과 PR을 자동으로 병합할 수 없습니다.")
        products = changed_products(self.repo, published, self.output(result))
        if len(branch_products | products) > 1:
            raise ValueError("호스트와 클라이언트가 함께 바뀌는 PR은 제품별로 분리하세요.")
        product = next(iter(products), None)
        if product == "host" and not args.host:
            raise ValueError("호스트 릴리즈를 준비하려면 --host를 지정하세요.")
        if args.approved_major and not product:
            raise ValueError("메이저 승격은 제품 변경이 있는 PR에만 적용됩니다.")
        return MergeRelease(args.number, product, "major" if args.approved_major else "minor")

    def require_merge_access(self, args: argparse.Namespace, product: str | None) -> None:
        error = "맥 GitHub CLI의 인증과 대상 저장소 쓰기 권한을 확인할 수 없습니다."
        try:
            repository = json.loads(self.gh("repo", "view", "--json", "viewerPermission"))
        except (ValueError, RuntimeError, OSError, subprocess.SubprocessError):
            raise ValueError(error) from None
        if not isinstance(repository, dict) or repository.get("viewerPermission") not in ("WRITE", "MAINTAIN", "ADMIN"):
            raise ValueError(error)
        if product != "host":
            return

        from tools.host_operations import RELEASE_PREFLIGHT_FAILURES

        reason = "transport"
        try:
            result = self.run_host(args, "release-preflight", "--release-repo", self.github_repo, timeout=60)
            response = json.loads(result.stdout)
            if result.returncode == 0 and isinstance(response, dict) and response.get("ok") is True:
                return
            if isinstance(response, dict) and response.get("ok") is False:
                reported = response.get("reason")
                if isinstance(reported, str) and reported in RELEASE_PREFLIGHT_FAILURES:
                    reason = reported
        except (ValueError, OSError, subprocess.SubprocessError):
            pass
        raise ValueError(RELEASE_PREFLIGHT_FAILURES[reason])

    def merge(self, args: argparse.Namespace, event: MergeRelease) -> None:
        if not args.message_file:
            raise ValueError("새 병합에는 검토한 커밋 메시지 --message-file이 필요합니다.")
        message = args.message_file.read_text(encoding="utf-8")
        errors = validate_message(message)
        if errors:
            raise ValueError("\n".join(errors))
        if "HomeworkHelper-Release:" in message:
            raise ValueError("릴리즈 표시는 병합 명령이 자동으로 붙입니다.")
        subject, _, body = message.strip().partition("\n")
        self.require_merge_access(args, event.product)
        self.gh("pr", "merge", str(args.number), "--merge", "--match-head-commit", args.head,
                "--subject", subject, "--body-file", "-", stdin=f"{body.strip()}\n\n{event.trailer}\n")

    def merged_event(self, args: argparse.Namespace, pr: dict, published: str) -> tuple[str, str | None, str]:
        commit = (pr["mergeCommit"] or {}).get("oid", "")
        if pr["state"] != "MERGED" or not SHA.fullmatch(commit):
            raise ValueError("PR 병합 완료가 확인되지 않았습니다. 상태를 확인한 뒤 같은 명령을 재실행하세요.")
        parents = self.git("show", "-s", "--format=%P", commit).split()
        if len(parents) != 2 or parents[1] != args.head:
            raise ValueError("검토한 PR head와 main에 병합된 커밋의 부모가 다릅니다.")
        if commit not in self.git("rev-list", "--first-parent", published, "--not", parents[0]).splitlines():
            raise ValueError("GitHub main의 첫 부모 이력에서 병합 커밋을 찾을 수 없습니다.")
        markers = TRAILER.findall(self.git("show", "-s", "--format=%B", commit))
        if len(markers) != 1 or markers[0][0] != str(args.number):
            raise ValueError("이 명령에서 시작한 PR 병합을 찾을 수 없습니다.")
        _, expected, event = markers[0]
        if args.approved_major and event != "major":
            raise ValueError("이미 마이너로 병합된 PR을 메이저로 변경할 수 없습니다.")
        products = changed_products(self.repo, parents[0], commit)
        if products and products != {expected}:
            raise ValueError("병합 뒤 main에서 실제 변경된 제품이 검토한 제품과 다릅니다.")
        return commit, next(iter(products), None), event

    def ensure_tag(self, version: BuildVersion, *, create: bool) -> None:
        tags = self.product_tags()
        if tags.get(version.tag, version.commit) != version.commit or any(
            tag != version.tag and target == version.commit for tag, target in tags.items()
        ):
            raise ValueError("병합 커밋에 이미 다른 정식 태그가 있거나 태그가 다른 커밋을 가리킵니다.")
        if version.tag not in tags:
            if not create:
                raise ValueError("GitHub 릴리즈 태그를 다시 확인할 수 없습니다.")
            self.git("push", "origin", f"{version.commit}:refs/tags/{version.tag}")

    def release(self, tag: str) -> dict | None:
        result = self.run("gh", "release", "view", tag, "--json", RELEASE_FIELDS,
                          "--repo", f"github.com/{self.github_repo}")
        if result.returncode and result.stderr.strip() == "release not found":
            return None
        return json.loads(self.output(result))

    def run_host(self, args: argparse.Namespace, command: str, *options: str,
                 timeout: int) -> subprocess.CompletedProcess:
        if not args.host:
            raise ValueError("호스트 빌드·첨부를 재개하려면 --host를 지정하세요.")
        argv = [sys.executable, "tools/host_operations.py", command, "--host", args.host,
                *options, "--ssh-port", str(args.ssh_port)]
        if args.user:
            argv.extend(["--user", args.user])
        if args.identity:
            argv.extend(["--identity", args.identity])
        return self.run(*argv, timeout=timeout)

    def upload_host(self, args: argparse.Namespace, version: BuildVersion) -> dict[str, str]:
        result = self.run_host(args, "release-build", "--commit", version.commit, "--release-tag", version.tag,
                               "--release-repo", self.github_repo, timeout=2460)
        payload = json.loads(self.output(result))
        if not payload["ok"] or payload["commit"] != version.commit:
            raise ValueError("Windows 빌드의 대상 커밋 또는 결과를 확인할 수 없습니다.")
        return payload["result"]["assets"]

    def upload_client(self, version: BuildVersion, draft: dict) -> dict[str, str]:
        from build import sha256_file

        branch = self.git("branch", "--show-current")
        head = self.git("rev-parse", "HEAD")
        if branch == "main" and head != version.commit:
            if self.run("git", "merge-base", "--is-ancestor", head, version.commit).returncode:
                raise ValueError("릴리즈 커밋의 깨끗한 detached checkout에서 같은 명령을 재실행하세요.")
            self.git("merge", "--ff-only", version.commit)
        self.require_clean()
        if branch not in {"main", ""} or self.git("rev-parse", "HEAD") != version.commit:
            raise ValueError("릴리즈 커밋과 맥 패키지의 checkout이 일치해야 합니다.")
        name, = release_assets(version)
        path = self.repo / "release" / name
        if not draft["assets"]:
            self.output(self.run(sys.executable, "build.py", "--no-prune-archives", timeout=1800))
        if not path.is_file() or path.is_symlink() or path.stat().st_size <= 0:
            raise ValueError(f"release/{name}의 기존 PKG를 확인한 뒤 다시 실행하세요.")
        expected = {name: sha256_file(path)}
        current = draft if draft["assets"] else self.release(version.tag)
        if not current:
            raise ValueError("맥 패키지를 첨부할 draft 릴리즈를 찾을 수 없습니다.")
        if current["assets"]:
            if asset_hashes(current, version) != expected:
                raise ValueError("첨부된 PKG와 로컬 PKG의 SHA-256이 다릅니다. 기존 PKG를 확인한 뒤 다시 실행하세요.")
        elif not current["isDraft"]:
            raise ValueError("맥 패키지는 현재 draft 릴리즈에만 첨부할 수 있습니다.")
        else:
            self.gh("release", "upload", version.tag, str(path))
        return expected

    def verify_release(self, release: dict | None, pr: dict, version: BuildVersion) -> dict:
        if (not release or release["tagName"] != version.tag
                or release["name"] != release_title(version)
                or release_source(pr, version) not in (release["body"] or "")):
            raise ValueError("GitHub 릴리즈의 태그·제목·원본 PR을 확인할 수 없습니다.")
        return release

    def publish(self, args: argparse.Namespace, pr: dict, version: BuildVersion) -> None:
        self.ensure_tag(version, create=True)
        release = self.release(version.tag)
        if release is None:
            self.gh("release", "create", version.tag, "--verify-tag", "--target", version.commit,
                    "--draft", "--title", release_title(version), "--notes-file", "-",
                    stdin=release_notes(pr, version))
            release = self.release(version.tag)
        release = self.verify_release(release, pr, version)
        if not release["isDraft"]:
            asset_hashes(release, version)
            print(release["url"])
            return
        hashes = self.upload_host(args, version) if version.product == "host" else self.upload_client(version, release)
        release = self.verify_release(self.release(version.tag), pr, version)
        if asset_hashes(release, version) != hashes:
            raise ValueError("빌드한 패키지의 SHA-256이 GitHub 업로드 자산과 다릅니다.")
        self.ensure_tag(version, create=False)
        if release["isDraft"]:
            self.gh("release", "edit", version.tag, "--draft=false", "--verify-tag")
        published = self.verify_release(self.release(version.tag), pr, version)
        if published["isDraft"] or asset_hashes(published, version) != hashes:
            raise ValueError("GitHub에서 실제 게시 결과를 확인할 수 없습니다.")
        print(published["url"])

    def run_pr(self, args: argparse.Namespace) -> None:
        self.require_clean()
        published = self.refresh_main()
        baseline = self.refresh_baseline()
        pr = self.pr(args.number)
        if pr["state"] != "MERGED":
            if pr["headRefOid"] != args.head:
                raise ValueError("현재 PR head가 검토한 SHA와 다릅니다.")
            event = self.preflight(args, pr, published)
            if args.dry_run:
                print(event.trailer)
                return
            self.merge(args, event)
            pr = self.pr(args.number)
            published = self.refresh_main()
        commit, product, event = self.merged_event(args, pr, published)
        self.git("merge-base", "--is-ancestor", baseline, commit)
        if commit == baseline:
            raise ValueError("버전 정책 시작 커밋 이전 PR은 릴리즈하지 않습니다.")
        if args.dry_run:
            print(f"{commit} {product or '제품 변경 없음'} {event}")
            return
        version = self.ledger.record_main(commit, event=event, expected_product=product,
                                          major_approved=event == "major")
        if version is None:
            print(f"#{args.number} 병합 완료 (패키지 변경 없음)")
            return
        self.publish(args, pr, version)


def full_sha(value: str) -> str:
    if not SHA.fullmatch(value):
        raise argparse.ArgumentTypeError("검토한 전체 Git 커밋 SHA(40자리)가 필요합니다.")
    return value


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    commands = p.add_subparsers(dest="command", required=True)
    merge = commands.add_parser("merge", allow_abbrev=False)
    merge.add_argument("number", type=int)
    merge.add_argument("--head", required=True, type=full_sha)
    merge.add_argument("--message-file", type=Path)
    merge.add_argument("--approved-major", action="store_true")
    merge.add_argument("--host")
    merge.add_argument("--user")
    merge.add_argument("--identity")
    merge.add_argument("--ssh-port", type=int, default=22)
    merge.add_argument("--dry-run", action="store_true")
    bootstrap = commands.add_parser("bootstrap", allow_abbrev=False)
    bootstrap.add_argument("--commit", required=True, type=full_sha)
    bootstrap.add_argument("--dry-run", action="store_true")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if platform.system() != "Darwin":
            raise ValueError("버전 권위를 가진 맥에서 이 명령을 실행하세요.")
        command = ReleaseCommand(ROOT)
        if args.command == "bootstrap":
            command.bootstrap(args.commit, dry_run=args.dry_run)
        else:
            if args.number <= 0:
                raise ValueError("양의 PR 번호가 필요합니다.")
            command.run_pr(args)
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        print(f"릴리즈 작업 실패: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
