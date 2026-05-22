from __future__ import annotations

import json
import re
import tempfile
import threading
import time
import urllib.request
import os
import platform
import shutil
import subprocess
from pathlib import Path, PureWindowsPath
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
    node_id: str = ""

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
    self_node_id: str = ""
    state: str = ""
    cli_path: str = ""
    cli_source: str = ""
    cli_version: str = ""

    @property
    def ready(self) -> bool:
        return self.installed and self.running and bool(self.self_ips)

    @property
    def foundation_state(self) -> str:
        return self.state or classify_tailscale_state(
            installed=self.installed,
            running=self.running,
            backend_state=self.backend_state,
            self_ips=self.self_ips,
            message=self.message,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "installed": self.installed,
            "running": self.running,
            "backend_state": self.backend_state,
            "state": self.foundation_state,
            "foundation_state": self.foundation_state,
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
                    "node_id": peer.node_id,
                }
                for peer in self.peers
            ],
            "message": self.message,
            "self_node_id": self.self_node_id,
            "cli": {
                "path": self.cli_path,
                "source": self.cli_source,
                "version": self.cli_version,
                "supports_cli": bool(self.cli_path),
                "error": "" if self.cli_path else self.message,
            },
        }


@dataclass(frozen=True)
class TailscaleCommandResolution:
    path: str
    source: str
    version: str = ""
    supports_cli: bool = False
    error: str = ""

    @property
    def found(self) -> bool:
        return bool(self.path and self.supports_cli)

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "source": self.source,
            "version": self.version,
            "supports_cli": self.supports_cli,
            "error": self.error,
        }


def classify_tailscale_state(
    *,
    installed: bool,
    running: bool,
    backend_state: str,
    self_ips: Sequence[str] | tuple[str, ...] | list[str],
    message: str = "",
) -> str:
    """Classify Tailscale as a required HomeworkHelper foundation layer."""
    if not installed:
        return "missing"
    if running and bool(self_ips):
        return "ready"

    normalized = (backend_state or "").strip().lower()
    lowered = (message or "").strip().lower()
    if "system extension" in lowered or "network extension" in lowered or "vpn" in lowered or "approval" in lowered or "승인" in lowered:
        return "needs_system_approval"
    if normalized in {"needslogin", "needs_login", "nostate"} or "not logged" in lowered or "로그인" in lowered or "login" in lowered:
        return "needs_login"
    if normalized in {"stopped", "down"} or "tailscale down" in lowered or "stopped" in lowered:
        return "stopped_or_down"
    if normalized == "running" and not self_ips:
        return "running_without_ip"
    if (
        "not running" in lowered
        or "failed to start" in lowered
        or "gui failed to start" in lowered
        or "tailscaled" in lowered
        or "daemon" in lowered
        or "backend" in lowered
    ):
        return "app_launch_needed"
    return "installed"


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _windows_tailscale_candidates(environ: dict[str, str] | None = None) -> list[str]:
    env = environ or os.environ
    candidates: list[str] = []
    for env_name in ("ProgramFiles", "ProgramFiles(x86)", "LocalAppData"):
        base = env.get(env_name)
        if base:
            candidates.append(str(PureWindowsPath(base) / "Tailscale" / "tailscale.exe"))
    candidates.extend([
        r"C:\Program Files\Tailscale\tailscale.exe",
        r"C:\Program Files (x86)\Tailscale\tailscale.exe",
    ])
    return _dedupe_preserve_order(candidates)


def _tailscale_cli_from_windows_command() -> str | None:
    commands = [
        ["where", "tailscale"],
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            "(Get-Command tailscale -ErrorAction SilentlyContinue).Source",
        ],
    ]
    for command in commands:
        try:
            completed = _run_subprocess(command, timeout_seconds=1.5)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if completed.returncode != 0:
            continue
        for line in (completed.stdout or "").splitlines():
            candidate = line.strip().strip('"')
            if not candidate:
                continue
            if candidate.lower().endswith(("tailscale.exe", "tailscale")):
                return candidate
    return None


