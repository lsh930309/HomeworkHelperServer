"""Windows Widgets presentation tokens and stylesheet.

This module is the single visual authority for the main window and sidebar.
Runtime state remains owned by the existing GUI/controllers.
"""
from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import (
    QBrush, QColor, QFont, QFontMetricsF, QIcon, QPainter, QPainterPath, QPalette, QPen,
    QPixmap, QRadialGradient,
)
from PySide6.QtWidgets import QApplication, QLabel, QMainWindow, QProgressBar, QWidget

if TYPE_CHECKING:
    from src.data.data_models import ManagedProcess

logger = logging.getLogger(__name__)


def calculate_game_progress(process: ManagedProcess, current_dt: datetime.datetime) -> tuple[float, str]:
    """Windows 게임 게이지에 표시할 백분율과 값의 원천을 계산합니다."""
    now = current_dt.timestamp()
    resource_percentage = process.get_resource_percentage(now=now)
    if resource_percentage is not None:
        label = process.resource_label or "리소스"
        return resource_percentage, f"RESOURCE:{process.resource_key}:{label}:{resource_percentage:.1f}%"

    if process.stamina_tracking_enabled and process.hoyolab_game_id:
        stamina_info = process.get_predicted_stamina(now=now)
        if stamina_info:
            predicted, max_stamina = stamina_info
            percentage = predicted / max_stamina * 100 if max_stamina > 0 else 0.0
            return percentage, f"STAMINA:{process.hoyolab_game_id}:{predicted}/{max_stamina}"

    if not process.last_played_timestamp or not process.user_cycle_hours:
        return 0.0, "기록 없음"

    try:
        last_played_dt = datetime.datetime.fromtimestamp(process.last_played_timestamp)
        cycle_hours = process.user_cycle_hours
        elapsed_hours = (current_dt - last_played_dt).total_seconds() / 3600
        percentage = min(elapsed_hours / cycle_hours, 1.0) * 100
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
            time_str = f"{int(remaining_hours * 60)}분"
        return percentage, time_str
    except Exception as exc:
        logger.error("진행률 계산 중 오류: %s", exc)
        return 0.0, "계산 오류"


def progress_bar_format(percentage: float, display_text: str) -> str:
    """게이지 옆에 표시할 짧은 값을 반환합니다."""
    if display_text.startswith("RESOURCE:"):
        parts = display_text.split(":", 3)
        if len(parts) == 4:
            return parts[3]
    if display_text.startswith("STAMINA:"):
        parts = display_text.split(":")
        if len(parts) >= 3:
            return parts[2]
    return f"{percentage:.1f}%"


def progress_color_bucket(percentage: float) -> str:
    """채워진 정도에 따라 공용 게이지 색을 선택합니다."""
    if percentage >= 100:
        return "full"
    if percentage >= 80:
        return "high"
    if percentage >= 50:
        return "medium"
    return "low"


class GameIconLabel(QLabel):
    """원본·캐시는 보존하고 게임 아이콘 표시 영역을 같은 둥근 정사각형으로 자른다."""

    def __init__(self, icon_size: int, parent=None):
        super().__init__(parent)
        self._icon_size = icon_size
        self.setMinimumSize(icon_size, icon_size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def paintEvent(self, event) -> None:
        size = min(self._icon_size, self.width(), self.height())
        rect = QRectF((self.width() - size) / 2, (self.height() - size) / 2, size, size)
        radius = size * 0.2
        clip = QPainterPath()
        clip.addRoundedRect(rect, radius, radius)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.setClipPath(clip)
        painter.fillRect(rect, QColor(255, 255, 255, 12))
        pixmap = self.pixmap()
        if not pixmap.isNull():
            side = min(pixmap.width(), pixmap.height())
            source = QRectF((pixmap.width() - side) / 2, (pixmap.height() - side) / 2, side, side)
            painter.drawPixmap(rect, pixmap, source)
        else:
            painter.setPen(self.palette().color(QPalette.ColorRole.WindowText))
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self.text())
        painter.setClipping(False)
        if self.property("hhRunning"):
            painter.setPen(QPen(QColor("#76ce96"), 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), radius - 1, radius - 1)


