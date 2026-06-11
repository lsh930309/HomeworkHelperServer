import json
import sqlite3
import time
import datetime as dt
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.core.process_progress import calculate_process_progress
from src.core.daily_checkin import (
    GAME_HONKAI_STARRAIL,
    GAME_NIKKE,
    descriptor_for_process,
    checkin_period_for_descriptor,
    should_attempt_daily_checkin,
)
from src.data.data_models import ManagedProcess
from src.utils.game_preset_manager import GamePresetManager
from src.utils.icon_helper import resolve_preset_icon_path
from src.services.hoyolab import HoYoLabService
from src.services.nikke import NikkeService
from src.utils.browser_cookie_extractor import BrowserCookieExtractor
import src.services.hoyolab as hoyolab_module


def _create_firefox_cookie_db(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute(
            """
            CREATE TABLE moz_cookies (
                host TEXT,
                name TEXT,
                value TEXT,
                path TEXT,
                expiry INTEGER,
                lastAccessed INTEGER,
                creationTime INTEGER
            )
            """
        )
        conn.executemany(
            "INSERT INTO moz_cookies VALUES (?, ?, ?, '/', ?, ?, ?)",
            rows,
        )
        conn.commit()


def test_firefox_hoyolab_cookie_extraction_accepts_missing_ltmid(monkeypatch, tmp_path):
    appdata = tmp_path / "AppData" / "Roaming"
    firefox_root = appdata / "Mozilla" / "Firefox"
    profile = firefox_root / "Profiles" / "abc.default-release"
    (firefox_root / "profiles.ini").parent.mkdir(parents=True, exist_ok=True)
    (firefox_root / "profiles.ini").write_text(
        "[Profile0]\nName=default\nIsRelative=1\nPath=Profiles/abc.default-release\nDefault=1\n",
        encoding="utf-8",
    )
    future = int(time.time()) + 86400
    _create_firefox_cookie_db(
        profile / "cookies.sqlite",
        [
            (".hoyolab.com", "ltuid_v2", "12345", future, 10, 1),
            (".hoyolab.com", "ltoken_v2", "token-value", future, 11, 1),
        ],
    )

    monkeypatch.setenv("APPDATA", str(appdata))

    extracted = BrowserCookieExtractor().extract_from_browser("firefox", provider="hoyolab")

    assert extracted is not None
    assert extracted["ltuid"] == 12345
    assert extracted["ltoken_v2"] == "token-value"
    assert "ltmid_v2" not in extracted


def test_firefox_nikke_cookie_extraction_keeps_all_blabla_cookies(monkeypatch, tmp_path):
    appdata = tmp_path / "AppData" / "Roaming"
    firefox_root = appdata / "Mozilla" / "Firefox"
    profile = firefox_root / "Profiles" / "abc.default-release"
    (firefox_root / "profiles.ini").parent.mkdir(parents=True, exist_ok=True)
    (firefox_root / "profiles.ini").write_text(
        "[Profile0]\nName=default\nIsRelative=1\nPath=Profiles/abc.default-release\nDefault=1\n",
        encoding="utf-8",
    )
    future = int(time.time()) + 86400
    _create_firefox_cookie_db(
        profile / "cookies.sqlite",
        [
            (".blablalink.com", "session_id", "abc", future, 10, 1),
            ("api.blablalink.com", "api_cookie", "def", future, 11, 1),
        ],
    )

    monkeypatch.setenv("APPDATA", str(appdata))

    extracted = BrowserCookieExtractor().extract_from_browser("firefox", provider="nikke_blablalink")

    assert extracted is not None
    assert extracted["cookies"] == {"api_cookie": "def", "session_id": "abc"}
    assert "api_cookie=def" in extracted["cookie_header"]
    assert "session_id=abc" in extracted["cookie_header"]


def test_nikke_login_button_uses_blabla_login(monkeypatch):
    opened = []

    monkeypatch.setattr("src.utils.browser_cookie_extractor.webbrowser.open", lambda url: opened.append(url))

    BrowserCookieExtractor().open_nikke_login()

    assert opened == ["https://www.blablalink.com/login"]


def test_daily_checkin_descriptor_uses_registered_supported_games():
    starrail = ManagedProcess(
        id="hsr",
        name="붕괴: 스타레일",
        monitoring_path="/StarRail.exe",
        launch_path="/StarRail.exe",
        user_preset_id="honkai_starrail",
    )
    nikke = ManagedProcess(
        id="nikke",
        name="NIKKE",
        monitoring_path="/nikke.exe",
        launch_path="/nikke.exe",
        user_preset_id="nikke",
    )

    assert descriptor_for_process(starrail).game_id == GAME_HONKAI_STARRAIL
    assert descriptor_for_process(nikke).game_id == GAME_NIKKE


def test_daily_checkin_kst_period_uses_game_reset_times():
    descriptor = descriptor_for_process(
        ManagedProcess(
            id="hsr",
            name="붕괴: 스타레일",
            monitoring_path="/StarRail.exe",
            launch_path="/StarRail.exe",
            user_preset_id="honkai_starrail",
        )
    )

    before_reset = dt.datetime(2026, 6, 11, 0, 30)
    after_reset = dt.datetime(2026, 6, 11, 1, 30)

    start_before, end_before = checkin_period_for_descriptor(descriptor, before_reset)
    start_after, end_after = checkin_period_for_descriptor(descriptor, after_reset)

    assert start_before.day == 10
    assert end_before.day == 11
    assert start_before.hour == 1
    assert start_after.day == 11
    assert end_after.day == 12
    assert start_after.hour == 1


def test_daily_checkin_due_policy_is_conservative():
    now = 2_000.0

    assert should_attempt_daily_checkin([], now_ts=now)
    assert not should_attempt_daily_checkin([{"status": "success", "attempted_at": 1_000.0}], now_ts=now)
    assert not should_attempt_daily_checkin([{"status": "auth_required", "attempted_at": 1_000.0}], now_ts=now)
    assert not should_attempt_daily_checkin([{"status": "network_error", "attempted_at": now - 100.0}], now_ts=now)
    assert should_attempt_daily_checkin([{"status": "network_error", "attempted_at": now - 2_000.0}], now_ts=now)


def test_nikke_factory_preset_enables_resource_tracking():
    data = json.loads(Path("src/data/game_presets.json").read_text(encoding="utf-8"))
    nikke = next(preset for preset in data["presets"] if preset["id"] == "nikke")

    assert data["version"] == 4
    assert nikke["is_hoyoverse"] is False
    assert nikke["hoyolab_game_id"] is None
    assert nikke["icon_path"] == "nikke_stamina.png"
    assert nikke["icon_type"] == "system"
    assert nikke["resource_tracking_enabled"] is True
    assert nikke["resource_provider"] == "nikke_blablalink"
    assert nikke["resource_key"] == "nikke_outpost_storage"
    assert nikke["resource_label"] == "전초기지 방어 보상"
    assert resolve_preset_icon_path("nikke_stamina.png", "system")


def test_game_preset_schema_migrates_legacy_nikke_to_resource_mode(monkeypatch, tmp_path):
    preset_path = tmp_path / "game_presets_user.json"
    preset_path.write_text(
        json.dumps(
            {
                "version": 2,
                "presets": [
                    {
                        "id": "nikke",
                        "display_name": "승리의 여신: 니케",
                        "exe_patterns": ["nikke.exe"],
                        "is_hoyoverse": False,
                        "hoyolab_game_id": None,
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(GamePresetManager, "USER_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(GamePresetManager, "USER_PRESET_FILE", preset_path)

    manager = GamePresetManager()
    nikke = manager.get_preset_by_id("nikke")
    saved = json.loads(preset_path.read_text(encoding="utf-8"))

    assert saved["version"] == GamePresetManager.CURRENT_SCHEMA_VERSION
    assert nikke["resource_tracking_enabled"] is True
    assert nikke["resource_provider"] == "nikke_blablalink"
    assert nikke["resource_key"] == "nikke_outpost_storage"
    assert nikke["resource_label"] == "전초기지 방어 보상"
    assert nikke["icon_path"] == "nikke_stamina.png"
    assert nikke["icon_type"] == "system"


def test_resource_label_is_part_of_runtime_persistence_stream():
    crud_source = Path("src/data/crud.py").read_text(encoding="utf-8")
    api_client_source = Path("src/api/client.py").read_text(encoding="utf-8")
    entrypoint_source = Path("homework_helper.pyw").read_text(encoding="utf-8")

    assert '"resource_label": resource_label' in crud_source
    assert '{"resource_percent", "resource_updated_at", "resource_status", "resource_label"}' in crud_source
    assert '"resource_label": getattr(updated_process, "resource_label", None)' in api_client_source
    assert "resource_label: str | None = None" in entrypoint_source


class _FakeNikkeConfig:
    def __init__(self, payload):
        self.payload = payload
        self.updated_role = None
        self.saved_sessions = []

    def is_configured(self):
        return bool(self.payload)

    def load_session(self):
        return self.payload

    def save_session(self, cookies, *, intl_open_id=None, nikke_area_id=None):
        self.saved_sessions.append((dict(cookies), intl_open_id, nikke_area_id))
        self.payload = {
            "cookies": dict(cookies),
            "intl_open_id": intl_open_id,
            "nikke_area_id": nikke_area_id,
        }
        return True

    def update_role(self, *, intl_open_id, nikke_area_id):
        self.updated_role = (intl_open_id, nikke_area_id)
        return True


class _FakeResponse:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


def _patch_nikke_http_session(monkeypatch, *, get=None, post=None):
    created_sessions = []

    class _FakeHttpSession:
        def __init__(self):
            self.cookies = {}
            created_sessions.append(self)

        def get(self, url, **kwargs):
            if get is None:
                raise AssertionError(f"unexpected GET: {url}")
            try:
                return get(self, url, **kwargs)
            except TypeError:
                return get(url, **kwargs)

        def post(self, url, **kwargs):
            if post is None:
                raise AssertionError(f"unexpected POST: {url}")
            try:
                return post(self, url, **kwargs)
            except TypeError:
                return post(url, **kwargs)

        def close(self):
            return None

    monkeypatch.setattr("src.services.nikke.requests.Session", _FakeHttpSession)
    return created_sessions


class _FakeHoYoLabConfig:
    def __init__(self, configured=True):
        self.configured = configured

    def is_configured(self):
        return self.configured

    def load_credentials(self):
        if not self.configured:
            return None
        return {"ltuid": 12345, "ltoken_v2": "token"}


class _FakeDailyReward:
    def __init__(self, name, amount):
        self.name = name
        self.amount = amount


def test_hoyolab_daily_checkin_runs_starrail_then_zzz_post_sequence():
    class FakeClient:
        def __init__(self):
            self.calls = []

        async def claim_daily_reward(self, *, game, lang):
            self.calls.append((game, lang))
            if game == hoyolab_module.genshin.Game.STARRAIL:
                return _FakeDailyReward("성옥", 20)
            if game == hoyolab_module.genshin.Game.ZZZ:
                return _FakeDailyReward("필름", 30)
            raise AssertionError(f"unexpected game: {game}")

    client = FakeClient()
    service = HoYoLabService(config=_FakeHoYoLabConfig())
    service._client = client

    results = service.claim_daily_rewards()

    assert [call[0] for call in client.calls] == [
        hoyolab_module.genshin.Game.STARRAIL,
        hoyolab_module.genshin.Game.ZZZ,
    ]
    assert [call[1] for call in client.calls] == ["ko-kr", "ko-kr"]
    assert [(result.game_id, result.status, result.reward_name, result.reward_amount) for result in results] == [
        ("honkai_starrail", "success", "성옥", 20),
        ("zenless_zone_zero", "success", "필름", 30),
    ]


def test_hoyolab_daily_checkin_continues_after_already_claimed():
    class FakeClient:
        async def claim_daily_reward(self, *, game, lang):
            if game == hoyolab_module.genshin.Game.STARRAIL:
                raise hoyolab_module.genshin.errors.AlreadyClaimed({"retcode": -5003, "message": "already signed in"})
            return _FakeDailyReward("필름", 30)

    service = HoYoLabService(config=_FakeHoYoLabConfig())
    service._client = FakeClient()

    results = service.claim_daily_rewards()

    assert [result.status for result in results] == ["already_done", "success"]
    assert results[0].game_name == "붕괴: 스타레일"
    assert results[1].game_name == "젠레스 존 제로"


def test_hoyolab_daily_checkin_requires_configured_credentials():
    service = HoYoLabService(config=_FakeHoYoLabConfig(configured=False))

    results = service.claim_daily_rewards()

    assert [result.status for result in results] == ["auth_required", "auth_required"]
    assert [result.game_id for result in results] == ["honkai_starrail", "zenless_zone_zero"]


def test_hoyolab_daily_checkin_status_probe_is_read_only():
    class FakeClient:
        def __init__(self):
            self.reward_info_calls = []
            self.claim_calls = []

        async def get_reward_info(self, *, game, lang):
            self.reward_info_calls.append((game, lang))
            return SimpleNamespace(signed_in=(game == hoyolab_module.genshin.Game.ZZZ))

        async def claim_daily_reward(self, *, game, lang):
            self.claim_calls.append((game, lang))
            raise AssertionError("status probe must not claim daily reward")

    client = FakeClient()
    service = HoYoLabService(config=_FakeHoYoLabConfig())
    service._client = client

    results = service.get_daily_reward_status()

    assert client.reward_info_calls == [
        (hoyolab_module.genshin.Game.STARRAIL, "ko-kr"),
        (hoyolab_module.genshin.Game.ZZZ, "ko-kr"),
    ]
    assert client.claim_calls == []
    assert [(result.game_id, result.status, result.message) for result in results] == [
        ("honkai_starrail", "ready", "오늘 출석 체크가 가능합니다."),
        ("zenless_zone_zero", "already_done", "오늘 이미 출석 체크가 완료되었습니다."),
    ]


def test_nikke_outpost_storage_parses_shiftypad_daily_progress(monkeypatch):
    config = _FakeNikkeConfig({"cookies": {"session_id": "abc"}, "intl_open_id": "open-1", "nikke_area_id": 1})
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return _FakeResponse({"code": 0, "data": {"daily_progress": [{"outpost_battle_storage_fullness": 0.055}]}})

    _patch_nikke_http_session(monkeypatch, post=fake_post)

    snapshot = NikkeService(config=config).get_outpost_storage()

    assert snapshot.status == "ok"
    assert snapshot.percent == 5.5
    assert calls[0][1]["json"] == {"intl_open_id": "open-1", "nikke_area_id": 1}


def test_nikke_outpost_storage_marks_auth_expired(monkeypatch):
    config = _FakeNikkeConfig({"cookies": {"session_id": "abc"}, "intl_open_id": "open-1", "nikke_area_id": 1})

    def fake_post(url, **kwargs):
        return _FakeResponse({"code": 300001, "msg": "game not login"})

    _patch_nikke_http_session(monkeypatch, post=fake_post)

    snapshot = NikkeService(config=config).get_outpost_storage()

    assert snapshot.status == "auth_expired"
    assert snapshot.percent is None


def test_nikke_role_discovery_combines_user_info_and_saved_role(monkeypatch):
    config = _FakeNikkeConfig({"cookies": {"session_id": "abc"}})
    post_calls = []
    get_calls = []

    def fake_post(url, **kwargs):
        post_calls.append((url, kwargs))
        if url.endswith("user/CheckLogin"):
            return _FakeResponse({"code": 0, "msg": "ok"})
        if url.endswith("ugc/proxy/standalonesite/User/GetUserInfoNew"):
            return _FakeResponse({"code": 0, "data": {"info": {"intl_openid": "global-open-42"}}})
        raise AssertionError(f"unexpected POST: {url}")

    def fake_get(url, **kwargs):
        get_calls.append((url, kwargs))
        if url.endswith("game/proxy/Game/GetSavedRoleInfo"):
            return _FakeResponse({"code": 0, "data": {"role_info": {"area_id": "1", "role_id": "10105414"}}})
        raise AssertionError(f"unexpected GET: {url}")

    _patch_nikke_http_session(monkeypatch, get=fake_get, post=fake_post)

    role = NikkeService(config=config).get_role_info(refresh=True)

    assert role is not None
    assert role.intl_open_id == "42"
    assert role.nikke_area_id == 1
    assert config.updated_role == ("42", 1)
    assert any(url.endswith("game/proxy/Game/GetSavedRoleInfo") for url, _kwargs in get_calls)
    assert all(not url.endswith("game/proxy/Game/GetSavedRoleInfo") for url, _kwargs in post_calls)


def test_nikke_outpost_storage_discovers_role_before_daily_progress(monkeypatch):
    config = _FakeNikkeConfig({"cookies": {"session_id": "abc"}})
    daily_payloads = []

    def fake_post(url, **kwargs):
        if url.endswith("user/CheckLogin"):
            return _FakeResponse({"code": 0, "msg": "ok"})
        if url.endswith("ugc/proxy/standalonesite/User/GetUserInfoNew"):
            return _FakeResponse({"code": 0, "data": {"info": {"intl_openid": "nikke-open-1"}}})
        if url.endswith("game/proxy/Game/GetUserDailyContentsProgress"):
            daily_payloads.append(kwargs["json"])
            return _FakeResponse({"code": 0, "data": {"daily_progress": [{"outpost_battle_storage_fullness": 0.055}]}})
        raise AssertionError(f"unexpected POST: {url}")

    def fake_get(url, **kwargs):
        if url.endswith("game/proxy/Game/GetSavedRoleInfo"):
            return _FakeResponse({"code": 0, "data": {"role_info": {"area_id": 1}}})
        raise AssertionError(f"unexpected GET: {url}")

    _patch_nikke_http_session(monkeypatch, get=fake_get, post=fake_post)

    snapshot = NikkeService(config=config).get_outpost_storage()

    assert snapshot.status == "ok"
    assert snapshot.percent == 5.5
    assert daily_payloads == [{"intl_open_id": "1", "nikke_area_id": 1}]


def _daily_checkin_body(task):
    return {"code": 0, "data": {"tasks": [task]}}


def _daily_checkin_task(**overrides):
    task = {
        "task_id": "15",
        "task_type": 1,
        "task_name": "매일 출석 체크",
        "reward_infos": [
            {
                "is_completed": False,
                "completed_times": 0,
                "need_completed_times": 1,
                "points": 100,
            }
        ],
    }
    task.update(overrides)
    return task


def test_nikke_daily_checkin_status_ready_is_read_only(monkeypatch):
    config = _FakeNikkeConfig({"cookies": {"session_id": "abc"}})
    get_calls = []

    def fake_get(url, **kwargs):
        get_calls.append((url, kwargs))
        assert url.endswith("lip/proxy/lipass/Points/GetTaskListWithStatusV2")
        return _FakeResponse(_daily_checkin_body(_daily_checkin_task()))

    def fail_post(*args, **kwargs):
        raise AssertionError("daily check-in status probe must not POST")

    _patch_nikke_http_session(monkeypatch, get=fake_get, post=fail_post)

    status = NikkeService(config=config).get_daily_checkin_status()

    assert status.status == "ready"
    assert status.task_id == "15"
    assert status.task_name == "매일 출석 체크"
    assert status.points == 100
    assert status.completed_times == 0
    assert status.need_completed_times == 1
    assert get_calls[0][1]["params"] == {"get_top": "false", "intl_game_id": "nikke"}


def test_nikke_daily_checkin_headers_match_current_blabla_web_common_params():
    service = NikkeService(config=_FakeNikkeConfig({"cookies": {"session_id": "abc"}}))

    headers = service._request_headers()
    common_params = json.loads(headers["x-common-params"])

    assert headers["Origin"] == "https://www.blablalink.com"
    assert headers["Referer"] == "https://www.blablalink.com/nikke/"
    assert common_params["game_id"] == "16"
    assert common_params["area_id"] == "global"
    assert common_params["intl_game_id"] == "nikke"
    assert common_params["source"] == "h5"
    assert common_params["data_statistics_scene"] == "outer"
    assert common_params["data_statistics_page_id"] == "https://www.blablalink.com/nikke/"
    assert common_params["data_statistics_client_type"] == "h5"
    assert common_params["data_statistics_lang"] == "ko"


def test_nikke_daily_checkin_status_already_done_from_completed_flag(monkeypatch):
    config = _FakeNikkeConfig({"cookies": {"session_id": "abc"}})

    def fake_get(url, **kwargs):
        return _FakeResponse(
            _daily_checkin_body(
                _daily_checkin_task(
                    reward_infos=[
                        {
                            "is_completed": True,
                            "completed_times": 0,
                            "need_completed_times": 1,
                            "points": 100,
                        }
                    ]
                )
            )
        )

    _patch_nikke_http_session(monkeypatch, get=fake_get)

    status = NikkeService(config=config).get_daily_checkin_status()

    assert status.status == "already_done"
    assert "완료" in status.message


def test_nikke_daily_checkin_status_already_done_from_completed_times(monkeypatch):
    config = _FakeNikkeConfig({"cookies": {"session_id": "abc"}})

    def fake_get(url, **kwargs):
        return _FakeResponse(
            _daily_checkin_body(
                _daily_checkin_task(
                    reward_infos=[
                        {
                            "is_completed": False,
                            "completed_times": 1,
                            "need_completed_times": 1,
                            "points": 100,
                        }
                    ]
                )
            )
        )

    _patch_nikke_http_session(monkeypatch, get=fake_get)

    status = NikkeService(config=config).get_daily_checkin_status()

    assert status.status == "already_done"
    assert status.completed_times == 1
    assert status.need_completed_times == 1


def test_nikke_daily_checkin_status_maps_game_login_required(monkeypatch):
    config = _FakeNikkeConfig({"cookies": {"session_id": "abc"}})

    def fake_get(url, **kwargs):
        return _FakeResponse({"code": 300001, "msg": "game not login"})

    _patch_nikke_http_session(monkeypatch, get=fake_get)

    status = NikkeService(config=config).get_daily_checkin_status()

    assert status.status == "game_login_required"
    assert status.message == "game not login"


def test_nikke_daily_checkin_status_falls_back_to_top_tasks(monkeypatch):
    config = _FakeNikkeConfig({"cookies": {"session_id": "abc"}})
    get_top_values = []

    def fake_get(url, **kwargs):
        get_top_values.append(kwargs["params"]["get_top"])
        if kwargs["params"]["get_top"] == "false":
            return _FakeResponse({"code": 0, "data": {"tasks": []}})
        return _FakeResponse(_daily_checkin_body(_daily_checkin_task()))

    _patch_nikke_http_session(monkeypatch, get=fake_get)

    status = NikkeService(config=config).get_daily_checkin_status()

    assert status.status == "ready"
    assert get_top_values == ["false", "true"]


def test_nikke_daily_checkin_status_requires_configured_session(monkeypatch):
    config = _FakeNikkeConfig(None)

    def fail_get(*args, **kwargs):
        raise AssertionError("unconfigured daily check-in status probe must not call network")

    _patch_nikke_http_session(monkeypatch, get=fail_get)

    status = NikkeService(config=config).get_daily_checkin_status()

    assert status.status == "auth_required"


def test_nikke_daily_checkin_claim_posts_ready_task(monkeypatch):
    config = _FakeNikkeConfig({"cookies": {"session_id": "abc"}})
    post_calls = []

    def fake_get(url, **kwargs):
        return _FakeResponse(_daily_checkin_body(_daily_checkin_task()))

    def fake_post(url, **kwargs):
        post_calls.append((url, kwargs))
        assert url.endswith("lip/proxy/lipass/Points/DailyCheckIn")
        return _FakeResponse({"code": 0, "msg": "ok"})

    _patch_nikke_http_session(monkeypatch, get=fake_get, post=fake_post)

    result = NikkeService(config=config).claim_daily_checkin()

    assert result.status == "success"
    assert result.task_id == "15"
    assert result.points == 100
    assert result.raw_debug["post_called"] is True
    assert post_calls[0][1]["json"] == {"task_id": "15"}


def test_nikke_daily_checkin_claim_persists_refreshed_session_cookie(monkeypatch):
    config = _FakeNikkeConfig({"cookies": {"session_id": "old"}})

    def fake_get(session, url, **kwargs):
        assert session.cookies["session_id"] == "old"
        session.cookies["session_id"] = "fresh"
        return _FakeResponse(_daily_checkin_body(_daily_checkin_task()))

    def fake_post(session, url, **kwargs):
        assert url.endswith("lip/proxy/lipass/Points/DailyCheckIn")
        assert session.cookies["session_id"] == "fresh"
        return _FakeResponse({"code": 0, "msg": "ok"})

    _patch_nikke_http_session(monkeypatch, get=fake_get, post=fake_post)

    result = NikkeService(config=config).claim_daily_checkin()

    assert result.status == "success"
    assert result.raw_debug["post_called"] is True
    assert config.saved_sessions
    assert config.saved_sessions[-1][0]["session_id"] == "fresh"


def test_nikke_daily_checkin_claim_skips_post_when_already_done(monkeypatch):
    config = _FakeNikkeConfig({"cookies": {"session_id": "abc"}})

    def fake_get(url, **kwargs):
        return _FakeResponse(
            _daily_checkin_body(
                _daily_checkin_task(
                    reward_infos=[
                        {
                            "is_completed": True,
                            "completed_times": 1,
                            "need_completed_times": 1,
                            "points": 100,
                        }
                    ]
                )
            )
        )

    def fail_post(*args, **kwargs):
        raise AssertionError("already completed check-in must not POST")

    _patch_nikke_http_session(monkeypatch, get=fake_get, post=fail_post)

    result = NikkeService(config=config).claim_daily_checkin()

    assert result.status == "already_done"
    assert result.raw_debug["post_called"] is False


def test_nikke_daily_checkin_claim_maps_already_done_post_code(monkeypatch):
    config = _FakeNikkeConfig({"cookies": {"session_id": "abc"}})

    def fake_get(url, **kwargs):
        return _FakeResponse(_daily_checkin_body(_daily_checkin_task()))

    def fake_post(url, **kwargs):
        return _FakeResponse({"code": 1001009, "msg": "already checked in"})

    _patch_nikke_http_session(monkeypatch, get=fake_get, post=fake_post)

    result = NikkeService(config=config).claim_daily_checkin()

    assert result.status == "already_done"
    assert result.message == "already checked in"
    assert result.raw_debug["post_called"] is True


def test_nikke_daily_checkin_claim_maps_login_required_post_code(monkeypatch):
    config = _FakeNikkeConfig({"cookies": {"session_id": "abc"}})

    def fake_get(url, **kwargs):
        return _FakeResponse(_daily_checkin_body(_daily_checkin_task()))

    def fake_post(url, **kwargs):
        return _FakeResponse({"code": 300001, "msg": "game not login"})

    _patch_nikke_http_session(monkeypatch, get=fake_get, post=fake_post)

    result = NikkeService(config=config).claim_daily_checkin()

    assert result.status == "game_login_required"
    assert result.message == "game not login"
    assert result.raw_debug["post_called"] is True


def test_nikke_daily_checkin_claim_maps_inner_token_invalid_to_cookie_refresh(monkeypatch):
    config = _FakeNikkeConfig({"cookies": {"session_id": "abc"}})

    def fake_get(url, **kwargs):
        return _FakeResponse(_daily_checkin_body(_daily_checkin_task()))

    def fake_post(url, **kwargs):
        return _FakeResponse({"ret": 11002, "msg": "Inner token is invalid[3]."})

    _patch_nikke_http_session(monkeypatch, get=fake_get, post=fake_post)

    result = NikkeService(config=config).claim_daily_checkin()

    assert result.status == "game_login_required"
    assert "BlablaLink 세션 쿠키 갱신이 필요합니다" in result.message
    assert "ret=11002" in result.message
    assert "Inner token is invalid[3]." in result.message
    assert result.raw_debug["post_called"] is True


def test_process_progress_exposes_generic_resource_snapshot():
    process = ManagedProcess(
        id="nikke",
        name="NIKKE",
        monitoring_path="/nikke.exe",
        launch_path="/nikke.exe",
        resource_tracking_enabled=True,
        resource_provider="nikke_blablalink",
        resource_key="nikke_outpost_storage",
        resource_label="전초기지 방어 보상",
        resource_percent=5.5,
        resource_status="ok",
    )

    progress = calculate_process_progress(process)

    assert progress["schema_version"] == 2
    assert progress["source"] == "server_tracked"
    assert progress["kind"] == "resource"
    assert progress["percentage"] == 5.5
    assert progress["display_text"] == "5.5%"
    assert progress["key"] == "nikke_outpost_storage"
    assert progress["projection"]["strategy"] == "linear_percent_fill"
    assert progress["projection"]["full_recovery_seconds"] == 24 * 60 * 60


def test_nikke_outpost_resource_progress_predicts_24h_fill_rate():
    updated_at = dt.datetime(2026, 5, 20, 0, 0).timestamp()
    process = ManagedProcess(
        id="nikke",
        name="NIKKE",
        monitoring_path="/nikke.exe",
        launch_path="/nikke.exe",
        resource_tracking_enabled=True,
        resource_provider="nikke_blablalink",
        resource_key="nikke_outpost_storage",
        resource_label="전초기지 방어 보상",
        resource_percent=25.0,
        resource_updated_at=updated_at,
        resource_status="ok",
    )

    half_day = dt.datetime(2026, 5, 20, 12, 0)
    progress = calculate_process_progress(process, current_dt=half_day)

    assert progress["source"] == "server_tracked"
    assert progress["kind"] == "resource"
    assert progress["percentage"] == 75.0
    assert progress["display_text"] == "75.0%"
    assert progress["projection"]["base_value"] == 25.0
    assert progress["projection"]["ready_at"] == dt.datetime(2026, 5, 20, 18, 0).timestamp()


def test_nikke_outpost_resource_progress_caps_at_100_percent():
    updated_at = dt.datetime(2026, 5, 20, 0, 0).timestamp()
    process = ManagedProcess(
        id="nikke",
        name="NIKKE",
        monitoring_path="/nikke.exe",
        launch_path="/nikke.exe",
        resource_tracking_enabled=True,
        resource_provider="nikke_blablalink",
        resource_key="nikke_outpost_storage",
        resource_label="전초기지 방어 보상",
        resource_percent=90.0,
        resource_updated_at=updated_at,
        resource_status="ok",
    )

    next_day = dt.datetime(2026, 5, 21, 0, 0)
    progress = calculate_process_progress(process, current_dt=next_day)

    assert progress["percentage"] == 100.0
    assert progress["display_text"] == "100.0%"
    assert progress["remaining_seconds"] == 0


def test_tracked_resource_without_snapshot_does_not_fall_back_to_cycle():
    process = ManagedProcess(
        id="nikke",
        name="NIKKE",
        monitoring_path="/nikke.exe",
        launch_path="/nikke.exe",
        last_played_timestamp=dt.datetime(2026, 5, 20, 0, 0).timestamp(),
        user_cycle_hours=24,
        resource_tracking_enabled=True,
        resource_provider="nikke_blablalink",
        resource_key="nikke_outpost_storage",
        resource_label="전초기지 방어 보상",
        resource_status="auth_required",
    )

    progress = calculate_process_progress(process, current_dt=dt.datetime(2026, 5, 20, 12, 0))

    assert progress["source"] == "server_tracked"
    assert progress["kind"] == "resource"
    assert progress["status"] == "auth_required"
    assert progress["display_text"] == "동기화 필요"
    assert "remaining_seconds" not in progress


def test_nikke_resource_persist_task_updates_process_and_session_percent():
    from src.core.resource_reconcile import _ResourcePersistTask

    process = ManagedProcess(
        id="nikke",
        name="NIKKE",
        monitoring_path="/nikke.exe",
        launch_path="/nikke.exe",
        resource_tracking_enabled=True,
        resource_provider="nikke_blablalink",
        resource_key="nikke_outpost_storage",
        resource_label="전초기지 방어 보상",
        resource_percent=10.0,
        resource_updated_at=1000.0,
        resource_status="ok",
    )

    class FakeDataManager:
        process_updates = []
        session_updates = []

        def get_process_by_id(self, process_id):
            assert process_id == "nikke"
            return process

        def update_process_resource(self, process_id, percent, updated_at, status, label):
            self.process_updates.append((process_id, percent, updated_at, status, label))
            return True

        def update_session_resource(self, session_id, resource_percent_at_end):
            self.session_updates.append((session_id, resource_percent_at_end))
            return True

    class Finished:
        def __init__(self):
            self.payloads = []

        def emit(self, *args):
            self.payloads.append(args)

    class Signals:
        def __init__(self):
            self.finished = Finished()

    data_manager = FakeDataManager()
    signals = Signals()
    task = _ResourcePersistTask(
        process_id="nikke",
        process_name="NIKKE",
        session_id=7,
        lifecycle_token=1,
        request_seq=1,
        fetched_percent=20.0,
        fetched_label="전초기지 방어 보상",
        fetched_status="ok",
        fetched_at=3600.0,
        exit_timestamp=0.0,
        allow_session_correction=True,
        applied_session_percent=10.0,
        data_manager=data_manager,
        should_abort=lambda: False,
        signals=signals,
    )

    task.run()

    assert data_manager.process_updates == [("nikke", 20.0, 3600.0, "ok", "전초기지 방어 보상")]
    assert data_manager.session_updates == [(7, pytest.approx(15.8333333333))]
    assert signals.finished.payloads[0][3]["persist_succeeded"] is True


def test_process_monitor_calibrates_nikke_resource_session_on_start(monkeypatch):
    from src.core.process_monitor import ProcessMonitor
    import src.services.nikke as nikke_module

    now = time.time()
    process = ManagedProcess(
        id="nikke",
        name="NIKKE",
        monitoring_path="/nikke.exe",
        launch_path="/nikke.exe",
        resource_tracking_enabled=True,
        resource_provider="nikke_blablalink",
        resource_key="nikke_outpost_storage",
        resource_label="전초기지 방어 보상",
        resource_percent=10.0,
        resource_updated_at=now,
        resource_status="ok",
    )

    class LastSession:
        id = 7
        resource_percent_at_end = 10.0

    class FakeDataManager:
        resource_updates = []
        session_updates = []

        def get_last_session(self, process_id):
            assert process_id == "nikke"
            return LastSession()

        def update_session_resource(self, session_id, resource_percent_at_end):
            self.session_updates.append((session_id, resource_percent_at_end))
            return True

        def update_process_resource(self, process_id, percent, updated_at, status, label):
            self.resource_updates.append((process_id, percent, updated_at, status, label))
            return True

    class FakeService:
        def get_outpost_storage(self):
            return nikke_module.GameResourceSnapshot(
                provider="nikke_blablalink",
                resource_key="nikke_outpost_storage",
                label="전초기지 방어 보상",
                percent=20.0,
                status="ok",
                updated_at=dt.datetime.fromtimestamp(now + 1),
            )

    monkeypatch.setattr(nikke_module, "get_nikke_service", lambda: FakeService())

    data_manager = FakeDataManager()
    ProcessMonitor(data_manager)._calibrate_external_resource_on_game_start(process)

    assert data_manager.session_updates == [(7, pytest.approx(20.0, abs=0.01))]
    assert data_manager.resource_updates == [("nikke", 20.0, pytest.approx(now + 1), "ok", "전초기지 방어 보상")]
