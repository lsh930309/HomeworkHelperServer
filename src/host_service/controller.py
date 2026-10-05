"""User-owned requests and Windows effects meet at this headless service boundary."""

from __future__ import annotations

import ntpath
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .constants import APP_EXE, SERVICE_EXE, SERVICE_NAME, SYSTEM_SID


class RequestDenied(Exception):
    """Authenticated caller requested an operation outside its current authority."""


@dataclass(frozen=True)
class Session:
    owner_sid: str
    session_id: int
    appdata_dir: Path
    logon_id: str | None = None


@dataclass(frozen=True)
class Caller:
    pid: int
    sid: str
    session_id: int
    image_path: str
    logon_id: str | None = None


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    create_time: float
    path: str
    sid: str
    session_id: int


@dataclass
class Reply:
    payload: dict
    after_send: Callable[[], object] | None = None


def windows_path(value: str | Path) -> str:
    return ntpath.normcase(ntpath.normpath(str(value)))


class PrivilegeController:
    """No caller controls paths, tokens or power flags. All targets come from one DB."""

    capabilities = ("status", "power", "launch_managed", "inspect_managed", "stop_managed")

    def __init__(self, owner_sid: str, install_dir: Path, backend, repository,
                 *, resolver=None, argument_resolver=None, admin_required=None, preset_inputs=None):
        self.owner_sid = owner_sid
        self.install_dir = Path(install_dir)
        self.backend = backend
        self.repository = repository
        self.allowed_images = {
            windows_path(self.install_dir / APP_EXE),
            windows_path(self.install_dir / SERVICE_EXE),
        }
        self.resolver = resolver
        self.argument_resolver = argument_resolver
        self.admin_required = admin_required
        self.preset_inputs = preset_inputs
        # This state exists only for current Windows logon lifecycle, never as a second setting.
        self._seen_logons: set[int] = set()

    def authorize(self, caller: Caller) -> None:
        if caller.sid not in {self.owner_sid, SYSTEM_SID}:
            raise RequestDenied("설치된 호스트 사용자의 요청만 허용됩니다.")
        if windows_path(caller.image_path) not in self.allowed_images:
            raise RequestDenied("설치된 HomeworkHelper 실행 파일의 요청만 허용됩니다.")

    def _session(self, caller: Caller) -> Session:
        session = self.backend.current_session(self.owner_sid)
        if session is None:
            raise RequestDenied("지정 사용자의 로그인 세션이 준비되지 않았습니다.")
        if (caller.sid != session.owner_sid or caller.session_id != session.session_id
                or caller.logon_id != session.logon_id):
            raise RequestDenied("요청자와 로그인 사용자의 Windows 세션이 다릅니다.")
        return session

    def _still_current(self, session: Session) -> None:
        if self.backend.current_session(self.owner_sid) != session:
            raise RequestDenied("요청 중 로그인 세션이 변경되었습니다. 다시 요청해 주세요.")

    @staticmethod
    def _id(value) -> str:
        if not isinstance(value, str) or not value or len(value) > 128:
            raise RequestDenied("등록 대상 ID가 올바르지 않습니다.")
        return value

    @staticmethod
    def _reply(status: str, message: str, **values) -> Reply:
        return Reply(dict(accepted=True, status=status, message=message, **values))

    def handle(self, request: dict, caller: Caller) -> Reply:
        self.authorize(caller)
        if not isinstance(request, dict):
            raise RequestDenied("요청은 JSON 객체여야 합니다.")
        operation = request.get("operation")
        if operation == "status":
            if set(request) != {"operation"}:
                raise RequestDenied("상태 요청에 지원하지 않는 필드가 있습니다.")
            sessions = self.backend.sessions(self.owner_sid)
            return self._reply("ready", "권한 서비스가 준비되었습니다.", service=SERVICE_NAME,
                               capabilities=list(self.capabilities), owner_sid=self.owner_sid,
                               user_sessions=[{"owner_sid":s.owner_sid, "session_id":s.session_id}
                                              for s in sessions], user_session_ready=bool(sessions))
        if operation == "power":
            action = request.get("action")
            if set(request) != {"operation", "action"} or action not in {"shutdown", "restart", "sleep"}:
                raise RequestDenied("지원하지 않는 전원 요청입니다.")
            self.backend.prepare_power(action)
            # The transport sends and closes this reply before the native action.
            reply = self._reply("accepted", "전원 요청을 수락했습니다.", action=action)
            reply.after_send = lambda: self.backend.power(action)
            return reply
        allowed = {
            "launch_managed": {"operation", "process_id", "mode"},
            "inspect_managed": {"operation", "process_ids"},
            "stop_managed": {"operation", "process_id", "pid", "create_time"},
        }
        if operation not in allowed or set(request) - allowed[operation]:
            raise RequestDenied("지원하지 않는 작업 또는 요청 필드입니다.")
        session = self._session(caller)
        with self.backend.read_as_user(session):
            snapshot = self.repository.read(session)
        if not snapshot.settings.run_as_admin:
            raise RequestDenied("관리자 기능 사용 설정이 꺼져 있습니다.")
        self._still_current(session)
        if operation == "launch_managed":
            process = snapshot.process(self._id(request.get("process_id")))
            mode = request.get("mode", "auto")
            if mode not in {"auto", "direct", "shortcut", "launcher"}:
                raise RequestDenied("지원하지 않는 실행 방식입니다.")
            if self.resolver is None:
                from src.core.launch_target import resolve_launch_target, resolve_launch_args
                from .repository import preset_launch_inputs
                resolver, arguments = resolve_launch_target, resolve_launch_args
                inputs = preset_launch_inputs
            else:
                resolver, arguments, inputs = self.resolver, self.argument_resolver, self.preset_inputs
            with self.backend.read_as_user(session):
                patterns, existing = inputs(process, session) if inputs else ((), frozenset())
            target, effective_mode = resolver(process, mode, launcher_patterns=patterns, existing_paths=existing)
            if not target:
                raise RequestDenied("등록된 실행 경로가 비어 있습니다.")
            args = arguments(process, effective_mode, target)
            if self.admin_required is None:
                from src.core.launch_policy import launch_admin_required
                with self.backend.read_as_user(session):
                    elevated = launch_admin_required(target)
            else:
                elevated = self.admin_required(target)
            self._still_current(session)
            result = self.backend.launch(session, target, args, elevated=bool(elevated))
            return self._reply("launched", "등록된 대상의 실행을 요청했습니다.",
                               process_id=process.id, mode=effective_mode, elevated=bool(elevated), **result)
        if operation == "inspect_managed":
            ids = request.get("process_ids")
            if not isinstance(ids, list) or len(ids) > 256:
                raise RequestDenied("관측할 등록 대상 ID 목록이 올바르지 않습니다.")
            processes = [snapshot.process(self._id(value)) for value in ids]
            matches = self._matching(session, processes)
            self._still_current(session)
            return self._reply("ready", "등록된 프로세스를 관측했습니다.",
                               processes=[self._identity_dict(pid, identity) for pid, identity in matches],
                               observed_at=time.time())
        process = snapshot.process(self._id(request.get("process_id")))
        pid, created = request.get("pid"), request.get("create_time")
        if pid is not None and (type(pid) is not int or pid <= 0 or type(created) not in (int, float)):
            raise RequestDenied("PID를 지정할 때 정확한 생성 시각이 필요합니다.")
        if pid is None and created is not None:
            raise RequestDenied("생성 시각은 PID와 함께 지정해야 합니다.")
        matches = self._matching(session, [process])
        if pid is not None:
            matches = [(key, identity) for key, identity in matches
                       if identity.pid == pid and identity.create_time == float(created)]
            if not matches:
                raise RequestDenied("프로세스 identity가 변경되었거나 등록 대상과 다릅니다.")
        stopped = []
        for key, identity in matches:
            self._still_current(session)
            self.backend.terminate(identity)
            stopped.append(self._identity_dict(key, identity))
        return self._reply("stopped", "등록된 프로세스 종료를 요청했습니다.", stopped=stopped)

    def _matching(self, session, processes):
        paths = {}
        for process in processes:
            if process.monitoring_path:
                paths.setdefault(windows_path(process.monitoring_path), []).append(process.id)
        return [(process_id, p) for p in self.backend.processes(session)
                if p.sid == session.owner_sid and p.session_id == session.session_id
                and windows_path(p.path) in paths
                for process_id in paths[windows_path(p.path)]]

    @staticmethod
    def _identity_dict(process_id, identity):
        return {"process_id":process_id, "pid":identity.pid, "exe":identity.path,
                "create_time":identity.create_time, "session_id":identity.session_id}

    def seed_logged_on_sessions(self) -> None:
        """Service recovery must not reopen an app that the user intentionally closed."""
        self._seen_logons.update(s.session_id for s in self.backend.sessions(self.owner_sid))

    def on_session_change(self, event: str, session_id: int) -> None:
        if event == "logoff":
            self._seen_logons.discard(session_id)
            return
        if event != "logon" or session_id in self._seen_logons:
            return
        self._seen_logons.add(session_id)
        session = self.backend.current_session(self.owner_sid)
        if session is None or session.session_id != session_id:
            return
        with self.backend.read_as_user(session):
            snapshot = self.repository.read(session, settings_only=True)
        if snapshot.settings.run_on_startup:
            self._still_current(session)
            self.backend.startup(session)
