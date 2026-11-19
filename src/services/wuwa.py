"""공식 Windows 런처 인증을 복사 저장하지 않는 명조 글로벌 자원 조회."""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from src.utils.resource_tracking import (
    GameResourceSnapshot, WUWA_PROVIDER, WUWA_WAVEPLATE_LABEL, WUWA_WAVEPLATE_RESOURCE_KEY,
    resource_quantity_percent, wuwa_role_id, wuwa_role_key,
)
from src.utils.wuwa_config import WuwaConfig


class WuwaError(Exception):
    """민감한 외부 응답·예외 대신 고정한 상태와 사용자 안내만 전달한다."""

    def __init__(self, status: str, message: str):
        self.status = status
        self.message = message
        super().__init__(message)


@dataclass(frozen=True)
class WuwaRoleInfo:
    resource_key: str
    label: str


@dataclass(frozen=True)
class WuwaAccountDiscovery:
    status: str
    accounts: list[WuwaRoleInfo]
    message: str = ""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        return None


class WuwaGateway:
    """실제 인증 파일·HTTPS 접근은 이 경계 두 메서드만 소유한다."""

    API_URLS = {
        "queryPlayerInfo": "https://pc-launcher-sdk-api.kurogame.net/game/queryPlayerInfo",
        "queryRole": "https://pc-launcher-sdk-api.kurogame.net/game/queryRole",
    }
    MAX_CACHE_BYTES = 1024 * 1024
    MAX_RESPONSE_BYTES = 4 * 1024 * 1024

    def __init__(self, appdata_root: Path | None = None):
        self._appdata_root = appdata_root

    def read_accounts(self) -> tuple[str, ...]:
        if self._appdata_root is None and os.name != "nt":
            raise WuwaError("unavailable", "명조 런처 자동 연결은 Windows 호스트에서 사용할 수 있습니다.")
        root_value = self._appdata_root if self._appdata_root is not None else os.environ.get("APPDATA")
        if not root_value:
            raise WuwaError("auth_required", "Windows 사용자 프로필을 확인할 수 없습니다.")
        root = Path(root_value) / "KR_G153"
        try:
            if not root.is_dir() or root.is_symlink():
                raise WuwaError("auth_required", "명조 공식 런처에서 로그인한 뒤 다시 연결하세요.")
            accounts: list[str] = []
            for folder in sorted(root.iterdir()):
                if not folder.is_dir() or folder.is_symlink():
                    continue
                cache = folder / "KRSDKUserLauncherCache.json"
                if not cache.is_file() or cache.is_symlink():
                    continue
                with cache.open("rb") as stream:
                    raw = stream.read(self.MAX_CACHE_BYTES + 1)
                if len(raw) > self.MAX_CACHE_BYTES:
                    raise ValueError
                payload = json.loads(raw.decode("utf-8-sig"))
                if not isinstance(payload, list):
                    raise ValueError
                for item in payload:
                    encoded = item.get("oauthCode") if isinstance(item, dict) else None
                    if not isinstance(encoded, str) or not encoded:
                        raise ValueError
                    token = "".join(chr(ord(character) ^ 5) for character in encoded)
                    if not token or any(ord(character) < 32 or ord(character) == 127 for character in token):
                        raise ValueError
                    if token not in accounts:
                        accounts.append(token)
            if not accounts:
                raise WuwaError("auth_required", "명조 공식 런처에서 로그인한 뒤 다시 연결하세요.")
            return tuple(accounts)
        except OSError:
            raise WuwaError("auth_required", "명조 런처의 로그인 정보를 읽을 수 없습니다. 런처에서 다시 로그인하세요.") from None
        except (ValueError, UnicodeError, TypeError):
            raise WuwaError("unavailable", "명조 런처 로그인 정보의 형식을 확인할 수 없습니다.") from None

    def post_json(self, operation: str, payload: dict, timeout: float) -> tuple[int, dict | None]:
        if operation not in self.API_URLS:
            raise WuwaError("unavailable", "지원하지 않는 명조 조회입니다.")
        request = Request(
            self.API_URLS[operation], data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=timeout) as response:
                status = int(response.status)
                raw = response.read(self.MAX_RESPONSE_BYTES + 1)
        except HTTPError as error:
            status = int(error.code)
            error.close()
            return status, None
        except (OSError, ValueError):
            raise WuwaError("network_error", "명조 서버에 연결할 수 없습니다. 잠시 후 다시 조회하세요.") from None
        if len(raw) > self.MAX_RESPONSE_BYTES:
            raise WuwaError("unavailable", "명조 서버 응답의 크기를 확인할 수 없습니다.")
        try:
            reply = json.loads(raw.decode("utf-8"))
            if not isinstance(reply, dict):
                raise ValueError
            return status, reply
        except (ValueError, UnicodeError):
            raise WuwaError("unavailable", "명조 서버 응답을 해석할 수 없습니다.") from None


