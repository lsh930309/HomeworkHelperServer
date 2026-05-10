# main_window.py
"""메인 윈도우 및 아이콘 다운로더 클래스"""

import os
import sys
import time
import datetime
import functools
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# PyQt6 임포트
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QTableWidget, QTableWidgetItem, QVBoxLayout, QHBoxLayout, QWidget,
    QHeaderView, QPushButton, QSizePolicy, QFileIconProvider, QAbstractItemView,
    QMessageBox, QMenu, QStyle, QStatusBar, QMenuBar, QAbstractScrollArea, QCheckBox,
    QLabel, QProgressBar, QSlider, QToolButton, QInputDialog,
)
from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QUrl, QEvent, QThread, QSettings, QPoint, QRect, QSize
from PyQt6.QtGui import QAction, QIcon, QColor, QDesktopServices, QFontDatabase, QFont, QPixmap, QPalette, QScreen

# --- 로컬 모듈 임포트 ---
from src.gui.dialogs import ProcessDialog, GlobalSettingsDialog, NumericTableWidgetItem, WebShortcutDialog, HoYoLabSettingsDialog
from src.gui.beholder_dialog import BeholderIncidentDialog
from src.gui.tray_manager import TrayManager
from src.gui.gui_notification_handler import GuiNotificationHandler
from src.core.instance_manager import run_with_single_instance_check, SingleInstanceApplication
from src.utils.common import get_bundle_resource_path
import requests

# --- 기타 로컬 유틸리티/데이터 모듈 임포트 ---
from src.api.client import ApiClient
from src.data.data_models import ManagedProcess, GlobalSettings, WebShortcut
from src.utils.process import get_qicon_for_file
from src.utils.window_focus import focus_process_window
from src.utils.windows import (
    apply_windows_title_bar_color,
    set_startup_shortcut,
    get_startup_shortcut_status,
)
from src.core.launcher import Launcher
from src.core.notifier import Notifier
from src.core.hoyolab_reconcile import HoYoStaminaReconcileCoordinator
from src.core.scheduler import Scheduler, PROC_STATE_INCOMPLETE, PROC_STATE_COMPLETED, PROC_STATE_RUNNING
from src.utils.admin import is_admin, run_as_admin, restart_as_normal
from src.utils.game_preset_manager import GamePresetManager
from src.utils import audio_control
from src.gui.volume_panel import VolumePopoverPanel
from src.gui.sidebar.sidebar_controller import SidebarController


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
            # 오류 발생 시 로그 출력 (시그널은 발생하지 않음)
            logger.error(f"아이콘 다운로드 실패 ({self.url}): {e}")

