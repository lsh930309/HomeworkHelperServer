# process_monitor.py
import psutil
import time
import os
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, Optional, List, Protocol
from src.data.data_models import ManagedProcess
from src.utils.resource_tracking import (
    NIKKE_OUTPOST_CORRECTION_THRESHOLD_PERCENT,
    clamp_percent,
    is_nikke_outpost_resource,
)

logger = logging.getLogger(__name__)

# 디버깅용 파일 로그
def _debug_log(message: str):
    """디버깅 메시지를 파일에 기록"""
    try:
        log_dir = Path.home() / ".HomeworkHelper" / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / "stamina_debug.log"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")
    except Exception:
        pass


class ProcessesDataPort(Protocol):
    managed_processes: list[ManagedProcess]
    def update_process(self, updated_process: ManagedProcess) -> bool: ...
    def update_process_runtime_state(self, updated_process: ManagedProcess) -> bool: ...
    def update_process_stamina(self, process_id: str, stamina_current: int, stamina_max: int, stamina_updated_at: float) -> bool: ...
    def update_process_resource(
        self,
        process_id: str,
        resource_percent: Optional[float],
        resource_updated_at: Optional[float],
        resource_status: Optional[str],
        resource_label: Optional[str] = None,
    ) -> bool: ...
    def start_session(self, process_id: str, process_name: str, start_timestamp: float) -> Any: ...
    def end_session(
        self,
        session_id: int,
        end_timestamp: float,
        stamina_at_end: Optional[int] = None,
        resource_percent_at_end: Optional[float] = None,
    ) -> Any: ...
    def get_last_session(self, process_id: str) -> Any: ...
    def update_session_stamina(self, session_id: int, stamina_at_end: int) -> bool: ...
    def update_session_resource(self, session_id: int, resource_percent_at_end: float) -> bool: ...


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


