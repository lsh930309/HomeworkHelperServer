"""사이드바의 고정 시계와 게임별 원형 음량 조작부."""
from __future__ import annotations

import datetime

from PySide6.QtCore import QPointF, Property, QPropertyAnimation, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFontMetricsF, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QAbstractButton, QWidget


class SidebarDivider(QWidget):
    """선과 위아래 여백을 같은 비율로 그리는 섹션 경계."""

    def __init__(self, sidebar_width: int, parent=None):
        super().__init__(parent)
        self.setFixedHeight(round(sidebar_width * 0.05))

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setPen(QPen(QColor(255, 255, 255, 26), 1))
        painter.drawLine(QPointF(0, self.height() / 2), QPointF(self.width(), self.height() / 2))


class SidebarClockFace(QWidget):
    """숫자의 실제 획 중심에 콜론을 그리는 HH:MM + 작은 SS 시계."""

    def __init__(self, sidebar_width: int, parent=None):
        super().__init__(parent)
        self._sidebar_width = sidebar_width
        self._time = datetime.datetime.now()
        self.setFixedHeight(round(sidebar_width * 0.19))

    def set_time(self, now: datetime.datetime) -> None:
        self._time = now
        self.setAccessibleName(now.strftime("%H:%M:%S"))
        self.update()

    def face_layout(self):
        """그리기에 사용하는 실제 숫자 획의 경계로 위치를 계산한다."""
        font = self.font()
        font.setPixelSize(round(self._sidebar_width * 0.145))
        small = self.font()
        small.setPixelSize(max(11, round(self._sidebar_width * 0.048)))
        metrics, small_metrics = QFontMetricsF(font), QFontMetricsF(small)
        hour, minute, second = self._time.strftime("%H %M %S").split()
        bounds = metrics.tightBoundingRect("00")
        colon_width = self._sidebar_width * 0.047
        gap = self._sidebar_width * 0.018
        # 숫자가 바뀌어도 콜론·초의 위치가 움직이지 않도록 같은 폭의 두 칸을 쓴다.
        digit_width = max(metrics.horizontalAdvance(str(n)) for n in range(10))
        small_width = max(small_metrics.horizontalAdvance(str(n)) for n in range(10))
        hour_width = minute_width = 2 * digit_width
        total = hour_width + colon_width + minute_width + gap + 2 * small_width
        left = (self.width() - total) / 2
        top = max(0.0, (self.height() - bounds.height()) / 2 - self._sidebar_width * 0.012)
        baseline = top - bounds.top()
        return (font, small, hour, minute, second, left, hour_width, colon_width,
                minute_width, gap, baseline, top + bounds.height() / 2)

    def paintEvent(self, event) -> None:
        font, small, hour, minute, second, left, hw, cw, mw, gap, baseline, center = self.face_layout()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QColor("#f0f2f6"))
        painter.setFont(font)
        metrics = QFontMetricsF(font)
        for start, digits in ((left, hour), (left + hw + cw, minute)):
            for index, digit in enumerate(digits):
                x = start + index * hw / 2 + (hw / 2 - metrics.horizontalAdvance(digit)) / 2
                painter.drawText(QPointF(x, baseline), digit)
        if self._time.microsecond < 500_000:
            radius = self._sidebar_width * 0.0052
            offset = self._sidebar_width * 0.017
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#f0f2f6"))
            for y in (center - offset, center + offset):
                painter.drawEllipse(QPointF(left + hw + cw / 2, y), radius, radius)
        painter.setFont(small)
        painter.setPen(QColor("#b8c1d0"))
        painter.drawText(QPointF(left + hw + cw + mw + gap, baseline + self._sidebar_width * 0.008), second)


