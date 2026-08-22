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
    if central.layout() is not None:
        central.layout().setContentsMargins(6, 6, 6, 6)
        central.layout().setSpacing(4)

    t = widgets_theme_tokens(dark)

    window.setStyleSheet(
        f"""
        QWidget#hhMainSurface {{ background: {t['surface']}; color: {t['text']}; }}
        QMenuBar {{ background: {t['surface']}; color: {t['text']}; padding: 1px 4px; spacing: 2px; }}
        QMenuBar::item {{ padding: 4px 7px; border-radius: 4px; }}
        QMenuBar::item:selected {{ background: {t['surface_hover']}; }}
        QMenu {{ background: {t['surface_raised']}; color: {t['text']}; border: none; padding: 4px; }}
        QMenu::item {{ padding: 5px 16px 5px 8px; border-radius: 4px; }}
        QMenu::item:selected {{ background: {t['surface_hover']}; }}
        QPushButton {{
            min-height: 26px; padding: 0px 8px; border-radius: 5px;
            border: 1px solid transparent; background: {t['surface_raised']}; color: {t['text']};
        }}
        QPushButton:hover {{ background: {t['surface_hover']}; border-color: {t['focus']}; }}
        QPushButton:pressed {{ background: {t['surface_pressed']}; border-color: {t['focus']}; }}
        QPushButton:focus {{ border-color: {t['focus']}; }}
        QPushButton[hhRole="primaryAction"] {{
            background: {t['accent']}; color: {t['text']}; font-weight: 600;
        }}
        QPushButton[hhRole="primaryAction"]:hover {{ background: {t['accent_hover']}; }}
        QPushButton[hhRole="iconAction"] {{ min-width: 30px; max-width: 30px; padding: 0px; }}
        QPushButton[hhState="success"] {{ background: {t['success_soft']}; color: {t['success']}; }}
        QPushButton[hhState="danger"] {{ background: {t['danger_soft']}; color: {t['danger']}; }}
        QToolButton {{
            min-width: 30px; min-height: 26px; border: 1px solid transparent; border-radius: 5px;
            background: transparent; color: {t['text']}; padding: 0px 7px;
        }}
        QToolButton:hover, QToolButton:focus {{ background: {t['surface_hover']}; border-color: {t['focus']}; }}
        QToolButton:pressed {{ background: {t['surface_pressed']}; border-color: {t['focus']}; }}
        QToolButton:checked {{ background: {t['accent']}; color: {t['text']}; }}
        QWidget#gameCardContainer {{ background: transparent; }}
        QFrame[hhRole="gameCard"] {{
            background: {t['surface_raised']}; border: none; border-radius: 6px;
        }}
        QLabel[hhRole="gameName"] {{ color: {t['text']}; font-weight: 600; }}
        QLabel[hhRole="muted"] {{ color: {t['muted']}; }}
        QLabel[hhRole="statusChip"] {{ padding: 2px 6px; border-radius: 5px; }}
        QLabel[hhRole="statusChip"][hhState="default"] {{ background: {t['surface_hover']}; color: {t['muted']}; }}
        QLabel[hhRole="statusChip"][hhState="running"] {{ background: {t['warning_soft']}; color: {t['warning']}; }}
        QLabel[hhRole="statusChip"][hhState="incomplete"] {{ background: {t['danger_soft']}; color: {t['danger']}; }}
        QLabel[hhRole="statusChip"][hhState="completed"] {{ background: {t['success_soft']}; color: {t['success']}; }}
        QProgressBar {{
            min-height: 6px; max-height: 6px; border: none; border-radius: 3px;
            background: {t['surface_hover']}; color: transparent; text-align: center;
        }}
        QProgressBar::chunk {{ border-radius: 3px; }}
        QProgressBar[hhBucket="low"]::chunk {{ background: {t['success']}; }}
        QProgressBar[hhBucket="medium"]::chunk {{ background: {t['warning']}; }}
        QProgressBar[hhBucket="high"]::chunk {{ background: #e67e22; }}
        QProgressBar[hhBucket="full"]::chunk {{ background: {t['danger']}; }}
        QToolButton#systemStatusButton {{
            min-width: 30px; min-height: 26px; border: 1px solid transparent; border-radius: 5px;
            background: transparent; color: {t['muted']}; padding: 0px 7px;
        }}
        QToolButton#systemStatusButton:hover, QToolButton#systemStatusButton:focus {{ background: {t['surface_hover']}; border-color: {t['focus']}; }}
        QToolButton#systemStatusButton:pressed {{ background: {t['surface_pressed']}; border-color: {t['focus']}; }}
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
        QFrame[hhRole="sidebarGroup"] {{ background: {t['surface_raised']}; border: none; border-radius: 6px; }}
        QPushButton {{ min-height: 26px; border: 1px solid transparent; border-radius: 5px; padding: 0px 8px; background: {t['surface_raised']}; }}
        QPushButton:hover, QPushButton:focus {{ background: {t['surface_hover']}; border-color: {t['focus']}; }}
        QPushButton:pressed {{ background: {t['surface_pressed']}; border-color: {t['focus']}; }}
        QPushButton:checked {{ color: {t['text']}; background: {t['accent']}; }}
        QPushButton[hhRole="danger"] {{ color: {t['danger']}; background: {t['danger_soft']}; }}
        QPushButton[hhRole="primaryAction"] {{ color: {t['text']}; background: {t['accent']}; font-weight: 600; }}
        QPushButton[hhRole="folderAction"] {{ color: {t['muted']}; background: {t['surface_raised']}; }}
        QLabel[hhState="error"] {{ color: {t['danger']}; }}
        QLabel[hhState="success"] {{ color: {t['success']}; }}
        QLabel[hhState="warning"] {{ color: {t['warning']}; }}
        QLabel[hhState="default"] {{ color: {t['muted']}; }}
        QToolTip {{ background: {t['surface_raised']}; color: {t['text']}; border: none; padding: 5px; }}
        """
    )
