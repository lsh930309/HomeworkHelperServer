from __future__ import annotations

import getpass
import json
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


def _programdata_ssh_dir() -> Path:
    return Path(os.environ.get("PROGRAMDATA") or r"C:\ProgramData") / "ssh"


def _default_user_authorized_keys_path() -> Path:
    if _is_windows():
        return Path(os.environ.get("USERPROFILE") or str(Path.home())) / ".ssh" / "authorized_keys"
    return Path.home() / ".ssh" / "authorized_keys"


def _default_admin_authorized_keys_path() -> Path:
    return _programdata_ssh_dir() / "administrators_authorized_keys"


def _sshd_config_path() -> Path:
    if _is_windows():
        return _programdata_ssh_dir() / "sshd_config"
    return Path("/etc/ssh/sshd_config")


def _default_authorized_keys_path() -> Path:
    return _effective_authorized_keys_target()["path"]


def _runner_kwargs(runner) -> dict[str, Any]:
    return _hidden_subprocess_kwargs() if runner is subprocess.run else {}


def _run_probe(command: list[str], *, runner=None, timeout: int = 5):
    runner = runner or subprocess.run
    return runner(command, capture_output=True, text=True, timeout=timeout, check=False, **_runner_kwargs(runner))


def _current_user_is_windows_admin(runner=None) -> tuple[bool, str]:
    if not _is_windows():
        return (False, "not_windows")
    try:
        result = _run_probe(["whoami", "/groups"], runner=runner, timeout=5)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return (False, f"admin group 확인 실패: {exc}")
    output = ((result.stdout or "") + "\n" + (result.stderr or "")).lower()
    if result.returncode != 0:
        return (False, output.strip() or "admin group 확인 실패")
    is_admin = "s-1-5-32-544" in output or "builtin\\administrators" in output or "administrators" in output
    return (is_admin, "Administrators group" if is_admin else "not Administrators group")


def _sshd_config_admin_match_enabled(config_path: Path | None = None) -> bool:
    if not _is_windows():
        return False
    path = config_path or _sshd_config_path()
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return False
    in_admin_match = False
    for raw in lines:
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        lowered = line.lower()
        if lowered.startswith("match "):
            in_admin_match = "group" in lowered and "administrators" in lowered
            continue
        if in_admin_match and lowered.startswith("authorizedkeysfile"):
            return "administrators_authorized_keys" in lowered and "__programdata__" in lowered
    return False


def _effective_authorized_keys_target(*, runner=None) -> dict[str, Any]:
    user_path = _default_user_authorized_keys_path()
    admin_path = _default_admin_authorized_keys_path()
    admin_user, admin_message = _current_user_is_windows_admin(runner=runner)
    admin_match = _sshd_config_admin_match_enabled()
    admin_active = bool(_is_windows() and admin_user and admin_match)
    path = admin_path if admin_active else user_path
    return {
        "path": path,
        "scope": "administrators" if admin_active else "user",
        "user_authorized_keys_path": user_path,
        "admin_authorized_keys_path": admin_path,
        "sshd_config_path": _sshd_config_path(),
        "current_user_is_admin": bool(admin_user),
        "current_user_admin_message": admin_message,
        "sshd_config_admin_match": bool(admin_match),
        "administrators_authorized_keys_active": admin_active,
    }


def _repair_admin_authorized_keys_acl(path: Path, *, runner=None) -> dict[str, Any]:
    if not _is_windows() or path != _default_admin_authorized_keys_path():
        return {"attempted": False, "ok": True, "message": "ACL 보정 불필요"}
    try:
        result = _run_probe(
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                "*S-1-5-18:F",
                "*S-1-5-32-544:F",
            ],
            runner=runner,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"attempted": True, "ok": False, "message": f"administrators_authorized_keys ACL 보정 실패: {exc}"}
    output = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    return {
        "attempted": True,
        "ok": result.returncode == 0,
        "message": output or ("ACL 보정 완료" if result.returncode == 0 else "ACL 보정 실패"),
    }


