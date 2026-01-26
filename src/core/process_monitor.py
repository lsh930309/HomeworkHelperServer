# process_monitor.py
import psutil
import time
import os
import logging
from typing import Dict, Any, Optional, List, Protocol
from src.data.data_models import ManagedProcess

logger = logging.getLogger(__name__)


class ProcessesDataPort(Protocol):
    managed_processes: list[ManagedProcess]
    def update_process(self, updated_process: ManagedProcess) -> bool: ...
    def start_session(self, process_id: str, process_name: str, start_timestamp: float) -> Any: ...
    def end_session(self, session_id: int, end_timestamp: float, stamina_at_end: Optional[int] = None) -> Any: ...
    def get_last_session(self, process_id: str) -> Any: ...
    def update_session_stamina(self, session_id: int, stamina_at_end: int) -> bool: ...


class ProcessMonitor:
    def __init__(self, data_manager: ProcessesDataPort):
        self.data_manager = data_manager
        self.active_monitored_processes: Dict[str, Dict[str, Any]] = {}  # key: process_id, value: {pid, exe, start_time_approx, session_id}
        self._hoyolab_service = None  # Lazy initialization

    def _get_hoyolab_service(self):
        """HoYoLab 서비스 인스턴스 (lazy init)"""
        if self._hoyolab_service is None:
            try:
                from src.services.hoyolab import get_hoyolab_service
                self._hoyolab_service = get_hoyolab_service()
            except ImportError:
                logger.warning("HoYoLab 서비스를 로드할 수 없습니다.")
                return None
        return self._hoyolab_service

    def _normalize_path(self, path: Optional[str]) -> Optional[str]:
        if not path: 
            return None
        try: 
            return os.path.normcase(os.path.abspath(path))
        except Exception: 
            return path 

    def check_and_update_statuses(self) -> bool:
        changed_occurred = False 
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
                            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Process STARTED: '{managed_proc.name}' (PID: {actual_process_instance.pid}, Session ID: {session.id if session else 'N/A'})")
                            changed_occurred = True # <<< 프로세스 시작 시에도 변경으로 간주
                        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                            print(f"'{managed_proc.name}' 시작 정보 가져오는 중 오류: {e}")
                            if managed_proc.id in self.active_monitored_processes:
                                self.active_monitored_processes.pop(managed_proc.id)
                    else:
                        print(f"경고: '{managed_proc.name}'이 실행 중으로 감지되었으나, 프로세스 인스턴스 정보를 찾을 수 없습니다.")
            else:
                if was_previously_active:
                    termination_time = time.time()
                    managed_proc.last_played_timestamp = termination_time

                    # 호요버스 게임인 경우 스태미나 조회를 세션 종료 전에 먼저 수행
                    stamina_at_end = None
                    if managed_proc.is_hoyoverse_game():
                        stamina_at_end = self._update_stamina_on_game_exit(managed_proc)

                    # 세션 종료 기록 (스태미나 값 포함)
                    cached_info = self.active_monitored_processes.pop(managed_proc.id)
                    session_id = cached_info.get('session_id')
                    if session_id:
                        ended_session = self.data_manager.end_session(session_id, termination_time, stamina_at_end)
                        if ended_session:
                            stamina_info = f", Stamina: {stamina_at_end}" if stamina_at_end is not None else ""
                            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Process STOPPED: '{managed_proc.name}' (Was PID: {cached_info.get('pid')}, Session ID: {session_id}, Duration: {ended_session.session_duration:.2f}s{stamina_info})")
                        else:
                            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Process STOPPED: '{managed_proc.name}' (Was PID: {cached_info.get('pid')}, Session end recording failed)")
                    else:
                        print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Process STOPPED: '{managed_proc.name}' (Was PID: {cached_info.get('pid')})")

                    if self.data_manager.update_process(managed_proc):
                         changed_occurred = True

                    print(f"    Last played updated: {time.ctime(termination_time)}")
        
        return changed_occurred

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
            print(f"[HoYoLab] '{process.name}' 스태미나 조회 중...")
            stamina = service.get_stamina(process.hoyolab_game_id)
            if stamina:
                process.stamina_current = stamina.current
                process.stamina_max = stamina.max
                process.stamina_updated_at = time.time()
                print(f"[HoYoLab] '{process.name}' 스태미나 업데이트: {stamina.current}/{stamina.max}")
                return stamina.current
            else:
                print(f"[HoYoLab] '{process.name}' 스태미나 조회 결과 없음")
                return None
        except Exception as e:
            logger.error(f"[HoYoLab] 스태미나 조회 실패: {e}")
            print(f"[HoYoLab] '{process.name}' 스태미나 조회 실패: {e}")
            return None

    def _calibrate_stamina_on_game_start(self, process: ManagedProcess) -> None:
        """게임 시작 시 스태미나 보정

        API에서 조회한 실제 스태미나와 로컬 예상값을 비교하여
        차이가 있을 경우 이전 세션의 종료 스태미나를 보정합니다.
        """
        service = self._get_hoyolab_service()
        if not service:
            return

        if not service.is_available() or not service.is_configured():
            return

        try:
            # 1. API에서 현재 실제 스태미나 조회
            print(f"[HoYoLab] '{process.name}' 스태미나 보정 체크 중...")
            stamina = service.get_stamina(process.hoyolab_game_id)
            if not stamina:
                return

            actual_current = stamina.current

            # 2. 이전 기록이 없으면 현재 값으로 초기화만 수행
            if process.stamina_current is None or process.stamina_updated_at is None:
                process.stamina_current = actual_current
                process.stamina_max = stamina.max
                process.stamina_updated_at = time.time()
                self.data_manager.update_process(process)
                print(f"[HoYoLab] '{process.name}' 스태미나 초기화: {actual_current}/{stamina.max}")
                return

            # 3. 로컬 예상값 계산 (마지막 기록 + 시간 기반 회복량)
            elapsed_seconds = time.time() - process.stamina_updated_at
            # 게임별 회복률 (기본: 6분(360초)당 1 회복)
            recovery_rate = getattr(process, 'stamina_recovery_rate', None) or 360
            expected_recovery = int(elapsed_seconds / recovery_rate)
            expected_current = min(process.stamina_current + expected_recovery, stamina.max)

            # 4. 차이 계산 및 보정
            difference = actual_current - expected_current

            if abs(difference) > 1:  # 유의미한 차이가 있는 경우 (1 이하는 오차 범위)
                # 이전 세션의 종료 스태미나 보정
                # 차이가 음수면: 실제로 더 많이 소모했음 → 이전 종료값을 낮춰야 함
                # 차이가 양수면: 예상보다 덜 소모했음 → 이전 종료값을 높여야 함
                last_session = self.data_manager.get_last_session(process.id)
                if last_session and last_session.stamina_at_end is not None:
                    corrected_stamina = last_session.stamina_at_end + difference
                    corrected_stamina = max(0, min(corrected_stamina, stamina.max))

                    self.data_manager.update_session_stamina(
                        last_session.id,
                        stamina_at_end=corrected_stamina
                    )
                    print(f"[HoYoLab] '{process.name}' 스태미나 보정: "
                          f"예상 {expected_current} → 실제 {actual_current} "
                          f"(이전 세션 종료값 {last_session.stamina_at_end} → {corrected_stamina})")

            # 5. 현재 스태미나 정보 업데이트
            process.stamina_current = actual_current
            process.stamina_max = stamina.max
            process.stamina_updated_at = time.time()
            self.data_manager.update_process(process)

        except Exception as e:
            logger.error(f"[HoYoLab] 스태미나 보정 실패: {e}")
            print(f"[HoYoLab] '{process.name}' 스태미나 보정 실패: {e}")
