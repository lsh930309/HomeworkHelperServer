"""카운트다운 오버레이 위젯.

3초 카운트다운 후 지정된 콜백을 실행하는 전체화면 반투명 오버레이.
녹화 시작 전 사용자에게 준비 시간을 제공합니다.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from PyQt6.QtCore import QRect, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QScreen
from PyQt6.QtWidgets import QApplication, QWidget

logger = logging.getLogger(__name__)


class CountdownOverlay(QWidget):
    """3초 카운트다운 오버레이.

    start()를 호출하면 3 → 2 → 1 숫자를 1초 간격으로 표시하고
    완료 시 on_complete 콜백을 메인 스레드에서 실행합니다.
    """

    _COUNT_START = 3

    def __init__(
        self,
        on_complete: Callable[[], None],
        screen: Optional[QScreen] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(
            parent,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        self._on_complete = on_complete
        self._count = self._COUNT_START

        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        scr = screen or QApplication.primaryScreen()
        if scr:
            self.setGeometry(scr.geometry())
        else:
            self.setGeometry(0, 0, 1920, 1080)

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    # ------------------------------------------------------------------
    # 공개 API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """카운트다운을 시작합니다."""
        self._count = self._COUNT_START
        self.show()
        self.raise_()
        self.update()
        self._timer.start()

    # ------------------------------------------------------------------
    # 내부
    # ------------------------------------------------------------------

    def _tick(self) -> None:
        self._count -= 1
        if self._count <= 0:
            self._timer.stop()
            self.hide()
            try:
                self._on_complete()
            except Exception:
                logger.exception("카운트다운 완료 콜백 오류")
            self.deleteLater()
            return
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)

            # 반투명 전체 배경
            painter.fillRect(self.rect(), QColor(0, 0, 0, 150))

            # 중앙 숫자 (1초 남으면 빨간색)
            font = QFont()
            font.setPointSize(120)
            font.setBold(True)
            painter.setFont(font)
            num_color = QColor(255, 80, 80) if self._count <= 1 else QColor(255, 255, 255)
            painter.setPen(QPen(num_color))
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                str(self._count),
            )

            # 하단 안내 텍스트
            font2 = QFont()
            font2.setPointSize(18)
            painter.setFont(font2)
            painter.setPen(QPen(QColor(200, 200, 200, 200)))
            guide_rect = QRect(
                self.rect().x(),
                self.rect().center().y() + 90,
                self.rect().width(),
                60,
            )
            painter.drawText(
                guide_rect,
                Qt.AlignmentFlag.AlignCenter,
                "잠시 후 녹화가 시작됩니다...",
            )
        finally:
            painter.end()
