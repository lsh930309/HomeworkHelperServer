"""Windows Widgets presentation tokens and stylesheet.

This module is the single visual authority for the main window and sidebar.
Runtime state remains owned by the existing GUI/controllers.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import QApplication, QMainWindow, QProgressBar, QWidget


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
    """극소 진행률도 원형 끝을 유지하는 6px 캡슐 진행률 표시입니다."""

    _BUCKET_COLORS = {
        "low": "success",
        "medium": "warning",
        "high": "#e67e22",
        "full": "danger",
    }

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt override
        del event
        if self.width() <= 0 or self.height() <= 0:
            return

        palette = self.palette()
        dark = (
            palette.color(QPalette.ColorRole.WindowText).lightness()
            > palette.color(QPalette.ColorRole.Window).lightness()
        )
        tokens = widgets_theme_tokens(dark)
        rect = QRectF(0.0, 0.0, float(self.width()), float(self.height()))
        radius = rect.height() / 2.0

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(tokens["surface_hover"]))
        painter.drawRoundedRect(rect, radius, radius)

        span = self.maximum() - self.minimum()
        if span <= 0 or self.value() <= self.minimum():
            painter.end()
            return

        ratio = min(1.0, max(0.0, (self.value() - self.minimum()) / span))
        fill_width = min(rect.width(), max(rect.height(), rect.width() * ratio))
        fill_rect = QRectF(rect.left(), rect.top(), fill_width, rect.height())
        bucket = str(self.property("hhBucket") or "low")
        color_key = self._BUCKET_COLORS.get(bucket, "success")
        fill_color = tokens[color_key] if color_key in tokens else color_key
        painter.setBrush(QColor(fill_color))
        painter.drawRoundedRect(fill_rect, radius, radius)
        painter.end()


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
    widget.setStyleSheet(
        f"""
        QWidget {{ color: {t['text']}; }}
        QFrame[hhRole="sidebarGroup"] {{ background: {t['surface_raised']}; border: none; border-radius: 6px; }}
        QPushButton {{ min-height: 26px; border: 1px solid transparent; border-radius: 5px; padding: 0px 8px; background: {t['surface_raised']}; }}
        QPushButton:hover, QPushButton:focus {{ background: {t['surface_hover']}; border-color: {t['focus']}; }}
        QPushButton:pressed {{ background: {t['surface_pressed']}; border-color: {t['focus']}; }}
        QPushButton:checked {{ color: {t['text']}; background: {t['accent']}; }}
        QPushButton[hhRole="danger"] {{ color: {t['danger']}; background: {t['danger_soft']}; }}
        QPushButton[hhRole="primaryAction"] {{ color: {t['text']}; background: {t['accent']}; font-weight: 600; }}
        QPushButton[hhRole="folderAction"] {{ color: {t['muted']}; background: {t['surface_raised']}; }}
        QPushButton[hhRole="danger"]:pressed,
        QPushButton[hhRole="primaryAction"]:pressed,
        QPushButton[hhRole="folderAction"]:pressed {{ background: {t['surface_pressed']}; border-color: {t['focus']}; }}
        QPushButton[hhRole="muteToggle"] {{
            min-width: 20px; max-width: 20px; min-height: 20px; max-height: 20px;
            padding: 0px; background: {t['surface_raised']};
        }}
        QPushButton[hhRole="muteToggle"]:checked {{ background: {t['mute_active']}; color: white; }}
        QPushButton[hhRole="muteToggle"]:checked:hover,
        QPushButton[hhRole="muteToggle"]:checked:focus {{
            background: {t['mute_active']}; border-color: {t['focus']};
        }}
        QPushButton[hhRole="muteToggle"]:checked:pressed {{
            background: {t['mute_pressed']}; border-color: {t['focus']};
        }}
        QLabel[hhState="error"] {{ color: {t['danger']}; }}
        QLabel[hhState="success"] {{ color: {t['success']}; }}
        QLabel[hhState="warning"] {{ color: {t['warning']}; }}
        QLabel[hhState="default"] {{ color: {t['muted']}; }}
        QToolTip {{ background: {t['surface_raised']}; color: {t['text']}; border: none; padding: 5px; }}
        """
    )
