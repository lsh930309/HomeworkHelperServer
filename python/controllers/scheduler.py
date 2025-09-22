# scheduler.py
import datetime
import time
from typing import Optional, Dict, Set, Tuple, List

from ..controllers.api_client import ApiClient
from ..models.data_models import ManagedProcess, GlobalSettings
from .notifier import Notifier
from .process_monitor import ProcessMonitor

# 프로세스 상태를 나타내는 상수 (문자열 반환용)
PROC_STATE_INCOMPLETE = "미완료"
PROC_STATE_COMPLETED = "완료됨"
PROC_STATE_RUNNING = "실행중"

class Scheduler:
    def __init__(self, api_client: ApiClient, notifier: Notifier, process_monitor: ProcessMonitor):
        self.api_client = api_client
        self.notifier = notifier
        self.process_monitor = process_monitor
        
        # 상태 변경 시 호출할 콜백 함수 (메인 윈도우에서 설정)
        self.status_change_callback = None
        
        # 알림 중복 방지를 위한 추적 변수들
        self.already_notified_mandatory_today: Set[Tuple[str, str, str]] = set()
        self.notified_cycle_deadlines: Dict[str, float] = {}
        self.notified_sleep_corrected_tasks: Dict[Tuple[str, float], bool] = {}
        self.notified_daily_reset_tasks: Set[Tuple[str, str]] = set()
        self.daily_task_reminder_before_reset_hours: float = 1.0

    def _get_time_from_str(self, time_str: str) -> Optional[datetime.time]:
        try:
            return datetime.datetime.strptime(time_str, "%H:%M").time()
        except (ValueError, TypeError):
            return None

    def _get_next_sleep_period(self, now_dt: datetime.datetime, gs: GlobalSettings) -> Optional[Tuple[datetime.datetime, datetime.datetime]]:
        sleep_start_t = self._get_time_from_str(gs.sleep_start_time_str)
        sleep_end_t = self._get_time_from_str(gs.sleep_end_time_str)

        if not sleep_start_t or not sleep_end_t:
            return None

        today_sleep_start_dt = now_dt.replace(hour=sleep_start_t.hour, minute=sleep_start_t.minute, second=0, microsecond=0)
        today_sleep_end_dt = now_dt.replace(hour=sleep_end_t.hour, minute=sleep_end_t.minute, second=0, microsecond=0)

        if sleep_start_t > sleep_end_t:  # Overnight sleep period (e.g., 22:00 to 06:00)
            if now_dt.time() >= sleep_start_t:
                return today_sleep_start_dt, today_sleep_end_dt + datetime.timedelta(days=1)
            elif now_dt.time() < sleep_end_t:
                return today_sleep_start_dt - datetime.timedelta(days=1), today_sleep_end_dt
            else:
                return today_sleep_start_dt, today_sleep_end_dt + datetime.timedelta(days=1)
        else:  # Same-day sleep period
            if sleep_start_t <= now_dt.time() < sleep_end_t:
                return today_sleep_start_dt, today_sleep_end_dt
            elif now_dt.time() < sleep_start_t:
                return today_sleep_start_dt, today_sleep_end_dt
            else:
                return today_sleep_start_dt + datetime.timedelta(days=1), today_sleep_end_dt + datetime.timedelta(days=1)

    def determine_process_visual_status(self, process: ManagedProcess, now_dt: datetime.datetime, gs: GlobalSettings) -> str:
        if self.process_monitor and process.id in self.process_monitor.active_monitored_processes:
            return PROC_STATE_RUNNING

        is_incomplete = False
        last_played_dt = datetime.datetime.fromtimestamp(process.last_played_timestamp) if process.last_played_timestamp else None

        if process.server_reset_time_str:
            server_reset_time_t = self._get_time_from_str(process.server_reset_time_str)
            if server_reset_time_t:
                today_server_reset_dt = now_dt.replace(hour=server_reset_time_t.hour, minute=server_reset_time_t.minute, second=0, microsecond=0)
                current_server_day_start_dt = today_server_reset_dt if now_dt.time() >= server_reset_time_t else today_server_reset_dt - datetime.timedelta(days=1)
                if last_played_dt is None or last_played_dt < current_server_day_start_dt:
                    is_incomplete = True
        
        if not is_incomplete and process.is_mandatory_time_enabled and process.mandatory_times_str:
            for mandatory_time_str in process.mandatory_times_str:
                mandatory_time_t = self._get_time_from_str(mandatory_time_str)
                if mandatory_time_t:
                    mandatory_dt_today = now_dt.replace(hour=mandatory_time_t.hour, minute=mandatory_time_t.minute, second=0, microsecond=0)
                    if now_dt >= mandatory_dt_today and (last_played_dt is None or last_played_dt < mandatory_dt_today):
                        is_incomplete = True
                        break
        
        original_deadline_dt_for_cycle: Optional[datetime.datetime] = None
        if process.user_cycle_hours and last_played_dt:
            original_deadline_dt_for_cycle = last_played_dt + datetime.timedelta(hours=process.user_cycle_hours)
            if now_dt > original_deadline_dt_for_cycle:
                is_incomplete = True

        if not is_incomplete and process.user_cycle_hours and last_played_dt and original_deadline_dt_for_cycle:
            if now_dt < original_deadline_dt_for_cycle:
                sleep_period = self._get_next_sleep_period(now_dt, gs)
                if sleep_period:
                    next_sleep_start_dt, next_sleep_end_dt = sleep_period
                    if next_sleep_start_dt <= original_deadline_dt_for_cycle < next_sleep_end_dt:
                        corrected_notify_trigger_dt = next_sleep_start_dt - datetime.timedelta(hours=gs.sleep_correction_advance_notify_hours)
                        if now_dt >= corrected_notify_trigger_dt and (last_played_dt < corrected_notify_trigger_dt):
                            is_incomplete = True
        
        return PROC_STATE_INCOMPLETE if is_incomplete else PROC_STATE_COMPLETED

    def check_mandatory_times(self, managed_processes: List[ManagedProcess], gs: GlobalSettings):
        now = datetime.datetime.now()
        current_time = now.time()
        today_date_str = now.date().isoformat()

        for process in managed_processes:
            if process.is_mandatory_time_enabled and process.mandatory_times_str:
                for mandatory_time_str in process.mandatory_times_str:
                    mandatory_time_obj = self._get_time_from_str(mandatory_time_str)
                    if not mandatory_time_obj:
                        continue

                    if (current_time.hour == mandatory_time_obj.hour and current_time.minute == mandatory_time_obj.minute):
                        notification_key = (process.id, mandatory_time_str, today_date_str)
                        if notification_key not in self.already_notified_mandatory_today:
                            if gs.notify_on_mandatory_time:
                                self.notifier.send_notification(
                                    title=f"{process.name} - 접속 시간!",
                                    message=f"지금은 '{process.name}'의 고정 접속 시간({mandatory_time_str})입니다.",
                                    task_id_to_highlight=process.id, button_text="실행", button_action="run"
                                )
                            self.already_notified_mandatory_today.add(notification_key)

    def check_user_cycles(self, managed_processes: List[ManagedProcess], gs: GlobalSettings):
        now_dt = datetime.datetime.now()
        for process in managed_processes:
            if process.user_cycle_hours and process.last_played_timestamp:
                last_played_dt = datetime.datetime.fromtimestamp(process.last_played_timestamp)
                deadline_dt = last_played_dt + datetime.timedelta(hours=process.user_cycle_hours)
                notify_start_dt = deadline_dt - datetime.timedelta(hours=gs.cycle_deadline_advance_notify_hours)
                current_deadline_ts = deadline_dt.timestamp()

                if self.notified_cycle_deadlines.get(process.id) == current_deadline_ts:
                    continue

                if notify_start_dt <= now_dt < deadline_dt:
                    last_notified_ts = self.notified_cycle_deadlines.get(process.id)
                    if last_notified_ts is None or last_notified_ts < current_deadline_ts:
                        time_remaining = deadline_dt - now_dt
                        hours_remaining, rem = divmod(time_remaining.total_seconds(), 3600)
                        remaining_str = f"{int(hours_remaining)}시간" if hours_remaining >= 1 else f"{int(rem / 60)}분"
                        if gs.notify_on_cycle_deadline:
                            self.notifier.send_notification(
                                title=f"{process.name} - 접속 권장",
                                message=f"'{process.name}' 접속 주기가 약 {remaining_str} 후 만료됩니다. (마감: {deadline_dt.strftime('%H:%M')})",
                                task_id_to_highlight=process.id, button_text="실행", button_action="run"
                            )
                        self.notified_cycle_deadlines[process.id] = current_deadline_ts

    def check_sleep_corrected_cycles(self, managed_processes: List[ManagedProcess], gs: GlobalSettings):
        now_dt = datetime.datetime.now()
        sleep_period = self._get_next_sleep_period(now_dt, gs)
        if not sleep_period: return

        next_sleep_start_dt, next_sleep_end_dt = sleep_period
        corrected_notify_trigger_dt = next_sleep_start_dt - datetime.timedelta(hours=gs.sleep_correction_advance_notify_hours)

        for process in managed_processes:
            if process.user_cycle_hours and process.last_played_timestamp:
                last_played_dt = datetime.datetime.fromtimestamp(process.last_played_timestamp)
                original_deadline_dt = last_played_dt + datetime.timedelta(hours=process.user_cycle_hours)

                if (next_sleep_start_dt <= original_deadline_dt < next_sleep_end_dt and corrected_notify_trigger_dt <= now_dt < next_sleep_start_dt):
                    notification_key = (process.id, original_deadline_dt.timestamp())
                    if notification_key not in self.notified_sleep_corrected_tasks:
                        if gs.notify_on_sleep_correction:
                            self.notifier.send_notification(
                                title=f"{process.name} - 미리 접속 권장!",
                                message=f"'{process.name}'의 다음 주기 마감({original_deadline_dt.strftime('%H:%M')})이 수면 시간({gs.sleep_start_time_str}~{gs.sleep_end_time_str}) 중입니다. 잠들기 전에 미리 접속하는 것이 좋습니다.",
                                task_id_to_highlight=process.id, button_text="실행", button_action="run"
                            )
                        self.notified_sleep_corrected_tasks[notification_key] = True
                        self.notified_cycle_deadlines[process.id] = original_deadline_dt.timestamp()

    def check_daily_reset_tasks(self, managed_processes: List[ManagedProcess], gs: GlobalSettings):
        now_dt = datetime.datetime.now()
        for process in managed_processes:
            if not process.server_reset_time_str: continue
            server_reset_time_t = self._get_time_from_str(process.server_reset_time_str)
            if not server_reset_time_t: continue

            today_reset_dt = now_dt.replace(hour=server_reset_time_t.hour, minute=server_reset_time_t.minute, second=0, microsecond=0)
            day_start_dt = today_reset_dt if now_dt.time() >= server_reset_time_t else today_reset_dt - datetime.timedelta(days=1)
            day_end_dt = day_start_dt + datetime.timedelta(days=1) - datetime.timedelta(microseconds=1)

            notification_key = (process.id, day_start_dt.date().isoformat())
            if notification_key in self.notified_daily_reset_tasks: continue

            played_today = False
            if process.last_played_timestamp:
                last_played_dt = datetime.datetime.fromtimestamp(process.last_played_timestamp)
                if day_start_dt <= last_played_dt <= day_end_dt:
                    played_today = True

            if played_today:
                self.notified_daily_reset_tasks.add(notification_key)
                continue

            reminder_trigger_dt = day_end_dt - datetime.timedelta(hours=self.daily_task_reminder_before_reset_hours)
            if reminder_trigger_dt <= now_dt < day_end_dt:
                if gs.notify_on_daily_reset:
                    self.notifier.send_notification(
                        title=f"{process.name} - 일일 과제!",
                        message=f"'{process.name}'의 오늘 서버 과제 마감({day_end_dt.strftime('%H:%M:%S')})이 다가옵니다. (오늘 플레이 기록 없음)",
                        task_id_to_highlight=process.id, button_text="실행", button_action="run"
                    )
                self.notified_daily_reset_tasks.add(notification_key)

    def run_all_checks(self) -> bool:
        processes_data = self.api_client.get_processes()
        settings_data = self.api_client.get_settings()

        if not settings_data:
            print("Scheduler: Could not fetch settings from server. Skipping checks.")
            return False
        
        managed_processes = [ManagedProcess.from_dict(p) for p in processes_data]
        gs = GlobalSettings.from_dict(settings_data)

        now = datetime.datetime.now()
        initial_statuses = {p.id: self.determine_process_visual_status(p, now, gs) for p in managed_processes}

        self.check_daily_reset_tasks(managed_processes, gs)
        self.check_sleep_corrected_cycles(managed_processes, gs)
        self.check_mandatory_times(managed_processes, gs)
        self.check_user_cycles(managed_processes, gs)

        final_statuses = {p.id: self.determine_process_visual_status(p, datetime.datetime.now(), gs) for p in managed_processes}

        if initial_statuses != final_statuses:
            if self.status_change_callback:
                self.status_change_callback()
            return True
        
        return False