def widgets_theme_tokens(dark: bool) -> dict[str, str]:
    if dark:
        return {
            "surface": "#0f0f10",
            "surface_raised": "#1a1a1c",
            "surface_hover": "#27272a",
            "surface_pressed": "#3a3a3e",
            "text": "#f5f5f6",
            "muted": "#a3a3aa",
            "accent": "#2b2b2f",
            "accent_hover": "#3a3a3f",
            "success": "#3fb950",
            "success_soft": "#203b28",
            "warning": "#d29922",
            "warning_soft": "#40351f",
            "danger": "#f85149",
            "danger_soft": "#472728",
            "focus": "#d8d8dc",
            "mute_active": "rgba(80, 130, 220, 160)",
            "mute_pressed": "rgba(65, 105, 190, 220)",
        }
    return {
        "surface": "#f3f3f3",
        "surface_raised": "#ffffff",
        "surface_hover": "#e5e5e7",
        "surface_pressed": "#cfcfd3",
        "text": "#171719",
        "muted": "#696970",
        "accent": "#dedee2",
        "accent_hover": "#cfcfd4",
        "success": "#188038",
        "success_soft": "#e6f4ea",
        "warning": "#9a6700",
        "warning_soft": "#fff4ce",
        "danger": "#c5221f",
        "danger_soft": "#fce8e6",
        "focus": "#45454b",
        "mute_active": "rgba(80, 130, 220, 160)",
        "mute_pressed": "rgba(65, 105, 190, 220)",
    }


class CapsuleProgressBar(QProgressBar):
    """극소 진행률도 원형 끝을 유지하고, 필요한 화면에 값을 함께 그립니다."""

    _PERCENTAGE_SCALE = 10
    _BUCKET_COLORS = {
        "low": "success",
        "medium": "warning",
        "high": "#e67e22",
        "full": "danger",
    }
    _SIDEBAR_BUCKET_COLORS = {
        "low": "#347e4a",
        "medium": "#8c6928",
        "high": "#9f622e",
        "full": "#ac4a47",
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setRange(0, 100 * self._PERCENTAGE_SCALE)
        self.setTextVisible(False)

    def set_progress(self, percentage: float | None, format_text: str) -> bool:
        """값·표시 문자열·색을 갱신하고 화면 변경 여부를 반환합니다."""
        value = (self.minimum() - 1 if percentage is None
                 else round(max(0.0, min(percentage, 100.0)) * self._PERCENTAGE_SCALE))
        bucket = progress_color_bucket(0.0 if percentage is None else percentage)
        value_changed = self.value() != value
        format_changed = self.format() != format_text
        bucket_changed = self.property("hhBucket") != bucket
        if format_changed:
            self.setFormat(format_text)
        if bucket_changed:
            self.setProperty("hhBucket", bucket)
            self.update()
        if value_changed:
            if percentage is None:
                self.reset()
            else:
                self.setValue(value)
        return value_changed or format_changed or bucket_changed

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        del event
        if self.width() <= 0 or self.height() <= 0:
            return

        app = QApplication.instance()
        palette = app.palette() if app is not None else self.palette()
        dark = (
            palette.color(QPalette.ColorRole.WindowText).lightness()
            > palette.color(QPalette.ColorRole.Window).lightness()
        )
        tokens = widgets_theme_tokens(dark)
        rect = QRectF(0.0, 0.0, float(self.width()), float(self.height()))
        radius = rect.height() / 2.0
        sidebar = self.objectName() == "gameProgressBar"
        track = ("#11181e" if dark else "#29313c") if sidebar else tokens["surface"]

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(track))
        painter.drawRoundedRect(rect, radius, radius)

        span = self.maximum() - self.minimum()
        if span > 0 and self.value() > self.minimum():
            ratio = min(1.0, (self.value() - self.minimum()) / span)
            fill_width = min(rect.width(), max(rect.height(), rect.width() * ratio))
            fill_rect = QRectF(rect.left(), rect.top(), fill_width, rect.height())
            bucket = str(self.property("hhBucket") or "low")
            color_key = self._BUCKET_COLORS.get(bucket, "success")
            fill_color = (self._SIDEBAR_BUCKET_COLORS.get(bucket, self._SIDEBAR_BUCKET_COLORS["low"])
                          if sidebar else tokens.get(color_key, color_key))
            painter.setBrush(QColor(fill_color))
            painter.drawRoundedRect(fill_rect, radius, radius)

        if self.isTextVisible():
            self._paint_caption(painter, rect)
        painter.end()

    def _paint_caption(self, painter: QPainter, rect: QRectF) -> None:
        missing = self.value() < self.minimum()
        caption = self.format() if missing else self.text()
        if not caption or rect.width() <= 4 or rect.height() <= 2:
            return
        glyphs = QPainterPath()
        font = self.font()
        if missing:
            if font.pixelSize() > 0:
                font.setPixelSize(max(1, round(font.pixelSize() * 10 / 11)))
            else:
                font.setPointSizeF(font.pointSizeF() * 10 / 11)
            font.setWeight(QFont.Weight.Normal)
        glyphs.addText(0.0, 0.0, font, caption)
        bounds = glyphs.boundingRect()
        if bounds.isEmpty():
            return

        text_scale = min(1.0, (rect.width() - 4) / bounds.width())
        if not missing:
            text_width = QFontMetricsF(font, self).horizontalAdvance(caption) * text_scale
            ellipse_width = text_width + 28 * rect.height() / 11
            radius = rect.height() / 2
            clip = QPainterPath()
            clip.addRoundedRect(rect, radius, radius)
            shade = QRadialGradient(0.0, 0.0, 1.0)
            shade.setStops([(position, QColor.fromRgbF(0, 0, 0, alpha)) for position, alpha in (
                (0.0, 0.22), (0.38, 0.19), (0.65, 0.12), (0.85, 0.04), (1.0, 0.0),
            )])
            painter.save()
            painter.setClipPath(clip)
            painter.translate(rect.center())
            painter.scale(ellipse_width / 2, rect.height() * 2)
            painter.fillRect(QRectF(-1.0, -1.0, 2.0, 2.0), QBrush(shade))
            painter.restore()

        painter.translate(rect.center())
        painter.scale(text_scale, min(1.0, (rect.height() - 2) / bounds.height()))
        painter.translate(-bounds.center().x(), -bounds.center().y())
        painter.fillPath(glyphs, QColor("#aab3bf" if missing else "#f4f6fa"))