def _ssh_service_status(runner=None) -> dict[str, Any]:
    if not _is_windows():
        return {"available": False, "running": False, "start_type": "unsupported", "message": "Windows OpenSSH Server 상태는 Windows 호스트에서만 확인합니다."}
    try:
        result = _run_probe(
            ["powershell", "-NoProfile", "-Command", "Get-Service sshd | Select-Object -Property Status,StartType | ConvertTo-Json -Compress"],
            runner=runner,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "running": False, "start_type": "unknown", "message": f"sshd 서비스 확인 실패: {exc}"}
    if result.returncode != 0:
        return {"available": False, "running": False, "start_type": "missing", "message": "OpenSSH Server(sshd)가 설치되어 있지 않거나 서비스 조회에 실패했습니다."}
    raw_output = (result.stdout or "").strip()
    try:
        payload = json.loads(raw_output)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        status_value = str(payload.get("Status") or payload.get("status") or "").lower()
        start_value = str(payload.get("StartType") or payload.get("starttype") or payload.get("StartType".lower()) or "").lower()
        running = status_value in {"4", "running"}
        start_type = "automatic" if start_value in {"2", "automatic"} else "manual" if start_value in {"3", "manual"} else "disabled" if start_value in {"4", "disabled"} else "unknown"
        return {
            "available": True,
            "running": running,
            "start_type": start_type,
            "message": f"sshd status={status_value or 'unknown'} start_type={start_value or 'unknown'}",
        }
    output = raw_output.lower()
    return {
        "available": True,
        "running": "running" in output,
        "start_type": "automatic" if "automatic" in output else "manual" if "manual" in output else "unknown",
        "message": output or "sshd 서비스 상태 확인 완료",
    }


def _firewall_status(runner=None) -> dict[str, Any]:
    if not _is_windows():
        return {"available": False, "enabled": False, "message": "Windows 방화벽 SSH 규칙은 Windows 호스트에서만 확인합니다."}
    try:
        result = _run_probe(
            ["powershell", "-NoProfile", "-Command", "Get-NetFirewallRule -DisplayName '*OpenSSH*' -ErrorAction SilentlyContinue | Where-Object Enabled -eq True | Select-Object -First 1 -ExpandProperty DisplayName"],
            runner=runner,
            timeout=5,
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
    joined = "\n".join(lines).strip()
    if joined.startswith("["):
        try:
            payload = json.loads(joined)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, list):
            devices: list[dict[str, str]] = []
            for item in payload:
                if not isinstance(item, dict):
                    continue
                device_id = str(item.get("deviceId") or item.get("id") or "").strip()
                if not device_id:
                    continue
                name = str(item.get("label") or item.get("name") or device_id).strip()
                devices.append({"id": device_id, "name": name, "raw": json.dumps(item, ensure_ascii=False, sort_keys=True)})
            return devices

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
        return {"available": False, "devices": [], "device_candidates": [], "message": "SmartThings CLI를 찾지 못했습니다.", "cli_path": None}
    runner = runner or subprocess.run
    kwargs = _hidden_subprocess_kwargs() if runner is subprocess.run else {}
    try:
        result = runner([cli, "devices"], capture_output=True, text=True, timeout=10, check=False, **kwargs)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "devices": [], "device_candidates": [], "message": f"SmartThings CLI 실행 실패: {exc}", "cli_path": cli, "error": str(exc)}
    lines = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    parsed = _parse_smartthings_devices(lines)
    ok = result.returncode == 0
    stderr = (result.stderr or "").strip()
    return {
        "available": ok,
        "devices": lines,
        "device_candidates": parsed if ok else [],
        "message": "SmartThings device 목록 조회 완료" if ok else (stderr or "SmartThings 로그인/권한 확인 필요"),
        "cli_path": cli,
        "return_code": result.returncode,
        "stderr": stderr,
        "stdout_line_count": len(lines),
    }