class MainWindow(QMainWindow):
    INSTANCE = None # 다른 모듈에서 메인 윈도우 인스턴스에 접근하기 위함
    request_table_refresh_signal = pyqtSignal() # 테이블 새로고침 요청 시그널
    _recording_state_sig = pyqtSignal(str)        # OBS 상태 변경 (백그라운드→메인 스레드 릴레이)
    _gamepad_countdown_sig = pyqtSignal()         # 게임패드 롱프레스 → 메인 스레드 릴레이

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
    TOTAL_COLUMNS = 5 # 전체 컬럼 개수
    _PROGRESS_BAR_SCALE = 10
    _PROGRESS_BAR_MAX = 100 * _PROGRESS_BAR_SCALE
    _UI_REFRESH_INTERVAL_MS = 1000
    _WEB_BUTTON_REFRESH_INTERVAL_TICKS = 60
    _FOCUS_ATTEMPT_INTERVAL_MS = 750
    _FOCUS_ATTEMPT_COUNT = 12
    _MIN_WINDOW_WIDTH = 320
    _MIN_WINDOW_HEIGHT = 120
    _SCREEN_SIZE_RATIO = 0.92
    _TABLE_ROW_HEIGHT = 40
    _TABLE_ICON_LOGICAL_SIZE = 32
    _TABLE_ICON_COLUMN_PADDING = 10

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

        from src.core.process_monitor import ProcessMonitor # 순환 참조 방지를 위한 동적 임포트
        self.process_monitor = ProcessMonitor(self.data_manager)
        self._hoyolab_reconcile = HoYoStaminaReconcileCoordinator(
            self.data_manager,
            self.process_monitor,
            self,
        )

        self.gui_notification_handler = GuiNotificationHandler(self) # GUI 알림 처리기 생성
        self.system_notifier = Notifier( # 시스템 알림 객체 생성 (콜백을 생성자에 전달하여 시그널 연결 보장)
            QApplication.applicationName(),
            main_window_activated_callback=self.gui_notification_handler.process_system_notification_activation,
        )

        self.scheduler = Scheduler(self.data_manager, self.system_notifier, self.process_monitor) # 스케줄러 객체 생성

        # 메인 GUI는 별도 heartbeat에서 표시 갱신을 처리합니다.
        self.scheduler.status_change_callback = None

        # 게임 프리셋 매니저 초기화
        self.preset_manager = GamePresetManager()

        self.setWindowTitle(QApplication.applicationName() or "숙제 관리자") # 창 제목 설정

        # 창 크기: 테이블/버튼 실제 sizeHint를 기반으로 동적으로 최적화합니다.
        self.setMinimumSize(self._MIN_WINDOW_WIDTH, self._MIN_WINDOW_HEIGHT)
        self.resize(470, 300) # 최초 표시 전 임시 크기

        # QSettings 초기화 (창 위치/크기 저장용)
        self._settings = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope,
                                    "HomeworkHelper", "display_settings")
        self._mute_retry_tokens: dict[str, int] = {}
        self._beholder_seen_incidents: set[int] = set()
        self._focus_attempt_tokens: dict[str, int] = {}

        # 저장된 창 위치 복원
        self._restore_window_geometry()
        self._recover_gamebar_setting_if_needed()

        self._set_window_icon() # 창 아이콘 설정
        self.tray_manager = TrayManager(self) # 트레이 아이콘 관리자 생성
        self._create_menu_bar() # 메뉴 바 생성
        # 테마 복원 시 사용할 원본 스타일명 저장 (setStyle("") 은 복원 보장 불가)
        _app = QApplication.instance()
        self._original_style_name = _app.style().objectName() if _app else ""
        # 저장된 테마 적용
        self._apply_theme(getattr(self.data_manager.global_settings, 'theme', 'system'))
        # 항상 위 설정 초기 적용 (앱 재시작 후에도 유지)
        self._load_always_on_top_setting()

        self._is_game_mode_active = False # 게임 모드 활성화 여부 추적

        # 볼륨 패널 상태
        self._volume_applied_pids: dict[str, int] = {}  # process_id -> 적용 완료 PID (PID 변경 재실행 감지)
        self._volume_panel: VolumePopoverPanel = VolumePopoverPanel(
            self.data_manager, on_hide=self._on_volume_panel_hidden
        )

        # 사이드바 컨트롤러 초기화
        self._sidebar_controller = SidebarController(self.data_manager, self)

        # 스크린샷 매니저
        from src.screenshot import ScreenshotManager
        gs = getattr(self.data_manager, 'global_settings', None)
        self._screenshot_manager = ScreenshotManager(
            get_target_hwnd=self._get_screenshot_target_hwnd,
            long_press_threshold_ms=getattr(gs, 'recording_hold_threshold_ms', 800),
            trigger_vk=getattr(gs, 'screenshot_trigger_vk', 0xB2),
        )
        self._screenshot_manager.set_on_captured(self._on_screenshot_captured)
        self._screenshot_manager.set_game_name_provider(self._get_screenshot_game_name)
        self._apply_screenshot_settings(sync_runtime=False)

        # 녹화 매니저
        from src.recording import RecordingManager
        self._recording_manager = RecordingManager()
        self._recording_manager.set_on_state_changed(self._on_recording_state_changed)
        self._screenshot_manager.set_on_long_press(self._on_gamepad_long_press)
        self._recording_state_sig.connect(self._dispatch_recording_state_to_sidebar)
        self._gamepad_countdown_sig.connect(self._show_countdown_then_record)
        self._sidebar_controller.set_recording_callbacks(
            on_stop=self._recording_manager.stop_recording,
            on_reconnect=self._recording_manager.reconnect,
            on_start=self._show_countdown_then_record,
            get_last_error=self._recording_manager.get_last_error,
            get_elapsed_sec=self._recording_manager.get_elapsed_sec,
            get_output_dir=self._get_recording_output_dir,
        )
        self._apply_recording_settings()

        # 앱 시작 즉시 게임패드 훅 활성화 (게임 실행 전에도 전역 동작)
        self._start_screenshot_manager()

        # 절전 복귀 시 창 상태 복원을 위한 geometry 저장 변수
        self._saved_geometry = None
        self._saved_size = None

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

        # 대시보드 버튼 추가
        self.dashboard_button = QPushButton()
        self.dashboard_button.setToolTip("통계 대시보드 열기")
        self.dashboard_button.setText("📊")  # 차트 이모지
        self.dashboard_button.setFixedSize(icon_button_size, icon_button_size)
        self.dashboard_button.clicked.connect(lambda: self.open_webpage("http://127.0.0.1:8000/dashboard"))
        self.top_button_area_layout.addWidget(self.dashboard_button)

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

        # 테이블 행 높이 및 아이콘 크기 설정
        vh = self.process_table.verticalHeader()
        if vh:
            vh.setDefaultSectionSize(self._TABLE_ROW_HEIGHT)
            vh.setMinimumSectionSize(self._TABLE_ROW_HEIGHT)

        # 아이콘 크기: 32px 캐시 변형을 직접 활용하고 40px 행 안에 균형 있게 배치합니다.
        # DPI 배율은 get_qicon_for_file 내부에서 적용합니다.
        self._table_icon_logical_size = self._TABLE_ICON_LOGICAL_SIZE
        self.process_table.setIconSize(QSize(self._table_icon_logical_size, self._table_icon_logical_size))

        main_layout.addWidget(self.process_table) # 메인 레이아웃에 테이블 추가

        # 초기 데이터 로드 및 UI 업데이트
        self.populate_process_list() # 프로세스 목록 채우기
        self._load_and_display_web_buttons() # 웹 바로가기 버튼 로드 및 표시
        self._adjust_window_height_for_table_rows() # 테이블 내용에 맞게 창 높이 조절

        # 시그널 및 타이머 설정
        self.request_table_refresh_signal.connect(self.populate_process_list_slot) # 테이블 새로고침 시그널 연결
        self._last_timer_tick = time.time()  # 절전 복귀 감지용 마지막 타이머 틱 시간
        self._ui_refresh_tick_count = 0
        self.monitor_timer = QTimer(self)
        self.monitor_timer.timeout.connect(self._on_monitor_timer_tick)
        self.monitor_timer.start(1000) # 프로세스 모니터 타이머 (1초)
        self.scheduler_timer = QTimer(self)
        self.scheduler_timer.timeout.connect(self.run_scheduler_check)
        self.scheduler_timer.start(1000) # 스케줄러 타이머 (1초)

        # 메인 GUI 표시 갱신 타이머
        self.ui_refresh_timer = QTimer(self)
        self.ui_refresh_timer.timeout.connect(self._on_ui_refresh_tick)
        self.ui_refresh_timer.start(self._UI_REFRESH_INTERVAL_MS)

        self.beholder_timer = QTimer(self)
        self.beholder_timer.timeout.connect(self._poll_beholder_incidents)
        self.beholder_timer.start(1500)
        self.runtime_heartbeat_timer = QTimer(self)
        self.runtime_heartbeat_timer.timeout.connect(self._send_runtime_heartbeat)
        self.runtime_heartbeat_timer.start(30000)
        self._send_runtime_heartbeat()
        QTimer.singleShot(500, self._poll_beholder_incidents)
        QTimer.singleShot(1200, self._reconcile_open_sessions_after_startup)
        QTimer.singleShot(1500, self._hoyolab_reconcile.schedule_startup_refreshes)

        # Qt6 자동 High DPI 스케일링에 의존 (커스텀 DPI 핸들러 제거됨)

        # statusBar()가 None이 아닌지 확인 후 메시지 설정
        status_bar = self.statusBar()
        if status_bar:
            status_bar.showMessage("준비 완료.", 5000) # 상태 표시줄 메시지

        self.apply_startup_setting() # 시작 프로그램 설정 적용


    def _poll_beholder_incidents(self):
        """Show Beholder incidents promptly in the PyQt main GUI."""
        incident = self.data_manager.pop_latest_beholder_incident()
        incidents = [incident] if incident else self.data_manager.get_active_beholder_incidents()
        for item in incidents:
            if not item:
                continue
            incident_id = item.get("id")
            if incident_id in self._beholder_seen_incidents:
                continue
            self.showNormal()
            self.raise_()
            self.activateWindow()
            dialog = BeholderIncidentDialog(item, self)
            if not dialog.exec() or not dialog.action:
                break
            if dialog.action == "restore_backup":
                if self._handle_beholder_restore_request() and incident_id is not None:
                    self._beholder_seen_incidents.add(incident_id)
            elif incident_id is not None:
                result = self.data_manager.resolve_beholder_incident(incident_id, dialog.action)
                if result:
                    self._beholder_seen_incidents.add(incident_id)
                if result and hasattr(self, "process_monitor"):
                    self.process_monitor.apply_beholder_resolution(result)
                if dialog.action == "allow_once" and result and result.get("override_token"):
                    QMessageBox.information(
                        self,
                        "Beholder 허용 토큰 발급",
                        "이번 요청을 1회 허용하는 토큰을 발급했습니다. 동일 작업을 다시 시도하면 한 번만 허용됩니다.",
                    )
            break

    def _send_runtime_heartbeat(self):
        if hasattr(self.data_manager, "send_runtime_heartbeat"):
            self.data_manager.send_runtime_heartbeat(runtime_kind="pyqt")

    def _reconcile_open_sessions_after_startup(self):
        if not hasattr(self.data_manager, "reconcile_open_sessions"):
            return
        running_ids = list(self.process_monitor.detect_running_process_ids())
        incidents = self.data_manager.reconcile_open_sessions(running_ids)
        if incidents:
            self._poll_beholder_incidents()

    def _handle_beholder_restore_request(self) -> bool:
        backups = self.data_manager.get_beholder_backups()
        if not backups:
            QMessageBox.warning(self, "Beholder 백업 복구", "사용 가능한 DB 백업을 찾지 못했습니다.")
            return False
        labels = [
            f"backup.{item.get('slot')} · {datetime.datetime.fromtimestamp(item.get('modified_at', 0)).strftime('%Y-%m-%d %H:%M:%S')} · {item.get('size', 0)} bytes"
            for item in backups
        ]
        choice, ok = QInputDialog.getItem(
            self,
            "Beholder 백업 복구",
            "복구할 백업을 선택하세요. 현재 DB는 복구 직전 별도 snapshot으로 보존됩니다.",
            labels,
            0,
            False,
        )
        if not ok or not choice:
            return False
        slot = backups[labels.index(choice)].get("slot")
        confirm = QMessageBox.question(
            self,
            "백업 복구 확인",
            f"backup.{slot}로 DB를 교체합니다. 계속할까요?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return False
        result = self.data_manager.restore_beholder_backup(int(slot))
        if result and result.get("ok"):
            QMessageBox.information(self, "Beholder 백업 복구", "복구가 완료되었습니다. 앱을 재시작해 주세요.")
            return True
        else:
            QMessageBox.warning(self, "Beholder 백업 복구", "복구에 실패했습니다.")
            return False

    def set_github_button_icon(self, icon: QIcon):
        """IconDownloader로부터 받은 아이콘을 GitHub 버튼에 설정합니다."""
        if not icon.isNull():
            self.github_button.setIcon(icon)
            self.github_button.setText("") # 아이콘이 설정되면 텍스트는 지웁니다.

    def changeEvent(self, event: QEvent):
        """창 상태 변경 이벤트를 처리합니다 (최소화 시 트레이로 보내기 + 절전 복귀 대응)."""
        if event.type() == QEvent.Type.WindowStateChange:
            if self.windowState() & Qt.WindowState.WindowMinimized: # 창이 최소화 상태로 변경될 때
                if hasattr(self, 'tray_manager') and self.tray_manager.is_tray_icon_visible(): # 트레이 아이콘이 보이는 경우
                    self.tray_manager.handle_minimize_event() # 트레이 관리자에게 최소화 처리 위임

        # 창 활성화 시 geometry 복원 및 타이머 재시작 (절전 복귀 대응)
        elif event.type() == QEvent.Type.ActivationChange:
            if self.isActiveWindow():
                # 타이머 상태 확인 및 재시작 (절전 복귀 대응)
                self._ensure_timers_running()

                if self._saved_size:
                    # 저장된 크기와 현재 크기 비교
                    current_size = self.size()
                    if current_size != self._saved_size:
                        QTimer.singleShot(100, self._restore_window_state)

        super().changeEvent(event)

    def showEvent(self, event):
        """창이 표시될 때 호출됩니다."""
        super().showEvent(event)
        # Qt6 자동 High DPI 스케일링에 의존하므로 수동 레이아웃 새로고침 불필요
        QTimer.singleShot(0, self._sync_windows_title_bar_color)

    def _on_monitor_timer_tick(self):
        """프로세스 모니터 타이머 틱 처리 (절전 복귀 감지 포함)"""
        start_time = time.time()
        current_time = time.time()
        elapsed = current_time - self._last_timer_tick

        # 10초 이상 경과했으면 절전 복귀로 판단 (정상: 1초 간격, 이전 5초 → 10초로 증가하여 오탐 방지)
        if elapsed > 10:
            logger.warning(f"절전 복귀 감지: 타이머 간격 {elapsed:.1f}초 (정상: 1초)")
            self._on_sleep_wake()

        self._last_timer_tick = current_time
        self.run_process_monitor_check()

        # 타이머 실행 시간 로깅 (100ms 이상 걸리면 경고)
        execution_time = (time.time() - start_time) * 1000
        if execution_time > 100:
            logger.warning(f"monitor_timer 실행 시간 초과: {execution_time:.1f}ms")

    def _on_sleep_wake(self):
        """절전 복귀 시 호출되는 메서드

        절전모드 복귀 후 UI 갱신이 멈추는 문제 해결:
        - 타이머는 작동하지만 Qt 렌더링이 트리거되지 않는 문제 대응
        - 테이블 전체를 다시 채워서 모든 셀이 강제로 다시 그려지도록 함
        """
        logger.info("절전 복귀 감지 - UI 전체 갱신 시작")

        # 타이머 상태 확인 및 재시작
        self._ensure_timers_running()

        # 테이블 전체 다시 채우기 (모든 위젯 강제 재생성)
        # 이렇게 하면 Progress Bar, 상태 컬럼 등 모든 셀이 현재 시간에 맞게 다시 그려짐
        self.populate_process_list()

        # 웹 버튼 상태 갱신
        self._refresh_web_button_states()

        # 테이블 viewport 강제 업데이트 (화면 다시 그리기)
        if self.process_table.viewport():
            self.process_table.viewport().update()
            self.process_table.viewport().repaint()

        # 창 크기 복원 (절전 복귀 시 창 렌더링 문제 대응)
        if self._saved_size:
            QTimer.singleShot(100, self._restore_window_state)

        logger.info("절전 복귀 UI 갱신 완료")

    def _on_ui_refresh_tick(self) -> None:
        """메인 GUI의 동적 표시를 주기적으로 갱신합니다."""
        start_time = time.time()
        self._ui_refresh_tick_count += 1

        self._refresh_status_columns()
        self._refresh_progress_bars()

        if self._ui_refresh_tick_count % self._WEB_BUTTON_REFRESH_INTERVAL_TICKS == 0:
            self._refresh_web_button_states()

        execution_time = (time.time() - start_time) * 1000
        if execution_time > 100:
            logger.warning(f"ui_refresh_timer 실행 시간 초과: {execution_time:.1f}ms")

    def _ensure_timers_running(self):
        """모든 주기적 타이머가 실행 중인지 확인하고, 중단된 경우 재시작합니다.

        Windows 절전 모드(슬립/최대 절전)에서 복귀할 때 QTimer가 중단될 수 있으므로,
        타이머 상태를 확인하고 필요시 재시작합니다.
        """
        timers_restarted = []

        if hasattr(self, 'monitor_timer') and not self.monitor_timer.isActive():
            self.monitor_timer.start(1000)
            timers_restarted.append('monitor_timer')

        if hasattr(self, 'scheduler_timer') and not self.scheduler_timer.isActive():
            self.scheduler_timer.start(1000)
            timers_restarted.append('scheduler_timer')

        if hasattr(self, 'ui_refresh_timer') and not self.ui_refresh_timer.isActive():
            self.ui_refresh_timer.start(self._UI_REFRESH_INTERVAL_MS)
            timers_restarted.append('ui_refresh_timer')

    def _restore_window_state(self):
        """절전 복귀 후 창 상태를 복원합니다.

        핵심: 창 크기를 +1/-1 픽셀 조정하여 Qt 렌더링 파이프라인을 강제 초기화.
        이 방법이 Windows DWM과 Qt 간의 좌표 불일치를 해결하는 가장 확실한 방법입니다.
        """
        # 1. 강제 다시 그리기
        self.repaint()
        self.update()

        # 2. 창 크기 +1 픽셀 조정 후 복구 (렌더링 파이프라인 강제 초기화)
        #    이 트릭이 유령 렌더링(Ghost Window)을 제거하는 핵심입니다.
        w, h = self.width(), self.height()
        self.resize(w + 1, h + 1)
        self.resize(w, h)

        # 3. 저장된 geometry가 있으면 위치도 복원
        if self._saved_geometry:
            self.move(self._saved_geometry.x(), self._saved_geometry.y())

        # 4. 레이아웃 강제 업데이트
        central_widget = self.centralWidget()
        if central_widget and central_widget.layout():
            central_widget.layout().invalidate()
            central_widget.layout().activate()

        # 5. UI 강제 다시 그리기
        self.update()
        self.repaint()

    def activate_and_show(self):
        """IPC 등을 통해 외부에서 창을 활성화하고 표시하도록 요청받았을 때 호출됩니다."""
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
        icon = QIcon(icon_path_ico)
        if os.path.exists(icon_path_ico) and not icon.isNull():
            self.setWindowIcon(icon)
        else:
            style = QApplication.style()
            self.setWindowIcon(style.standardIcon(QStyle.StandardPixmap.SP_ComputerIcon))

    def _configure_table_header(self):
        h = self.process_table.horizontalHeader()
        if h:
            h.hide()
            h.setSectionsClickable(False)
            h.setHighlightSections(False)
            for col in range(self.TOTAL_COLUMNS):
                h.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)

        vh = self.process_table.verticalHeader()
        if vh:
            vh.hide()
            vh.setHidden(True)
            vh.setVisible(False)
            vh.setMinimumWidth(0)
            vh.setMaximumWidth(0)
            vh.setFixedWidth(0)
            vh.setSectionsClickable(False)
            vh.setHighlightSections(False)
        self.process_table.setCornerButtonEnabled(False)

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
        restart_action = QAction("재시작(&R)", self)
        restart_action.setShortcut("Ctrl+R")
        restart_action.triggered.connect(self._restart_app)
        if fm:
            fm.addAction(restart_action)
            fm.addSeparator()
            fm.addAction(ea) # 종료 액션

        sm = mb.addMenu("설정(&S)") # 설정 메뉴
        gsa = QAction("전역 설정 변경...", self); gsa.triggered.connect(self.open_global_settings_dialog)
        hoyolab_action = QAction("HoYoLab 설정...", self); hoyolab_action.triggered.connect(self.open_hoyolab_settings_dialog)
        sidebar_settings_action = QAction("사이드바 설정...", self)
        sidebar_settings_action.triggered.connect(self.open_sidebar_settings_dialog)
        if sm:
            sm.addAction(gsa) # 전역 설정 변경 액션
            sm.addAction(hoyolab_action)  # HoYoLab 설정 액션
            sm.addSeparator()
            sm.addAction(sidebar_settings_action)

        # 메뉴바 오른쪽 끝: [항상 위] 체크박스 + 볼륨 토글 버튼
        self._volume_btn = QToolButton()
        self._volume_btn.setText("🔊")
        self._volume_btn.setToolTip("볼륨 조절 패널 열기/닫기")
        self._volume_btn.setCheckable(True)
        self._volume_btn.clicked.connect(self._toggle_volume_panel)
        self._volume_btn.setStyleSheet("""
            QToolButton {
                border: 1px solid transparent;
                border-radius: 4px;
                background: transparent;
                padding: 2px 6px;
            }
            QToolButton:hover {
                background: palette(midlight);
                border-color: palette(mid);
            }
            QToolButton:checked {
                background: palette(highlight);
                color: palette(highlighted-text);
                border-color: palette(highlight);
            }
            QToolButton:pressed {
                background: palette(dark);
            }
        """)

        self._always_on_top_cb = QCheckBox("항상 위")
        self._always_on_top_cb.setToolTip("창을 항상 위에 표시")
        self._always_on_top_cb.setChecked(self.data_manager.global_settings.always_on_top)
        self._always_on_top_cb.toggled.connect(self._on_always_on_top_toggled)

        corner_container = QWidget()
        corner_layout = QHBoxLayout(corner_container)
        corner_layout.setContentsMargins(0, 0, 4, 0)
        corner_layout.setSpacing(6)
        corner_layout.addWidget(self._always_on_top_cb)
        corner_layout.addWidget(self._volume_btn)
        mb.setCornerWidget(corner_container, Qt.Corner.TopRightCorner)

    def _restart_app(self) -> None:
        """앱을 재시작합니다."""
        import sys, os
        QApplication.quit()
        os.execv(sys.executable, [sys.executable] + sys.argv)

    def open_sidebar_settings_dialog(self) -> None:
        from src.gui.sidebar_settings_dialog import SidebarSettingsDialog
        gs = self.data_manager.global_settings
        dlg = SidebarSettingsDialog(gs, self)
        if dlg.exec():
            updated = dlg.get_updated_settings()
            if not self.data_manager.save_global_settings(updated, actor="sidebar_settings_dialog"):
                QMessageBox.warning(self, "사이드바 설정", "설정을 저장하지 못해 실행 중 설정도 변경하지 않았습니다.")
                self._poll_beholder_incidents()
                return
            if hasattr(self, '_sidebar_controller'):
                self._sidebar_controller.apply_settings(updated)
            self._apply_screenshot_settings()
            self._apply_recording_settings()

    def _load_always_on_top_setting(self):
        """전역 설정에서 항상 위 설정을 로드합니다."""
        always_on_top = self.data_manager.global_settings.always_on_top
        if always_on_top:
            self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        else:
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowStaysOnTopHint)
        # 메뉴바 체크박스 상태 동기화 (시그널 루프 방지)
        if hasattr(self, '_always_on_top_cb'):
            self._always_on_top_cb.blockSignals(True)
            self._always_on_top_cb.setChecked(always_on_top)
            self._always_on_top_cb.blockSignals(False)

    def _on_always_on_top_toggled(self, checked: bool):
        """메뉴바 [항상 위] 체크박스 토글 시 즉시 적용 및 설정 저장."""
        gs = self.data_manager.global_settings
        gs.always_on_top = checked
        self.data_manager.save_global_settings(gs, actor="global_settings_dialog")
        self._load_always_on_top_setting()
        self.show()

    def _apply_theme(self, theme: str = "system"):
        """테마를 적용합니다. theme: 'system' | 'light' | 'dark'"""
        self._current_theme = theme
        app = QApplication.instance()
        if app is None:
            return
        # setStyle() 호출 시 앱 폰트가 스타일 기본값으로 초기화되는 문제 방지
        saved_font = app.font()
        if theme == "dark":
            app.setStyle("Fusion")
            palette = QPalette()
            dark_base = QColor(42, 42, 42)
            dark_window = QColor(53, 53, 53)
            dark_text = QColor(220, 220, 220)
            highlight = QColor(42, 130, 218)
            palette.setColor(QPalette.ColorRole.Window, dark_window)
            palette.setColor(QPalette.ColorRole.WindowText, dark_text)
            palette.setColor(QPalette.ColorRole.Base, dark_base)
            palette.setColor(QPalette.ColorRole.AlternateBase, QColor(66, 66, 66))
            palette.setColor(QPalette.ColorRole.ToolTipBase, dark_base)
            palette.setColor(QPalette.ColorRole.ToolTipText, dark_text)
            palette.setColor(QPalette.ColorRole.Text, dark_text)
            palette.setColor(QPalette.ColorRole.Button, dark_window)
            palette.setColor(QPalette.ColorRole.ButtonText, dark_text)
            palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 80, 80))
            palette.setColor(QPalette.ColorRole.Link, highlight)
            palette.setColor(QPalette.ColorRole.Highlight, highlight)
            palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
            palette.setColor(QPalette.ColorRole.Mid, QColor(80, 80, 80))
            palette.setColor(QPalette.ColorRole.Shadow, QColor(20, 20, 20))
            palette.setColor(QPalette.ColorRole.Light, QColor(90, 90, 90))
            palette.setColor(QPalette.ColorRole.Midlight, QColor(65, 65, 65))
            app.setPalette(palette)
        elif theme == "light":
            app.setStyle("Fusion")
            # standardPalette() 대신 모든 색상 명시적 정의:
            # 시스템 다크 모드가 활성화된 환경에서도 라이트 팔레트 강제 적용
            palette = QPalette()
            palette.setColor(QPalette.ColorRole.Window, QColor(240, 240, 240))
            palette.setColor(QPalette.ColorRole.WindowText, QColor(0, 0, 0))
            palette.setColor(QPalette.ColorRole.Base, QColor(255, 255, 255))
            palette.setColor(QPalette.ColorRole.AlternateBase, QColor(233, 231, 227))
            palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(255, 255, 220))
            palette.setColor(QPalette.ColorRole.ToolTipText, QColor(0, 0, 0))
            palette.setColor(QPalette.ColorRole.Text, QColor(0, 0, 0))
            palette.setColor(QPalette.ColorRole.Button, QColor(240, 240, 240))
            palette.setColor(QPalette.ColorRole.ButtonText, QColor(0, 0, 0))
            palette.setColor(QPalette.ColorRole.BrightText, QColor(255, 0, 0))
            palette.setColor(QPalette.ColorRole.Link, QColor(0, 0, 255))
            palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
            palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
            palette.setColor(QPalette.ColorRole.Mid, QColor(160, 160, 160))
            palette.setColor(QPalette.ColorRole.Shadow, QColor(105, 105, 105))
            palette.setColor(QPalette.ColorRole.Light, QColor(255, 255, 255))
            palette.setColor(QPalette.ColorRole.Midlight, QColor(227, 227, 227))
            app.setPalette(palette)
        else:  # system
            app.setStyle(self._original_style_name or "")
            app.setPalette(QPalette())
        # 스타일 변경 후 폰트 복원
        app.setFont(saved_font)
        self._sync_windows_title_bar_color()

    def _is_effective_dark_theme(self) -> bool:
        """현재 팔레트가 실질적으로 다크 테마인지 반환합니다."""
        current_theme = getattr(self, "_current_theme", "system")
        if current_theme == "dark":
            return True
        if current_theme == "light":
            return False
        palette = self.palette()
        return palette.color(QPalette.ColorRole.WindowText).lightness() > palette.color(QPalette.ColorRole.Window).lightness()

    def _sync_windows_title_bar_color(self) -> bool:
        """가능한 Windows 환경에서 표준 제목 표시줄 색상을 앱 GUI 팔레트와 맞춥니다."""
        palette = self.palette()
        window = palette.color(QPalette.ColorRole.Window)
        text = palette.color(QPalette.ColorRole.WindowText)
        return apply_windows_title_bar_color(
            int(self.winId()),
            caption_color=(window.red(), window.green(), window.blue()),
            text_color=(text.red(), text.green(), text.blue()),
            dark_mode=self._is_effective_dark_theme(),
        )

    def _table_default_colors(self) -> tuple[QColor, QColor]:
        """테이블 기본 배경/전경색을 반환합니다.

        일부 플랫폼 스타일은 앱 팔레트가 다크여도 QTableWidgetItem에 저장한
        palette(base) 브러시를 밝은 기본색으로 해석할 수 있어, 다크 테마에서는
        명시 색상을 사용해 셀 배경이 창 배경과 어긋나지 않게 합니다.
        """
        if self._is_effective_dark_theme():
            return QColor(42, 42, 42), QColor(220, 220, 220)
        palette = self.process_table.palette()
        return palette.color(QPalette.ColorRole.Base), palette.color(QPalette.ColorRole.Text)

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
            self.data_manager.save_global_settings(upd_gs, actor="global_settings_dialog")

            # 관리자 권한 설정이 변경되었는지 확인 (디버깅용 로그 파일 기록)
            def _log_admin_debug(msg):
                """디버깅 로그를 파일에 기록"""
                try:
                    import datetime
                    log_dir = os.path.join(os.getenv('APPDATA', ''), 'HomeworkHelper')
                    os.makedirs(log_dir, exist_ok=True)
                    log_file = os.path.join(log_dir, 'admin_debug.log')
                    with open(log_file, 'a', encoding='utf-8') as f:
                        f.write(f"[{datetime.datetime.now()}] {msg}\n")
                except:
                    pass

            _log_admin_debug(f"previous_run_as_admin: {previous_run_as_admin}, upd_gs.run_as_admin: {upd_gs.run_as_admin}, is_admin(): {is_admin()}")
            if previous_run_as_admin != upd_gs.run_as_admin:
                if upd_gs.run_as_admin and not is_admin():
                    # 일반 → 관리자: UAC 프롬프트로 관리자 권한 재시작
                    _log_admin_debug("일반 → 관리자 권한 재시작 시도")
                    result = run_as_admin()
                    _log_admin_debug(f"run_as_admin() 반환값: {result}")
                    if result:
                        # 재시작 플래그 설정 후 즉시 종료
                        import homework_helper
                        homework_helper._restart_in_progress = True
                        _log_admin_debug("QApplication.quit() 호출")
                        QApplication.quit()
                        return
                    else:
                        # 재시작 실패 시 설정 롤백
                        _log_admin_debug("재시작 실패, 설정 롤백")
                        upd_gs.run_as_admin = False
                        self.data_manager.save_global_settings(upd_gs, actor="global_settings_dialog")
                        status_bar = self.statusBar()
                        if status_bar:
                            status_bar.showMessage("관리자 권한으로 재시작 실패. 설정이 롤백되었습니다.", 5000)
                        return
                elif not upd_gs.run_as_admin and is_admin():
                    # 관리자 → 일반: 일반 권한으로 재시작
                    _log_admin_debug("관리자 → 일반 권한 재시작 시도")
                    result = restart_as_normal()
                    _log_admin_debug(f"restart_as_normal() 반환값: {result}")
                    if result:
                        # 재시작 플래그 설정 후 즉시 종료
                        import homework_helper
                        homework_helper._restart_in_progress = True
                        _log_admin_debug("QApplication.quit() 호출")
                        QApplication.quit()
                        return
                    else:
                        status_bar = self.statusBar()
                        if status_bar:
                            status_bar.showMessage("일반 권한으로 재시작 실패. 앱을 수동으로 재시작해주세요.", 5000)
            else:
                _log_admin_debug("권한 설정 변경 없음 - 조건문 통과하지 않음")

            # Launcher 인스턴스의 관리자 권한 설정 업데이트
            self.launcher.run_as_admin = upd_gs.run_as_admin

            # '항상 위' 설정이 변경되었을 수 있으므로 즉시 적용
            self._load_always_on_top_setting()
            # 테마 설정 즉시 적용
            self._apply_theme(getattr(upd_gs, 'theme', 'system'))
            self.show() # 창 플래그 변경을 적용하기 위해 show() 호출

            status_bar = self.statusBar()
            if status_bar:
                status_bar.showMessage("전역 설정 저장됨.", 3000) # 상태 표시줄 메시지
            self.apply_startup_setting() # 시작 프로그램 설정 적용
            self.populate_process_list() # 전체 테이블 새로고침 (전역 설정 변경)
            self._refresh_web_button_states() # 웹 버튼 상태 새로고침 (전역 설정 변경이 웹 버튼에 영향을 줄 수 있는 경우)
            self._adjust_window_height_for_table_rows() # 창 높이 조절

            # 시작 프로그램 상태 확인 및 메시지 표시
            current_status = get_startup_shortcut_status()
            status_bar = self.statusBar()
            if status_bar:
                if current_status:
                    status_bar.showMessage("시작 프로그램에 등록되어 있습니다.", 3000)
                else:
                    status_bar.showMessage("시작 프로그램에 등록되어 있지 않습니다.", 3000)

    def open_hoyolab_settings_dialog(self):
        """HoYoLab 인증 정보 설정 다이얼로그를 엽니다."""
        dlg = HoYoLabSettingsDialog(self)
        dlg.exec()

    def apply_startup_setting(self):

        """시작 프로그램 자동 실행 설정을 적용합니다."""
        run = self.data_manager.global_settings.run_on_startup # 자동 실행 여부 가져오기
        status_bar = self.statusBar()
        if set_startup_shortcut(run): # 바로가기 설정 시도
            if status_bar:
                status_bar.showMessage(f"시작 시 자동 실행: {'활성' if run else '비활성'}", 3000)
        else:
            if status_bar:
                status_bar.showMessage("자동 실행 설정 중 문제 발생 가능.", 3000)

    def run_process_monitor_check(self):
        """실행 중인 프로세스를 확인하고 상태 변경 시 테이블을 새로고침합니다."""
        monitor_result = self.process_monitor.check_and_update_statuses() # 상태 변경 감지

        for event in monitor_result.started:
            self._hoyolab_reconcile.handle_process_started(event)
        for event in monitor_result.stopped:
            self._hoyolab_reconcile.handle_process_stopped(event)

        if monitor_result.changed:
            status_bar = self.statusBar()
            if status_bar:
                status_bar.showMessage("프로세스 상태 변경 감지됨.", 2000)
            self.update_process_statuses_only() # 상태 컬럼만 업데이트

        # 사이드바/게임 모드는 ProcessMonitor의 시작·종료 이벤트 외에도
        # Beholder 복구, startup reconcile, 외부 캐시 재결합처럼 이미 실행 중인
        # 상태가 캐시에 들어온 뒤 steady-state tick만 발생하는 경로가 있습니다.
        # changed=True에만 묶으면 앱 기동 후 서랍 손잡이 트리거가 시작되지 않을 수
        # 있으므로 매 tick 실제 active cache와 UI 모드를 재동기화합니다.
        self._check_and_toggle_game_mode()

    def _check_and_toggle_game_mode(self):
        """실행 중인 게임이 있는지 확인하고, 그에 따라 창을 숨기거나 표시합니다."""
        # 게임 감지 시 창 숨기기 기능이 비활성화된 경우 게임 모드 플래그만 갱신
        hide_enabled = getattr(self.data_manager.global_settings, 'hide_on_game', True)

        # 현재 모니터링 중인 프로세스 중 ProcessMonitor가 실제 실행 중으로
        # 보유한 항목을 직접 확인합니다. Scheduler의 시각 상태도 이 캐시를
        # 0순위로 보지만, 여기서는 사이드바를 열 대상 process/pid까지 같은
        # 스냅샷에서 얻어야 하므로 active cache를 기준으로 삼습니다.
        running_process = None
        running_pid = None
        for p in self.data_manager.managed_processes:
            entry = self.process_monitor.active_monitored_processes.get(p.id)
            if entry is not None:
                running_process = p
                running_pid = entry.get('pid')
                break

        any_game_running = running_process is not None

        if any_game_running and not self._is_game_mode_active:
            # 게임이 실행되었고, 아직 게임 모드가 활성화되지 않았다면
            self._is_game_mode_active = True
            if hide_enabled:
                self.tray_manager.handle_minimize_event() # 창을 트레이로 숨김
                status_bar = self.statusBar()
                if status_bar:
                    status_bar.showMessage("게임 실행 중: 창이 트레이로 숨겨졌습니다.", 3000)
            if hasattr(self, '_sidebar_controller') and running_process is not None:
                self._sidebar_controller.activate_for_game(
                    running_process,
                    pid=running_pid,
                    game_start_timestamp=None,
                )
                # 스크린샷 매니저 시작
                self._start_screenshot_manager()
                # 사이드바 생성 직후 RecordingManager의 현재 상태를 즉시 동기화
                # (앱 시작 시 연결 시도가 사이드바 생성보다 먼저 완료되는 경우
                #  상태 변경 신호가 버려지므로, 여기서 강제로 한 번 재전송)
                if hasattr(self, '_recording_manager'):
                    self._recording_state_sig.emit(self._recording_manager.get_state())
        elif not any_game_running and self._is_game_mode_active:
            # 모든 게임이 종료되었고, 게임 모드가 활성화되어 있었다면
            self._is_game_mode_active = False
            if hasattr(self, '_sidebar_controller'):
                self._sidebar_controller.deactivate()
            if hide_enabled:
                self.activate_and_show() # 창을 다시 표시
                status_bar = self.statusBar()
                if status_bar:
                    status_bar.showMessage("모든 게임 종료: 창이 다시 표시되었습니다.", 3000)

    def run_scheduler_check(self):
        """스케줄러 검사를 실행하고 상태 변경이 있을 때만 테이블을 업데이트합니다."""
        start_time = time.time()

        # 스케줄러 검사 실행 (알림 발송 등)
        status_changed = self.scheduler.run_all_checks() # 게임 관련 스케줄 검사

        if status_changed:
            self.update_process_statuses_only()

        # 웹 버튼 상태는 별도 타이머(_refresh_web_button_states)로 주기적으로 체크하므로 여기서 호출하지 않음

        # 타이머 실행 시간 로깅 (100ms 이상 걸리면 경고)
        execution_time = (time.time() - start_time) * 1000
        if execution_time > 100:
            logger.warning(f"scheduler_timer 실행 시간 초과: {execution_time:.1f}ms")

    def populate_process_list_slot(self):
        """테이블 새로고침 시그널에 연결된 슬롯입니다."""
        self.populate_process_list()

    def update_process_statuses_only(self):
        """프로세스 상태 컬럼만 업데이트합니다. 버튼은 유지하여 포커스 문제를 방지합니다."""
        if not hasattr(self, 'process_table') or not self.process_table:
            return

        processes_by_id = {
            process.id: process
            for process in self.data_manager.managed_processes
        }
        now_dt = datetime.datetime.now()
        gs = self.data_manager.global_settings
        df_bg, df_fg = self._table_default_colors()

        # 현재 테이블의 행 수와 프로세스 수가 다르면 전체 새로고침 필요
        if self.process_table.rowCount() != len(processes_by_id):
            self.populate_process_list()
            return

        has_changes = False
        for r in range(self.process_table.rowCount()):
            name_item = self.process_table.item(r, self.COL_NAME)
            if not name_item:
                self.populate_process_list()
                return

            process_id = name_item.data(Qt.ItemDataRole.UserRole)
            p = processes_by_id.get(process_id)
            if p is None:
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

            # 새로 실행된 프로세스에 기본 볼륨 자동 적용
            pid = self._get_active_pid(p.id)
            self._sync_default_volume_state(p, pid)

        # 상태 변경과 별개로 진행률 컬럼은 전용 refresh 루프에서 갱신한다.
        self._refresh_progress_bars()

        # 실제 변경사항이 있을 때만 상태바 메시지 표시
        if has_changes:
            status_bar = self.statusBar()
            if status_bar:
                status_bar.showMessage("프로세스 상태 업데이트됨.", 2000)

    def populate_process_list(self):
        """관리 대상 프로세스 목록을 테이블에 채웁니다."""
        self.process_table.setSortingEnabled(False) # 사용자가 바꿀 수 없는 고정 정렬
        processes = sorted(
            self.data_manager.managed_processes,
            key=lambda process: ((process.name or "").casefold(), process.id or ""),
        )
        self.process_table.setRowCount(len(processes)) # 행 개수 설정

        now_dt = datetime.datetime.now() # 현재 시각
        gs = self.data_manager.global_settings # 전역 설정
        df_bg, df_fg = self._table_default_colors() # 기본 배경색 및 글자색

        for r, p in enumerate(processes): # 각 프로세스에 대해 반복
            # 아이콘 컬럼
            icon_item = QTableWidgetItem()
            qi = get_qicon_for_file(
                p.monitoring_path,
                icon_size=getattr(self, '_table_icon_logical_size', self._TABLE_ICON_LOGICAL_SIZE),
                process_id=p.id,
            )
            if qi and not qi.isNull(): icon_item.setIcon(qi)
            icon_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.process_table.setItem(r, self.COL_ICON, icon_item); icon_item.setBackground(df_bg); icon_item.setForeground(df_fg)

            # 이름 컬럼 (UserRole에 ID 저장)
            name_item = QTableWidgetItem(p.name)
            name_item.setData(Qt.ItemDataRole.UserRole, p.id) # UserRole에 프로세스 ID 저장
            self.process_table.setItem(r, self.COL_NAME, name_item); name_item.setBackground(df_bg); name_item.setForeground(df_fg)

            # 마지막 플레이 컬럼 (진행률 표시)
            percentage, time_str = self._calculate_progress_percentage(p, now_dt)
            progress_widget = self._create_progress_bar_widget(p, percentage, time_str)
            self.process_table.setCellWidget(r, self.COL_LAST_PLAYED, progress_widget)

            # 실행 버튼 컬럼
            btn = QPushButton("실행")
            btn.clicked.connect(functools.partial(self.handle_launch_button_in_row, p.id)) # 버튼 클릭 시그널 연결

            # 모니터링 경로와 실행 경로가 다른 경우 우클릭 메뉴 활성화
            if p.monitoring_path != p.launch_path and p.launch_path:
                btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                btn.customContextMenuRequested.connect(
                    functools.partial(self._show_launch_context_menu, p.id, btn)
                )
                current_pref = getattr(p, "preferred_launch_type", "shortcut")
                if current_pref == "auto":
                    current_pref = "shortcut"
                pref_label = "바로가기 선호" if current_pref == "shortcut" else "프로세스 선호"
                btn.setToolTip(f"좌클릭: 실행 / 우클릭: 기본 실행 방식 설정 (현재: {pref_label})")

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

            pid = self._get_active_pid(p.id)
            self._sync_default_volume_state(p, pid)

        self.scheduler.invalidate_visual_status_snapshot()
        QTimer.singleShot(0, self._adjust_window_size_to_content)

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
                                       original_launch_path=getattr(p_edit, 'original_launch_path', data["launch_path"]),  # 원본 경로 보존
                                       preferred_launch_type=data.get("preferred_launch_type", "shortcut"),  # 실행 방식 선택
                                       user_preset_id=data.get("user_preset_id"),  # 사용자 프리셋 ID
                                       stamina_tracking_enabled=data.get("stamina_tracking_enabled", False),  # 스태미나 추적
                                       hoyolab_game_id=data.get("hoyolab_game_id"),  # 호요랩 게임 ID
                                       stamina_current=getattr(p_edit, 'stamina_current', None),  # 기존 스태미나 정보 유지
                                       stamina_max=getattr(p_edit, 'stamina_max', None),
                                       stamina_updated_at=getattr(p_edit, 'stamina_updated_at', None),
                                       default_volume=getattr(p_edit, 'default_volume', None))  # 기존 볼륨 설정 보존

                if self.data_manager.update_process(upd_p): # 프로세스 정보 업데이트
                    self.populate_process_list() # 전체 테이블 새로고침 (프로세스 정보 변경)
                    # 테이블이 완전히 렌더링된 후 창 높이 조절 (다음 이벤트 루프에서 실행)
                    QTimer.singleShot(0, self._adjust_window_height_for_table_rows)
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
                # 테이블이 완전히 렌더링된 후 창 높이 조절 (다음 이벤트 루프에서 실행)
                QTimer.singleShot(0, self._adjust_window_height_for_table_rows)
                status_bar = self.statusBar()
                if status_bar:
                    status_bar.showMessage(f"'{p_del.name}' 삭제 완료.", 3000)
            else: QMessageBox.warning(self, "오류", "프로세스 삭제 실패.")

    def handle_launch_button_in_row(self, pid:str): # 게임 실행
        """선택된 게임 프로세스를 실행합니다."""
        p_launch = self.data_manager.get_process_by_id(pid) # ID로 프로세스 정보 가져오기
        if not p_launch: QMessageBox.warning(self, "오류", f"ID '{pid}' 프로세스 없음."); return

        # preferred_launch_type에 따라 실행 경로 결정
        launch_type = getattr(p_launch, 'preferred_launch_type', 'shortcut') or 'shortcut'
        if launch_type == 'direct':
            # 직접 실행 선호: 모니터링 경로 사용, 없으면 실행 경로 사용
            launch_target = p_launch.monitoring_path or p_launch.launch_path
        elif launch_type == 'shortcut':
            # 바로가기 선호: 실행 경로 사용, 없으면 모니터링 경로 사용
            launch_target = p_launch.launch_path or p_launch.monitoring_path
        elif launch_type == 'launcher':
            # 런처 우선: 프리셋에서 런처 패턴 확인 후 사용, 없으면 shortcut 방식으로 폴백
            # 런처 경로를 찾기 위한 로직: 프리셋의 launcher_patterns 활용
            launcher_path = None
            if hasattr(p_launch, 'user_preset_id') and p_launch.user_preset_id:
                preset = self.preset_manager.get_preset_by_id(p_launch.user_preset_id)
                if preset and preset.get('launcher_patterns'):
                    # 런처 패턴으로 경로 탐색 (간단히 실행 경로에서 런처 탐색)
                    launch_dir = os.path.dirname(p_launch.launch_path or p_launch.monitoring_path or '')
                    for pattern in preset['launcher_patterns']:
                        potential_launcher = os.path.join(launch_dir, pattern)
                        if os.path.exists(potential_launcher):
                            launcher_path = potential_launcher
                            break
            launch_target = launcher_path or p_launch.launch_path or p_launch.monitoring_path
        else:
            # 레거시 'auto' 등: 실행 경로가 있으면 사용, 없으면 모니터링 경로
            launch_target = p_launch.launch_path or p_launch.monitoring_path

        if not launch_target: QMessageBox.warning(self, "오류", f"'{p_launch.name}' 실행 경로 없음."); return

        if self.launcher.launch_process(launch_target): # 프로세스 실행 시도
            status_bar = self.statusBar()
            if status_bar:
                status_bar.showMessage(f"'{p_launch.name}' 실행 시도.", 3000)
            self._schedule_focus_after_launch(p_launch, launch_target)
            # 실행 성공 시 즉시 상태 업데이트
            self.update_process_statuses_only()
        else: # 실행 실패 시
            status_bar = self.statusBar()
            if status_bar:
                status_bar.showMessage(f"'{p_launch.name}' 실행 실패.", 3000)

    def _launch_with_specific_path(self, pid: str, use_shortcut: bool):
        """특정 경로로 프로세스 실행 (우클릭 메뉴용)"""
        p_launch = self.data_manager.get_process_by_id(pid)
        if not p_launch: return

        launch_target = p_launch.launch_path if use_shortcut else p_launch.monitoring_path
        if not launch_target:
            QMessageBox.warning(self, "오류", f"해당 경로가 없습니다.")
            return

        if self.launcher.launch_process(launch_target):
            status_bar = self.statusBar()
            if status_bar:
                path_type = "바로가기" if use_shortcut else "직접 실행"
                status_bar.showMessage(f"'{p_launch.name}' {path_type}으로 실행 시도.", 3000)
            self._schedule_focus_after_launch(p_launch, launch_target)
            self.update_process_statuses_only()
        else:
            status_bar = self.statusBar()
            if status_bar:
                status_bar.showMessage(f"'{p_launch.name}' 실행 실패.", 3000)

    def _set_launch_preference(self, pid: str, preference: str):
        """기본 실행 방식을 영구 저장"""
        p = self.data_manager.get_process_by_id(pid)
        if not p or preference not in ("shortcut", "direct"):
            return

        current_pref = getattr(p, "preferred_launch_type", "shortcut") or "shortcut"
        if current_pref == "auto":
            current_pref = "shortcut"

        if current_pref == preference:
            status_bar = self.statusBar()
            if status_bar:
                status_bar.showMessage(f"이미 '{('바로가기' if preference == 'shortcut' else '프로세스')}' 선호로 설정되어 있습니다.", 3000)
            return

        updated_data = p.to_dict() if hasattr(p, "to_dict") else p.__dict__.copy()
        updated_data["preferred_launch_type"] = preference
        updated_process = ManagedProcess(**updated_data)

        if self.data_manager.update_process(updated_process):
            self.populate_process_list()
            status_bar = self.statusBar()
            if status_bar:
                status_bar.showMessage(
                    f"기본 실행 방식이 '{('바로가기 선호' if preference == 'shortcut' else '프로세스 선호')}'로 저장되었습니다.",
                    4000
                )
        else:
            QMessageBox.warning(self, "저장 실패", "기본 실행 방식을 저장하지 못했습니다.")

    def _schedule_focus_after_launch(self, process: ManagedProcess, launch_target: str | None = None) -> None:
        """게임 창이 늦게 생기는 경우를 고려해 foreground focus를 재시도합니다."""
        self._focus_attempt_tokens[process.id] = self._focus_attempt_tokens.get(process.id, 0) + 1
        token = self._focus_attempt_tokens[process.id]
        executable_path = process.monitoring_path or launch_target or process.launch_path

        def _attempt(remaining: int) -> None:
            if self._focus_attempt_tokens.get(process.id) != token:
                return
            entry = self.process_monitor.active_monitored_processes.get(process.id, {})
            pid = entry.get("pid")
            if focus_process_window(pid=pid, executable_path=executable_path):
                status_bar = self.statusBar()
                if status_bar:
                    status_bar.showMessage(f"'{process.name}' 창으로 포커스를 이동했습니다.", 2000)
                return
            if remaining <= 0:
                return
            QTimer.singleShot(
                self._FOCUS_ATTEMPT_INTERVAL_MS,
                functools.partial(_attempt, remaining - 1),
            )

        QTimer.singleShot(0, functools.partial(_attempt, self._FOCUS_ATTEMPT_COUNT))

    def _show_launch_context_menu(self, pid: str, button: QPushButton, pos):
        """실행 버튼 우클릭 시 컨텍스트 메뉴 표시"""
        from PyQt6.QtWidgets import QMenu

        p = self.data_manager.get_process_by_id(pid)
        if not p: return

        current_pref = getattr(p, "preferred_launch_type", "shortcut") or "shortcut"
        if current_pref == "auto":
            current_pref = "shortcut"

        menu = QMenu(button)

        shortcut_action = menu.addAction("바로가기 선호 (기본 실행)")
        shortcut_action.setCheckable(True)
        shortcut_action.setChecked(current_pref == "shortcut")
        shortcut_action.triggered.connect(
            functools.partial(self._set_launch_preference, pid, "shortcut")
        )
        if not p.launch_path:
            shortcut_action.setEnabled(False)

        direct_action = menu.addAction("프로세스 선호 (직접 실행)")
        direct_action.setCheckable(True)
        direct_action.setChecked(current_pref == "direct")
        direct_action.triggered.connect(
            functools.partial(self._set_launch_preference, pid, "direct")
        )
        if not p.monitoring_path:
            direct_action.setEnabled(False)

        menu.exec(button.mapToGlobal(pos))

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
                                       original_launch_path=data["launch_path"],  # 원본 경로 보존
                                       preferred_launch_type=data.get("preferred_launch_type", "shortcut"),  # 실행 방식 선택
                                       user_preset_id=data.get("user_preset_id"),  # 사용자 프리셋 ID
                                       stamina_tracking_enabled=data.get("stamina_tracking_enabled", False),  # 스태미나 추적
                                       hoyolab_game_id=data.get("hoyolab_game_id"))  # 호요랩 게임 ID
                self.data_manager.add_process(new_p) # 데이터 매니저에 프로세스 추가
                self.populate_process_list() # 전체 테이블 새로고침 (프로세스 추가)
                # 테이블이 완전히 렌더링된 후 창 높이 조절 (다음 이벤트 루프에서 실행)
                QTimer.singleShot(0, self._adjust_window_height_for_table_rows)
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
        start_time = time.time()
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
                df_bg, df_fg = self._table_default_colors()

                status_item.setBackground(df_bg)  # 기본 배경색으로 초기화
                status_item.setForeground(df_fg)  # 기본 글자색으로 초기화

                if new_status == PROC_STATE_RUNNING:
                    status_item.setBackground(self.COLOR_RUNNING)
                    status_item.setForeground(QColor("black"))
                elif new_status == PROC_STATE_INCOMPLETE:
                    status_item.setBackground(self.COLOR_INCOMPLETE)
                elif new_status == PROC_STATE_COMPLETED:
                    status_item.setBackground(self.COLOR_COMPLETED)

        # 상태 변경이 있었으면 viewport 강제 갱신 (절전 복귀 후 화면 그리기 문제 대응)
        if status_changes > 0:
            if self.process_table.viewport():
                self.process_table.viewport().update()

        # 타이머 실행 시간 로깅 (100ms 이상 걸리면 경고)
        execution_time = (time.time() - start_time) * 1000
        if execution_time > 100:
            logger.warning(f"_refresh_status_columns 실행 시간 초과: {execution_time:.1f}ms")

    def _refresh_status_columns_immediate(self):
        """상태 컬럼을 즉시 새로고침합니다 (중요한 시각 변경 시 호출)."""
        self._refresh_status_columns()

    def refresh_presets_and_ui(self):
        """프리셋 매니저를 다시 로드하고 UI를 새로고침합니다 (프리셋 편집 후 호출)."""
        # 프리셋 매니저 새로고침
        self.preset_manager.reload()

        # 프로세스 목록 새로고침 (아이콘 변경사항 반영)
        self.populate_process_list()

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
        shortcut = self.data_manager.get_web_shortcut_by_id(shortcut_id) # 바로가기 정보 가져오기
        if not shortcut: # 바로가기 정보 없으면 경고 후 URL 열기 시도
            QMessageBox.warning(self, "오류", "해당 웹 바로 가기 정보를 찾을 수 없습니다.")
            self.open_webpage(url) # URL 열기 시도
            return

        self.open_webpage(url) # URL 열기

        # 초기화 시간이 설정된 바로가기인 경우, 마지막 초기화 타임스탬프 업데이트
        if shortcut.refresh_time_str:
            if hasattr(self.data_manager, "mark_web_shortcut_opened"):
                saved = self.data_manager.mark_web_shortcut_opened(shortcut.id)
            else:
                shortcut.last_reset_timestamp = datetime.datetime.now().timestamp() # 현재 시각으로 업데이트
                saved = self.data_manager.update_web_shortcut(shortcut) # legacy 데이터 매니저 폴백
            if saved:
                self._refresh_web_button_states() # 버튼 상태 즉시 새로고침

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

    def _save_window_geometry(self):
        """현재 창 위치와 크기를 QSettings에 저장합니다."""
        try:
            self._settings.setValue("window_geometry", self.saveGeometry())
            self._settings.setValue("window_position", self.pos())
            self._settings.sync()
            logger.debug(f"창 위치 저장: {self.pos()}, 크기: {self.size()}")
        except Exception as e:
            logger.error(f"창 위치 저장 실패: {e}", exc_info=True)

    def _restore_window_geometry(self):
        """저장된 창 위치와 크기를 복원합니다."""
        try:
            # 저장된 geometry가 있으면 복원
            geometry = self._settings.value("window_geometry")
            if geometry:
                self.restoreGeometry(geometry)
                logger.debug("저장된 창 geometry 복원 완료")
                self._clamp_window_to_available_screen()
                return

            # geometry가 없으면 position만 복원
            position = self._settings.value("window_position")
            if position:
                self.move(position)
                logger.debug(f"저장된 창 위치 복원: {position}")
                self._clamp_window_to_available_screen()
        except Exception as e:
            logger.error(f"창 위치 복원 실패: {e}", exc_info=True)

    def _clamp_window_to_available_screen(self):
        """창이 상태 표시줄/Dock 등을 제외한 화면 유효 영역 안에 위치하도록 보정합니다."""
        try:
            screen = QApplication.screenAt(self.pos())
            if not screen:
                screen = QApplication.primaryScreen()
            if not screen:
                return
            avail = screen.availableGeometry()
            # 창 크기가 가용 영역을 초과하면 먼저 크기를 줄임 (위치 계산 전)
            if self.height() > avail.height():
                self.resize(self.width(), avail.height())
            if self.width() > avail.width():
                self.resize(avail.width(), self.height())
            pos = self.pos()
            size = self.size()
            new_x = max(avail.left(), min(pos.x(), avail.right() - size.width() + 1))
            new_y = max(avail.top(), min(pos.y(), avail.bottom() - size.height() + 1))
            if new_x != pos.x() or new_y != pos.y():
                self.move(new_x, new_y)
                logger.debug(f"창 위치 화면 영역으로 보정: ({new_x}, {new_y})")
        except Exception as e:
            logger.error(f"창 위치 보정 실패: {e}", exc_info=True)

    def moveEvent(self, event):
        """창 이동 이벤트 - 마그넷 스냅 기능 구현"""
        super().moveEvent(event)

        # 마그넷 스냅 활성화 (화면 가장자리에 자동 정렬)
        try:
            # 현재 창 위치와 크기
            window_rect = self.frameGeometry()
            window_pos = window_rect.topLeft()

            # 현재 창이 있는 스크린 찾기
            screen = QApplication.screenAt(window_pos)
            if not screen:
                screen = QApplication.primaryScreen()

            if screen:
                # 사용 가능한 화면 영역 (작업 표시줄 제외)
                available_geometry = screen.availableGeometry()

                # 마그넷 감도 (픽셀 단위)
                snap_threshold = 15

                new_x = window_pos.x()
                new_y = window_pos.y()

                # 왼쪽 가장자리 스냅
                if abs(window_rect.left() - available_geometry.left()) < snap_threshold:
                    new_x = available_geometry.left()

                # 오른쪽 가장자리 스냅
                if abs(window_rect.right() - available_geometry.right()) < snap_threshold:
                    new_x = available_geometry.right() - window_rect.width()

                # 위쪽 가장자리 스냅
                if abs(window_rect.top() - available_geometry.top()) < snap_threshold:
                    new_y = available_geometry.top()

                # 아래쪽 가장자리 스냅 (덜 자주 사용되므로 선택적)
                if abs(window_rect.bottom() - available_geometry.bottom()) < snap_threshold:
                    new_y = available_geometry.bottom() - window_rect.height()

                # 위치가 변경되었으면 이동
                if new_x != window_pos.x() or new_y != window_pos.y():
                    self.move(new_x, new_y)

        except Exception as e:
            logger.error(f"마그넷 스냅 처리 중 오류: {e}", exc_info=True)

    def closeEvent(self, event: QEvent):
        """창 닫기 이벤트를 처리합니다. 트레이 관리자가 있으면 트레이로 숨깁니다."""
        # 창 위치 저장 (트레이로 숨기기 전에 저장)
        self._save_window_geometry()

        if hasattr(self, 'tray_manager') and self.tray_manager:
            self.tray_manager.handle_window_close_event(event) # 트레이 관리자에게 이벤트 처리 위임
        else: # 트레이 관리자 없으면 기본 동작 (숨기기)
            event.ignore()
            self.hide()

    def initiate_quit_sequence(self):
        """애플리케이션 종료 절차를 시작합니다 (타이머 중지, 아이콘 숨기기, 리소스 정리 등)."""

        # 0. 창 위치 저장 (앱 종료 시)
        self._save_window_geometry()

        # 1. 활성화된 타이머들 중지
        if hasattr(self, 'monitor_timer') and self.monitor_timer.isActive():
            self.monitor_timer.stop()
        if hasattr(self, 'scheduler_timer') and self.scheduler_timer.isActive():
            self.scheduler_timer.stop()
        if hasattr(self, 'ui_refresh_timer') and self.ui_refresh_timer.isActive():
            self.ui_refresh_timer.stop()
        if hasattr(self, 'runtime_heartbeat_timer') and self.runtime_heartbeat_timer.isActive():
            self.runtime_heartbeat_timer.stop()
        if hasattr(self.data_manager, "send_runtime_heartbeat"):
            self.data_manager.send_runtime_heartbeat(shutdown=True, runtime_kind="pyqt")

        # 2. 트레이 아이콘 숨기기
        if hasattr(self, 'tray_manager') and self.tray_manager:
            self.tray_manager.hide_tray_icon()

        # 3. 인스턴스 매니저 리소스 정리 (단일 인스턴스 실행 관련)
        if self._instance_manager and hasattr(self._instance_manager, 'cleanup'):
            self._instance_manager.cleanup()

        # 3-1. 볼륨 패널 정리 (대기 중인 볼륨 저장 타이머 플러시)
        if hasattr(self, '_volume_panel') and self._volume_panel:
            self._volume_panel.cleanup()

        # 3-2. 사이드바 컨트롤러 정리
        if hasattr(self, '_sidebar_controller'):
            self._sidebar_controller.cleanup()

        # 3-2. 녹화 매니저 종료
        if hasattr(self, '_recording_manager'):
            self._recording_manager.shutdown()

        if hasattr(self, '_hoyolab_reconcile'):
            self._hoyolab_reconcile.shutdown()

        # 3-3. Game Bar 설정 복원
        self._restore_gamebar_setting()

        # 4. QApplication 종료
        app_instance = QApplication.instance()
        if app_instance:
            app_instance.quit()

    def _visible_table_columns(self) -> list[int]:
        return [
            column
            for column in range(self.process_table.columnCount())
            if not self.process_table.isColumnHidden(column)
        ]

    def _cell_content_width(self, row: int, column: int) -> int:
        """아이템/셀 위젯의 실제 sizeHint를 함께 반영한 컬럼 최소 폭."""
        if column == self.COL_ICON:
            # 아이콘 전용 컬럼은 QTableWidgetItem.sizeHint()의 플랫폼별 기본 여백을
            # 신뢰하지 않고, 표시 아이콘 + 최소 여백만으로 고정해 불필요한 빈 폭을 막습니다.
            return self.process_table.iconSize().width() + self._TABLE_ICON_COLUMN_PADDING

        style = self.process_table.style() or self.style()
        focus_margin = style.pixelMetric(QStyle.PixelMetric.PM_FocusFrameHMargin) if style else 2
        metrics = self.process_table.fontMetrics()
        padding = max(metrics.horizontalAdvance("  "), focus_margin * 2 + self.process_table.frameWidth() * 2)

        widget = self.process_table.cellWidget(row, column)
        widget_width = widget.sizeHint().width() if widget is not None else 0

        item = self.process_table.item(row, column)
        item_width = 0
        if item is not None:
            item_width = max(
                item.sizeHint().width(),
                metrics.horizontalAdvance(f" {item.text()} ") + padding,
            )
            if not item.icon().isNull():
                item_width += self.process_table.iconSize().width() + padding

        return max(widget_width, item_width)

    def _resize_table_to_contents(self, max_table_size: Optional[QSize] = None) -> QSize:
        """헤더 없이도 각 셀 내용에 맞는 테이블 고정 크기를 계산합니다."""
        table = self.process_table
        self._configure_table_header()
        table.resizeRowsToContents()

        default_row_height = max(self._TABLE_ROW_HEIGHT, table.verticalHeader().defaultSectionSize())
        for row in range(table.rowCount()):
            table.setRowHeight(row, max(default_row_height, table.rowHeight(row)))

        visible_columns = self._visible_table_columns()
        style = table.style() or self.style()
        column_gap = style.pixelMetric(QStyle.PixelMetric.PM_LayoutHorizontalSpacing) if style else 6
        column_gap = max(4, column_gap)

        for column in visible_columns:
            max_width = 0
            for row in range(table.rowCount()):
                max_width = max(max_width, self._cell_content_width(row, column))
            if table.rowCount() == 0:
                max_width = max(max_width, table.fontMetrics().horizontalAdvance("빈 목록") + column_gap * 2)
            table.setColumnWidth(column, max_width + column_gap)

        frame = table.frameWidth() * 2
        content_width = sum(table.columnWidth(column) for column in visible_columns) + frame
        content_height = frame
        if table.rowCount() > 0:
            content_height += sum(table.rowHeight(row) for row in range(table.rowCount()))
        else:
            content_height += max(default_row_height, table.fontMetrics().height() + column_gap * 2)

        max_width = max_table_size.width() if max_table_size and max_table_size.width() > 0 else None
        max_height = max_table_size.height() if max_table_size and max_table_size.height() > 0 else None

        horizontal_overflow = max_width is not None and content_width > max_width
        vertical_overflow = max_height is not None and content_height > max_height
        table.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded if horizontal_overflow else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        table.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded if vertical_overflow else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        target_width = content_width
        target_height = content_height
        if vertical_overflow and not horizontal_overflow:
            target_width += table.verticalScrollBar().sizeHint().width()
        if horizontal_overflow:
            target_height += table.horizontalScrollBar().sizeHint().height()

        if max_width is not None:
            target_width = min(target_width, max_width)
        if max_height is not None:
            target_height = min(target_height, max_height)

        target = QSize(max(target_width, 1), max(target_height, 1))
        table.setFixedSize(target)
        table.updateGeometry()
        return target

    def _adjust_window_size_to_content(self):
        """현재 테이블/웹 버튼/상태바 sizeHint에 맞춰 창 크기를 동적으로 최적화합니다."""
        table_size = self._resize_table_to_contents()

        central_widget = self.centralWidget()
        if central_widget and central_widget.layout():
            central_widget.layout().invalidate()
            central_widget.layout().activate()

        self.setMinimumSize(self._MIN_WINDOW_WIDTH, self._MIN_WINDOW_HEIGHT)
        target = self.sizeHint().expandedTo(self.minimumSizeHint())

        screen = self.screen() or QApplication.primaryScreen()
        max_width: Optional[int] = None
        max_height: Optional[int] = None
        if screen is not None:
            available = screen.availableGeometry()
            max_width = max(self._MIN_WINDOW_WIDTH, int(available.width() * self._SCREEN_SIZE_RATIO))
            max_height = max(self._MIN_WINDOW_HEIGHT, int(available.height() * self._SCREEN_SIZE_RATIO))

        if (
            (max_width is not None and target.width() > max_width)
            or (max_height is not None and target.height() > max_height)
        ):
            extra_width = max(0, target.width() - table_size.width())
            extra_height = max(0, target.height() - table_size.height())
            capped_table_size = QSize(
                max(1, (max_width or target.width()) - extra_width),
                max(1, (max_height or target.height()) - extra_height),
            )
            self._resize_table_to_contents(capped_table_size)
            if central_widget and central_widget.layout():
                central_widget.layout().invalidate()
                central_widget.layout().activate()
            target = self.sizeHint().expandedTo(self.minimumSizeHint())

        target.setWidth(max(target.width(), self.minimumSizeHint().width(), self._MIN_WINDOW_WIDTH))
        target.setHeight(max(target.height(), self.minimumSizeHint().height(), self._MIN_WINDOW_HEIGHT))
        if max_width is not None:
            target.setWidth(min(target.width(), max_width))
        if max_height is not None:
            target.setHeight(min(target.height(), max_height))

        self.resize(target)
        self.updateGeometry()
        self.update()

        self._saved_size = self.size()
        self._saved_geometry = self.geometry()

    def _adjust_window_height_to_table(self):
        """기존 메서드명 호환성을 위한 별칭"""
        self._adjust_window_size_to_content()

    def _adjust_window_width_for_web_buttons(self):
        """웹 바로가기 변경 후 전체 content 기반 크기 계산을 다시 수행합니다."""
        self._adjust_window_size_to_content()

    def _adjust_window_height_for_table_rows(self):
        """기존 호출부 호환: 전체 content 기반 크기 계산을 수행합니다."""
        self._adjust_window_size_to_content()

    # ───────── 볼륨 패널 ─────────

    def _toggle_volume_panel(self):
        """볼륨 팝오버 패널을 토글합니다."""
        if self._volume_panel.isVisible():
            self._volume_panel.hide()
            self._volume_btn.setChecked(False)
            self._volume_btn.setText("🔊")
        else:
            all_entries = []
            for p in self.data_manager.managed_processes:
                pid = self._get_active_pid(p.id)  # 실행 중이 아니면 None
                all_entries.append((p, pid))
            self._volume_panel.refresh(all_entries)
            self._volume_panel.show_below(self._volume_btn)
            self._volume_btn.setChecked(True)

    def _on_volume_panel_hidden(self):
        """볼륨 패널이 숨겨질 때 (외부 클릭 포함) 토글 버튼 상태를 초기화합니다."""
        self._volume_btn.setChecked(False)
        self._volume_btn.setText("🔊")

    def _get_active_pid(self, process_id: str) -> Optional[int]:
        """process_id에 대해 현재 활성 PID를 반환합니다. 실행 중이 아니면 None."""
        pm_entry = self.process_monitor.active_monitored_processes.get(process_id)
        if pm_entry:
            return pm_entry.get('pid')
        return None

    def _sync_default_volume_state(self, process: ManagedProcess, pid: Optional[int]) -> None:
        """프로세스의 기본 볼륨을 시스템에 적용하거나 추적 상태를 정리합니다."""
        if not pid:
            self._volume_applied_pids.pop(process.id, None)
            self._mute_retry_tokens.pop(process.id, None)
            return

        default_volume = getattr(process, "default_volume", None)
        already_applied = self._volume_applied_pids.get(process.id) == pid
        if not already_applied and default_volume is not None:
            if audio_control.set_app_volume(pid, default_volume / 100.0):
                self._volume_applied_pids[process.id] = pid

        # default_muted 적용 (default_volume 미설정이어도 항상 적용)
        # 게임 시작 직후 오디오 세션이 없을 수 있으므로 실패 시 재시도
        process_id = process.id
        default_muted = getattr(process, "default_muted", False)
        retry_token = self._mute_retry_tokens.get(process_id, 0) + 1
        self._mute_retry_tokens[process_id] = retry_token
        if not audio_control.set_mute(pid, default_muted):
            from PyQt6.QtCore import QTimer
            remaining_delays = [1000, 3000, 5000]

            def get_current_default_muted() -> Optional[bool]:
                for managed in getattr(self.data_manager, "managed_processes", []):
                    if managed.id == process_id:
                        return getattr(managed, "default_muted", False)
                return None

            def try_set_mute(
                target_pid: int,
                muted: bool,
                delays: list[int],
                token: int,
            ) -> None:
                if self._mute_retry_tokens.get(process_id) != token:
                    return
                if self._get_active_pid(process_id) != target_pid:
                    return
                current_muted = get_current_default_muted()
                if current_muted is None or current_muted != muted:
                    return
                if audio_control.set_mute(target_pid, muted) or not delays:
                    return
                next_delay = delays[0]
                QTimer.singleShot(
                    next_delay,
                    lambda p=target_pid, m=muted, d=delays[1:], t=token: try_set_mute(p, m, d, t),
                )

            try_set_mute(pid, default_muted, remaining_delays, retry_token)

    # ── 스크린샷 ────────────────────────────────────────────────

    def _get_screenshot_target_hwnd(self) -> Optional[int]:
        """포커스된 등록 게임 창의 HWND 반환. 등록 게임이 아니면 None."""
        import ctypes
        import ctypes.wintypes as wt
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid_c = wt.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_c))
        pid = pid_c.value
        active_pids = set()
        if self.process_monitor:
            active_snapshot = dict(self.process_monitor.active_monitored_processes)
            active_pids = {
                entry.get('pid')
                for entry in active_snapshot.values()
                if entry.get('pid')
            }
        return hwnd if pid in active_pids else None

    def _get_screenshot_game_name(self) -> str:
        """포커스된 등록 게임의 이름 반환. 없으면 빈 문자열."""
        import ctypes
        import ctypes.wintypes as wt
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd or not self.process_monitor:
            return ""
        pid_c = wt.DWORD()
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_c))
        pid = pid_c.value
        active = dict(self.process_monitor.active_monitored_processes)
        managed_map = {p.id: p for p in getattr(self.data_manager, 'managed_processes', [])}
        for proc_id, entry in active.items():
            if entry.get('pid') == pid:
                proc = managed_map.get(proc_id)
                if proc:
                    return proc.name
        return ""

    def _apply_screenshot_settings(self, *, sync_runtime: bool = True) -> None:
        """GlobalSettings의 스크린샷 설정을 ScreenshotManager에 반영합니다."""
        gs = getattr(self.data_manager, 'global_settings', None)
        if gs is None or self._screenshot_manager is None:
            return
        save_dir = getattr(gs, 'screenshot_save_dir', '') or None
        self._screenshot_manager.set_save_dir(save_dir)
        self._screenshot_manager.set_capture_mode(
            getattr(gs, 'screenshot_capture_mode', 'fullscreen')
        )
        self._screenshot_manager.set_long_press_threshold(
            getattr(gs, 'recording_hold_threshold_ms', 800)
        )
        self._screenshot_manager.set_trigger_vk(
            getattr(gs, 'screenshot_trigger_vk', 0xB2)
        )
        if getattr(gs, 'screenshot_disable_gamebar', False):
            self._set_gamebar_capture(False)
        else:
            self._restore_gamebar_setting()
        if sync_runtime:
            self._sync_screenshot_manager_state(gs)

    def _apply_recording_settings(self) -> None:
        """GlobalSettings의 녹화 설정을 RecordingManager에 반영합니다."""
        gs = getattr(self.data_manager, 'global_settings', None)
        if gs is None or not hasattr(self, '_recording_manager'):
            return
        self._recording_manager.apply_settings(gs)

    def _on_recording_state_changed(self, state: str) -> None:
        """RecordingManager 상태 변경 콜백 — 백그라운드 스레드에서 호출될 수 있음.
        pyqtSignal을 통해 메인 스레드로 안전하게 릴레이."""
        self._recording_state_sig.emit(state)

    def _dispatch_recording_state_to_sidebar(self, state: str) -> None:
        """메인 스레드에서 실행되는 실제 사이드바 업데이트."""
        if hasattr(self, '_sidebar_controller'):
            self._sidebar_controller.dispatch_recording_state(state)

    def _on_gamepad_long_press(self) -> None:
        """게임패드 롱프레스(800ms+) 처리 — 훅 스레드에서 호출될 수 있음.

        녹화 중이면 즉시 중지, idle이면 카운트다운 후 시작.
        """
        if not hasattr(self, '_recording_manager'):
            return
        state = self._recording_manager.get_state()
        if state == "recording":
            self._recording_manager.stop_recording()
        elif state == "idle":
            self._gamepad_countdown_sig.emit()  # 메인 스레드로 릴레이
        else:
            # obs_offline / connecting: 기존 동작 (자동 연결 + 녹화)
            self._recording_manager.on_recording_toggle()

    def _show_countdown_then_record(self) -> None:
        """3초 카운트다운 오버레이를 표시하고 완료 시 녹화를 시작합니다.
        반드시 메인 스레드에서 호출해야 합니다.
        """
        if not hasattr(self, '_recording_manager'):
            return
        from src.gui.countdown_overlay import CountdownOverlay
        from PyQt6.QtWidgets import QApplication
        screen = QApplication.primaryScreen()
        self._countdown_overlay = CountdownOverlay(
            on_complete=self._recording_manager.start_recording,
            screen=screen,
        )
        self._countdown_overlay.start()

    def _get_recording_output_dir(self) -> str:
        """OBS 녹화 출력 폴더 경로를 반환합니다."""
        gs = getattr(self.data_manager, 'global_settings', None)
        if gs is None or not getattr(gs, 'obs_watch_output_dir', True):
            return ""
        # 수동 지정 경로 우선
        manual = getattr(gs, 'obs_recording_output_dir', '').strip()
        if manual:
            return manual
        # 없으면 OBS INI에서 자동 읽기
        try:
            from src.recording.obs_config_reader import read_obs_config
            output_dir = read_obs_config().get("output_dir", "")
        except Exception:
            output_dir = ""
        # OBS가 기본 출력 경로를 사용 중이면 INI에 기록되지 않으므로 fallback
        if not output_dir:
            import os
            output_dir = os.path.join(os.path.expanduser("~"), "Videos")
        return output_dir

    def _start_screenshot_manager(self) -> None:
        """현재 설정 기준으로 스크린샷 매니저 상태를 동기화합니다."""
        if self._screenshot_manager is None:
            return
        self._apply_screenshot_settings(sync_runtime=True)

    def _sync_screenshot_manager_state(self, gs: Optional[GlobalSettings] = None) -> None:
        """스크린샷 훅의 런타임 시작/중지 상태를 현재 설정과 맞춥니다."""
        if self._screenshot_manager is None:
            return
        if gs is None:
            gs = getattr(self.data_manager, 'global_settings', None)
        if gs is None:
            self._screenshot_manager.stop()
            return
        should_run = bool(
            getattr(gs, 'screenshot_enabled', True)
            and getattr(gs, 'screenshot_gamepad_trigger', True)
        )
        if should_run:
            self._screenshot_manager.start()
        else:
            self._screenshot_manager.stop()

    def _on_screenshot_captured(self, path: str) -> None:
        """캡처 완료 콜백 — 사이드바 썸네일 갱신."""
        logger.info("스크린샷 저장됨: %s", path)
        if self._sidebar_controller is not None:
            self._sidebar_controller.notify_screenshot_captured(path)

    _gamebar_original_value: Optional[int] = None
    _gamebar_original_value_key = "system/gamebar_original_value"

    def _persist_gamebar_original_value(self) -> None:
        """Game Bar 원래 값을 QSettings에 저장하거나 제거합니다."""
        if self._gamebar_original_value is None:
            self._settings.remove(self._gamebar_original_value_key)
        else:
            self._settings.setValue(self._gamebar_original_value_key, self._gamebar_original_value)
        self._settings.sync()

    def _load_persisted_gamebar_original_value(self) -> Optional[int]:
        """QSettings에 저장된 Game Bar 원래 값을 로드합니다."""
        value = self._settings.value(self._gamebar_original_value_key)
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            logger.warning("저장된 Game Bar 원래 값이 잘못되었습니다: %r", value)
            self._settings.remove(self._gamebar_original_value_key)
            self._settings.sync()
            return None

    def _recover_gamebar_setting_if_needed(self) -> None:
        """이전 비정상 종료로 남은 Game Bar 설정이 있으면 앱 시작 시 복원합니다."""
        if sys.platform != "win32":
            return
        if self._gamebar_original_value is not None:
            return
        persisted_value = self._load_persisted_gamebar_original_value()
        if persisted_value is None:
            return
        self._gamebar_original_value = persisted_value
        logger.info("이전 세션의 Game Bar 설정을 복원합니다.")
        self._restore_gamebar_setting()

    def _set_gamebar_capture(self, enabled: bool) -> None:
        """Game Bar 스크린샷 캡처 활성화 여부를 레지스트리로 제어합니다."""
        if sys.platform != "win32":
            return
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\GameDVR"
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ | winreg.KEY_WRITE
            ) as key:
                if self._gamebar_original_value is None:
                    try:
                        val, _ = winreg.QueryValueEx(key, "AppCaptureEnabled")
                        self._gamebar_original_value = int(val)
                    except FileNotFoundError:
                        self._gamebar_original_value = 1
                    self._persist_gamebar_original_value()
                winreg.SetValueEx(key, "AppCaptureEnabled", 0, winreg.REG_DWORD,
                                  1 if enabled else 0)
            logger.info("Game Bar AppCaptureEnabled → %d", 1 if enabled else 0)
        except Exception as exc:
            logger.warning("Game Bar 레지스트리 설정 실패: %s", exc, exc_info=True)

    def _restore_gamebar_setting(self) -> None:
        """Game Bar 설정을 원래 값으로 복원합니다."""
        if sys.platform != "win32":
            return
        if self._gamebar_original_value is None:
            self._gamebar_original_value = self._load_persisted_gamebar_original_value()
            if self._gamebar_original_value is None:
                return
        try:
            import winreg
            key_path = r"Software\Microsoft\Windows\CurrentVersion\GameDVR"
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE
            ) as key:
                winreg.SetValueEx(key, "AppCaptureEnabled", 0, winreg.REG_DWORD,
                                  self._gamebar_original_value)
            logger.info("Game Bar AppCaptureEnabled 복원 → %d", self._gamebar_original_value)
            self._gamebar_original_value = None
            self._persist_gamebar_original_value()
        except Exception as exc:
            logger.warning("Game Bar 레지스트리 복원 실패: %s", exc, exc_info=True)

    # ─────────────────────────────

    def _calculate_progress_percentage(self, process: ManagedProcess, current_dt: datetime.datetime) -> tuple[float, str]:
        """마지막 실행 시각을 기준으로 다음 접속까지의 진행률을 계산합니다.

        호요버스 게임의 경우 스태미나 기반으로 계산합니다.
        """
        # 스태미나 자동 추적이 활성화된 경우 스태미나 기반 계산
        stamina_tracking_enabled = getattr(process, 'stamina_tracking_enabled', False)
        hoyolab_game_id = getattr(process, 'hoyolab_game_id', None)

        if stamina_tracking_enabled and hoyolab_game_id:
            stamina_info = process.get_predicted_stamina()
            if stamina_info:
                predicted, max_stamina = stamina_info
                percentage = (predicted / max_stamina) * 100 if max_stamina > 0 else 0
                # 특수 포맷: "STAMINA:game_id:current/max" (아이콘 표시용)
                result = f"STAMINA:{hoyolab_game_id}:{predicted}/{max_stamina}"
                return percentage, result

        # 기존 시간 기반 계산
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
            logger.error(f"진행률 계산 중 오류: {e}")
            return 0.0, "계산 오류"


    def _create_progress_bar_widget(self, process, percentage: float, time_str: str) -> QWidget:
        """진행률을 표시하는 QProgressBar 위젯을 생성합니다."""
        if percentage == 0.0 and not time_str.startswith("STAMINA:"):
            # 기록이 없는 경우 - 동일한 레이아웃 구조 유지
            container = QWidget()
            layout = QHBoxLayout(container)
            layout.setContentsMargins(2, 0, 2, 0)
            layout.setSpacing(4)

            # 프리셋 아이콘 표시
            icon_label = QLabel()
            icon_path = self._get_stamina_icon_path(process)

            if icon_path and os.path.exists(icon_path):
                pixmap = QPixmap(icon_path).scaled(16, 16, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                icon_label.setPixmap(pixmap)
                icon_label.setFixedSize(18, 18)
            else:
                # 아이콘이 없으면 공간 확보
                icon_label.setFixedSize(18, 18)
            layout.addWidget(icon_label)

            # 텍스트 라벨
            text_label = QLabel(time_str)
            text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(text_label, 1)  # stretch factor 1로 남은 공간 채움

            return container

        # 스태미나 형식 감지: "STAMINA:game_id:current/max"
        if time_str.startswith("STAMINA:"):
            try:
                parts = time_str.split(":")
                if len(parts) >= 3:
                    game_id = parts[1]
                    stamina_text = parts[2]

                    # 아이콘 + Progress Bar를 포함하는 컨테이너 위젯 생성
                    container = QWidget()
                    layout = QHBoxLayout(container)
                    layout.setContentsMargins(2, 0, 2, 0)
                    layout.setSpacing(4)

                    # 아이콘 라벨
                    icon_label = QLabel()
                    icon_path = self._get_stamina_icon_path(process)

                    if icon_path and os.path.exists(icon_path):
                        pixmap = QPixmap(icon_path).scaled(16, 16, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                        icon_label.setPixmap(pixmap)
                        icon_label.setFixedSize(18, 18)
                    else:
                        # 아이콘이 없어도 공간 확보
                        icon_label.setFixedSize(18, 18)
                    layout.addWidget(icon_label)

                    # Progress Bar
                    progress_bar = self._create_styled_progress_bar(percentage, stamina_text)
                    layout.addWidget(progress_bar, 1)

                    return container
            except Exception as e:
                logger.error(f"스태미나 위젯 생성 오류: {e}", exc_info=True)

        # 일반 시간 기반 Progress Bar (프리셋 아이콘 포함)
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(2, 0, 2, 0)
        layout.setSpacing(4)

        # 프리셋 아이콘 표시
        icon_label = QLabel()
        icon_path = self._get_stamina_icon_path(process)

        if icon_path and os.path.exists(icon_path):
            pixmap = QPixmap(icon_path).scaled(16, 16, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            icon_label.setPixmap(pixmap)
            icon_label.setFixedSize(18, 18)
        else:
            # 아이콘이 없으면 공간 확보
            icon_label.setFixedSize(18, 18)
        layout.addWidget(icon_label)

        # Progress Bar
        progress_bar = self._create_styled_progress_bar(percentage, f"{percentage:.1f}%")
        layout.addWidget(progress_bar, 1)  # stretch factor 1로 남은 공간 채움

        return container

    def _get_stamina_icon_path(self, process) -> Optional[str]:
        """프로세스에 해당하는 스태미나/재화 아이콘 경로 반환 (프리셋 기반)"""
        from src.utils.icon_helper import resolve_preset_icon_path

        if not process.user_preset_id:
            return None

        preset = self.preset_manager.get_preset_by_id(process.user_preset_id)
        if not preset:
            return None

        icon_path = preset.get("icon_path")
        icon_type = preset.get("icon_type")

        # icon_path가 없으면 None 반환 (공란 표시)
        if not icon_path:
            return None

        return resolve_preset_icon_path(icon_path, icon_type)

    def _create_styled_progress_bar(self, percentage: float, format_text: str) -> QProgressBar:
        """스타일이 적용된 QProgressBar 생성"""
        progress_bar = QProgressBar()
        progress_bar.setValue(self._progress_bar_value(percentage))
        progress_bar.setMaximum(self._PROGRESS_BAR_MAX)
        progress_bar.setMinimum(0)

        # 높이 설정 (행 높이에 맞게 자동 조절)
        progress_bar.setMinimumHeight(20)

        # 텍스트 표시 설정
        progress_bar.setTextVisible(True)
        progress_bar.setFormat(format_text)
        progress_bar.setProperty("color_bucket", self._progress_color_bucket(percentage))
        self._apply_progress_bar_style(progress_bar, percentage)

        return progress_bar

    def _progress_bar_value(self, percentage: float) -> int:
        """진행률 백분율을 ProgressBar 내부 값으로 변환합니다."""
        clamped = max(0.0, min(percentage, 100.0))
        return round(clamped * self._PROGRESS_BAR_SCALE)

    def _progress_color_bucket(self, percentage: float) -> int:
        """진행률에 따른 색상 구간을 반환합니다."""
        if percentage >= 100:
            return 3
        if percentage >= 80:
            return 2
        if percentage >= 50:
            return 1
        return 0

    def _progress_bar_stylesheet(self, chunk_color: str) -> str:
        """공통 ProgressBar 스타일시트를 생성합니다."""
        return f"""
            QProgressBar {{
                border: 1px solid #404040;
                border-radius: 2px;
                text-align: center;
                background-color: #2d2d2d;
                color: white;
                font-weight: bold;
            }}
            QProgressBar::chunk {{
                background-color: {chunk_color};
                border-radius: 1px;
            }}
        """

    def _apply_progress_bar_style(self, progress_bar: QProgressBar, percentage: float) -> None:
        """진행률 구간에 맞는 스타일을 ProgressBar에 적용합니다."""
        if percentage >= 100:
            chunk_color = "#ff4444"
        elif percentage >= 80:
            chunk_color = "#ff8800"
        elif percentage >= 50:
            chunk_color = "#ffcc00"
        else:
            chunk_color = "#44cc44"
        progress_bar.setStyleSheet(self._progress_bar_stylesheet(chunk_color))

    def _refresh_progress_bars(self):
        """프로그레스 바들을 실시간으로 갱신합니다.

        최적화:
        - 값이 실제로 변경되었을 때만 업데이트
        - 스타일시트는 색상 구간 변경 시에만 적용
        - 컨테이너 내부의 Progress Bar 처리
        """
        start_time = time.time()
        now_dt = datetime.datetime.now()
        processes = self.data_manager.managed_processes
        updated_count = 0

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

            # 컨테이너 위젯인 경우 내부 Progress Bar 찾기 (Task #2에서 변경된 구조)
            progress_bar = None
            if isinstance(current_widget, QWidget):
                # 컨테이너 내부에서 QProgressBar 찾기
                for child in current_widget.findChildren(QProgressBar):
                    progress_bar = child
                    break
            elif isinstance(current_widget, QProgressBar):
                # 직접 QProgressBar인 경우 (하위 호환)
                progress_bar = current_widget

            # Progress Bar 업데이트
            expects_progress_widget = not (percentage == 0.0 and not time_str.startswith("STAMINA:"))
            if expects_progress_widget != (progress_bar is not None):
                self.process_table.setCellWidget(
                    row,
                    self.COL_LAST_PLAYED,
                    self._create_progress_bar_widget(process, percentage, time_str),
                )
                updated_count += 1
                continue

            if progress_bar:
                new_value = self._progress_bar_value(percentage)
                new_format = self._get_progress_bar_format(percentage, time_str)
                new_bucket = self._progress_color_bucket(percentage)

                if progress_bar.value() != new_value:
                    progress_bar.setValue(new_value)
                    updated_count += 1

                if progress_bar.format() != new_format:
                    progress_bar.setFormat(new_format)
                    updated_count += 1

                if progress_bar.property("color_bucket") != new_bucket:
                    progress_bar.setProperty("color_bucket", new_bucket)
                    self._apply_progress_bar_style(progress_bar, percentage)
                    updated_count += 1

            # QLabel 업데이트 (컨테이너 내부의 라벨 - "기록 없음" 표시)
            else:
                for child in current_widget.findChildren(QLabel):
                    if child.text() != time_str:
                        child.setText(time_str)
                        updated_count += 1
                    break

        # 업데이트가 있었으면 viewport 강제 갱신 (절전 복귀 후 화면 그리기 문제 대응)
        if updated_count > 0:
            if self.process_table.viewport():
                self.process_table.viewport().update()

        # 타이머 실행 시간 로깅 (100ms 이상 걸리면 경고)
        execution_time = (time.time() - start_time) * 1000
        if execution_time > 100:
            logger.warning(f"_refresh_progress_bars 실행 시간 초과: {execution_time:.1f}ms (업데이트: {updated_count}개)")

    def _get_progress_bar_format(self, percentage: float, time_str: str) -> str:
        """ProgressBar 표시 문자열을 반환합니다."""
        if time_str.startswith("STAMINA:"):
            try:
                parts = time_str.split(":")
                if len(parts) >= 3:
                    return parts[2]
            except (AttributeError, IndexError, TypeError, ValueError) as exc:
                logger.debug(
                    "ProgressBar 포맷 파싱 실패: time_str=%r, percentage=%.1f, error=%s",
                    time_str,
                    percentage,
                    exc,
                )
        return f"{percentage:.1f}%"

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