def tint_icon(icon: QIcon, color: QColor, logical_size: int = 16) -> QIcon:
    """표준 아이콘을 현재 테마의 명시적 전경색으로 변환합니다."""
    pixmap = icon.pixmap(logical_size, logical_size)
    if pixmap.isNull():
        return icon
    tinted = QPixmap(pixmap.size())
    tinted.setDevicePixelRatio(pixmap.devicePixelRatio())
    tinted.fill(Qt.GlobalColor.transparent)
    painter = QPainter(tinted)
    painter.drawPixmap(0, 0, pixmap)
    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
    painter.fillRect(tinted.rect(), color)
    painter.end()
    return QIcon(tinted)


def apply_widgets_palette(*, dark: bool) -> None:
    app = QApplication.instance()
    if app is None:
        return
    tokens = widgets_theme_tokens(dark)
    palette = app.palette()
    palette.setColor(QPalette.ColorRole.Window, QColor(tokens["surface"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(tokens["text"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(tokens["surface_raised"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(tokens["surface_hover"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(tokens["text"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(tokens["surface_raised"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(tokens["text"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(tokens["accent"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(tokens["text"]))
    app.setPalette(palette)


def apply_modern_widgets_style(window: QMainWindow, *, dark: bool) -> None:
    central = window.centralWidget()
    if central is None:
        return
    window.setProperty("hhUiVariant", "newgui-2nd")
    central.setObjectName("hhMainSurface")
    central.setProperty("hhSurface", True)

    for name, attribute in (
        ("primaryAction", "add_game_button"),
        ("iconAction", "add_web_shortcut_button"),
        ("iconAction", "dashboard_button"),
        ("iconAction", "github_button"),
    ):
        control = getattr(window, attribute, None)
        if control is not None:
            control.setProperty("hhRole", name)
    table = getattr(window, "process_table", None)
    if table is not None:
        table.setObjectName("processTable")
    if central.layout() is not None:
        central.layout().setContentsMargins(6, 6, 6, 6)
        central.layout().setSpacing(4)

    t = widgets_theme_tokens(dark)

    window.setStyleSheet(
        f"""
        QWidget#hhMainSurface {{ background: {t['surface']}; color: {t['text']}; }}
        QMenuBar {{ background: {t['surface']}; color: {t['text']}; padding: 4px 4px 3px 4px; spacing: 2px; }}
        QMenuBar::item {{ padding: 5px 7px 4px 7px; border-radius: 4px; }}
        QMenuBar::item:selected {{ background: {t['surface_hover']}; }}
        QMenu {{ background: {t['surface_raised']}; color: {t['text']}; border: none; padding: 4px; }}
        QMenu::item {{ padding: 5px 16px 5px 8px; border-radius: 4px; }}
        QMenu::item:selected {{ background: {t['surface_hover']}; }}
        QPushButton {{
            min-height: 26px; padding: 0px 8px; border-radius: 5px;
            border: 1px solid transparent; background: {t['surface_raised']}; color: {t['text']};
        }}
        QPushButton:hover {{ background: {t['surface_hover']}; border-color: {t['focus']}; }}
        QPushButton:focus {{ border-color: {t['focus']}; }}
        QPushButton:pressed {{ background: {t['surface_pressed']}; border-color: {t['focus']}; }}
        QPushButton[hhRole="primaryAction"] {{
            background: {t['accent']}; color: {t['text']}; font-weight: 600;
        }}
        QTableWidget#processTable QPushButton[hhRole="primaryAction"] {{
            min-height: 30px; max-height: 30px;
        }}
        QPushButton[hhRole="primaryAction"]:hover {{ background: {t['accent_hover']}; }}
        QPushButton[hhRole="primaryAction"]:pressed {{ background: {t['surface_pressed']}; }}
        QPushButton[hhRole="iconAction"] {{
            min-width: 28px; max-width: 28px; min-height: 28px; max-height: 28px; padding: 0px;
        }}
        QPushButton[hhRole="iconAction"]:pressed {{ background: {t['surface_pressed']}; }}
        QPushButton[hhState="success"] {{ background: {t['success_soft']}; color: {t['success']}; }}
        QPushButton[hhState="danger"] {{ background: {t['danger_soft']}; color: {t['danger']}; }}
        QPushButton[hhState="success"]:pressed,
        QPushButton[hhState="danger"]:pressed {{ background: {t['surface_pressed']}; }}
        QToolButton {{
            min-width: 30px; min-height: 26px; border: 1px solid transparent; border-radius: 5px;
            background: transparent; color: {t['text']}; padding: 0px 7px;
        }}
        QToolButton:hover, QToolButton:focus {{ background: {t['surface_hover']}; border-color: {t['focus']}; }}
        QToolButton:pressed {{ background: {t['surface_pressed']}; border-color: {t['focus']}; }}
        QToolButton:checked {{ background: {t['accent']}; color: {t['text']}; }}
        QToolButton:checked:pressed {{ background: {t['surface_pressed']}; border-color: {t['focus']}; }}
        QToolButton[hhRole="menuCornerAction"] {{
            min-width: 0px; min-height: 0px; padding: 0px;
        }}
        QTableWidget#processTable {{
            background: {t['surface_raised']}; alternate-background-color: {t['surface_raised']};
            color: {t['text']}; border: none; outline: none; padding: 0px;
            gridline-color: transparent; selection-background-color: transparent;
        }}
        QTableWidget#processTable::item {{ border: none; padding: 0px 2px; }}
        QLabel#progressText {{ color: {t['muted']}; }}
        QProgressBar {{
            min-height: 6px; max-height: 6px; border: none; border-radius: 3px;
            background: transparent; color: transparent; text-align: center;
        }}
        QWidget#readinessStrip {{
            background: {t['surface']}; border-top: 1px solid {t['surface_hover']};
        }}
        QWidget[hhRole="readinessItem"] {{ background: transparent; border: none; }}
        QLabel[hhRole="readinessDot"], QLabel[hhRole="readinessText"] {{
            background: transparent; border: none; color: {t['muted']};
        }}
        QLabel[hhRole="readinessDot"][hhState="green"] {{ color: {t['success']}; }}
        QLabel[hhRole="readinessDot"][hhState="yellow"] {{ color: {t['warning']}; }}
        QLabel[hhRole="readinessDot"][hhState="red"] {{ color: {t['danger']}; }}
        QCheckBox {{ color: {t['text']}; spacing: 6px; padding-left: 2px; }}
        QCheckBox[hhRole="menuCornerToggle"] {{ padding: 1px 4px 1px 2px; }}
        QToolTip {{ background: {t['surface_raised']}; color: {t['text']}; border: none; padding: 5px; }}
        """
    )

    # Dynamic properties do not always repolish immediately on Windows.
    for attribute in ("add_game_button", "add_web_shortcut_button", "dashboard_button", "github_button"):
        control = getattr(window, attribute, None)
        if control is not None:
            control.style().unpolish(control)
            control.style().polish(control)


def apply_sidebar_widgets_style(widget: QWidget, *, dark: bool) -> None:
    """Apply the same surface/state language to the independent sidebar shell."""
    t = widgets_theme_tokens(dark)
    button_height = round(widget.width() * 0.1) - 2  # border 1px × 2
    button_padding = round(widget.width() * 0.03)
    action_content = round(widget.width() * 0.114) - 2  # 공통 외곽 크기에서 테두리 양쪽 1px을 제외
    surface_height = round(widget.width() * 0.125) - 2  # 1px 패딩을 제외한 창 전환 영역 높이
    tab_gap = round(widget.width() * 0.012)
    row_radius = round(widget.width() * 0.02)
    widget.setStyleSheet(
        f"""
        QWidget {{ color: {t['text']}; }}
        QLabel[hhRole="sidebarSecondary"] {{ color: {t['muted']}; font-size: 11px; }}
        QLabel[hhRole="sidebarGameName"] {{ color: {t['text']}; font-size: {round(widget.width() * 0.05)}px; font-weight: 500; }}
        QProgressBar#gameProgressBar {{ font-size: {round(widget.width() * 0.039)}px; font-weight: 500; }}
        QLabel[hhRole="sidebarSectionTitle"] {{ font-size: 12px; font-weight: 500; }}
        QFrame[hhRole="sidebarGameRow"] {{ background: transparent; border: none; border-radius: {row_radius}px; }}
        QFrame[hhRole="sidebarGameRow"][hhRunning="true"] {{ background: rgba(42,101,174,77); }}
        QFrame[hhRole="sidebarGameRow"][hhFocused="true"] {{ background: rgba(28,116,103,99); }}
        QPushButton {{ min-height: {button_height}px; font-size: 12px; border: 1px solid transparent;
            border-radius: 5px; padding: 0px {button_padding}px; background: {t['surface_raised']}; }}
        QPushButton:hover, QPushButton:focus {{ background: {t['surface_hover']}; border-color: {t['focus']}; }}
        QPushButton:pressed {{ background: {t['surface_pressed']}; border-color: {t['focus']}; }}
        QPushButton:checked {{ color: {t['text']}; background: {t['accent']}; }}
        QPushButton[hhRole="danger"] {{ color: {t['danger']}; background: {t['danger_soft']}; }}
        QPushButton[hhRole="primaryAction"] {{ color: {t['text']}; background: {t['accent']}; font-weight: 600; }}
        QPushButton[hhRole="folderAction"] {{ color: {t['muted']}; background: {t['surface_raised']}; }}
        QPushButton[hhRole="danger"]:pressed,
        QPushButton[hhRole="primaryAction"]:pressed,
        QPushButton[hhRole="folderAction"]:pressed {{ background: {t['surface_pressed']}; border-color: {t['focus']}; }}
        QPushButton[hhRole="sidebarIconAction"] {{ min-width: {action_content}px; max-width: {action_content}px;
            min-height: {action_content}px; max-height: {action_content}px; padding: 0px; }}
        QPushButton[hhRole="sidebarIconAction"][hhDanger="true"] {{ color: {t['danger']}; background: {t['danger_soft']}; }}
        QPushButton[hhRole="sidebarGameSurface"] {{ min-height: {surface_height}px; padding: 1px;
            background: transparent; border-radius: {row_radius}px; border: none; }}
        QPushButton[hhRole="sidebarGameSurface"][hhRunning="true"]:hover {{ background: rgba(42,101,174,62); }}
        QPushButton[hhRole="sidebarGameSurface"][hhRunning="true"]:focus {{ background: rgba(42,101,174,115); }}
        QPushButton[hhRole="sidebarGameSurface"][hhRunning="true"]:pressed {{ background: rgba(42,101,174,155); }}
        QPushButton[hhRole="sidebarGameSurface"][hhFocused="true"]:hover {{ background: rgba(28,116,103,74); }}
        QPushButton[hhRole="sidebarGameSurface"][hhFocused="true"]:focus {{ background: rgba(28,116,103,130); }}
        QPushButton[hhRole="sidebarGameSurface"][hhFocused="true"]:pressed {{ background: rgba(28,116,103,175); }}
        QTabBar::tab {{ color: {t['muted']}; background: {t['surface_raised']};
            border: none; border-radius: 5px; padding: 0.5em; margin-right: {tab_gap}px; }}
        QTabBar::tab:last {{ margin-right: 0px; }}
        QTabBar::tab:selected {{ color: {t['text']}; background: {t['accent']}; }}
        QTabBar::tab:hover {{ color: {t['text']}; background: {t['surface_hover']}; }}
        QLabel[hhState="error"] {{ color: {t['danger']}; }}
        QLabel[hhState="success"] {{ color: {t['success']}; }}
        QLabel[hhState="warning"] {{ color: {t['warning']}; }}
        QLabel[hhState="default"] {{ color: {t['muted']}; }}
        QToolTip {{ background: {t['surface_raised']}; color: {t['text']}; border: none; padding: 5px; }}
        """
    )
