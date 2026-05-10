"""Design tokens and QSS for the PyQt v2 GUI."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtGui import QPalette
from PyQt6.QtWidgets import QApplication


@dataclass(frozen=True)
class V2Palette:
    bg: str
    panel: str
    panel_alt: str
    text: str
    muted: str
    line: str
    accent: str
    accent_soft: str
    good: str
    warn: str
    danger: str
    button_bg: str
    button_hover: str
    input_bg: str
    shadow: str


LIGHT = V2Palette(
    bg="#f6f7fb",
    panel="#ffffff",
    panel_alt="#eef2ff",
    text="#172033",
    muted="#667085",
    line="#dbe3f0",
    accent="#4f46e5",
    accent_soft="#eef2ff",
    good="#15803d",
    warn="#b45309",
    danger="#dc2626",
    button_bg="#f8fafc",
    button_hover="#eef2ff",
    input_bg="#ffffff",
    shadow="rgba(15, 23, 42, 0.10)",
)

DARK = V2Palette(
    bg="#101522",
    panel="#171f2f",
    panel_alt="#1f2a44",
    text="#e8eefb",
    muted="#9aa8bd",
    line="#334155",
    accent="#8b93ff",
    accent_soft="#263154",
    good="#42d27d",
    warn="#f59e0b",
    danger="#fb7185",
    button_bg="#202a3c",
    button_hover="#283650",
    input_bg="#111827",
    shadow="rgba(0, 0, 0, 0.28)",
)


def is_dark_theme(theme: str = "system") -> bool:
    if theme == "dark":
        return True
    if theme == "light":
        return False
    app = QApplication.instance()
    if not app:
        return False
    palette = app.palette()
    return (
        palette.color(QPalette.ColorRole.WindowText).lightness()
        > palette.color(QPalette.ColorRole.Window).lightness()
    )


def palette_for_theme(theme: str = "system") -> V2Palette:
    return DARK if is_dark_theme(theme) else LIGHT


def build_v2_qss(theme: str = "system") -> str:
    p = palette_for_theme(theme)
    return f"""
        QMainWindow#HomeworkHelperV2 {{
            background: {p.bg};
            color: {p.text};
        }}
        QWidget#V2Central {{
            background: {p.bg};
            color: {p.text};
        }}
        QFrame#V2ShellFrame {{
            background: {p.panel};
            border: 1px solid {p.line};
            border-radius: 18px;
        }}
        QFrame#V2Topbar {{
            background: {p.panel_alt};
            border: 1px solid {p.line};
            border-radius: 16px;
        }}
        QFrame#V2MessageBanner {{
            background: {p.accent_soft};
            border: 1px solid {p.line};
            border-radius: 13px;
        }}
        QLabel#V2Brand {{
            color: {p.accent};
            font-size: 10px;
            font-weight: 800;
            letter-spacing: 1px;
        }}
        QLabel#V2Title {{
            color: {p.text};
            font-size: 19px;
            font-weight: 900;
        }}
        QLabel#V2Subtitle,
        QLabel#V2BannerDetail {{
            color: {p.muted};
            font-size: 11px;
        }}
        QLabel#V2BannerSummary {{
            color: {p.text};
            font-weight: 800;
        }}
        QPushButton, QToolButton {{
            min-height: 30px;
            padding: 4px 10px;
            border: 1px solid {p.line};
            border-radius: 10px;
            background: {p.button_bg};
            color: {p.text};
            font-weight: 800;
        }}
        QPushButton:hover, QToolButton:hover {{
            background: {p.button_hover};
            border-color: {p.accent};
        }}
        QPushButton#V2PrimaryButton, QToolButton#V2PrimaryButton {{
            background: {p.accent};
            border-color: {p.accent};
            color: white;
        }}
        QPushButton#V2IconButton, QToolButton#V2IconButton {{
            min-width: 34px;
            padding-left: 7px;
            padding-right: 7px;
        }}
        QPushButton[v2State="due"] {{
            border-color: {p.danger};
            color: {p.danger};
            background: {p.panel};
        }}
        QPushButton[v2State="done"] {{
            border-color: {p.good};
            color: {p.good};
            background: {p.panel};
        }}
        QPushButton[v2State="default"] {{
            border-color: {p.line};
            color: {p.text};
            background: {p.button_bg};
        }}
        QTableWidget#V2ProcessTable {{
            background: transparent;
            border: none;
            gridline-color: transparent;
            selection-background-color: transparent;
            alternate-background-color: {p.panel_alt};
            color: {p.text};
        }}
        QTableWidget#V2ProcessTable::item {{
            border: none;
            padding: 4px;
        }}
        QHeaderView::section {{
            background: transparent;
            border: none;
            border-bottom: 1px solid {p.line};
            color: {p.muted};
            padding: 5px 6px;
            font-size: 10px;
            font-weight: 800;
        }}
        QProgressBar {{
            min-height: 18px;
            border: 1px solid {p.line};
            border-radius: 9px;
            text-align: center;
            background-color: {p.input_bg};
            color: {p.text};
            font-size: 10px;
            font-weight: 800;
        }}
        QProgressBar::chunk {{
            border-radius: 8px;
        }}
        QMenuBar {{
            background: {p.bg};
            color: {p.muted};
        }}
        QMenuBar::item:selected {{
            background: {p.panel_alt};
            color: {p.text};
        }}
        QStatusBar {{
            background: {p.bg};
            color: {p.muted};
        }}
        QDialog {{
            background: {p.bg};
            color: {p.text};
        }}
        QTabWidget::pane {{
            border: 1px solid {p.line};
            border-radius: 12px;
            background: {p.panel};
        }}
        QTabBar::tab {{
            padding: 8px 12px;
            margin-right: 4px;
            border: 1px solid {p.line};
            border-bottom: none;
            border-top-left-radius: 9px;
            border-top-right-radius: 9px;
            background: {p.button_bg};
            color: {p.muted};
        }}
        QTabBar::tab:selected {{
            background: {p.panel};
            color: {p.text};
            border-color: {p.accent};
        }}
        QGroupBox {{
            border: 1px solid {p.line};
            border-radius: 12px;
            margin-top: 12px;
            padding: 10px;
            background: {p.panel};
            font-weight: 800;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 12px;
            padding: 0 4px;
            color: {p.accent};
        }}
        QLineEdit, QTimeEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
            min-height: 28px;
            border: 1px solid {p.line};
            border-radius: 8px;
            padding: 3px 7px;
            background: {p.input_bg};
            color: {p.text};
        }}
    """


def progress_chunk_color(percentage: float, theme: str = "system") -> str:
    p = palette_for_theme(theme)
    if percentage >= 100:
        return p.danger
    if percentage >= 80:
        return p.warn
    if percentage >= 50:
        return "#eab308"
    return p.good

