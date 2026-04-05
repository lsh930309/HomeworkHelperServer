"""공통 GUI 스타일 토큰과 QSS 헬퍼."""

from __future__ import annotations

from typing import Final

PANEL_BG: Final[str] = "rgba(12, 12, 16, 240)"
POPOVER_BG: Final[str] = "#0c0c10"
PANEL_BORDER: Final[str] = "rgba(180, 200, 255, 18)"
POPOVER_BORDER: Final[str] = "rgba(180,200,255,22)"

SURFACE_SOFT: Final[str] = "rgba(255,255,255,5)"
SURFACE_SOFT_ALT: Final[str] = "rgba(255,255,255,6)"
SURFACE_BUTTON: Final[str] = "rgba(255,255,255,10)"
SURFACE_BUTTON_ALT: Final[str] = "rgba(255,255,255,12)"
SURFACE_BUTTON_HOVER: Final[str] = "rgba(255,255,255,22)"
SURFACE_BUTTON_PRESSED: Final[str] = "rgba(255,255,255,8)"
SURFACE_ICON: Final[str] = "rgba(255,255,255,8)"
SURFACE_ICON_BORDER: Final[str] = "rgba(255,255,255,12)"
SURFACE_TRACK: Final[str] = "rgba(255,255,255,28)"
SURFACE_SCROLLBAR: Final[str] = "rgba(255,255,255,60)"

TEXT_PRIMARY: Final[str] = "rgba(220,230,255,240)"
TEXT_EMPHASIS: Final[str] = "rgba(235,240,255,240)"
TEXT_SECONDARY: Final[str] = "rgba(200,210,235,200)"
TEXT_TERTIARY: Final[str] = "rgba(160,180,220,180)"
TEXT_SECTION: Final[str] = "rgba(150,170,210,160)"
TEXT_SECTION_STRONG: Final[str] = "rgba(150,170,210,200)"
TEXT_BUTTON_MUTED: Final[str] = "rgba(255,255,255,160)"
TEXT_BUTTON_ACCENT: Final[str] = "rgba(180,200,240,200)"
TEXT_MUTED: Final[str] = "rgba(255,255,255,80)"
TEXT_MUTED_STRONG: Final[str] = "rgba(255,255,255,100)"

BORDER_SOFT: Final[str] = "rgba(255,255,255,10)"
BORDER_DEFAULT: Final[str] = "rgba(255,255,255,15)"
BORDER_STRONG: Final[str] = "rgba(255,255,255,18)"
BORDER_ACCENT: Final[str] = "rgba(255,255,255,22)"
BORDER_DASHED: Final[str] = "rgba(255,255,255,25)"
BORDER_HIGHLIGHT: Final[str] = "rgba(100,160,255,180)"

ACCENT_BLUE: Final[str] = "rgba(80,130,220,160)"
ACCENT_BLUE_BORDER: Final[str] = "rgba(100,160,255,180)"
ACCENT_BLUE_START: Final[str] = "rgba(100,160,255,200)"
ACCENT_BLUE_END: Final[str] = "rgba(140,190,255,220)"

STATUS_ACTIVE: Final[str] = "rgba(80,200,120,220)"
STATUS_RECORDING: Final[str] = "#e05555"
STATUS_SUCCESS: Final[str] = "#5aaa5a"
STATUS_WARNING: Final[str] = "#aaa850"
STATUS_DISABLED: Final[str] = "#888"

DANGER_BG: Final[str] = "rgba(160, 30, 30, 160)"
DANGER_BG_HOVER: Final[str] = "rgba(200, 40, 40, 200)"
DANGER_BG_PRESSED: Final[str] = "rgba(130, 20, 20, 220)"
DANGER_TEXT: Final[str] = "rgba(255,200,200,220)"
DANGER_BORDER: Final[str] = "rgba(200, 60, 60, 120)"

PROGRESS_BG: Final[str] = "#2d2d2d"
PROGRESS_BORDER: Final[str] = "#404040"
PROGRESS_TEXT: Final[str] = "white"

PREVIEW_BORDER: Final[str] = "#ccc"
PREVIEW_BG: Final[str] = "white"
PRIMARY_ACTION_BG: Final[str] = "#e1f5fe"
PRIMARY_ACTION_BG_HOVER: Final[str] = "#cbefff"
PRIMARY_ACTION_BORDER: Final[str] = "#a7ddf2"


