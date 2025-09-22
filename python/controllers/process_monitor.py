# process_monitor.py
import psutil
import time
import os
from typing import Dict, Any, Optional, List

from ..controllers.api_client import ApiClient
from ..models.data_models import ManagedProcess

class ProcessMonitor:
    def __init__(self, api_client: ApiClient):
        self.api_client = api_client
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

        # 1. Get all currently running processes from psutil
        current_system_processes: Dict[Optional[str], psutil.Process] = {}
        for proc in psutil.process_iter(['pid', 'name', 'exe', 'create_time']):
            try:
                if proc.info['exe']:
                    exe_path = self._normalize_path(proc.info['exe'])
                    if exe_path and exe_path not in current_system_processes:
                        current_system_processes[exe_path] = proc
            except (psutil.NoSuchProcess, psutil.AccessDenied, TypeError, FileNotFoundError):
                continue

        # 2. Get all managed processes from the API
        processes_data = self.api_client.get_processes()
        managed_processes = {p['id']: ManagedProcess.from_dict(p) for p in processes_data}

        # 3. Check for newly stopped processes
        for active_id in list(self.active_monitored_processes.keys()):
            active_proc_info = self.active_monitored_processes[active_id]
            normalized_path = self._normalize_path(active_proc_info.get('exe'))

            is_still_running = normalized_path in current_system_processes
            is_still_managed = active_id in managed_processes

            if not is_still_running or not is_still_managed:
                termination_time = time.time()

                if is_still_managed:
                    update_data = {'last_played_timestamp': termination_time}
                    if self.api_client.update_process(active_id, update_data):
                        changed_occurred = True

                cached_info = self.active_monitored_processes.pop(active_id)
                proc_name = managed_processes.get(active_id, type('',(object,),{'name': 'Unknown'})()).name
                print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Process STOPPED: '{proc_name}' (Was PID: {cached_info.get('pid')}). Last played updated: {time.ctime(termination_time)}")
                changed_occurred = True

        # 4. Check for newly started processes
        for proc_id, managed_proc in managed_processes.items():
            normalized_monitoring_path = self._normalize_path(managed_proc.monitoring_path)
            if not normalized_monitoring_path:
                continue

            is_currently_running = normalized_monitoring_path in current_system_processes
            was_previously_active = proc_id in self.active_monitored_processes

            if is_currently_running and not was_previously_active:
                actual_process_instance = current_system_processes[normalized_monitoring_path]
                try:
                    self.active_monitored_processes[managed_proc.id] = {
                        'pid': actual_process_instance.pid,
                        'exe': normalized_monitoring_path,
                        'start_time_approx': actual_process_instance.create_time()
                    }
                    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] Process STARTED: '{managed_proc.name}' (PID: {actual_process_instance.pid})")
                    changed_occurred = True
                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    print(f"Error getting start info for '{managed_proc.name}': {e}")

        return changed_occurred
