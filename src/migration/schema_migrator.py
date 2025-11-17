#!/usr/bin/env python3
"""
스키마 자동 마이그레이션 시스템
앱 시작 시 스키마 버전을 체크하고 필요한 마이그레이션을 자동으로 수행합니다.
"""

import json
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple

# 로깅 설정
logger = logging.getLogger(__name__)


class SchemaMigrator:
    """스키마 버전 관리 및 자동 마이그레이션"""

    CURRENT_VERSION = "2.0.0"

    def __init__(self, schemas_dir: Optional[Path] = None):
        """
        Args:
            schemas_dir: 스키마 디렉토리 경로 (기본값: 프로젝트 루트/schemas)
        """
        if schemas_dir is None:
            # 프로젝트 루트 디렉토리 자동 감지
            self.schemas_dir = self._find_schemas_dir()
        else:
            self.schemas_dir = Path(schemas_dir)

        self.version_file = self.schemas_dir / "version.json"
        self.games_dir = self.schemas_dir / "games"

    def _find_schemas_dir(self) -> Path:
        """프로젝트 루트의 schemas 디렉토리 찾기"""
        # 현재 파일 위치에서 상위로 올라가며 schemas 디렉토리 찾기
        current = Path(__file__).resolve().parent
        for _ in range(5):  # 최대 5단계 상위까지
            schemas_path = current / "schemas"
            if schemas_path.exists():
                return schemas_path
            current = current.parent

        # 찾지 못한 경우 기본 경로 반환
        return Path.cwd() / "schemas"

    def check_and_migrate(self) -> bool:
        """
        스키마 버전 체크 및 마이그레이션 실행
        앱 시작 시 호출됩니다.

        Returns:
            bool: 성공 여부
        """
        try:
            logger.info("스키마 버전 체크 시작...")

            current_version = self.get_current_version()
            logger.info(f"현재 스키마 버전: {current_version or 'None'}")

            if current_version == self.CURRENT_VERSION:
                logger.info(f"스키마가 최신 버전입니다 (v{self.CURRENT_VERSION})")
                return True

            if current_version is None:
                logger.info("신규 설치 감지 - 기본 구조 생성")
                return self.handle_fresh_install()

            # 마이그레이션 필요
            logger.info(f"마이그레이션 필요: v{current_version} → v{self.CURRENT_VERSION}")
            return self.migrate(current_version, self.CURRENT_VERSION)

        except Exception as e:
            logger.error(f"스키마 체크/마이그레이션 중 오류: {e}")
            return False

    def get_current_version(self) -> Optional[str]:
        """
        현재 스키마 버전 확인

        감지 방법:
        1. version.json 파일 존재 → 해당 버전 반환
        2. 구 구조(통합 JSON) 존재 → "1.0.0" 반환
        3. 신 구조(games/) 존재 → version.json 생성 후 CURRENT_VERSION 반환
        4. 아무것도 없음 → None (신규 설치)
        """
        # 1. version.json 체크
        if self.version_file.exists():
            try:
                with open(self.version_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("schema_version")
            except Exception as e:
                logger.warning(f"version.json 읽기 실패: {e}")

        # 2. 구 구조 감지 (v1.0.0)
        old_files = [
            self.schemas_dir / "game_resources.json",
            self.schemas_dir / "game_contents.json",
            self.schemas_dir / "ui_elements.json"
        ]
        if all(f.exists() for f in old_files):
            logger.info("구 스키마 구조 감지 (v1.0.0)")
            return "1.0.0"

        # 3. 신 구조 감지 (v2.0.0) - version.json만 없는 경우
        if self.games_dir.exists() and (self.schemas_dir / "registry.json").exists():
            logger.info("신 스키마 구조 감지 - version.json 생성")
            self.create_version_file(self.CURRENT_VERSION)
            return self.CURRENT_VERSION

        # 4. 신규 설치
        return None

    def handle_fresh_install(self) -> bool:
        """
        신규 설치: 기본 스키마 구조 생성

        Returns:
            bool: 성공 여부
        """
        try:
            logger.info("신규 설치 - 기본 스키마 구조 생성 중...")

            # schemas 디렉토리 생성
            self.schemas_dir.mkdir(parents=True, exist_ok=True)

            # games 디렉토리 생성
            self.games_dir.mkdir(parents=True, exist_ok=True)

            # 빈 registry.json 생성
            registry = {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "title": "Game Registry",
                "description": "게임 목록 및 프로세스 매칭 정보",
                "version": "1.0.0",
                "games": []
            }
            registry_file = self.schemas_dir / "registry.json"
            with open(registry_file, "w", encoding="utf-8") as f:
                json.dump(registry, f, ensure_ascii=False, indent=2)
            logger.info(f"registry.json 생성 완료: {registry_file}")

            # version.json 생성
            self.create_version_file(self.CURRENT_VERSION)

            logger.info("신규 설치 완료")
            return True

        except Exception as e:
            logger.error(f"신규 설치 초기화 실패: {e}")
            return False

    def migrate(self, from_version: str, to_version: str) -> bool:
        """
        버전별 마이그레이션 실행

        Args:
            from_version: 현재 버전
            to_version: 목표 버전

        Returns:
            bool: 성공 여부
        """
        # 마이그레이션 경로 찾기
        migration_path = self.find_migration_path(from_version, to_version)
        if not migration_path:
            logger.error(f"마이그레이션 경로 없음: {from_version} → {to_version}")
            return False

        logger.info(f"마이그레이션 경로: {' → '.join(migration_path)}")

        # 순차적으로 마이그레이션 실행
        for i in range(len(migration_path) - 1):
            current = migration_path[i]
            next_ver = migration_path[i + 1]

            if not self._execute_single_migration(current, next_ver):
                logger.error(f"마이그레이션 실패: {current} → {next_ver}")
                return False

        logger.info(f"모든 마이그레이션 완료: {from_version} → {to_version}")
        return True

    def find_migration_path(self, from_version: str, to_version: str) -> List[str]:
        """
        마이그레이션 경로 찾기
        향후 버전이 추가되면 여기에 경로 정의
        """
        # 지원하는 마이그레이션 그래프
        migrations = {
            "1.0.0": ["2.0.0"],
            "2.0.0": [],  # 현재 최신
        }

        # BFS로 최단 경로 찾기
        if from_version == to_version:
            return [from_version]

        from collections import deque
        queue = deque([(from_version, [from_version])])
        visited = {from_version}

        while queue:
            current, path = queue.popleft()

            for next_ver in migrations.get(current, []):
                if next_ver == to_version:
                    return path + [next_ver]

                if next_ver not in visited:
                    visited.add(next_ver)
                    queue.append((next_ver, path + [next_ver]))

        return []

    def _execute_single_migration(self, from_version: str, to_version: str) -> bool:
        """
        단일 마이그레이션 실행

        Args:
            from_version: 현재 버전
            to_version: 다음 버전
        """
        migrations = {
            ("1.0.0", "2.0.0"): self._migrate_v1_to_v2,
        }

        migration_func = migrations.get((from_version, to_version))
        if not migration_func:
            logger.error(f"마이그레이션 함수 없음: {from_version} → {to_version}")
            return False

        try:
            # 백업 생성
            backup_path = self.create_backup(from_version)
            logger.info(f"백업 생성 완료: {backup_path}")

            # 마이그레이션 실행
            success = migration_func()

            if success:
                # 버전 파일 업데이트
                self.update_version_file(from_version, to_version)
                logger.info(f"마이그레이션 성공: {from_version} → {to_version}")
                return True
            else:
                # 롤백
                logger.error(f"마이그레이션 실패, 롤백 시작...")
                self.restore_backup(backup_path)
                return False

        except Exception as e:
            logger.error(f"마이그레이션 중 예외 발생: {e}")
            if backup_path:
                self.restore_backup(backup_path)
            return False

    def _migrate_v1_to_v2(self) -> bool:
        """
        v1.0.0 → v2.0.0 마이그레이션
        통합 JSON 파일 → 게임별 디렉토리 구조
        """
        logger.info("v1.0.0 → v2.0.0 마이그레이션 시작...")

        try:
            # 구 파일 로드
            old_resources = self._load_json(self.schemas_dir / "game_resources.json")
            old_contents = self._load_json(self.schemas_dir / "game_contents.json")
            old_ui_elements = self._load_json(self.schemas_dir / "ui_elements.json")

            if not all([old_resources, old_contents, old_ui_elements]):
                logger.error("구 스키마 파일 로드 실패")
                return False

            # 게임 목록 추출
            game_ids = list(old_resources.get("games", {}).keys())
            logger.info(f"마이그레이션 대상 게임: {game_ids}")

            # games 디렉토리 생성
            self.games_dir.mkdir(parents=True, exist_ok=True)

            # 각 게임별로 분리
            for game_id in game_ids:
                game_dir = self.games_dir / game_id
                game_dir.mkdir(parents=True, exist_ok=True)

                # resources.json
                if game_id in old_resources.get("games", {}):
                    game_data = old_resources["games"][game_id]
                    new_resources = {
                        "$schema": "http://json-schema.org/draft-07/schema#",
                        "title": "Game Resources",
                        "description": f"{game_data.get('game_name_kr', game_id)} 재화 정의",
                        "version": "1.0.0",
                        "game_id": game_data.get("game_id", game_id),
                        "game_name": game_data.get("game_name", game_id),
                        "game_name_kr": game_data.get("game_name_kr", game_id),
                        "resources": game_data.get("resources", [])
                    }
                    self._save_json(game_dir / "resources.json", new_resources)

                # contents.json
                if game_id in old_contents.get("games", {}):
                    game_data = old_contents["games"][game_id]
                    new_contents = {
                        "$schema": "http://json-schema.org/draft-07/schema#",
                        "title": "Game Contents",
                        "description": f"{game_data.get('game_name_kr', game_id)} 콘텐츠 정의",
                        "version": "1.0.0",
                        "game_id": game_data.get("game_id", game_id),
                        "game_name": game_data.get("game_name", game_id),
                        "game_name_kr": game_data.get("game_name_kr", game_id),
                        "contents": game_data.get("contents", [])
                    }
                    self._save_json(game_dir / "contents.json", new_contents)

                # ui_elements.json
                if game_id in old_ui_elements.get("games", {}):
                    game_data = old_ui_elements["games"][game_id]
                    new_ui_elements = {
                        "$schema": "http://json-schema.org/draft-07/schema#",
                        "title": "UI Elements",
                        "description": f"{game_data.get('game_name_kr', game_id)} UI 요소 정의",
                        "version": "1.0.0",
                        "game_id": game_data.get("game_id", game_id),
                        "game_name": game_data.get("game_name", game_id),
                        "game_name_kr": game_data.get("game_name_kr", game_id),
                        "ui_elements": game_data.get("ui_elements", [])
                    }
                    self._save_json(game_dir / "ui_elements.json", new_ui_elements)

                # metadata.json
                game_info = old_resources["games"].get(game_id, {})
                metadata = {
                    "$schema": "http://json-schema.org/draft-07/schema#",
                    "title": "Game Metadata",
                    "description": "게임 기본 정보 및 설정",
                    "version": "1.0.0",
                    "game_id": game_info.get("game_id", game_id),
                    "game_name": game_info.get("game_name", game_id),
                    "game_name_kr": game_info.get("game_name_kr", game_id),
                    "schema_version": "1.0.0",
                    "enabled": True,
                    "last_updated": datetime.now().strftime("%Y-%m-%d"),
                    "process_patterns": [],
                    "window_title_patterns": [],
                    "verification_status": {
                        "resources_verified": False,
                        "contents_verified": False,
                        "ui_elements_verified": False
                    },
                    "notes": "v1.0.0에서 자동 마이그레이션됨"
                }
                self._save_json(game_dir / "metadata.json", metadata)

                logger.info(f"게임 '{game_id}' 마이그레이션 완료")

            # registry.json 생성
            self._create_registry_from_old_data(old_resources)

            # 구 파일 삭제
            for old_file in ["game_resources.json", "game_contents.json", "ui_elements.json"]:
                old_path = self.schemas_dir / old_file
                if old_path.exists():
                    old_path.unlink()
                    logger.info(f"구 파일 삭제: {old_file}")

            logger.info("v1.0.0 → v2.0.0 마이그레이션 완료")
            return True

        except Exception as e:
            logger.error(f"v1→v2 마이그레이션 실패: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _create_registry_from_old_data(self, old_resources: dict):
        """구 데이터에서 registry.json 생성"""
        # 기본 프로세스 패턴
        process_patterns_map = {
            "zenless_zone_zero": {
                "process_patterns": ["ZenlessZoneZero.exe", "*zenless*.exe"],
                "window_title_patterns": ["Zenless Zone Zero", "젠레스 존 제로"]
            },
            "honkai_star_rail": {
                "process_patterns": ["StarRail.exe", "*starrail*.exe"],
                "window_title_patterns": ["Honkai: Star Rail", "붕괴: 스타레일"]
            },
            "wuthering_waves": {
                "process_patterns": ["Wuthering Waves.exe", "Client-Win64-Shipping.exe"],
                "window_title_patterns": ["Wuthering Waves", "명조"]
            },
            "nikke": {
                "process_patterns": ["NIKKE.exe", "*nikke*.exe"],
                "window_title_patterns": ["NIKKE", "니케"]
            }
        }

        games_list = []
        for game_id, game_data in old_resources.get("games", {}).items():
            patterns = process_patterns_map.get(game_id, {
                "process_patterns": [],
                "window_title_patterns": []
            })

            game_entry = {
                "game_id": game_data.get("game_id", game_id),
                "game_name": game_data.get("game_name", game_id),
                "game_name_kr": game_data.get("game_name_kr", game_id),
                "schema_version": "1.0.0",
                "enabled": True,
                "process_patterns": patterns["process_patterns"],
                "window_title_patterns": patterns["window_title_patterns"],
                "last_updated": datetime.now().strftime("%Y-%m-%d")
            }
            games_list.append(game_entry)

        registry = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "title": "Game Registry",
            "description": "게임 목록 및 프로세스 매칭 정보",
            "version": "1.0.0",
            "games": games_list
        }

        self._save_json(self.schemas_dir / "registry.json", registry)
        logger.info("registry.json 생성 완료")

    def create_backup(self, version: str) -> Path:
        """
        백업 생성

        Args:
            version: 현재 버전

        Returns:
            Path: 백업 디렉토리 경로
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = self.schemas_dir / f"backup_v{version}_{timestamp}"

        # schemas 디렉토리 전체 복사 (기존 백업 제외)
        def ignore_backups(directory, files):
            return [f for f in files if f.startswith("backup_")]

        shutil.copytree(self.schemas_dir, backup_dir, ignore=ignore_backups)
        return backup_dir

    def restore_backup(self, backup_path: Path) -> bool:
        """
        백업에서 복원

        Args:
            backup_path: 백업 디렉토리 경로

        Returns:
            bool: 성공 여부
        """
        try:
            if not backup_path.exists():
                logger.error(f"백업 디렉토리 없음: {backup_path}")
                return False

            # 현재 상태 삭제 (백업 디렉토리 제외)
            for item in self.schemas_dir.iterdir():
                if item.name.startswith("backup_"):
                    continue
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()

            # 백업에서 복원
            for item in backup_path.iterdir():
                if item.is_dir():
                    shutil.copytree(item, self.schemas_dir / item.name)
                else:
                    shutil.copy2(item, self.schemas_dir / item.name)

            logger.info(f"백업에서 복원 완료: {backup_path}")
            return True

        except Exception as e:
            logger.error(f"백업 복원 실패: {e}")
            return False

    def create_version_file(self, version: str):
        """version.json 생성"""
        data = {
            "schema_version": version,
            "last_migration": datetime.now().isoformat(),
            "migration_history": []
        }
        self._save_json(self.version_file, data)
        logger.info(f"version.json 생성: v{version}")

    def update_version_file(self, from_version: str, to_version: str):
        """version.json 업데이트"""
        if self.version_file.exists():
            data = self._load_json(self.version_file)
        else:
            data = {"migration_history": []}

        # 마이그레이션 기록 추가
        migration_record = {
            "from": from_version,
            "to": to_version,
            "date": datetime.now().isoformat(),
            "description": f"v{from_version} → v{to_version} 자동 마이그레이션"
        }

        if "migration_history" not in data:
            data["migration_history"] = []

        data["migration_history"].append(migration_record)
        data["schema_version"] = to_version
        data["last_migration"] = datetime.now().isoformat()

        self._save_json(self.version_file, data)
        logger.info(f"version.json 업데이트: v{to_version}")

    def _load_json(self, file_path: Path) -> Optional[dict]:
        """JSON 파일 로드"""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"JSON 로드 실패 ({file_path}): {e}")
            return None

    def _save_json(self, file_path: Path, data: dict):
        """JSON 파일 저장"""
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def check_and_migrate_schemas() -> bool:
    """
    편의 함수: 스키마 마이그레이션 체크 및 실행
    앱 시작 시 호출됩니다.

    Returns:
        bool: 성공 여부
    """
    migrator = SchemaMigrator()
    return migrator.check_and_migrate()