class WuwaService:
    MAX_REQUESTS = 5

    def __init__(self, gateway=None, timeout: float = 10.0, *, config=None, sleep=time.sleep, clock=time.time, monotonic=time.monotonic):
        self._gateway = gateway or WuwaGateway()
        self._config = config if config is not None else WuwaConfig()
        self.selected_resource_key = self._config.load_selected_resource_key()
        self._timeout = min(max(float(timeout), 0.001), 10.0)
        self._sleep = sleep
        self._clock = clock
        self._monotonic = monotonic
        self._deadline: float | None = None
        self._accounts: tuple[str, ...] | None = None

    def close(self):
        self._accounts = None
        self._deadline = None

    def is_available(self) -> bool:
        return True

    def is_configured(self) -> bool:
        if self.selected_resource_key is None:
            return False
        try:
            self._accounts = tuple(self._gateway.read_accounts())
            return bool(self._accounts)
        except WuwaError:
            return False

    def is_current(self) -> bool:
        if self._config.load_selected_resource_key() != self.selected_resource_key:
            return False
        if self._accounts is None:
            return True
        try:
            return set(self._gateway.read_accounts()) == set(self._accounts)
        except WuwaError:
            return False

    def _read_accounts(self) -> tuple[str, ...]:
        if self._accounts is None:
            self._accounts = tuple(self._gateway.read_accounts())
        return self._accounts

    def _query(self, operation, body, *, before_fetch=None):
        for attempt in range(self.MAX_REQUESTS):
            if before_fetch is not None:
                before_fetch()
            remaining = self._deadline - self._monotonic()
            if remaining <= 0:
                raise WuwaError("network_error", "명조 서버 조회의 대기 시간이 끝났습니다. 잠시 후 다시 조회하세요.")
            status, reply = self._gateway.post_json(operation, body, min(self._timeout, remaining))
            if status != 200:
                raise WuwaError("network_error", "명조 서버 요청을 완료하지 못했습니다. 잠시 후 다시 조회하세요.")
            code = reply.get("code") if isinstance(reply, dict) else None
            if code == 1005:
                if attempt + 1 < self.MAX_REQUESTS:
                    self._sleep(min(0.5, max(0.0, self._deadline - self._monotonic())))
                    continue
                raise WuwaError("loading", "명조 서버에서 자료를 준비 중입니다. 잠시 후 다시 조회하세요.")
            if code == 1001:
                raise WuwaError("auth_required", "명조 런처 인증이 거절되었습니다. 런처에서 다시 로그인한 뒤 연결하세요.")
            if type(code) is not int or code not in (0, 200):
                raise WuwaError("unavailable", "명조 서버에서 자원 정보를 제공하지 않았습니다.")
            data = reply.get("data")
            asia = data.get("Asia") if isinstance(data, dict) else None
            try:
                parsed = json.loads(asia) if isinstance(asia, str) else None
            except (ValueError, TypeError):
                parsed = None
            if not isinstance(parsed, dict):
                raise WuwaError("role_not_found", "글로벌 아시아의 명조 캐릭터를 찾을 수 없습니다.")
            return parsed

    def _discover(self, before_prepare=None, resource_key=None):
        roles = {}
        last_error = None
        for token in self._read_accounts():
            try:
                player = self._query("queryPlayerInfo", {"oauthCode": token}, before_fetch=before_prepare)
                role = player.get("roleId")
                role = str(role) if type(role) is int else role
                key = wuwa_role_key(role) if isinstance(role, str) else ""
                if wuwa_role_id(key) is None:
                    raise WuwaError("role_not_found", "글로벌 아시아의 명조 캐릭터를 찾을 수 없습니다.")
                roles.setdefault(key, token)
                if key == resource_key:
                    return {key: token}
            except WuwaError as error:
                if error.status not in {"auth_required", "role_not_found"}:
                    raise
                if last_error is None:
                    last_error = error
        if not roles:
            raise last_error or WuwaError("auth_required", "명조 공식 런처에서 로그인한 뒤 다시 연결하세요.")
        return roles

    def discover_accounts(self) -> WuwaAccountDiscovery:
        self.close()
        self._deadline = self._monotonic() + 30.0
        try:
            roles = self._discover()
            return WuwaAccountDiscovery("ok", [WuwaRoleInfo(key, f"글로벌 아시아 · …{wuwa_role_id(key)[-4:]}") for key in sorted(roles)])
        except WuwaError as error:
            return WuwaAccountDiscovery(error.status, [], error.message)
        finally:
            self.close()

    def get_resource_snapshot(self, resource_key: str, *, before_fetch=None, before_prepare=None) -> GameResourceSnapshot:
        def failed(status, message):
            return GameResourceSnapshot(WUWA_PROVIDER, resource_key, WUWA_WAVEPLATE_LABEL, None, status,
                                        datetime.fromtimestamp(self._clock()), message)
        if resource_key != WUWA_WAVEPLATE_RESOURCE_KEY or self.selected_resource_key is None:
            return failed("auth_required", "자원/출석 관리에서 명조 계정을 연결하세요.")
        self.close()
        self._deadline = self._monotonic() + 30.0
        try:
            roles = self._discover(before_prepare, self.selected_resource_key)
            token = roles.get(self.selected_resource_key)
            if token is None:
                raise WuwaError("role_not_found", "연결한 캐릭터의 로그인을 찾을 수 없습니다. 런처에서 로그인한 뒤 다시 연결하세요.")
            role = self._query("queryRole", {"oauthCode": token, "playerId": wuwa_role_id(self.selected_resource_key), "region": "Asia"},
                               before_fetch=before_fetch)
            if not self.is_current():
                raise WuwaError("cancelled", "연결 계정이 변경되어 이전 조회 결과를 적용하지 않았습니다.")
            base = role.get("Base")
            values = [base.get(field) for field in ("Energy", "MaxEnergy", "StoreEnergy", "MaxStoreEnergy")] if isinstance(base, dict) else []
            if len(values) != 4 or any(type(value) is not int or not 0 <= value < 2**63 for value in values):
                raise WuwaError("unavailable", "명조 서버의 일반·저장 자원 수치를 확인할 수 없습니다.")
            current, maximum, reserve_current, reserve_max = values
            percent = resource_quantity_percent(current, maximum)
            if percent is None or resource_quantity_percent(reserve_current, reserve_max) is None or reserve_current > reserve_max:
                raise WuwaError("unavailable", "명조 서버의 일반·저장 자원 범위를 확인할 수 없습니다.")
            return GameResourceSnapshot(WUWA_PROVIDER, resource_key, WUWA_WAVEPLATE_LABEL, percent, "ok",
                                        datetime.fromtimestamp(self._clock()), current=current, maximum=maximum,
                                        reserve_current=reserve_current, reserve_max=reserve_max)
        except WuwaError as error:
            return failed(error.status, error.message)


_wuwa_service: WuwaService | None = None


def get_wuwa_service() -> WuwaService:
    global _wuwa_service
    if _wuwa_service is None:
        _wuwa_service = WuwaService()
    return _wuwa_service


def reset_wuwa_service() -> None:
    global _wuwa_service
    if _wuwa_service is not None:
        _wuwa_service.close()
    _wuwa_service = None
