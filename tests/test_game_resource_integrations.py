import sqlite3
import time
from pathlib import Path

from src.core.process_progress import calculate_process_progress
from src.data.data_models import ManagedProcess
from src.services.nikke import NikkeService
from src.utils.browser_cookie_extractor import BrowserCookieExtractor


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


class _FakeNikkeConfig:
    def __init__(self, payload):
        self.payload = payload
        self.updated_role = None

    def is_configured(self):
        return bool(self.payload)

    def load_session(self):
        return self.payload

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


def test_nikke_outpost_storage_parses_shiftypad_daily_progress(monkeypatch):
    config = _FakeNikkeConfig({"cookies": {"session_id": "abc"}, "intl_open_id": "open-1", "nikke_area_id": 1})
    calls = []

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return _FakeResponse({"code": 0, "data": {"daily_progress": [{"outpost_battle_storage_fullness": 0.055}]}})

    monkeypatch.setattr("src.services.nikke.requests.post", fake_post)

    snapshot = NikkeService(config=config).get_outpost_storage()

    assert snapshot.status == "ok"
    assert snapshot.percent == 5.5
    assert calls[0][1]["json"] == {"intl_open_id": "open-1", "nikke_area_id": 1}


def test_nikke_outpost_storage_marks_auth_expired(monkeypatch):
    config = _FakeNikkeConfig({"cookies": {"session_id": "abc"}, "intl_open_id": "open-1", "nikke_area_id": 1})

    def fake_post(url, **kwargs):
        return _FakeResponse({"code": 300001, "msg": "game not login"})

    monkeypatch.setattr("src.services.nikke.requests.post", fake_post)

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

    monkeypatch.setattr("src.services.nikke.requests.post", fake_post)
    monkeypatch.setattr("src.services.nikke.requests.get", fake_get)

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

    monkeypatch.setattr("src.services.nikke.requests.post", fake_post)
    monkeypatch.setattr("src.services.nikke.requests.get", fake_get)

    snapshot = NikkeService(config=config).get_outpost_storage()

    assert snapshot.status == "ok"
    assert snapshot.percent == 5.5
    assert daily_payloads == [{"intl_open_id": "1", "nikke_area_id": 1}]


def test_process_progress_exposes_generic_resource_snapshot():
    process = ManagedProcess(
        id="nikke",
        name="NIKKE",
        monitoring_path="/nikke.exe",
        launch_path="/nikke.exe",
        resource_tracking_enabled=True,
        resource_provider="nikke_blablalink",
        resource_key="nikke_outpost_storage",
        resource_label="보관함 용량",
        resource_percent=5.5,
        resource_status="ok",
    )

    progress = calculate_process_progress(process)

    assert progress["kind"] == "resource"
    assert progress["percentage"] == 5.5
    assert progress["display_text"] == "5.5%"
    assert progress["resource_key"] == "nikke_outpost_storage"
