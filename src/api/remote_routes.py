from __future__ import annotations

import os
import platform
import time
import webbrowser
from typing import Any, Callable, Iterable, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.core.launcher import Launcher
from src.core.remote_audit import RemoteAuditLogger
from src.core.remote_pairing import RemoteDeviceRegistry
from src.core.remote_power import ConfigurablePowerController, PowerAction
from src.data import beholder, crud, schemas


REMOTE_API_VERSION = "0.1.6"


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
        if path.endswith("/remote/pair/start") and (_is_loopback_request(request) or _is_valid_remote_token(authorization)):
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
            "power_control": bool(power_status.get("configured")),
            "beholder": True,
            "auth_required": bool(require_auth or auth_token or device_registry.has_registered_devices()),
            "pairing": True,
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
        }

    @router.get("/capabilities")
    def remote_capabilities():
        power_status = power_controller.status() if hasattr(power_controller, "status") else {}
        return {
            "remote_api_version": REMOTE_API_VERSION,
            "capabilities": _remote_capabilities(power_status),
            "power": power_status,
        }

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
        return {
            "range": {"start": start_date.isoformat(), "end": end_date.isoformat()},
            "metrics": _aggregate_summary(sessions, start_dt, end_dt, groups),
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
