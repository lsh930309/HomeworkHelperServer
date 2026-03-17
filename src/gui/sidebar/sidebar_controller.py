"""사이드바 컨트롤러.

EdgeTriggerWindow 와 SidebarWidget 의 생명주기를 조율합니다.
게임 실행 시 activate_for_game() 으로 트리거를 활성화하고,
게임 종료 시 deactivate() 로 사이드바와 트리거를 비활성화합니다.
"""
import logging
from typing import Optional

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

        # 디버그 토글 버튼
        self._sidebar_controller.toggle_debug_sidebar()
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

        # 지연 생성 (화면 정보가 필요하므로 QApplication 초기화 이후)
        self._trigger: Optional[EdgeTriggerWindow] = None
        self._sidebar: Optional[SidebarWidget] = None
        self._debug_mode = False  # 디버그 강제 표시 여부

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
        self._debug_mode = False

        if self._trigger is not None:
            self._trigger.stop()

        if self._sidebar is not None:
            self._sidebar.slide_out()

        logger.debug("SidebarController 비활성화")

    def toggle_debug_sidebar(self) -> None:
        """디버그용 사이드바 토글 (게임 실행 없이 사이드바를 열거나 닫습니다)."""
        self._ensure_widgets_created()

        if self._sidebar is None:
            return

        if self._sidebar._is_shown:
            self._sidebar.slide_out()
            self._debug_mode = False
        else:
            # 더미 프로세스 없이 빈 상태로 표시
            self._sidebar.update_process(self._active_process, self._active_pid, self._game_start_timestamp)
            self._sidebar.slide_in()
            self._debug_mode = True

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

    # ------------------------------------------------------------------
    # 내부 메서드
    # ------------------------------------------------------------------

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
        auto_hide_sec = getattr(gs, 'sidebar_auto_hide_sec', 3) if gs else 3
        auto_hide_ms = int(auto_hide_sec * 1000)

        if self._sidebar is None:
            self._sidebar = SidebarWidget(
                data_manager=self._data_manager,
                auto_hide_ms=auto_hide_ms,
                screen=screen,
            )
        else:
            # 설정 갱신
            self._sidebar.update_auto_hide_ms(auto_hide_ms)

        if self._trigger is None:
            self._trigger = EdgeTriggerWindow(
                trigger_callback=self._on_edge_triggered,
                trigger_y_start=trigger_y_start,
                trigger_y_end=trigger_y_end,
                cooldown_sec=1.0,
                screen=screen,
            )
        else:
            self._trigger.update_settings(trigger_y_start, trigger_y_end, 1.0)

    def _on_edge_triggered(self) -> None:
        """EdgeTriggerWindow 가 커서 진입을 감지했을 때 호출됩니다."""
        if self._sidebar is None:
            return
        self._sidebar.slide_in()
        logger.debug("엣지 트리거 → 사이드바 슬라이드인")