def text_style(
    *,
    color: str,
    font_size: int,
    font_weight: int | str | None = None,
    letter_spacing: int | None = None,
    background: str | None = None,
    padding: int | None = None,
) -> str:
    """간단한 텍스트 스타일 시트를 생성합니다."""
    parts = [f"color: {color}", f"font-size: {font_size}px"]
    if font_weight is not None:
        parts.append(f"font-weight: {font_weight}")
    if letter_spacing is not None:
        parts.append(f"letter-spacing: {letter_spacing}px")
    if background is not None:
        parts.append(f"background: {background}")
    if padding is not None:
        parts.append(f"padding: {padding}px")
    return "; ".join(parts) + ";"


SLIDER_STYLE: Final[str] = f"""
QSlider::groove:horizontal {{
    height: 4px;
    background: {SURFACE_TRACK};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {ACCENT_BLUE_START}, stop:1 {ACCENT_BLUE_END});
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: rgba(220,230,255,240);
    border: none;
    width: 12px;
    height: 12px;
    border-radius: 6px;
    margin: -4px 0;
}}
QSlider::handle:horizontal:hover {{
    background: white;
}}
"""


def mute_button_stylesheet(*, font_size: int, border_radius: int) -> str:
    """공통 음소거 버튼 스타일을 반환합니다."""
    return f"""
QPushButton {{
    border: 1px solid {BORDER_ACCENT};
    border-radius: {border_radius}px;
    background: {SURFACE_BUTTON};
    color: white;
    font-size: {font_size}px;
}}
QPushButton:checked {{
    background: {ACCENT_BLUE};
    border-color: {ACCENT_BLUE_BORDER};
    color: white;
}}
QPushButton:hover:!checked {{
    background: {SURFACE_BUTTON_HOVER};
    color: white;
}}
QPushButton:disabled {{
    color: rgba(255,255,255,60);
    border-color: rgba(255,255,255,15);
}}
"""


def popover_panel_stylesheet(object_name: str = "VolumePopoverPanel") -> str:
    """볼륨 팝오버 패널 스타일을 반환합니다."""
    return f"""
{object_name} {{
    border: 1px solid {POPOVER_BORDER};
    border-radius: 8px;
    background-color: {POPOVER_BG};
}}
"""


def sidebar_frame_stylesheet(object_name: str = "SidebarFrame") -> str:
    """사이드바 외곽 프레임 스타일을 반환합니다."""
    return f"""
QFrame#{object_name} {{
    background-color: {PANEL_BG};
    border-left: 1px solid {PANEL_BORDER};
    border-radius: 0px;
}}
"""


def transparent_scroll_area_stylesheet(content_object_name: str = "scroll_content") -> str:
    """투명 스크롤 영역 스타일을 반환합니다."""
    return f"""
QScrollArea {{ border: none; background: transparent; }}
QWidget#{content_object_name} {{ background: transparent; }}
QScrollBar:vertical {{
    width: 4px; background: transparent; border-radius: 2px;
}}
QScrollBar::handle:vertical {{
    background: {SURFACE_SCROLLBAR}; border-radius: 2px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}
"""


def subtle_outline_button_stylesheet(*, font_size: int, border_radius: int = 4) -> str:
    """은은한 테두리 버튼 스타일을 반환합니다."""
    return f"""
QPushButton {{
    background: {SURFACE_BUTTON};
    color: {TEXT_BUTTON_MUTED};
    border: 1px solid {BORDER_STRONG};
    border-radius: {border_radius}px;
    font-size: {font_size}px;
}}
QPushButton:hover {{
    background: {SURFACE_BUTTON_HOVER};
    color: white;
}}
"""


def accent_outline_button_stylesheet(*, font_size: int, border_radius: int = 5) -> str:
    """보조 강조 버튼 스타일을 반환합니다."""
    return f"""
QPushButton {{
    background: {SURFACE_BUTTON_ALT};
    color: {TEXT_BUTTON_ACCENT};
    border: 1px solid {BORDER_DASHED};
    border-radius: {border_radius}px;
    font-size: {font_size}px;
}}
QPushButton:hover {{ background: {SURFACE_BUTTON_HOVER}; color: white; }}
QPushButton:pressed {{ background: {SURFACE_BUTTON_PRESSED}; }}
"""


