from PyQt6.QtWidgets import QSystemTrayIcon, QMenu, QApplication, QStyle
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtCore import QObject # QObject는 많은 Qt 클래스의 기본 클래스입니다

# 타입 힌팅 및 순환 참조 관련 주석:
# main_window 인자의 타입 힌트는 좋은 관행이지만, MainWindow가 TrayManager를 임포트하는 경우
# 순환 참조가 발생할 수 있습니다. 복잡한 시나리오에서는 문자열로 순방향 선언을 하거나
# `typing.TYPE_CHECKING`을 사용하여 이 문제를 해결할 수 있습니다.
# 여기서는 'Any'를 사용하거나 명시적 타입을 생략하는 방식을 가정합니다.
# from typing import TYPE_CHECKING
# if TYPE_CHECKING:
#     from homework_helper import MainWindow # homework_helper.py에 MainWindow가 있다고 가정합니다

class TrayManager(QObject): # 내부적으로 시그널/슬롯을 사용한다면 QObject로부터 상속받습니다
    def __init__(self, main_window): # main_window는 MainWindow의 인스턴스가 됩니다
        super().__init__(main_window) # main_window를 QObject의 부모로 전달합니다
        self.main_window = main_window
        self.tray_icon = QSystemTrayIcon(self.main_window) # 부모가 올바르게 설정되었습니다

        self._setup_tray_icon_and_menu()

    def _setup_tray_icon_and_menu(self):
        """트레이 아이콘, 툴팁 및 컨텍스트 메뉴를 설정합니다."""
        # 메인 창의 아이콘을 트레이 아이콘으로 사용합니다.
        tray_icon_image = self.main_window.windowIcon()
        if tray_icon_image.isNull():
            # 메인 창 아이콘이 설정되지 않았거나 null일 경우의 대체 아이콘입니다.
            tray_icon_image = QIcon(QApplication.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))
        self.tray_icon.setIcon(tray_icon_image)
        self.tray_icon.setToolTip(QApplication.applicationName() or "숙제 관리자") # 애플리케이션 이름이 설정된 경우 해당 이름을 사용합니다.

        # 컨텍스트 메뉴를 생성합니다.
        tray_menu = QMenu(self.main_window) # QMenu의 부모를 main_window로 설정합니다.

        # 창 보이기/숨기기 액션
        show_hide_action = QAction("창 보이기/숨기기", self.main_window)
        show_hide_action.triggered.connect(self.toggle_window_visibility)
        tray_menu.addAction(show_hide_action)

        # 설정 액션
        # main_window에 open_global_settings_dialog 메소드가 있다고 가정합니다.
        if hasattr(self.main_window, 'open_global_settings_dialog'):
            settings_action_tray = QAction("전역 설정...", self.main_window)
            settings_action_tray.triggered.connect(self.main_window.open_global_settings_dialog)
            tray_menu.addAction(settings_action_tray)
            tray_menu.addSeparator()

        # 종료 액션
        # main_window에 'initiate_quit_sequence'와 같이
        # 타이머 중지 및 기타 정리 작업을 애플리케이션 종료 전에 처리하는 메소드가 있다고 가정합니다.
        quit_action_tray = QAction("종료", self.main_window)
        if hasattr(self.main_window, 'initiate_quit_sequence'):
            quit_action_tray.triggered.connect(self.main_window.initiate_quit_sequence)
        else:
            # 해당 메소드가 없을 경우의 대체 처리 (덜 이상적임)
            quit_action_tray.triggered.connect(self.direct_quit_application)
        tray_menu.addAction(quit_action_tray)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self._handle_tray_icon_activation)
        self.tray_icon.show()
        print("TrayManager: 트레이 아이콘 생성 및 표시됨.")

    def toggle_window_visibility(self):
        """메인 창을 보여주거나 숨깁니다."""
        if self.main_window.isVisible() and not self.main_window.isMinimized():
            self.main_window.hide()
            print("TrayManager: 창 숨김.")
        else:
            self.main_window.showNormal() # 복원하고 표시합니다.
            self.main_window.activateWindow() # 최상단으로 가져옵니다.
            self.main_window.raise_()         # 다른 창들보다 위에 있도록 보장합니다.
            print("TrayManager: 창 보임.")

    def _handle_tray_icon_activation(self, reason: QSystemTrayIcon.ActivationReason):
        """트레이 아이콘 활성화 이벤트(예: 클릭, 더블클릭)를 처리합니다."""
        if reason == QSystemTrayIcon.ActivationReason.Trigger or \
           reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.toggle_window_visibility()

    def handle_window_close_event(self, event):
        """
        MainWindow의 closeEvent에 의해 호출됩니다.
        이벤트를 무시하고 창을 트레이로 숨깁니다.
        """
        if event:
            event.ignore()
        self.main_window.hide()
        print("TrayManager: 창 닫기 이벤트 가로채서 숨김 처리.")

    def handle_minimize_event(self):
        """
        메인 윈도우의 changeEvent (최소화 시)에서 호출되어 창을 숨깁니다.
        """
        print("TrayManager: 최소화 이벤트 수신, 창 숨김 처리.")
        self.main_window.hide()
        # 트레이 아이콘은 이미 표시 중이어야 합니다.

    def hide_tray_icon(self):
        """트레이 아이콘을 숨깁니다. 애플리케이션 종료 전에 호출되어야 합니다."""
        self.tray_icon.hide()
        print("TrayManager: 트레이 아이콘 숨김.")

    def direct_quit_application(self):
        """메인 창 정리 작업 없이 애플리케이션을 직접 종료합니다. (덜 이상적인 방법)"""
        print("TrayManager: 직접 종료 (메인 윈도우 정리 작업 없을 수 있음).")
        self.hide_tray_icon()
        app_instance = QApplication.instance()
        if app_instance:
            app_instance.quit()

    def is_tray_icon_visible(self) -> bool:
        """트레이 아이콘이 현재 보이는지 여부를 반환합니다."""
        return self.tray_icon.isVisible()