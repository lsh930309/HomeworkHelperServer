from __future__ import annotations

import json
import re
import tempfile
import threading
import time
import urllib.request
import platform
import shutil
import subprocess
from pathlib import Path
from dataclasses import dataclass
from typing import Any, Callable, Sequence

_STATUS_CACHE_LOCK = threading.Lock()
_STATUS_CACHE = None


@dataclass(frozen=True)
class TailscalePeer:
    hostname: str
    dns_name: str
    ips: tuple[str, ...]
    online: bool
    os: str

    def primary_ipv4(self) -> str:
        return next((ip for ip in self.ips if "." in ip), "")


@dataclass(frozen=True)
class TailscaleSnapshot:
    installed: bool
    running: bool
    backend_state: str
    self_ips: tuple[str, ...]
    self_hostname: str
    peers: tuple[TailscalePeer, ...]
    message: str

    @property
    def ready(self) -> bool:
        return self.installed and self.running and bool(self.self_ips)

    def as_dict(self) -> dict[str, Any]:
        return {
            "installed": self.installed,
            "running": self.running,
            "backend_state": self.backend_state,
            "self_ips": list(self.self_ips),
            "self_hostname": self.self_hostname,
            "peers": [
                {
                    "hostname": peer.hostname,
                    "dns_name": peer.dns_name,
                    "ips": list(peer.ips),
                    "online": peer.online,
                    "os": peer.os,
                    "primary_ipv4": peer.primary_ipv4(),
                }
                for peer in self.peers
            ],
            "message": self.message,
        }


def _tailscale_executable() -> str | None:
    candidates = ["tailscale"]
    if platform.system() == "Windows":
        candidates.extend([
            r"C:\\Program Files\\Tailscale\\tailscale.exe",
            r"C:\\Program Files (x86)\\Tailscale\\tailscale.exe",
        ])
    else:
        candidates.extend(["/Applications/Tailscale.app/Contents/MacOS/Tailscale", "/usr/local/bin/tailscale", "/opt/homebrew/bin/tailscale"])
    for candidate in candidates:
        if candidate == "tailscale":
            resolved = shutil.which(candidate)
            if resolved:
                return resolved
            continue
        if Path(candidate).exists():
            return candidate
    return None


def _hidden_subprocess_kwargs() -> dict[str, Any]:
    """Hide console windows when GUI-packaged Windows builds poll CLI tools."""
    if platform.system() != "Windows":
        return {}
    kwargs: dict[str, Any] = {}
    startupinfo_cls = getattr(subprocess, "STARTUPINFO", None)
    if startupinfo_cls is not None:
        startupinfo = startupinfo_cls()
        startupinfo.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 0)
        startupinfo.wShowWindow = 0
        kwargs["startupinfo"] = startupinfo
    create_no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if create_no_window:
        kwargs["creationflags"] = create_no_window
    return kwargs


def _run_subprocess(args: Sequence[str], *, timeout_seconds: float, runner=None):
    kwargs = {
        "text": True,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "timeout": timeout_seconds,
        "check": False,
    }
    if runner is None:
        kwargs.update(_hidden_subprocess_kwargs())
    return (runner or subprocess.run)(list(args), **kwargs)


def _node_ips(item: dict[str, Any]) -> tuple[str, ...]:
    raw = item.get("TailscaleIPs") or item.get("TailAddr") or []
    if isinstance(raw, str):
        raw = [raw]
    return tuple(str(ip) for ip in raw if ip)


