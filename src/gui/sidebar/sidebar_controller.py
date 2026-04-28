"""사이드바 컨트롤러.

EdgeTriggerWindow 와 SidebarWidget 의 생명주기를 조율합니다.
게임 실행 시 activate_for_game() 으로 트리거를 활성화하고,
게임 종료 시 deactivate() 로 사이드바와 트리거를 비활성화합니다.
"""
import logging
from typing import Callable, Optional

from PyQt6.QtWidgets import QApplication, QWidget
from PyQt6.QtGui import QScreen

from src.data.data_models import ManagedProcess
from src.gui.sidebar.edge_trigger_window import EdgeTriggerWindow
from src.gui.sidebar.sidebar_widget import SidebarWidget

logger = logging.getLogger(__name__)


class SidebarController:
    """EdgeTriggerWindow + SidebarWidget 생명주기 관리자.

    MainWindow.__init__ 에서 생성하고 게임 이벤트에 따라 호출합니다.

    Usage::

        # MainWindow.__init__
        self._sidebar_controller = SidebarController(self.data_manager, self)

        # 게임 실행 감지 시
        self._sidebar_controller.activate_for_game(running_process)

        # 게임 종료 감지 시
        self._sidebar_controller.deactivate()

        # 앱 종료 시
        self._sidebar_controller.cleanup()

    """

    def __init__(self, data_manager, main_window: Optional[QWidget] = None):
        """SidebarController 를 초기화합니다.

        Args:
            data_manager: ApiClient 인스턴스.
            main_window: 부모 윈도우 (스크린 정보 참조용).
        """
        self._data_manager = data_manager
        self._main_window = main_window
        self._active_process: Optional[ManagedProcess] = None
        self._active_pid: Optional[int] = None
        self._game_start_timestamp: Optional[float] = None
        self._on_stop_recording: Optional[Callable[[], None]] = None
        self._on_reconnect_recording: Optional[Callable[[], None]] = None
        self._on_start_recording: Optional[Callable[[], None]] = None
        self._get_recording_error: Optional[Callable[[], str]] = None
        self._get_recording_elapsed_sec: Optional[Callable[[], int]] = None
        self._get_recording_output_dir: Optional[Callable[[], str]] = None

        # 지연 생성 (화면 정보가 필요하므로 QApplication 초기화 이후)
        self._trigger: Optional[EdgeTriggerWindow] = None
        self._sidebar: Optional[SidebarWidget] = None

        # 디스플레이 변경 감지 (가상 디스플레이 전환 등)
        app = QApplication.instance()
        if app is not None:
            app.primaryScreenChanged.connect(self._on_primary_screen_changed)
            app.screenAdded.connect(self._on_screen_config_changed)
            app.screenRemoved.connect(self._on_screen_config_changed)

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    def activate_for_game(
        self,
        process: ManagedProcess,
        pid: Optional[int] = None,
        game_start_timestamp: Optional[float] = None,
    ) -> None:
        """게임 실행 시 사이드바 트리거를 활성화합니다.

        Args:
            process: 실행 중인 ManagedProcess.
            pid: 실행 중인 프로세스 PID (볼륨 제어용).
            game_start_timestamp: 게임 시작 Unix 타임스탬프 (플레이 시간용).
        """
        if not self._is_sidebar_enabled():
            logger.debug("사이드바 비활성화 설정 — activate_for_game 무시")
            return

        import time
        self._active_process = process
        self._active_pid = pid
        self._game_start_timestamp = game_start_timestamp or time.time()

        self._ensure_widgets_created()

        # 위젯에 프로세스 정보 전달
        if self._sidebar is not None:
            self._sidebar.update_process(
                self._active_process,
                self._active_pid,
                self._game_start_timestamp,
            )

        # 트리거 시작
        if self._trigger is not None:
            self._trigger.start()

        logger.debug("SidebarController 활성화: %s (pid=%s)", process.name, pid)

    def deactivate(self) -> None:
        """게임 종료 시 사이드바와 트리거를 비활성화합니다."""
        self._active_process = None
        self._active_pid = None
        self._game_start_timestamp = None

        if self._trigger is not None:
            self._trigger.stop()

        if self._sidebar is not None:
            self._sidebar.slide_out()

        logger.debug("SidebarController 비활성화")

    def cleanup(self) -> None:
        """앱 종료 시 모든 리소스를 정리합니다."""
        if self._trigger is not None:
            self._trigger.stop()
            try:
                self._trigger.close()
            except RuntimeError:
                pass
            self._trigger = None

        if self._sidebar is not None:
            self._sidebar.cleanup()
            try:
                self._sidebar.close()
            except RuntimeError:
                pass
            self._sidebar = None

        logger.debug("SidebarController cleanup 완료")

    def set_recording_callbacks(
        self,
        *,
        on_stop: Optional[Callable[[], None]] = None,
        on_reconnect: Optional[Callable[[], None]] = None,
        on_start: Optional[Callable[[], None]] = None,
        get_last_error: Optional[Callable[[], str]] = None,
        get_elapsed_sec: Optional[Callable[[], int]] = None,
        get_output_dir: Optional[Callable[[], str]] = None,
    ) -> None:
        """사이드바 녹화 제어 콜백을 주입합니다."""
        if on_stop is not None:
            self._on_stop_recording = on_stop
        if on_reconnect is not None:
            self._on_reconnect_recording = on_reconnect
        if on_start is not None:
            self._on_start_recording = on_start
        if get_last_error is not None:
            self._get_recording_error = get_last_error
        if get_elapsed_sec is not None:
            self._get_recording_elapsed_sec = get_elapsed_sec
        if get_output_dir is not None:
            self._get_recording_output_dir = get_output_dir
        if self._sidebar is not None:
            self._sidebar.set_on_stop_recording(self._on_stop_recording)
            self._sidebar.set_on_reconnect_recording(self._on_reconnect_recording)
            self._sidebar.set_on_start_recording(self._on_start_recording)
            self._sidebar.set_recording_error_provider(self._get_recording_error)
            self._sidebar.set_recording_elapsed_provider(self._get_recording_elapsed_sec)
            if self._get_recording_output_dir:
                self._sidebar.set_recording_output_dir(self._get_recording_output_dir())

    def dispatch_recording_state(self, state: str) -> None:
        """사이드바에 녹화 상태를 전달합니다."""
        if self._sidebar is not None:
            self._sidebar.on_recording_state_changed(state)

    def notify_screenshot_captured(self, path: str) -> None:
        """사이드바에 새 스크린샷 캡처를 전달합니다."""
        if self._sidebar is not None:
            self._sidebar.on_screenshot_captured(path)

    # ------------------------------------------------------------------
    # 내부 메서드
    # ------------------------------------------------------------------

    def apply_settings(self, settings) -> None:
        """사이드바 설정을 런타임에 반영합니다."""
        if self._sidebar is not None:
            auto_hide_ms = getattr(settings, 'sidebar_auto_hide_ms', 3000)
            self._sidebar.update_auto_hide_ms(auto_hide_ms)
            self._sidebar.apply_visual_settings()
            self._sidebar.refresh_content()
            # sidebar_enabled=False 로 변경 시 즉시 숨김
            if not getattr(settings, 'sidebar_enabled', True) and self._sidebar._is_shown:
                self._sidebar.slide_out()
        if self._trigger is not None:
            trigger_y_start = getattr(settings, 'sidebar_trigger_y_start', 0.1)
            trigger_y_end = getattr(settings, 'sidebar_trigger_y_end', 0.9)
            edge_width_px = getattr(settings, 'sidebar_edge_width_px', 2)
            self._trigger.update_settings(trigger_y_start, trigger_y_end, 1.0, edge_width_px)

    def _is_sidebar_enabled(self) -> bool:
        """GlobalSettings.sidebar_enabled 를 확인합니다."""
        if self._data_manager is None:
            return True
        gs = getattr(self._data_manager, 'global_settings', None)
        if gs is None:
            return True
        return getattr(gs, 'sidebar_enabled', True)

    def _get_screen(self) -> Optional[QScreen]:
        """메인 윈도우 또는 기본 스크린을 반환합니다."""
        if self._main_window is not None:
            screen = self._main_window.screen()
            if screen is not None:
                return screen
        return QApplication.primaryScreen()

    def _get_settings(self):
        """GlobalSettings 를 반환합니다. 없으면 None."""
        if self._data_manager is None:
            return None
        return getattr(self._data_manager, 'global_settings', None)

    def _ensure_widgets_created(self) -> None:
        """위젯이 아직 생성되지 않았다면 생성합니다."""
        gs = self._get_settings()
        screen = self._get_screen()

        trigger_y_start = getattr(gs, 'sidebar_trigger_y_start', 0.1) if gs else 0.1
        trigger_y_end = getattr(gs, 'sidebar_trigger_y_end', 0.9) if gs else 0.9
        auto_hide_ms = int(getattr(gs, 'sidebar_auto_hide_ms', 3000) if gs else 3000)
        edge_width_px = int(getattr(gs, 'sidebar_edge_width_px', 2) if gs else 2)

        if self._sidebar is None:
            self._sidebar = SidebarWidget(
                data_manager=self._data_manager,
                auto_hide_ms=auto_hide_ms,
                screen=screen,
                stop_recording=self._on_stop_recording,
                reconnect_recording=self._on_reconnect_recording,
                get_recording_error=self._get_recording_error,
                get_recording_elapsed=self._get_recording_elapsed_sec,
            )
            self._sidebar.set_on_start_recording(self._on_start_recording)
            if self._get_recording_output_dir:
                self._sidebar.set_recording_output_dir(self._get_recording_output_dir())
        else:
            # 설정 갱신
            self._sidebar.update_auto_hide_ms(auto_hide_ms)

        if self._trigger is None:
            self._trigger = EdgeTriggerWindow(
                trigger_callback=self._on_edge_triggered,
                trigger_y_start=trigger_y_start,
                trigger_y_end=trigger_y_end,
                cooldown_sec=1.0,
                trigger_width_px=edge_width_px,
                screen=screen,
            )
        else:
            self._trigger.update_settings(trigger_y_start, trigger_y_end, 1.0, edge_width_px)

    def _on_edge_triggered(self) -> None:
        """EdgeTriggerWindow 가 커서 진입을 감지했을 때 호출됩니다."""
        if self._sidebar is None:
            return
        self._sidebar.slide_in()
        logger.debug("엣지 트리거 → 사이드바 슬라이드인")

    def _on_primary_screen_changed(self, screen: "QScreen") -> None:
        """주 화면이 변경되었을 때 위젯을 재배치합니다."""
        logger.debug("주 화면 변경 감지 → 사이드바 위젯 재배치: %s", screen.name() if screen else "None")
        new_screen = screen or QApplication.primaryScreen()
        if self._trigger is not None:
            self._trigger.reposition(new_screen)
        if self._sidebar is not None:
            self._sidebar.update_screen(new_screen)

    def _on_screen_config_changed(self, screen: "QScreen") -> None:
        """화면이 추가/제거되었을 때 위젯을 재배치합니다."""
        logger.debug("화면 구성 변경 감지 → 사이드바 위젯 재배치")
        new_screen = self._get_screen()
        if self._trigger is not None:
            self._trigger.reposition(new_screen)
        if self._sidebar is not None:
            self._sidebar.update_screen(new_screen)
