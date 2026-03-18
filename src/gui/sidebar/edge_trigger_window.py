"""화면 우측 가장자리 커서 감지 투명 창.

화면 우측 끝에 1px 너비의 투명 창을 배치하고,
100ms 폴링으로 커서가 트리거 영역(trigger_y_start ~ trigger_y_end 비율)에
들어왔을 때 콜백을 호출합니다.

쿨다운(cooldown_sec) 동안은 재트리거를 방지합니다.
"""
import logging
from typing import Callable, Optional

from PyQt6.QtCore import Qt, QTimer, QRect
from PyQt6.QtGui import QCursor, QScreen
from PyQt6.QtWidgets import QApplication, QWidget

logger = logging.getLogger(__name__)

_POLL_INTERVAL_MS = 100   # 커서 감지 폴링 간격 (ms)
_TRIGGER_WIDTH_PX = 2     # 트리거 창 너비 (px) — 1px은 가끔 클리핑되므로 2px 사용


class EdgeTriggerWindow(QWidget):
    """화면 우측 가장자리에 붙어있는 투명 트리거 창.

    게임이 전체화면으로 실행 중일 때도 WS_EX_TOPMOST 로 커서를 감지합니다.
    """

    def __init__(
        self,
        trigger_callback: Callable[[], None],
        trigger_y_start: float = 0.1,
        trigger_y_end: float = 0.9,
        cooldown_sec: float = 1.0,
        screen: Optional[QScreen] = None,
        parent: Optional[QWidget] = None,
    ):
        """EdgeTriggerWindow 를 초기화합니다.

        Args:
            trigger_callback: 커서가 트리거 영역 진입 시 호출할 함수.
            trigger_y_start: 트리거 영역 시작 Y 비율 (0.0 ~ 1.0).
            trigger_y_end: 트리거 영역 종료 Y 비율 (0.0 ~ 1.0).
            cooldown_sec: 트리거 후 재발동 방지 시간 (초).
            screen: 배치할 화면. None이면 주 화면을 사용합니다.
            parent: 부모 위젯.
        """
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput,
        )
        self._trigger_callback = trigger_callback
        _s = max(0.0, min(1.0, trigger_y_start))
        _e = max(0.0, min(1.0, trigger_y_end))
        self._trigger_y_start, self._trigger_y_end = min(_s, _e), max(_s, _e)
        self._cooldown_ms = int(cooldown_sec * 1000)
        self._in_cooldown = False
        self._cursor_was_in_zone = False

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setWindowOpacity(0.0)  # 완전 투명

        # 배치할 화면 결정
        target_screen = screen or QApplication.primaryScreen()
        self._reposition(target_screen)

        # 폴링 타이머
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll_cursor)

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """커서 감지 폴링을 시작하고 트리거 창을 표시합니다."""
        self.show()
        self._poll_timer.start()
        logger.debug("EdgeTriggerWindow 시작됨")

    def stop(self) -> None:
        """커서 감지 폴링을 중지하고 창을 숨깁니다."""
        self._poll_timer.stop()
        self.hide()
        self._in_cooldown = False
        self._cursor_was_in_zone = False
        logger.debug("EdgeTriggerWindow 중지됨")

    def update_settings(
        self,
        trigger_y_start: float,
        trigger_y_end: float,
        cooldown_sec: float,
    ) -> None:
        """트리거 설정을 런타임에 갱신합니다."""
        _s = max(0.0, min(1.0, trigger_y_start))
        _e = max(0.0, min(1.0, trigger_y_end))
        self._trigger_y_start, self._trigger_y_end = min(_s, _e), max(_s, _e)
        self._cooldown_ms = int(cooldown_sec * 1000)

    def reposition(self, screen: Optional[QScreen]) -> None:
        """화면 변경 시 트리거 창을 새 화면의 우측 끝으로 재배치합니다."""
        self._reposition(screen)
        logger.debug("EdgeTriggerWindow 재배치: %s", screen.name() if screen else "None")

    # ------------------------------------------------------------------
    # 내부 메서드
    # ------------------------------------------------------------------

    def _reposition(self, screen: Optional[QScreen]) -> None:
        """창을 지정된 화면의 우측 끝에 배치합니다."""
        if screen is None:
            return
        geo: QRect = screen.geometry()
        trigger_x = geo.right() - _TRIGGER_WIDTH_PX + 1
        self.setGeometry(trigger_x, geo.top(), _TRIGGER_WIDTH_PX, geo.height())

    def _poll_cursor(self) -> None:
        """현재 커서 위치를 확인하고 트리거 영역 진입 여부를 판단합니다."""
        if self._in_cooldown:
            return

        cursor_pos = QCursor.pos()

        # 트리거 창 자체의 geometry 기준으로 판정 (멀티모니터 오탐 방지)
        my_geo: QRect = self.geometry()

        # 우측 가장자리 X 범위 내에 있는지 확인
        if cursor_pos.x() < my_geo.left():
            self._cursor_was_in_zone = False
            return

        # Y 비율 계산 (트리거 창은 화면 전체 높이와 동일)
        if my_geo.height() == 0:
            return
        y_ratio = (cursor_pos.y() - my_geo.top()) / my_geo.height()
        in_zone = self._trigger_y_start <= y_ratio <= self._trigger_y_end

        if in_zone and not self._cursor_was_in_zone:
            # 새로 진입한 경우 트리거
            self._cursor_was_in_zone = True
            self._fire_trigger()
        elif not in_zone:
            self._cursor_was_in_zone = False

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
        self._cursor_was_in_zone = False
