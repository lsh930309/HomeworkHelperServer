#!/usr/bin/env python3
"""
스키마 관리 유틸리티
게임 스키마 로드, 저장, 자동 감지 등의 기능을 제공합니다.
"""

import json
import fnmatch
import logging
from pathlib import Path
from typing import Optional, Dict, List, Any

logger = logging.getLogger(__name__)


def get_schemas_dir() -> Path:
    """
    스키마 디렉토리 경로 반환

    Returns:
        Path: schemas 디렉토리 경로
    """
    # 프로젝트 루트 디렉토리 자동 감지
    current = Path(__file__).resolve().parent
    for _ in range(5):  # 최대 5단계 상위까지
        schemas_path = current / "schemas"
        if schemas_path.exists():
            return schemas_path
        current = current.parent

    # 찾지 못한 경우 현재 작업 디렉토리 사용
    return Path.cwd() / "schemas"


def load_registry() -> Dict[str, Any]:
    """
    registry.json 로드

    Returns:
        dict: 게임 레지스트리 데이터

    Raises:
        FileNotFoundError: registry.json이 없는 경우
    """
    registry_file = get_schemas_dir() / "registry.json"

    if not registry_file.exists():
        logger.warning(f"registry.json 파일을 찾을 수 없습니다: {registry_file}")
        return {"games": []}

    try:
        with open(registry_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"registry.json 로드 실패: {e}")
        return {"games": []}


def get_available_games() -> List[Dict[str, Any]]:
    """
    사용 가능한 게임 목록 반환

    Returns:
        list: 게임 정보 딕셔너리 목록
        [
            {
                "game_id": "zenless_zone_zero",
                "game_name": "Zenless Zone Zero",
                "game_name_kr": "젠레스 존 제로",
                "enabled": True,
                ...
            },
            ...
        ]
    """
    registry = load_registry()
    games = registry.get("games", [])

    # 활성화된 게임만 필터링
    return [game for game in games if game.get("enabled", True)]


def detect_game_from_path(exe_path: str) -> Optional[str]:
    """
    프로세스 경로에서 게임 스키마 자동 감지

    Args:
        exe_path: 실행 파일 경로 (예: "C:\\...\\ZenlessZoneZero.exe")

    Returns:
        str: 게임 ID (예: "zenless_zone_zero") 또는 None
    """
    if not exe_path:
        return None

    registry = load_registry()
    exe_name = Path(exe_path).name.lower()

    for game in registry.get("games", []):
        if not game.get("enabled", True):
            continue

        # 프로세스 패턴 매칭
        for pattern in game.get("process_patterns", []):
            # 패턴을 소문자로 비교
            if fnmatch.fnmatch(exe_name, pattern.lower()):
                logger.info(f"게임 자동 감지: {exe_path} → {game['game_id']}")
                return game["game_id"]

            # 전체 경로도 매칭 시도
            if fnmatch.fnmatch(exe_path.lower(), f"*{pattern.lower()}"):
                logger.info(f"게임 자동 감지 (경로): {exe_path} → {game['game_id']}")
                return game["game_id"]

    logger.debug(f"게임 자동 감지 실패: {exe_path}")
    return None


def check_schema_exists(game_id: str) -> bool:
    """
    게임 스키마 파일 존재 확인

    Args:
        game_id: 게임 ID

    Returns:
        bool: 모든 필수 파일이 존재하면 True
    """
    if not game_id:
        return False

    schema_dir = get_schemas_dir() / "games" / game_id
    required_files = ["metadata.json", "resources.json", "contents.json", "ui_elements.json"]

    return all((schema_dir / f).exists() for f in required_files)


def load_game_schema(game_id: str, schema_type: str) -> Optional[Dict[str, Any]]:
    """
    게임별 스키마 파일 로드

    Args:
        game_id: 게임 ID (예: "zenless_zone_zero")
        schema_type: 스키마 타입 ("resources", "contents", "ui_elements", "metadata")

    Returns:
        dict: 스키마 데이터 또는 None
    """
    if not game_id or not schema_type:
        return None

    schema_file = get_schemas_dir() / "games" / game_id / f"{schema_type}.json"

    if not schema_file.exists():
        logger.warning(f"스키마 파일을 찾을 수 없습니다: {schema_file}")
        return None

    try:
        with open(schema_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"스키마 로드 실패 ({schema_file}): {e}")
        return None


def save_game_schema(game_id: str, schema_type: str, data: Dict[str, Any]) -> bool:
    """
    게임별 스키마 파일 저장

    Args:
        game_id: 게임 ID
        schema_type: 스키마 타입
        data: 저장할 데이터

    Returns:
        bool: 성공 여부
    """
    if not game_id or not schema_type or not data:
        return False

    schema_file = get_schemas_dir() / "games" / game_id / f"{schema_type}.json"

    try:
        # 디렉토리 생성 (없는 경우)
        schema_file.parent.mkdir(parents=True, exist_ok=True)

        # 저장
        with open(schema_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"스키마 저장 완료: {schema_file}")
        return True

    except Exception as e:
        logger.error(f"스키마 저장 실패 ({schema_file}): {e}")
        return False


def get_game_info(game_id: str) -> Optional[Dict[str, Any]]:
    """
    게임 정보 반환 (registry.json에서)

    Args:
        game_id: 게임 ID

    Returns:
        dict: 게임 정보 또는 None
    """
    registry = load_registry()

    for game in registry.get("games", []):
        if game.get("game_id") == game_id:
            return game

    return None


def get_game_name_kr(game_id: str) -> str:
    """
    게임 한국어 이름 반환

    Args:
        game_id: 게임 ID

    Returns:
        str: 한국어 이름 또는 game_id
    """
    game_info = get_game_info(game_id)
    if game_info:
        return game_info.get("game_name_kr", game_id)
    return game_id
