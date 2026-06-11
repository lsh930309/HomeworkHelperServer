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


@dataclass
class NikkeDailyCheckInStatus:
    """BlablaLink 일일 출석 체크 상태 조회/실행 결과.

    읽기 전용 status probe 결과와 임시 실험용 DailyCheckIn POST 결과를 같은
    UI formatter로 표시하기 위해 공유합니다.
    """

    status: str
    updated_at: datetime
    task_id: Optional[str] = None
    task_name: str = ""
    points: Optional[int] = None
    completed_times: Optional[int] = None
    need_completed_times: Optional[int] = None
    message: str = ""
    raw_debug: dict[str, Any] = field(default_factory=dict)


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
    DAILY_CHECKIN_STATUS_PATH = "lip/proxy/lipass/Points/GetTaskListWithStatusV2"
    DAILY_CHECKIN_POST_PATH = "lip/proxy/lipass/Points/DailyCheckIn"
    DAILY_CHECKIN_TASK_TYPE = 1
    DAILY_CHECKIN_TASK_ID = "15"

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

    def get_daily_checkin_status(self) -> NikkeDailyCheckInStatus:
        """BlablaLink NIKKE 일일 출석 체크 상태를 읽기 전용으로 조회합니다.

        실제 출석 처리 endpoint인 ``DailyCheckIn`` POST는 호출하지 않습니다.
        ShiftyPad 웹앱이 출석 버튼 노출에 사용하는 task status endpoint만
        조회하여 오늘 출석 가능/완료/인증 필요 상태를 판별합니다.
        """
        now = datetime.now()
        if not self.is_configured():
            return NikkeDailyCheckInStatus(
                "auth_required",
                now,
                message="BlablaLink 세션이 없습니다.",
            )

        for get_top in ("false", "true"):
            try:
                body = self._get(
                    self.DAILY_CHECKIN_STATUS_PATH,
                    {"get_top": get_top, "intl_game_id": "nikke"},
                )
            except Exception as exc:
                logger.error("NIKKE 출석 상태 조회 실패: %s", exc)
                return NikkeDailyCheckInStatus("network_error", now, message=str(exc))

            status = self._parse_daily_checkin_status(body, now, get_top=get_top)
            if status.status != "route_error" or get_top == "true":
                return status

        return NikkeDailyCheckInStatus("route_error", now, message="BlablaLink 출석 task를 찾지 못했습니다.")

    def claim_daily_checkin(self) -> NikkeDailyCheckInStatus:
        """BlablaLink NIKKE 일일 출석 체크를 실제 POST로 실행합니다.

        안전한 task id 확인을 위해 먼저 읽기 전용 status endpoint를 호출합니다.
        daily task가 ``ready``일 때만 ``DailyCheckIn`` POST를 수행하며, 이미
        완료되었거나 인증/route 문제가 있는 경우에는 POST를 생략하고 해당
        상태를 그대로 반환합니다.
        """
        status = self.get_daily_checkin_status()
        if status.status != "ready":
            status.raw_debug = {**status.raw_debug, "post_called": False}
            return status

        task_id = status.task_id or self.DAILY_CHECKIN_TASK_ID
        try:
            body = self._post(self.DAILY_CHECKIN_POST_PATH, {"task_id": task_id})
        except Exception as exc:
            logger.error("NIKKE 출석 체크 POST 실패: %s", exc)
            return NikkeDailyCheckInStatus(
                "network_error",
                datetime.now(),
                task_id=task_id,
                task_name=status.task_name,
                points=status.points,
                completed_times=status.completed_times,
                need_completed_times=status.need_completed_times,
                message=str(exc),
                raw_debug={"task_id": task_id, "post_called": True},
            )

        return self._parse_daily_checkin_post_result(body, status, task_id=task_id)

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

    @classmethod
    def _parse_daily_checkin_status(cls, body: Any, updated_at: datetime, *, get_top: str) -> NikkeDailyCheckInStatus:
        if not isinstance(body, dict):
            return NikkeDailyCheckInStatus(
                "route_error",
                updated_at,
                message="BlablaLink API가 예상하지 못한 응답을 반환했습니다.",
                raw_debug={"get_top": get_top, "body_type": type(body).__name__},
            )

        code = body.get("code")
        msg = str(body.get("msg") or body.get("message") or "")
        raw_debug = {"get_top": get_top, "code": code, "msg": msg}
        if code == "auth_required":
            return NikkeDailyCheckInStatus("auth_required", updated_at, message=msg, raw_debug=raw_debug)
        if cls._is_auth_expired(body):
            return NikkeDailyCheckInStatus("game_login_required", updated_at, message=msg or "game not login", raw_debug=raw_debug)
        if code not in (0, "0", None):
            return NikkeDailyCheckInStatus("route_error", updated_at, message=msg or f"BlablaLink API code={code}", raw_debug=raw_debug)

        task = cls._find_daily_checkin_task(body)
        if not task:
            return NikkeDailyCheckInStatus(
                "route_error",
                updated_at,
                message="BlablaLink 출석 task를 찾지 못했습니다.",
                raw_debug=raw_debug,
            )

        completed_times = cls._to_int(task.get("completed_times"))
        need_completed_times = cls._to_int(task.get("need_completed_times"))
        points = cls._to_int(task.get("points"))
        is_completed = cls._truthy(task.get("is_completed"))
        if (
            not is_completed
            and completed_times is not None
            and need_completed_times is not None
            and need_completed_times > 0
            and completed_times >= need_completed_times
        ):
            is_completed = True

        status = "already_done" if is_completed else "ready"
        task_id = str(task.get("task_id") or "")
        task_name = str(task.get("task_name") or "")
        raw_debug.update(
            {
                "task_id": task_id,
                "task_type": task.get("task_type"),
                "completed_times": completed_times,
                "need_completed_times": need_completed_times,
            }
        )
        return NikkeDailyCheckInStatus(
            status,
            updated_at,
            task_id=task_id,
            task_name=task_name,
            points=points,
            completed_times=completed_times,
            need_completed_times=need_completed_times,
            message="오늘 이미 출석 체크가 완료되었습니다." if is_completed else "오늘 출석 체크가 가능합니다.",
            raw_debug=raw_debug,
        )

    @classmethod
    def _parse_daily_checkin_post_result(
        cls, body: Any, status: NikkeDailyCheckInStatus, *, task_id: str
    ) -> NikkeDailyCheckInStatus:
        updated_at = datetime.now()
        if not isinstance(body, dict):
            return cls._daily_checkin_post_result(
                "route_error",
                status,
                task_id=task_id,
                message="BlablaLink API가 예상하지 못한 응답을 반환했습니다.",
                raw_debug={"body_type": type(body).__name__, "post_called": True},
                updated_at=updated_at,
            )

        code = body.get("code")
        msg = str(body.get("msg") or body.get("message") or "")
        raw_debug = {"task_id": task_id, "code": code, "msg": msg, "post_called": True}
        if code in (0, "0", None):
            return cls._daily_checkin_post_result(
                "success",
                status,
                task_id=task_id,
                message=msg or "BlablaLink 출석 체크가 완료되었습니다.",
                raw_debug=raw_debug,
                updated_at=updated_at,
            )
        if str(code) == "1001009":
            return cls._daily_checkin_post_result(
                "already_done",
                status,
                task_id=task_id,
                message=msg or "오늘 이미 출석 체크가 완료되었습니다.",
                raw_debug=raw_debug,
                updated_at=updated_at,
            )
        if code == "auth_required" or cls._is_auth_expired(body):
            return cls._daily_checkin_post_result(
                "game_login_required",
                status,
                task_id=task_id,
                message=msg or "game not login",
                raw_debug=raw_debug,
                updated_at=updated_at,
            )
        return cls._daily_checkin_post_result(
            "route_error",
            status,
            task_id=task_id,
            message=msg or f"BlablaLink API code={code}",
            raw_debug=raw_debug,
            updated_at=updated_at,
        )

    @staticmethod
    def _daily_checkin_post_result(
        result_status: str,
        status: NikkeDailyCheckInStatus,
        *,
        task_id: str,
        message: str,
        raw_debug: dict[str, Any],
        updated_at: datetime,
    ) -> NikkeDailyCheckInStatus:
        return NikkeDailyCheckInStatus(
            result_status,
            updated_at,
            task_id=task_id,
            task_name=status.task_name,
            points=status.points,
            completed_times=status.completed_times,
            need_completed_times=status.need_completed_times,
            message=message,
            raw_debug=raw_debug,
        )

    @classmethod
    def _find_daily_checkin_task(cls, body: Any) -> dict[str, Any] | None:
        tasks = cls._find_key(body, "tasks")
        if not isinstance(tasks, list):
            return None

        normalised = [cls._normalise_reward_task(task) for task in tasks if isinstance(task, dict)]
        for task in normalised:
            if cls._to_int(task.get("task_type")) == cls.DAILY_CHECKIN_TASK_TYPE:
                return task
        for task in normalised:
            task_id = str(task.get("task_id") or "").strip()
            task_name = str(task.get("task_name") or "").strip().lower()
            if task_id == cls.DAILY_CHECKIN_TASK_ID or "출석" in task_name or "check" in task_name:
                return task
        return None

    @staticmethod
    def _normalise_reward_task(task: dict[str, Any]) -> dict[str, Any]:
        merged = dict(task)
        reward_infos = task.get("reward_infos")
        if isinstance(reward_infos, list) and reward_infos and isinstance(reward_infos[0], dict):
            merged.update(reward_infos[0])
        return merged

    @staticmethod
    def _truthy(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y", "completed", "complete"}
        return False

    @staticmethod
    def _to_int(value: Any) -> int | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

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
