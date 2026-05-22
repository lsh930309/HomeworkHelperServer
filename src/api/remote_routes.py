from __future__ import annotations

import os
import platform
import re
import time
import webbrowser
import datetime
import hashlib
import json
import uuid
from collections import defaultdict
from typing import Any, Callable, Iterable, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.api.runtime_config import resolve_api_port
from src.core.launcher import Launcher
from src.core.remote_audit import RemoteAuditLogger
from src.core.remote_pairing import RemoteDeviceRegistry
from src.core.remote_debug_log import load_config as load_remote_log_config, save_config as save_remote_log_config, write_event as write_remote_log
from src.core.remote_power import ConfigurablePowerController
from src.core.remote_power_setup import power_setup_status, register_public_key
from src.core.process_progress import calculate_process_progress
from src.core.tailscale import ensure_tailscale_ready, set_tailscale_network_enabled, suggest_remote_base_urls, tailscale_status
from src.data.database import data_dir
from src.core.remote_local_store import remote_store
from src.data import beholder, crud, models, schemas
from src.utils.game_preset_manager import GamePresetManager


REMOTE_API_VERSION = "0.2.0"
TEMPORARY_MACBOOK_TAILSCALE_IP = "100.114.138.46"
REMOTE_ICON_VARIANT_SIZES = (32, 64, 128, 256)


def _temporary_pairing_allowed_ips() -> set[str]:
    raw = os.environ.get("HH_REMOTE_DEV_ALLOWED_PAIRING_IPS")
    if raw is None:
        raw = TEMPORARY_MACBOOK_TAILSCALE_IP
    return {item.strip() for item in raw.split(",") if item.strip()}


def _looks_like_tailscale_ip(value: str | None) -> bool:
    return bool(value and re.match(r"^100\.\d{1,3}\.\d{1,3}\.\d{1,3}$", value.strip()))


class RemoteLaunchRequest(BaseModel):
    mode: Literal["shortcut", "direct", "launcher", "auto"] | None = None


class RemoteCommandResult(BaseModel):
    accepted: bool
    command: str
    target_id: str | None = None
    target_name: str | None = None
    target: str | None = None
    status: str
    message: str
    command_id: str | None = None
    accepted_at: float | None = None
    refresh_after_ms: int | None = None


class PairingConfirmRequest(BaseModel):
    code: str
    device_name: str
    platform: str | None = None


class RemoteMobileSessionStartRequest(BaseModel):
    game_link_id: str
    source: Literal["manual", "usage_stats"] = "manual"
    started_at: float | None = None


class RemoteMobileSessionEndRequest(BaseModel):
    session_id: str
    ended_at: float | None = None


class RemotePublicKeyRequest(BaseModel):
    public_key: str
    label: str = "HomeworkHelper Remote"


class RemoteLoggingConfigRequest(BaseModel):
    enabled: bool
    path: str | None = None


def _model_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    if hasattr(model, "dict"):
        return model.dict()
    return dict(model)


def _serialize_process(
    process: Any,
    *,
    current_dt: datetime.datetime | None = None,
    running_process_ids: set[str] | None = None,
    played_today_process_ids: set[str] | None = None,
) -> dict[str, Any]:
    if hasattr(schemas.ProcessSchema, "model_validate"):
        payload = _model_dump(schemas.ProcessSchema.model_validate(process))
    else:
        payload = _model_dump(schemas.ProcessSchema.from_orm(process))
    payload["progress"] = calculate_process_progress(process, current_dt=current_dt)
    process_id = str(payload.get("id") or getattr(process, "id", "") or "")
    if process_id and getattr(process, "user_preset_id", None):
        progress = payload.get("progress")
        if isinstance(progress, dict):
            progress["resource_icon_url"] = f"/api/dashboard/resource-icons/{quote(process_id, safe='')}?size=32"
            progress["resource_icon_urls"] = _resource_icon_urls(process_id)
    running_process_ids = running_process_ids or set()
    played_today_process_ids = played_today_process_ids or set()
    payload["icon_url"] = f"/api/dashboard/icons/{quote(process_id, safe='')}?size=128&format=png" if process_id else None
    payload["icon_urls"] = _process_icon_urls(process_id) if process_id else {}
    payload["is_running"] = process_id in running_process_ids
    payload["played_today"] = process_id in played_today_process_ids
    payload["status_text"] = "실행 중" if payload["is_running"] else ("오늘 실행" if payload["played_today"] else "대기")
    return payload


def _process_icon_urls(process_id: str) -> dict[str, str]:
    quoted = quote(process_id, safe="")
    return {
        str(size): f"/api/dashboard/icons/{quoted}?size={size}&format=png"
        for size in REMOTE_ICON_VARIANT_SIZES
    }


def _resource_icon_urls(process_id: str) -> dict[str, str]:
    quoted = quote(process_id, safe="")
    return {
        str(size): f"/api/dashboard/resource-icons/{quoted}?size={size}"
        for size in REMOTE_ICON_VARIANT_SIZES
    }


def _serialize_shortcut(shortcut: Any) -> dict[str, Any]:
    if hasattr(schemas.WebShortcutSchema, "model_validate"):
        return _model_dump(schemas.WebShortcutSchema.model_validate(shortcut))
    return _model_dump(schemas.WebShortcutSchema.from_orm(shortcut))


def _serialize_game_platform_link(link: Any) -> dict[str, Any]:
    if hasattr(schemas.GamePlatformLinkSchema, "model_validate"):
        return _model_dump(schemas.GamePlatformLinkSchema.model_validate(link))
    return _model_dump(schemas.GamePlatformLinkSchema.from_orm(link))


def _serialize_mobile_game_session(session: Any) -> dict[str, Any]:
    if hasattr(schemas.MobileGameSessionSchema, "model_validate"):
        return _model_dump(schemas.MobileGameSessionSchema.model_validate(session))
    return _model_dump(schemas.MobileGameSessionSchema.from_orm(session))


def _mobile_session_effective_end(session: Any, now_ts: float) -> float:
    if getattr(session, "ended_at", None) is not None:
        return float(session.ended_at)
    if getattr(session, "duration_seconds", None) is not None:
        return float(session.started_at) + float(session.duration_seconds)
    if getattr(session, "status", None) == "active":
        return now_ts
    return float(session.started_at)


