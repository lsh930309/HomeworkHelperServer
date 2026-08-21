"""Restrained Fluent-inspired styling for the existing QWidget surface."""
from __future__ import annotations

from PySide6.QtWidgets import QMainWindow


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
        central.layout().setContentsMargins(14, 12, 14, 14)
        central.layout().setSpacing(10)

    surface = "#202124" if dark else "#f5f6f8"
    card = "#292b2f" if dark else "#ffffff"
    card_hover = "#32353a" if dark else "#f3f6fb"
    border = "#3c4047" if dark else "#d8dce3"
    text = "#f2f3f5" if dark else "#202124"
    muted = "#aeb4bf" if dark else "#667085"
    accent = "#6ea8fe" if dark else "#2563eb"
    accent_hover = "#8bb9ff" if dark else "#1d4ed8"

    window.setStyleSheet(
        f"""
        QWidget#hhMainSurface {{ background: {surface}; color: {text}; }}
        QMenuBar {{ background: {surface}; color: {text}; padding: 3px 6px; spacing: 4px; }}
        QMenuBar::item {{ padding: 6px 9px; border-radius: 5px; }}
        QMenuBar::item:selected {{ background: {card_hover}; }}
        QStatusBar {{ background: {surface}; color: {muted}; }}
        QPushButton {{
            min-height: 22px; padding: 2px 10px; border-radius: 7px;
            border: 1px solid {border}; background: {card}; color: {text};
        }}
        QPushButton:hover {{ background: {card_hover}; border-color: {accent}; }}
        QPushButton:pressed {{ padding-top: 4px; padding-bottom: 2px; }}
        QPushButton[hhRole="primaryAction"] {{
            min-height: 28px; padding: 3px 12px;
            background: {accent}; border-color: {accent}; color: white; font-weight: 600;
        }}
        QPushButton[hhRole="primaryAction"]:hover {{ background: {accent_hover}; }}
        QPushButton[hhRole="iconAction"] {{ min-width: 28px; padding: 2px; }}
        QTableWidget#processTable {{
            background: {card}; alternate-background-color: {card_hover};
            border: 1px solid {border}; border-radius: 10px; gridline-color: transparent;
            outline: none; padding: 4px;
        }}
        QTableWidget#processTable::item {{ border: none; padding: 4px; }}
        QProgressBar {{
            min-height: 18px; border: 1px solid {border}; border-radius: 7px;
            background: {surface}; color: {text}; text-align: center;
        }}
        QProgressBar::chunk {{ border-radius: 6px; }}
        QCheckBox {{ color: {text}; spacing: 6px; }}
        QToolTip {{ background: {card}; color: {text}; border: 1px solid {border}; padding: 5px; }}
        """
    )

    # Dynamic properties do not always repolish immediately on Windows.
    for attribute in ("add_game_button", "add_web_shortcut_button", "dashboard_button", "github_button"):
        control = getattr(window, attribute, None)
        if control is not None:
            control.style().unpolish(control)
            control.style().polish(control)
