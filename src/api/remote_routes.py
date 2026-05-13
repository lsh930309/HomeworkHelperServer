from __future__ import annotations

import os
import platform
import time
import webbrowser
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Iterable, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.core.launcher import Launcher
from src.core.remote_audit import RemoteAuditLogger
from src.core.remote_pairing import RemoteDeviceRegistry
from src.core.remote_power import ConfigurablePowerController, PowerAction, RemotePowerConfig
from src.core.tailscale import ensure_tailscale_ready, suggest_remote_base_urls, tailscale_status
from src.data.database import data_dir
from src.data import beholder, crud, models, schemas


REMOTE_API_VERSION = "0.1.9"
TEMPORARY_MACBOOK_TAILSCALE_IP = "100.114.138.46"


def _temporary_pairing_allowed_ips() -> set[str]:
    raw = os.environ.get("HH_REMOTE_DEV_ALLOWED_PAIRING_IPS")
    if raw is None:
        raw = TEMPORARY_MACBOOK_TAILSCALE_IP
    return {item.strip() for item in raw.split(",") if item.strip()}


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


class RemotePowerConfigRequest(BaseModel):
    smartthings_device_id: str = ""
    smartthings_cli_path: str = ""
    ssh_host: str = ""
    ssh_port: int = 22
    ssh_user: str = ""
    ssh_key_path: str = ""
    status_timeout_seconds: float = 4.0


def _model_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    if hasattr(model, "dict"):
        return model.dict()
    return dict(model)


def _serialize_process(process: Any) -> dict[str, Any]:
    if hasattr(schemas.ProcessSchema, "model_validate"):
        return _model_dump(schemas.ProcessSchema.model_validate(process))
    return _model_dump(schemas.ProcessSchema.from_orm(process))


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


def _power_config_payload(config: RemotePowerConfig, config_path: Path, config_exists: bool) -> dict[str, Any]:
    wake_ready = bool(config.smartthings_device_id and config.smartthings_cli_path)
    ssh_ready = bool(config.ssh_host and config.ssh_user and config.ssh_key_path and config.ssh_port)
    supported_actions: list[str] = []
    if wake_ready:
        supported_actions.append("wake")
    if ssh_ready:
        supported_actions.extend(["shutdown", "sleep", "restart"])
    return {
        "config_path": str(config_path),
        "config_exists": config_exists,
        "config": {
            "smartthings_device_id": config.smartthings_device_id,
            "smartthings_cli_path": config.smartthings_cli_path,
            "ssh_host": config.ssh_host,
            "ssh_port": config.ssh_port,
            "ssh_user": config.ssh_user,
            "ssh_key_path": config.ssh_key_path,
            "status_timeout_seconds": config.status_timeout_seconds,
        },
        "readiness": {
            "wake_configured": wake_ready,
            "ssh_configured": ssh_ready,
            "supported_actions": supported_actions,
        },
    }