def _mobile_session_metrics(
    sessions: Iterable[Any],
    *,
    start_ts: float,
    end_ts: float,
    now_ts: float,
) -> dict[str, Any]:
    total_seconds = 0.0
    active_seconds = 0.0
    session_count = 0
    active_session_count = 0
    games: dict[str, dict[str, Any]] = {}
    source_breakdown: dict[str, int] = defaultdict(int)

    for session in sessions:
        raw_start = float(session.started_at)
        raw_end = _mobile_session_effective_end(session, now_ts)
        overlap_start = max(raw_start, start_ts)
        overlap_end = min(raw_end, end_ts)
        if overlap_end <= overlap_start:
            continue

        overlap_seconds = overlap_end - overlap_start
        total_seconds += overlap_seconds
        session_count += 1
        source_breakdown[str(getattr(session, "source", None) or "manual")] += 1
        if getattr(session, "status", None) == "active":
            active_session_count += 1
            active_seconds += overlap_seconds

        process_id = str(getattr(session, "pc_process_id", "") or "")
        display_name = str(getattr(session, "pc_display_name", None) or process_id or "알 수 없는 게임")
        game = games.setdefault(
            process_id or display_name,
            {
                "process_id": process_id,
                "display_name": display_name,
                "android_package_name": str(getattr(session, "android_package_name", "") or ""),
                "total_seconds": 0.0,
                "session_count": 0,
                "active_session_count": 0,
            },
        )
        game["total_seconds"] += overlap_seconds
        game["session_count"] += 1
        if getattr(session, "status", None) == "active":
            game["active_session_count"] += 1

    game_rows = sorted(games.values(), key=lambda row: row["total_seconds"], reverse=True)
    for row in game_rows:
        row["total_seconds"] = round(row["total_seconds"], 3)
        row["share"] = round(row["total_seconds"] / total_seconds, 6) if total_seconds else 0

    return {
        "total_seconds": round(total_seconds, 3),
        "active_seconds": round(active_seconds, 3),
        "session_count": session_count,
        "active_session_count": active_session_count,
        "source_breakdown": dict(sorted(source_breakdown.items())),
        "top_game": game_rows[0] if game_rows else None,
        "games": game_rows,
    }


def _read_preset_by_id(preset_id: str | None) -> dict[str, Any] | None:
    if not preset_id:
        return None
    candidates = [GamePresetManager.SYSTEM_PRESET_FILE, GamePresetManager.USER_PRESET_FILE]
    for path in candidates:
        try:
            if not path.exists():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for preset in payload.get("presets", []):
            if preset.get("id") == preset_id:
                return preset
    return None


def _resolve_launcher_path(process: Any) -> str | None:
    """Mirror the PyQt launcher's preset-based launcher preference."""
    preset = _read_preset_by_id(getattr(process, "user_preset_id", None))
    patterns = preset.get("launcher_patterns") if preset else None
    if not patterns:
        return None

    base_candidates = [
        getattr(process, "launch_path", None),
        getattr(process, "monitoring_path", None),
    ]
    seen_dirs: set[str] = set()
    for candidate in base_candidates:
        if not candidate:
            continue
        base_dir = os.path.dirname(str(candidate))
        if not base_dir or base_dir in seen_dirs:
            continue
        seen_dirs.add(base_dir)
        for pattern in patterns:
            launcher_path = os.path.join(base_dir, str(pattern))
            if os.path.exists(launcher_path):
                return launcher_path
    return None


def _resolve_launch_target(process: Any, requested_mode: str | None = None) -> tuple[str | None, str]:
    """Resolve the same launch preference used by the PyQt main window.

    The remote API deliberately returns the chosen target for auditability, but
    leaves actual execution to ``Launcher`` so existing .url/.lnk/protocol logic
    remains centralized.
    """

    mode = requested_mode or getattr(process, "preferred_launch_type", None) or "shortcut"
    if mode == "direct":
        return (getattr(process, "monitoring_path", None) or getattr(process, "launch_path", None), mode)
    if mode == "shortcut":
        return (getattr(process, "launch_path", None) or getattr(process, "monitoring_path", None), mode)
    if mode == "launcher":
        return (_resolve_launcher_path(process) or getattr(process, "launch_path", None) or getattr(process, "monitoring_path", None), mode)
    return (getattr(process, "launch_path", None) or getattr(process, "monitoring_path", None), "auto")


