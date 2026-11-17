"""외부 자원 관측 검사의 운영 데이터·인증·네트워크 접근을 한 곳에서 막는다."""
from __future__ import annotations

import os
from pathlib import Path
import socket
import subprocess
import urllib.request
import webbrowser

import pytest


@pytest.fixture
def resource_test_isolation(monkeypatch, tmp_path):
    """명시적으로 선택한 자원 검사 모듈만 사용하는 격리 경계다.

    앱 경로를 평가하는 모듈이 collection 때 import되므로 환경변수는 pytest를
    시작하기 전에 지정해야 한다. 함수 fixture에서 뒤늦게 지정하지 않는다.
    실제 제공자·설정·HTTP가 필요하면 각 검사에서 fake를 명시적으로 주입한다.
    """
    from src.data import database, crud
    from src.utils.hoyolab_config import HoYoLabConfig
    from src.utils.nikke_config import NikkeConfig
    from src.utils.browser_cookie_extractor import BrowserCookieExtractor
    from src.services.wuwa import WuwaGateway
    import aiohttp
    import requests

    app_data = os.environ.get("HH_TEST_APPDATA_DIR")
    assert app_data, "pytest 시작 전 HH_TEST_APPDATA_DIR 임시 경로를 지정해야 한다"
    isolated_root = Path(app_data).resolve()
    assert isolated_root != Path.home() / ".config" / "HomeworkHelper"
    assert Path(database.base_dir).resolve() == isolated_root
    assert Path(HoYoLabConfig.CONFIG_DIR).resolve() == isolated_root
    assert Path(NikkeConfig.CONFIG_DIR).resolve() == isolated_root

    def blocked(*args, **kwargs):
        raise AssertionError("격리 자원 검사에서 실제 인증·브라우저·네트워크 접근을 차단했습니다")

    # 모든 실제 인증 읽기·쓰기는 이 두 저장소 경계를 지나야 한다.
    for config, names in (
        (HoYoLabConfig, ("load_credentials", "save_credentials", "clear_credentials")),
        (NikkeConfig, ("load_session", "save_session", "clear_session")),
    ):
        for name in names:
            monkeypatch.setattr(config, name, blocked)
    # 브라우저 프로필 탐색과 로그인 창 열기는 모두 운영 사용자 상태에 닿는다.
    for name in ("extract_from_browser", "_get_cookie_db_path", "_get_firefox_profiles_dir",
                 "_get_local_state_path", "_get_encryption_key", "_decrypt_cookie_value"):
        monkeypatch.setattr(BrowserCookieExtractor, name, blocked)
    monkeypatch.setattr(webbrowser, "open", blocked)
    # 명조는 별도 token store 없이 런처 캐시를 읽는다. 새 단일 입구도 실조회 전에 막는다.
    monkeypatch.setattr(WuwaGateway, "read_accounts", blocked)
    monkeypatch.setattr(WuwaGateway, "post_json", blocked)

    monkeypatch.setattr(requests.sessions.Session, "request", blocked)
    monkeypatch.setattr(aiohttp.ClientSession, "_request", blocked)
    monkeypatch.setattr(urllib.request, "urlopen", blocked)
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", blocked)
    monkeypatch.setattr(subprocess, "run", blocked)
    monkeypatch.setattr(subprocess, "Popen", blocked)
    # Qt의 외부 URL 열기는 Python subprocess를 통하지 않을 수 있다.
    from PySide6.QtGui import QDesktopServices
    monkeypatch.setattr(QDesktopServices, "openUrl", blocked)
    # 선택된 HTTP 래퍼 밖으로 새 호출이 생겨도 외부 연결·DNS로 빠져나가지 못한다.
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)

    # 운영 engine/session은 fixture로 사용하지 않는다. 검사는 별도 in-memory DB를 주입한다.
    monkeypatch.setattr(database.engine, "connect", blocked)
    monkeypatch.setattr(crud, "base_dir", str(tmp_path / "mutation-backups"))
