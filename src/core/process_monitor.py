# process_monitor.py
import psutil
import time
import os
import logging
import math
import sys
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, List, Protocol
from src.data.data_models import ManagedProcess
from src.utils.resource_tracking import (
    is_nikke_outpost_resource,
)

logger = logging.getLogger(__name__)

# 디버깅용 파일 로그


class ProcessesDataPort(Protocol):
    managed_processes: list[ManagedProcess]
    def update_process(self, updated_process: ManagedProcess) -> bool: ...
    def update_process_runtime_state(self, updated_process: ManagedProcess) -> bool: ...
    def start_session(self, process_id: str, process_name: str, start_timestamp: float) -> Any: ...
    def end_session(
        self,
        session_id: int,
        end_timestamp: float,
        stamina_at_end: Optional[int] = None,
        resource_percent_at_end: Optional[float] = None,
    ) -> Any: ...


@dataclass(frozen=True)
class ProcessLifecycleEvent:
    process_id: str
    process_name: str
    session_id: Optional[int]
    timestamp: float
    stamina_tracking_enabled: bool
    hoyolab_game_id: Optional[str]
    pid: Optional[int] = None
    stamina_at_end: Optional[int] = None
    stamina_max: Optional[int] = None
    resource_tracking_enabled: bool = False
    resource_provider: Optional[str] = None
    resource_key: Optional[str] = None
    resource_percent_at_end: Optional[float] = None

    def is_hoyoverse_game(self) -> bool:
        """현재 lifecycle 이벤트가 HoYoLab 기반 스태미나 추적 대상인지 반환합니다."""
        return self.stamina_tracking_enabled and self.hoyolab_game_id is not None

    def is_nikke_outpost_resource_game(self) -> bool:
        """현재 lifecycle 이벤트가 NIKKE 전초기지 방어 보상 추적 대상인지 반환합니다."""
        return bool(
            self.resource_tracking_enabled
            and is_nikke_outpost_resource(self.resource_provider, self.resource_key)
        )


@dataclass(frozen=True)
class ProcessMonitorTickResult:
    changed: bool
    started: List[ProcessLifecycleEvent] = field(default_factory=list)
    stopped: List[ProcessLifecycleEvent] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class DetectedRuntimeProcess:
    """GUI thread로 전달할 수 있는 불변 OS 프로세스 관측값입니다."""

    process_id: str
    pid: int
    executable: str
    create_time: float


@dataclass(frozen=True, slots=True)
class ProcessScanSnapshot:
    detected: tuple[DetectedRuntimeProcess, ...]
    observed_at: float


@dataclass(frozen=True, slots=True)
class ProcessScanTarget:
    process_id: str
    monitoring_path: str


def _normalize_process_path(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    try:
        return os.path.normcase(os.path.abspath(path))
    except Exception:
        return path


def _is_windows() -> bool:
    return sys.platform == "win32"


def _windows_process_session(pid: int) -> int:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    kernel32.ProcessIdToSessionId.restype = wintypes.BOOL
    session = wintypes.DWORD()
    if not kernel32.ProcessIdToSessionId(int(pid), ctypes.byref(session)):
        raise OSError(ctypes.get_last_error(), "Windows 프로세스 세션을 확인할 수 없습니다.")
    return int(session.value)


def _belongs_to_current_user_session(proc: psutil.Process) -> bool:
    current = psutil.Process(os.getpid())
    if proc.username().casefold() != current.username().casefold():
        return False
    return not _is_windows() or _windows_process_session(proc.pid) == _windows_process_session(current.pid)


def _privilege_client(client: Any = None) -> Any:
    if client is not None:
        return client
    from src.host_service.client import HostPrivilegeClient
    return HostPrivilegeClient()


def detect_running_process_ids(
    targets: tuple[ProcessScanTarget, ...],
    *,
    run_as_admin: bool = False,
    privilege_client: Any = None,
) -> set[str]:
    """불변 대상 목록만으로 현재 실행 중인 관리 프로세스 ID를 찾습니다."""
    if _is_windows() and run_as_admin:
        return {
            item.process_id
            for item in scan_running_processes(
                targets, run_as_admin=True, privilege_client=privilege_client
            ).detected
        }
    running_exes: set[str] = set()
    for proc in psutil.process_iter(["exe"]):
        try:
            exe_path = _normalize_process_path(proc.info["exe"])
            if exe_path and (not _is_windows() or _belongs_to_current_user_session(proc)):
                running_exes.add(exe_path)
        except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError, FileNotFoundError, OSError):
            continue
    return {
        target.process_id
        for target in targets
        if (normalized := _normalize_process_path(target.monitoring_path)) and normalized in running_exes
    }


