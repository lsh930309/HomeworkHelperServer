#!/usr/bin/env python3
"""Reusable SSH operations. Inspect is read-only; mutation is an explicit command."""
from __future__ import annotations

import argparse
import base64
import gzip
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.ssh_host_testbench import SSHConfig, run_remote_powershell

VERIFY_FILES = ("tools/host_operations.py", "tools/ssh_host_testbench.py", "tools/windows_host_probe.py",
                "tools/windows_session_probe.py", "tools/windows_host_operations.ps1", "tests/test_host_operations.py",
                "src/__init__.py", "src/gui/__init__.py", "src/gui/runtime_logging.py")


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


def ps_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def source_state() -> dict:
    branch = git("branch", "--show-current")
    remote = git("ls-remote", "--heads", "origin", f"refs/heads/{branch}") if branch else ""
    return {"branch": branch, "head": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain")),
            "published_head": remote.split()[0] if remote else None}


def remote_script(args, commit: str = "", branch: str = "") -> str:
    script = (ROOT / "tools/windows_host_operations.ps1").read_text(encoding="utf-8")
    values = {
        "Command": args.command, "Repo": args.repo, "Owner": args.owner,
        "ExpectedComputer": args.computer, "Commit": commit, "Branch": branch,
        "Bump": args.bump,
        "LogLines": str(args.log_lines), "Contains": args.contains,
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
    return "& {\n" + script + "\n} " + invocation


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("inspect", "logs", "prepare-source", "build", "install", "desktop", "verify"))
    p.add_argument("--host", required=True)
    p.add_argument("--user")
    p.add_argument("--ssh-port", type=int, default=22)
    p.add_argument("--identity")
    p.add_argument("--repo", required=True, help="Windows build checkout (absolute path)")
    p.add_argument("--owner", default="lsh93")
    p.add_argument("--computer", default="LSH_DESKTOP")
    p.add_argument("--commit", help="Published local HEAD (defaults to current HEAD)")
    p.add_argument("--bump", choices=("build", "patch", "minor", "major", "none"), default="build")
    p.add_argument("--duration", type=int, choices=range(0, 121), default=0,
                   metavar="0..120", help="desktop observation duration; 0 takes one snapshot")
    p.add_argument("--log-lines", type=int, choices=range(1, 2001), default=80, metavar="1..2000")
    p.add_argument("--contains", default="", help="Literal substring filter for recent GUI log lines")
    p.add_argument("--allow-protected-time", action="store_true",
                   help="Use only with the user's explicit authorization for this protected-time installation")
    p.add_argument("--report-root", type=Path, default=ROOT / "artifacts/host-operations")
    return p


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    report = args.report_root / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
    try:
        report.mkdir(parents=True)
        commit, branch = (published_commit(args.commit) if args.command in
                          {"prepare-source", "build", "install"} else ("", ""))
        script = remote_script(args, commit, branch)
        timeout = {"build": 1800, "install": 360, "prepare-source": 120, "verify": 180,
                   "desktop": args.duration + 90, "inspect": 45, "logs": 20}[args.command]
        result = run_remote_powershell(SSHConfig(args.host, args.user, args.ssh_port, args.identity),
                                       script, timeout=timeout)
        (report / "stdout.log").write_text(result.stdout, encoding="utf-8")
        (report / "stderr.log").write_text(result.stderr, encoding="utf-8")
        payload = json.loads(result.stdout) if result.returncode == 0 else None
        summary = {"ok": result.returncode == 0, "command": args.command, "commit": commit or None,
                   "report": str(report), "result": payload}
        if args.command == "inspect":
            summary["local_source"] = source_state()
        (report / "result.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        if result.returncode:
            print(result.stderr.strip(), file=sys.stderr)
        return 0 if result.returncode == 0 else 1
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        message = ("SSH 작업 응답 시간 초과" if isinstance(error, subprocess.TimeoutExpired) else str(error))
        failure = {"ok": False, "command": args.command, "report": str(report), "error": message}
        if report.is_dir():
            (report / "result.json").write_text(json.dumps(failure, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(failure, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
