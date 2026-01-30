"""게임 프리셋 관리 유틸리티

실행 파일명으로 게임 타입을 자동 감지하고, 프리셋 정보를 관리합니다.
시스템 프리셋과 사용자 정의 프리셋을 모두 지원합니다.
"""
import json
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class GamePresetManager:
    """게임 프리셋 로드 및 자동 감지 매니저
    
    시스템 프리셋 (src/data/game_presets.json)과 
    사용자 프리셋 (%APPDATA%/HomeworkHelper/game_presets_user.json)을 
    병합하여 관리합니다. 사용자 프리셋이 시스템 프리셋을 오버라이드합니다.
    """
    
    # 시스템 프리셋 경로 (패키지 내부) - 초기화용
    SYSTEM_PRESET_FILE = Path(__file__).parent.parent / "data" / "game_presets.json"
    
    # 사용자 프리셋 경로 - 실제 런타임 사용
    USER_CONFIG_DIR = Path(os.environ.get("APPDATA", "")) / "HomeworkHelper"
    USER_PRESET_FILE = USER_CONFIG_DIR / "game_presets_user.json"
    
    def __init__(self):
        """GamePresetManager 초기화"""
        self._presets: list[dict] = []
        self._load_presets()
    
    def _load_presets(self) -> None:
        """프리셋 로드 (Copy-On-Init 전략)

        1. 사용자 프리셋 파일이 있으면 그것만 로드합니다.
        2. 없으면 시스템 프리셋을 로드하여 사용자 프리셋 파일로 복사(초기화)한 후 로드합니다.
        3. 프리셋 스키마 버전 마이그레이션을 수행합니다.
        """
        # 사용자 설정 디렉토리 확인
        if not self.USER_CONFIG_DIR.exists():
            self.USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        # 사용자 프리셋 파일 존재 여부 확인
        if not self.USER_PRESET_FILE.exists():
            logger.info("사용자 프리셋 파일이 없음. 시스템 프리셋으로 초기화합니다.")
            self._initialize_user_presets_from_system()

        # 사용자 프리셋 로드
        loaded_data = self._load_json_file(self.USER_PRESET_FILE)
        if loaded_data and "presets" in loaded_data:
            # 마이그레이션 수행
            version = loaded_data.get("version", 1)
            if version < 2:
                logger.info(f"프리셋 스키마 v{version} → v2 마이그레이션 시작")
                migrated_presets = [self._migrate_preset_schema(p) for p in loaded_data["presets"]]
                self._presets = migrated_presets
                # 마이그레이션 결과를 파일에 저장
                self._save_presets()
                logger.info("프리셋 스키마 마이그레이션 완료")
            else:
                self._presets = loaded_data["presets"]

            logger.info(f"프리셋 {len(self._presets)}개 로드 완료 (사용자 설정)")
        else:
            logger.error("프리셋 로드 실패 또는 형식이 잘못됨")
            self._presets = []

    def _initialize_user_presets_from_system(self) -> None:
        """시스템 프리셋을 사용자 프리셋 파일로 복사"""
        system_presets = self._load_json_file(self.SYSTEM_PRESET_FILE)
        if system_presets:
            try:
                with open(self.USER_PRESET_FILE, "w", encoding="utf-8") as f:
                    json.dump(system_presets, ensure_ascii=False, indent=4, fp=f)
                logger.info(f"시스템 프리셋 복사 완료: {self.USER_PRESET_FILE}")
            except Exception as e:
                logger.error(f"시스템 프리셋 초기화 실패: {e}")
                # 실패하더라도 빈 리스트로라도 동작하도록 예외 처리는 로깅만 함
    
    def _load_json_file(self, path: Path) -> Optional[dict]:
        """JSON 파일 로드"""
        if not path.exists():
            return None
        
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"프리셋 파일 로드 실패 ({path}): {e}")
            return None
    
    def detect_game_from_exe(self, exe_path: str) -> Optional[dict]:
        """실행 파일 경로에서 게임 프리셋 자동 감지
        
        Args:
            exe_path: 실행 파일 전체 경로 (예: "C:/Games/StarRail.exe")
        
        Returns:
            매칭된 프리셋 dict 또는 None
        """
        if not exe_path:
            return None
        
        exe_name = os.path.basename(exe_path).lower()
        
        for preset in self._presets:
            patterns = preset.get("exe_patterns", [])
            for pattern in patterns:
                if pattern.lower() == exe_name:
                    logger.info(f"게임 감지: {exe_path} -> {preset['display_name']}")
                    return preset
        
        return None
    
    def get_preset_by_id(self, preset_id: str) -> Optional[dict]:
        """ID로 프리셋 조회"""
        for preset in self._presets:
            if preset.get("id") == preset_id:
                return preset
        return None
    
    def get_all_presets(self) -> list[dict]:
        """모든 프리셋 반환"""
        return self._presets.copy()
    
    def get_hoyoverse_presets(self) -> list[dict]:
        """호요버스 게임 프리셋만 반환"""
        return [p for p in self._presets if p.get("is_hoyoverse", False)]
    
    def add_user_preset(self, preset: dict) -> bool:
        """프리셋 추가 (기존에 있으면 오버라이드)"""
        # 기존 ID가 있다면 제거 (업데이트 효과)
        self._presets = [p for p in self._presets if p.get("id") != preset["id"]]
        
        # 새 프리셋 추가
        self._presets.append(preset)
        
        return self._save_presets()
            
    def update_user_preset(self, preset_id: str, updates: dict) -> bool:
        """프리셋 수정"""
        found = False
        for preset in self._presets:
            if preset.get("id") == preset_id:
                preset.update(updates)
                found = True
                break
        
        if found:
            return self._save_presets()
        return False
    
    def remove_user_preset(self, preset_id: str) -> bool:
        """프리셋 삭제"""
        original_len = len(self._presets)
        self._presets = [p for p in self._presets if p.get("id") != preset_id]
        
        if len(self._presets) < original_len:
            return self._save_presets()
        return False
    
    def _migrate_preset_schema(self, preset: dict) -> dict:
        """프리셋 스키마를 v2로 마이그레이션

        Args:
            preset: v1 프리셋 데이터

        Returns:
            v2 프리셋 데이터
        """
        migrated = preset.copy()

        # stamina_icon → icon_path 변환
        if "stamina_icon" in migrated:
            old_icon = migrated.pop("stamina_icon")
            if old_icon:
                # 확장자 추출
                _, ext = os.path.splitext(old_icon)
                # {preset_id}_stamina.{ext} 형식으로 변환
                migrated["icon_path"] = f"{migrated['id']}_stamina{ext}"
                migrated["icon_type"] = "system"

        # 누락된 필드 null로 채우기
        default_fields = {
            "icon_path": None,
            "icon_type": None,
            "hoyolab_game_id": None,
            "server_reset_time": None,
            "default_cycle_hours": None,
            "stamina_name": None,
            "stamina_max_default": None,
            "stamina_recovery_minutes": None,
            "launcher_patterns": None,
            "preferred_launch_type": "shortcut",
            "mandatory_times": []
        }
        for key, default_val in default_fields.items():
            if key not in migrated:
                migrated[key] = default_val

        # hoyolab_game_id 설정 (호요버스 게임은 id와 동일)
        if migrated.get("is_hoyoverse") and not migrated.get("hoyolab_game_id"):
            migrated["hoyolab_game_id"] = migrated["id"]

        return migrated

    def _save_presets(self) -> bool:
        """현재 프리셋 목록을 파일에 저장"""
        try:
            data = {
                "version": 2,
                "presets": self._presets
            }

            with open(self.USER_PRESET_FILE, "w", encoding="utf-8") as f:
                json.dump(data, ensure_ascii=False, indent=4, fp=f)

            logger.info("프리셋 저장 완료")
            return True

        except Exception as e:
            logger.error(f"프리셋 저장 실패: {e}")
            return False
    
    def reload(self) -> None:
        """프리셋 다시 로드"""
        self._load_presets()