def scan_running_processes(
    targets: tuple[ProcessScanTarget, ...],
    *,
    run_as_admin: bool = False,
    privilege_client: Any = None,
) -> ProcessScanSnapshot:
    """DB/provider/cache 참조 없이 OS 프로세스 표를 불변 snapshot으로 읽습니다."""
    managed_paths = {
        normalized: target.process_id
        for target in targets
        if (normalized := _normalize_process_path(target.monitoring_path))
    }
    detected_by_id: dict[str, DetectedRuntimeProcess] = {}
    for proc in psutil.process_iter(["pid", "exe", "create_time"]):
        try:
            executable = _normalize_process_path(proc.info.get("exe"))
            process_id = managed_paths.get(executable)
            if process_id is None or process_id in detected_by_id:
                continue
            if _is_windows() and not _belongs_to_current_user_session(proc):
                continue
            detected_by_id[process_id] = DetectedRuntimeProcess(
                process_id=process_id,
                pid=int(proc.info.get("pid") or proc.pid),
                executable=str(executable),
                create_time=float(proc.info.get("create_time") or proc.create_time()),
            )
        except (
            psutil.NoSuchProcess,
            psutil.AccessDenied,
            TypeError,
            ValueError,
            FileNotFoundError,
            OSError,
        ):
            continue
    observed_at = time.time()
    if _is_windows() and run_as_admin:
        # 권한 서비스의 실패를 빈 관측으로 바꾸면 실행 중인 게임 세션이 종료로 기록됩니다.
        # 실패는 호출자에게 전달하여 이 tick의 기존 GUI cache와 DB 상태를 유지합니다.
        response = _privilege_client(privilege_client).inspect_managed(
            [target.process_id for target in targets]
        )
        for item in response["processes"]:
            process_id = str(item["process_id"])
            executable = _normalize_process_path(item["exe"])
            if managed_paths.get(executable) != process_id:
                continue
            detected_by_id[process_id] = DetectedRuntimeProcess(
                process_id=process_id,
                pid=int(item["pid"]),
                executable=str(executable),
                create_time=float(item["create_time"]),
            )
        observed_at = float(response["observed_at"])
    return ProcessScanSnapshot(
        detected=tuple(detected_by_id[key] for key in sorted(detected_by_id)),
        observed_at=observed_at,
    )