def tailscale_status(timeout_seconds: float = 1.5, runner=None, *, cache_ttl_seconds: float = 0.0) -> TailscaleSnapshot:
    global _STATUS_CACHE
    if cache_ttl_seconds > 0 and runner is None:
        now = time.monotonic()
        with _STATUS_CACHE_LOCK:
            if _STATUS_CACHE and now - _STATUS_CACHE[0] < cache_ttl_seconds:
                return _STATUS_CACHE[1]

    exe = _tailscale_executable()
    if not exe:
        snapshot = TailscaleSnapshot(False, False, "missing", (), "", (), "tailscale CLI를 찾지 못했습니다.")
        if cache_ttl_seconds > 0 and runner is None:
            with _STATUS_CACHE_LOCK:
                _STATUS_CACHE = (time.monotonic(), snapshot)
        return snapshot

    try:
        completed = _run_subprocess([exe, "status", "--json"], timeout_seconds=timeout_seconds, runner=runner)
    except (OSError, subprocess.TimeoutExpired) as exc:
        snapshot = TailscaleSnapshot(True, False, "error", (), "", (), f"tailscale status 실행 실패: {exc}")
        if cache_ttl_seconds > 0 and runner is None:
            with _STATUS_CACHE_LOCK:
                _STATUS_CACHE = (time.monotonic(), snapshot)
        return snapshot

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        snapshot = TailscaleSnapshot(True, False, "error", (), "", (), detail or "tailscale status가 실패했습니다.")
        if cache_ttl_seconds > 0 and runner is None:
            with _STATUS_CACHE_LOCK:
                _STATUS_CACHE = (time.monotonic(), snapshot)
        return snapshot

    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        snapshot = TailscaleSnapshot(True, False, "invalid_json", (), "", (), "tailscale status JSON을 해석하지 못했습니다.")
        if cache_ttl_seconds > 0 and runner is None:
            with _STATUS_CACHE_LOCK:
                _STATUS_CACHE = (time.monotonic(), snapshot)
        return snapshot

    self_node = payload.get("Self") or {}
    backend_state = str(payload.get("BackendState") or "unknown")
    peers = []
    for item in (payload.get("Peer") or {}).values():
        ips = _node_ips(item)
        peers.append(
            TailscalePeer(
                hostname=str(item.get("HostName") or ""),
                dns_name=str(item.get("DNSName") or ""),
                ips=ips,
                online=bool(item.get("Online")),
                os=str(item.get("OS") or ""),
            )
        )
    self_ips = _node_ips(self_node)
    running = backend_state.lower() == "running" and bool(self_ips)
    message = "tailscale 네트워크 사용 가능" if running else f"tailscale 상태: {backend_state}"
    snapshot = TailscaleSnapshot(
        installed=True,
        running=running,
        backend_state=backend_state,
        self_ips=self_ips,
        self_hostname=str(self_node.get("HostName") or ""),
        peers=tuple(peers),
        message=message,
    )
    if cache_ttl_seconds > 0 and runner is None:
        with _STATUS_CACHE_LOCK:
            _STATUS_CACHE = (time.monotonic(), snapshot)
    return snapshot


def suggest_remote_base_urls(snapshot: TailscaleSnapshot, *, port: int = 8000, preferred_names: tuple[str, ...] = ()) -> list[str]:
    names = tuple(name.lower() for name in preferred_names if name)
    candidates: list[TailscalePeer] = []
    for peer in snapshot.peers:
        haystack = " ".join([peer.hostname, peer.dns_name]).lower()
        if names and not any(name in haystack for name in names):
            continue
        if peer.primary_ipv4():
            candidates.append(peer)
    if not candidates and not names:
        candidates = [peer for peer in snapshot.peers if peer.primary_ipv4()]
    return [f"http://{peer.primary_ipv4()}:{port}" for peer in candidates]


@dataclass(frozen=True)
class TailscaleEnsureResult:
    before: TailscaleSnapshot
    after: TailscaleSnapshot
    install_attempted: bool
    launch_attempted: bool
    method: str
    message: str

    @property
    def ready(self) -> bool:
        return self.after.ready

    def as_dict(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "install_attempted": self.install_attempted,
            "launch_attempted": self.launch_attempted,
            "method": self.method,
            "message": self.message,
            "before": self.before.as_dict(),
            "after": self.after.as_dict(),
        }


def _run_command(args: Sequence[str], timeout_seconds: float = 120.0, runner=None) -> bool:
    try:
        completed = _run_subprocess(args, timeout_seconds=timeout_seconds, runner=runner)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0


def _download_latest_macos_pkg() -> Path | None:
    try:
        listing = urllib.request.urlopen("https://pkgs.tailscale.com/stable/?v=latest", timeout=15).read().decode("utf-8", "replace")
    except OSError:
        return None
    match = re.search(r"Tailscale-[0-9.]+-macos\.pkg", listing)
    if not match:
        return None
    url = "https://pkgs.tailscale.com/stable/" + match.group(0)
    target = Path(tempfile.gettempdir()) / match.group(0)
    try:
        urllib.request.urlretrieve(url, target)
    except OSError:
        return None
    return target