def _macos_tailscale_candidates() -> list[tuple[str, str]]:
    return [
        ("/Applications/Tailscale.app/Contents/MacOS/Tailscale", "macos-app-bundled-cli"),
        ("/usr/local/bin/tailscale", "macos-cli-integration"),
        ("/opt/homebrew/bin/tailscale", "homebrew-cli"),
    ]


def _tailscale_version(exe: str, *, runner=None) -> str:
    try:
        completed = _run_subprocess([exe, "version"], timeout_seconds=2.0, runner=runner)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if completed.returncode != 0:
        return ""
    return (completed.stdout or "").splitlines()[0].strip()


def resolve_tailscale_cli(*, include_version: bool = False, runner=None) -> TailscaleCommandResolution:
    """Find the real Tailscale executable path without relying on shell aliases."""
    system = platform.system()
    if system == "Windows":
        resolved = shutil.which("tailscale")
        if resolved:
            return TailscaleCommandResolution(
                resolved,
                "path",
                _tailscale_version(resolved, runner=runner) if include_version else "",
                True,
                "",
            )
        for candidate in _windows_tailscale_candidates():
            if Path(candidate).exists():
                return TailscaleCommandResolution(
                    candidate,
                    "windows-known-path",
                    _tailscale_version(candidate, runner=runner) if include_version else "",
                    True,
                    "",
                )
        command_path = _tailscale_cli_from_windows_command()
        if command_path:
            return TailscaleCommandResolution(
                command_path,
                "windows-command-discovery",
                _tailscale_version(command_path, runner=runner) if include_version else "",
                True,
                "",
            )
        return TailscaleCommandResolution("", "windows", "", False, "tailscale.exe를 찾지 못했습니다.")

    if system == "Darwin":
        for candidate, source in _macos_tailscale_candidates():
            if Path(candidate).exists():
                return TailscaleCommandResolution(
                    candidate,
                    source,
                    _tailscale_version(candidate, runner=runner) if include_version else "",
                    True,
                    "",
                )
        resolved = shutil.which("tailscale")
        if resolved:
            return TailscaleCommandResolution(
                resolved,
                "path",
                _tailscale_version(resolved, runner=runner) if include_version else "",
                True,
                "",
            )
        return TailscaleCommandResolution("", "macos", "", False, "Tailscale.app 또는 tailscale CLI를 찾지 못했습니다.")

    resolved = shutil.which("tailscale")
    if resolved:
        return TailscaleCommandResolution(
            resolved,
            "path",
            _tailscale_version(resolved, runner=runner) if include_version else "",
            True,
            "",
        )
    return TailscaleCommandResolution("", system.lower() or "unknown", "", False, "tailscale CLI를 찾지 못했습니다.")


def _tailscale_executable() -> str | None:
    resolution = resolve_tailscale_cli()
    return resolution.path if resolution.found else None


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
    if platform.system() == "Darwin" and args:
        executable = str(args[0])
        if "Tailscale.app" in executable or Path(executable).name.lower() == "tailscale":
            env = os.environ.copy()
            env["TAILSCALE_BE_CLI"] = "1"
            kwargs["env"] = env
    return (runner or subprocess.run)(list(args), **kwargs)


def _node_ips(item: dict[str, Any]) -> tuple[str, ...]:
    raw = item.get("TailscaleIPs") or item.get("TailAddr") or []
    if isinstance(raw, str):
        raw = [raw]
    return tuple(str(ip) for ip in raw if ip)


def _looks_like_tailscale_ip(value: str) -> bool:
    return bool(re.match(r"^100\.\d{1,3}\.\d{1,3}\.\d{1,3}$", value.strip()))