class VolumeDial(QAbstractButton):
    """휠 5% 조정·음소거와 일시적인 수치 표시를 한 버튼에서 소유한다."""

    valueChanged = Signal(int)
    interacted = Signal()

    def __init__(self, diameter: int, parent=None):
        super().__init__(parent)
        self._value = 100
        self._wheel_remainder = 0
        self._text_blend = 0.0
        self.setFixedSize(diameter, diameter)
        self.setCheckable(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setToolTip("휠로 5% 조절 · 클릭으로 음소거")
        self._reveal_timer = QTimer(self)
        self._reveal_timer.setSingleShot(True)
        self._reveal_timer.setInterval(900)
        self._reveal_timer.timeout.connect(lambda: self._fade_to(0.0))
        self._fade = QPropertyAnimation(self, b"textBlend", self)
        self._fade.setDuration(180)
        self.toggled.connect(self._on_mute_changed)
        self._describe_value()

    def value(self) -> int | None:
        return self._value

    def setValue(self, value: int | None) -> None:
        # 관측된 37%를 35%로 바꾸지 않는다. 5%는 사용자 조작의 증분이다.
        value = max(0, min(100, round(value))) if value is not None else None
        if value != self._value:
            self._value = value
            self._describe_value()
            self.update()
            if value is not None:
                self.valueChanged.emit(value)

    def is_silent(self) -> bool:
        return self.isChecked() or self._value == 0

    def _describe_value(self) -> None:
        self.setAccessibleDescription(
            "음량 확인 불가" if self._value is None else
            f"{self._value}%, {'음소거' if self.is_silent() else '음소거 안 됨'}")

    def _get_text_blend(self) -> float:
        return self._text_blend

    def _set_text_blend(self, value: float) -> None:
        self._text_blend = value
        self.update()

    textBlend = Property(float, _get_text_blend, _set_text_blend)

    def _fade_to(self, value: float) -> None:
        self._fade.stop()
        self._fade.setStartValue(self._text_blend)
        self._fade.setEndValue(value)
        self._fade.start()

    def _adjust(self, steps: int) -> None:
        if self._value is None:
            return
        self.setValue(self._value + steps * 5)
        self._fade_to(1.0)
        self._reveal_timer.start()
        self.interacted.emit()

    def _on_mute_changed(self, _checked: bool) -> None:
        self._describe_value()
        self._reveal_timer.stop()
        self._fade_to(0.0)
        self.update()
        self.interacted.emit()

    def wheelEvent(self, event) -> None:
        # 고해상도 휠도 한 노치(120)에 한 번만 적용한다. 픽셀 입력은 40px을 한 단계로 본다.
        delta = event.angleDelta().y() or event.pixelDelta().y() * 3
        self._wheel_remainder += delta
        steps = int(self._wheel_remainder / 120)
        self._wheel_remainder -= steps * 120
        if steps:
            self._adjust(steps)
        event.accept()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            self._adjust(1 if event.key() == Qt.Key.Key_Up else -1)
            event.accept()
            return
        super().keyPressEvent(event)

    def hideEvent(self, event) -> None:
        self._reveal_timer.stop()
        self._fade.stop()
        self._text_blend = 0.0
        super().hideEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        diameter = min(self.width(), self.height())
        stroke = max(1.5, diameter * 0.045)
        circle = QRectF(stroke, stroke, diameter - 2 * stroke, diameter - 2 * stroke)
        painter.setBrush(QColor("#161e29"))
        painter.setPen(QPen(QColor(255, 255, 255, 45), stroke))
        painter.drawEllipse(circle)
        if self._value is None:
            painter.setPen(QColor("#7c879a"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "?")
            return
        pen = QPen(QColor("#7c879a" if self.is_silent() else "#91b5e0"), stroke)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(circle, 90 * 16, -round(360 * 16 * self._value / 100))
        if self.hasFocus() or self.underMouse():
            painter.setPen(QPen(QColor(225, 235, 249, 100), 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(circle.adjusted(-1, -1, 1, 1))
        painter.setOpacity(1.0 - self._text_blend)
        painter.save()
        size = diameter * 0.45
        painter.translate((diameter - size) / 2, (diameter - size) / 2)
        painter.scale(size / 16, size / 16)
        painter.setPen(QPen(QColor("#c8d3e3"), 1.3))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        speaker = QPainterPath()
        speaker.moveTo(2, 6)
        speaker.lineTo(5, 6)
        speaker.lineTo(9, 2)
        speaker.lineTo(9, 14)
        speaker.lineTo(5, 10)
        speaker.lineTo(2, 10)
        speaker.closeSubpath()
        painter.drawPath(speaker)
        if self.is_silent():
            painter.drawLine(11, 6, 15, 10)
            painter.drawLine(11, 10, 15, 6)
        else:
            painter.drawArc(QRectF(8, 4, 5, 8), -65 * 16, 130 * 16)
            painter.drawArc(QRectF(8, 1, 8, 14), -65 * 16, 130 * 16)
        painter.restore()
        painter.setOpacity(self._text_blend)
        painter.setPen(QColor("#e4eaf4"))
        font = self.font()
        font.setPixelSize(max(11, round(diameter * 0.29)))
        painter.setFont(font)
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, f"{self._value}%")
