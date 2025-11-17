#!/usr/bin/env python3
"""
스키마 마이그레이션 스크립트
기존 통합 JSON 파일을 게임별 디렉토리 구조로 분리
"""

import json
import os
from pathlib import Path

# 프로젝트 루트 디렉토리
ROOT_DIR = Path(__file__).parent.parent
SCHEMAS_DIR = ROOT_DIR / "schemas"
OLD_SCHEMAS_DIR = SCHEMAS_DIR / "old"
GAMES_DIR = SCHEMAS_DIR / "games"

# 게임 ID 목록
GAME_IDS = [
    "zenless_zone_zero",
    "honkai_star_rail",
    "wuthering_waves",
    "nikke"
]


def load_json(file_path: Path) -> dict:
    """JSON 파일 로드"""
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(file_path: Path, data: dict, indent: int = 2):
    """JSON 파일 저장"""
    file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)
    print(f"✅ Saved: {file_path}")


def migrate_resources():
    """재화 데이터 마이그레이션"""
    print("\n📦 Migrating resources...")

    old_file = SCHEMAS_DIR / "game_resources.json"
    data = load_json(old_file)

    for game_id in GAME_IDS:
        if game_id not in data["games"]:
            print(f"⚠️  Game '{game_id}' not found in resources")
            continue

        game_data = data["games"][game_id]

        # 새 구조로 변환
        new_data = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "Game Resources",
            "description": f"{game_data['game_name_kr']} 재화 정의",
            "version": "1.0.0",
            "game_id": game_data["game_id"],
            "game_name": game_data["game_name"],
            "game_name_kr": game_data["game_name_kr"],
            "resources": game_data["resources"]
        }

        output_file = GAMES_DIR / game_id / "resources.json"
        save_json(output_file, new_data)


def migrate_contents():
    """콘텐츠 데이터 마이그레이션"""
    print("\n🎮 Migrating contents...")

    old_file = SCHEMAS_DIR / "game_contents.json"
    data = load_json(old_file)

    for game_id in GAME_IDS:
        if game_id not in data["games"]:
            print(f"⚠️  Game '{game_id}' not found in contents")
            continue

        game_data = data["games"][game_id]

        # 새 구조로 변환
        new_data = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "Game Contents",
            "description": f"{game_data['game_name_kr']} 콘텐츠 정의",
            "version": "1.0.0",
            "game_id": game_data["game_id"],
            "game_name": game_data["game_name"],
            "game_name_kr": game_data["game_name_kr"],
            "contents": game_data["contents"]
        }

        output_file = GAMES_DIR / game_id / "contents.json"
        save_json(output_file, new_data)


def migrate_ui_elements():
    """UI 요소 데이터 마이그레이션"""
    print("\n🖼️  Migrating UI elements...")

    old_file = SCHEMAS_DIR / "ui_elements.json"
    data = load_json(old_file)

    for game_id in GAME_IDS:
        if game_id not in data["games"]:
            print(f"⚠️  Game '{game_id}' not found in ui_elements")
            continue

        game_data = data["games"][game_id]

        # 새 구조로 변환
        new_data = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "UI Elements",
            "description": f"{game_data['game_name_kr']} UI 요소 정의 (YOLO 탐지 대상)",
            "version": "1.0.0",
            "game_id": game_data["game_id"],
            "game_name": game_data["game_name"],
            "game_name_kr": game_data["game_name_kr"],
            "ui_elements": game_data["ui_elements"]
        }

        output_file = GAMES_DIR / game_id / "ui_elements.json"
        save_json(output_file, new_data)


def create_metadata():
    """각 게임별 metadata.json 생성"""
    print("\n📄 Creating metadata files...")

    # 기존 파일에서 게임 정보 추출
    resources_data = load_json(SCHEMAS_DIR / "game_resources.json")

    for game_id in GAME_IDS:
        if game_id not in resources_data["games"]:
            continue

        game_info = resources_data["games"][game_id]

        metadata = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "Game Metadata",
            "description": "게임 기본 정보 및 설정",
            "version": "1.0.0",
            "game_id": game_info["game_id"],
            "game_name": game_info["game_name"],
            "game_name_kr": game_info["game_name_kr"],
            "schema_version": "1.0.0",
            "enabled": True,
            "last_updated": "2025-11-14",
            "process_patterns": [],  # 나중에 채울 것
            "window_title_patterns": [],
            "verification_status": {
                "resources_verified": False,
                "contents_verified": False,
                "ui_elements_verified": False
            },
            "notes": "한국어 명칭 검증 필요"
        }

        output_file = GAMES_DIR / game_id / "metadata.json"
        save_json(output_file, metadata)


