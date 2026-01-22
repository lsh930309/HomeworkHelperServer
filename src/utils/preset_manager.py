"""게임 프리셋 관리 유틸리티

game_presets.json 파일을 로드하고, 프로세스 경로에서 게임을 자동 감지하며,
프리셋을 ProcessDialog에 적용하는 기능을 제공합니다.
"""
import json
import os
from typing import List, Optional, Dict, Any
from pathlib import Path


class PresetManager:
    """게임 프리셋 관리 클래스"""

    _presets_cache: Optional[List[Dict[str, Any]]] = None

    @classmethod
    def get_presets_file_path(cls) -> str:
        """game_presets.json 파일 경로 반환"""
        # 현재 파일 기준으로 상대 경로 계산
        current_dir = Path(__file__).parent  # src/utils
        presets_file = current_dir.parent / "data" / "game_presets.json"  # src/data/game_presets.json
        return str(presets_file)

    @classmethod
    def load_presets(cls) -> List[Dict[str, Any]]:
        """game_presets.json에서 프리셋 목록 로드

        Returns:
            프리셋 딕셔너리 리스트. 로드 실패 시 빈 리스트 반환.
        """
        # 캐시가 있으면 반환
        if cls._presets_cache is not None:
            return cls._presets_cache

        try:
            presets_path = cls.get_presets_file_path()
            if not os.path.exists(presets_path):
                print(f"[PresetManager] 프리셋 파일을 찾을 수 없습니다: {presets_path}")
                cls._presets_cache = []
                return cls._presets_cache

            with open(presets_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                cls._presets_cache = data.get("presets", [])
                print(f"[PresetManager] 프리셋 {len(cls._presets_cache)}개 로드 완료")
                return cls._presets_cache

        except Exception as e:
            print(f"[PresetManager] 프리셋 로드 실패: {e}")
            cls._presets_cache = []
            return cls._presets_cache

    @classmethod
    def reload_presets(cls) -> List[Dict[str, Any]]:
        """프리셋 캐시를 무효화하고 다시 로드"""
        cls._presets_cache = None
        return cls.load_presets()

    @classmethod
    def detect_preset_from_path(cls, path: str) -> Optional[Dict[str, Any]]:
        """프로세스 경로에서 프리셋 자동 감지

        exe_patterns를 사용하여 실행 파일 이름과 매칭합니다.

        Args:
            path: 프로세스 실행 파일 경로 (예: "C:/Games/StarRail.exe")

        Returns:
            매칭된 프리셋 딕셔너리 또는 None
        """
        if not path:
            return None

        # 경로에서 실행 파일 이름 추출
        exe_name = os.path.basename(path).lower()

        presets = cls.load_presets()
        for preset in presets:
            exe_patterns = preset.get("exe_patterns", [])
            for pattern in exe_patterns:
                if pattern.lower() == exe_name:
                    print(f"[PresetManager] '{exe_name}'에 대해 프리셋 '{preset['id']}' 감지")
                    return preset

        return None

    @classmethod
    def get_preset_by_id(cls, preset_id: str) -> Optional[Dict[str, Any]]:
        """프리셋 ID로 프리셋 조회

        Args:
            preset_id: 프리셋 ID (예: "honkai_starrail")

        Returns:
            프리셋 딕셔너리 또는 None
        """
        if not preset_id:
            return None

        presets = cls.load_presets()
        for preset in presets:
            if preset.get("id") == preset_id:
                return preset

        return None

    @classmethod
    def apply_preset_to_dialog(cls, preset: Dict[str, Any], dialog: 'ProcessDialog') -> None:
        """프리셋을 ProcessDialog에 적용

        프리셋의 설정값을 다이얼로그의 입력 필드에 자동으로 채웁니다.

        Args:
            preset: 프리셋 딕셔너리
            dialog: ProcessDialog 인스턴스
        """
        if not preset:
            return

        # 게임 이름 설정 (비어있을 때만)
        if not dialog.name_edit.text().strip():
            display_name = preset.get("display_name", "")
            if display_name:
                dialog.name_edit.setText(display_name)

        # 서버 초기화 시각 설정 (비어있을 때만)
        if not dialog.server_reset_time_edit.text().strip():
            server_reset_time = preset.get("server_reset_time", "")
            if server_reset_time:
                dialog.server_reset_time_edit.setText(server_reset_time)

        # 사용자 실행 주기 설정 (비어있을 때만)
        if not dialog.user_cycle_hours_edit.text().strip():
            default_cycle_hours = preset.get("default_cycle_hours")
            if default_cycle_hours:
                dialog.user_cycle_hours_edit.setText(str(default_cycle_hours))

        # 게임 스키마 자동 선택
        game_id = preset.get("id")
        if game_id and hasattr(dialog, 'game_schema_combo'):
            for i in range(dialog.game_schema_combo.count()):
                if dialog.game_schema_combo.itemData(i) == game_id:
                    dialog.game_schema_combo.setCurrentIndex(i)
                    print(f"[PresetManager] 게임 스키마 '{game_id}' 자동 선택")
                    break

        # 호요버스 게임이면 스태미나 추적 활성화 및 호요랩 게임 콤보박스 설정
        if preset.get("is_hoyoverse", False):
            if hasattr(dialog, 'stamina_tracking_checkbox'):
                dialog.stamina_tracking_checkbox.setChecked(True)
                print(f"[PresetManager] 호요버스 게임 '{game_id}': 스태미나 추적 자동 활성화")

            # 호요랩 게임 콤보박스 자동 선택
            if hasattr(dialog, 'hoyolab_game_combo') and game_id:
                for i in range(dialog.hoyolab_game_combo.count()):
                    if dialog.hoyolab_game_combo.itemData(i) == game_id:
                        dialog.hoyolab_game_combo.setCurrentIndex(i)
                        print(f"[PresetManager] 호요랩 게임 '{game_id}' 자동 선택")
                        break
