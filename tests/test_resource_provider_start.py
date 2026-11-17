"""실제 제공자 구현의 권한 검사 위치를 fake 전송으로 검증한다."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.services.hoyolab import HoYoLabService
from src.services.nikke import NikkeService, NikkeRoleInfo
import src.services.hoyolab as hoyo
import src.services.nikke as nikke


pytestmark = pytest.mark.usefixtures("resource_test_isolation")


@pytest.mark.parametrize("game_id", ["honkai_starrail", "zenless_zone_zero"])
def test_hoyolab_uid_lookup_delay_does_not_authorize_resource_request(monkeypatch, game_id):
    now = SimpleNamespace(value=599.0)
    notes = []
    game = SimpleNamespace(STARRAIL="starrail", ZZZ="zzz")

    class Client:
        uid = None
        def __init__(self, **kwargs):
            pass
        async def get_game_accounts(self):
            now.value = 601.0
            return [SimpleNamespace(game=self.game, level=1, uid=42)]
        async def get_starrail_notes(self, **kwargs):
            notes.append(kwargs)
            raise AssertionError("기간 뒤 스태미나 HTTP가 시작되면 안 된다")
        get_zzz_notes = get_starrail_notes
        async def close(self):
            pass

    config = SimpleNamespace(load_credentials=lambda: {"ltuid": 1, "ltoken_v2": "fixture-token"})
    monkeypatch.setattr(hoyo, "genshin", SimpleNamespace(Game=game, Client=Client))
    monkeypatch.setattr(hoyo, "GENSHIN_AVAILABLE", True)
    service = HoYoLabService(config=config)
    attempts = []
    def before_fetch():
        attempts.append(now.value)
        if now.value >= 600:
            raise RuntimeError("fixture expired")
    try:
        assert service.get_stamina(game_id, before_fetch=before_fetch) is None
        assert attempts == [601]
        assert notes == []
    finally:
        service.close()


def test_nikke_role_lookup_delay_checks_authority_before_progress_http(monkeypatch):
    now = SimpleNamespace(value=599.0)
    payload = {"cookies": {"session_id": "fixture-session"}, "intl_open_id": "fixture-role", "nikke_area_id": 1}
    config = SimpleNamespace(is_configured=lambda: True, load_session=lambda: payload)
    service = NikkeService(config=config)
    http_calls = []

    def get_role_info(**kwargs):
        now.value = 601.0
        return NikkeRoleInfo("fixture-role", 1)
    monkeypatch.setattr(service, "get_role_info", get_role_info)
    class HttpSession:
        cookies = SimpleNamespace(update=lambda cookies: None)
        def post(self, *args, **kwargs):
            http_calls.append(args)
            raise AssertionError("기간 뒤 자원 HTTP가 시작되면 안 된다")
        def close(self):
            pass
    monkeypatch.setattr(nikke.requests, "Session", HttpSession)
    attempts = []
    def before_fetch():
        attempts.append(now.value)
        if now.value >= 600:
            raise RuntimeError("fixture expired")
    result = service.get_outpost_storage(before_fetch=before_fetch)
    assert result.status == "unavailable"
    assert attempts == [601]
    assert http_calls == []