def create_registry():
    """registry.json 생성"""
    print("\n📋 Creating registry.json...")

    # 기존 파일에서 게임 정보 추출
    resources_data = load_json(SCHEMAS_DIR / "game_resources.json")

    games_list = []

    # 프로세스 패턴 정의 (수동으로 작성)
    process_patterns_map = {
        "zenless_zone_zero": {
            "process_patterns": [
                "ZenlessZoneZero.exe",
                "Zenless.exe",
                "*zenless*.exe"
            ],
            "window_title_patterns": [
                "Zenless Zone Zero",
                "젠레스 존 제로"
            ]
        },
        "honkai_star_rail": {
            "process_patterns": [
                "StarRail.exe",
                "HonkaiStarRail.exe",
                "*starrail*.exe"
            ],
            "window_title_patterns": [
                "Honkai: Star Rail",
                "붕괴: 스타레일"
            ]
        },
        "wuthering_waves": {
            "process_patterns": [
                "Wuthering Waves.exe",
                "WutheringWaves.exe",
                "Client-Win64-Shipping.exe"
            ],
            "window_title_patterns": [
                "Wuthering Waves",
                "명조: 워더링 웨이브",
                "鸣潮"
            ]
        },
        "nikke": {
            "process_patterns": [
                "NIKKE.exe",
                "*nikke*.exe"
            ],
            "window_title_patterns": [
                "GODDESS OF VICTORY: NIKKE",
                "승리의 여신: 니케"
            ]
        }
    }

    for game_id in GAME_IDS:
        if game_id not in resources_data["games"]:
            continue

        game_info = resources_data["games"][game_id]
        patterns = process_patterns_map.get(game_id, {
            "process_patterns": [],
            "window_title_patterns": []
        })

        game_entry = {
            "game_id": game_info["game_id"],
            "game_name": game_info["game_name"],
            "game_name_kr": game_info["game_name_kr"],
            "schema_version": "1.0.0",
            "enabled": True,
            "process_patterns": patterns["process_patterns"],
            "window_title_patterns": patterns["window_title_patterns"],
            "last_updated": "2025-11-14"
        }

        games_list.append(game_entry)

    registry = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "Game Registry",
        "description": "게임 목록 및 프로세스 매칭 정보",
        "version": "1.0.0",
        "games": games_list
    }

    output_file = SCHEMAS_DIR / "registry.json"
    save_json(output_file, registry)


def backup_old_files():
    """기존 파일 백업"""
    print("\n💾 Backing up old files...")

    OLD_SCHEMAS_DIR.mkdir(exist_ok=True)

    old_files = [
        "game_resources.json",
        "game_contents.json",
        "ui_elements.json"
    ]

    for filename in old_files:
        src = SCHEMAS_DIR / filename
        dst = OLD_SCHEMAS_DIR / filename

        if src.exists():
            import shutil
            shutil.copy2(src, dst)
            print(f"✅ Backed up: {filename}")


def main():
    """메인 실행 함수"""
    print("=" * 60)
    print("🚀 Schema Migration Script")
    print("=" * 60)

    # 1. 기존 파일 백업
    backup_old_files()

    # 2. 데이터 마이그레이션
    migrate_resources()
    migrate_contents()
    migrate_ui_elements()

    # 3. 메타데이터 생성
    create_metadata()

    # 4. 레지스트리 생성
    create_registry()

    print("\n" + "=" * 60)
    print("✅ Migration completed successfully!")
    print("=" * 60)

    print("\n📁 New structure:")
    print("schemas/")
    print("├── registry.json")
    print("├── games/")
    for game_id in GAME_IDS:
        print(f"│   ├── {game_id}/")
        print(f"│   │   ├── metadata.json")
        print(f"│   │   ├── resources.json")
        print(f"│   │   ├── contents.json")
        print(f"│   │   └── ui_elements.json")
    print("└── old/  (backup)")

    print("\n⚠️  Next steps:")
    print("1. 기존 파일 삭제: rm schemas/game_*.json")
    print("2. 한국어 명칭 검증 GUI 실행")
    print("3. Git 커밋 및 푸시")


if __name__ == "__main__":
    main()
