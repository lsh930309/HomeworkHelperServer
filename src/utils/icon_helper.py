"""
아이콘 경로 해석 유틸리티

시스템 프리셋과 사용자 프리셋의 스태미나/재화 아이콘 경로를 관리합니다.
"""

import os
from typing import Optional
from src.utils.common import get_bundle_resource_path, get_app_data_dir


def resolve_preset_icon_path(icon_path: str, icon_type: str = "system") -> Optional[str]:
    """
    프리셋 스태미나 아이콘 경로를 실제 파일 경로로 변환

    Args:
        icon_path: 아이콘 파일명 (예: "honkai_starrail_stamina.png")
                   시스템/사용자 모두 파일명만 저장됨
        icon_type: "system" (번들 리소스) 또는 "user" (사용자 커스텀)

    Returns:
        절대 경로 또는 None (파일이 없으면)
    """
    if not icon_path:
        return None

    if icon_type == "system":
        # PyInstaller 번들 또는 개발 환경 경로
        # assets/icons/games/ 디렉토리에서 파일 찾기
        relative_path = os.path.join("assets", "icons", "games", icon_path)
        full_path = get_bundle_resource_path(relative_path)
    elif icon_type == "user":
        # %APPDATA%/HomeworkHelper/custom_icons/
        custom_icons_dir = os.path.join(get_app_data_dir(), "custom_icons")
        full_path = os.path.join(custom_icons_dir, icon_path)
    else:
        return None

    # 파일 존재 여부 확인
    if os.path.exists(full_path):
        return full_path
    return None


def ensure_custom_icons_directory() -> str:
    """사용자 커스텀 아이콘 디렉토리 생성 (없으면)

    Returns:
        커스텀 아이콘 디렉토리 절대 경로
    """
    custom_icons_dir = os.path.join(get_app_data_dir(), "custom_icons")
    os.makedirs(custom_icons_dir, exist_ok=True)
    return custom_icons_dir