def terminate_managed_process(
    process: ManagedProcess,
    *,
    run_as_admin: bool = False,
    pid: Optional[int] = None,
    create_time: Optional[float] = None,
    privilege_client: Any = None,
) -> dict[str, Any]:
    """등록 대상과 사용자·세션·생성 시각이 일치하는 프로세스만 종료합니다.

    호출자는 GUI/DB의 등록 대상을 확정한 뒤 전달합니다. 권한 서비스가 필요한 모드는
    서비스 실패를 직접 종료나 UAC로 우회하지 않습니다.
    """
    if pid is not None and (
        create_time is None or not math.isfinite(float(create_time)) or float(create_time) <= 0
    ):
        return {"accepted": False, "status": "identity_required", "message": "프로세스 생성 시각이 필요합니다.", "stopped": []}
    if _is_windows() and run_as_admin:
        return _privilege_client(privilege_client).stop_managed(
            process.id, pid=pid, create_time=create_time
        )

    expected_executable = _normalize_process_path(process.monitoring_path)
    if not expected_executable:
        return {"accepted": False, "status": "invalid_target", "message": "등록된 감시 경로가 없습니다.", "stopped": []}
    try:
        candidates = [psutil.Process(int(pid))] if pid is not None else psutil.process_iter(["pid", "exe", "create_time"])
    except psutil.NoSuchProcess:
        return {"accepted": False, "status": "not_running", "message": "관측한 게임 프로세스가 이미 종료되었습니다.", "stopped": []}
    stopped: list[dict[str, Any]] = []
    errors: list[str] = []
    for candidate in candidates:
        matches_registered_path = False
        try:
            if _normalize_process_path(candidate.exe()) != expected_executable:
                continue
            matches_registered_path = True
            actual_created = float(candidate.create_time())
            if create_time is not None and abs(actual_created - float(create_time)) > 0.001:
                continue
            if not _belongs_to_current_user_session(candidate):
                continue
            # psutil이 보관한 process identity와 is_running 확인으로 PID 재사용을 거부합니다.
            if not candidate.is_running():
                continue
            candidate.terminate()
            stopped.append({
                "process_id": process.id,
                "pid": candidate.pid,
                "exe": expected_executable,
                "create_time": actual_created,
            })
        except psutil.NoSuchProcess:
            continue
        except (psutil.AccessDenied, OSError) as exc:
            if matches_registered_path or pid is not None:
                errors.append(str(exc))
    if errors:
        return {"accepted": False, "status": "access_denied", "message": "프로세스 종료 권한이 없거나 종료 요청이 실패했습니다.", "stopped": stopped}
    return {
        "accepted": bool(stopped),
        "status": "stopped" if stopped else "not_running",
        "message": "게임 종료를 요청했습니다." if stopped else "관측한 게임 프로세스가 이미 종료되었거나 식별 정보가 변경되었습니다.",
        "stopped": stopped,
    }


