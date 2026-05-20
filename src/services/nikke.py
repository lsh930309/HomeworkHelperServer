"""NIKKE BlablaLink/ShiftyPad 읽기 전용 리소스 조회 서비스."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import requests

from src.utils.nikke_config import NikkeConfig

logger = logging.getLogger(__name__)


NIKKE_PROVIDER = "nikke_blablalink"
NIKKE_OUTPOST_RESOURCE_KEY = "nikke_outpost_storage"
NIKKE_OUTPOST_LABEL = "보관함 용량"


@dataclass
class GameResourceSnapshot:
    provider: str
    resource_key: str
    label: str
    percent: Optional[float]
    status: str
    updated_at: datetime
    message: str = ""
    raw_debug: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NikkeRoleInfo:
    intl_open_id: str
    nikke_area_id: int | str


class NikkeService:
    """ShiftyPad 웹앱이 사용하는 BlablaLink API에서 NIKKE 리소스를 조회합니다."""

    API_BASE = "https://api.blablalink.com/api/"
    CHECK_LOGIN_PATH = "user/CheckLogin"
    ROLE_ENDPOINTS = (
        "game/proxy/Game/GetSavedRoleInfo",
        "game/proxy/Tools/GetUserSavedRoleInfo",
    )
    DAILY_PROGRESS_PATH = "game/proxy/Game/GetUserDailyContentsProgress"

    def __init__(self, config: Optional[NikkeConfig] = None, timeout: float = 10.0):
        self._config = config or NikkeConfig()
        self._timeout = timeout

    def is_configured(self) -> bool:
        return self._config.is_configured()

    def _session_payload(self) -> Optional[dict[str, Any]]:
        return self._config.load_session()

    def _request_headers(self) -> dict[str, str]:
        common_params = {
            "game_id": "nikke",
            "intl_game_id": "nikke",
            "source": "h5",
            "language": "ko",
            "env": "prod",
            "data_statistics_scene": "shiftypad",
        }
        return {
            "Accept": "application/json, text/plain, */*",
            "Content-Type": "application/json;charset=UTF-8",
            "Origin": "https://www.blablalink.com",
            "Referer": "https://www.blablalink.com/nikke/",
            "User-Agent": "Mozilla/5.0 HomeworkHelper/1.0",
            "x-language": "ko",
            "x-channel-type": "2",
            "x-common-params": self._json_dumps(common_params),
        }

    @staticmethod
    def _json_dumps(value: dict[str, Any]) -> str:
        import json

        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    def _post(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        session_payload = self._session_payload()
        if not session_payload:
            return {"code": "auth_required", "msg": "BlablaLink 세션이 없습니다."}
        cookies = session_payload.get("cookies") or {}
        response = requests.post(
            self.API_BASE + path,
            json=payload or {},
            headers=self._request_headers(),
            cookies=cookies,
            timeout=self._timeout,
        )
        response.raise_for_status()
        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError("BlablaLink API가 JSON이 아닌 응답을 반환했습니다.") from exc

    @staticmethod
    def _is_auth_expired(body: dict[str, Any]) -> bool:
        code = body.get("code")
        msg = str(body.get("msg") or body.get("message") or "").lower()
        return code == 300001 or str(code) == "300001" or "not login" in msg or "login" in msg and "not" in msg

    def check_login(self) -> tuple[bool, str]:
        try:
            body = self._post(self.CHECK_LOGIN_PATH, {})
        except Exception as exc:
            return False, str(exc)
        if self._is_auth_expired(body):
            return False, str(body.get("msg") or "game not login")
        code = body.get("code")
        return (code in (0, "0", None)), str(body.get("msg") or body.get("message") or "ok")

    def get_role_info(self, *, refresh: bool = False) -> Optional[NikkeRoleInfo]:
        session_payload = self._session_payload()
        if not session_payload:
            return None
        if not refresh and session_payload.get("intl_open_id") and session_payload.get("nikke_area_id") is not None:
            return NikkeRoleInfo(str(session_payload["intl_open_id"]), session_payload["nikke_area_id"])

        for endpoint in self.ROLE_ENDPOINTS:
            try:
                body = self._post(endpoint, {})
            except Exception as exc:
                logger.debug("NIKKE role endpoint 실패: %s: %s", endpoint, exc)
                continue
            if self._is_auth_expired(body):
                return None
            role = self._extract_role(body)
            if role:
                self._config.update_role(intl_open_id=role.intl_open_id, nikke_area_id=role.nikke_area_id)
                return role
        return None

    def get_outpost_storage(self) -> GameResourceSnapshot:
        now = datetime.now()
        if not self.is_configured():
            return GameResourceSnapshot(NIKKE_PROVIDER, NIKKE_OUTPOST_RESOURCE_KEY, NIKKE_OUTPOST_LABEL, None, "auth_required", now)

        role = self.get_role_info()
        if not role:
            return GameResourceSnapshot(
                NIKKE_PROVIDER,
                NIKKE_OUTPOST_RESOURCE_KEY,
                NIKKE_OUTPOST_LABEL,
                None,
                "role_not_found",
                now,
                "ShiftyPad 대표 계정/서버 정보를 찾지 못했습니다.",
            )

        try:
            body = self._post(
                self.DAILY_PROGRESS_PATH,
                {"intl_open_id": role.intl_open_id, "nikke_area_id": role.nikke_area_id},
            )
        except Exception as exc:
            logger.error("NIKKE 보관함 용량 조회 실패: %s", exc)
            return GameResourceSnapshot(NIKKE_PROVIDER, NIKKE_OUTPOST_RESOURCE_KEY, NIKKE_OUTPOST_LABEL, None, "unavailable", now, str(exc))

        if self._is_auth_expired(body):
            return GameResourceSnapshot(NIKKE_PROVIDER, NIKKE_OUTPOST_RESOURCE_KEY, NIKKE_OUTPOST_LABEL, None, "auth_expired", now, str(body.get("msg") or "login expired"))

        raw_value = self._extract_outpost_fullness(body)
        if raw_value is None:
            return GameResourceSnapshot(
                NIKKE_PROVIDER,
                NIKKE_OUTPOST_RESOURCE_KEY,
                NIKKE_OUTPOST_LABEL,
                None,
                "unavailable",
                now,
                "outpost_battle_storage_fullness 필드를 찾지 못했습니다.",
            )

        percent = self.normalise_outpost_percent(raw_value)
        return GameResourceSnapshot(
            NIKKE_PROVIDER,
            NIKKE_OUTPOST_RESOURCE_KEY,
            NIKKE_OUTPOST_LABEL,
            percent,
            "ok",
            datetime.now(),
            raw_debug={"field": "daily_progress[0].outpost_battle_storage_fullness", "value": raw_value},
        )

    @staticmethod
    def normalise_outpost_percent(raw_value: Any) -> float:
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            value = 0.0
        percent = round(value * 100.0, 1)
        return max(0.0, min(percent, 100.0))

    @classmethod
    def _extract_outpost_fullness(cls, body: Any) -> Any | None:
        # ShiftyPad 번들 기준으로 daily_progress[0].outpost_battle_storage_fullness를 우선 사용합니다.
        if isinstance(body, dict):
            daily = cls._find_key(body, "daily_progress")
            if isinstance(daily, list) and daily:
                first = daily[0]
                if isinstance(first, dict) and "outpost_battle_storage_fullness" in first:
                    return first.get("outpost_battle_storage_fullness")
            direct = cls._find_key(body, "outpost_battle_storage_fullness")
            if direct is not None:
                return direct
        return None

    @classmethod
    def _extract_role(cls, body: Any) -> Optional[NikkeRoleInfo]:
        for candidate in cls._walk_dicts(body):
            open_id = candidate.get("intl_open_id") or candidate.get("intlOpenId") or candidate.get("open_id")
            area_id = candidate.get("nikke_area_id") or candidate.get("nikkeAreaId") or candidate.get("area_id")
            if open_id and area_id is not None:
                return NikkeRoleInfo(str(open_id), area_id)
        return None

    @classmethod
    def _find_key(cls, value: Any, key: str) -> Any | None:
        if isinstance(value, dict):
            if key in value:
                return value[key]
            for child in value.values():
                found = cls._find_key(child, key)
                if found is not None:
                    return found
        elif isinstance(value, list):
            for child in value:
                found = cls._find_key(child, key)
                if found is not None:
                    return found
        return None

    @classmethod
    def _walk_dicts(cls, value: Any):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from cls._walk_dicts(child)
        elif isinstance(value, list):
            for child in value:
                yield from cls._walk_dicts(child)


_service_instance: Optional[NikkeService] = None


def get_nikke_service() -> NikkeService:
    global _service_instance
    if _service_instance is None:
        _service_instance = NikkeService()
    return _service_instance


def reset_nikke_service() -> None:
    global _service_instance
    _service_instance = None
