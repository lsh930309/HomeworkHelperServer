#!/usr/bin/env python3
"""
label-studio 모듈용 유틸리티 함수
PyInstaller 패키징 환경 지원을 위한 경로 처리
"""

import sys
from pathlib import Path


def get_label_studio_root() -> Path:
    """
    label-studio 폴더의 루트 경로를 반환합니다.
    개발 환경과 PyInstaller 환경 모두에서 동작합니다.

    Returns:
        Path: label-studio 폴더의 절대 경로
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller로 패키징된 경우, _internal/label-studio 폴더
        # sys.executable은 homework_helper.exe를 가리킴
        return Path(sys.executable).parent / "_internal" / "label-studio"
    else:
        # 개발 환경의 경우, 이 파일(utils.py)의 위치를 기준으로 상대 경로 계산
        # utils.py -> core -> gui -> label-studio
        return Path(__file__).parent.parent.parent


def get_resource_path(relative_path: str) -> Path:
    """
    label-studio 내의 리소스 파일 절대 경로를 반환합니다.

    Args:
        relative_path: label-studio 루트로부터의 상대 경로

    Returns:
        Path: 리소스 파일의 절대 경로

    Example:
        >>> get_resource_path("config/class-mapping.json")
        Path("C:/Program Files/HomeworkHelper/_internal/label-studio/config/class-mapping.json")
    """
    return get_label_studio_root() / relative_path