def dashed_tile_button_stylesheet(*, font_size: int, border_radius: int = 3) -> str:
    """스크린샷 폴더 버튼용 점선 타일 스타일을 반환합니다."""
    return f"""
QPushButton {{
    background: {SURFACE_ICON};
    color: {TEXT_BUTTON_ACCENT};
    border: 1px dashed {BORDER_DASHED};
    border-radius: {border_radius}px;
    font-size: {font_size}px;
}}
QPushButton:hover {{ background: {BORDER_STRONG}; color: white; }}
"""


def danger_button_stylesheet(*, font_size: int, border_radius: int = 5) -> str:
    """위험 액션 버튼 스타일을 반환합니다."""
    return f"""
QPushButton {{
    background: {DANGER_BG};
    color: {DANGER_TEXT};
    border: 1px solid {DANGER_BORDER};
    border-radius: {border_radius}px;
    font-size: {font_size}px;
}}
QPushButton:hover  {{ background: {DANGER_BG_HOVER}; color: white; }}
QPushButton:pressed {{ background: {DANGER_BG_PRESSED}; }}
"""


def card_stylesheet() -> str:
    """카드형 컨테이너 스타일을 반환합니다."""
    return (
        f"QWidget {{ background: {SURFACE_SOFT}; border: 1px solid {BORDER_SOFT}; border-radius: 8px; }}"
    )


def icon_frame_stylesheet() -> str:
    """아이콘 프레임 스타일을 반환합니다."""
    return (
        f"background: {SURFACE_ICON}; border: 1px solid {SURFACE_ICON_BORDER}; border-radius: 10px;"
    )


def preview_frame_stylesheet() -> str:
    """프리셋 아이콘 미리보기 프레임 스타일을 반환합니다."""
    return f"border: 1px solid {PREVIEW_BORDER}; background: {PREVIEW_BG};"


def primary_action_button_stylesheet() -> str:
    """기본 강조 액션 버튼 스타일을 반환합니다."""
    return f"font-weight: bold; background-color: {PRIMARY_ACTION_BG};"


def primary_toolbar_button_stylesheet() -> str:
    """메인 창 상단의 핵심 액션 버튼 스타일을 반환합니다."""
    return f"""
QPushButton {{
    background: {PRIMARY_ACTION_BG};
    border: 1px solid {PRIMARY_ACTION_BORDER};
    border-radius: 7px;
    padding: 6px 12px;
    font-weight: 600;
}}
QPushButton:hover {{
    background: {PRIMARY_ACTION_BG_HOVER};
}}
QPushButton:pressed {{
    background: {PRIMARY_ACTION_BORDER};
}}
"""


def compact_icon_button_stylesheet() -> str:
    """메인 창의 작은 아이콘 액션 버튼 스타일을 반환합니다."""
    return """
QPushButton {
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 7px;
    padding: 4px 8px;
    font-weight: 600;
}
QPushButton:hover {
    background: palette(button);
    border-color: palette(mid);
}
QPushButton:pressed {
    background: palette(midlight);
}
"""


def secondary_table_button_stylesheet() -> str:
    """테이블 내부의 보조 액션 버튼 스타일을 반환합니다."""
    return """
QPushButton {
    background: palette(button);
    border: 1px solid palette(midlight);
    border-radius: 6px;
    padding: 4px 10px;
    font-weight: 500;
}
QPushButton:hover {
    background: palette(midlight);
    border-color: palette(mid);
}
QPushButton:pressed {
    background: palette(mid);
}
"""


def menu_tool_button_stylesheet() -> str:
    """메뉴바 우측 볼륨 토글 버튼 스타일을 반환합니다."""
    return """
QToolButton {
    border: 1px solid transparent;
    border-radius: 4px;
    background: transparent;
    padding: 2px 6px;
}
QToolButton:hover {
    background: palette(midlight);
    border-color: palette(mid);
}
QToolButton:checked {
    background: palette(highlight);
    color: palette(highlighted-text);
    border-color: palette(highlight);
}
QToolButton:pressed {
    background: palette(dark);
}
"""


def toolbar_frame_stylesheet(object_name: str = "TopActionBar") -> str:
    """메인 창 상단 액션 프레임 스타일을 반환합니다."""
    return f"""
QFrame#{object_name} {{
    background: palette(base);
    border: 1px solid palette(midlight);
    border-radius: 10px;
}}
"""


