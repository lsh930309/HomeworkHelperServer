from typing import Optional

from PyQt6.QtWidgets import QMessageBox, QAbstractItemView
from PyQt6.QtCore import Qt, QObject, pyqtSlot

# To avoid circular imports with type hinting, you might use:
# from typing import TYPE_CHECKING
# if TYPE_CHECKING:
#     from .homework_helper import MainWindow # Assuming homework_helper.py contains MainWindow
#     from .data_manager import DataManager


class GuiNotificationHandler(QObject):
    """
    Handles how the GUI (MainWindow) reacts to system notification activations,
    such as bringing the window to the front and highlighting the relevant task.
    """
    def __init__(self, main_window): # main_window will be an instance of MainWindow
        super().__init__(main_window) # Set main_window as parent
        self.main_window = main_window
        # It's often useful to have a direct reference to data_manager if used frequently
        # self.data_manager = main_window.data_manager

    @pyqtSlot(object, object) # task_id, source
    def process_system_notification_activation(self, task_id_obj: Optional[str], source: Optional[str] = None):
        """
        알림 클릭 시 호출. source가 'run'이면 해당 프로그램 실행, 아니면 기존대로 강조/메시지.
        """
        try:
            task_id = str(task_id_obj) if task_id_obj is not None else None
            print(f"GuiNotificationHandler: 시스템 알림 활성화 처리 시작 (Task ID: {task_id}, source: {source})")
            status_bar = self.main_window.statusBar()
            if status_bar:
                status_bar.showMessage(
                    f"알림 클릭됨 (ID: {task_id if task_id else '정보 없음'}, source: {source})", 3000
                )
            # 창 앞으로 가져오기
            if self.main_window.isMinimized():
                self.main_window.showNormal()
            else:
                self.main_window.show()
            self.main_window.activateWindow()
            self.main_window.raise_()
            # 실행 버튼 요청이면 바로 실행
            if source == 'run' and task_id:
                if hasattr(self.main_window, 'handle_launch_button_in_row'):
                    self.main_window.handle_launch_button_in_row(task_id)
                return
            # 이하 기존 강조/메시지 로직
            if not task_id:
                QMessageBox.information(
                    self.main_window,
                    "알림",
                    "일반 알림이 수신되었습니다."
                )
                return
            if not hasattr(self.main_window, 'data_manager') or \
               not hasattr(self.main_window, 'process_table') or \
               not hasattr(self.main_window, 'COL_NAME'):
                print("GuiNotificationHandler: MainWindow에 필수 속성(data_manager, process_table, COL_NAME)이 없습니다.")
                QMessageBox.warning(self.main_window, "오류", "알림 처리 중 내부 오류 발생.")
                return
            target_process = self.main_window.data_manager.get_process_by_id(task_id)
            target_process_name = target_process.name if target_process else "알 수 없는 작업"
            found_item = None
            for row in range(self.main_window.process_table.rowCount()):
                name_item = self.main_window.process_table.item(row, self.main_window.COL_NAME)
                if name_item and name_item.data(Qt.ItemDataRole.UserRole) == task_id:
                    found_item = name_item
                    break
            if found_item:
                self.main_window.process_table.scrollToItem(found_item, QAbstractItemView.ScrollHint.PositionAtCenter)
                QMessageBox.information(
                    self.main_window,
                    "알림 작업",
                    f"'{target_process_name}' 작업과(와) 관련된 알림입니다."
                )
            else:
                QMessageBox.information(
                    self.main_window,
                    "알림 작업",
                    f"알림을 받은 작업 ID '{task_id}' ({target_process_name})을(를) 현재 목록에서 찾을 수 없습니다."
                )
        except Exception as e:
            print(f"[알림 콜백 예외] {e}")