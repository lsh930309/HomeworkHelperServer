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
    
    # 시스템 프리셋 경로 (패키지 내부)
    SYSTEM_PRESET_FILE = Path(__file__).parent.parent / "data" / "game_presets.json"
    
    # 사용자 프리셋 경로
    USER_CONFIG_DIR = Path(os.environ.get("APPDATA", "")) / "HomeworkHelper"
    USER_PRESET_FILE = USER_CONFIG_DIR / "game_presets_user.json"
    
    def __init__(self):
        """GamePresetManager 초기화"""
        self._presets: list[dict] = []
        self._user_presets: list[dict] = []
        self._load_presets()
    
    def _load_presets(self) -> None:
        """시스템 프리셋과 사용자 프리셋 로드 및 병합"""
        self._presets = []
        
        # 1. 시스템 프리셋 로드
        system_presets = self._load_json_file(self.SYSTEM_PRESET_FILE)
        if system_presets and "presets" in system_presets:
            self._presets = system_presets["presets"]
            logger.info(f"시스템 프리셋 {len(self._presets)}개 로드")
        
        # 2. 사용자 프리셋 로드
        self._user_presets = []
        user_presets = self._load_json_file(self.USER_PRESET_FILE)
        if user_presets and "presets" in user_presets:
            self._user_presets = user_presets["presets"]
            logger.info(f"사용자 프리셋 {len(self._user_presets)}개 로드")
            
            # 3. 병합 (사용자 프리셋이 시스템 프리셋을 오버라이드)
            self._merge_user_presets()
    
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
    
    def _merge_user_presets(self) -> None:
        """사용자 프리셋을 시스템 프리셋에 병합"""
        # ID로 인덱스 생성
        preset_by_id = {p["id"]: i for i, p in enumerate(self._presets)}
        
        for user_preset in self._user_presets:
            preset_id = user_preset.get("id")
            if not preset_id:
                continue
            
            if preset_id in preset_by_id:
                # 기존 프리셋 업데이트
                idx = preset_by_id[preset_id]
                self._presets[idx].update(user_preset)
            else:
                # 새 프리셋 추가
                self._presets.append(user_preset)
                preset_by_id[preset_id] = len(self._presets) - 1
    
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
        """ID로 프리셋 조회
        
        Args:
            preset_id: 프리셋 ID (예: "honkai_starrail")
        
        Returns:
            프리셋 dict 또는 None
        """
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
        """사용자 정의 프리셋 추가
        
        Args:
            preset: 프리셋 정보 (id, display_name, exe_patterns 필수)
        
        Returns:
            추가 성공 여부
        """
        required_fields = ["id", "display_name", "exe_patterns"]
        if not all(field in preset for field in required_fields):
            logger.error(f"프리셋 필수 필드 누락: {required_fields}")
            return False
        
        try:
            # 기존 사용자 프리셋에서 같은 ID 제거
            self._user_presets = [p for p in self._user_presets if p.get("id") != preset["id"]]
            
            # 새 프리셋 추가
            self._user_presets.append(preset)
            
            # 파일에 저장
            return self._save_user_presets()
            
        except Exception as e:
            logger.error(f"프리셋 추가 실패: {e}")
            return False
    
    def update_user_preset(self, preset_id: str, updates: dict) -> bool:
        """사용자 프리셋 수정
        
        Args:
            preset_id: 수정할 프리셋 ID
            updates: 업데이트할 필드들
        
        Returns:
            수정 성공 여부
        """
        for preset in self._user_presets:
            if preset.get("id") == preset_id:
                preset.update(updates)
                return self._save_user_presets()
        
        # 사용자 프리셋에 없으면 시스템 프리셋을 복사해서 추가
        system_preset = self.get_preset_by_id(preset_id)
        if system_preset:
            new_preset = system_preset.copy()
            new_preset.update(updates)
            self._user_presets.append(new_preset)
            return self._save_user_presets()
        
        return False
    
    def remove_user_preset(self, preset_id: str) -> bool:
        """사용자 프리셋 삭제
        
        Args:
            preset_id: 삭제할 프리셋 ID
        
        Returns:
            삭제 성공 여부
        """
        original_len = len(self._user_presets)
        self._user_presets = [p for p in self._user_presets if p.get("id") != preset_id]
        
        if len(self._user_presets) < original_len:
            return self._save_user_presets()
        return False
    
    def _save_user_presets(self) -> bool:
        """사용자 프리셋을 파일에 저장"""
        try:
            # 디렉토리 생성
            self.USER_CONFIG_DIR.mkdir(parents=True, exist_ok=True)
            
            data = {
                "version": 1,
                "presets": self._user_presets
            }
            
            with open(self.USER_PRESET_FILE, "w", encoding="utf-8") as f:
                json.dump(data, ensure_ascii=False, indent=4, fp=f)
            
            logger.info(f"사용자 프리셋 저장 완료: {self.USER_PRESET_FILE}")
            
            # 프리셋 다시 로드
            self._load_presets()
            return True
            
        except Exception as e:
            logger.error(f"사용자 프리셋 저장 실패: {e}")
            return False
    
    def reload(self) -> None:
        """프리셋 다시 로드"""
        self._load_presets()