def power_setup_status(runner=None) -> dict[str, Any]:
    target = _effective_authorized_keys_target(runner=runner)
    authorized_keys = target["path"]
    smartthings = smartthings_cli_candidates()
    return {
        "host_platform": platform.system() or "unknown",
        "user": getpass.getuser(),
        "authorized_keys_path": str(authorized_keys),
        "authorized_keys_exists": authorized_keys.exists(),
        "effective_authorized_keys_path": str(authorized_keys),
        "authorized_keys_scope": target["scope"],
        "user_authorized_keys_path": str(target["user_authorized_keys_path"]),
        "user_authorized_keys_exists": target["user_authorized_keys_path"].exists(),
        "admin_authorized_keys_path": str(target["admin_authorized_keys_path"]),
        "admin_authorized_keys_exists": target["admin_authorized_keys_path"].exists(),
        "sshd_config_path": str(target["sshd_config_path"]),
        "sshd_config_admin_match": target["sshd_config_admin_match"],
        "current_user_is_admin": target["current_user_is_admin"],
        "current_user_admin_message": target["current_user_admin_message"],
        "administrators_authorized_keys_active": target["administrators_authorized_keys_active"],
        "ssh_service": _ssh_service_status(runner=runner),
        "firewall": _firewall_status(runner=runner),
        "smartthings_cli_candidates": smartthings,
        "smartthings_ready": bool(smartthings),
        "message": "전원 관리 준비 상태를 확인했습니다.",
    }


def register_public_key(public_key: str, *, label: str = "HomeworkHelper Remote", authorized_keys_path: Path | None = None, runner=None) -> dict[str, Any]:
    key = " ".join(public_key.strip().split())
    if not _PUBLIC_KEY_RE.match(key):
        raise ValueError("지원하지 않는 SSH public key 형식입니다.")
    target = _effective_authorized_keys_target(runner=runner)
    path = authorized_keys_path or target["path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        current = path.read_text(encoding="utf-8")
    else:
        current = ""
    key_body = " ".join(key.split()[:2])
    for line in current.splitlines():
        if " ".join(line.strip().split()[:2]) == key_body:
            acl = _repair_admin_authorized_keys_acl(path, runner=runner)
            return {
                "registered": False,
                "already_present": True,
                "authorized_keys_path": str(path),
                "effective_authorized_keys_path": str(path),
                "authorized_keys_scope": target["scope"],
                "administrators_authorized_keys_active": target["administrators_authorized_keys_active"],
                "acl_repair_attempted": acl["attempted"],
                "acl_repair_ok": acl["ok"],
                "acl_message": acl["message"],
                "message": "이미 등록된 SSH public key입니다." if acl["ok"] else "SSH public key는 이미 있지만 administrators_authorized_keys ACL 보정이 필요합니다.",
            }
    comment = label.strip() or "HomeworkHelper Remote"
    entry_parts = key.split()[:2] + [comment]
    next_text = current
    if next_text and not next_text.endswith("\n"):
        next_text += "\n"
    next_text += " ".join(entry_parts) + "\n"
    path.write_text(next_text, encoding="utf-8")
    acl = _repair_admin_authorized_keys_acl(path, runner=runner)
    try:
        if not _is_windows():
            path.chmod(0o600)
            path.parent.chmod(0o700)
    except OSError:
        pass
    return {
        "registered": True,
        "already_present": False,
        "authorized_keys_path": str(path),
        "effective_authorized_keys_path": str(path),
        "authorized_keys_scope": target["scope"],
        "administrators_authorized_keys_active": target["administrators_authorized_keys_active"],
        "acl_repair_attempted": acl["attempted"],
        "acl_repair_ok": acl["ok"],
        "acl_message": acl["message"],
        "message": "SSH public key를 authorized_keys에 등록했습니다." if acl["ok"] else "SSH public key를 등록했지만 administrators_authorized_keys ACL 보정이 필요합니다.",
    }