class ProcessMonitor:
    def __init__(self, data_manager: ProcessesDataPort):
        """실행 중 프로세스 캐시를 초기화합니다."""
        self.data_manager = data_manager
        self.active_monitored_processes: Dict[str, Dict[str, Any]] = {}  # key: process_id, value: {pid, exe, start_time_approx, session_id}

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

    def _get_hoyolab_service(self):
        """reset 이후에도 최신 전역 HoYoLab 서비스 인스턴스를 반환합니다."""
        try:
            from src.services.hoyolab import get_hoyolab_service
            return get_hoyolab_service()
        except ImportError:
            logger.warning("HoYoLab 서비스를 로드할 수 없습니다.")
            return None

    def _persist_stamina_state(self, process: ManagedProcess) -> bool:
        """Persist only HoYoLab stamina fields when a full runtime patch is unnecessary."""
        if (
            process.stamina_current is None
            or process.stamina_max is None
            or process.stamina_updated_at is None
        ):
            return True
        if hasattr(self.data_manager, "update_process_stamina"):
            return self.data_manager.update_process_stamina(
                process.id,
                process.stamina_current,
                process.stamina_max,
                process.stamina_updated_at,
            )
        return self.data_manager.update_process_runtime_state(process)

    def _persist_resource_state(self, process: ManagedProcess) -> bool:
        """Persist only external resource fields when a full runtime patch is unnecessary."""
        if (
            process.resource_updated_at is None
            or process.resource_status is None
        ):
            return True
        if hasattr(self.data_manager, "update_process_resource"):
            return self.data_manager.update_process_resource(
                process.id,
                process.resource_percent,
                process.resource_updated_at,
                process.resource_status,
                process.resource_label,
            )
        return self.data_manager.update_process_runtime_state(process)

    def _normalize_path(self, path: Optional[str]) -> Optional[str]:
        """실행 파일 경로를 비교 가능한 절대 경로 형태로 정규화합니다."""
        if not path: 
            return None
        try: 
            return os.path.normcase(os.path.abspath(path))
        except Exception: 
            return path 

    def detect_running_process_ids(self) -> set[str]:
        """Return managed process IDs currently visible in the OS process table."""
        running_exes: set[str] = set()
        for proc in psutil.process_iter(['exe']):
            try:
                exe_path = self._normalize_path(proc.info['exe'])
                if exe_path:
                    running_exes.add(exe_path)
            except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError, FileNotFoundError):
                continue
        running_ids: set[str] = set()
        for managed_proc in self.data_manager.managed_processes:
            normalized_monitoring_path = self._normalize_path(managed_proc.monitoring_path)
            if normalized_monitoring_path and normalized_monitoring_path in running_exes:
                running_ids.add(managed_proc.id)
        return running_ids

    def check_and_update_statuses(self) -> ProcessMonitorTickResult:
        """시스템 프로세스 스냅샷과 내부 캐시를 비교해 시작/종료 이벤트를 기록합니다."""
        changed_occurred = False 
        started_events: List[ProcessLifecycleEvent] = []
        stopped_events: List[ProcessLifecycleEvent] = []
        current_system_processes: Dict[Optional[str], List[psutil.Process]] = {}
        
        for proc in psutil.process_iter(['pid', 'name', 'exe', 'create_time']):
            try:
                if not proc.info['exe']:
                    continue
                exe_path = self._normalize_path(proc.info['exe'])
                if exe_path: 
                    if exe_path not in current_system_processes:
                        current_system_processes[exe_path] = []
                    current_system_processes[exe_path].append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError, FileNotFoundError):
                continue
            except Exception as e: 
                continue 

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
                            start_timestamp = actual_process_instance.create_time()

                            # 호요버스 게임인 경우 스태미나 보정 체크 (세션 시작 전에 수행)
                            if managed_proc.is_hoyoverse_game() and managed_proc.stamina_tracking_enabled:
                                self._calibrate_stamina_on_game_start(managed_proc)
                            if getattr(managed_proc, "is_external_resource_game", lambda: False)():
                                self._calibrate_external_resource_on_game_start(managed_proc)

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

                    # 호요버스 게임인 경우 스태미나 조회를 세션 종료 전에 먼저 수행
                    stamina_at_end = None
                    _debug_log(f"[종료 감지] '{managed_proc.name}' - is_hoyoverse_game={managed_proc.is_hoyoverse_game()}, tracking={managed_proc.stamina_tracking_enabled}, game_id={managed_proc.hoyolab_game_id}")
                    if managed_proc.is_hoyoverse_game():
                        stamina_at_end = self._update_stamina_on_game_exit(managed_proc)
                        _debug_log(f"[스태미나 조회] '{managed_proc.name}' - stamina_at_end={stamina_at_end}")
                    resource_percent_at_end = None
                    if getattr(managed_proc, "is_external_resource_game", lambda: False)():
                        resource_percent_at_end = self._update_external_resource_on_game_exit(managed_proc)

                    # 세션 종료 기록 (스태미나 값 포함)
                    session_id = cached_info.get('session_id')
                    _debug_log(f"[세션 종료] '{managed_proc.name}' - session_id={session_id}, stamina_at_end={stamina_at_end}")
                    if session_id:
                        if resource_percent_at_end is not None:
                            ended_session = self.data_manager.end_session(
                                session_id,
                                termination_time,
                                stamina_at_end,
                                resource_percent_at_end=resource_percent_at_end,
                            )
                        else:
                            ended_session = self.data_manager.end_session(session_id, termination_time, stamina_at_end)
                        if ended_session:
                            stamina_info = f", Stamina: {stamina_at_end}" if stamina_at_end is not None else ""
                            resource_info = f", Resource: {resource_percent_at_end:.1f}%" if resource_percent_at_end is not None else ""
                            logger.info(f"Process STOPPED: '{managed_proc.name}' (Was PID: {cached_info.get('pid')}, Session ID: {session_id}, Duration: {ended_session.session_duration:.2f}s{stamina_info}{resource_info})")
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
                            stamina_at_end=stamina_at_end,
                            stamina_max=managed_proc.stamina_max,
                            resource_tracking_enabled=getattr(managed_proc, "resource_tracking_enabled", False),
                            resource_provider=getattr(managed_proc, "resource_provider", None),
                            resource_key=getattr(managed_proc, "resource_key", None),
                            resource_percent_at_end=resource_percent_at_end,
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

    def _update_stamina_on_game_exit(self, process: ManagedProcess) -> Optional[int]:
        """게임 종료 시 HoYoLab에서 스태미나 정보 조회 및 저장

        Returns:
            Optional[int]: 조회된 현재 스태미나 값, 실패 시 None
        """
        service = self._get_hoyolab_service()
        if not service:
            return None

        if not service.is_available():
            logger.debug("[HoYoLab] genshin.py 라이브러리가 설치되지 않았습니다.")
            return None

        if not service.is_configured():
            logger.info(f"[HoYoLab] 인증 정보가 설정되지 않아 '{process.name}' 스태미나 조회를 건너뜁니다.")
            return None

        try:
            logger.info(f"[HoYoLab] '{process.name}' 스태미나 조회 중...")
            stamina = service.get_stamina(process.hoyolab_game_id)
            if stamina:
                process.stamina_current = stamina.current
                process.stamina_max = stamina.max
                process.stamina_updated_at = stamina.updated_at.timestamp()
                logger.info(f"[HoYoLab] '{process.name}' 스태미나 업데이트: {stamina.current}/{stamina.max}")
                return stamina.current
            else:
                logger.info(f"[HoYoLab] '{process.name}' 스태미나 조회 결과 없음")
                return None
        except Exception as e:
            logger.error(f"[HoYoLab] '{process.name}' 스태미나 조회 실패: {e}")
            return None

    def _update_external_resource_on_game_exit(self, process: ManagedProcess) -> Optional[float]:
        """게임 종료 시 범용 외부 리소스 스냅샷을 갱신하고 세션 종료값을 반환합니다."""
        provider = getattr(process, "resource_provider", None)
        resource_key = getattr(process, "resource_key", None)
        if not is_nikke_outpost_resource(provider, resource_key):
            logger.debug("지원하지 않는 외부 리소스 추적 대상: provider=%s key=%s", provider, resource_key)
            return None

        try:
            from src.services.nikke import get_nikke_service

            snapshot = get_nikke_service().get_outpost_storage()
            process.resource_label = snapshot.label
            process.resource_status = snapshot.status
            process.resource_updated_at = snapshot.updated_at.timestamp()
            if snapshot.percent is not None:
                process.resource_percent = snapshot.percent
            logger.info(
                "[NIKKE] '%s' %s 업데이트: status=%s percent=%s",
                process.name,
                snapshot.label,
                snapshot.status,
                snapshot.percent,
            )
            return snapshot.percent if snapshot.status == "ok" and snapshot.percent is not None else None
        except Exception as exc:
            logger.error("[NIKKE] '%s' 리소스 조회 실패: %s", process.name, exc)
            process.resource_status = "unavailable"
            process.resource_updated_at = time.time()
            return None

    def _calibrate_external_resource_on_game_start(self, process: ManagedProcess) -> None:
        """게임 시작 시 외부 리소스 예측값을 실제 API 값으로 보정합니다."""
        if not is_nikke_outpost_resource(
            getattr(process, "resource_provider", None),
            getattr(process, "resource_key", None),
        ):
            return

        try:
            from src.services.nikke import get_nikke_service

            logger.info("[NIKKE] '%s' 리소스 보정 체크 중...", process.name)
            predicted_before_fetch = process.get_resource_percentage()
            snapshot = get_nikke_service().get_outpost_storage()
            if snapshot.status != "ok" or snapshot.percent is None:
                logger.info(
                    "[NIKKE] '%s' 리소스 보정 스킵: status=%s message=%s",
                    process.name,
                    snapshot.status,
                    snapshot.message,
                )
                process.resource_label = snapshot.label
                process.resource_status = snapshot.status
                process.resource_updated_at = snapshot.updated_at.timestamp()
                self._persist_resource_state(process)
                return

            actual_percent = clamp_percent(snapshot.percent)
            if actual_percent is None:
                return

            if predicted_before_fetch is None:
                process.resource_label = snapshot.label
                process.resource_percent = actual_percent
                process.resource_status = snapshot.status
                process.resource_updated_at = snapshot.updated_at.timestamp()
                self._persist_resource_state(process)
                logger.info("[NIKKE] '%s' 리소스 초기화: %.1f%%", process.name, actual_percent)
                return

            difference = actual_percent - predicted_before_fetch
            if abs(difference) > NIKKE_OUTPOST_CORRECTION_THRESHOLD_PERCENT:
                last_session = self.data_manager.get_last_session(process.id)
                previous_value = getattr(last_session, "resource_percent_at_end", None) if last_session else None
                if last_session and previous_value is not None and hasattr(self.data_manager, "update_session_resource"):
                    corrected_percent = clamp_percent(float(previous_value) + difference)
                    if corrected_percent is not None:
                        self.data_manager.update_session_resource(last_session.id, corrected_percent)
                        logger.info(
                            "[NIKKE] '%s' 리소스 보정: 예상 %.1f%% → 실제 %.1f%% "
                            "(이전 세션 종료값 %.1f%% → %.1f%%)",
                            process.name,
                            predicted_before_fetch,
                            actual_percent,
                            float(previous_value),
                            corrected_percent,
                        )

            process.resource_label = snapshot.label
            process.resource_percent = actual_percent
            process.resource_status = snapshot.status
            process.resource_updated_at = snapshot.updated_at.timestamp()
            self._persist_resource_state(process)
        except Exception as exc:
            logger.error("[NIKKE] '%s' 리소스 보정 실패: %s", process.name, exc)

    def _calibrate_stamina_on_game_start(self, process: ManagedProcess) -> None:
        """게임 시작 시 스태미나 보정

        API에서 조회한 실제 스태미나와 로컬 예상값을 비교하여
        차이가 있을 경우 이전 세션의 종료 스태미나를 보정합니다.
        """
        _debug_log(f"[보정 시작] '{process.name}' (process_id={process.id}) - game_id={process.hoyolab_game_id}")

        # 먼저 직전 세션 정보 조회 (디버깅용)
        last_session = self.data_manager.get_last_session(process.id)
        _debug_log(f"[보정 직전세션] '{process.name}' - "
                   f"last_session_id={last_session.id if last_session else None}, "
                   f"db_stamina_at_end={last_session.stamina_at_end if last_session else None}, "
                   f"process.stamina_current={process.stamina_current}, "
                   f"process.stamina_updated_at={process.stamina_updated_at}")

        service = self._get_hoyolab_service()
        if not service:
            _debug_log(f"[보정 실패] '{process.name}' - HoYoLab 서비스 로드 실패")
            return

        if not service.is_available():
            _debug_log(f"[보정 스킵] '{process.name}' - genshin.py 라이브러리 없음")
            return

        if not service.is_configured():
            _debug_log(f"[보정 스킵] '{process.name}' - 인증 정보 없음")
            return

        try:
            # 1. API에서 현재 실제 스태미나 조회
            logger.info(f"[HoYoLab] '{process.name}' 스태미나 보정 체크 중...")
            stamina = service.get_stamina(process.hoyolab_game_id)
            if not stamina:
                _debug_log(f"[보정 실패] '{process.name}' - API 스태미나 조회 결과 없음")
                return

            actual_current = stamina.current
            _debug_log(f"[보정 API] '{process.name}' - 현재 스태미나: {actual_current}/{stamina.max}")

            # 2. 이전 기록이 없으면 현재 값으로 초기화만 수행
            if process.stamina_current is None or process.stamina_updated_at is None:
                process.stamina_current = actual_current
                process.stamina_max = stamina.max
                process.stamina_updated_at = stamina.updated_at.timestamp()
                self._persist_stamina_state(process)
                logger.info(f"[HoYoLab] '{process.name}' 스태미나 초기화: {actual_current}/{stamina.max}")
                _debug_log(f"[보정 초기화] '{process.name}' - 첫 스태미나 설정: {actual_current}/{stamina.max}")
                return

            # 3. 로컬 예상값 계산 (마지막 기록 + 시간 기반 회복량)
            elapsed_seconds = time.time() - process.stamina_updated_at
            # 게임별 회복률 (기본: 6분(360초)당 1 회복)
            recovery_rate = getattr(process, 'stamina_recovery_rate', None) or 360
            expected_recovery = int(elapsed_seconds / recovery_rate)
            expected_current = min(process.stamina_current + expected_recovery, stamina.max)

            _debug_log(f"[보정 계산] '{process.name}' - 이전값={process.stamina_current}, "
                       f"경과={elapsed_seconds:.0f}초, 회복량={expected_recovery}, 예상={expected_current}, 실제={actual_current}")

            # 4. 차이 계산 및 보정
            difference = actual_current - expected_current
            _debug_log(f"[보정 차이] '{process.name}' - diff={difference} (임계값=1)")

            if abs(difference) > 1:  # 유의미한 차이가 있는 경우 (1 이하는 오차 범위)
                # 이전 세션의 종료 스태미나 보정
                # 차이가 음수면: 실제로 더 많이 소모했음 → 이전 종료값을 낮춰야 함
                # 차이가 양수면: 예상보다 덜 소모했음 → 이전 종료값을 높여야 함
                last_session = self.data_manager.get_last_session(process.id)
                _debug_log(f"[보정 세션] '{process.name}' - last_session_id={last_session.id if last_session else None}, "
                           f"stamina_at_end={last_session.stamina_at_end if last_session else None}")

                if last_session and last_session.stamina_at_end is not None:
                    corrected_stamina = last_session.stamina_at_end + difference
                    corrected_stamina = max(0, min(corrected_stamina, stamina.max))

                    self.data_manager.update_session_stamina(
                        last_session.id,
                        stamina_at_end=corrected_stamina
                    )
                    logger.info(f"[HoYoLab] '{process.name}' 스태미나 보정: "
                          f"예상 {expected_current} → 실제 {actual_current} "
                          f"(이전 세션 종료값 {last_session.stamina_at_end} → {corrected_stamina})")
                    _debug_log(f"[보정 완료] '{process.name}' - 세션 {last_session.id}: "
                               f"{last_session.stamina_at_end} → {corrected_stamina}")
                else:
                    _debug_log(f"[보정 스킵] '{process.name}' - 이전 세션 없음 또는 stamina_at_end=None")
            else:
                _debug_log(f"[보정 불필요] '{process.name}' - 차이 임계값 이하 (|{difference}| <= 1)")

            # 5. 현재 스태미나 정보 업데이트
            process.stamina_current = actual_current
            process.stamina_max = stamina.max
            process.stamina_updated_at = stamina.updated_at.timestamp()
            self._persist_stamina_state(process)
            _debug_log(f"[보정 업데이트] '{process.name}' - 스태미나 정보 저장 완료")

        except Exception as e:
            logger.error(f"[HoYoLab] '{process.name}' 스태미나 보정 실패: {e}")
            _debug_log(f"[보정 예외] '{process.name}' - {type(e).__name__}: {e}")
