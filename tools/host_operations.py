#!/usr/bin/env python3
"""Reusable SSH operations. Inspect is read-only; mutation is an explicit command."""
from __future__ import annotations

import argparse
import base64
import gzip
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
WINDOWS_REPO = r"C:\VSCode\Projects\HomeworkHelperServer"
sys.path.insert(0, str(ROOT))
from tools.ssh_host_testbench import SSHConfig, run_remote_powershell
from tools.version_policy import BuildVersion, VersionLedger, VersionPolicyError

RELEASE_PREFLIGHT_FAILURES = {
    "cli-missing": "Windows에서 GitHub CLI를 찾을 수 없습니다. 병합 전에 호스트의 게시 환경을 준비하세요.",
    "github-auth": "Windows GitHub CLI의 기존 인증을 확인할 수 없습니다.",
    "repository-mismatch": "Windows 작업 저장소의 origin이 릴리즈 대상 저장소와 다릅니다.",
    "github-permission": "Windows GitHub CLI의 릴리즈 대상 저장소 쓰기 권한을 확인할 수 없습니다.",
    "transport": "Windows SSH 연결 또는 릴리즈 사전 점검 응답을 확인할 수 없습니다.",
}

VERIFY_FILES = ("build.py", "tools/host_operations.py", "tools/ssh_host_testbench.py", "tools/windows_host_probe.py",
                "tools/windows_session_probe.py", "tools/windows_host_operations.ps1", "tools/version_policy.py",
                "tests/test_host_operations.py",
                "src/__init__.py", "src/core/__init__.py", "src/core/tailscale.py",
                "src/gui/__init__.py", "src/gui/runtime_logging.py")


def save_preview_images(payload: dict, report: Path) -> None:
    """사용자 세션의 렌더를 보관하고 JSON에 픽셀 데이터를 중복 저장하지 않는다."""
    for item in payload.get("images", ()):
        name = item["name"]
        if Path(name).name != name or not name.endswith(".png") or "\\" in name:
            raise ValueError("검수 이미지 파일명이 올바르지 않습니다.")
        pixels = base64.b64decode(item.pop("base64"), validate=True)
        if not pixels.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("검수 이미지가 PNG가 아닙니다.")
        path = report / name
        path.write_bytes(pixels)
        item["path"] = str(path)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, text=True, encoding="utf-8",
                          errors="strict", capture_output=True, check=True).stdout.strip()


def published_commit(commit: str | None) -> tuple[str, str]:
    """Deploy exactly this clean branch's published HEAD, without implicitly pushing."""
    if git("status", "--porcelain"):
        raise ValueError("작업 트리를 커밋한 뒤 소스 준비·빌드·설치를 실행하세요.")
    branch = git("branch", "--show-current")
    if not branch:
        raise ValueError("배포 소스 브랜치를 선택하세요.")
    head = git("rev-parse", "HEAD")
    if commit and git("rev-parse", f"{commit}^{{commit}}") != head:
        raise ValueError("지정 커밋이 현재 HEAD와 다릅니다.")
    remote = git("ls-remote", "--heads", "origin", f"refs/heads/{branch}")
    if not remote or remote.split()[0] != head:
        raise ValueError("현재 브랜치 HEAD가 origin에 공개되지 않았습니다. 검증·커밋·푸시 후 실행하세요.")
    return head, branch


def published_release_commit(commit: str) -> str:
    """Select a specific public main revision even when local HEAD is elsewhere."""
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("릴리즈에는 main의 전체 커밋 해시가 필요합니다.")
    main = git("ls-remote", "--heads", "origin", "refs/heads/main")
    if not main or commit not in git("rev-list", "--first-parent", main.split()[0]).splitlines():
        raise ValueError("릴리즈 커밋이 공개 main 이력에 없습니다.")
    return commit


def ps_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def source_state() -> dict:
    branch = git("branch", "--show-current")
    remote = git("ls-remote", "--heads", "origin", f"refs/heads/{branch}") if branch else ""
    return {"branch": branch, "head": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain")),
            "published_head": remote.split()[0] if remote else None}