def _download_latest_windows_msi() -> Path | None:
    try:
        listing = urllib.request.urlopen("https://pkgs.tailscale.com/stable/?v=latest", timeout=15).read().decode("utf-8", "replace")
    except OSError:
        return None
    machine = platform.machine().lower()
    suffix = "arm64" if "arm" in machine else "amd64" if "64" in machine else "x86"
    match = re.search(rf"tailscale-setup-[0-9.]+-{suffix}\.msi", listing)
    if not match:
        return None
    url = "https://pkgs.tailscale.com/stable/" + match.group(0)
    target = Path(tempfile.gettempdir()) / match.group(0)
    try:
        urllib.request.urlretrieve(url, target)
    except OSError:
        return None
    return target

def _install_tailscale(runner=None) -> tuple[bool, str]:
    system = platform.system()
    if system == "Darwin":
        brew = shutil.which("brew") or ("/opt/homebrew/bin/brew" if Path("/opt/homebrew/bin/brew").exists() else None) or ("/usr/local/bin/brew" if Path("/usr/local/bin/brew").exists() else None)
        if brew and _run_command([brew, "install", "--cask", "tailscale"], 600.0, runner=runner):
            return True, "homebrew-cask"
        pkg = _download_latest_macos_pkg()
        if pkg and _run_command(["/usr/sbin/installer", "-pkg", str(pkg), "-target", "/"], 600.0, runner=runner):
            return True, "official-pkg"
        return False, "macos-install-failed"
    if system == "Windows":
        winget = shutil.which("winget")
        if winget and _run_command([winget, "install", "--id", "Tailscale.Tailscale", "--exact", "--silent", "--accept-package-agreements", "--accept-source-agreements"], 600.0, runner=runner):
            return True, "winget"
        msi = _download_latest_windows_msi()
        if msi and _run_command(["msiexec", "/i", str(msi), "/qn", "/norestart"], 600.0, runner=runner):
            return True, "official-msi"
        return False, "windows-install-failed"
    return False, "unsupported-platform"


def _launch_tailscale(runner=None) -> tuple[bool, str]:
    system = platform.system()
    if system == "Darwin":
        if _run_command(["/usr/bin/open", "-a", "Tailscale"], 30.0, runner=runner):
            return True, "open-app"
    if system == "Windows":
        exe = _tailscale_executable()
        if exe and _run_command([exe, "up", "--accept-routes"], 60.0, runner=runner):
            return True, "tailscale-up"
    return False, "launch-failed"


def ensure_tailscale_ready(
    *,
    timeout_seconds: float = 1.5,
    retry_delay_seconds: float = 2.0,
    runner=None,
    status_probe: Callable[[], TailscaleSnapshot] | None = None,
) -> TailscaleEnsureResult:
    probe = status_probe or (lambda: tailscale_status(timeout_seconds=timeout_seconds, runner=runner))
    before = probe()
    install_attempted = False
    launch_attempted = False
    methods: list[str] = []

    if before.ready:
        return TailscaleEnsureResult(before, before, False, False, "already-ready", before.message)

    if not before.installed:
        install_attempted = True
        ok, method = _install_tailscale(runner=runner)
        methods.append(method)
        if not ok:
            after = probe()
            return TailscaleEnsureResult(before, after, True, False, "+".join(methods), "tailscale 자동 설치에 실패했습니다. 공식 다운로드 페이지에서 수동 설치가 필요합니다.")

    launch_attempted = True
    ok, method = _launch_tailscale(runner=runner)
    methods.append(method)
    if retry_delay_seconds > 0:
        time.sleep(retry_delay_seconds)
    after = probe()
    message = after.message if after.ready else "tailscale 설치/실행 후에도 로그인 또는 System Extension 승인이 필요합니다."
    if not ok and after.ready:
        message = after.message
    return TailscaleEnsureResult(before, after, install_attempted, launch_attempted, "+".join(methods) or "status-only", message)