def _parse_plain_status_output(
    output: str,
    *,
    cli_path: str = "",
    cli_source: str = "",
    cli_version: str = "",
) -> TailscaleSnapshot | None:
    peers: list[TailscalePeer] = []
    self_ips: list[str] = []
    self_hostname = ""
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 4 or not _looks_like_tailscale_ip(parts[0]):
            continue
        ip, hostname, _user, os_name = parts[:4]
        online = "offline" not in line.lower()
        peer = TailscalePeer(hostname=hostname, dns_name="", ips=(ip,), online=online, os=os_name)
        peers.append(peer)
        if not self_ips and online:
            self_ips.append(ip)
            self_hostname = hostname
    if not peers:
        return None
    message = "tailscale 네트워크 사용 가능" if self_ips else "tailscale status 출력은 확인했지만 온라인 self IP를 찾지 못했습니다."
    return TailscaleSnapshot(
        installed=True,
        running=bool(self_ips),
        backend_state="Running" if self_ips else "unknown",
        self_ips=tuple(self_ips),
        self_hostname=self_hostname,
        peers=tuple(peers),
        message=message,
        state=classify_tailscale_state(
            installed=True,
            running=bool(self_ips),
            backend_state="Running" if self_ips else "unknown",
            self_ips=tuple(self_ips),
            message=message,
        ),
        cli_path=cli_path,
        cli_source=cli_source,
        cli_version=cli_version,
    )



def _plain_status_snapshot(
    exe: str,
    timeout_seconds: float,
    runner=None,
    *,
    resolution: TailscaleCommandResolution | None = None,
) -> TailscaleSnapshot | None:
    try:
        plain_completed = _run_subprocess([exe, "status"], timeout_seconds=max(timeout_seconds, 2.5), runner=runner)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if plain_completed.returncode != 0:
        return None
    resolution = resolution or TailscaleCommandResolution(exe, "unknown", "", bool(exe), "")
    return _parse_plain_status_output(
        plain_completed.stdout or "",
        cli_path=resolution.path,
        cli_source=resolution.source,
        cli_version=resolution.version,
    )