def _save_power_config(path: Path, config: RemotePowerConfig) -> None:
    import json

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "smartthings_device_id": config.smartthings_device_id,
        "smartthings_cli_path": config.smartthings_cli_path,
        "ssh_host": config.ssh_host,
        "ssh_port": config.ssh_port,
        "ssh_user": config.ssh_user,
        "ssh_key_path": config.ssh_key_path,
        "status_timeout_seconds": config.status_timeout_seconds,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
        # Remote MVP does not yet depend on preset-manager path discovery.  Keep
        # the semantic mode and safely fall back to the stored launch paths.
        return (getattr(process, "launch_path", None) or getattr(process, "monitoring_path", None), mode)
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
    power_config_path: Path | None = None,
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
    power_config_path = power_config_path or Path(data_dir) / "remote_power_config.json"
    tailscale_probe = tailscale_probe or tailscale_status

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

    def _is_valid_remote_token(authorization: str | None) -> bool:
        token = _bearer_token(authorization)
        if not token:
            return False
        if auth_token and secrets_compare(token, auth_token):
            return True
        return bool(device_registry.validate_token(token, now=now()))

    def require_remote_auth(request: Request, authorization: str | None = Header(None)) -> None:
        path = request.url.path.rstrip("/")
        if path.endswith("/remote/pair/confirm"):
            return
        if path.endswith("/remote/pair/start") and (
            _is_loopback_request(request)
            or _is_temporary_pairing_allowed_request(request)
            or _is_valid_remote_token(authorization)
        ):
            return
        if path.endswith("/remote/pair/start"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="페어링 코드 발급은 로컬 요청 또는 인증된 디바이스에서만 가능합니다.",
            )
        if not require_auth and not auth_token and not device_registry.has_registered_devices():
            return
        if _is_valid_remote_token(authorization):
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
            "power_config": True,
            "power_control": bool(power_status.get("configured")),
            "beholder": True,
            "auth_required": bool(require_auth or auth_token or device_registry.has_registered_devices()),
            "pairing": True,
            "tailscale_discovery": True,
            "readiness": True,
        }

    def _readiness_payload(power_status: dict[str, Any], *, active_beholder_incidents: int | None = None) -> dict[str, Any]:
        try:
            ts_snapshot = tailscale_probe()
            tailscale_payload = ts_snapshot.as_dict() if hasattr(ts_snapshot, "as_dict") else dict(ts_snapshot)
        except Exception as exc:
            tailscale_payload = {
                "installed": False,
                "running": False,
                "backend_state": "error",
                "self_ips": [],
                "self_hostname": "",
                "peers": [],
                "message": f"tailscale readiness 확인 실패: {exc}",
            }
            ts_snapshot = None
        tailscale_ready = bool(tailscale_payload.get("installed") and tailscale_payload.get("running"))
        power_ready = bool(power_status.get("configured"))
        auth_ready = bool(require_auth or auth_token or device_registry.has_registered_devices())
        beholder_state = "ok" if not active_beholder_incidents else "warning"
        remote_state = "ok" if auth_ready else "warning"
        server_state = "ok" if auth_ready and tailscale_ready else "warning"
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
                "message": "서버 모드 준비됨" if server_state == "ok" else "Tailscale 또는 페어링 준비가 더 필요합니다.",
            },
            "power_readiness": {
                "state": "ok" if power_ready else "warning",
                "color": "green" if power_ready else "yellow",
                "message": power_status.get("message") or ("전원 제어 adapter 설정됨" if power_ready else "전원 제어 adapter 미설정"),
                "supported_actions": power_status.get("supported_actions") or [],
            },
            "tailscale_readiness": {
                "state": "ok" if tailscale_ready else "warning",
                "color": "green" if tailscale_ready else "yellow",
                "message": tailscale_payload.get("message") or "tailscale 상태 미확인",
                "suggested_base_urls": suggest_remote_base_urls(ts_snapshot) if tailscale_ready and ts_snapshot is not None else [],
                "details": tailscale_payload,
            },
        }

    @router.post("/pair/start")
    def start_remote_pairing():
        pairing = device_registry.start_pairing(now=now())
        return {
            "code": pairing["code"],
            "expires_at": pairing["expires_at"],
            "ttl_seconds": device_registry.code_ttl_seconds,
            "message": "macOS/Android 앱에서 이 코드를 입력해 페어링을 완료하세요.",
        }

    @router.post("/pair/confirm")
    def confirm_remote_pairing(request: PairingConfirmRequest):
        device = device_registry.confirm_pairing(
            code=request.code,
            device_name=request.device_name,
            platform=request.platform,
            now=now(),
        )
        if not device:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="페어링 코드가 올바르지 않거나 만료되었습니다.")
        return device

    @router.get("/devices")
    def list_remote_devices():
        return {"devices": device_registry.list_devices()}

    @router.delete("/devices/{device_id}")
    def revoke_remote_device(device_id: str):
        if not device_registry.revoke_device(device_id, now=now()):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="디바이스를 찾을 수 없습니다.")
        return {"revoked": True, "device_id": device_id}

    @router.post("/tokens/refresh")
    def refresh_remote_device_token(authorization: str | None = Header(None)):
        token = _bearer_token(authorization)
        if not token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="갱신할 device Bearer token이 필요합니다.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        device = device_registry.refresh_token(token, now=now())
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
        processes = crud.get_processes(db)
        shortcuts = crud.get_shortcuts(db)
        active_count = 0
        try:
            active_count = len([session for session in crud.get_all_sessions(db) if session.end_timestamp is None])
        except Exception:
            active_count = 0

        power_status = power_controller.status() if hasattr(power_controller, "status") else {}
        return {
            "app": "HomeworkHelper",
            "remote_api_version": REMOTE_API_VERSION,
            "server_time": now(),
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
            "readiness": _readiness_payload(power_status, active_beholder_incidents=len(beholder.active_incidents(db))),
        }

    @router.get("/capabilities")
    def remote_capabilities():
        power_status = power_controller.status() if hasattr(power_controller, "status") else {}
        return {
            "remote_api_version": REMOTE_API_VERSION,
            "capabilities": _remote_capabilities(power_status),
            "power": power_status,
            "readiness": _readiness_payload(power_status),
        }

    @router.get("/readiness")
    def remote_readiness():
        power_status = power_controller.status() if hasattr(power_controller, "status") else {}
        return _readiness_payload(power_status)

    @router.post("/tailscale/ensure")
    def remote_tailscale_ensure():
        result = ensure_tailscale_ready()
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

    @router.get("/power/config")
    def remote_power_config():
        """Return editable power adapter config without sending power commands."""

        config = RemotePowerConfig.load(power_config_path)
        return _power_config_payload(config, power_config_path, power_config_path.exists())

    @router.put("/power/config")
    def update_remote_power_config(request: RemotePowerConfigRequest):
        """Persist fixed-schema power config and refresh the in-process adapter.

        This endpoint writes only HomeworkHelper's allowlisted
        ``remote_power_config.json`` shape. It never accepts raw commands and
        never performs wake/shutdown/sleep/restart side effects.
        """

        config = RemotePowerConfig(
            smartthings_device_id=request.smartthings_device_id.strip(),
            smartthings_cli_path=request.smartthings_cli_path.strip(),
            ssh_host=request.ssh_host.strip(),
            ssh_port=int(request.ssh_port or 22),
            ssh_user=request.ssh_user.strip(),
            ssh_key_path=request.ssh_key_path.strip(),
            status_timeout_seconds=float(request.status_timeout_seconds or 4.0),
        )
        _save_power_config(power_config_path, config)
        if isinstance(power_controller, ConfigurablePowerController):
            power_controller.config = config
        auditor.record(
            command="power.config.update",
            accepted=True,
            status="accepted",
            target=str(power_config_path),
            metadata={
                "wake_configured": config.wake_configured,
                "ssh_configured": config.ssh_configured,
            },
        )
        return _power_config_payload(config, power_config_path, True)

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
        return [_serialize_process(process) for process in crud.get_processes(db)]

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
        )

    @router.get("/power/status")
    def remote_power_status():
        if not hasattr(power_controller, "status"):
            raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="전원 제어 adapter가 없습니다.")
        return power_controller.status()

    @router.post("/power/{action}", response_model=RemoteCommandResult)
    def remote_power_action(action: PowerAction):
        if not hasattr(power_controller, "perform"):
            raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="전원 제어 adapter가 없습니다.")
        result = power_controller.perform(action)
        auditor.record(
            command=f"power.{action}",
            accepted=bool(result.accepted),
            status=result.status,
            target_id=None,
            target_name="desktop",
            target=action,
        )
        return RemoteCommandResult(
            accepted=bool(result.accepted),
            command=f"power.{action}",
            target_id=None,
            target_name="desktop",
            target=action,
            status=result.status,
            message=result.message,
        )

    return router


def secrets_compare(left: str, right: str) -> bool:
    import secrets

    return secrets.compare_digest(left, right)