def remote_script(args, commit: str = "", branch: str = "", version: BuildVersion | None = None) -> str:
    script = (ROOT / "tools/windows_host_operations.ps1").read_text(encoding="utf-8")
    values = {
        "Command": args.command, "Repo": WINDOWS_REPO, "Owner": args.owner,
        "ExpectedComputer": args.computer, "Commit": commit, "Branch": branch,
        "VersionSnapshot": version.to_json() if version is not None else "",
        "ReleaseTag": args.release_tag or "", "ReleaseRepo": args.release_repo or "",
        "ArchivedRelease": args.archived_release or "",
        "LogLines": str(args.log_lines), "Contains": args.contains,
        "Scenario": args.scenario,
        "ProbeSource": base64.b64encode(gzip.compress((ROOT / "tools/windows_host_probe.py").read_bytes())).decode(),
        "SessionSource": base64.b64encode(gzip.compress((ROOT / "tools/windows_session_probe.py").read_bytes())).decode(),
    }
    if args.command == "verify":
        values["VerifySource"] = base64.b64encode(gzip.compress(json.dumps({name: (ROOT / name).read_text(encoding="utf-8")
                                                                            for name in VERIFY_FILES}).encode())).decode()
    invocation = " ".join(f"-{key} {ps_literal(value)}" for key, value in values.items())
    invocation += f" -Duration {args.duration}"
    if args.allow_protected_time:
        invocation += " -AllowProtectedTime"
    if args.prepare_runtime:
        invocation += " -PrepareRuntime"
    return "& {\n" + script + "\n} " + invocation


def release_preflight(args: argparse.Namespace) -> int:
    """Expose only a known outcome, never SSH or GitHub authentication output."""
    reason = "transport"
    try:
        result = run_remote_powershell(SSHConfig(args.host, args.user, args.ssh_port, args.identity),
                                       remote_script(args), timeout=45)
        if result.returncode == 0:
            payload = json.loads(result.stdout)
            if isinstance(payload, dict) and payload.get("ok") is True:
                print('{"ok": true}')
                return 0
            if isinstance(payload, dict) and payload.get("ok") is False:
                reported = payload.get("reason")
                if isinstance(reported, str) and reported in RELEASE_PREFLIGHT_FAILURES:
                    reason = reported
    except (ValueError, OSError, subprocess.SubprocessError):
        pass
    print(json.dumps({"ok": False, "reason": reason}))
    return 1


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    p.add_argument("command", choices=("inspect", "logs", "prepare-source", "build", "release-preflight", "release-build", "install", "desktop", "verify", "media-qa"))
    p.add_argument("--host", required=True, help="Tailscale device/MagicDNS name, explicit IP or external FQDN")
    p.add_argument("--user")
    p.add_argument("--ssh-port", type=int, default=22)
    p.add_argument("--identity")
    p.add_argument("--owner", default="lsh93")
    p.add_argument("--computer", default="LSH_DESKTOP")
    p.add_argument("--commit", help="Published local HEAD (defaults to current HEAD)")
    p.add_argument("--archived-release", help="install only: reinstall this exact release from build.py archives")
    p.add_argument("--release-tag", help="release-build only: tag of the existing draft release")
    p.add_argument("--release-repo", help="release-preflight and release-build only: owner/repository of the release")
    p.add_argument("--duration", type=int, choices=range(0, 121), default=0,
                   metavar="0..120", help="desktop observation duration; 0 takes one snapshot")
    p.add_argument("--log-lines", type=int, choices=range(1, 2001), default=80, metavar="1..2000")
    p.add_argument("--contains", default="", help="Literal substring filter for recent GUI log lines")
    p.add_argument("--scenario", choices=("observe", "preview", "audio", "focus", "focus-compare", "focus-uia", "focus-lifecycle", "bgm", "prepare-spotify", "triggers", "firefox", "spotify-window-observe", "spotify-window-open", "spotify-window-minimize", "spotify-window-close", "spotify-window-startup", "spotify-window-startup-close", "spotify-window-startup-delayed-close"), default="observe",
                   help="media-qa only: explicit native verification scenario")
    p.add_argument("--prepare-runtime", action="store_true",
                   help="media-qa only: install declared requirements in the canonical Windows venv")
    p.add_argument("--allow-protected-time", action="store_true",
                   help="Use only with the user's explicit authorization for this protected-time installation")
    p.add_argument("--report-root", type=Path, default=ROOT / "artifacts/host-operations")
    return p


