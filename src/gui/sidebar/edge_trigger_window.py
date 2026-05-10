"""화면 우측 가장자리 사이드바 손잡이 창.

활성 게임이 감지되면 화면 우측 끝에 클릭 가능한 손잡이를 항상 표시합니다.
손잡이를 클릭했을 때만 콜백을 호출하며, 쿨다운(cooldown_sec) 동안은
재트리거를 방지합니다.
"""
import logging
from typing import Callable, Optional

from PyQt6.QtCore import Qt, QTimer, QRect, QRectF
from PyQt6.QtGui import QColor, QPainter, QPen, QScreen
from PyQt6.QtWidgets import QApplication, QWidget

logger = logging.getLogger(__name__)

_POLL_INTERVAL_MS = 100   # 손잡이 유지 폴링 간격 (ms)
_HANDLE_WIDTH = 14
_HANDLE_MIN_HEIGHT = 84
_HANDLE_MAX_HEIGHT = 132
_HANDLE_COLOR = QColor(24, 30, 44, 218)
_HANDLE_HOVER_COLOR = QColor(38, 48, 70, 235)
_HANDLE_BORDER_COLOR = QColor(145, 180, 235, 120)
_HANDLE_BORDER_HOVER_COLOR = QColor(170, 205, 255, 165)
_HANDLE_GRIP_COLOR = QColor(188, 216, 255, 200)
_HANDLE_GRIP_HOVER_COLOR = QColor(220, 238, 255, 235)


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
        self._hovered = False

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
        self.update()

    def _apply_visible_handle_style(self) -> None:
        self._set_transparent_for_input(False)
        self.setWindowOpacity(1.0)
        # 실제 손잡이는 paintEvent에서 직접 그립니다. 스타일시트 배경은
        # top-level translucent QWidget에서 플랫폼별로 누락될 수 있어
        # borderless 계약 확인용으로만 유지합니다.
        self.setStyleSheet("QWidget { background: transparent; border: none; }")
        self.setToolTip("사이드바 열기")
        self.update()

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
        """상시 노출 손잡이가 외부 요인으로 숨거나 밀렸을 때 다시 표시합니다."""
        if self._screen is None:
            return
        expected_geometry = self._handle_geometry(self._screen)
        if (
            not self._handle_visible
            or not self.isVisible()
            or self.geometry() != expected_geometry
        ):
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
        self._hovered = True
        if self._handle_visible:
            self._handle_hide_timer.stop()
            self.update()

    def leaveEvent(self, event) -> None:
        super().leaveEvent(event)
        self._hovered = False
        if self._handle_visible:
            self._handle_hide_timer.stop()
            self.update()

    def paintEvent(self, event) -> None:
        """손잡이 픽셀을 직접 그려 투명 top-level 스타일 누락을 피합니다."""
        super().paintEvent(event)
        if not self._handle_visible:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        tab_rect = QRectF(self.rect()).adjusted(3.0, 10.0, 1.0, -10.0)
        painter.setPen(QPen(_HANDLE_BORDER_HOVER_COLOR if self._hovered else _HANDLE_BORDER_COLOR, 1))
        painter.setBrush(_HANDLE_HOVER_COLOR if self._hovered else _HANDLE_COLOR)
        painter.drawRoundedRect(tab_rect, 5.0, 5.0)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(_HANDLE_GRIP_HOVER_COLOR if self._hovered else _HANDLE_GRIP_COLOR)
        dot_radius = 1.25
        dot_spacing = 7.0
        center = tab_rect.center()
        start_y = center.y() - dot_spacing
        for index in range(3):
            painter.drawEllipse(
                QRectF(
                    center.x() - dot_radius,
                    start_y + (index * dot_spacing) - dot_radius,
                    dot_radius * 2,
                    dot_radius * 2,
                )
            )

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._handle_visible:
            if not self._in_cooldown:
                self._fire_trigger()
            event.accept()
            return
        super().mousePressEvent(event)
