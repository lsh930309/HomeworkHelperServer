"""Windows Widgets presentation tokens and stylesheet.

This module is the single visual authority for the main window and sidebar.
Runtime state remains owned by the existing GUI/controllers.
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget


def widgets_theme_tokens(dark: bool) -> dict[str, str]:
    if dark:
        return {
            "surface": "#202124",
            "surface_raised": "#292b2f",
            "surface_hover": "#32353a",
            "text": "#f2f3f5",
            "muted": "#aeb4bf",
            "accent": "#6ea8fe",
            "accent_hover": "#8bb9ff",
            "success": "#3fb950",
            "success_soft": "#203b28",
            "warning": "#d29922",
            "warning_soft": "#40351f",
            "danger": "#f85149",
            "danger_soft": "#472728",
            "focus": "#6ea8fe",
        }
    return {
        "surface": "#f5f6f8",
        "surface_raised": "#ffffff",
        "surface_hover": "#edf1f7",
        "text": "#202124",
        "muted": "#667085",
        "accent": "#2563eb",
        "accent_hover": "#1d4ed8",
        "success": "#188038",
        "success_soft": "#e6f4ea",
        "warning": "#9a6700",
        "warning_soft": "#fff4ce",
        "danger": "#c5221f",
        "danger_soft": "#fce8e6",
        "focus": "#2563eb",
    }


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
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("white"))
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
    if central.layout() is not None:
        central.layout().setContentsMargins(12, 10, 12, 12)
        central.layout().setSpacing(8)

    t = widgets_theme_tokens(dark)

    window.setStyleSheet(
        f"""
        QWidget#hhMainSurface {{ background: {t['surface']}; color: {t['text']}; }}
        QMenuBar {{ background: {t['surface']}; color: {t['text']}; padding: 2px 6px; spacing: 4px; }}
        QMenuBar::item {{ padding: 6px 9px; border-radius: 5px; }}
        QMenuBar::item:selected {{ background: {t['surface_hover']}; }}
        QMenu {{ background: {t['surface_raised']}; color: {t['text']}; border: none; padding: 5px; }}
        QMenu::item {{ padding: 6px 18px 6px 10px; border-radius: 5px; }}
        QMenu::item:selected {{ background: {t['surface_hover']}; }}
        QPushButton {{
            min-height: 28px; padding: 0px 11px; border-radius: 7px;
            border: none; background: {t['surface_raised']}; color: {t['text']};
        }}
        QPushButton:hover {{ background: {t['surface_hover']}; }}
        QPushButton:pressed {{ background: {t['surface_hover']}; }}
        QPushButton:focus {{ border: 1px solid {t['focus']}; padding: 0px 10px; }}
        QPushButton[hhRole="primaryAction"] {{
            background: {t['accent']}; color: white; font-weight: 600;
        }}
        QPushButton[hhRole="primaryAction"]:hover {{ background: {t['accent_hover']}; }}
        QPushButton[hhRole="iconAction"] {{ min-width: 30px; max-width: 30px; padding: 0px; }}
        QPushButton[hhState="success"] {{ background: {t['success_soft']}; color: {t['success']}; }}
        QPushButton[hhState="danger"] {{ background: {t['danger_soft']}; color: {t['danger']}; }}
        QToolButton {{
            min-width: 30px; min-height: 28px; border: none; border-radius: 7px;
            background: transparent; color: {t['text']}; padding: 0px 7px;
        }}
        QToolButton:hover {{ background: {t['surface_hover']}; }}
        QToolButton:checked {{ background: {t['accent']}; color: white; }}
        QScrollArea#gameCardScroll {{ background: transparent; border: none; }}
        QWidget#gameCardViewport {{ background: transparent; }}
        QFrame[hhRole="gameCard"] {{
            background: {t['surface_raised']}; border: none; border-radius: 9px;
        }}
        QLabel[hhRole="gameName"] {{ color: {t['text']}; font-weight: 600; }}
        QLabel[hhRole="muted"] {{ color: {t['muted']}; }}
        QLabel[hhRole="statusChip"] {{ padding: 3px 8px; border-radius: 7px; }}
        QLabel[hhRole="statusChip"][hhState="default"] {{ background: {t['surface_hover']}; color: {t['muted']}; }}
        QLabel[hhRole="statusChip"][hhState="running"] {{ background: {t['warning_soft']}; color: {t['warning']}; }}
        QLabel[hhRole="statusChip"][hhState="incomplete"] {{ background: {t['danger_soft']}; color: {t['danger']}; }}
        QLabel[hhRole="statusChip"][hhState="completed"] {{ background: {t['success_soft']}; color: {t['success']}; }}
        QProgressBar {{
            min-height: 8px; max-height: 8px; border: none; border-radius: 4px;
            background: {t['surface_hover']}; color: transparent; text-align: center;
        }}
        QProgressBar::chunk {{ border-radius: 4px; }}
        QProgressBar[hhBucket="low"]::chunk {{ background: {t['success']}; }}
        QProgressBar[hhBucket="medium"]::chunk {{ background: {t['warning']}; }}
        QProgressBar[hhBucket="high"]::chunk {{ background: #e67e22; }}
        QProgressBar[hhBucket="full"]::chunk {{ background: {t['danger']}; }}
        QToolButton#systemStatusButton {{
            min-width: 30px; min-height: 28px; border: none; border-radius: 7px;
            background: transparent; color: {t['muted']}; padding: 0px 7px;
        }}
        QToolButton#systemStatusButton:hover {{ background: {t['surface_hover']}; }}
        QToolButton#systemStatusButton[hhState="warning"] {{ color: {t['warning']}; background: {t['warning_soft']}; }}
        QToolButton#systemStatusButton[hhState="error"] {{ color: {t['danger']}; background: {t['danger_soft']}; }}
        QCheckBox {{ color: {t['text']}; spacing: 6px; }}
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
        QFrame[hhRole="sidebarGroup"] {{ background: rgba(255, 255, 255, 10); border: none; border-radius: 8px; }}
        QPushButton {{ min-height: 28px; border: none; border-radius: 7px; padding: 0px 9px; background: rgba(255, 255, 255, 14); }}
        QPushButton:hover {{ background: rgba(255, 255, 255, 28); }}
        QPushButton:checked {{ color: white; background: {t['accent']}; }}
        QPushButton[hhRole="danger"] {{ color: {t['danger']}; background: {t['danger_soft']}; }}
        QPushButton[hhRole="primaryAction"] {{ color: white; background: {t['accent']}; font-weight: 600; }}
        QPushButton[hhRole="folderAction"] {{ color: {t['muted']}; background: rgba(255, 255, 255, 8); }}
        QLabel[hhState="error"] {{ color: {t['danger']}; }}
        QLabel[hhState="success"] {{ color: {t['success']}; }}
        QLabel[hhState="warning"] {{ color: {t['warning']}; }}
        QLabel[hhState="default"] {{ color: {t['muted']}; }}
        QToolTip {{ background: {t['surface_raised']}; color: {t['text']}; border: none; padding: 5px; }}
        """
    )
