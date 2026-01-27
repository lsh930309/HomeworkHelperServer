# scheduler.py
import datetime
import time
import logging
from typing import Optional, Dict, Set, Tuple

from src.data.manager import DataManager

logger = logging.getLogger(__name__)
from src.data.data_models import ManagedProcess, GlobalSettings
from src.core.notifier import Notifier
from src.core.process_monitor import ProcessMonitor # ProcessMonitor 클래스 추가

# 프로세스 상태를 나타내는 상수 (문자열 반환용)
PROC_STATE_INCOMPLETE = "미완료"
PROC_STATE_COMPLETED = "완료됨"
PROC_STATE_RUNNING = "실행중"

class Scheduler:
    def __init__(self, data_manager: DataManager, notifier: Notifier, process_monitor: ProcessMonitor):
        self.data_manager = data_manager
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
        # 스태미나 알림 추적
        self.notified_stamina_full: Set[str] = set()  # 스태미나 알림을 보낸 프로세스 ID

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
            if now_dt.time() >= sleep_start_t: # Current time is after sleep start today
                # Sleep starts today and ends tomorrow
                return today_sleep_start_dt, today_sleep_end_dt.replace(day=today_sleep_start_dt.day) + datetime.timedelta(days=1)
            elif now_dt.time() < sleep_end_t: # Current time is before sleep end today (meaning sleep started yesterday)
                # Sleep started yesterday and ends today
                return today_sleep_start_dt.replace(day=now_dt.day) - datetime.timedelta(days=1), today_sleep_end_dt
            else: # Current time is between sleep end and next sleep start (daytime)
                # Next sleep period starts today and ends tomorrow
                return today_sleep_start_dt, today_sleep_end_dt.replace(day=today_sleep_start_dt.day) + datetime.timedelta(days=1)
        else:  # Same-day sleep period (e.g., 13:00 to 15:00, or 00:00 to 06:00)
            if sleep_start_t <= now_dt.time() < sleep_end_t: # Currently in sleep period
                return today_sleep_start_dt, today_sleep_end_dt
            elif now_dt.time() < sleep_start_t: # Before today's sleep period
                return today_sleep_start_dt, today_sleep_end_dt
            else: # After today's sleep period
                # Next sleep period starts tomorrow
                return today_sleep_start_dt + datetime.timedelta(days=1), today_sleep_end_dt + datetime.timedelta(days=1)

    def determine_process_visual_status(self, process: ManagedProcess, now_dt: datetime.datetime, gs: GlobalSettings) -> str:
        """ 특정 프로세스의 현재 시각적 상태를 [실행중], [미완료] 또는 [완료됨]으로 결정합니다. """
        
        # 0순위: 현재 실행 중인지 확인 (ProcessMonitor의 정보 활용)
        if self.process_monitor and process.id in self.process_monitor.active_monitored_processes:
            return PROC_STATE_RUNNING # 최우선으로 "실행중" 상태 반환

        is_incomplete = False
        last_played_dt: Optional[datetime.datetime] = None
        if process.last_played_timestamp:
            last_played_dt = datetime.datetime.fromtimestamp(process.last_played_timestamp)

        # 조건 ㄱ: 서버 리셋 시각 이후 현 시점까지 접속하지 않음
        if process.server_reset_time_str:
            server_reset_time_t = self._get_time_from_str(process.server_reset_time_str)
            if server_reset_time_t:
                today_server_reset_dt = now_dt.replace(
                    hour=server_reset_time_t.hour, minute=server_reset_time_t.minute,
                    second=0, microsecond=0
                )
                current_server_day_start_dt: datetime.datetime
                if now_dt.time() < server_reset_time_t:
                    current_server_day_start_dt = today_server_reset_dt - datetime.timedelta(days=1)
                else:
                    current_server_day_start_dt = today_server_reset_dt

                if last_played_dt is None or last_played_dt < current_server_day_start_dt:
                    is_incomplete = True
        
        # 조건 ㄴ: 고정 접속 시각 이후 현 시점까지 접속하지 않음 (하나라도 해당하면 미완료)
        if not is_incomplete and process.is_mandatory_time_enabled and process.mandatory_times_str:
            for mandatory_time_str in process.mandatory_times_str:
                mandatory_time_t = self._get_time_from_str(mandatory_time_str)
                if mandatory_time_t:
                    mandatory_dt_today = now_dt.replace(
                        hour=mandatory_time_t.hour, minute=mandatory_time_t.minute,
                        second=0, microsecond=0
                    )
                    if now_dt >= mandatory_dt_today: # 오늘 해당 고정 접속 시각이 지났거나 현재라면
                        if last_played_dt is None or last_played_dt < mandatory_dt_today:
                            is_incomplete = True
                            break # 하나라도 미완이면 더 볼 필요 없음
        
        # 조건 ㄷ: 마지막 종료 시각으로부터 사용자 설정 접속 주기를 "이미 초과하여" 접속하지 않음
        original_deadline_dt_for_cycle: Optional[datetime.datetime] = None # 사용자 주기에 따른 원래 마감 시간
        if process.user_cycle_hours and last_played_dt:
            original_deadline_dt_for_cycle = last_played_dt + datetime.timedelta(hours=process.user_cycle_hours)
            if now_dt > original_deadline_dt_for_cycle: # 이미 마감 시간 지남
                is_incomplete = True # 이것이 is_incomplete의 주된 조건 중 하나가 됨

        # <<< 새로운 조건 추가 >>>
        # 조건 ㄹ: (위 조건들로 아직 미완료가 아니고) 수면 시간 보정으로 인해 "미리 알림" 시점은 지났지만,
        #          아직 원래 마감은 안 됐고, 그 "미리 알림" 시점 이후로 플레이 안 한 경우
        if not is_incomplete and process.user_cycle_hours and last_played_dt and original_deadline_dt_for_cycle:
            # original_deadline_dt_for_cycle이 None이 아님을 위에서 보장
            
            # 이 조건은 "원래 마감 시간은 아직 지나지 않았을 때"만 의미가 있음
            if now_dt < original_deadline_dt_for_cycle:
                sleep_period = self._get_next_sleep_period(now_dt, gs)
                if sleep_period:
                    next_sleep_start_dt, next_sleep_end_dt = sleep_period
                    
                    # 원래 마감 시간이 다음 (또는 현재 진행중인) 수면 기간 내에 해당하는지 확인
                    if next_sleep_start_dt <= original_deadline_dt_for_cycle < next_sleep_end_dt:
                        sleep_correction_advance_hours = gs.sleep_correction_advance_notify_hours
                        # 실제 수면 보정 알림을 보내야 했던 시간 (수면 시작 시간 - 미리 알림 시간)
                        corrected_notify_trigger_dt = next_sleep_start_dt - datetime.timedelta(hours=sleep_correction_advance_hours)
                        
                        # 현재 시간이 이 "보정된 알림 트리거 시간" 이후이고, (아직 실제 수면 시작 전이거나 혹은 막 시작했더라도)
                        # 마지막 플레이가 이 "보정된 알림 트리거 시간" 이전이라면 [미완료]
                        if now_dt >= corrected_notify_trigger_dt and \
                           (last_played_dt < corrected_notify_trigger_dt): # last_played_dt가 None인 경우는 이미 위에서 필터링됨
                            is_incomplete = True
        
        if is_incomplete:
            return PROC_STATE_INCOMPLETE
        else:
            return PROC_STATE_COMPLETED

    def check_mandatory_times(self): # (send_notification에서 on_click_callback 제거된 버전)
        now = datetime.datetime.now()
        current_time = now.time()
        today_date_str = now.date().isoformat()

        for process in self.data_manager.managed_processes:
            if process.is_mandatory_time_enabled and process.mandatory_times_str:
                for mandatory_time_str in process.mandatory_times_str:
                    mandatory_time_obj = self._get_time_from_str(mandatory_time_str)
                    if not mandatory_time_obj:
                        continue

                    # Check if it's the exact minute for the mandatory time
                    if (current_time.hour == mandatory_time_obj.hour and
                            current_time.minute == mandatory_time_obj.minute):
                        notification_key = (process.id, mandatory_time_str, today_date_str)
                        if notification_key not in self.already_notified_mandatory_today:
                            logger.info(f"고정 접속 시간 알림: '{process.name}' - {mandatory_time_str}")
                            # 설정에 따라 고정 접속 시간 알림
                            if self.data_manager.global_settings.notify_on_mandatory_time:
                                self.notifier.send_notification(
                                    title=f"{process.name} - 접속 시간!",
                                    message=f"지금은 '{process.name}'의 고정 접속 시간({mandatory_time_str})입니다.",
                                    task_id_to_highlight=process.id,
                                    button_text="실행",
                                    button_action="run"
                                )
                            self.already_notified_mandatory_today.add(notification_key)

    def check_user_cycles(self): # (send_notification에서 on_click_callback 제거된 버전)
        now_dt = datetime.datetime.now()
        gs = self.data_manager.global_settings

        for process in self.data_manager.managed_processes:
            if process.user_cycle_hours and process.last_played_timestamp:
                last_played_dt = datetime.datetime.fromtimestamp(process.last_played_timestamp)
                deadline_dt = last_played_dt + datetime.timedelta(hours=process.user_cycle_hours)
                advance_notify_hours = gs.cycle_deadline_advance_notify_hours
                notify_start_dt = deadline_dt - datetime.timedelta(hours=advance_notify_hours)

                current_deadline_ts = deadline_dt.timestamp()

                # Skip if already notified for this specific deadline timestamp
                if self.notified_cycle_deadlines.get(process.id) == current_deadline_ts:
                    continue

                if notify_start_dt <= now_dt < deadline_dt:
                    # Check if we have notified for this deadline before (even if timestamp differs slightly due to load time)
                    # This check is more about preventing re-notification for the *same logical deadline event*
                    last_notified_ts_for_this_deadline = self.notified_cycle_deadlines.get(process.id)
                    if (last_notified_ts_for_this_deadline is None or
                            last_notified_ts_for_this_deadline < current_deadline_ts): # Ensure we notify for newer deadlines
                        time_remaining = deadline_dt - now_dt
                        hours_remaining = time_remaining.total_seconds() / 3600
                        minutes_remaining = (time_remaining.total_seconds() % 3600) / 60

                        if hours_remaining >= 1:
                            remaining_str = f"{hours_remaining:.1f}시간"
                        else:
                            remaining_str = f"{minutes_remaining:.0f}분"

                        logger.info(f"사용자 주기 만료 임박 알림: '{process.name}'. 마감: {deadline_dt.strftime('%H:%M')}")
                        if self.data_manager.global_settings.notify_on_cycle_deadline:
                            self.notifier.send_notification(
                                title=f"{process.name} - 접속 권장",
                                message=f"'{process.name}' 접속 주기가 약 {remaining_str} 후 만료됩니다. (마감: {deadline_dt.strftime('%H:%M')})",
                                task_id_to_highlight=process.id,
                                button_text="실행",
                                button_action="run"
                            )
                        self.notified_cycle_deadlines[process.id] = current_deadline_ts
                elif now_dt >= deadline_dt:
                    # Deadline has passed, potentially clear notification status if needed for re-notification after next play
                    pass # Or self.notified_cycle_deadlines.pop(process.id, None) if logic requires

    def check_sleep_corrected_cycles(self): # (send_notification에서 on_click_callback 제거된 버전)
        now_dt = datetime.datetime.now()
        gs = self.data_manager.global_settings
        sleep_period = self._get_next_sleep_period(now_dt, gs)

        if not sleep_period:
            return

        next_sleep_start_dt, next_sleep_end_dt = sleep_period
        sleep_correction_advance_hours = gs.sleep_correction_advance_notify_hours
        corrected_notify_trigger_dt = next_sleep_start_dt - datetime.timedelta(hours=sleep_correction_advance_hours)

        for process in self.data_manager.managed_processes:
            if process.user_cycle_hours and process.last_played_timestamp:
                last_played_dt = datetime.datetime.fromtimestamp(process.last_played_timestamp)
                original_deadline_dt = last_played_dt + datetime.timedelta(hours=process.user_cycle_hours)

                # Check if the original deadline falls within the upcoming sleep period
                # and if the current time is within the notification window before sleep starts
                if (next_sleep_start_dt <= original_deadline_dt < next_sleep_end_dt and
                        corrected_notify_trigger_dt <= now_dt < next_sleep_start_dt):
                    notification_key = (process.id, original_deadline_dt.timestamp())
                    if notification_key not in self.notified_sleep_corrected_tasks:
                        logger.info(f"수면 보정 알림: '{process.name}'. 원래 마감: {original_deadline_dt.strftime('%H:%M')}")
                        if self.data_manager.global_settings.notify_on_sleep_correction:
                            self.notifier.send_notification(
                                title=f"{process.name} - 미리 접속 권장!",
                                message=f"'{process.name}'의 다음 주기 마감({original_deadline_dt.strftime('%H:%M')})이 수면 시간({gs.sleep_start_time_str}~{gs.sleep_end_time_str}) 중입니다. 잠들기 전에 미리 접속하는 것이 좋습니다.",
                                task_id_to_highlight=process.id,
                                button_text="실행",
                                button_action="run"
                            )
                        self.notified_sleep_corrected_tasks[notification_key] = True
                        # Also mark this as notified for regular cycle to avoid double notification
                        self.notified_cycle_deadlines[process.id] = original_deadline_dt.timestamp()

    def check_daily_reset_tasks(self): # (send_notification에서 on_click_callback 제거된 버전)
        now_dt = datetime.datetime.now()

        for process in self.data_manager.managed_processes:
            if not process.server_reset_time_str:
                continue

            server_reset_time_t = self._get_time_from_str(process.server_reset_time_str)
            if not server_reset_time_t:
                continue

            today_server_reset_dt = now_dt.replace(
                hour=server_reset_time_t.hour, minute=server_reset_time_t.minute,
                second=0, microsecond=0
            )

            current_server_day_start_dt: datetime.datetime
            current_server_day_end_dt: datetime.datetime

            if now_dt.time() < server_reset_time_t: # Before today's reset time
                current_server_day_start_dt = today_server_reset_dt - datetime.timedelta(days=1)
                current_server_day_end_dt = today_server_reset_dt - datetime.timedelta(microseconds=1) # Ends just before reset
            else: # After or at today's reset time
                current_server_day_start_dt = today_server_reset_dt
                current_server_day_end_dt = (today_server_reset_dt + datetime.timedelta(days=1)) - datetime.timedelta(microseconds=1)

            notification_key = (process.id, current_server_day_start_dt.date().isoformat())
            if notification_key in self.notified_daily_reset_tasks:
                continue # Already notified for this task for this server day

            played_this_server_day = False
            if process.last_played_timestamp:
                last_played_dt = datetime.datetime.fromtimestamp(process.last_played_timestamp)
                if current_server_day_start_dt <= last_played_dt <= current_server_day_end_dt:
                    played_this_server_day = True

            if played_this_server_day:
                self.notified_daily_reset_tasks.add(notification_key) # Mark as handled for today
                continue

            # If not played this server day, check if it's time for a reminder
            reminder_trigger_dt = current_server_day_end_dt - datetime.timedelta(hours=self.daily_task_reminder_before_reset_hours)

            if reminder_trigger_dt <= now_dt < current_server_day_end_dt:
                logger.info(f"일일 과제 마감 임박 알림: '{process.name}'. 서버 하루 마감: {current_server_day_end_dt.strftime('%H:%M')}")
                if self.data_manager.global_settings.notify_on_daily_reset:
                    self.notifier.send_notification(
                        title=f"{process.name} - 일일 과제!",
                        message=f"'{process.name}'의 오늘 서버 과제 마감({current_server_day_end_dt.strftime('%H:%M:%S')})이 다가옵니다. (오늘 플레이 기록 없음)",
                        task_id_to_highlight=process.id,
                        button_text="실행",
                        button_action="run"
                    )
                self.notified_daily_reset_tasks.add(notification_key)

    def check_stamina_notifications(self):
        """호요버스 게임의 스태미나 알림 체크"""
        now_dt = datetime.datetime.now()
        gs = self.data_manager.global_settings
        
        # 스태미나 알림이 비활성화된 경우 건너뛰기
        if not gs.stamina_notify_enabled:
            return
        
        threshold = gs.stamina_notify_threshold
        
        for process in self.data_manager.managed_processes:
            # 호요버스 게임이 아니면 건너뛰기
            if not process.is_hoyoverse_game():
                continue
            
            # 스태미나 정보 가져오기
            stamina_info = process.get_predicted_stamina()
            if stamina_info is None:
                continue
            
            predicted, max_stamina = stamina_info
            
            # 임계값 체크: 스태미나가 (최대 - threshold) 이상인 경우
            if predicted >= max_stamina - threshold:
                # 이미 알림을 보낸 경우 건너뛰기
                if process.id in self.notified_stamina_full:
                    continue
                
                # 게임별 스태미나 이름
                stamina_name = "개척력" if process.hoyolab_game_id == "honkai_starrail" else "배터리"
                remaining = max_stamina - predicted


                logger.info(f"스태미나 알림: '{process.name}' - {stamina_name} {predicted}/{max_stamina}")
                self.notifier.send_notification(
                    title=f"{process.name} - {stamina_name} 가득 참",
                    message=f"'{process.name}'의 {stamina_name}이 곷 가득 찉니다! ({predicted}/{max_stamina}, {remaining}개 남음)",
                    task_id_to_highlight=process.id,
                    button_text="실행",
                    button_action="run"
                )
                self.notified_stamina_full.add(process.id)
            
            else:
                # 스태미나가 임계값 미만이면 알림 상태 초기화
                # (스태미나를 소비하고 다시 차오르면 알림)
                self.notified_stamina_full.discard(process.id)

    def run_all_checks(self) -> bool:
        """모든 스케줄러 검사를 실행하고, 프로세스 상태의 시각적 변경 여부를 반환합니다."""
        initial_statuses = {
            p.id: self.determine_process_visual_status(p, datetime.datetime.now(), self.data_manager.global_settings)
            for p in self.data_manager.managed_processes
        }

        # 주기적 로그 제거 (GUI 성능 개선)
        # current_time_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        # print(f"\n[{current_time_str}] 스케줄러 검사 실행...")
        self.check_daily_reset_tasks()
        self.check_sleep_corrected_cycles()
        self.check_mandatory_times()
        self.check_user_cycles()
        self.check_stamina_notifications()  # 스태미나 알림 체크 추가
        # print(f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 스케줄러 검사 완료.")

        # 검사 실행 후 상태를 다시 확인하여 변경 여부 감지
        final_statuses = {
            p.id: self.determine_process_visual_status(p, datetime.datetime.now(), self.data_manager.global_settings)
            for p in self.data_manager.managed_processes
        }

        if initial_statuses != final_statuses:
            # 상태 변경 시 콜백 함수 호출
            if self.status_change_callback:
                self.status_change_callback()
            return True # 상태 변경됨
        
        return False # 상태 변경 없음

def example_global_on_click_handler(received_task_id: Optional[str]):
    """ Example handler for notification clicks, for testing purposes. """
    # 테스트용 핸들러 - 실제 사용 시 로직 구현
    pass