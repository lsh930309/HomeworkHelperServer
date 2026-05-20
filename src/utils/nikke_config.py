"""NIKKE/BlablaLink 인증 세션 저장 유틸리티.

BlablaLink 비밀번호나 별도 계정 토큰을 입력받지 않고, 사용자가 브라우저에서 이미
로그인한 세션 쿠키만 로컬에 저장합니다. Windows에서는 DPAPI로 현재 사용자 계정에
바인딩해 암호화합니다.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    import win32crypt
    DPAPI_AVAILABLE = True
except ImportError:  # pragma: no cover - Windows host dependency
    DPAPI_AVAILABLE = False
    win32crypt = None


class NikkeConfig:
    """암호화된 BlablaLink/NIKKE 세션 정보 관리 클래스."""

    CONFIG_DIR = Path(os.environ.get("APPDATA", "")) / "HomeworkHelper"
    CREDENTIALS_FILE = "nikke_blabla_credentials.enc"

    def __init__(self):
        self._ensure_config_dir()

    def _ensure_config_dir(self) -> None:
        self.CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    @property
    def credentials_path(self) -> Path:
        return self.CONFIG_DIR / self.CREDENTIALS_FILE

    def _encrypt_data(self, data: bytes) -> Optional[bytes]:
        if not DPAPI_AVAILABLE:
            logger.error("Windows DPAPI를 사용할 수 없습니다. pywin32를 설치하세요.")
            return None
        try:
            return win32crypt.CryptProtectData(
                data,
                "HomeworkHelper NIKKE BlablaLink Credentials",
                None,
                None,
                None,
                0,
            )
        except Exception as exc:
            logger.error("NIKKE 세션 암호화 실패: %s", exc)
            return None

    def _decrypt_data(self, encrypted_data: bytes) -> Optional[bytes]:
        if not DPAPI_AVAILABLE:
            logger.error("Windows DPAPI를 사용할 수 없습니다.")
            return None
        try:
            _description, decrypted = win32crypt.CryptUnprotectData(encrypted_data, None, None, None, 0)
            return decrypted
        except Exception as exc:
            logger.error("NIKKE 세션 복호화 실패: %s", exc)
            return None

    def save_session(
        self,
        cookies: dict[str, Any],
        *,
        intl_open_id: str | None = None,
        nikke_area_id: int | str | None = None,
    ) -> bool:
        """BlablaLink 쿠키와 선택적 대표 캐릭터 식별자를 저장합니다."""
        clean_cookies = {str(key): str(value) for key, value in (cookies or {}).items() if value is not None}
        if not clean_cookies:
            logger.error("저장할 BlablaLink 쿠키가 없습니다.")
            return False

        payload: dict[str, Any] = {
            "provider": "nikke_blablalink",
            "cookies": clean_cookies,
            "saved_at": time.time(),
        }
        if intl_open_id:
            payload["intl_open_id"] = str(intl_open_id)
        if nikke_area_id is not None and str(nikke_area_id).strip():
            try:
                payload["nikke_area_id"] = int(nikke_area_id)
            except (TypeError, ValueError):
                payload["nikke_area_id"] = str(nikke_area_id)

        try:
            encrypted = self._encrypt_data(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
            if not encrypted:
                return False
            self.credentials_path.write_bytes(encrypted)
            logger.info("NIKKE/BlablaLink 세션 저장 완료: %s", self.credentials_path)
            return True
        except Exception as exc:
            logger.error("NIKKE 세션 저장 실패: %s", exc)
            return False

    def load_session(self) -> Optional[dict[str, Any]]:
        if not self.credentials_path.exists():
            logger.debug("NIKKE/BlablaLink 인증 정보 파일이 없습니다.")
            return None
        try:
            decrypted = self._decrypt_data(self.credentials_path.read_bytes())
            if not decrypted:
                return None
            data = json.loads(decrypted.decode("utf-8"))
            cookies = data.get("cookies")
            if not isinstance(cookies, dict) or not cookies:
                return None
            return data
        except Exception as exc:
            logger.error("NIKKE 세션 로드 실패: %s", exc)
            return None

    def update_role(self, *, intl_open_id: str, nikke_area_id: int | str) -> bool:
        session = self.load_session()
        if not session:
            return False
        return self.save_session(
            session.get("cookies") or {},
            intl_open_id=intl_open_id,
            nikke_area_id=nikke_area_id,
        )

    def clear_session(self) -> bool:
        try:
            if self.credentials_path.exists():
                self.credentials_path.unlink()
                logger.info("NIKKE/BlablaLink 인증 정보 삭제 완료")
            return True
        except Exception as exc:
            logger.error("NIKKE 인증 정보 삭제 실패: %s", exc)
            return False

    def is_configured(self) -> bool:
        session = self.load_session()
        return bool(session and session.get("cookies"))
