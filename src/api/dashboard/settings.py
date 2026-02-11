# dashboard/settings.py
"""대시보드 설정 관리"""

import json
import os

SETTINGS_DIR = os.path.join(os.getenv('APPDATA', os.path.expanduser('~')), 'HomeworkHelper')
SETTINGS_FILE = os.path.join(SETTINGS_DIR, 'dashboard_settings.json')

DEFAULT_SETTINGS = {
    "theme": "auto",
    "toolbar": "top",
    "chartType": "bar",
    "stackMode": "stacked",
    "period": "week",
    "calendarThreshold": 10,
    "showUnregistered": False,
    "showChartIcons": True
}


def load_settings() -> dict:
    """AppData에서 설정 로드"""
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                return {**DEFAULT_SETTINGS, **json.load(f)}
    except Exception:
        pass
    return DEFAULT_SETTINGS.copy()


def save_settings(settings: dict) -> None:
    """AppData에 설정 저장"""
    os.makedirs(SETTINGS_DIR, exist_ok=True)
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)
