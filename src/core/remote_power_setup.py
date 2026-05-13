from __future__ import annotations

import getpass
import os
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from src.core.tailscale import _hidden_subprocess_kwargs

_PUBLIC_KEY_RE = re.compile(r"^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521))\s+[A-Za-z0-9+/=]+(?:\s+.*)?$")


def _which_many(names: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    paths: list[str] = []
    for name in names:
        found = shutil.which(name)
        if found and found not in seen:
            paths.append(found)
            seen.add(found)
    return paths


def _is_windows() -> bool:
    return platform.system().lower() == "windows"


def _default_authorized_keys_path() -> Path:
    if _is_windows():
        return Path(os.environ.get("USERPROFILE") or str(Path.home())) / ".ssh" / "authorized_keys"
    return Path.home() / ".ssh" / "authorized_keys"


def _ssh_service_status(runner=None) -> dict[str, Any]:
    if not _is_windows():
        return {"available": False, "running": False, "start_type": "unsupported", "message": "Windows OpenSSH Server 상태는 Windows 호스트에서만 확인합니다."}
    runner = runner or subprocess.run
    kwargs = _hidden_subprocess_kwargs() if runner is subprocess.run else {}
    try:
        result = runner(
            ["powershell", "-NoProfile", "-Command", "Get-Service sshd | Select-Object -Property Status,StartType | ConvertTo-Json -Compress"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            **kwargs,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "running": False, "start_type": "unknown", "message": f"sshd 서비스 확인 실패: {exc}"}
    if result.returncode != 0:
        return {"available": False, "running": False, "start_type": "missing", "message": "OpenSSH Server(sshd)가 설치되어 있지 않거나 서비스 조회에 실패했습니다."}
    output = (result.stdout or "").strip().lower()
    return {
        "available": True,
        "running": "running" in output,
        "start_type": "automatic" if "automatic" in output else "manual" if "manual" in output else "unknown",
        "message": output or "sshd 서비스 상태 확인 완료",
    }


def _firewall_status(runner=None) -> dict[str, Any]:
    if not _is_windows():
        return {"available": False, "enabled": False, "message": "Windows 방화벽 SSH 규칙은 Windows 호스트에서만 확인합니다."}
    runner = runner or subprocess.run
    kwargs = _hidden_subprocess_kwargs() if runner is subprocess.run else {}
    try:
        result = runner(
            ["powershell", "-NoProfile", "-Command", "Get-NetFirewallRule -DisplayName '*OpenSSH*' -ErrorAction SilentlyContinue | Where-Object Enabled -eq True | Select-Object -First 1 -ExpandProperty DisplayName"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
            **kwargs,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "enabled": False, "message": f"방화벽 규칙 확인 실패: {exc}"}
    enabled = result.returncode == 0 and bool((result.stdout or "").strip())
    return {"available": True, "enabled": enabled, "message": (result.stdout or "OpenSSH 방화벽 규칙 없음").strip()}


def smartthings_cli_candidates() -> list[str]:
    names = ["smartthings", "smartthings.exe"]
    candidates = _which_many(names)
    for path in [
        "/opt/homebrew/bin/smartthings",
        "/usr/local/bin/smartthings",
        str(Path.home() / ".npm-global" / "bin" / "smartthings"),
    ]:
        if os.path.exists(path) and path not in candidates:
            candidates.append(path)
    return candidates


def _parse_smartthings_devices(lines: list[str]) -> list[dict[str, str]]:
    devices: list[dict[str, str]] = []
    for line in lines:
        lowered = line.lower()
        if not line or lowered.startswith("id ") or "----" in line or not any(ch.isalnum() for ch in line):
            continue
        parts = line.split()
        if not parts:
            continue
        candidate_id = parts[0]
        if len(candidate_id) < 8 or candidate_id.lower() in {"id", "name", "label"}:
            continue
        name = " ".join(parts[1:]).strip()
        devices.append({"id": candidate_id, "name": name or candidate_id, "raw": line})
    return devices

def list_smartthings_devices(cli_path: str | None = None, runner=None) -> dict[str, Any]:
    cli = cli_path or (smartthings_cli_candidates()[0] if smartthings_cli_candidates() else "")
    if not cli:
        return {"available": False, "devices": [], "message": "SmartThings CLI를 찾지 못했습니다."}
    runner = runner or subprocess.run
    try:
        result = runner([cli, "devices"], capture_output=True, text=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": True, "devices": [], "message": f"SmartThings CLI 실행 실패: {exc}", "cli_path": cli}
    lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    parsed = _parse_smartthings_devices(lines)
    return {"available": True, "devices": lines, "device_candidates": parsed, "message": "SmartThings device 목록 조회 완료" if result.returncode == 0 else (result.stderr or "SmartThings 로그인/권한 확인 필요"), "cli_path": cli}


def power_setup_status() -> dict[str, Any]:
    authorized_keys = _default_authorized_keys_path()
    smartthings = smartthings_cli_candidates()
    return {
        "host_platform": platform.system() or "unknown",
        "user": getpass.getuser(),
        "authorized_keys_path": str(authorized_keys),
        "authorized_keys_exists": authorized_keys.exists(),
        "ssh_service": _ssh_service_status(),
        "firewall": _firewall_status(),
        "smartthings_cli_candidates": smartthings,
        "smartthings_ready": bool(smartthings),
        "message": "전원 관리 준비 상태를 확인했습니다.",
    }


def register_public_key(public_key: str, *, label: str = "HomeworkHelper Remote", authorized_keys_path: Path | None = None) -> dict[str, Any]:
    key = " ".join(public_key.strip().split())
    if not _PUBLIC_KEY_RE.match(key):
        raise ValueError("지원하지 않는 SSH public key 형식입니다.")
    path = authorized_keys_path or _default_authorized_keys_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        current = path.read_text(encoding="utf-8")
    else:
        current = ""
    key_body = " ".join(key.split()[:2])
    for line in current.splitlines():
        if " ".join(line.strip().split()[:2]) == key_body:
            return {"registered": False, "already_present": True, "authorized_keys_path": str(path), "message": "이미 등록된 SSH public key입니다."}
    comment = label.strip() or "HomeworkHelper Remote"
    entry_parts = key.split()[:2] + [comment]
    next_text = current
    if next_text and not next_text.endswith("\n"):
        next_text += "\n"
    next_text += " ".join(entry_parts) + "\n"
    path.write_text(next_text, encoding="utf-8")
    try:
        if not _is_windows():
            path.chmod(0o600)
            path.parent.chmod(0o700)
    except OSError:
        pass
    return {"registered": True, "already_present": False, "authorized_keys_path": str(path), "message": "SSH public key를 authorized_keys에 등록했습니다."}