def summary_chip_stylesheet(kind: str = "neutral") -> str:
    """요약 칩 스타일을 반환합니다."""
    presets = {
        "neutral": ("rgba(120, 140, 180, 40)", "rgba(120, 140, 180, 80)", "palette(window-text)"),
        "running": ("rgba(255, 210, 90, 60)", "rgba(255, 210, 90, 110)", "palette(window-text)"),
        "attention": ("rgba(255, 105, 105, 60)", "rgba(255, 105, 105, 110)", "palette(window-text)"),
        "completed": ("rgba(110, 200, 140, 55)", "rgba(110, 200, 140, 105)", "palette(window-text)"),
    }
    background, border, color = presets.get(kind, presets["neutral"])
    return f"""
QLabel {{
    background: {background};
    border: 1px solid {border};
    border-radius: 9px;
    color: {color};
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 500;
}}
"""


def status_badge_stylesheet(status: str) -> str:
    """상태 문자열에 맞는 배지 스타일을 반환합니다."""
    presets = {
        "실행중": ("rgba(255, 213, 79, 70)", "rgba(255, 213, 79, 140)", "palette(window-text)"),
        "미완료": ("rgba(239, 83, 80, 70)", "rgba(239, 83, 80, 140)", "palette(window-text)"),
        "완료됨": ("rgba(102, 187, 106, 70)", "rgba(102, 187, 106, 140)", "palette(window-text)"),
    }
    background, border, color = presets.get(
        status,
        ("rgba(120, 140, 180, 40)", "rgba(120, 140, 180, 80)", "palette(window-text)"),
    )
    return f"""
QLabel {{
    background: {background};
    border: 1px solid {border};
    border-radius: 8px;
    color: {color};
    padding: 3px 8px;
    font-size: 11px;
    font-weight: 600;
}}
"""


def main_table_stylesheet() -> str:
    """메인 프로세스 테이블 스타일을 반환합니다."""
    return """
QTableWidget {
    border: 1px solid palette(midlight);
    border-radius: 10px;
    gridline-color: transparent;
    padding: 2px;
}
QHeaderView::section {
    background: palette(button);
    border: none;
    border-bottom: 1px solid palette(midlight);
    padding: 6px 8px;
    font-weight: 600;
}
QTableWidget::item {
    padding: 4px 6px;
}
"""


def progress_placeholder_label_stylesheet() -> str:
    """진행률 정보가 없을 때 사용하는 보조 라벨 스타일을 반환합니다."""
    return (
        "color: palette(mid); font-size: 11px; font-weight: 500; padding-left: 2px;"
    )


def progress_bar_stylesheet(chunk_color: str) -> str:
    """메인 진행률 바 공통 스타일을 반환합니다."""
    return f"""
QProgressBar {{
    border: 1px solid {PROGRESS_BORDER};
    border-radius: 2px;
    text-align: center;
    background-color: {PROGRESS_BG};
    color: {PROGRESS_TEXT};
    font-weight: bold;
}}
QProgressBar::chunk {{
    background-color: {chunk_color};
    border-radius: 1px;
}}
"""


def thumbnail_button_stylesheet(border_radius: int = 3) -> str:
    """스크린샷 썸네일 셀 스타일을 반환합니다."""
    return f"""
QPushButton {{
    background: {SURFACE_SOFT_ALT};
    border: 1px solid {BORDER_DEFAULT};
    border-radius: {border_radius}px;
    padding: 0;
}}
QPushButton:hover {{ border-color: {BORDER_HIGHLIGHT}; }}
"""


def web_shortcut_button_stylesheet(state: str, *, red: str, green: str) -> str:
    """웹 바로가기 버튼 상태에 맞는 스타일을 반환합니다."""
    background = "palette(button)"
    border = "palette(midlight)"
    color = "palette(button-text)"
    if state == "RED":
        background = red
        border = red
        color = "white"
    elif state == "GREEN":
        background = green
        border = green
        color = "white"
    return f"""
QPushButton {{
    background: {background};
    color: {color};
    border: 1px solid {border};
    border-radius: 7px;
    padding: 4px 10px;
    font-weight: 600;
}}
QPushButton:hover {{
    border-color: palette(highlight);
}}
QPushButton:pressed {{
    background: palette(midlight);
}}
"""
