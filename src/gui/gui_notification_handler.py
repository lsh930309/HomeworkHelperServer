from typing import Optional

from PyQt6.QtCore import QObject, pyqtSlot


class GuiNotificationHandler(QObject):
    """토스트 알림 클릭 이벤트를 메인 스레드에서 처리합니다."""

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main_window = main_window

    @pyqtSlot(str, str)
    def process_system_notification_activation(self, task_id_obj: Optional[str], source: Optional[str] = None):
        """
        토스트 알림 클릭 처리.
        - source == 'run': 해당 게임 실행
        - 그 외(본문 클릭): 게임 실행 중이면 사이드바 표시, 아니면 메인 창 표시
        """
        try:
            task_id = task_id_obj if task_id_obj else None

            if source == 'run' and task_id:
                if hasattr(self.main_window, 'handle_launch_button_in_row'):
                    self.main_window.handle_launch_button_in_row(task_id)
                return

            # 본문 클릭: 게임 실행 중이면 사이드바, 아니면 메인 창
            is_game_running = (
                hasattr(self.main_window, 'process_monitor')
                and bool(self.main_window.process_monitor.active_monitored_processes)
            )
            if is_game_running and hasattr(self.main_window, '_sidebar_controller'):
                sidebar = self.main_window._sidebar_controller._sidebar
                if sidebar is not None:
                    sidebar.slide_in()
                    return

            if self.main_window.isMinimized():
                self.main_window.showNormal()
            else:
                self.main_window.show()
            self.main_window.activateWindow()
            self.main_window.raise_()

        except Exception as e:
            print(f"[알림 콜백 예외] {e}")