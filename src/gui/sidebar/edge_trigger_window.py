"""화면 우측 가장자리 사이드바 손잡이 창.

활성 게임이 감지되면 화면 우측 끝에 클릭 가능한 손잡이를 항상 표시합니다.
손잡이를 클릭했을 때만 콜백을 호출하며, 쿨다운(cooldown_sec) 동안은
재트리거를 방지합니다.
"""
import logging
from typing import Callable, Optional

from PyQt6.QtCore import Qt, QTimer, QRect
from PyQt6.QtGui import QScreen
from PyQt6.QtWidgets import QApplication, QWidget

logger = logging.getLogger(__name__)

_POLL_INTERVAL_MS = 100   # 손잡이 유지 폴링 간격 (ms)
_HANDLE_WIDTH = 18
_HANDLE_MIN_HEIGHT = 96
_HANDLE_MAX_HEIGHT = 160


class EdgeTriggerWindow(QWidget):
    """화면 우측 가장자리에 붙어있는 클릭 손잡이 창.

    게임이 전체화면으로 실행 중일 때도 WS_EX_TOPMOST 로 손잡이를 표시합니다.
    """

    def __init__(
        self,
        trigger_callback: Callable[[], None],
        trigger_y_start: float = 0.1,
        trigger_y_end: float = 0.9,
        cooldown_sec: float = 1.0,
        trigger_width_px: int = 2,
        screen: Optional[QScreen] = None,
        parent: Optional[QWidget] = None,
    ):
        """EdgeTriggerWindow 를 초기화합니다.

        Args:
            trigger_callback: 손잡이를 클릭했을 때 호출할 함수.
            trigger_y_start: 손잡이 배치 영역 시작 Y 비율 (0.0 ~ 1.0).
            trigger_y_end: 손잡이 배치 영역 종료 Y 비율 (0.0 ~ 1.0).
            cooldown_sec: 트리거 후 재발동 방지 시간 (초).
            trigger_width_px: 비활성 상태의 edge overlay 너비 (px).
            screen: 배치할 화면. None이면 주 화면을 사용합니다.
            parent: 부모 위젯.
        """
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self._trigger_callback = trigger_callback
        _s = max(0.0, min(1.0, trigger_y_start))
        _e = max(0.0, min(1.0, trigger_y_end))
        self._trigger_y_start, self._trigger_y_end = min(_s, _e), max(_s, _e)
        self._cooldown_ms = int(cooldown_sec * 1000)
        self._trigger_width_px = max(1, trigger_width_px)
        self._in_cooldown = False
        self._handle_visible = False

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_hidden_handle_style()

        # 배치할 화면 결정
        self._screen = screen or QApplication.primaryScreen()
        self._reposition(self._screen)

        # 손잡이 유지 폴링 타이머
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll_cursor)
        self._handle_hide_timer = QTimer(self)
        self._handle_hide_timer.setSingleShot(True)
        self._handle_hide_timer.timeout.connect(self._hide_handle)

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """항상 보이는 손잡이를 표시하고 유지 폴링을 시작합니다."""
        self._in_cooldown = False
        self._show_handle()
        self._poll_timer.start()
        logger.debug("EdgeTriggerWindow 시작됨")

    def stop(self) -> None:
        """손잡이 유지 폴링을 중지하고 창을 숨깁니다."""
        self._poll_timer.stop()
        self._handle_hide_timer.stop()
        self.hide()
        self._in_cooldown = False
        self._handle_visible = False
        self._apply_hidden_handle_style()
        logger.debug("EdgeTriggerWindow 중지됨")

    def update_settings(
        self,
        trigger_y_start: float,
        trigger_y_end: float,
        cooldown_sec: float,
        trigger_width_px: int = 2,
    ) -> None:
        """손잡이 설정을 런타임에 갱신합니다."""
        _s = max(0.0, min(1.0, trigger_y_start))
        _e = max(0.0, min(1.0, trigger_y_end))
        self._trigger_y_start, self._trigger_y_end = min(_s, _e), max(_s, _e)
        self._cooldown_ms = int(cooldown_sec * 1000)
        self._trigger_width_px = max(1, trigger_width_px)
        self._reposition(self._screen if hasattr(self, '_screen') else None)

    def reposition(self, screen: Optional[QScreen]) -> None:
        """화면 변경 시 손잡이 창을 새 화면의 우측 끝으로 재배치합니다."""
        self._screen = screen
        self._reposition(screen)
        logger.debug("EdgeTriggerWindow 재배치: %s", screen.name() if screen else "None")

    # ------------------------------------------------------------------
    # 내부 메서드
    # ------------------------------------------------------------------

    def _reposition(self, screen: Optional[QScreen]) -> None:
        """창을 지정된 화면의 우측 끝에 배치합니다."""
        if screen is None:
            return
        self.setGeometry(self._handle_geometry(screen) if self._handle_visible else self._trigger_geometry(screen))

    def _trigger_geometry(self, screen: QScreen) -> QRect:
        geo: QRect = screen.geometry()
        trigger_x = geo.right() - self._trigger_width_px + 1
        return QRect(trigger_x, geo.top(), self._trigger_width_px, geo.height())

    def _handle_geometry(self, screen: QScreen) -> QRect:
        geo: QRect = screen.geometry()
        zone_top = geo.top() + int(geo.height() * self._trigger_y_start)
        zone_bottom = geo.top() + int(geo.height() * self._trigger_y_end)
        zone_height = max(1, zone_bottom - zone_top)
        handle_height = max(_HANDLE_MIN_HEIGHT, min(_HANDLE_MAX_HEIGHT, zone_height))
        handle_y = zone_top + max(0, (zone_height - handle_height) // 2)
        handle_x = geo.right() - _HANDLE_WIDTH + 1
        return QRect(handle_x, handle_y, _HANDLE_WIDTH, handle_height)

    def _set_transparent_for_input(self, enabled: bool) -> None:
        flag = Qt.WindowType.WindowTransparentForInput
        if bool(self.windowFlags() & flag) == enabled:
            return
        was_visible = self.isVisible()
        self.setWindowFlag(flag, enabled)
        if was_visible:
            self.show()

    def _apply_hidden_handle_style(self) -> None:
        self._set_transparent_for_input(True)
        self.setWindowOpacity(0.0)
        self.setStyleSheet("QWidget { background: transparent; border: none; }")

    def _apply_visible_handle_style(self) -> None:
        self._set_transparent_for_input(False)
        self.setWindowOpacity(0.86)
        self.setStyleSheet("""
            QWidget {
                background-color: rgba(70, 95, 135, 190);
                border: none;
                border-top-left-radius: 9px;
                border-bottom-left-radius: 9px;
            }
            QWidget:hover {
                background-color: rgba(95, 125, 175, 220);
            }
        """)
        self.setToolTip("사이드바 열기")

    def _show_handle(self) -> None:
        if self._screen is None:
            return
        self._handle_hide_timer.stop()
        self._handle_visible = True
        self._apply_visible_handle_style()
        # setWindowFlag(WindowTransparentForInput, False)는 top-level QWidget을
        # 숨겼다가 다시 show하는 경로를 타며 일부 플랫폼에서 위치를 되돌릴 수
        # 있습니다. 입력 플래그를 먼저 바꾼 뒤 최종 handle geometry를 적용해야
        # 화면 우측 가장자리에서 손잡이가 안정적으로 나타납니다.
        self.setGeometry(self._handle_geometry(self._screen))
        self.show()
        self.raise_()

    def _hide_handle(self) -> None:
        self._handle_hide_timer.stop()
        self._handle_visible = False
        self._apply_hidden_handle_style()
        if self._screen is not None:
            self.setGeometry(self._trigger_geometry(self._screen))
        if self._poll_timer.isActive():
            self.show()

    def _poll_cursor(self) -> None:
        """상시 노출 손잡이가 외부 요인으로 숨겨졌을 때 다시 표시합니다."""
        if self._handle_visible or self._screen is None:
            return
        self._show_handle()

    def _fire_trigger(self) -> None:
        """트리거 콜백을 호출하고 쿨다운을 시작합니다."""
        self._in_cooldown = True
        try:
            self._trigger_callback()
        except Exception:
            logger.exception("EdgeTriggerWindow 트리거 콜백 예외")
        QTimer.singleShot(self._cooldown_ms, self._reset_cooldown)

    def _reset_cooldown(self) -> None:
        """쿨다운을 해제합니다."""
        self._in_cooldown = False

    def enterEvent(self, event) -> None:
        super().enterEvent(event)
        if self._handle_visible:
            self._handle_hide_timer.stop()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        if self._handle_visible:
            self._handle_hide_timer.stop()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._handle_visible:
            if not self._in_cooldown:
                self._fire_trigger()
            event.accept()
            return
        super().mousePressEvent(event)