class ProcessMonitor:
    def __init__(self, data_manager: ProcessesDataPort):
        """실행 중 프로세스 캐시를 초기화합니다."""
        self.data_manager = data_manager
        self.active_monitored_processes: Dict[str, Dict[str, Any]] = {}  # key: process_id, value: {pid, exe, start_time_approx, session_id}

    def _admin_features_enabled(self) -> bool:
        return bool(getattr(getattr(self.data_manager, "global_settings", None), "run_as_admin", False))

    def _is_runtime_process_running(self, process_id: str, context: dict[str, Any] | None = None) -> bool:
        """Return whether the process selected by a late Beholder decision is still running."""
        context = context or {}
        expected_exe = self._normalize_path(context.get("exe"))
        if not expected_exe:
            for managed_proc in self.data_manager.managed_processes:
                if managed_proc.id == process_id:
                    expected_exe = self._normalize_path(managed_proc.monitoring_path)
                    break
        expected_start = context.get("requested_start_timestamp") or context.get("start_time_approx")
        expected_pid = context.get("pid")
        if _is_windows() and self._admin_features_enabled():
            snapshot = self.scan_running_processes(self.process_scan_targets())
            return any(
                item.process_id == process_id
                and (expected_pid is None or item.pid == int(expected_pid))
                and (not expected_exe or item.executable == expected_exe)
                and (expected_start is None or abs(item.create_time - float(expected_start)) <= 0.001)
                for item in snapshot.detected
            )
        if expected_pid is not None:
            try:
                proc = psutil.Process(int(expected_pid))
                proc_exe = self._normalize_path(proc.exe())
                if expected_exe and proc_exe != expected_exe:
                    return False
                if expected_start is not None and abs(proc.create_time() - float(expected_start)) > 2:
                    return False
                return proc.is_running()
            except (TypeError, ValueError, psutil.NoSuchProcess, psutil.AccessDenied, FileNotFoundError):
                pass

        if not expected_exe:
            return False

        for proc in psutil.process_iter(["exe"]):
            try:
                if self._normalize_path(proc.info.get("exe")) != expected_exe:
                    continue
                if expected_start is not None and abs(proc.create_time() - float(expected_start)) > 2:
                    continue
                return True
            except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError, FileNotFoundError):
                continue
        return False

    def apply_beholder_resolution(self, result: dict[str, Any] | None) -> None:
        """Bind active runtime cache to a session selected/created by Beholder."""
        if not result:
            return
        session_id = result.get("session_id")
        incident = result.get("incident") or {}
        metadata = incident.get("resolution_metadata") or {}
        context = metadata.get("action_context") or (metadata.get("override_scope") or {}).get("context") or {}
        process_id = result.get("process_id") or context.get("process_id")
        action = result.get("action")
        if process_id and action == "close_sessions_and_delete_process":
            self.active_monitored_processes.pop(process_id, None)
            return
        if process_id and incident.get("operation_kind") == "runtime_stop":
            entry = self.active_monitored_processes.get(process_id)
            if result.get("override_token"):
                if entry is not None:
                    entry.pop("runtime_stop_pending", None)
            else:
                self.active_monitored_processes.pop(process_id, None)
            return
        if process_id and result.get("override_token") and incident.get("operation_kind") == "runtime_start":
            self.active_monitored_processes.pop(process_id, None)
            return
        if not process_id or not session_id:
            return
        entry = self.active_monitored_processes.get(process_id)
        if entry is None:
            if not self._is_runtime_process_running(process_id, context):
                logger.info(
                    "Beholder resolution returned session %s for '%s', but the process is no longer running; leaving monitor cache unbound.",
                    session_id,
                    process_id,
                )
                return
            entry = {"pid": context.get("pid"), "exe": context.get("exe"), "start_time_approx": context.get("requested_start_timestamp")}
            self.active_monitored_processes[process_id] = entry
        entry["session_id"] = session_id


    def _normalize_path(self, path: Optional[str]) -> Optional[str]:
        """실행 파일 경로를 비교 가능한 절대 경로 형태로 정규화합니다."""
        return _normalize_process_path(path)

    def process_scan_targets(self) -> tuple[ProcessScanTarget, ...]:
        """GUI 소유 모델에서 스캔에 필요한 값만 확정해 반환합니다."""
        return tuple(
            ProcessScanTarget(str(process.id), str(process.monitoring_path or ""))
            for process in tuple(self.data_manager.managed_processes)
        )

    def detect_running_process_ids(
        self,
        targets: tuple[ProcessScanTarget, ...] | None = None,
    ) -> set[str]:
        """Return managed process IDs currently visible in the OS process table."""
        scan_targets = targets if targets is not None else self.process_scan_targets()
        return detect_running_process_ids(scan_targets, run_as_admin=self._admin_features_enabled())

    def scan_running_processes(
        self,
        targets: tuple[ProcessScanTarget, ...],
    ) -> ProcessScanSnapshot:
        """DB/provider/cache를 건드리지 않고 OS 프로세스 표만 읽습니다."""
        return scan_running_processes(targets, run_as_admin=self._admin_features_enabled())

    def check_and_update_statuses(self) -> ProcessMonitorTickResult:
        """시스템 프로세스 스냅샷과 내부 캐시를 비교해 시작/종료 이벤트를 기록합니다."""
        changed_occurred = False 
        started_events: List[ProcessLifecycleEvent] = []
        stopped_events: List[ProcessLifecycleEvent] = []
        snapshot = self.scan_running_processes(self.process_scan_targets())
        current_system_processes = {item.executable: [item] for item in snapshot.detected}

        for managed_proc in self.data_manager.managed_processes:
            normalized_monitoring_path = self._normalize_path(managed_proc.monitoring_path)
            if not normalized_monitoring_path: 
                continue

            is_currently_running_on_system = normalized_monitoring_path in current_system_processes
            was_previously_active = managed_proc.id in self.active_monitored_processes

            if is_currently_running_on_system:
                if not was_previously_active:
                    if current_system_processes[normalized_monitoring_path]:
                        actual_process_instance = current_system_processes[normalized_monitoring_path][0]
                        try: # proc.create_time() 등에서 발생할 수 있는 예외 처리
                            start_timestamp = actual_process_instance.create_time

                            # 세션 시작 기록
                            session = self.data_manager.start_session(
                                process_id=managed_proc.id,
                                process_name=managed_proc.name,
                                start_timestamp=start_timestamp
                            )

                            self.active_monitored_processes[managed_proc.id] = {
                                'pid': actual_process_instance.pid,
                                'exe': normalized_monitoring_path,
                                'start_time_approx': start_timestamp,
                                'session_id': session.id if session else None
                            }
                            started_events.append(
                                ProcessLifecycleEvent(
                                    process_id=managed_proc.id,
                                    process_name=managed_proc.name,
                                    session_id=session.id if session else None,
                                    timestamp=start_timestamp,
                                    stamina_tracking_enabled=managed_proc.stamina_tracking_enabled,
                                    hoyolab_game_id=managed_proc.hoyolab_game_id,
                                    pid=actual_process_instance.pid,
                                    resource_tracking_enabled=getattr(managed_proc, "resource_tracking_enabled", False),
                                    resource_provider=getattr(managed_proc, "resource_provider", None),
                                    resource_key=getattr(managed_proc, "resource_key", None),
                                )
                            )
                            logger.info(f"Process STARTED: '{managed_proc.name}' (PID: {actual_process_instance.pid}, Session ID: {session.id if session else 'N/A'})")
                            changed_occurred = True # <<< 프로세스 시작 시에도 변경으로 간주
                        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                            logger.error(f"'{managed_proc.name}' 시작 정보 가져오는 중 오류: {e}")
                            if managed_proc.id in self.active_monitored_processes:
                                self.active_monitored_processes.pop(managed_proc.id)
                    else:
                        logger.warning(f"'{managed_proc.name}'이 실행 중으로 감지되었으나, 프로세스 인스턴스 정보를 찾을 수 없습니다.")
            else:
                if was_previously_active:
                    cached_info = self.active_monitored_processes.get(managed_proc.id, {})
                    if cached_info.get("runtime_stop_pending"):
                        continue
                    termination_time = cached_info.get("pending_termination_time") or time.time()
                    previous_last_played = managed_proc.last_played_timestamp
                    managed_proc.last_played_timestamp = termination_time

                    # 감시는 수명주기만 기록합니다. 자원 조회·저장은 제공자별 직렬 작업이 소유합니다.
                    session_id = cached_info.get('session_id')
                    if session_id:
                        ended_session = self.data_manager.end_session(session_id, termination_time)
                        if ended_session:
                            logger.info(f"Process STOPPED: '{managed_proc.name}' (Was PID: {cached_info.get('pid')}, Session ID: {session_id}, Duration: {ended_session.session_duration:.2f}s)")
                        else:
                            logger.info(f"Process STOPPED: '{managed_proc.name}' (Was PID: {cached_info.get('pid')}, Session end recording failed)")
                            managed_proc.last_played_timestamp = previous_last_played
                            incident = getattr(self.data_manager, "latest_beholder_incident", None)
                            if (
                                isinstance(incident, dict)
                                and incident.get("operation_kind") == "runtime_stop"
                            ):
                                cached_info["runtime_stop_pending"] = True
                                cached_info["pending_termination_time"] = termination_time
                            continue
                    else:
                        logger.info(f"Process STOPPED: '{managed_proc.name}' (Was PID: {cached_info.get('pid')}, no session was recorded)")
                        managed_proc.last_played_timestamp = previous_last_played
                        self.active_monitored_processes.pop(managed_proc.id, None)
                        continue

                    self.active_monitored_processes.pop(managed_proc.id, None)
                    stopped_events.append(
                        ProcessLifecycleEvent(
                            process_id=managed_proc.id,
                            process_name=managed_proc.name,
                            session_id=session_id,
                            timestamp=termination_time,
                            stamina_tracking_enabled=managed_proc.stamina_tracking_enabled,
                            hoyolab_game_id=managed_proc.hoyolab_game_id,
                            stamina_max=managed_proc.stamina_max,
                            resource_tracking_enabled=getattr(managed_proc, "resource_tracking_enabled", False),
                            resource_provider=getattr(managed_proc, "resource_provider", None),
                            resource_key=getattr(managed_proc, "resource_key", None),
                        )
                    )
                    changed_occurred = True
                    if hasattr(self.data_manager, "update_process_runtime_state"):
                        saved = self.data_manager.update_process_runtime_state(managed_proc)
                    else:
                        saved = self.data_manager.update_process(managed_proc)
                    if not saved:
                        logger.warning(
                            "Process STOPPED 상태 저장 실패: process_id=%s",
                            managed_proc.id,
                        )
                    logger.info(f"Last played updated: {time.ctime(termination_time)}")

        return ProcessMonitorTickResult(
            changed=changed_occurred,
            started=started_events,
            stopped=stopped_events,
        )
