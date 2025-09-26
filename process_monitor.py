# process_monitor.py
import psutil
import time
import os
from typing import Dict, Any, Optional, List
from typing import Protocol
from data_models import ManagedProcess

class ProcessesDataPort(Protocol):
    managed_processes: list[ManagedProcess]
    def update_process(self, updated_process: ManagedProcess) -> bool: ...

class ProcessMonitor:
    def __init__(self, data_manager: ProcessesDataPort):
        self.data_manager = data_manager
        self.active_monitored_processes: Dict[str, Dict[str, Any]] = {}

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
                            self.active_monitored_processes[managed_proc.id] = {
                                'pid': actual_process_instance.pid,
                                'exe': normalized_monitoring_path, 
                                'start_time_approx': actual_process_instance.create_time() 
                            }
                            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Process STARTED: '{managed_proc.name}' (PID: {actual_process_instance.pid})")
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
                    if self.data_manager.update_process(managed_proc):
                         changed_occurred = True 
                    
                    cached_info = self.active_monitored_processes.pop(managed_proc.id)
                    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Process STOPPED: '{managed_proc.name}' (Was PID: {cached_info.get('pid')}). Last played updated: {time.ctime(termination_time)}")
        
        return changed_occurred