def tailscale_status(timeout_seconds: float = 1.5, runner=None, *, cache_ttl_seconds: float = 0.0) -> TailscaleSnapshot:
    global _STATUS_CACHE
    if cache_ttl_seconds > 0 and runner is None:
        now = time.monotonic()
        with _STATUS_CACHE_LOCK:
            if _STATUS_CACHE and now - _STATUS_CACHE[0] < cache_ttl_seconds:
                return _STATUS_CACHE[1]

    # Keep the historical _tailscale_executable hook as the status entrypoint so
    # tests and packaged call sites can override path discovery without relying
    # on shell aliases.
    exe = _tailscale_executable() or ""
    resolution = TailscaleCommandResolution(exe, "resolved", "", bool(exe), "" if exe else "tailscale CLI를 찾지 못했습니다.")
    if not exe:
        message = resolution.error or "tailscale CLI를 찾지 못했습니다."
        snapshot = TailscaleSnapshot(
            False,
            False,
            "missing",
            (),
            "",
            (),
            message,
            state="missing",
            cli_path="",
            cli_source=resolution.source,
        )
        if cache_ttl_seconds > 0 and runner is None:
            with _STATUS_CACHE_LOCK:
                _STATUS_CACHE = (time.monotonic(), snapshot)
        return snapshot

    try:
        completed = _run_subprocess([exe, "status", "--json"], timeout_seconds=max(timeout_seconds, 2.5), runner=runner)
    except (OSError, subprocess.TimeoutExpired) as exc:
        message = f"tailscale status 실행 실패: {exc}"
        snapshot = TailscaleSnapshot(
            True,
            False,
            "error",
            (),
            "",
            (),
            message,
            state=classify_tailscale_state(installed=True, running=False, backend_state="error", self_ips=(), message=message),
            cli_path=resolution.path,
            cli_source=resolution.source,
            cli_version=resolution.version,
        )
        if cache_ttl_seconds > 0 and runner is None:
            with _STATUS_CACHE_LOCK:
                _STATUS_CACHE = (time.monotonic(), snapshot)
        return snapshot

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        message = f"tailscale status가 실패했습니다. returncode={completed.returncode}"
        if detail:
            message = f"{message}: {detail}"
        plain = _plain_status_snapshot(exe, timeout_seconds, runner=runner, resolution=resolution)
        snapshot = plain or TailscaleSnapshot(
            True,
            False,
            "error",
            (),
            "",
            (),
            message,
            state=classify_tailscale_state(installed=True, running=False, backend_state="error", self_ips=(), message=message),
            cli_path=resolution.path,
            cli_source=resolution.source,
            cli_version=resolution.version,
        )
        if cache_ttl_seconds > 0 and runner is None:
            with _STATUS_CACHE_LOCK:
                _STATUS_CACHE = (time.monotonic(), snapshot)
        return snapshot

    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError:
        plain = _plain_status_snapshot(exe, timeout_seconds, runner=runner, resolution=resolution)
        message = "tailscale status JSON을 해석하지 못했습니다."
        snapshot = plain or TailscaleSnapshot(
            True,
            False,
            "invalid_json",
            (),
            "",
            (),
            message,
            state=classify_tailscale_state(installed=True, running=False, backend_state="invalid_json", self_ips=(), message=message),
            cli_path=resolution.path,
            cli_source=resolution.source,
            cli_version=resolution.version,
        )
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
                node_id=str(item.get("ID") or item.get("StableID") or item.get("NodeID") or ""),
            )
        )
    self_ips = _node_ips(self_node)
    normalized_state = backend_state.lower()
    if normalized_state == "unknown" and not self_ips:
        plain = _plain_status_snapshot(exe, timeout_seconds, runner=runner, resolution=resolution)
        if plain and plain.ready:
            if cache_ttl_seconds > 0 and runner is None:
                with _STATUS_CACHE_LOCK:
                    _STATUS_CACHE = (time.monotonic(), plain)
            return plain
    running = normalized_state == "running" and bool(self_ips)
    if running:
        message = "tailscale 네트워크 사용 가능"
    elif normalized_state == "running" and not self_ips:
        message = "tailscale 상태는 Running이지만 Self IP가 없습니다. Tailscale 로그인/네트워크 상태를 확인하세요."
    elif normalized_state == "unknown":
        message = "tailscale CLI 응답에 BackendState가 없습니다. 로그인/서비스 상태를 확인하세요."
    elif normalized_state in {"needslogin", "stopped", "nostate"}:
        message = f"tailscale 상태: {backend_state}. 로그인 또는 서비스 실행이 필요합니다."
    else:
        message = f"tailscale 상태: {backend_state}"
    state = classify_tailscale_state(
        installed=True,
        running=running,
        backend_state=backend_state,
        self_ips=self_ips,
        message=message,
    )
    snapshot = TailscaleSnapshot(
        installed=True,
        running=running,
        backend_state=backend_state,
        self_ips=self_ips,
        self_hostname=str(self_node.get("HostName") or ""),
        peers=tuple(peers),
        message=message,
        self_node_id=str(self_node.get("ID") or self_node.get("StableID") or self_node.get("NodeID") or ""),
        state=state,
        cli_path=resolution.path,
        cli_source=resolution.source,
        cli_version=resolution.version,
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


@dataclass(frozen=True)
class TailscaleControlResult:
    action: str
    before: TailscaleSnapshot
    after: TailscaleSnapshot
    attempted: bool
    succeeded: bool
    method: str
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "attempted": self.attempted,
            "succeeded": self.succeeded,
            "ready": self.after.ready,
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


def _run_control_command(args: Sequence[str], timeout_seconds: float = 120.0, runner=None) -> tuple[bool, str]:
    try:
        completed = _run_subprocess(args, timeout_seconds=timeout_seconds, runner=runner)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    output = ((completed.stdout or "") + "\n" + (completed.stderr or "")).strip()
    return completed.returncode == 0, output


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
    methods: list[str] = []
    ok = False
    if system == "Darwin":
        if _run_command(["/usr/bin/open", "-a", "Tailscale"], 30.0, runner=runner):
            ok = True
            methods.append("open-app")
    exe = _tailscale_executable()
    if exe:
        up_ok, _output = _run_control_command([exe, "up", "--accept-routes"], 90.0, runner=runner)
        ok = ok or up_ok
        methods.append("tailscale-up" if up_ok else "tailscale-up-pending")
    return ok, "+".join(methods) if methods else "launch-failed"


def _down_tailscale(runner=None) -> tuple[bool, str]:
    exe = _tailscale_executable()
    if not exe:
        return False, "tailscale-missing"
    ok, _output = _run_control_command([exe, "down"], 60.0, runner=runner)
    return ok, "tailscale-down" if ok else "tailscale-down-failed"


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
    message = after.message if after.ready else _message_for_foundation_state(after.foundation_state)
    if not ok and after.ready:
        message = after.message
    return TailscaleEnsureResult(before, after, install_attempted, launch_attempted, "+".join(methods) or "status-only", message)


def _message_for_foundation_state(state: str) -> str:
    return {
        "missing": "Tailscale이 설치되어 있지 않습니다. 공식 설치 프로그램으로 설치가 필요합니다.",
        "needs_login": "Tailscale 실행은 확인됐지만 tailnet 로그인/계정 생성이 필요합니다. Tailscale 앱에서 로그인 후 다시 시도하세요.",
        "needs_system_approval": "Tailscale 실행은 확인됐지만 macOS VPN/System Extension 승인이 필요합니다. 시스템 설정에서 승인 후 다시 시도하세요.",
        "stopped_or_down": "Tailscale이 설치되어 있지만 네트워크가 down 상태입니다. 활성화를 실행하세요.",
        "running_without_ip": "Tailscale 상태는 Running이지만 self IP가 없습니다. 로그인/네트워크 상태를 확인하세요.",
        "app_launch_needed": "Tailscale이 설치되어 있지만 앱/daemon 실행이 필요합니다. 자동 실행을 시도했으며 로그인/승인이 필요할 수 있습니다.",
        "installed": "Tailscale이 설치되어 있지만 tailnet 연결은 아직 준비되지 않았습니다. 실행/로그인 상태를 확인하세요.",
        "ready": "tailscale 네트워크 사용 가능",
    }.get(state, "Tailscale 설치/실행 후에도 로그인 또는 System Extension 승인이 필요합니다.")


def set_tailscale_network_enabled(
    enabled: bool,
    *,
    timeout_seconds: float = 1.5,
    retry_delay_seconds: float = 2.0,
    runner=None,
) -> TailscaleControlResult:
    before = tailscale_status(timeout_seconds=timeout_seconds, runner=runner)
    if enabled:
        ensure = ensure_tailscale_ready(
            timeout_seconds=timeout_seconds,
            retry_delay_seconds=retry_delay_seconds,
            runner=runner,
        )
        return TailscaleControlResult(
            action="up",
            before=before,
            after=ensure.after,
            attempted=ensure.install_attempted or ensure.launch_attempted,
            succeeded=ensure.ready,
            method=ensure.method,
            message=ensure.message,
        )

    ok, method = _down_tailscale(runner=runner)
    if retry_delay_seconds > 0:
        time.sleep(retry_delay_seconds)
    after = tailscale_status(timeout_seconds=timeout_seconds, runner=runner)
    message = "Tailscale 네트워크를 비활성화했습니다." if ok else _message_for_foundation_state(after.foundation_state)
    return TailscaleControlResult(
        action="down",
        before=before,
        after=after,
        attempted=True,
        succeeded=ok,
        method=method,
        message=message,
    )
