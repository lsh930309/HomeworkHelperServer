"""User-owned requests and Windows effects meet at this headless service boundary."""

from __future__ import annotations

import ntpath
from queue import Empty, SimpleQueue
import sqlite3
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


@dataclass
class _StartupAttempt:
    """One in-memory decision for a Windows logon, owned by the startup worker."""

    deadline: float
    next_attempt: float
    session: Session | None = None
    outcome: str = "pending"
    previous_logon: tuple[str, int, str | None] | None = None
    app_complete: bool = False
    obs_complete: bool = False
    has_error: bool = False


def windows_path(value: str | Path) -> str:
    return ntpath.normcase(ntpath.normpath(str(value)))


class PrivilegeController:
    """No caller controls paths, tokens or power flags. All targets come from one DB."""

    capabilities = ("status", "power", "launch_obs", "launch_managed", "inspect_managed", "stop_managed")

    def __init__(self, owner_sid: str, install_dir: Path, backend, repository,
                 *, resolver=None, argument_resolver=None, admin_required=None, preset_inputs=None,
                 session_events=None, clock=time.monotonic, log_error=None):
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
        # SCM callbacks only put events. The startup worker alone changes these decisions.
        self._session_events = session_events if session_events is not None else SimpleQueue()
        self._clock = clock
        self._log_error = log_error or (lambda message: None)
        self._startup_attempts: dict[int, _StartupAttempt] = {}

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
                                              for s in sessions], user_session_ready=self.backend.current_session(self.owner_sid) is not None)
        if operation == "power":
            action = request.get("action")
            if set(request) != {"operation", "action"} or action not in {"shutdown", "restart", "sleep"}:
                raise RequestDenied("지원하지 않는 전원 요청입니다.")
            session = self.backend.current_session(self.owner_sid)
            if session is None:
                raise RequestDenied("전원 제어는 지정 사용자 로그온 후 사용할 수 있습니다.")
            self.backend.prepare_power(action)
            # The transport sends and closes this reply before the native action.
            reply = self._reply("accepted", "전원 요청을 수락했습니다.", action=action)
            def perform_power():
                self._still_current(session)
                self.backend.power(action)
            reply.after_send = perform_power
            return reply
        if operation == "launch_obs":
            if set(request) != {"operation"}:
                raise RequestDenied("OBS 요청에 경로 또는 인자를 지정할 수 없습니다.")
            session = self._session(caller)
            with self.backend.read_as_user(session):
                settings = self.repository.read(session, settings_only=True).settings
            self._still_current(session)
            result = self.backend.launch_obs(session, settings.obs_exe_path, settings.obs_launch_hidden)
            return self._reply("launched", "관리자 권한 OBS 실행을 확인했습니다.",
                               **{k:v for k,v in result.items() if k != "accepted"})
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
        sessions = self.backend.sessions(self.owner_sid)
        events = self._take_session_events()
        # A logon received while SCM initialized is new, even if its token is now ready.
        new_logons = {session_id for event, session_id, _at in events if event == "logon"}
        for session in sessions:
            if session.session_id not in new_logons:
                self._startup_attempts[session.session_id] = _StartupAttempt(
                    0, 0, session=session, outcome="existing",
                )
        self._apply_session_events(events)

    def on_session_change(self, event: str, session_id: int) -> None:
        """Queue only: no token lookup, SQLite read or process creation in SCM callback."""
        if event in {"logon", "logoff", "disconnect"}:
            self._session_events.put((event, session_id, self._clock()))

    def _take_session_events(self) -> list[tuple[str, int, float]]:
        events = []
        while True:
            try:
                events.append(self._session_events.get_nowait())
            except Empty:
                return events

    def _apply_session_events(self, events) -> None:
        for event, session_id, observed_at in events:
            attempt = self._startup_attempts.get(session_id)
            if event == "logoff":
                self._startup_attempts.pop(session_id, None)
            elif event == "disconnect":
                if attempt is not None and attempt.outcome == "pending":
                    self._startup_attempts.pop(session_id, None)
            elif event == "logon":
                if attempt is None or (attempt.outcome != "pending" and attempt.session is not None):
                    previous_logon = None
                    if attempt is not None:
                        previous_logon = (attempt.session.owner_sid, attempt.session.session_id,
                                          attempt.session.logon_id)
                    self._startup_attempts[session_id] = _StartupAttempt(
                        deadline=observed_at + 120, next_attempt=observed_at,
                        previous_logon=previous_logon,
                    )

    @staticmethod
    def _temporary_startup_error(error: Exception) -> bool:
        if isinstance(error, sqlite3.OperationalError):
            code = getattr(error, "sqlite_errorcode", None)
            return code is not None and (code & 0xff) in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
        # These token/session/busy errors describe an unavailable effect, not an
        # unknown launch result. Missing settings, access denied and corrupt DBs fail explicitly.
        return getattr(error, "winerror", None) in {87, 170, 1008, 1237, 7022}

    def _startup_is_current(self, session_id, attempt, stop_event) -> bool:
        self._apply_session_events(self._take_session_events())
        return (not (stop_event is not None and stop_event.is_set())
                and self._startup_attempts.get(session_id) is attempt
                and attempt.outcome == "pending" and self._clock() < attempt.deadline)

    def _try_startup(self, session_id, attempt, stop_event) -> bool:
        session = self.backend.current_session(self.owner_sid)
        if session is None or session.logon_id is None:
            return False
        if session.owner_sid != self.owner_sid or session.session_id != session_id:
            raise RequestDenied("자동 시작 대상의 사용자 또는 Windows 세션이 변경되었습니다.")
        if attempt.previous_logon == (session.owner_sid, session.session_id, session.logon_id):
            # The same authentication ID is a duplicate event/service recovery, not a new login.
            attempt.session = session
            attempt.outcome = "existing"
            return True
        if attempt.session is not None and attempt.session != session:
            raise RequestDenied("자동 시작 대상의 Windows 로그온 식별이 변경되었습니다.")
        attempt.session = session
        with self.backend.read_as_user(session):
            snapshot = self.repository.read(session, settings_only=True)
        if not self._startup_is_current(session_id, attempt, stop_event):
            return False
        self._still_current(session)
        for component in ("obs", "app"):
            if not self._startup_is_current(session_id, attempt, stop_event):
                return False
            if getattr(attempt, component + "_complete"):
                continue
            try:
                self._still_current(session)
                if component == "obs":
                    result = self.backend.launch_obs(session, snapshot.settings.obs_exe_path,
                                                     snapshot.settings.obs_launch_hidden)
                elif snapshot.settings.run_on_startup:
                    result = self.backend.startup(session)
                else:
                    attempt.app_complete = True
                    continue
                if (not isinstance(result, dict) or result.get("accepted") is not True
                        or type(result.get("pid")) is not int or result["pid"] <= 0):
                    raise RuntimeError(f"{component} 실행 완료를 확인하지 못했습니다. 자동 재시도하지 않습니다.")
                setattr(attempt, component + "_complete", True)
            except Exception as error:
                if not self._temporary_startup_error(error):
                    setattr(attempt, component + "_complete", True)
                    attempt.has_error = True
                    self._log_error(f"로그인 {component} 자동 시작 실패: session={session_id}: {error}")
        if attempt.app_complete and attempt.obs_complete:
            attempt.outcome = "failed" if attempt.has_error else "completed"
            return True
        return False

    def process_session_events(self, stop_event=None) -> None:
        """One worker tick. Tests advance its clock without sleeping or native effects."""
        self._apply_session_events(self._take_session_events())
        for session_id, attempt in list(self._startup_attempts.items()):
            if stop_event is not None and stop_event.is_set():
                self._startup_attempts.clear()
                return
            if attempt.outcome != "pending":
                continue
            now = self._clock()
            if now >= attempt.deadline:
                attempt.outcome = "failed"
                self._log_error(f"로그인 자동 시작 제한 시간 초과: session={session_id}, timeout=120s")
                continue
            if now < attempt.next_attempt:
                continue
            try:
                if not self._try_startup(session_id, attempt, stop_event):
                    attempt.next_attempt = self._clock() + 1
            except Exception as error:
                if self._temporary_startup_error(error):
                    attempt.next_attempt = self._clock() + 1
                else:
                    attempt.outcome = "failed"
                    self._log_error(f"로그인 자동 시작 실패: session={session_id}: {error}")

    def run_session_startup(self, stop_event) -> None:
        """A single worker consumes initial events, new events and bounded readiness retries."""
        try:
            self.seed_logged_on_sessions()
        except Exception as error:
            self._log_error(f"서비스 시작 시 기존 로그인 확인 실패: {error}")
        while not stop_event.is_set():
            self.process_session_events(stop_event)
            stop_event.wait(1)
        self._startup_attempts.clear()
