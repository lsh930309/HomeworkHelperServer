# main_window.py
"""메인 윈도우 및 아이콘 다운로더 클래스"""

import os
import datetime
import functools
from typing import Optional

# PyQt6 임포트
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTableWidget, QTableWidgetItem, QVBoxLayout, QHBoxLayout, QWidget,
    QHeaderView, QPushButton, QSizePolicy, QFileIconProvider, QAbstractItemView,
    QMessageBox, QMenu, QStyle, QStatusBar, QMenuBar, QAbstractScrollArea, QCheckBox,
    QLabel, QProgressBar
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QUrl, QEvent, QSize, QThread
from PyQt6.QtGui import QAction, QIcon, QColor, QDesktopServices, QFontDatabase, QFont, QPixmap, QPalette

# --- 로컬 모듈 임포트 ---
from dialogs import ProcessDialog, GlobalSettingsDialog, NumericTableWidgetItem, WebShortcutDialog
from tray_manager import TrayManager
from gui_notification_handler import GuiNotificationHandler
from instance_manager import run_with_single_instance_check, SingleInstanceApplication
from utils import get_bundle_resource_path
import requests

# --- 기타 로컬 유틸리티/데이터 모듈 임포트 ---
#from data_manager import DataManager
from api_client import ApiClient
from data_models import ManagedProcess, GlobalSettings, WebShortcut
from process_utils import get_qicon_for_file
from windows_utils import set_startup_shortcut, get_startup_shortcut_status
from launcher import Launcher
from notifier import Notifier
from scheduler import Scheduler, PROC_STATE_INCOMPLETE, PROC_STATE_COMPLETED, PROC_STATE_RUNNING

# ==================== 서버 종료 설정 ====================
# API 서버 Graceful Shutdown 타임아웃 (초 단위)
# - GUI 종료 시 서버가 안전하게 종료될 때까지 대기하는 최대 시간
# - 서버는 이 시간 내에 DB 체크포인트 등 정리 작업을 완료해야 함
# - 기본값: 10초 (일반적으로 충분함)
# - 타임아웃 초과 시: 서버를 독립 프로세스로 남겨두고 GUI만 종료
API_SERVER_SHUTDOWN_TIMEOUT = 10  # 초 단위
# ========================================================

class IconDownloader(QThread):
    """
    별도 스레드에서 URL로부터 아이콘을 다운로드하는 클래스.
    다운로드가 완료되면 icon_ready 시그널을 통해 QIcon 객체를 전달합니다.
    """
    icon_ready = pyqtSignal(QIcon)

    def __init__(self, url, parent=None):
        super().__init__(parent)
        self.url = url

    def run(self):
        try:
            # 5초 타임아웃으로 이미지 데이터 요청
            response = requests.get(self.url, timeout=5)
            response.raise_for_status()  # HTTP 오류 발생 시 예외 발생

            pixmap = QPixmap()
            # 받아온 바이트(byte) 데이터로부터 이미지 로드
            pixmap.loadFromData(response.content)

            if not pixmap.isNull():
                # 성공적으로 로드되면 QIcon 객체를 시그널로 전달
                self.icon_ready.emit(QIcon(pixmap))
        except Exception as e:
            # 오류 발생 시 콘솔에 로그 출력 (시그널은 발생하지 않음)
            print(f"아이콘 다운로드 실패 ({self.url}): {e}")

