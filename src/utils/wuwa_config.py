"""명조의 선택 계정만 보존한다. 인증은 공식 런처 캐시가 소유한다."""
from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from src.utils.app_paths import DEFAULT_APP_NAME, _app_data_path
from src.utils.resource_tracking import wuwa_role_id


class WuwaConfig:
    CONFIG_FILE = "wuwa_link.json"

    def __init__(self, config_dir: Path | None = None):
        self.config_dir = Path(config_dir) if config_dir is not None else _app_data_path(DEFAULT_APP_NAME)

    @property
    def config_path(self) -> Path:
        return self.config_dir / self.CONFIG_FILE

    def exists(self) -> bool:
        return self.config_path.exists()

    def load_selected_resource_key(self) -> str | None:
        try:
            value = json.loads(self.config_path.read_text(encoding="utf-8")).get("selected_resource_key")
            return value if wuwa_role_id(value) is not None else None
        except (OSError, ValueError, AttributeError, TypeError):
            return None

    @property
    def selected_resource_key(self) -> str | None:
        return self.load_selected_resource_key()

    def is_configured(self) -> bool:
        return self.load_selected_resource_key() is not None

    def save_account(self, selected_resource_key: str | None) -> bool:
        if selected_resource_key is not None and wuwa_role_id(selected_resource_key) is None:
            return False
        temporary = None
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.config_dir, delete=False) as stream:
                temporary = Path(stream.name)
                json.dump({"selected_resource_key": selected_resource_key}, stream, ensure_ascii=False)
            os.replace(temporary, self.config_path)
            return True
        except OSError:
            return False
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def remove_created_account(self) -> bool:
        """DB 저장 실패 보상에서 이번 작업이 만든 설정 파일만 제거한다."""
        try:
            self.config_path.unlink(missing_ok=True)
            return True
        except OSError:
            return False

    def clear_account(self) -> bool:
        # 파일 없음과 구분하여 이전 게임 설정에서 자동 재연결하지 않는다.
        return self.save_account(None)
