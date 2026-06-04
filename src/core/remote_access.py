from __future__ import annotations

import ipaddress
import os
import platform
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.request import urlopen

import psutil

from src.api.runtime_config import resolve_api_port
from src.core.remote_local_store import remote_store


REMOTE_ACCESS_CONFIG = "remote_access.json"
DEFAULT_DOMAIN_SUFFIX = "sslip.io"
DEFAULT_EXTERNAL_HTTPS_PORT = 443
DEFAULT_INTERNAL_HTTPS_PORT = 38443


@dataclass(frozen=True)
class PortForwardRule:
    protocol: str = "TCP"
    external_port: int = DEFAULT_EXTERNAL_HTTPS_PORT
    internal_port: int = DEFAULT_INTERNAL_HTTPS_PORT
    target_host: str = "Windows Host"
    purpose: str = "HomeworkHelper HTTPS control plane"

    def as_dict(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "external_port": self.external_port,
            "internal_port": self.internal_port,
            "target_host": self.target_host,
            "purpose": self.purpose,
            "summary": f"{self.protocol} {self.external_port} -> {self.target_host}:{self.internal_port}",
        }


def is_public_ipv4_literal(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return False
    return bool(
        address.version == 4
        and address.is_global
        and not address.is_private
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_multicast
        and not address.is_reserved
        and not address.is_unspecified
    )


def sslip_hostname_for_ip(public_ip: str, *, suffix: str = DEFAULT_DOMAIN_SUFFIX) -> str:
    """Return the dash-form sslip.io host for a public IPv4 literal."""

    ip = public_ip.strip()
    if not is_public_ipv4_literal(ip):
        raise ValueError(f"public IPv4 주소가 아닙니다: {public_ip}")
    return f"{ip.replace('.', '-')}.{suffix.strip('.')}"


def public_https_base_url_for_ip(public_ip: str, *, suffix: str = DEFAULT_DOMAIN_SUFFIX) -> str:
    return f"https://{sslip_hostname_for_ip(public_ip, suffix=suffix)}"


def load_remote_access_config() -> dict[str, Any]:
    default = {
        "schema_version": 1,
        "enabled": True,
        "domain_suffix": DEFAULT_DOMAIN_SUFFIX,
        "public_ip": "",
        "hostname": "",
        "external_https_port": DEFAULT_EXTERNAL_HTTPS_PORT,
        "internal_https_port": DEFAULT_INTERNAL_HTTPS_PORT,
        "agent_port": resolve_api_port(),
        "caddy_path": "",
        "updated_at": 0,
    }
    config = remote_store().read_json(REMOTE_ACCESS_CONFIG, default)
    merged = {**default, **config}
    merged["agent_port"] = resolve_api_port(_valid_port(merged.get("agent_port"), resolve_api_port()))
    merged["external_https_port"] = _valid_port(merged.get("external_https_port"), DEFAULT_EXTERNAL_HTTPS_PORT)
    merged["internal_https_port"] = _valid_port(merged.get("internal_https_port"), DEFAULT_INTERNAL_HTTPS_PORT)
    return merged


def save_remote_access_config(updates: dict[str, Any]) -> dict[str, Any]:
    config = load_remote_access_config()
    for key in {
        "enabled",
        "domain_suffix",
        "public_ip",
        "hostname",
        "external_https_port",
        "internal_https_port",
        "agent_port",
        "caddy_path",
    }:
        if key in updates:
            config[key] = updates[key]
    config["updated_at"] = time.time()
    remote_store().write_json(REMOTE_ACCESS_CONFIG, config)
    return load_remote_access_config()


def generate_caddyfile(
    hostname: str,
    *,
    internal_https_port: int = DEFAULT_INTERNAL_HTTPS_PORT,
    agent_port: int | None = None,
) -> str:
    agent_port = resolve_api_port() if agent_port is None else _valid_port(agent_port, resolve_api_port())
    host = hostname.strip() or "<public-ip>.sslip.io"
    return (
        "{\n"
        f"    https_port {internal_https_port}\n"
        "    auto_https disable_redirects\n"
        "}\n\n"
        f"https://{host} {{\n"
        f"    reverse_proxy 127.0.0.1:{agent_port}\n"
        "}\n"
    )


def caddy_config_path() -> Path:
    path = remote_store().path("caddy/Caddyfile")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def remote_access_status(
    *,
    public_direct: bool = False,
    auth_required: bool = False,
    probe_public_ip: bool = False,
    probe_upnp: bool = False,
    probe_caddy: bool = True,
) -> dict[str, Any]:
    """Return a non-secret status payload for public HTTPS remote access.

    This intentionally does not mutate router state.  UPnP is represented as a
    read-only diagnostic so v1 can keep manual forwarding as the safe default.
    """

    config = load_remote_access_config()
    configured_ip = str(os.environ.get("HH_REMOTE_PUBLIC_IP") or config.get("public_ip") or "").strip()
    detected_ip = _detect_public_ip() if probe_public_ip else ""
    public_ip = configured_ip or detected_ip
    suffix = str(config.get("domain_suffix") or DEFAULT_DOMAIN_SUFFIX).strip(".") or DEFAULT_DOMAIN_SUFFIX
    configured_hostname = str(config.get("hostname") or "").strip()
    generated_hostname = ""
    if is_public_ipv4_literal(public_ip):
        generated_hostname = sslip_hostname_for_ip(public_ip, suffix=suffix)
    hostname = configured_hostname or generated_hostname
    public_base_url = f"https://{hostname}" if hostname else ""
    internal_https_port = _valid_port(config.get("internal_https_port"), DEFAULT_INTERNAL_HTTPS_PORT)
    external_https_port = _valid_port(config.get("external_https_port"), DEFAULT_EXTERNAL_HTTPS_PORT)
    agent_port = resolve_api_port()
    rule = PortForwardRule(
        external_port=external_https_port,
        internal_port=internal_https_port,
    )
    caddy = _caddy_status(hostname, internal_https_port=internal_https_port, agent_port=agent_port, probe=probe_caddy)
    warnings = _remote_access_warnings(
        public_ip=public_ip,
        hostname=hostname,
        public_direct=public_direct,
        auth_required=auth_required,
        caddy=caddy,
    )
    advisories = ["공유기에서 Remote Agent 8000 포트는 공개하지 마세요."]
    return {
        "schema_version": 1,
        "enabled": bool(config.get("enabled", True)),
        "mode": "manual_port_forward_public_https",
        "state": "ready" if not warnings else "warning",
        "public_ip": public_ip,
        "public_ip_source": "configured" if configured_ip else "detected" if detected_ip else "missing",
        "hostname": hostname,
        "domain_suffix": suffix,
        "public_base_url": public_base_url,
        "agent_base_url": f"http://127.0.0.1:{agent_port}",
        "ports": {
            "required_count": 1,
            "rules": [rule.as_dict()],
            "no_udp_required": True,
            "do_not_forward": [agent_port],
        },
        "router_rule": rule.as_dict(),
        "caddy": caddy,
        "upnp": _upnp_diagnostic(probe=probe_upnp),
        "security": {
            "public_direct": bool(public_direct),
            "auth_required": bool(auth_required),
            "public_http_allowed": False,
            "pairing_start_public": False,
        },
        "warnings": warnings,
        "advisories": advisories,
        "message": (
            f"공유기에서 TCP {external_https_port} -> Host {internal_https_port} 포트포워딩을 추가하세요."
            if hostname
            else "공인 IP를 입력하면 sslip.io HTTPS hostname과 포트포워딩 규칙을 생성합니다."
        ),
    }


def _valid_port(value: Any, default: int) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return default
    return port if 0 < port < 65536 else default


def _detect_public_ip(timeout: float = 2.0) -> str:
    endpoints = (
        "https://api.ipify.org",
        "https://ifconfig.me/ip",
    )
    for endpoint in endpoints:
        try:
            with urlopen(endpoint, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS public-IP endpoints
                value = response.read(64).decode("utf-8", errors="ignore").strip()
            if is_public_ipv4_literal(value):
                return value
        except Exception:
            continue
    return ""


def _caddy_status(hostname: str, *, internal_https_port: int, agent_port: int, probe: bool = True) -> dict[str, Any]:
    configured = str(load_remote_access_config().get("caddy_path") or "").strip()
    resolved = configured if configured and Path(configured).exists() else shutil.which("caddy") or ""
    running = _caddy_process_running() if probe else False
    listener = _port_listener(internal_https_port) if probe else {"listening": False, "host": "", "port": internal_https_port, "pid": None, "message": "runtime probe skipped"}
    preview = generate_caddyfile(hostname, internal_https_port=internal_https_port, agent_port=agent_port)
    return {
        "strategy": "caddy_sidecar",
        "probe": probe,
        "installed": bool(resolved),
        "path": resolved,
        "running": running,
        "internal_https_port": internal_https_port,
        "config_path": str(caddy_config_path()),
        "config_preview": preview,
        "listener": listener,
        "message": (
            "Caddy sidecar 실행 중"
            if running
            else "Caddy sidecar가 아직 실행 중이 아닙니다. Host App에서 생성된 Caddyfile로 실행하세요."
        ),
    }


def _caddy_process_running() -> bool:
    for process in psutil.process_iter(["name", "exe", "cmdline"]):
        try:
            parts = [
                str(process.info.get("name") or ""),
                str(process.info.get("exe") or ""),
                " ".join(process.info.get("cmdline") or []),
            ]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if any("caddy" in part.casefold() for part in parts):
            return True
    return False


def _port_listener(port: int) -> dict[str, Any]:
    try:
        for connection in psutil.net_connections(kind="tcp"):
            local = connection.laddr
            if getattr(local, "port", None) == port and connection.status == psutil.CONN_LISTEN:
                return {
                    "listening": True,
                    "host": getattr(local, "ip", ""),
                    "port": port,
                    "pid": connection.pid,
                }
    except (psutil.AccessDenied, OSError):
        return {"listening": False, "host": "", "port": port, "pid": None, "message": "listener 조회 권한 없음"}
    return {"listening": False, "host": "", "port": port, "pid": None}


def _remote_access_warnings(
    *,
    public_ip: str,
    hostname: str,
    public_direct: bool,
    auth_required: bool,
    caddy: dict[str, Any],
) -> list[str]:
    warnings: list[str] = []
    if not public_ip:
        warnings.append("공유기 WAN 공인 IP를 입력하거나 감지해야 합니다.")
    elif not is_public_ipv4_literal(public_ip):
        warnings.append("입력한 IP가 public IPv4가 아닙니다. 공유기 WAN IP와 외부 IP가 다르면 CGNAT일 수 있습니다.")
    if not hostname:
        warnings.append("sslip.io hostname을 아직 생성하지 못했습니다.")
    if not public_direct:
        warnings.append("공개 접속 시 Host는 HH_REMOTE_PUBLIC_DIRECT=1로 실행해야 합니다.")
    if not auth_required:
        warnings.append("공개 접속 시 Remote API bearer 인증이 필수입니다.")
    if not caddy.get("probe", True):
        return warnings
    if not caddy.get("installed"):
        warnings.append("Caddy 실행 파일을 찾지 못했습니다.")
    if not caddy.get("listener", {}).get("listening"):
        warnings.append(f"Caddy 내부 HTTPS 포트 {caddy.get('internal_https_port')} listener가 아직 없습니다.")
    return warnings


def _upnp_diagnostic(*, probe: bool) -> dict[str, Any]:
    base = {
        "mapping_enabled": False,
        "state": "deferred",
        "message": "UPnP 자동 매핑은 v1에서 실행하지 않고 수동 포트포워딩을 기본값으로 사용합니다.",
    }
    if not probe:
        return base
    discovered = _ssdp_gateway_discovery()
    if discovered:
        return {
            **base,
            "state": "discoverable",
            "message": "UPnP/IGD 응답은 감지됐지만 자동 매핑은 후속 구현으로 분리되어 있습니다.",
            "responses": discovered,
        }
    return {
        **base,
        "state": "not_discoverable",
        "message": "UPnP/IGD 응답을 찾지 못했습니다. 수동 포트포워딩을 사용하세요.",
        "responses": [],
    }


def _ssdp_gateway_discovery(timeout: float = 1.0) -> list[str]:
    message = (
        "M-SEARCH * HTTP/1.1\r\n"
        "HOST: 239.255.255.250:1900\r\n"
        'MAN: "ssdp:discover"\r\n'
        "MX: 1\r\n"
        "ST: urn:schemas-upnp-org:device:InternetGatewayDevice:1\r\n"
        "\r\n"
    ).encode("ascii")
    responses: list[str] = []
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.settimeout(timeout)
        sock.sendto(message, ("239.255.255.250", 1900))
        deadline = time.time() + timeout
        while time.time() < deadline and len(responses) < 4:
            try:
                data, _addr = sock.recvfrom(2048)
            except socket.timeout:
                break
            responses.append(data.decode("utf-8", errors="ignore")[:600])
    except OSError:
        return responses
    finally:
        try:
            sock.close()
        except Exception:
            pass
    return responses


def windows_network_snapshot() -> dict[str, Any]:
    if platform.system().lower() != "windows":
        return {"available": False, "message": "Windows 네트워크 세부 진단은 Windows Host에서만 실행됩니다."}
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        "Get-NetConnectionProfile | Select-Object -First 1 -Property Name,NetworkCategory,IPv4Connectivity | ConvertTo-Json -Compress",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"available": False, "message": f"Windows network profile 조회 실패: {exc}"}
    return {
        "available": result.returncode == 0,
        "stdout": (result.stdout or "").strip(),
        "stderr": (result.stderr or "").strip(),
        "message": "Windows network profile 조회 완료" if result.returncode == 0 else "Windows network profile 조회 실패",
    }
