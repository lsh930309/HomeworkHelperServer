"""NIKKE BlablaLink/ShiftyPad 읽기 전용 리소스 조회 서비스."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

import requests

from src.utils.nikke_config import NikkeConfig
from src.utils.resource_tracking import NIKKE_OUTPOST_LABEL, NIKKE_OUTPOST_RESOURCE_KEY, NIKKE_PROVIDER

logger = logging.getLogger(__name__)


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
    USER_INFO_ENDPOINTS = (
        "ugc/proxy/standalonesite/User/GetUserInfoNew",
        "user/GetGameLoginInfo",
    )
    SAVED_ROLE_ENDPOINTS = (
        ("GET", "game/proxy/Game/GetSavedRoleInfo"),
        # 현재 ShiftyPad 번들에는 GET wrapper가 주 경로지만, 같은 번들에 POST helper도
        # 남아 있으므로 서버 측 호환성을 위해 fallback으로 유지합니다.
        ("POST", "game/proxy/Game/GetSavedRoleInfo"),
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

    def _request_session(self) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        session_payload = self._session_payload()
        if not session_payload:
            return None, None
        cookies = session_payload.get("cookies") or {}
        if not cookies:
            return None, None
        return session_payload, cookies

    @staticmethod
    def _json_response(response: requests.Response) -> dict[str, Any]:
        response.raise_for_status()
        try:
            return response.json()
        except ValueError as exc:
            raise RuntimeError("BlablaLink API가 JSON이 아닌 응답을 반환했습니다.") from exc

    def _post(self, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        _session_payload, cookies = self._request_session()
        if not cookies:
            return {"code": "auth_required", "msg": "BlablaLink 세션이 없습니다."}
        response = requests.post(
            self.API_BASE + path,
            json=payload or {},
            headers=self._request_headers(),
            cookies=cookies,
            timeout=self._timeout,
        )
        return self._json_response(response)

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        _session_payload, cookies = self._request_session()
        if not cookies:
            return {"code": "auth_required", "msg": "BlablaLink 세션이 없습니다."}
        response = requests.get(
            self.API_BASE + path,
            params=params or {},
            headers=self._request_headers(),
            cookies=cookies,
            timeout=self._timeout,
        )
        return self._json_response(response)

    def _call_endpoint(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        method = method.upper()
        if method == "GET":
            return self._get(path, payload)
        if method == "POST":
            return self._post(path, payload)
        raise ValueError(f"지원하지 않는 BlablaLink API 메서드입니다: {method}")

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
            return NikkeRoleInfo(
                str(session_payload["intl_open_id"]),
                self._normalise_area_id(session_payload["nikke_area_id"]) or session_payload["nikke_area_id"],
            )

        intl_open_id = str(session_payload["intl_open_id"]) if session_payload.get("intl_open_id") else None
        nikke_area_id = self._normalise_area_id(session_payload.get("nikke_area_id"))

        # ShiftyPad 본인 계정 조회는 user_info.intl_openid에서 intl_open_id를, saved
        # role_info.area_id에서 nikke_area_id를 각각 조합해 daily API payload를 만듭니다.
        # 두 값이 같은 응답에 함께 있지 않기 때문에 단계별로 수집해야 합니다.
        auth_checked = False
        try:
            login_body = self._post(self.CHECK_LOGIN_PATH, {})
            auth_checked = True
            if self._is_auth_expired(login_body):
                return None
            intl_open_id = intl_open_id or self._extract_open_id(login_body)
            nikke_area_id = nikke_area_id if nikke_area_id is not None else self._extract_area_id(login_body)
        except Exception as exc:
            logger.debug("NIKKE CheckLogin 실패: %s", exc)

        if not intl_open_id:
            for endpoint in self.USER_INFO_ENDPOINTS:
                try:
                    body = self._post(endpoint, {})
                except Exception as exc:
                    logger.debug("NIKKE user info endpoint 실패: %s: %s", endpoint, exc)
                    continue
                if self._is_auth_expired(body):
                    if auth_checked:
                        continue
                    return None
                intl_open_id = self._extract_open_id(body)
                if intl_open_id:
                    break

        if nikke_area_id is None:
            for method, endpoint in self.SAVED_ROLE_ENDPOINTS:
                try:
                    body = self._call_endpoint(method, endpoint, {})
                except Exception as exc:
                    logger.debug("NIKKE role endpoint 실패: %s %s: %s", method, endpoint, exc)
                    continue
                if self._is_auth_expired(body):
                    return None
                role = self._extract_role(body)
                if role:
                    intl_open_id = intl_open_id or role.intl_open_id
                    nikke_area_id = role.nikke_area_id
                    break
                found_area_id = self._extract_area_id(body)
                if found_area_id is not None:
                    nikke_area_id = found_area_id
                    break

        if intl_open_id and nikke_area_id is not None:
            role = NikkeRoleInfo(str(intl_open_id), nikke_area_id)
            self._config.update_role(intl_open_id=role.intl_open_id, nikke_area_id=role.nikke_area_id)
            return role

        # 아주 오래된/다른 응답 형태에 대비해 같은 dict 안에 두 값이 함께 있는 경우도
        # 한 번 더 탐색합니다.
        for method, endpoint in self.SAVED_ROLE_ENDPOINTS:
            try:
                body = self._call_endpoint(method, endpoint, {})
            except Exception as exc:
                logger.debug("NIKKE legacy role endpoint 실패: %s %s: %s", method, endpoint, exc)
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
            logger.error("NIKKE 전초기지 방어 보상 조회 실패: %s", exc)
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
        open_id = cls._extract_open_id(body)
        area_id = cls._extract_area_id(body)
        if open_id and area_id is not None:
            return NikkeRoleInfo(open_id, area_id)
        return None

    @classmethod
    def _extract_open_id(cls, body: Any) -> Optional[str]:
        priority_keys = ("intl_openid", "intl_open_id", "intlOpenid", "intlOpenId")
        fallback_keys = ("open_id", "openid")
        for keys in (priority_keys, fallback_keys):
            for candidate in cls._walk_dicts(body):
                for key in keys:
                    open_id = cls._normalise_open_id(candidate.get(key))
                    if open_id:
                        return open_id
        return None

    @classmethod
    def _extract_area_id(cls, body: Any) -> int | str | None:
        # 대표 계정 응답은 data.role_info.area_id 형태가 가장 안정적입니다. 먼저
        # role_info/saved_role_info 내부를 우선 탐색해 주변 area_list 항목과 혼동하지
        # 않도록 합니다.
        for candidate in cls._walk_dicts(body):
            for role_key in ("role_info", "saved_role_info"):
                role = candidate.get(role_key)
                area_id = cls._extract_area_id_from_dict(role)
                if area_id is not None:
                    return area_id
        for candidate in cls._walk_dicts(body):
            area_id = cls._extract_area_id_from_dict(candidate)
            if area_id is not None:
                return area_id
        return None

    @classmethod
    def _extract_area_id_from_dict(cls, value: Any) -> int | str | None:
        if not isinstance(value, dict):
            return None
        for key in ("nikke_area_id", "nikkeAreaId", "area_id", "areaId"):
            area_id = cls._normalise_area_id(value.get(key))
            if area_id is not None:
                return area_id
        return None

    @staticmethod
    def _normalise_open_id(value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        # ShiftyPad 번들은 user_info.intl_openid에서 "-" 뒤쪽 값을 daily API의
        # intl_open_id로 넘깁니다.
        if "-" in text:
            text = text.rsplit("-", 1)[-1].strip()
        return text or None

    @staticmethod
    def _normalise_area_id(value: Any) -> int | str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text:
            return None
        try:
            return int(text)
        except (TypeError, ValueError):
            return text

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