def create_remote_router(
    get_db_dependency: Callable[[], Iterable[Session]],
    *,
    launcher_factory: Callable[[bool], Any] | None = None,
    shortcut_opener: Callable[[str], bool] | None = None,
    power_controller: Any | None = None,
    auditor: Any | None = None,
    device_registry: RemoteDeviceRegistry | None = None,
    auth_token: str | None = None,
    require_auth: bool = False,
    now: Callable[[], float] | None = None,
    tailscale_probe: Callable[[], Any] | None = None,
) -> APIRouter:
    """Create HomeworkHelper's native-client remote-control API router.

    The factory shape keeps the router testable without starting the packaged
    server process and makes later connectivity layers (Tailscale, Tunnel,
    relay) independent from the command surface.
    """

    router = APIRouter(prefix="/remote", tags=["remote"])
    launcher_factory = launcher_factory or (lambda run_as_admin: Launcher(run_as_admin=run_as_admin))
    shortcut_opener = shortcut_opener or webbrowser.open
    power_controller = power_controller or ConfigurablePowerController()
    auditor = auditor or RemoteAuditLogger()
    device_registry = device_registry or RemoteDeviceRegistry()
    auth_token = auth_token or os.environ.get("HH_REMOTE_TOKEN")
    now = now or time.time
    tailscale_probe = tailscale_probe or (lambda: tailscale_status(cache_ttl_seconds=30.0))

    def _bearer_token(authorization: str | None) -> str | None:
        if not authorization:
            return None
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return None
        return token

    def _is_loopback_request(request: Request) -> bool:
        host = request.client.host if request.client else ""
        return host in {"127.0.0.1", "::1", "localhost", "testclient"}

    def _is_temporary_pairing_allowed_request(request: Request) -> bool:
        host = request.client.host if request.client else ""
        return host in _temporary_pairing_allowed_ips()

    def _request_host(request: Request) -> str:
        return request.client.host if request.client else ""

    def _tailscale_snapshot_payload() -> tuple[dict[str, Any], Any | None]:
        try:
            snapshot = tailscale_probe()
            payload = snapshot.as_dict() if hasattr(snapshot, "as_dict") else dict(snapshot)
            return payload, snapshot
        except Exception as exc:
            return {
                "installed": False,
                "running": False,
                "backend_state": "error",
                "state": "missing",
                "foundation_state": "missing",
                "self_ips": [],
                "self_hostname": "",
                "self_node_id": "",
                "peers": [],
                "message": f"tailscale 상태 확인 실패: {exc}",
            }, None

    def _primary_tailnet_ip(ips: Iterable[Any] | None) -> str:
        for ip in ips or []:
            candidate = str(ip or "").strip()
            if _looks_like_tailscale_ip(candidate):
                return candidate
        return ""

    def _peer_binding(peer: dict[str, Any]) -> dict[str, Any]:
        tailnet_ip = str(peer.get("primary_ipv4") or "").strip() or _primary_tailnet_ip(peer.get("ips") or [])
        return {
            "tailnet_ip": tailnet_ip,
            "tailnet_ips": [str(ip) for ip in (peer.get("ips") or []) if str(ip or "").strip()],
            "tailnet_dns_name": str(peer.get("dns_name") or "").strip(),
            "tailnet_hostname": str(peer.get("hostname") or "").strip(),
            "tailnet_os": str(peer.get("os") or "").strip(),
            "tailnet_node_id": str(peer.get("node_id") or "").strip(),
        }

    def _peer_binding_for_ip(tailnet_ip: str) -> dict[str, Any]:
        if not _looks_like_tailscale_ip(tailnet_ip):
            return {}
        payload, _snapshot = _tailscale_snapshot_payload()
        for peer in payload.get("peers") or []:
            binding = _peer_binding(peer)
            if tailnet_ip == binding.get("tailnet_ip") or tailnet_ip in binding.get("tailnet_ips", []):
                return binding
        return {"tailnet_ip": tailnet_ip, "tailnet_ips": [tailnet_ip]}

    def _suggested_base_urls(tailscale_payload: dict[str, Any], ts_snapshot: Any | None) -> list[str]:
        if ts_snapshot is not None and hasattr(ts_snapshot, "peers"):
            return suggest_remote_base_urls(ts_snapshot, port=resolve_api_port())
        return [
            f"http://{binding['tailnet_ip']}:{resolve_api_port()}"
            for binding in (_peer_binding(peer) for peer in tailscale_payload.get("peers") or [])
            if binding.get("tailnet_ip")
        ]

    def _normalized_device_name(value: Any) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())

    def _peer_name_keys(peer: dict[str, Any]) -> set[str]:
        hostname = str(peer.get("tailnet_hostname") or peer.get("hostname") or "")
        dns_name = str(peer.get("tailnet_dns_name") or peer.get("dns_name") or "")
        dns_label = dns_name.split(".", 1)[0] if dns_name else ""
        return {
            key
            for key in (
                _normalized_device_name(hostname),
                _normalized_device_name(dns_label),
            )
            if key
        }

    def _normalized_platform(value: Any) -> str:
        raw = str(value or "").lower()
        if raw in {"macos", "darwin", "mac"}:
            return "macos"
        if raw in {"windows", "win32", "win"}:
            return "windows"
        if raw in {"android"}:
            return "android"
        return raw

    def _match_peer_for_device(
        device: dict[str, Any],
        peers_by_ip: dict[str, dict[str, Any]],
        used_tailnet_ips: set[str],
    ) -> tuple[dict[str, Any] | None, bool]:
        available = {
            tailnet_ip: peer
            for tailnet_ip, peer in peers_by_ip.items()
            if tailnet_ip not in used_tailnet_ips
        }
        for key in ("tailnet_ip", "last_source_ip"):
            tailnet_ip = str(device.get(key) or "").strip()
            if tailnet_ip in available:
                return available[tailnet_ip], True

        device_name = _normalized_device_name(device.get("name"))
        if device_name:
            name_matches = [
                peer
                for peer in available.values()
                if any(
                    device_name == key or key.startswith(device_name) or device_name.startswith(key)
                    for key in _peer_name_keys(peer)
                )
            ]
            if len(name_matches) == 1:
                return name_matches[0], True

        device_platform = _normalized_platform(device.get("platform"))
        if device_platform:
            os_matches = [
                peer
                for peer in available.values()
                if _normalized_platform(peer.get("tailnet_os") or peer.get("os")) == device_platform
            ]
            if len(os_matches) == 1:
                return os_matches[0], False
        return None, False

    def _connectivity_state(device: dict[str, Any], peer: dict[str, Any] | None) -> tuple[str, str]:
        if device.get("role") == "host":
            return "local", "이 HomeworkHelper Host가 실행 중인 기기입니다."
        if device.get("revoked_at"):
            return "revoked", "페어링 토큰이 폐기되었습니다."
        if peer and peer.get("online"):
            if device.get("last_seen_at"):
                return "active", "Tailnet online 및 Remote API 통신 이력이 있습니다."
            return "tailnet_online", "Tailnet에는 보이지만 Remote API 통신 이력은 아직 없습니다."
        if peer:
            return "tailnet_offline", "Tailnet peer는 알려져 있지만 현재 offline으로 표시됩니다."
        if device.get("last_seen_at"):
            return "stale_or_offline", "최근 Remote API 통신 이력은 있지만 현재 tailnet status에서 찾지 못했습니다."
        return "unknown", "Tailnet 매칭 전인 페어링 기기입니다."

    def _device_display_name(device: dict[str, Any]) -> str:
        return str(
            device.get("name")
            or device.get("tailnet_hostname")
            or device.get("tailnet_dns_name")
            or device.get("tailnet_ip")
            or device.get("id")
            or ""
        )

    def _host_device_sort_key(device: dict[str, Any]) -> tuple[int, str, str]:
        pairing_status = str(device.get("pairing_status") or "")
        role = str(device.get("role") or "")
        if role == "host":
            rank = 0
        elif pairing_status == "paired":
            rank = 1
        elif pairing_status == "tailnet_unpaired":
            rank = 2
        elif pairing_status == "revoked":
            rank = 3
        else:
            rank = 2
        return (
            rank,
            _normalized_device_name(_device_display_name(device)),
            str(device.get("tailnet_ip") or device.get("id") or ""),
        )

    def _managed_device_rows() -> list[dict[str, Any]]:
        paired_devices = device_registry.list_devices()
        tailscale_payload, _snapshot = _tailscale_snapshot_payload()
        self_ips = {
            str(ip or "").strip()
            for ip in (tailscale_payload.get("self_ips") or [])
            if str(ip or "").strip()
        }
        peers_by_ip: dict[str, dict[str, Any]] = {}
        for peer in tailscale_payload.get("peers") or []:
            binding = _peer_binding(peer)
            tailnet_ip = binding.get("tailnet_ip")
            if tailnet_ip and tailnet_ip not in self_ips:
                row = {**peer, **binding}
                peers_by_ip[tailnet_ip] = row

        rows: list[dict[str, Any]] = []
        used_tailnet_ips: set[str] = set()
        for device in paired_devices:
            peer, should_backfill = _match_peer_for_device(device, peers_by_ip, used_tailnet_ips)
            state, message = _connectivity_state(device, peer)
            tailnet_fields = _peer_binding(peer) if peer else {}
            tailnet_ip = tailnet_fields.get("tailnet_ip") or str(device.get("tailnet_ip") or "").strip()
            if tailnet_ip and peer:
                used_tailnet_ips.add(tailnet_ip)
                if should_backfill:
                    device_registry.bind_tailnet_device(str(device.get("id") or ""), tailnet_fields, now=now())
            rows.append({
                **device,
                **{key: value for key, value in tailnet_fields.items() if value},
                "role": device.get("role") or "client",
                "pairing_status": "revoked" if device.get("revoked_at") else "paired",
                "tailnet_online": bool(peer and peer.get("online")),
                "connectivity_state": state,
                "health_message": message,
                "can_revoke": not bool(device.get("revoked_at")) and (device.get("role") or "client") == "client",
            })

        host_ip = _primary_tailnet_ip(tailscale_payload.get("self_ips") or [])
        if host_ip:
            rows.append({
                "id": f"host:{host_ip}",
                "name": tailscale_payload.get("self_hostname") or "HomeworkHelper Host",
                "platform": platform.system().lower() or "host",
                "role": "host",
                "tailnet_ip": host_ip,
                "tailnet_ips": list(tailscale_payload.get("self_ips") or []),
                "tailnet_dns_name": "",
                "tailnet_hostname": tailscale_payload.get("self_hostname") or "",
                "tailnet_os": platform.system().lower() or "",
                "tailnet_node_id": tailscale_payload.get("self_node_id") or "",
                "created_at": None,
                "last_seen_at": None,
                "last_source_ip": None,
                "token_refreshed_at": None,
                "tailnet_bound_at": None,
                "revoked_at": None,
                "pairing_status": "host",
                "tailnet_online": bool(tailscale_payload.get("running")),
                "connectivity_state": "local",
                "health_message": "이 HomeworkHelper Host가 실행 중인 기기입니다.",
                "can_revoke": False,
            })

        for tailnet_ip, peer in peers_by_ip.items():
            if tailnet_ip in used_tailnet_ips:
                continue
            binding = _peer_binding(peer)
            rows.append({
                "id": f"tailnet:{tailnet_ip}",
                "name": binding.get("tailnet_hostname") or binding.get("tailnet_dns_name") or tailnet_ip,
                "platform": binding.get("tailnet_os") or "unknown",
                "role": "unknown",
                **binding,
                "created_at": None,
                "last_seen_at": None,
                "last_source_ip": None,
                "token_refreshed_at": None,
                "tailnet_bound_at": None,
                "revoked_at": None,
                "pairing_status": "tailnet_unpaired",
                "tailnet_online": bool(peer.get("online")),
                "connectivity_state": "tailnet_online_unpaired" if peer.get("online") else "tailnet_offline_unpaired",
                "health_message": "같은 tailnet에 보이지만 HomeworkHelper 페어링은 없습니다.",
                "can_revoke": False,
            })
        return sorted(rows, key=_host_device_sort_key)

    def _is_valid_remote_token(request: Request, authorization: str | None) -> bool:
        token = _bearer_token(authorization)
        if not token:
            return False
        if auth_token and secrets_compare(token, auth_token):
            return True
        return bool(device_registry.validate_token(token, now=now(), source_ip=_request_host(request)))

    def _is_local_management_path(path: str, method: str) -> bool:
        if path.endswith("/remote/readiness") or path.endswith("/remote/capabilities"):
            return method == "GET"
        if path.endswith("/remote/devices"):
            return method == "GET"
        if "/remote/devices/" in path:
            return method == "DELETE"
        if path.endswith("/remote/power/setup"):
            return method == "GET"
        if path.endswith("/remote/power/ssh-key"):
            return method == "POST"
        if path.endswith("/remote/logging/config"):
            return method in {"GET", "PUT"}
        if path.endswith("/remote/devices/revoked"):
            return method == "DELETE"
        if path.endswith("/remote/tailscale/ensure"):
            return method == "POST"
        if path.endswith("/remote/tailscale/up") or path.endswith("/remote/tailscale/down"):
            return method == "POST"
        return False

    def require_remote_auth(request: Request, authorization: str | None = Header(None)) -> None:
        path = request.url.path.rstrip("/")
        method = request.method.upper()
        if path.endswith("/remote/pair/confirm"):
            return
        if path.endswith("/remote/pair/start") and (
            _is_loopback_request(request)
            or _is_temporary_pairing_allowed_request(request)
            or _is_valid_remote_token(request, authorization)
        ):
            return
        if _is_loopback_request(request) and _is_local_management_path(path, method):
            return
        if path.endswith("/remote/pair/start"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="페어링 코드 발급은 로컬 요청 또는 인증된 디바이스에서만 가능합니다.",
            )
        if not require_auth and not auth_token and not device_registry.has_registered_devices():
            return
        if _is_valid_remote_token(request, authorization):
            return
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Remote API 인증 토큰이 필요합니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    router.dependencies.append(Depends(require_remote_auth))

    def _remote_capabilities(power_status: dict[str, Any]) -> dict[str, bool]:
        return {
            "process_launch": True,
            "shortcut_open": True,
            "dashboard_summary": True,
            "beholder_incidents": True,
            "game_links": True,
            "mobile_sessions": True,
            "power_config": False,
            "power_control": False,
            "beholder": True,
            "auth_required": bool(require_auth or auth_token or device_registry.has_registered_devices()),
            "pairing": True,
            "tailscale_discovery": True,
            "readiness": True,
            "local_store_health": True,
        }

    def _readiness_payload(
        power_status: dict[str, Any],
        *,
        active_beholder_incidents: int | None = None,
        include_tailscale_details: bool = True,
    ) -> dict[str, Any]:
        tailscale_payload: dict[str, Any] = {}
        ts_snapshot = None
        if include_tailscale_details:
            tailscale_payload, ts_snapshot = _tailscale_snapshot_payload()
        tailscale_ready = bool(
            include_tailscale_details
            and tailscale_payload.get("installed")
            and tailscale_payload.get("running")
        )
        power_ready = bool(power_status.get("configured"))
        auth_ready = bool(require_auth or auth_token or device_registry.has_registered_devices())
        beholder_state = "ok" if not active_beholder_incidents else "warning"
        remote_state = "ok" if auth_ready else "warning"
        server_state = "ok" if auth_ready and (tailscale_ready or not include_tailscale_details) else "warning"
        if include_tailscale_details:
            tailscale_section = {
                "state": "ok" if tailscale_ready else "warning",
                "color": "green" if tailscale_ready else "yellow",
                "message": tailscale_payload.get("message") or "tailscale 상태 미확인",
                "foundation_state": tailscale_payload.get("foundation_state") or tailscale_payload.get("state") or ("ready" if tailscale_ready else "installed"),
                "suggested_base_urls": _suggested_base_urls(tailscale_payload, ts_snapshot) if tailscale_ready else [],
                "details": tailscale_payload,
            }
        else:
            tailscale_section = {
                "state": "deferred",
                "color": "yellow",
                "message": "상세 Tailscale 점검은 /remote/readiness에서 확인하세요.",
                "suggested_base_urls": [],
            }
        return {
            "beholder_health": {
                "state": beholder_state,
                "color": "green" if beholder_state == "ok" else "yellow",
                "message": "Beholder 대기 중인 incident 없음" if beholder_state == "ok" else f"Beholder incident {active_beholder_incidents}건 확인 필요",
                "active_incidents": int(active_beholder_incidents or 0),
            },
            "remote_connectivity": {
                "state": remote_state,
                "color": "green" if remote_state == "ok" else "yellow",
                "message": "Remote 인증/페어링 준비됨" if auth_ready else "첫 페어링 전에는 로컬 pair/start로 시작하세요.",
                "auth_required": bool(require_auth or auth_token or device_registry.has_registered_devices()),
            },
            "server_mode_readiness": {
                "state": server_state,
                "color": "green" if server_state == "ok" else "yellow",
                "message": (
                    "Remote Agent HTTP 응답 중"
                    if server_state == "ok" and not include_tailscale_details
                    else "서버 모드 준비됨"
                    if server_state == "ok"
                    else "Tailscale 또는 페어링 준비가 더 필요합니다."
                ),
            },
            "power_readiness": {
                "state": "ok" if power_ready else "warning",
                "color": "green" if power_ready else "yellow",
                "message": power_status.get("message") or (
                    "클라이언트 직접 전원 경로 설정됨" if power_ready else "클라이언트 직접 전원 경로 미설정"
                ),
                "supported_actions": power_status.get("supported_actions") or [],
            },
            "tailscale_readiness": tailscale_section,
        }

    def _state_fingerprint(db: Session, power_status: dict[str, Any], *, processes: Iterable[Any] | None = None) -> dict[str, Any]:
        """Small, stable fingerprint for native-client revision-aware polling."""

        process_rows = []
        max_updated_at = 0.0
        process_source = list(processes) if processes is not None else list(crud.get_processes(db))
        for process in process_source:
            last_played = getattr(process, "last_played_timestamp", None)
            stamina_updated = getattr(process, "stamina_updated_at", None)
            resource_updated = getattr(process, "resource_updated_at", None)
            for candidate in (last_played, stamina_updated, resource_updated):
                if candidate is not None:
                    max_updated_at = max(max_updated_at, float(candidate))
            process_rows.append(
                {
                    "id": getattr(process, "id", None),
                    "name": getattr(process, "name", None),
                    "monitoring_path": getattr(process, "monitoring_path", None),
                    "launch_path": getattr(process, "launch_path", None),
                    "preferred_launch_type": getattr(process, "preferred_launch_type", None),
                    "last_played_timestamp": last_played,
                    "user_cycle_hours": getattr(process, "user_cycle_hours", None),
                    "user_preset_id": getattr(process, "user_preset_id", None),
                    "stamina_tracking_enabled": getattr(process, "stamina_tracking_enabled", None),
                    "hoyolab_game_id": getattr(process, "hoyolab_game_id", None),
                    "stamina_current": getattr(process, "stamina_current", None),
                    "stamina_max": getattr(process, "stamina_max", None),
                    "stamina_updated_at": stamina_updated,
                    "resource_tracking_enabled": getattr(process, "resource_tracking_enabled", None),
                    "resource_provider": getattr(process, "resource_provider", None),
                    "resource_key": getattr(process, "resource_key", None),
                    "resource_label": getattr(process, "resource_label", None),
                    "resource_percent": getattr(process, "resource_percent", None),
                    "resource_updated_at": resource_updated,
                    "resource_status": getattr(process, "resource_status", None),
                }
            )

        active_sessions = []
        for session in db.query(models.ProcessSession).filter(models.ProcessSession.end_timestamp.is_(None)).all():
            start = getattr(session, "start_timestamp", None)
            if start is not None:
                max_updated_at = max(max_updated_at, float(start))
            active_sessions.append(
                {
                    "process_id": getattr(session, "process_id", None),
                    "process_name": getattr(session, "process_name", None),
                    "start_timestamp": start,
                    "heartbeat_timestamp": getattr(session, "heartbeat_timestamp", None),
                    "session_status": getattr(session, "session_status", None),
                }
            )

        game_link_rows = []
        try:
            for link in crud.get_game_platform_links(db):
                updated = getattr(link, "updated_at", None)
                if updated is not None:
                    max_updated_at = max(max_updated_at, float(updated))
                game_link_rows.append(
                    {
                        "id": getattr(link, "id", None),
                        "pc_process_id": getattr(link, "pc_process_id", None),
                        "android_package_name": getattr(link, "android_package_name", None),
                        "sync_strategy": getattr(link, "sync_strategy", None),
                        "updated_at": updated,
                    }
                )
        except Exception:
            game_link_rows = []

        mobile_rows = []
        try:
            for session in crud.get_active_mobile_game_sessions(db):
                start = getattr(session, "started_at", None)
                if start is not None:
                    max_updated_at = max(max_updated_at, float(start))
                mobile_rows.append(
                    {
                        "id": getattr(session, "id", None),
                        "game_link_id": getattr(session, "game_link_id", None),
                        "pc_process_id": getattr(session, "pc_process_id", None),
                        "status": getattr(session, "status", None),
                        "started_at": start,
                    }
                )
        except Exception:
            mobile_rows = []

        incident_rows = []
        try:
            for incident in beholder.active_incidents(db):
                created = getattr(incident, "created_at", None)
                if created is not None:
                    max_updated_at = max(max_updated_at, float(created))
                incident_rows.append(
                    {
                        "id": getattr(incident, "id", None),
                        "severity": getattr(incident, "severity", None),
                        "status": getattr(incident, "status", None),
                        "risk_score": getattr(incident, "risk_score", None),
                        "created_at": created,
                    }
                )
        except Exception:
            incident_rows = []

        return {
            "remote_api_version": REMOTE_API_VERSION,
            "processes": sorted(process_rows, key=lambda row: str(row.get("id") or "")),
            "active_sessions": sorted(active_sessions, key=lambda row: (str(row.get("process_id") or ""), float(row.get("start_timestamp") or 0))),
            "game_links": sorted(game_link_rows, key=lambda row: str(row.get("id") or "")),
            "mobile_sessions": sorted(mobile_rows, key=lambda row: str(row.get("id") or "")),
            "beholder_incidents": sorted(incident_rows, key=lambda row: str(row.get("id") or "")),
            "power": {
                "configured": bool(power_status.get("configured")),
                "status": power_status.get("status"),
                "supported_actions": power_status.get("supported_actions") or [],
            },
            "updated_at": max_updated_at,
        }

    def _state_revision_payload(
        db: Session,
        power_status: dict[str, Any],
        *,
        processes: Iterable[Any] | None = None,
    ) -> dict[str, Any]:
        fingerprint = _state_fingerprint(db, power_status, processes=processes)
        canonical = json.dumps(fingerprint, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return {
            "state_revision": hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16],
            "updated_at": fingerprint["updated_at"] or None,
        }

    @router.post("/pair/start")
    def start_remote_pairing():
        pairing = device_registry.start_pairing(now=now())
        auditor.record(
            command="pair.start",
            accepted=True,
            status="accepted",
            target="remote_devices",
            metadata={"expires_at": pairing["expires_at"], "ttl_seconds": device_registry.code_ttl_seconds},
        )
        return {
            "code": pairing["code"],
            "expires_at": pairing["expires_at"],
            "ttl_seconds": device_registry.code_ttl_seconds,
            "message": "macOS/Android 앱에서 이 코드를 입력해 페어링을 완료하세요.",
        }

    @router.post("/pair/confirm")
    def confirm_remote_pairing(request: Request, pair_request: PairingConfirmRequest):
        source_ip = _request_host(request)
        tailnet_binding = _peer_binding_for_ip(source_ip) if _looks_like_tailscale_ip(source_ip) else {}
        device = device_registry.confirm_pairing(
            code=pair_request.code,
            device_name=pair_request.device_name,
            platform=pair_request.platform,
            role="client",
            tailnet_binding=tailnet_binding,
            now=now(),
        )
        if not device:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="페어링 코드가 올바르지 않거나 만료되었습니다.")
        write_remote_log("pair.confirm", device_name=device.get("name"), platform=device.get("platform"))
        auditor.record(
            command="pair.confirm",
            accepted=True,
            status="accepted",
            target_id=device.get("id"),
            target_name=device.get("name"),
            target=device.get("platform"),
        )
        power_status = power_controller.status() if hasattr(power_controller, "status") else {}
        response = dict(device)
        response["onboarding"] = {
            "readiness": _readiness_payload(power_status),
            "power_setup": power_setup_status(),
            "message": "페어링 완료. 클라이언트에서 SSH key, Tailscale, SmartThings wake 경로를 이어서 자동 점검할 수 있습니다.",
        }
        return response

    @router.get("/devices")
    def list_remote_devices():
        return {"devices": _managed_device_rows()}

    @router.delete("/devices/revoked")
    def purge_revoked_remote_devices():
        removed = device_registry.purge_revoked_devices()
        write_remote_log("devices.purge_revoked", removed=removed)
        auditor.record(command="device.purge_revoked", accepted=True, status="accepted", metadata={"removed": removed})
        return {"removed": removed}

    @router.delete("/devices/{device_id}")
    def revoke_remote_device(device_id: str):
        if not device_registry.revoke_device(device_id, now=now()):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="디바이스를 찾을 수 없습니다.")
        auditor.record(
            command="device.revoke",
            accepted=True,
            status="accepted",
            target_id=device_id,
        )
        return {"revoked": True, "device_id": device_id}

    @router.post("/tokens/refresh")
    def refresh_remote_device_token(request: Request, authorization: str | None = Header(None)):
        token = _bearer_token(authorization)
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="갱신할 device Bearer token이 필요합니다.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        device = device_registry.refresh_token(token, now=now(), source_ip=_request_host(request))
        if not device:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="갱신 가능한 device token을 찾을 수 없습니다.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        auditor.record(
            command="token.refresh",
            accepted=True,
            status="accepted",
            target_id=device.get("id"),
            target_name=device.get("name"),
            target=device.get("platform"),
        )
        return device

    @router.get("/status")
    def remote_status(db: Session = Depends(get_db_dependency)):
        handler_started_at = time.perf_counter()
        diagnostics: dict[str, Any] = {"readiness_mode": "lightweight"}

        process_started_at = time.perf_counter()
        processes = crud.get_processes(db)
        diagnostics["processes_ms"] = round((time.perf_counter() - process_started_at) * 1000, 2)

        shortcuts_started_at = time.perf_counter()
        shortcuts = crud.get_shortcuts(db)
        diagnostics["shortcuts_ms"] = round((time.perf_counter() - shortcuts_started_at) * 1000, 2)

        active_started_at = time.perf_counter()
        active_count = 0
        try:
            active_count = db.query(models.ProcessSession).filter(models.ProcessSession.end_timestamp.is_(None)).count()
        except Exception:
            active_count = 0
        diagnostics["active_sessions_ms"] = round((time.perf_counter() - active_started_at) * 1000, 2)

        power_started_at = time.perf_counter()
        power_status = power_controller.status() if hasattr(power_controller, "status") else {}
        diagnostics["power_status_ms"] = round((time.perf_counter() - power_started_at) * 1000, 2)

        revision_started_at = time.perf_counter()
        revision_payload = _state_revision_payload(db, power_status, processes=processes)
        diagnostics["state_revision_ms"] = round((time.perf_counter() - revision_started_at) * 1000, 2)

        beholder_started_at = time.perf_counter()
        active_beholder_count = len(beholder.active_incidents(db))
        diagnostics["beholder_ms"] = round((time.perf_counter() - beholder_started_at) * 1000, 2)

        readiness_started_at = time.perf_counter()
        readiness_payload = _readiness_payload(
            power_status,
            active_beholder_incidents=active_beholder_count,
            include_tailscale_details=False,
        )
        diagnostics["readiness_ms"] = round((time.perf_counter() - readiness_started_at) * 1000, 2)
        diagnostics["duration_ms"] = round((time.perf_counter() - handler_started_at) * 1000, 2)
        return {
            "app": "HomeworkHelper",
            "remote_api_version": REMOTE_API_VERSION,
            "server_time": now(),
            **revision_payload,
            "host": {
                "platform": platform.system() or "unknown",
                "release": platform.release(),
                "pid": os.getpid(),
            },
            "counts": {
                "processes": len(processes),
                "shortcuts": len(shortcuts),
                "active_sessions": active_count,
            },
            "capabilities": _remote_capabilities(power_status),
            "power": power_status,
            "readiness": readiness_payload,
            "diagnostics": diagnostics,
        }

    @router.get("/capabilities")
    def remote_capabilities(db: Session = Depends(get_db_dependency)):
        power_status = power_controller.status() if hasattr(power_controller, "status") else {}
        revision_payload = _state_revision_payload(db, power_status)
        return {
            "remote_api_version": REMOTE_API_VERSION,
            **revision_payload,
            "capabilities": _remote_capabilities(power_status),
            "power": power_status,
            "readiness": _readiness_payload(power_status),
        }

    @router.get("/readiness")
    def remote_readiness():
        power_status = power_controller.status() if hasattr(power_controller, "status") else {}
        return _readiness_payload(power_status)

    @router.get("/logging/config")
    def remote_logging_config():
        return load_remote_log_config()

    @router.put("/logging/config")
    def update_remote_logging_config(request: RemoteLoggingConfigRequest):
        config = save_remote_log_config(request.enabled, request.path)
        write_remote_log("logging.config", enabled=config.get("enabled"), path=config.get("path"))
        return config

    @router.get("/local-store/health")
    def remote_local_store_health():
        report = remote_store().integrity_report()
        if not report.get("ok"):
            write_remote_log("local_store.integrity", **report)
        return report

    @router.post("/tailscale/ensure")
    def remote_tailscale_ensure():
        result = ensure_tailscale_ready()
        write_remote_log("tailscale.ensure", ready=result.ready, method=result.method, message=result.message)
        auditor.record(
            command="tailscale.ensure",
            accepted=bool(result.ready),
            status="ready" if result.ready else "not_ready",
            target=result.method,
            metadata={
                "install_attempted": result.install_attempted,
                "launch_attempted": result.launch_attempted,
            },
        )
        return result.as_dict()

    @router.post("/tailscale/up")
    def remote_tailscale_up():
        result = set_tailscale_network_enabled(True)
        write_remote_log("tailscale.up", ready=result.after.ready, method=result.method, message=result.message)
        auditor.record(
            command="tailscale.up",
            accepted=bool(result.succeeded),
            status="ready" if result.after.ready else result.after.foundation_state,
            target=result.method,
        )
        return result.as_dict()

    @router.post("/tailscale/down")
    def remote_tailscale_down(request: Request):
        if not _is_loopback_request(request):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tailscale down은 호스트 로컬 설정 화면에서만 실행할 수 있습니다.")
        result = set_tailscale_network_enabled(False)
        write_remote_log("tailscale.down", ready=result.after.ready, method=result.method, message=result.message)
        auditor.record(
            command="tailscale.down",
            accepted=bool(result.succeeded),
            status="down" if result.succeeded else result.after.foundation_state,
            target=result.method,
        )
        return result.as_dict()

    @router.get("/power/setup")
    def remote_power_setup():
        return power_setup_status()

    @router.post("/power/ssh-key")
    def remote_power_register_ssh_key(request: RemotePublicKeyRequest):
        try:
            result = register_public_key(request.public_key, label=request.label)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        auditor.record(
            command="power.ssh_key.register",
            accepted=bool(result.get("registered") or result.get("already_present")),
            status="registered" if result.get("registered") else "already_present" if result.get("already_present") else "rejected",
            target=result.get("authorized_keys_path"),
        )
        return result

    @router.get("/dashboard/summary")
    def remote_dashboard_summary(
        start: str | None = None,
        end: str | None = None,
        game_id: str = "all",
        show_unregistered: bool = False,
        db: Session = Depends(get_db_dependency),
    ):
        """Expose the dashboard's read-only playtime summary through /remote.

        Native clients should not call the general dashboard API surface
        directly.  This endpoint keeps analytics read-only and under the same
        Remote API auth/pairing boundary used for commands.
        """

        from src.api.dashboard.routes import (
            _aggregate_summary,
            _build_game_groups,
            _resolve_range,
            _sessions_for_range,
        )

        try:
            start_date, end_date, start_dt, end_dt = _resolve_range(start, end)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

        start_date, end_date, start_dt, end_dt, sessions = _sessions_for_range(
            db,
            start_date,
            end_date,
            start_dt,
            end_dt,
            game_id,
            show_unregistered,
        )
        groups = _build_game_groups(db, sessions, show_unregistered)
        mobile_sessions = db.query(models.MobileGameSession).filter(
            models.MobileGameSession.started_at < end_dt.timestamp(),
        ).all()
        return {
            "range": {"start": start_date.isoformat(), "end": end_date.isoformat()},
            "metrics": _aggregate_summary(sessions, start_dt, end_dt, groups),
            "mobile_metrics": _mobile_session_metrics(
                mobile_sessions,
                start_ts=start_dt.timestamp(),
                end_ts=end_dt.timestamp(),
                now_ts=now(),
            ),
        }

    @router.get("/beholder/incidents")
    def remote_beholder_incidents(db: Session = Depends(get_db_dependency)):
        """Read-only Beholder incident list for native remote dashboards."""

        incidents = [beholder.incident_to_dict(incident) for incident in beholder.active_incidents(db)]
        return {"incidents": incidents, "count": len(incidents)}


    @router.get("/game-links")
    def list_remote_game_links(db: Session = Depends(get_db_dependency)):
        links = [_serialize_game_platform_link(link) for link in crud.get_game_platform_links(db)]
        return {"links": links, "count": len(links)}

    @router.post("/game-links")
    def create_remote_game_link(request: schemas.GamePlatformLinkCreate, db: Session = Depends(get_db_dependency)):
        process = crud.get_process_by_id(db, request.pc_process_id)
        if process is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="연결할 PC 프로세스를 찾을 수 없습니다.")
        if not request.pc_display_name:
            request.pc_display_name = getattr(process, "name", None)
        try:
            link = crud.create_game_platform_link(db, request, timestamp=now())
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        auditor.record(
            command="game_link.create",
            accepted=True,
            status="accepted",
            target_id=link.id,
            target_name=link.pc_display_name,
            target=link.android_package_name,
            metadata={"pc_process_id": link.pc_process_id, "sync_strategy": link.sync_strategy},
        )
        return _serialize_game_platform_link(link)


    @router.get("/mobile-sessions/active")
    def list_active_remote_mobile_sessions(db: Session = Depends(get_db_dependency)):
        sessions = [_serialize_mobile_game_session(session) for session in crud.get_active_mobile_game_sessions(db)]
        return {"sessions": sessions, "count": len(sessions)}

    @router.post("/mobile-sessions/start")
    def start_remote_mobile_session(request: RemoteMobileSessionStartRequest, db: Session = Depends(get_db_dependency)):
        try:
            session = crud.start_mobile_game_session(
                db,
                game_link_id=request.game_link_id,
                source=request.source,
                started_at=request.started_at,
                timestamp=now(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
        auditor.record(
            command="mobile_session.start",
            accepted=True,
            status="accepted",
            target_id=session.id,
            target_name=session.pc_display_name,
            target=session.android_package_name,
            metadata={"game_link_id": session.game_link_id, "source": session.source},
        )
        return _serialize_mobile_game_session(session)

    @router.post("/mobile-sessions/end")
    def end_remote_mobile_session(request: RemoteMobileSessionEndRequest, db: Session = Depends(get_db_dependency)):
        session = crud.end_mobile_game_session(
            db,
            session_id=request.session_id,
            ended_at=request.ended_at,
            timestamp=now(),
        )
        if session is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="활성 모바일 세션을 찾을 수 없습니다.")
        auditor.record(
            command="mobile_session.end",
            accepted=True,
            status="accepted",
            target_id=session.id,
            target_name=session.pc_display_name,
            target=session.android_package_name,
            metadata={"game_link_id": session.game_link_id, "duration_seconds": session.duration_seconds},
        )
        return _serialize_mobile_game_session(session)

    @router.get("/processes")
    def list_remote_processes(db: Session = Depends(get_db_dependency)):
        current_dt = datetime.datetime.fromtimestamp(now())
        start_of_day = current_dt.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        current_ts = current_dt.timestamp()
        running_process_ids = {
            row[0]
            for row in db.query(models.ProcessSession.process_id)
            .filter(models.ProcessSession.end_timestamp.is_(None))
            .distinct()
            .all()
            if row[0]
        }
        played_today_process_ids = {
            row[0]
            for row in db.query(models.ProcessSession.process_id)
            .filter(
                models.ProcessSession.start_timestamp <= current_ts,
                (
                    (models.ProcessSession.end_timestamp.is_(None) & (models.ProcessSession.start_timestamp >= start_of_day))
                    | (models.ProcessSession.end_timestamp >= start_of_day)
                ),
            )
            .distinct()
            .all()
            if row[0]
        }
        played_today_process_ids.update(running_process_ids)
        processes = list(crud.get_processes(db))
        for process in processes:
            last_played = getattr(process, "last_played_timestamp", None)
            if last_played is not None and float(last_played) >= start_of_day:
                played_today_process_ids.add(process.id)
        return [
            _serialize_process(
                process,
                current_dt=current_dt,
                running_process_ids=running_process_ids,
                played_today_process_ids=played_today_process_ids,
            )
            for process in processes
        ]

    @router.post("/processes/{process_id}/launch", response_model=RemoteCommandResult)
    def launch_remote_process(
        process_id: str,
        request: RemoteLaunchRequest | None = None,
        db: Session = Depends(get_db_dependency),
    ):
        process = crud.get_process_by_id(db, process_id)
        if process is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="프로세스를 찾을 수 없습니다.")

        target, mode = _resolve_launch_target(process, request.mode if request else None)
        if not target:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="실행할 경로가 없습니다.")

        settings = crud.get_settings(db)
        launcher = launcher_factory(bool(getattr(settings, "run_as_admin", False)))
        ok = bool(launcher.launch_process(target))
        command = f"process.launch.{mode}"
        result_status = "accepted" if ok else "failed"
        auditor.record(
            command=command,
            accepted=ok,
            status=result_status,
            target_id=getattr(process, "id", process_id),
            target_name=getattr(process, "name", None),
            target=target,
            metadata={"mode": mode},
        )
        return RemoteCommandResult(
            accepted=ok,
            command=command,
            target_id=getattr(process, "id", process_id),
            target_name=getattr(process, "name", None),
            target=target,
            status=result_status,
            message="게임 실행 명령을 전달했습니다." if ok else "게임 실행 명령 전달에 실패했습니다.",
            command_id=f"{command}:{uuid.uuid4().hex}",
            accepted_at=now() if ok else None,
            refresh_after_ms=750 if ok else None,
        )

    @router.get("/shortcuts")
    def list_remote_shortcuts(db: Session = Depends(get_db_dependency)):
        return [_serialize_shortcut(shortcut) for shortcut in crud.get_shortcuts(db)]

    @router.post("/shortcuts/{shortcut_id}/open", response_model=RemoteCommandResult)
    def open_remote_shortcut(shortcut_id: str, db: Session = Depends(get_db_dependency)):
        shortcut = crud.get_shortcut_by_id(db, shortcut_id)
        if shortcut is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="웹 바로 가기를 찾을 수 없습니다.")

        opened = bool(shortcut_opener(shortcut.url))
        if opened:
            crud.mark_shortcut_opened(db, shortcut_id=shortcut_id, opened_at=now())
        result_status = "accepted" if opened else "failed"
        auditor.record(
            command="shortcut.open",
            accepted=opened,
            status=result_status,
            target_id=getattr(shortcut, "id", shortcut_id),
            target_name=getattr(shortcut, "name", None),
            target=getattr(shortcut, "url", None),
        )
        return RemoteCommandResult(
            accepted=opened,
            command="shortcut.open",
            target_id=getattr(shortcut, "id", shortcut_id),
            target_name=getattr(shortcut, "name", None),
            target=getattr(shortcut, "url", None),
            status=result_status,
            message="웹 숏컷 열기 명령을 전달했습니다." if opened else "웹 숏컷 열기 명령 전달에 실패했습니다.",
            command_id=f"shortcut.open:{uuid.uuid4().hex}",
            accepted_at=now() if opened else None,
            refresh_after_ms=750 if opened else None,
        )

    @router.get("/power/status")
    def remote_power_status():
        if not hasattr(power_controller, "status"):
            raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="전원 준비 상태 provider가 없습니다.")
        return power_controller.status()

    return router


def secrets_compare(left: str, right: str) -> bool:
    import secrets

    return secrets.compare_digest(left, right)
