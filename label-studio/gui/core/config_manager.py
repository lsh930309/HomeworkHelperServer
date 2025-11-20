#!/usr/bin/env python3
"""
Label Studio Manager 설정 관리 모듈
사용자 설정을 JSON 파일로 저장/로드
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, asdict

from .utils import get_resource_path


@dataclass
class SSIMPreset:
    """SSIM 샘플링 프리셋"""
    name: str
    ssim_high: float
    ssim_low: float
    interval: float
    quality: int


@dataclass
class LabelStudioConfig:
    """Label Studio Manager 설정"""
    # 일반 설정
    last_raw_data_path: str = ""
    last_output_path: str = ""
    auto_open_browser: bool = True
    label_studio_port: int = 8080

    # SSIM 프리셋
    current_preset: str = "standard"

    # 경로 설정
    docker_compose_path: str = ""

    # 윈도우 설정
    window_width: int = 1200
    window_height: int = 800

    # 로그 설정
    log_max_lines: int = 1000
    auto_scroll_log: bool = True


class ConfigManager:
    """설정 관리자"""

    # 기본 SSIM 프리셋
    DEFAULT_PRESETS = {
        "quick": SSIMPreset(
            name="빠른 샘플링",
            ssim_high=0.95,
            ssim_low=0.80,
            interval=3.0,
            quality=90
        ),
        "standard": SSIMPreset(
            name="표준 샘플링",
            ssim_high=0.98,
            ssim_low=0.85,
            interval=5.0,
            quality=95
        ),
        "precise": SSIMPreset(
            name="정밀 샘플링",
            ssim_high=0.99,
            ssim_low=0.90,
            interval=8.0,
            quality=98
        )
    }

    def __init__(self, config_file: Optional[Path] = None):
        """
        설정 관리자 초기화

        Args:
            config_file: 설정 파일 경로 (None이면 기본 경로 사용)
        """
        if config_file is None:
            # 기본 설정 파일 경로: label-studio/gui/config.json
            self.config_file = get_resource_path("gui/config.json")
        else:
            self.config_file = config_file

        self.config = LabelStudioConfig()
        self.presets = self.DEFAULT_PRESETS.copy()

        # 설정 로드
        self.load()

    def load(self) -> bool:
        """
        설정 파일 로드

        Returns:
            성공 여부
        """
        if not self.config_file.exists():
            print(f"설정 파일 없음. 기본 설정 사용: {self.config_file}")
            return False

        try:
            with open(self.config_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # 설정 로드
            if 'config' in data:
                config_dict = data['config']
                for key, value in config_dict.items():
                    if hasattr(self.config, key):
                        setattr(self.config, key, value)

            # 프리셋 로드 (있으면)
            if 'presets' in data:
                preset_dict = data['presets']
                for preset_name, preset_data in preset_dict.items():
                    self.presets[preset_name] = SSIMPreset(**preset_data)

            print(f"설정 로드 완료: {self.config_file}")
            return True

        except Exception as e:
            print(f"설정 로드 실패: {e}")
            return False

    def save(self) -> bool:
        """
        설정 파일 저장

        Returns:
            성공 여부
        """
        try:
            # 설정 디렉토리 생성
            self.config_file.parent.mkdir(parents=True, exist_ok=True)

            # 저장할 데이터 구성
            data = {
                'config': asdict(self.config),
                'presets': {
                    name: asdict(preset)
                    for name, preset in self.presets.items()
                }
            }

            # JSON 저장
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

            print(f"설정 저장 완료: {self.config_file}")
            return True

        except Exception as e:
            print(f"설정 저장 실패: {e}")
            return False

    def get_current_preset(self) -> SSIMPreset:
        """현재 선택된 SSIM 프리셋 반환"""
        preset_name = self.config.current_preset
        if preset_name in self.presets:
            return self.presets[preset_name]
        else:
            # 기본값: standard
            return self.presets["standard"]

    def set_current_preset(self, preset_name: str):
        """현재 SSIM 프리셋 설정"""
        if preset_name in self.presets:
            self.config.current_preset = preset_name
            self.save()

    def get_all_presets(self) -> Dict[str, SSIMPreset]:
        """모든 SSIM 프리셋 반환"""
        return self.presets.copy()

    def add_preset(self, name: str, preset: SSIMPreset):
        """새 프리셋 추가"""
        self.presets[name] = preset
        self.save()

    def remove_preset(self, name: str) -> bool:
        """프리셋 삭제 (기본 프리셋은 삭제 불가)"""
        if name in ["quick", "standard", "precise"]:
            print(f"기본 프리셋은 삭제할 수 없습니다: {name}")
            return False

        if name in self.presets:
            del self.presets[name]
            self.save()
            return True

        return False

    def get_docker_compose_path(self) -> Path:
        """docker-compose.yml 경로 반환"""
        if self.config.docker_compose_path:
            return Path(self.config.docker_compose_path)
        else:
            # 기본 경로: label-studio/docker-compose.yml
            return get_resource_path("docker-compose.yml")

    def set_docker_compose_path(self, path: Path):
        """docker-compose.yml 경로 설정"""
        self.config.docker_compose_path = str(path)
        self.save()


# 싱글톤 인스턴스
_config_manager_instance: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    """ConfigManager 싱글톤 인스턴스 반환"""
    global _config_manager_instance
    if _config_manager_instance is None:
        _config_manager_instance = ConfigManager()
    return _config_manager_instance