class MainWindow(QMainWindow):
    INSTANCE = None # 다른 모듈에서 메인 윈도우 인스턴스에 접근하기 위함
    request_table_refresh_signal = pyqtSignal() # 테이블 새로고침 요청 시그널

    # UI 색상 정의
    COLOR_INCOMPLETE = QColor("red")      # 미완료 상태 색상
    COLOR_COMPLETED = QColor("green")     # 완료 상태 색상
    COLOR_RUNNING = QColor("yellow")      # 실행 중 상태 색상
    COLOR_WEB_BTN_RED = QColor("red")     # 웹 버튼 (리셋 필요) 색상
    COLOR_WEB_BTN_GREEN = QColor("green") # 웹 버튼 (리셋 완료) 색상

    # 테이블 컬럼 인덱스 정의
    COL_ICON = 0
    COL_NAME = 1
    COL_LAST_PLAYED = 2
    COL_LAUNCH_BTN = 3
    COL_STATUS = 4
    TOTAL_COLUMNS = 5 # 전체 컬럼 개수 (0부터 시작하므로 5개면 range(6) 대신 5)

    def __init__(self, data_manager: ApiClient, instance_manager: Optional[SingleInstanceApplication] = None):
        super().__init__()
        MainWindow.INSTANCE = self
        self.data_manager = data_manager
        self._instance_manager = instance_manager # 종료 시 정리를 위해 인스턴스 매니저 참조 저장
        self.launcher = Launcher(run_as_admin=self.data_manager.global_settings.run_as_admin)

        # Launcher 콜백 설정: 게임 런처 재시작 확인
        self.launcher.launcher_restart_callback = self._on_launcher_restart_request

        # statusBar, menuBar 명시적 생성
        self.setStatusBar(QStatusBar(self))
        self.setMenuBar(QMenuBar(self))

        from process_monitor import ProcessMonitor # 순환 참조 방지를 위한 동적 임포트
        self.process_monitor = ProcessMonitor(self.data_manager)

        self.system_notifier = Notifier(QApplication.applicationName()) # 시스템 알림 객체 생성
        self.gui_notification_handler = GuiNotificationHandler(self) # GUI 알림 처리기 생성
        # 시스템 알림 콜백을 GUI 알림 처리기에 연결
        if hasattr(self.system_notifier, 'main_window_activated_callback'):
            self.system_notifier.main_window_activated_callback = self.gui_notification_handler.process_system_notification_activation

        self.scheduler = Scheduler(self.data_manager, self.system_notifier, self.process_monitor) # 스케줄러 객체 생성
        
        # 스케줄러의 상태 변경 콜백 함수 설정
        self.scheduler.status_change_callback = self._refresh_status_columns_immediate

        self.setWindowTitle(QApplication.applicationName() or "숙제 관리자") # 창 제목 설정

        self.setMinimumWidth(450) # 최소 너비 설정
        self.setGeometry(100, 100, 450, 300) # 창 초기 위치 및 크기 설정 (고정 너비)
        self._set_window_icon() # 창 아이콘 설정
        self.tray_manager = TrayManager(self) # 트레이 아이콘 관리자 생성
        self._create_menu_bar() # 메뉴 바 생성

        self._is_game_mode_active = False # 게임 모드 활성화 여부 추적

        # --- UI 구성 ---
        central_widget = QWidget(self) # 중앙 위젯 생성
        self.setCentralWidget(central_widget) # 중앙 위젯 설정
        main_layout = QVBoxLayout(central_widget) # 메인 수직 레이아웃 생성

        # 상단 버튼 영역 레이아웃 (게임 추가 버튼 + 동적 웹 버튼들 + 웹 바로가기 추가 버튼)
        self.top_button_area_layout = QHBoxLayout() # 수평 레이아웃
        self.add_game_button = QPushButton("새 게임 추가") # '새 게임 추가' 버튼 생성
        self.add_game_button.clicked.connect(self.open_add_process_dialog) # 버튼 클릭 시그널 연결
        self.top_button_area_layout.addWidget(self.add_game_button) # 레이아웃에 버튼 추가
        self.top_button_area_layout.addStretch(1) # 버튼들 사이의 공간 확장

        self.dynamic_web_buttons_layout = QHBoxLayout() # 동적 웹 버튼들을 위한 수평 레이아웃
        self.dynamic_web_buttons_layout.setSpacing(3) # 버튼 간격을 더 작게 설정
        self.top_button_area_layout.addLayout(self.dynamic_web_buttons_layout) # 상단 버튼 영역에 동적 웹 버튼 레이아웃 추가

        self.add_web_shortcut_button = QPushButton("+") # 웹 바로가기 추가 버튼 생성
        self.add_web_shortcut_button.setToolTip("새로운 웹 바로 가기 버튼을 추가합니다.") # 툴팁 설정

        # '+' 버튼 크기를 텍스트에 맞게 조절
        font_metrics = self.add_web_shortcut_button.fontMetrics()
        text_width = font_metrics.horizontalAdvance(" + ") # 텍스트 너비 계산 (양 옆 공백 포함)
        icon_button_size = text_width + 8 # 아이콘 버튼 크기 (여유 공간 추가)
        self.add_web_shortcut_button.setFixedSize(icon_button_size, icon_button_size) # 버튼 크기 고정

        self.add_web_shortcut_button.clicked.connect(self._open_add_web_shortcut_dialog) # 버튼 클릭 시그널 연결
        self.top_button_area_layout.addWidget(self.add_web_shortcut_button) # 상단 버튼 영역에 웹 바로가기 추가 버튼 추가

        # GitHub 바로가기 버튼 추가
        self.github_button = QPushButton()
        self.github_button.setToolTip("GitHub 저장소 방문")
        self.github_button.setText("GH") # 아이콘 로딩 전 기본 텍스트
        # 크기를 다른 아이콘 버튼과 맞춤
        self.github_button.setFixedSize(icon_button_size, icon_button_size)
        self.github_button.clicked.connect(lambda: self.open_webpage("https://github.com/lsh930309/HomeworkHelperServer"))
        self.top_button_area_layout.addWidget(self.github_button)

        # 시스템 테마에 따라 적절한 GitHub 아이콘 URL 선택
        palette = self.palette()
        # 창 배경색과 텍스트 색상의 밝기를 비교하여 다크 모드 여부 판단
        # 다크 모드에서는 보통 텍스트가 배경보다 밝습니다.
        is_dark_theme = palette.color(QPalette.ColorRole.WindowText).lightness() > palette.color(QPalette.ColorRole.Window).lightness()
        
        if is_dark_theme:
            favicon_url = "https://github.githubassets.com/favicons/favicon-dark.svg" # 다크 모드용 아이콘
        else:
            favicon_url = "https://github.githubassets.com/favicons/favicon.svg" # 라이트 모드용 아이콘

        self.icon_downloader = IconDownloader(favicon_url)
        self.icon_downloader.icon_ready.connect(self.set_github_button_icon) # 아이콘 다운로더에 연결
        self.icon_downloader.start()

        main_layout.addLayout(self.top_button_area_layout) # 메인 레이아웃에 상단 버튼 영역 추가

        # 프로세스 테이블 설정
        self.process_table = QTableWidget() # 테이블 위젯 생성
        self.process_table.setColumnCount(self.TOTAL_COLUMNS) # 컬럼 개수 설정
        self.process_table.setHorizontalHeaderLabels(["", "이름", "진행률", "실행", "상태"]) # 헤더 라벨 설정
        self._configure_table_header() # 테이블 헤더 상세 설정
        self.process_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers) # 편집 불가 설정
        self.process_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection) # 선택 불가 설정
        self.process_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu) # 컨텍스트 메뉴 정책 설정
        self.process_table.customContextMenuRequested.connect(self.show_table_context_menu) # 컨텍스트 메뉴 요청 시그널 연결
        
        # 테이블 크기 정책 설정 - 스크롤바 없이 내용에 맞게 조절
        self.process_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.process_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        
        # 테이블 행 높이 설정 (기본값 유지)
        vh = self.process_table.verticalHeader()
        if vh:
            vh.setDefaultSectionSize(30)  # 기본 행 높이를 30px로 설정 (기존과 비슷하게)
        
        main_layout.addWidget(self.process_table) # 메인 레이아웃에 테이블 추가

        # 초기 데이터 로드 및 UI 업데이트
        self.populate_process_list() # 프로세스 목록 채우기
        self._load_and_display_web_buttons() # 웹 바로가기 버튼 로드 및 표시
        self._adjust_window_height_for_table_rows() # 테이블 내용에 맞게 창 높이 조절
        
        # 창 크기 조절 잠금 설정 적용
        self._apply_window_resize_lock()

        # 시그널 및 타이머 설정
        self.request_table_refresh_signal.connect(self.populate_process_list_slot) # 테이블 새로고침 시그널 연결
        self.monitor_timer = QTimer(self); self.monitor_timer.timeout.connect(self.run_process_monitor_check); self.monitor_timer.start(1000) # 프로세스 모니터 타이머 (1초)
        self.scheduler_timer = QTimer(self); self.scheduler_timer.timeout.connect(self.run_scheduler_check); self.scheduler_timer.start(1000) # 스케줄러 타이머 (1초)

        # 웹 버튼 상태 새로고침 타이머
        self.web_button_refresh_timer = QTimer(self) # 웹 버튼 상태 새로고침 타이머
        self.web_button_refresh_timer.timeout.connect(self._refresh_web_button_states) # 타이머 타임아웃 시그널 연결
        self.web_button_refresh_timer.start(1000 * 60) # 1분마다 웹 버튼 상태 갱신 (1000ms * 60)

        # 상태 컬럼 자동 업데이트 타이머
        self.status_column_refresh_timer = QTimer(self) # 상태 컬럼 자동 업데이트 타이머
        self.status_column_refresh_timer.timeout.connect(self._refresh_status_columns) # 타이머 타임아웃 시그널 연결
        self.status_column_refresh_timer.start(1000 * 30) # 30초마다 상태 컬럼 갱신 (1000ms * 30)

        # 프로그레스 바 실시간 갱신 타이머
        self.progress_bar_refresh_timer = QTimer(self)
        self.progress_bar_refresh_timer.timeout.connect(self._refresh_progress_bars)
        self.progress_bar_refresh_timer.start(1000) # 1초마다 프로그레스 바 갱신

        # statusBar()가 None이 아닌지 확인 후 메시지 설정
        status_bar = self.statusBar()
        if status_bar:
            status_bar.showMessage("준비 완료.", 5000) # 상태 표시줄 메시지

        self.apply_startup_setting() # 시작 프로그램 설정 적용

    def set_github_button_icon(self, icon: QIcon):
        """IconDownloader로부터 받은 아이콘을 GitHub 버튼에 설정합니다."""
        if not icon.isNull():
            self.github_button.setIcon(icon)
            self.github_button.setText("") # 아이콘이 설정되면 텍스트는 지웁니다.

    def changeEvent(self, event: QEvent):
        """창 상태 변경 이벤트를 처리합니다 (최소화 시 트레이로 보내는 로직 포함)."""
        if event.type() == QEvent.Type.WindowStateChange:
            if self.windowState() & Qt.WindowState.WindowMinimized: # 창이 최소화 상태로 변경될 때
                if hasattr(self, 'tray_manager') and self.tray_manager.is_tray_icon_visible(): # 트레이 아이콘이 보이는 경우
                    self.tray_manager.handle_minimize_event() # 트레이 관리자에게 최소화 처리 위임
        super().changeEvent(event)

    def activate_and_show(self):
        """IPC 등을 통해 외부에서 창을 활성화하고 표시하도록 요청받았을 때 호출됩니다."""
        print("MainWindow: activate_and_show() 호출됨.")
        self.showNormal() # 창을 보통 크기로 표시 (최소화/숨김 상태에서 복원)
        self.activateWindow() # 창 활성화 (포커스 가져오기)
        self.raise_() # 창을 최상단으로 올림

    def open_webpage(self, url: str):
        """주어진 URL을 기본 웹 브라우저에서 엽니다."""
        if not QDesktopServices.openUrl(QUrl(url)):
            QMessageBox.warning(self, "URL 열기 실패", f"다음 URL을 여는 데 실패했습니다:\n{url}")

    def _set_window_icon(self):
        """창 아이콘을 설정합니다."""
        # .ico 파일 먼저 확인
        icon_path_ico = get_bundle_resource_path(r"img\app_icon.ico")
        print("아이콘 경로:", icon_path_ico)
        print("존재 여부:", os.path.exists(icon_path_ico))
        icon = QIcon(icon_path_ico)
        print("QIcon isNull:", icon.isNull())
        if os.path.exists(icon_path_ico) and not icon.isNull():
            self.setWindowIcon(icon)
        else:
            style = QApplication.style()
            self.setWindowIcon(style.standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))

    def _configure_table_header(self):
        h = self.process_table.horizontalHeader()
        if h:
            h.setSectionResizeMode(self.COL_ICON, QHeaderView.ResizeMode.ResizeToContents) # 아이콘 컬럼: 내용에 맞게
            h.setSectionResizeMode(self.COL_NAME, QHeaderView.ResizeMode.Stretch) # 이름 컬럼: 남은 공간 채우기
            h.setSectionResizeMode(self.COL_LAST_PLAYED, QHeaderView.ResizeMode.ResizeToContents) # 마지막 플레이 컬럼: 내용에 맞게
            h.setSectionResizeMode(self.COL_LAUNCH_BTN, QHeaderView.ResizeMode.ResizeToContents) # 실행 버튼 컬럼: 내용에 맞게
            h.setSectionResizeMode(self.COL_STATUS, QHeaderView.ResizeMode.ResizeToContents) # 상태 컬럼: 내용에 맞게

    def _create_menu_bar(self):
        mb = self.menuBar()
        if not mb:
            return
        fm = mb.addMenu("파일(&F)") # 파일 메뉴
        try:
            # 표준 종료 아이콘 가져오기 시도
            style = self.style()
            if style:
                ei_px = style.standardPixmap(QStyle.StandardPixmap.SP_DialogCloseButton)
                ei = QIcon.fromTheme("app-exit", QIcon(ei_px)) # 테마 아이콘 우선, 없으면 표준 아이콘 사용
            else:
                ei = QIcon()
        except AttributeError: # 예외 발생 시 빈 아이콘 사용 (안전 장치)
            ei = QIcon()
        ea = QAction(ei, "종료(&X)", self); ea.setShortcut("Ctrl+Q"); ea.triggered.connect(self.initiate_quit_sequence)
        if fm:
            fm.addAction(ea) # 종료 액션

        sm = mb.addMenu("설정(&S)") # 설정 메뉴
        gsa = QAction("전역 설정 변경...", self); gsa.triggered.connect(self.open_global_settings_dialog)
        if sm:
            sm.addAction(gsa) # 전역 설정 변경 액션

    def _load_always_on_top_setting(self):
        """전역 설정에서 항상 위 설정을 로드합니다."""
        always_on_top = self.data_manager.global_settings.always_on_top
        if always_on_top:
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowStaysOnTopHint)

    def open_global_settings_dialog(self):
        """전역 설정 대화 상자를 엽니다."""
        # 중요: 대화상자를 열 때마다 data_manager로부터 최신 설정 객체를 가져와야 합니다.
        # ApiClient는 설정을 저장할 때마다 내부의 global_settings 객체를 새로 교체하기 때문입니다.
        latest_settings = self.data_manager.global_settings
        previous_run_as_admin = latest_settings.run_as_admin  # 이전 설정 값 저장

        dlg = GlobalSettingsDialog(latest_settings, self) # 최신 설정으로 대화 상자 생성
        if dlg.exec(): # 대화 상자 실행 및 'OK' 클릭 시
            upd_gs = dlg.get_updated_settings() # 업데이트된 설정 가져오기
            # self.data_manager.global_settings = upd_gs # 전역 설정 업데이트
            self.data_manager.save_global_settings(upd_gs)

            # 관리자 권한 설정이 False에서 True로 변경되었는지 확인
            if not previous_run_as_admin and upd_gs.run_as_admin and not is_admin():
                # 관리자 권한으로 재시작 필요
                print("관리자 권한으로 실행 설정이 활성화되었습니다. 앱을 재시작합니다...")
                if run_as_admin():
                    # 재시작 성공 시 현재 인스턴스 종료
                    QApplication.quit()
                    sys.exit(0)
                else:
                    # 재시작 실패 시 상태 표시
                    status_bar = self.statusBar()
                    if status_bar:
                        status_bar.showMessage("관리자 권한으로 재시작 실패. 일반 권한으로 계속 실행합니다.", 5000)
                    return

            # Launcher 인스턴스의 관리자 권한 설정 업데이트
            self.launcher.run_as_admin = upd_gs.run_as_admin

            # '항상 위' 설정이 변경되었을 수 있으므로 즉시 적용
            self._load_always_on_top_setting()
            self.show() # 창 플래그 변경을 적용하기 위해 show() 호출

            status_bar = self.statusBar()
            if status_bar:
                status_bar.showMessage("전역 설정 저장됨.", 3000) # 상태 표시줄 메시지
            self.apply_startup_setting() # 시작 프로그램 설정 적용
            self.populate_process_list() # 전체 테이블 새로고침 (전역 설정 변경)
            self._refresh_web_button_states() # 웹 버튼 상태 새로고침 (전역 설정 변경이 웹 버튼에 영향을 줄 수 있는 경우)
            self._adjust_window_height_for_table_rows() # 창 높이 조절
            self._update_window_resize_lock() # 창 크기 조절 잠금 업데이트

            # 시작 프로그램 상태 확인 및 메시지 표시
            current_status = get_startup_shortcut_status()
            status_bar = self.statusBar()
            if status_bar:
                if current_status:
                    status_bar.showMessage("시작 프로그램에 등록되어 있습니다.", 3000)
                else:
                    status_bar.showMessage("시작 프로그램에 등록되어 있지 않습니다.", 3000)

    def apply_startup_setting(self):
        """시작 프로그램 자동 실행 설정을 적용합니다."""
        run = self.data_manager.global_settings.run_on_startup # 자동 실행 여부 가져오기
        print(f"apply_startup_setting 호출됨 - run_on_startup: {run}")
        status_bar = self.statusBar()
        if set_startup_shortcut(run): # 바로가기 설정 시도
            if status_bar:
                status_bar.showMessage(f"시작 시 자동 실행: {'활성' if run else '비활성'}", 3000)
        else:
            if status_bar:
                status_bar.showMessage("자동 실행 설정 중 문제 발생 가능.", 3000)

    def run_process_monitor_check(self):
        """실행 중인 프로세스를 확인하고 상태 변경 시 테이블을 새로고침합니다."""
        if self.process_monitor.check_and_update_statuses(): # 상태 변경 감지 시
            status_bar = self.statusBar()
            if status_bar:
                status_bar.showMessage("프로세스 상태 변경 감지됨.", 2000)
            self.update_process_statuses_only() # 상태 컬럼만 업데이트

        # 게임 모드 (실행 중인 게임이 있는지) 확인 및 창 상태 변경
        self._check_and_toggle_game_mode()

    def _check_and_toggle_game_mode(self):
        """실행 중인 게임이 있는지 확인하고, 그에 따라 창을 숨기거나 표시합니다."""
        # 현재 모니터링 중인 프로세스 중 '실행중' 상태인 것이 있는지 확인
        any_game_running = False
        for p in self.data_manager.managed_processes:
            if self.scheduler.determine_process_visual_status(p, datetime.datetime.now(), self.data_manager.global_settings) == PROC_STATE_RUNNING:
                any_game_running = True
                break

        if any_game_running and not self._is_game_mode_active:
            # 게임이 실행되었고, 아직 게임 모드가 활성화되지 않았다면
            self._is_game_mode_active = True
            print("게임 실행 감지: 창을 트레이로 숨깁니다.")
            self.tray_manager.handle_minimize_event() # 창을 트레이로 숨김
            status_bar = self.statusBar()
            if status_bar:
                status_bar.showMessage("게임 실행 중: 창이 트레이로 숨겨졌습니다.", 3000)
        elif not any_game_running and self._is_game_mode_active:
            # 모든 게임이 종료되었고, 게임 모드가 활성화되어 있었다면
            self._is_game_mode_active = False
            print("모든 게임 종료 감지: 창을 다시 표시합니다.")
            self.activate_and_show() # 창을 다시 표시
            status_bar = self.statusBar()
            if status_bar:
                status_bar.showMessage("모든 게임 종료: 창이 다시 표시되었습니다.", 3000)

    def run_scheduler_check(self):
        """스케줄러 검사를 실행하고 상태 변경이 있을 때만 테이블을 업데이트합니다."""
        # 스케줄러 검사 실행 (알림 발송 등)
        status_changed = self.scheduler.run_all_checks() # 게임 관련 스케줄 검사
        
        if status_changed:
            print("스케줄러에 의해 상태 변경 감지됨. 테이블 UI 업데이트.")
            self.update_process_statuses_only()
        
        # 웹 버튼 상태는 별도 타이머(_refresh_web_button_states)로 주기적으로 체크하므로 여기서 호출하지 않음

    def populate_process_list_slot(self):
        """테이블 새로고침 시그널에 연결된 슬롯입니다."""
        self.populate_process_list()

    def update_process_statuses_only(self):
        """프로세스 상태 컬럼만 업데이트합니다. 버튼은 유지하여 포커스 문제를 방지합니다."""
        if not hasattr(self, 'process_table') or not self.process_table:
            return
            
        processes = self.data_manager.managed_processes
        now_dt = datetime.datetime.now()
        gs = self.data_manager.global_settings
        palette = self.process_table.palette()
        df_bg, df_fg = palette.base(), palette.text()

        # 현재 테이블의 행 수와 프로세스 수가 다르면 전체 새로고침 필요
        if self.process_table.rowCount() != len(processes):
            self.populate_process_list()
            return

        has_changes = False
        for r, p in enumerate(processes):
            # 이름 컬럼에서 프로세스 ID 확인
            name_item = self.process_table.item(r, self.COL_NAME)
            if not name_item or name_item.data(Qt.ItemDataRole.UserRole) != p.id:
                # ID가 다르면 전체 새로고침 필요
                self.populate_process_list()
                return

            # 상태 컬럼만 업데이트
            st_str = self.scheduler.determine_process_visual_status(p, now_dt, gs)
            st_item = self.process_table.item(r, self.COL_STATUS)
            if st_item and st_item.text() != st_str:
                st_item.setText(st_str)
                st_item.setForeground(df_fg)  # 기본 글자색 설정

                # 상태에 따른 배경색 설정
                if st_str == PROC_STATE_RUNNING:
                    st_item.setBackground(self.COLOR_RUNNING)
                    st_item.setForeground(QColor("black"))
                elif st_str == PROC_STATE_INCOMPLETE:
                    st_item.setBackground(self.COLOR_INCOMPLETE)
                elif st_str == PROC_STATE_COMPLETED:
                    st_item.setBackground(self.COLOR_COMPLETED)
                else:
                    st_item.setBackground(df_bg)
                has_changes = True

            # 마지막 플레이 컬럼도 업데이트 (진행률 표시)
            percentage, time_str = self._calculate_progress_percentage(p, now_dt)
            progress_widget = self._create_progress_bar_widget(percentage, time_str)
            self.process_table.setCellWidget(r, self.COL_LAST_PLAYED, progress_widget)
            has_changes = True

        # 실제 변경사항이 있을 때만 상태바 메시지 표시
        if has_changes:
            status_bar = self.statusBar()
            if status_bar:
                status_bar.showMessage("프로세스 상태 업데이트됨.", 2000)

    def populate_process_list(self):
        """관리 대상 프로세스 목록을 테이블에 채웁니다."""
        self.process_table.setSortingEnabled(False) # 정렬 기능 임시 비활성화
        processes = self.data_manager.managed_processes # 관리 대상 프로세스 목록 가져오기
        self.process_table.setRowCount(len(processes)) # 행 개수 설정

        now_dt = datetime.datetime.now() # 현재 시각
        gs = self.data_manager.global_settings # 전역 설정
        palette = self.process_table.palette() # 테이블 팔레트
        df_bg, df_fg = palette.base(), palette.text() # 기본 배경색 및 글자색

        for r, p in enumerate(processes): # 각 프로세스에 대해 반복
            # 아이콘 컬럼
            icon_item = QTableWidgetItem()
            qi = get_qicon_for_file(p.monitoring_path) # 파일 경로로부터 아이콘 가져오기
            if qi and not qi.isNull(): icon_item.setIcon(qi)
            self.process_table.setItem(r, self.COL_ICON, icon_item); icon_item.setBackground(df_bg); icon_item.setForeground(df_fg)

            # 이름 컬럼 (UserRole에 ID 저장)
            name_item = QTableWidgetItem(p.name)
            name_item.setData(Qt.ItemDataRole.UserRole, p.id) # UserRole에 프로세스 ID 저장
            self.process_table.setItem(r, self.COL_NAME, name_item); name_item.setBackground(df_bg); name_item.setForeground(df_fg)

            # 마지막 플레이 컬럼 (진행률 표시)
            percentage, time_str = self._calculate_progress_percentage(p, now_dt)
            progress_widget = self._create_progress_bar_widget(percentage, time_str)
            self.process_table.setCellWidget(r, self.COL_LAST_PLAYED, progress_widget)

            # 실행 버튼 컬럼
            btn = QPushButton("실행")
            btn.clicked.connect(functools.partial(self.handle_launch_button_in_row, p.id)) # 버튼 클릭 시그널 연결
            self.process_table.setCellWidget(r, self.COL_LAUNCH_BTN, btn) # 셀에 버튼 위젯 설정

            # 상태 컬럼
            st_str = self.scheduler.determine_process_visual_status(p, now_dt, gs) # 시각적 상태 결정
            st_item = QTableWidgetItem(st_str)
            st_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter) # 텍스트 가운데 정렬
            self.process_table.setItem(r, self.COL_STATUS, st_item)
            st_item.setForeground(df_fg) # 기본 글자색 설정

            # 상태에 따른 배경색 설정
            if st_str == PROC_STATE_RUNNING: st_item.setBackground(self.COLOR_RUNNING); st_item.setForeground(QColor("black")) # 실행 중: 노란색 배경, 검은색 글자
            elif st_str == PROC_STATE_INCOMPLETE: st_item.setBackground(self.COLOR_INCOMPLETE) # 미완료: 빨간색 배경
            elif st_str == PROC_STATE_COMPLETED: st_item.setBackground(self.COLOR_COMPLETED) # 완료: 초록색 배경
            else: st_item.setBackground(df_bg) # 그 외: 기본 배경색

        self.process_table.setSortingEnabled(True) # 정렬 기능 다시 활성화
        self.process_table.sortByColumn(self.COL_NAME, Qt.SortOrder.AscendingOrder) # 이름 컬럼 기준 오름차순 정렬
        
        # 다른 컬럼들을 내용에 맞게 조정하고, 이름 컬럼은 남은 공간 채우기
        self.process_table.resizeColumnsToContents() # 먼저 모든 컬럼을 내용에 맞게 조정
        header = self.process_table.horizontalHeader()
        if header:
            header.setSectionResizeMode(self.COL_NAME, QHeaderView.ResizeMode.Stretch) # 이름 컬럼은 남은 공간 채우도록 설정

    def show_table_context_menu(self, pos): # 게임 테이블용 컨텍스트 메뉴
        """게임 테이블의 항목에 대한 컨텍스트 메뉴를 표시합니다."""
        item = self.process_table.itemAt(pos) # 클릭 위치의 아이템 가져오기
        if not item: return # 아이템 없으면 반환

        name_item = self.process_table.item(item.row(), self.COL_NAME)
        if not name_item:
            return
        pid = name_item.data(Qt.ItemDataRole.UserRole) # 선택된 행의 프로세스 ID 가져오기
        if not pid: return # ID 없으면 반환

        menu = QMenu(self) # 컨텍스트 메뉴 생성
        edit_act = QAction("편집", self) # 편집 액션
        del_act = QAction("삭제", self) # 삭제 액션

        edit_act.triggered.connect(functools.partial(self.handle_edit_action_for_row, pid)) # 편집 액션 시그널 연결
        del_act.triggered.connect(functools.partial(self.handle_delete_action_for_row, pid)) # 삭제 액션 시그널 연결

        menu.addActions([edit_act, del_act]) # 메뉴에 액션 추가
        menu.exec(self.process_table.mapToGlobal(pos)) # 컨텍스트 메뉴 표시

    def handle_edit_action_for_row(self, pid:str): # 게임 수정
        """선택된 게임 프로세스의 정보를 수정하는 대화 상자를 엽니다."""
        p_edit = self.data_manager.get_process_by_id(pid) # ID로 프로세스 정보 가져오기
        if not p_edit: QMessageBox.warning(self, "오류", f"ID '{pid}' 프로세스 없음."); return

        dialog = ProcessDialog(self, existing_process=p_edit) # 프로세스 수정 대화 상자 생성
        if dialog.exec(): # 'OK' 클릭 시
            data = dialog.get_data() # 수정된 데이터 가져오기
            if data:
                name = data["name"].strip() or p_edit.name # 이름이 비었으면 기존 이름 사용
                # 업데이트된 프로세스 객체 생성 (원본 경로 보존)
                upd_p = ManagedProcess(id=p_edit.id, name=name, monitoring_path=data["monitoring_path"],
                                       launch_path=data["launch_path"], server_reset_time_str=data["server_reset_time_str"],
                                       user_cycle_hours=data["user_cycle_hours"], mandatory_times_str=data["mandatory_times_str"],
                                       is_mandatory_time_enabled=data["is_mandatory_time_enabled"],
                                       last_played_timestamp=p_edit.last_played_timestamp,  # 마지막 플레이 시간은 유지
                                       original_launch_path=getattr(p_edit, 'original_launch_path', data["launch_path"]))  # 원본 경로 보존
                if self.data_manager.update_process(upd_p): # 프로세스 정보 업데이트
                    self.populate_process_list() # 전체 테이블 새로고침 (프로세스 정보 변경)
                    self._adjust_window_height_for_table_rows() # 창 높이 조절
                    status_bar = self.statusBar()
                    if status_bar:
                        status_bar.showMessage(f"'{upd_p.name}' 수정 완료.", 3000)
                else: QMessageBox.warning(self, "오류", "프로세스 수정 실패.")

    def handle_delete_action_for_row(self, pid:str): # 게임 삭제
        """선택된 게임 프로세스를 삭제합니다."""
        p_del = self.data_manager.get_process_by_id(pid) # ID로 프로세스 정보 가져오기
        if not p_del: QMessageBox.warning(self, "오류", f"ID '{pid}' 프로세스 없음."); return

        # 삭제 확인 대화 상자 표시
        reply = QMessageBox.question(self, "삭제 확인", f"'{p_del.name}' 삭제?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No) # 기본 선택은 'No'
        if reply == QMessageBox.StandardButton.Yes: # 'Yes' 클릭 시
            if self.data_manager.remove_process(pid): # 프로세스 삭제
                self.populate_process_list() # 전체 테이블 새로고침 (프로세스 삭제)
                self._adjust_window_height_for_table_rows() # 창 높이 조절
                status_bar = self.statusBar()
                if status_bar:
                    status_bar.showMessage(f"'{p_del.name}' 삭제 완료.", 3000)
            else: QMessageBox.warning(self, "오류", "프로세스 삭제 실패.")

    def handle_launch_button_in_row(self, pid:str): # 게임 실행
        """선택된 게임 프로세스를 실행합니다."""
        p_launch = self.data_manager.get_process_by_id(pid) # ID로 프로세스 정보 가져오기
        if not p_launch: QMessageBox.warning(self, "오류", f"ID '{pid}' 프로세스 없음."); return
        if not p_launch.launch_path: QMessageBox.warning(self, "오류", f"'{p_launch.name}' 실행 경로 없음."); return

        if self.launcher.launch_process(p_launch.launch_path): # 프로세스 실행 시도
            # 설정에 따라 실행 성공 알림 전송
            if self.data_manager.global_settings.notify_on_launch_success:
                self.system_notifier.send_notification(title="프로세스 실행", message=f"'{p_launch.name}' 실행함.", task_id_to_highlight=None)
            status_bar = self.statusBar()
            if status_bar:
                status_bar.showMessage(f"'{p_launch.name}' 실행 시도.", 3000)
            # 실행 성공 시 즉시 상태 업데이트
            self.update_process_statuses_only()
        else: # 실행 실패 시
            if self.data_manager.global_settings.notify_on_launch_failure:
                self.system_notifier.send_notification(title="실행 실패", message=f"'{p_launch.name}' 실행 실패. 로그 확인.", task_id_to_highlight=None)
            status_bar = self.statusBar()
            if status_bar:
                status_bar.showMessage(f"'{p_launch.name}' 실행 실패.", 3000)

    def open_add_process_dialog(self): # "새 게임 추가" 버튼에 연결
        """새 게임 프로세스를 추가하는 대화 상자를 엽니다."""
        dialog = ProcessDialog(self) # 새 프로세스 추가 대화 상자 생성
        if dialog.exec(): # 'OK' 클릭 시
            data = dialog.get_data() # 입력 데이터 가져오기
            if data:
                name = data["name"].strip()
                # 이름이 비어있고 모니터링 경로가 있으면 파일명으로 자동 생성
                if not name and data["monitoring_path"]:
                    name = os.path.splitext(os.path.basename(data["monitoring_path"]))[0] or "새 프로세스"
                # 새 프로세스 객체 생성 (원본 경로 보존)
                new_p = ManagedProcess(name=name, monitoring_path=data["monitoring_path"],
                                       launch_path=data["launch_path"], server_reset_time_str=data["server_reset_time_str"],
                                       user_cycle_hours=data["user_cycle_hours"], mandatory_times_str=data["mandatory_times_str"],
                                       is_mandatory_time_enabled=data["is_mandatory_time_enabled"],
                                       original_launch_path=data["launch_path"])  # 원본 경로 보존
                self.data_manager.add_process(new_p) # 데이터 매니저에 프로세스 추가
                self.populate_process_list() # 전체 테이블 새로고침 (프로세스 추가)
                self._adjust_window_height_for_table_rows() # 창 높이 조절
                status_bar = self.statusBar()
                if status_bar:
                    status_bar.showMessage(f"'{new_p.name}' 추가 완료.", 3000)

    # --- 웹 바로 가기 버튼 관련 메소드들 ---
    def _clear_layout(self, layout: QHBoxLayout):
        """주어진 QHBoxLayout의 모든 위젯을 제거하고 삭제합니다."""
        if layout is not None:
            while layout.count(): # 레이아웃에 아이템이 있는 동안 반복
                item = layout.takeAt(0) # 첫 번째 아이템 가져오기 (제거됨)
                if item is None:
                    continue
                widget = item.widget() # 아이템에서 위젯 가져오기
                if widget is not None:
                    widget.deleteLater() # 위젯 나중에 삭제 (메모리 누수 방지)

    def _determine_web_button_state(self, shortcut: WebShortcut, current_dt: datetime.datetime) -> str:
        """웹 바로가기 버튼의 현재 상태 (RED, GREEN, DEFAULT)를 결정합니다."""
        if not shortcut.refresh_time_str: return "DEFAULT" # 초기화 시간 없으면 기본 상태

        try:
            # 문자열 형식의 초기화 시간을 datetime.time 객체로 변환
            rt_hour, rt_minute = map(int, shortcut.refresh_time_str.split(':'))
            refresh_time_today_obj = datetime.time(rt_hour, rt_minute)
        except (ValueError, TypeError): # 변환 실패 시 기본 상태
            return "DEFAULT"

        # 오늘의 초기화 이벤트 시각
        todays_refresh_event_dt = datetime.datetime.combine(current_dt.date(), refresh_time_today_obj)
        # 마지막 초기화 타임스탬프 (없으면 None)
        last_reset_dt = datetime.datetime.fromtimestamp(shortcut.last_reset_timestamp) if shortcut.last_reset_timestamp else None

        if current_dt >= todays_refresh_event_dt: # 현재 시각이 오늘의 초기화 시각 이후인 경우
            # 마지막 초기화가 없거나, 오늘의 초기화 시각 이전이면 RED (리셋 필요)
            # 그렇지 않으면 GREEN (오늘 리셋 완료)
            return "RED" if last_reset_dt is None or last_reset_dt < todays_refresh_event_dt else "GREEN"
        else: # 현재 시각이 오늘의 초기화 시각 이전인 경우
            if last_reset_dt is None: return "DEFAULT" # 마지막 초기화 기록 없으면 기본
            # 어제의 초기화 이벤트 시각
            yesterdays_refresh_event_dt = datetime.datetime.combine(current_dt.date() - datetime.timedelta(days=1), refresh_time_today_obj)
            # 마지막 초기화가 어제의 초기화 시각 이후면 GREEN (어제 리셋 완료)
            # 그렇지 않으면 DEFAULT (어제 리셋 안 함 또는 해당 없음)
            return "GREEN" if last_reset_dt >= yesterdays_refresh_event_dt else "DEFAULT"

    def _apply_button_style(self, button: QPushButton, state: str):
        """버튼 상태에 따라 스타일시트를 적용합니다."""
        button.setStyleSheet("") # 기존 스타일 초기화
        if state == "RED":
            button.setStyleSheet(f"background-color: {self.COLOR_WEB_BTN_RED.name()};") # 빨간색 배경
        elif state == "GREEN":
            button.setStyleSheet(f"background-color: {self.COLOR_WEB_BTN_GREEN.name()};") # 초록색 배경

    def _refresh_web_button_states(self):
        """동적으로 생성된 모든 웹 바로가기 버튼의 상태를 새로고침합니다."""
        # print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 웹 버튼 상태 새로고침") # 디버그용 로그
        current_dt = datetime.datetime.now()
        for i in range(self.dynamic_web_buttons_layout.count()): # 레이아웃 내 모든 위젯에 대해 반복
            item = self.dynamic_web_buttons_layout.itemAt(i)
            if item is None:
                continue
            widget = item.widget()
            if isinstance(widget, QPushButton): # 위젯이 QPushButton인 경우
                button = widget
                shortcut_id = button.property("shortcut_id") # 버튼 속성에서 바로가기 ID 가져오기
                if shortcut_id:
                    shortcut = self.data_manager.get_web_shortcut_by_id(shortcut_id) # ID로 바로가기 정보 가져오기
                    if shortcut:
                        state = self._determine_web_button_state(shortcut, current_dt) # 상태 결정
                        self._apply_button_style(button, state) # 스타일 적용

    def _refresh_status_columns(self):
        """테이블의 상태 컬럼만 새로고침합니다."""
        current_dt = datetime.datetime.now()
        gs = self.data_manager.global_settings
        status_changes = 0
        
        for r in range(self.process_table.rowCount()):
            # 이름 컬럼에서 프로세스 ID 가져오기
            name_item = self.process_table.item(r, self.COL_NAME)
            if not name_item:
                continue
            process_id = name_item.data(Qt.ItemDataRole.UserRole)
            if not process_id:
                continue
            
            # 프로세스 정보 가져오기
            process = self.data_manager.get_process_by_id(process_id)
            if not process:
                continue
            
            # 새로운 상태 결정
            new_status = self.scheduler.determine_process_visual_status(process, current_dt, gs)
            
            # 상태 컬럼 아이템 가져오기
            status_item = self.process_table.item(r, self.COL_STATUS)
            if not status_item:
                continue
            
            # 상태가 변경된 경우에만 업데이트
            if status_item.text() != new_status:
                old_status = status_item.text()
                status_item.setText(new_status)
                status_changes += 1
                
                # 상태에 따른 배경색 설정
                palette = self.process_table.palette()
                df_bg, df_fg = palette.base(), palette.text()
                
                status_item.setBackground(df_bg)  # 기본 배경색으로 초기화
                status_item.setForeground(df_fg)  # 기본 글자색으로 초기화
                
                if new_status == PROC_STATE_RUNNING:
                    status_item.setBackground(self.COLOR_RUNNING)
                    status_item.setForeground(QColor("black"))
                elif new_status == PROC_STATE_INCOMPLETE:
                    status_item.setBackground(self.COLOR_INCOMPLETE)
                elif new_status == PROC_STATE_COMPLETED:
                    status_item.setBackground(self.COLOR_COMPLETED)
                
                # 상태 변경 로그 출력
                print(f"[{current_dt.strftime('%H:%M:%S')}] 상태 변경: '{process.name}' {old_status} → {new_status}")
        
        # 상태 변경이 있었을 때만 로그 출력
        if status_changes > 0:
            print(f"[{current_dt.strftime('%H:%M:%S')}] 상태 컬럼 새로고침 완료: {status_changes}개 항목 상태 변경됨")

    def _refresh_status_columns_immediate(self):
        """상태 컬럼을 즉시 새로고침합니다 (중요한 시각 변경 시 호출)."""
        self._refresh_status_columns()

    def _load_and_display_web_buttons(self):
        """저장된 웹 바로가기 정보를 불러와 동적 버튼으로 UI에 표시합니다."""
        self._clear_layout(self.dynamic_web_buttons_layout) # 기존 버튼들 모두 제거
        shortcuts = self.data_manager.web_shortcuts # 모든 웹 바로가기 정보 가져오기
        current_dt = datetime.datetime.now()

        for sc_data in shortcuts: # 각 바로가기에 대해 버튼 생성
            button = QPushButton(sc_data.name) # 버튼 텍스트는 바로가기 이름
            # 버튼 크기를 텍스트에 맞게 최적화
            button.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            # 버튼 클릭 시 _handle_web_button_clicked 메소드 호출 (ID와 URL 전달)
            button.clicked.connect(functools.partial(self._handle_web_button_clicked, sc_data.id, sc_data.url))
            button.setProperty("shortcut_id", sc_data.id) # 버튼에 바로가기 ID 저장 (나중에 참조용)
            button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu) # 컨텍스트 메뉴 사용 설정
            # 컨텍스트 메뉴 요청 시 _show_web_button_context_menu 메소드 호출 (버튼 객체 전달)
            button.customContextMenuRequested.connect(functools.partial(self._show_web_button_context_menu, button))

            state = self._determine_web_button_state(sc_data, current_dt) # 버튼 초기 상태 결정
            self._apply_button_style(button, state) # 스타일 적용
            self.dynamic_web_buttons_layout.addWidget(button) # 레이아웃에 버튼 추가
        
        # 웹 버튼 로드 완료 후 창 너비 조절
        self._adjust_window_width_for_web_buttons()

    def _handle_web_button_clicked(self, shortcut_id: str, url: str):
        """웹 바로가기 버튼 클릭 시 호출됩니다. URL을 열고, 필요한 경우 상태를 업데이트합니다."""
        print(f"웹 버튼 클릭 (ID: {shortcut_id}): {url} 열기 시도")
        shortcut = self.data_manager.get_web_shortcut_by_id(shortcut_id) # 바로가기 정보 가져오기
        if not shortcut: # 바로가기 정보 없으면 경고 후 URL 열기 시도
            QMessageBox.warning(self, "오류", "해당 웹 바로 가기 정보를 찾을 수 없습니다.")
            self.open_webpage(url) # URL 열기 시도
            return

        self.open_webpage(url) # URL 열기

        # 초기화 시간이 설정된 바로가기인 경우, 마지막 초기화 타임스탬프 업데이트
        if shortcut.refresh_time_str:
            shortcut.last_reset_timestamp = datetime.datetime.now().timestamp() # 현재 시각으로 업데이트
            if self.data_manager.update_web_shortcut(shortcut): # 데이터 매니저 통해 정보 업데이트
                print(f"웹 바로 가기 '{shortcut.name}' 상태 업데이트 (last_reset_timestamp).")
                self._refresh_web_button_states() # 버튼 상태 즉시 새로고침
            else:
                print(f"웹 바로 가기 '{shortcut.name}' 상태 업데이트 실패.")

    def _open_add_web_shortcut_dialog(self):
        """새 웹 바로가기를 추가하는 대화 상자를 엽니다."""
        dialog = WebShortcutDialog(self) # 웹 바로가기 추가/편집 대화 상자 생성
        if dialog.exec(): # 'OK' 클릭 시
            data = dialog.get_data() # 입력 데이터 가져오기
            if data:
                # 새 웹 바로가기 객체 생성
                new_shortcut = WebShortcut(name=data["name"], url=data["url"],
                                           refresh_time_str=data.get("refresh_time_str")) # refresh_time_str은 선택 사항
                if self.data_manager.add_web_shortcut(new_shortcut): # 데이터 매니저에 추가
                    self._load_and_display_web_buttons() # 버튼 목록 새로고침
                    self._adjust_window_width_for_web_buttons() # 창 너비 조절
                    status_bar = self.statusBar()
                    if status_bar:
                        status_bar.showMessage(f"웹 바로 가기 '{new_shortcut.name}' 추가됨.", 3000)
                else:
                    QMessageBox.warning(self, "추가 실패", "웹 바로 가기 추가에 실패했습니다.")

    def _show_web_button_context_menu(self, button: QPushButton, position):
        """웹 바로가기 버튼의 컨텍스트 메뉴 (편집, 삭제)를 표시합니다."""
        shortcut_id = button.property("shortcut_id") # 버튼에서 바로가기 ID 가져오기
        if not shortcut_id: return

        menu = QMenu(self) # 컨텍스트 메뉴 생성
        edit_action = QAction("편집", self) # 편집 액션
        delete_action = QAction("삭제", self) # 삭제 액션

        # 액션 트리거 시 해당 메소드 호출 (바로가기 ID 전달)
        edit_action.triggered.connect(functools.partial(self._edit_web_shortcut, shortcut_id))
        delete_action.triggered.connect(functools.partial(self._delete_web_shortcut, shortcut_id))

        menu.addActions([edit_action, delete_action]) # 메뉴에 액션 추가
        menu.exec(button.mapToGlobal(position)) # 컨텍스트 메뉴 표시 (버튼 기준 전역 좌표)

    def _edit_web_shortcut(self, shortcut_id: str):
        """선택된 웹 바로가기를 편집하는 대화 상자를 엽니다."""
        shortcut_to_edit = self.data_manager.get_web_shortcut_by_id(shortcut_id) # 편집할 바로가기 정보 가져오기
        if not shortcut_to_edit:
            QMessageBox.warning(self, "오류", "편집할 웹 바로 가기를 찾을 수 없습니다.")
            return

        # 기존 데이터로 채워진 웹 바로가기 편집 대화 상자 생성
        dialog = WebShortcutDialog(self, shortcut_data=shortcut_to_edit.to_dict())
        if dialog.exec(): # 'OK' 클릭 시
            data = dialog.get_data() # 수정된 데이터 가져오기
            if data:
                # 업데이트된 웹 바로가기 객체 생성 (ID와 마지막 초기화 시간은 유지 또는 조건부 업데이트)
                updated_shortcut = WebShortcut(id=shortcut_id, name=data["name"], url=data["url"],
                                               refresh_time_str=data.get("refresh_time_str"),
                                               last_reset_timestamp=shortcut_to_edit.last_reset_timestamp)
                # 초기화 시간이 제거되면 마지막 초기화 타임스탬프도 제거
                if not updated_shortcut.refresh_time_str:
                    updated_shortcut.last_reset_timestamp = None

                if self.data_manager.update_web_shortcut(updated_shortcut): # 데이터 매니저 통해 정보 업데이트
                    self._load_and_display_web_buttons() # 버튼 목록 새로고침
                    self._adjust_window_width_for_web_buttons() # 창 너비 조절
                    status_bar = self.statusBar()
                    if status_bar:
                        status_bar.showMessage(f"웹 바로 가기 '{updated_shortcut.name}' 수정됨.", 3000)
                else:
                    QMessageBox.warning(self, "수정 실패", "웹 바로 가기 수정에 실패했습니다.")

    def _delete_web_shortcut(self, shortcut_id: str):
        """선택된 웹 바로가기를 삭제합니다."""
        shortcut_to_delete = self.data_manager.get_web_shortcut_by_id(shortcut_id) # 삭제할 바로가기 정보 가져오기
        if not shortcut_to_delete:
            QMessageBox.warning(self, "오류", "삭제할 웹 바로 가기를 찾을 수 없습니다.")
            return

        # 삭제 확인 대화 상자 표시
        reply = QMessageBox.question(self, "삭제 확인",
                                     f"웹 바로 가기 '{shortcut_to_delete.name}'을(를) 정말 삭제하시겠습니까?",
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                     QMessageBox.StandardButton.No) # 기본 선택은 'No'
        if reply == QMessageBox.StandardButton.Yes: # 'Yes' 클릭 시
            if self.data_manager.remove_web_shortcut(shortcut_id): # 데이터 매니저 통해 삭제
                self._load_and_display_web_buttons() # 버튼 목록 새로고침
                self._adjust_window_width_for_web_buttons() # 창 너비 조절
                status_bar = self.statusBar()
                if status_bar:
                    status_bar.showMessage(f"웹 바로 가기 '{shortcut_to_delete.name}' 삭제됨.", 3000)
            else:
                QMessageBox.warning(self, "삭제 실패", "웹 바로 가기 삭제에 실패했습니다.")

    def closeEvent(self, event: QEvent):
        """창 닫기 이벤트를 처리합니다. 트레이 관리자가 있으면 트레이로 숨깁니다."""
        if hasattr(self, 'tray_manager') and self.tray_manager:
            self.tray_manager.handle_window_close_event(event) # 트레이 관리자에게 이벤트 처리 위임
        else: # 트레이 관리자 없으면 기본 동작 (숨기기)
            event.ignore()
            self.hide()

    def initiate_quit_sequence(self):
        """애플리케이션 종료 절차를 시작합니다 (타이머 중지, 아이콘 숨기기, 리소스 정리 등)."""
        import homework_helper
        import subprocess

        print("=== 애플리케이션 종료 절차 시작 ===")

        # 1. FastAPI 서버에 Graceful Shutdown 요청
        server_shutdown_success = False
        # multiprocessing.Process는 is_alive()로 프로세스 실행 여부 확인
        if homework_helper.api_server_process and homework_helper.api_server_process.is_alive():
            try:
                print("서버에 graceful shutdown 요청 중...")
                response = requests.post("http://127.0.0.1:8000/shutdown", timeout=3)
                if response.status_code == 200:
                    print("✓ 서버가 종료 신호를 수신했습니다.")

                    # 서버 프로세스가 완전히 종료될 때까지 대기 (타임아웃: 전역 변수 사용)
                    # multiprocessing.Process는 join() 사용 (subprocess.Popen의 wait()와 동일한 의미)
                    homework_helper.api_server_process.join(timeout=API_SERVER_SHUTDOWN_TIMEOUT)

                    # join() 후에도 프로세스가 살아있는지 확인
                    if not homework_helper.api_server_process.is_alive():
                        print("[OK] 서버 프로세스 정상 종료 완료")
                        server_shutdown_success = True

                        # 추가 안전장치: 서버가 리소스를 완전히 해제할 시간 제공
                        import time
                        time.sleep(2)
                        print("[OK] 서버 리소스 해제 대기 완료 (2초)")
                    else:
                        print(f"[경고] 서버 종료 타임아웃 ({API_SERVER_SHUTDOWN_TIMEOUT}초 초과)")
                        print("   서버를 독립 프로세스로 남겨두고 GUI만 종료합니다.")
                        # 강제 종료하지 않음 - 서버가 DB 정리 중일 수 있으므로 안전을 위해 독립 실행 유지
            except requests.exceptions.RequestException as e:
                print(f"⚠ 서버 종료 요청 실패 (서버가 이미 종료되었을 수 있음): {e}")

        # 2. 활성화된 타이머들 중지
        if hasattr(self, 'monitor_timer') and self.monitor_timer.isActive():
            self.monitor_timer.stop()
        if hasattr(self, 'scheduler_timer') and self.scheduler_timer.isActive():
            self.scheduler_timer.stop()
        if hasattr(self, 'web_button_refresh_timer') and self.web_button_refresh_timer.isActive():
            self.web_button_refresh_timer.stop()
            print("웹 버튼 상태 새로고침 타이머 중지됨.")
        if hasattr(self, 'status_column_refresh_timer') and self.status_column_refresh_timer.isActive():
            self.status_column_refresh_timer.stop()
            print("상태 컬럼 자동 업데이트 타이머 중지됨.")

        # 3. 트레이 아이콘 숨기기
        if hasattr(self, 'tray_manager') and self.tray_manager:
            self.tray_manager.hide_tray_icon()

        # 4. 인스턴스 매니저 리소스 정리 (단일 인스턴스 실행 관련)
        if self._instance_manager and hasattr(self._instance_manager, 'cleanup'):
            self._instance_manager.cleanup()

        # 5. QApplication 종료
        app_instance = QApplication.instance()
        if app_instance:
            app_instance.quit()

        print("=== GUI 종료 완료 ===")

    def _adjust_window_size_to_content(self):
        """테이블 내용에 맞춰 메인 윈도우의 높이를 자동으로 조절합니다. 너비는 고정합니다."""
        # 테이블 행 높이를 내용에 맞게 조절
        if self.process_table.rowCount() > 0:
            self.process_table.resizeRowsToContents()

        # 테이블 내용 높이 계산
        table_content_height = 0

        # 1. 수평 헤더 높이 추가
        header = self.process_table.horizontalHeader()
        if header and not header.isHidden():
            table_content_height += header.height()

        # 2. 모든 행의 높이 합산
        if self.process_table.rowCount() > 0:
            for i in range(self.process_table.rowCount()):
                table_content_height += self.process_table.rowHeight(i)
            table_content_height += self.process_table.frameWidth() * 2  # 테이블 테두리 두께 고려
        else:
            # 행이 없을 경우, 기본 높이 추정치 사용
            default_row_height_approx = self.fontMetrics().height() + 12
            table_content_height += default_row_height_approx
            table_content_height += self.process_table.frameWidth() * 2

        # 테이블의 고정 높이 설정
        self.process_table.setFixedHeight(table_content_height)
        
        # 웹 버튼이 있을 때만 창 너비 조절
        web_button_count = 0
        if hasattr(self, 'dynamic_web_buttons_layout') and self.dynamic_web_buttons_layout:
            for i in range(self.dynamic_web_buttons_layout.count()):
                item = self.dynamic_web_buttons_layout.itemAt(i)
                if item and item.widget():
                    widget = item.widget()
                    if widget and widget.isVisible():
                        web_button_count += 1
        
        # 창 너비 결정 (고정 너비 + 웹 버튼이 있을 때만 추가)
        if web_button_count > 0:
            # 웹 버튼이 있을 때: 기본 너비 + 웹 버튼 영역
            target_width = 400  # 웹 버튼이 있을 때의 고정 너비
        else:
            # 웹 버튼이 없을 때: 기본 너비
            target_width = 300  # 웹 버튼이 없을 때의 고정 너비
        
        # 창 높이 계산
        # - 상단 버튼 영역 높이: 약 35px
        # - 테이블 높이 (계산된 값)
        # - 레이아웃 여백: 약 15px
        # - 메뉴바, 상태바 높이
        menu_bar = self.menuBar()
        status_bar = self.statusBar()
        menu_height = menu_bar.height() if menu_bar else 0
        status_height = status_bar.height() if status_bar else 0
        
        top_button_height = 35
        layout_margin = 15
        
        total_height = menu_height + top_button_height + table_content_height + status_height + layout_margin
        
        # 창 크기 설정 (너비는 고정, 높이만 조절)
        self.resize(target_width, total_height)
        self.show()
        
        # print(f"윈도우 크기 조절됨. 새 크기: {self.width()}x{self.height()}, 테이블 높이: {table_content_height}, 웹 버튼 개수: {web_button_count}")

    def _adjust_window_height_to_table(self):
        """기존 메서드명 호환성을 위한 별칭"""
        self._adjust_window_size_to_content()

    def _adjust_window_width_for_web_buttons(self):
        """웹 바로가기 버튼 추가/삭제 시에만 창 너비를 조절합니다."""
        # 웹 버튼 개수 확인
        web_button_count = 0
        if hasattr(self, 'dynamic_web_buttons_layout') and self.dynamic_web_buttons_layout:
            for i in range(self.dynamic_web_buttons_layout.count()):
                item = self.dynamic_web_buttons_layout.itemAt(i)
                if item and item.widget():
                    widget = item.widget()
                    if widget and widget.isVisible():
                        web_button_count += 1
        
        # 창 너비 결정 (최초 창 너비보다 작은 값으로는 축소되지 않음)
        if web_button_count > 0:
            target_width = 400  # 웹 버튼이 있을 때의 고정 너비
        else:
            target_width = 300  # 웹 버튼이 없을 때의 고정 너비 (최초 창 너비)
        
        # 현재 너비가 목표 너비와 다르면 조절
        current_width = self.width()
        if current_width != target_width:
            # 창 최소 너비 제거 후 너비 설정
            current_min_width = self.minimumWidth()
            self.setMinimumWidth(0)  # 최소 너비 제거
            self.resize(target_width, self.height())
            self.setMinimumWidth(current_min_width)  # 원래 최소 너비 복원
            # print(f"웹 버튼에 따른 창 너비 조절: {current_width} -> {target_width}")

    def _adjust_window_height_for_table_rows(self):
        """테이블 행 추가/삭제 시에만 창 높이를 조절합니다."""
        # 현재 행 수 확인
        current_row_count = self.process_table.rowCount()
        
        print(f"\n=== 창 높이 조절 디버깅 ===")
        print(f"현재 행 수: {current_row_count}")
        
        # 행이 없으면 기본 높이 사용
        if current_row_count == 0:
            # 기본 높이 계산 (헤더 + 1행 + 여백)
            header = self.process_table.horizontalHeader()
            header_height = header.height() if header and not header.isHidden() else 0
            default_row_height = self.fontMetrics().height() + 12
            table_height = header_height + default_row_height + self.process_table.frameWidth() * 2
            print(f"행이 없음 - 헤더 높이: {header_height}, 기본 행 높이: {default_row_height}, 테이블 높이: {table_height}")
        else:
            # 실제 행 높이 계산
            table_height = 0
            header = self.process_table.horizontalHeader()
            if header and not header.isHidden():
                table_height += header.height()
                print(f"헤더 높이: {header.height()}")
            
            print(f"각 행 높이: ", end="")
            for i in range(current_row_count):
                row_height = self.process_table.rowHeight(i)
                table_height += row_height
                print(f"{row_height}px ", end="")
            print()
            
            frame_width = self.process_table.frameWidth() * 2
            table_height += frame_width
            print(f"테두리 두께: {frame_width}px")
            print(f"총 테이블 높이: {table_height}px")
        
        # 테이블 높이 설정
        self.process_table.setFixedHeight(table_height)
        print(f"테이블 고정 높이 설정: {table_height}px")
        
        # 창 높이 계산
        menu_bar = self.menuBar()
        status_bar = self.statusBar()
        menu_height = menu_bar.height() if menu_bar else 0
        status_height = status_bar.height() if status_bar else 0
        
        top_button_height = 35
        layout_margin = 15
        
        total_height = menu_height + top_button_height + table_height + status_height + layout_margin
        
        print(f"창 높이 구성: 메뉴({menu_height}) + 상단버튼({top_button_height}) + 테이블({table_height}) + 상태바({status_height}) + 여백({layout_margin}) = {total_height}px")
        
        # 레이아웃 구조 분석
        print(f"\n=== 레이아웃 구조 분석 ===")
        central_widget = self.centralWidget()
        print(f"중앙 위젯: {central_widget}")
        if central_widget:
            print(f"중앙 위젯 크기 정책: {central_widget.sizePolicy()}")
            print(f"중앙 위젯 최소 크기: {central_widget.minimumSize()}")
            print(f"중앙 위젯 최대 크기: {central_widget.maximumSize()}")
            
            main_layout = central_widget.layout()
            print(f"메인 레이아웃: {main_layout}")
            if main_layout:
                print(f"메인 레이아웃 여백: {main_layout.contentsMargins()}")
                print(f"메인 레이아웃 간격: {main_layout.spacing()}")
        
        print(f"테이블 크기 정책: {self.process_table.sizePolicy()}")
        print(f"테이블 최소 크기: {self.process_table.minimumSize()}")
        print(f"테이블 최대 크기: {self.process_table.maximumSize()}")
        print(f"테이블 sizeHint: {self.process_table.sizeHint()}")
        print(f"테이블 minimumSizeHint: {self.process_table.minimumSizeHint()}")
        
        print(f"창 최소 크기: {self.minimumSize()}")
        print(f"창 최대 크기: {self.maximumSize()}")
        print(f"창 sizeHint: {self.sizeHint()}")
        print("=== 레이아웃 분석 완료 ===\n")
        
        # 현재 창 크기와 비교
        current_height = self.height()
        print(f"현재 창 높이: {current_height}px -> 목표 높이: {total_height}px")
        
        # 창 최소 높이 제거 후 높이 설정
        current_min_height = self.minimumHeight()
        self.setMinimumHeight(0)  # 최소 높이 제거
        self.resize(self.width(), total_height)
        self.setMinimumHeight(current_min_height)  # 원래 최소 높이 복원
        
        # 설정 후 확인
        new_height = self.height()
        print(f"설정 후 창 높이: {new_height}px")
        print(f"테이블 실제 높이: {self.process_table.height()}px")
        print("=== 디버깅 완료 ===\n")

    def _calculate_progress_percentage(self, process: ManagedProcess, current_dt: datetime.datetime) -> tuple[float, str]:
        """마지막 실행 시각을 기준으로 다음 접속까지의 진행률을 계산합니다."""
        if not process.last_played_timestamp or not process.user_cycle_hours:
            return 0.0, "기록 없음"
        
        try:
            last_played_dt = datetime.datetime.fromtimestamp(process.last_played_timestamp)
            cycle_hours = process.user_cycle_hours
            
            # 경과 시간 계산 (시간 단위)
            elapsed_hours = (current_dt - last_played_dt).total_seconds() / 3600
            
            # 진행률 계산 (0.0 ~ 1.0)
            progress = min(elapsed_hours / cycle_hours, 1.0)
            
            # 백분율로 변환
            percentage = progress * 100
            
            # 남은 시간 계산
            remaining_hours = max(cycle_hours - elapsed_hours, 0)
            
            if remaining_hours >= 24:
                remaining_days = int(remaining_hours // 24)
                remaining_hours_remainder = remaining_hours % 24
                if remaining_hours_remainder > 0:
                    time_str = f"{remaining_days}일 {int(remaining_hours_remainder)}시간"
                else:
                    time_str = f"{remaining_days}일"
            elif remaining_hours >= 1:
                time_str = f"{int(remaining_hours)}시간"
            else:
                remaining_minutes = int(remaining_hours * 60)
                time_str = f"{remaining_minutes}분"
            
            return percentage, time_str
            
        except Exception as e:
            print(f"진행률 계산 중 오류: {e}")
            return 0.0, "계산 오류"

    def _create_progress_bar_widget(self, percentage: float, time_str: str) -> QWidget:
        """진행률을 표시하는 QProgressBar 위젯을 생성합니다."""
        if percentage == 0.0:
            # 기록이 없는 경우 텍스트 라벨 반환
            label = QLabel(time_str)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            return label
        
        # QProgressBar 생성
        progress_bar = QProgressBar()
        progress_bar.setValue(int(percentage))
        progress_bar.setMaximum(100)
        progress_bar.setMinimum(0)
        
        # 높이 설정 (행 높이에 맞게 자동 조절)
        progress_bar.setMinimumHeight(20)  # 최소 높이만 설정
        
        # 텍스트 표시 설정
        progress_bar.setTextVisible(True)
        progress_bar.setFormat(f"{percentage:.1f}%")
        
        # 진행률에 따른 색상 설정 (다크 모드 배경)
        if percentage >= 100:
            # 100% 이상: 빨간색 (접속 필요)
            progress_bar.setStyleSheet("""
                QProgressBar {
                    border: 1px solid #404040;
                    border-radius: 2px;
                    text-align: center;
                    background-color: #2d2d2d;
                    color: white;
                    font-weight: bold;
                }
                QProgressBar::chunk {
                    background-color: #ff4444;
                    border-radius: 1px;
                }
            """)
        elif percentage >= 80:
            # 80% 이상: 주황색 (곧 접속 필요)
            progress_bar.setStyleSheet("""
                QProgressBar {
                    border: 1px solid #404040;
                    border-radius: 2px;
                    text-align: center;
                    background-color: #2d2d2d;
                    color: white;
                    font-weight: bold;
                }
                QProgressBar::chunk {
                    background-color: #ff8800;
                    border-radius: 1px;
                }
            """)
        elif percentage >= 50:
            # 50% 이상: 노란색 (중간 진행)
            progress_bar.setStyleSheet("""
                QProgressBar {
                    border: 1px solid #404040;
                    border-radius: 2px;
                    text-align: center;
                    background-color: #2d2d2d;
                    color: white;
                    font-weight: bold;
                }
                QProgressBar::chunk {
                    background-color: #ffcc00;
                    border-radius: 1px;
                }
            """)
        else:
            # 50% 미만: 초록색 (여유 있음)
            progress_bar.setStyleSheet("""
                QProgressBar {
                    border: 1px solid #404040;
                    border-radius: 2px;
                    text-align: center;
                    background-color: #2d2d2d;
                    color: white;
                    font-weight: bold;
                }
                QProgressBar::chunk {
                    background-color: #44cc44;
                    border-radius: 1px;
                }
            """)
        
        return progress_bar

    def _refresh_progress_bars(self):
        """프로그레스 바들을 실시간으로 갱신합니다."""
        now_dt = datetime.datetime.now()
        processes = self.data_manager.managed_processes
        
        # 테이블의 각 행을 순회하면서 해당 행의 프로세스 ID를 찾아서 갱신
        for row in range(self.process_table.rowCount()):
            # 해당 행의 이름 컬럼에서 프로세스 ID 가져오기
            name_item = self.process_table.item(row, self.COL_NAME)
            if not name_item:
                continue
                
            process_id = name_item.data(Qt.ItemDataRole.UserRole)
            if not process_id:
                continue
                
            # 프로세스 ID로 해당 프로세스 찾기
            process = None
            for p in processes:
                if p.id == process_id:
                    process = p
                    break
                    
            if not process:
                continue
                
            # 현재 셀의 위젯 가져오기
            current_widget = self.process_table.cellWidget(row, self.COL_LAST_PLAYED)
            if not current_widget:
                continue
                
            # 새로운 진행률 계산
            percentage, time_str = self._calculate_progress_percentage(process, now_dt)
            
            # QProgressBar인 경우 값 업데이트
            if isinstance(current_widget, QProgressBar):
                current_widget.setValue(int(percentage))
                current_widget.setFormat(f"{percentage:.1f}%")
                
                # 진행률에 따른 색상 업데이트
                if percentage >= 100:
                    current_widget.setStyleSheet("""
                        QProgressBar {
                            border: 1px solid #404040;
                            border-radius: 2px;
                            text-align: center;
                            background-color: #2d2d2d;
                            color: white;
                            font-weight: bold;
                        }
                        QProgressBar::chunk {
                            background-color: #ff4444;
                            border-radius: 1px;
                        }
                    """)
                elif percentage >= 80:
                    current_widget.setStyleSheet("""
                        QProgressBar {
                            border: 1px solid #404040;
                            border-radius: 2px;
                            text-align: center;
                            background-color: #2d2d2d;
                            color: white;
                            font-weight: bold;
                        }
                        QProgressBar::chunk {
                            background-color: #ff8800;
                            border-radius: 1px;
                        }
                    """)
                elif percentage >= 50:
                    current_widget.setStyleSheet("""
                        QProgressBar {
                            border: 1px solid #404040;
                            border-radius: 2px;
                            text-align: center;
                            background-color: #2d2d2d;
                            color: white;
                            font-weight: bold;
                        }
                        QProgressBar::chunk {
                            background-color: #ffcc00;
                            border-radius: 1px;
                        }
                    """)
                else:
                    current_widget.setStyleSheet("""
                        QProgressBar {
                            border: 1px solid #404040;
                            border-radius: 2px;
                            text-align: center;
                            background-color: #2d2d2d;
                            color: white;
                            font-weight: bold;
                        }
                        QProgressBar::chunk {
                            background-color: #44cc44;
                            border-radius: 1px;
                        }
                    """)
            # QLabel인 경우 (기록 없음) 텍스트 업데이트
            elif isinstance(current_widget, QLabel):
                current_widget.setText(time_str)

    def _apply_window_resize_lock(self):
        """창 크기 조절 잠금 설정을 적용합니다."""
        lock_enabled = self.data_manager.global_settings.lock_window_resize
        
        if lock_enabled:
            # 창 크기 조절을 고정 (사용자가 드래그로 크기 조절 불가)
            # 자동 크기 조절은 허용하기 위해 최소/최대 크기를 현재 크기로 설정
            current_size = self.size()
            self.setMinimumSize(current_size)
            self.setMaximumSize(current_size)
            print("창 크기 조절 잠금 활성화됨")
        else:
            # 창 크기 조절 허용 (기본 동작)
            self.setMinimumSize(300, 0)  # 원래 최소 너비만 유지
            self.setMaximumSize(16777215, 16777215)  # 최대 크기 해제
            print("창 크기 조절 잠금 비활성화됨")

    def _update_window_resize_lock(self):
        """전역 설정 변경 시 창 크기 조절 잠금을 업데이트합니다."""
        self._apply_window_resize_lock()

    def _on_launcher_restart_request(self, launcher_name: str) -> bool:
        """
        게임 런처 재시작 요청 시 사용자 확인 대화상자를 표시합니다.

        Args:
            launcher_name: 재시작할 런처 프로세스명 (예: "Steam.exe")

        Returns:
            True: 사용자가 재시작에 동의
            False: 사용자가 재시작 거부
        """
        from PyQt6.QtWidgets import QMessageBox

        # 런처명을 사용자 친화적으로 변환
        friendly_name = launcher_name.replace('.exe', '').replace('Launcher', ' Launcher')

        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Warning)
        msg_box.setWindowTitle("게임 런처 재시작 필요")
        msg_box.setText(f"{friendly_name}가 일반 권한으로 실행 중입니다.")
        msg_box.setInformativeText(
            f"게임을 관리자 권한으로 실행하려면 {friendly_name}를 재시작해야 합니다.\n\n"
            f"재시작하시겠습니까?\n\n"
            f"참고: 현재 실행 중인 게임이 있다면 저장 후 진행하세요."
        )
        msg_box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        msg_box.setDefaultButton(QMessageBox.StandardButton.No)

        result = msg_box.exec()
        return result == QMessageBox.StandardButton.Yes