def main(argv=None) -> int:
    argument_parser = parser()
    args = argument_parser.parse_args(argv)
    if args.prepare_runtime and args.command != "media-qa":
        argument_parser.error("--prepare-runtime은 media-qa에서만 사용할 수 있습니다.")
    if args.archived_release and (args.command != "install" or args.commit):
        argument_parser.error("--archived-release는 install에서만 사용하며 --commit과 함께 지정하지 않습니다.")
    if args.command == "release-build":
        if not (args.commit and args.release_tag and args.release_repo):
            argument_parser.error("release-build에는 --commit, --release-tag, --release-repo가 필요합니다.")
    elif args.command == "release-preflight":
        if not args.release_repo or args.commit or args.release_tag:
            argument_parser.error("release-preflight에는 --release-repo만 지정하세요. 커밋과 태그는 필요하지 않습니다.")
    elif args.release_tag or args.release_repo:
        argument_parser.error("--release-tag는 release-build, --release-repo는 release-preflight와 release-build에서 사용합니다.")
    if args.release_repo and not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.release_repo):
        argument_parser.error("--release-repo는 owner/repository 형식이어야 합니다.")
    if args.command == "release-preflight":
        return release_preflight(args)
    report = args.report_root / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    try:
        report.mkdir(parents=True)
        version = None
        if args.command == "release-build":
            commit, branch = published_release_commit(args.commit), "main"
            event, version = VersionLedger(ROOT).read_main(commit) or (None, None)
            if (event not in {"minor", "major"} or version is None or version.product != "host"
                    or args.release_tag != version.tag):
                raise ValueError("공개 호스트 릴리즈에 발급된 정식 버전과 태그가 필요합니다.")
        else:
            commit, branch = (published_commit(args.commit) if args.command in
                              {"prepare-source", "build", "install", "media-qa"} and not args.archived_release else ("", ""))
            if commit and args.command in {"prepare-source", "build", "install"}:
                version = VersionLedger(ROOT).resolve_build("host", commit, development=branch != "main")
        script = remote_script(args, commit, branch, version)
        timeout = {"build": 1800, "release-build": 2400, "install": 360, "prepare-source": 120, "verify": 180,
                   "desktop": args.duration + 90,
                   "media-qa": 360 if args.prepare_runtime else (190 if args.scenario == "focus-lifecycle" else 180),
                   "inspect": 45, "logs": 20}[args.command]
        result = run_remote_powershell(SSHConfig(args.host, args.user, args.ssh_port, args.identity),
                                       script, timeout=timeout)
        stdout = result.stdout
        payload = None
        try:
            if result.returncode == 0:
                payload = json.loads(stdout)
                if not isinstance(payload, dict):
                    raise ValueError("원격 작업 응답이 JSON 객체가 아닙니다.")
                if args.command == "media-qa":
                    save_preview_images(payload, report)
                    stdout = json.dumps(payload, ensure_ascii=False)
        finally:
            # 해석 실패 때는 원격 출력을 보존하고, 성공한 미디어 응답의 PNG는 한 번만 저장한다.
            (report / "stdout.log").write_text(stdout, encoding="utf-8")
            (report / "stderr.log").write_text(result.stderr, encoding="utf-8")
        native_ok = (payload.get("ok", False) if args.command == "media-qa" and payload is not None else True)
        summary = {"ok": result.returncode == 0 and native_ok, "command": args.command, "commit": commit or None,
                   "report": str(report), "result": payload}
        if args.command == "inspect":
            summary["local_source"] = source_state()
        (report / "result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        if result.returncode:
            print(result.stderr.strip(), file=sys.stderr)
        return 0 if summary["ok"] else 1
    except (ValueError, OSError, subprocess.SubprocessError, VersionPolicyError) as error:
        message = ("SSH 작업 응답 시간 초과" if isinstance(error, subprocess.TimeoutExpired) else str(error))
        failure = {"ok": False, "command": args.command, "report": str(report), "error": message}
        if report.is_dir():
            if isinstance(error, subprocess.TimeoutExpired):
                # TimeoutExpired may contain bytes even when subprocess uses text mode.
                # Keep incomplete UTF-8 bytes as received instead of replacing or losing them.
                for filename, captured in (("stdout.log", error.stdout), ("stderr.log", error.stderr)):
                    (report / filename).write_bytes(
                        captured.encode("utf-8") if isinstance(captured, str) else captured or b""
                    )
            (report / "result.json").write_text(json.dumps(failure, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(failure, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
