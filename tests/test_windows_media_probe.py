"""공용 media probe의 운영 데이터 비변경·환경 격리·시각 검수 경계를 확인한다."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
from types import SimpleNamespace

import pytest

from tools import windows_media_probe as probe


def test_media_json_projection_keeps_timing_and_image_size_without_image_bytes():
    from src.core.media_center import MediaCenterSnapshot
    from src.core.media_sessions import MediaSessionInfo
    session = MediaSessionInfo(
        "spotify", "Spotify.exe", artwork=b"private image contents",
        position_seconds=30, duration_seconds=180, timeline_updated_at=1792236000,
        playback_rate=1,
    )
    snapshot = MediaCenterSnapshot(sessions=(session,), bgm_session_id="spotify", running=True)
    result = json.loads(json.dumps(probe._media_snapshot_payload(snapshot)))
    assert result["bgm_session_id"] == "spotify" and result["running"]
    row, = result["sessions"]
    assert "artwork" not in row and row["artwork_bytes"] == len(session.artwork)
    assert row["position_seconds"] == 30 and row["duration_seconds"] == 180
    assert row["timeline_updated_at"] == 1792236000 and row["playback_rate"] == 1
    assert "private image" not in json.dumps(result)
    assert session.artwork == b"private image contents"


def test_spotify_window_observe_dispatch_preserves_real_profile_only_as_reader_input(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", "actual-roaming")
    monkeypatch.setenv("LOCALAPPDATA", "actual-local")
    def observe(source, local):
        assert source == tmp_path / "actual-roaming" and local == "actual-local"
        assert os.environ["APPDATA"] != "actual-roaming"
        assert os.environ["LOCALAPPDATA"] != "actual-local"
        return {"ok": True, "writes": []}
    monkeypatch.setattr(probe, "_spotify_window_observe", observe)
    assert probe.run(tmp_path, tmp_path / "actual-roaming", tmp_path / "result", "spotify-window-observe")["ok"]


@pytest.mark.parametrize("failure", [False, True])
def test_spotify_identity_reader_keeps_isolated_environment_even_on_failure(tmp_path, monkeypatch, failure):
    from src.core import spotify_app
    monkeypatch.setenv("APPDATA", "isolated-roaming")
    monkeypatch.setenv("LOCALAPPDATA", "isolated-local")
    monkeypatch.setitem(sys.modules, "src.core.process_monitor", SimpleNamespace())
    def read(**kwargs):
        assert kwargs == {"appdata": str(tmp_path), "local_appdata": "actual-local"}
        assert os.environ["APPDATA"] == "isolated-roaming" and os.environ["LOCALAPPDATA"] == "isolated-local"
        if failure:
            raise OSError("native identity failed")
        return ()
    monkeypatch.setattr(spotify_app, "spotify_processes", read)
    if failure:
        with pytest.raises(OSError, match="identity failed"):
            probe._spotify_probe_processes(tmp_path, "actual-local")
    else:
        assert probe._spotify_probe_processes(tmp_path, "actual-local") == ()
    assert os.environ["APPDATA"] == "isolated-roaming" and os.environ["LOCALAPPDATA"] == "isolated-local"


def test_spotify_window_inventory_only_contains_verified_process_windows(tmp_path, monkeypatch):
    from src.core.spotify_app import SpotifyProcess
    process = SpotifyProcess(41, 123, "C:/Spotify.exe")
    monkeypatch.setattr(probe, "_spotify_probe_processes", lambda *_args: (process,))
    def enumerate_windows(callback, context):
        for hwnd in (10, 11):
            callback(hwnd, context)
    monkeypatch.setitem(sys.modules, "win32gui", SimpleNamespace(
        EnumWindows=enumerate_windows, IsWindowVisible=lambda hwnd: True,
        IsIconic=lambda hwnd: False, GetWindowRect=lambda hwnd: (1, 2, 301, 402),
        GetClassName=lambda hwnd: "Chrome_WidgetWin_0", GetWindow=lambda *args: 0,
        GetForegroundWindow=lambda: 11))
    monkeypatch.setitem(sys.modules, "win32process", SimpleNamespace(
        GetWindowThreadProcessId=lambda hwnd: (1, 41 if hwnd == 11 else 99)))
    result = probe._spotify_window_state(tmp_path, None)
    assert result["processes"] == [{"pid": 41, "create_time": 123, "path": "C:/Spotify.exe"}]
    assert result["windows"] == [{"hwnd": 11, "pid": 41, "create_time": 123, "path": "C:/Spotify.exe",
        "visible": True, "iconic": False, "rect": [1, 2, 301, 402], "class": "Chrome_WidgetWin_0", "owner": 0}]


def test_spotify_window_observe_records_native_changes_without_window_or_playback_actions(tmp_path, monkeypatch):
    from src.core import media_center
    from src.core.media_sessions import MediaSessionInfo
    clock, cleaned, menus = [0.0], [], []
    window = {"hwnd": 11, "pid": 41, "create_time": 123, "path": "C:/Spotify.exe", "visible": True, "owner": 0}
    snapshot = media_center.MediaCenterSnapshot(
        sessions=(MediaSessionInfo("spotify", "Spotify.exe", artwork=b"image", status="playing"),), running=True)
    class Runtime:
        def __init__(self, spotify_launcher):
            assert spotify_launcher() is False
            self.snapshot = snapshot
        def start(self, options):
            assert not any((options.auto_bgm, options.background_mute, options.auto_focus))
            return True
        def stop(self, **kwargs):
            cleaned.append(True)
            return True
    monkeypatch.setattr(media_center, "MediaCenterRuntime", Runtime)
    monkeypatch.setattr(probe, "_wait", lambda predicate, _seconds: predicate())
    monkeypatch.setattr(probe.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(probe.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(probe, "_spotify_window_state", lambda *args: {
        "processes": [], "windows": [{**window, "iconic": clock[0] < .5}], "foreground_hwnd": 11})
    monkeypatch.setattr(probe, "_spotify_chrome_controls", lambda row: menus.append(row) or {
        "controls": [{"name": "File"}], "worker_stopped": True})
    result = probe._spotify_window_observe(tmp_path, None)
    assert result["ok"] and result["writes"] == [] and cleaned == [True]
    assert len(result["trace"]) == 8 and menus[0]["hwnd"] == 11
    assert [row["at_ms"] for row in result["trace"]] == [index * 125 for index in range(8)]
    assert result["trace"][0]["windows"][0]["iconic"] and not result["trace"][-1]["windows"][0]["iconic"]
    json.dumps(result)


@pytest.mark.parametrize("has_native_menu", [False, True])
@pytest.mark.parametrize("dpi", [96, 144])
def test_spotify_menu_diagnostic_reads_native_ids_and_deep_chrome_without_account_or_media_names(monkeypatch, has_native_menu, dpi):
    import ctypes
    from src.utils import audio_control
    cleaned, reads = [], []
    def node(kind, name="", *, x=10, y=10, children=()):
        return SimpleNamespace(CurrentControlType=kind, CurrentName=name, children=children, CurrentIsOffscreen=False,
                               CurrentBoundingRectangle=SimpleNamespace(left=x, top=y, right=x + 30, bottom=y + 20))
    options = node(50000, "Options")
    options.CurrentBoundingRectangle.right = 80  # 96 DPI 후보 제외, 144 DPI에서는 실제 60 DIP 안이다.
    body, account = node(50000, "PRIVATE TRACK TITLE", y=300), node(50000, "PRIVATE ACCOUNT", x=900)
    branch = node(50033, children=(options, body, account))
    for _ in range(4):
        branch = node(50033, children=(branch,))
    root = node(50032, children=(branch,))
    root.CurrentBoundingRectangle = SimpleNamespace(left=0, top=0, right=1000, bottom=1000)
    def next_sibling(value):
        return {id(options): body, id(body): account}.get(id(value))
    automation = SimpleNamespace(ElementFromHandle=lambda hwnd: root, ControlViewWalker=SimpleNamespace(
        GetFirstChildElement=lambda value: value.children[0] if value.children else None,
        GetNextSiblingElement=next_sibling))
    client = SimpleNamespace(GetModule=lambda name: SimpleNamespace(IUIAutomation2=object),
                             CreateObject=lambda *args, **kwargs: automation)
    monkeypatch.setitem(sys.modules, "comtypes", SimpleNamespace(
        client=client, COINIT_MULTITHREADED=0, CoInitializeEx=lambda value: None,
        CoUninitialize=lambda: cleaned.append(True)))
    monkeypatch.setitem(sys.modules, "win32process", SimpleNamespace(GetWindowThreadProcessId=lambda hwnd: (1, 41)))
    def menu_info(menu, index, by_position, buffer):
        reads.append((menu, index, by_position))
        buffer.update(text="File" if menu == 100 else "Exit", wID=7 if menu == 100 else 42,
                      hSubMenu=200 if menu == 100 else 0, fState=0)
    monkeypatch.setitem(sys.modules, "win32gui", SimpleNamespace(
        GetMenu=lambda hwnd: 100 if has_native_menu else 0,
        GetMenuItemCount=lambda menu: 1, GetMenuItemInfo=menu_info))
    monkeypatch.setitem(sys.modules, "win32gui_struct", SimpleNamespace(
        EmptyMENUITEMINFO=lambda **kwargs: ({}, []), UnpackMENUITEMINFO=lambda value: SimpleNamespace(**value)))
    monkeypatch.setattr(audio_control, "verify_identity", lambda process: True)
    class GetDpi:
        def __call__(self, hwnd):
            assert hwnd == 11
            return dpi
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: SimpleNamespace(GetDpiForWindow=GetDpi()), raising=False)
    result = probe._spotify_chrome_controls({"hwnd": 11, "pid": 41, "create_time": 123,
                                            "path": "C:/Spotify.exe", "rect": [0, 0, 1000, 1000]})
    assert result["worker_stopped"] and cleaned == [True]
    assert result["controls"] == [{"name": "Options", "control_type": 50000, "depth": 6,
                                   "offscreen": False, "bounds": [10, 10, 80, 30]}]
    assert result["window_dpi"] == dpi and result["window_uia_bounds"] == [0, 0, 1000, 1000]
    assert result["menu_button_count"] == (1 if dpi == 144 else 0)
    assert result["depth_type_counts"]["6:50000"] == 3
    assert automation.ConnectionTimeout == 500 and automation.TransactionTimeout == 1500
    assert "PRIVATE" not in json.dumps(result)
    assert result["native_menu"]["handle"] == (100 if has_native_menu else 0)
    if has_native_menu:
        assert reads == [(100, 0, True), (200, 0, True)]
        assert result["native_menu"]["items"][-1] == {"path": ["File", "Exit"], "id": 42, "submenu": 0, "state": 0}
    else:
        assert reads == [] and result["native_menu"]["items"] == []


@pytest.mark.parametrize("action", ["close", "minimize"])
@pytest.mark.parametrize("condition", ["valid", "cancelled", "pid_reused", "window_changed", "hidden", "owned", "already_iconic", "native_error"])
def test_spotify_window_action_verifies_identity_and_sends_at_most_one_request(monkeypatch, action, condition):
    import ctypes
    from src.utils import audio_control
    calls = []
    window = {"hwnd": 11, "pid": 41, "create_time": 123, "path": "C:/Spotify.exe"}
    def native(*args):
        calls.append(args)
        if condition == "native_error":
            raise OSError("native request failed")
        return True
    class Show:
        def __call__(self, *args):
            return native(*args)
    monkeypatch.setattr(ctypes, "WinDLL", lambda *args, **kwargs: SimpleNamespace(ShowWindowAsync=Show()), raising=False)
    monkeypatch.setattr(audio_control, "verify_identity", lambda process: condition != "pid_reused")
    monkeypatch.setitem(sys.modules, "win32gui", SimpleNamespace(
        IsWindowVisible=lambda hwnd: condition != "hidden", GetWindow=lambda *args: condition == "owned",
        IsIconic=lambda hwnd: condition == "already_iconic", PostMessage=native))
    monkeypatch.setitem(sys.modules, "win32process", SimpleNamespace(
        GetWindowThreadProcessId=lambda hwnd: (1, 99 if condition == "window_changed" else 41)))
    if condition == "native_error":
        result = probe._spotify_window_action(window, action, is_current=lambda: True)
        assert result == {"attempted": True, "accepted": False, "error_type": "OSError", "error": "native request failed"}
        assert len(calls) == 1
    elif condition in ("cancelled", "pid_reused", "window_changed", "hidden", "owned"):
        with pytest.raises(ValueError, match="identity"):
            probe._spotify_window_action(window, action, is_current=lambda: condition != "cancelled")
        assert not calls
    else:
        result = probe._spotify_window_action(window, action, is_current=lambda: True)
        if condition == "already_iconic" and action == "minimize":
            assert result == {"attempted": False, "accepted": None, "already_minimized": True}
            assert not calls
        else:
            assert result == {"attempted": True, "accepted": True}
            assert calls == [(11, 0x0010, 0, 0)] if action == "close" else calls == [(11, 7)]


@pytest.mark.parametrize("scenario, duration", [("spotify-window-open", 10), ("spotify-window-close", 5), ("spotify-window-minimize", 5)])
def test_spotify_window_experiments_keep_warm_identity_and_trace_post_request_without_playback(tmp_path, monkeypatch, scenario, duration):
    from src.core import media_center, spotify_app
    from src.core.media_sessions import MediaSessionInfo
    clock, launches, actions, chrome, options = [0.0], [], [], [], []
    window = {"hwnd": 11, "pid": 41, "create_time": -100, "path": "C:/Spotify.exe", "visible": True, "owner": 0}
    session = MediaSessionInfo("spotify", "Spotify.exe", status="paused", artwork=b"private image")
    snapshot = media_center.MediaCenterSnapshot(sessions=(session,), running=True)
    class Runtime:
        running = True
        def __init__(self, spotify_launcher):
            assert not spotify_launcher()
            self.snapshot = snapshot
        def start(self, value):
            options.append(value)
            return True
        def stop(self, **kwargs):
            self.running = False
            return True
    monkeypatch.setattr(media_center, "MediaCenterRuntime", Runtime)
    monkeypatch.setattr(spotify_app, "launch_spotify", lambda: launches.append("spotify:") or True)
    monkeypatch.setattr(probe, "_wait", lambda predicate, seconds: predicate())
    monkeypatch.setattr(probe.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(probe.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(probe, "_spotify_window_state", lambda *_args: {
        "processes": [{"pid": 41, "create_time": -100, "path": "C:/Spotify.exe"}],
        "windows": [{**window, "iconic": clock[0] < .5}], "foreground_hwnd": 11})
    monkeypatch.setattr(probe, "_spotify_window_action", lambda target, action, is_current: (
        actions.append((target, action, is_current())) or {"attempted": True, "accepted": True}))
    def chrome_controls(target, **kwargs):
        chrome.append(target)
        assert not kwargs
        return {"controls": []}
    monkeypatch.setattr(probe, "_spotify_chrome_controls", chrome_controls)
    result = probe._spotify_window_observe(tmp_path, None, scenario)
    assert result["ok"] and result["cleanup_ok"] and not result["writes"]
    assert result["request"]["accepted"] and result["request"]["attempted"]
    assert len(result["trace"]) == duration * 8 + 1
    assert result["trace"][-1]["at_ms"] == duration * 1000
    assert all(row["media"]["sessions"][0]["status"] == "paused" for row in result["trace"])
    assert all(not any((value.auto_bgm, value.background_mute, value.auto_focus)) for value in options)
    if scenario.endswith("-open"):
        assert launches == ["spotify:"] and not actions and len(chrome) == 1
    else:
        assert not launches and actions == [(window | {"iconic": True}, scenario.removeprefix("spotify-window-"), True)] and not chrome
    json.dumps(result)


@pytest.mark.parametrize("condition", ["cold", "later_playing", "process", "session", "external", "no_window"])
@pytest.mark.parametrize("first_action, first_delay", [("minimize", 0), ("close", 0), ("close", 5)])
def test_spotify_startup_comparison_uses_product_play_once_and_stops_at_fixed_phases(tmp_path, monkeypatch, condition, first_action, first_delay):
    import asyncio
    from src.core import media_center, media_sessions, spotify_app
    clock, calls, phases = [0.0], [], {"cold": False, "minimizes": 0, "closed": False}
    session = media_sessions.MediaSessionInfo("spotify", "Spotify.exe", status="playing")
    before = (session,) if condition == "session" else (
        media_sessions.MediaSessionInfo("browser", "Firefox.exe", status="playing"),) if condition == "external" else ()
    class Backend:
        async def snapshot(self):
            return before
        async def control(self, session_id, action):
            calls.append(("control", session_id, action))
            return True
    class Runtime:
        running = False
        pending_window = True
        def __init__(self, **kwargs):
            self.kwargs, self.backend = kwargs, kwargs["backend_factory"]()
            self.snapshot = media_center.MediaCenterSnapshot()
            phases["runtime"] = self
        def start(self, options):
            assert not any((options.auto_bgm, options.background_mute, options.auto_focus))
            self.running = True
            rows = asyncio.run(self.backend.snapshot())
            self.snapshot = media_center.MediaCenterSnapshot(sessions=rows, running=True)
            return True
        def request(self, action):
            calls.append(("request", action))
            assert action == "play" and self.kwargs["spotify_process_reader"]() == ()
            assert self.kwargs["dj_launcher"]()
            phases["cold"] = True
            self.pending_window = not self.kwargs["spotify_window_minimizer"](1, is_current=lambda: self.running)
            assert asyncio.run(self.backend.control("spotify", "play"))
            current_session = media_sessions.MediaSessionInfo("spotify", "Spotify.exe", status="paused") if condition == "later_playing" else session
            self.snapshot = media_center.MediaCenterSnapshot(sessions=(current_session,), bgm_session_id="spotify", running=True)
            return True
        def stop(self, **kwargs):
            calls.append(("stop",))
            self.running = False
            return True
    def state(*args):
        has_process = phases["cold"] or condition == "process"
        process = {"pid": 41, "create_time": 2, "path": "C:/Spotify.exe"}
        window = {"hwnd": 11, **process, "owner": 0,
                  "visible": not phases["closed"] and condition != "no_window",
                  "iconic": phases["minimizes"] > 0 and (clock[0] < 1 or phases["minimizes"] >= 2)}
        return {"processes": [process] if has_process else [], "windows": [window] if has_process else [], "foreground_hwnd": 0}
    def window_action(target, action, is_current):
        assert is_current() and target["pid"] == 41 and target["create_time"] == 2
        calls.append(("window", action, clock[0], target["iconic"]))
        if action == "minimize":
            phases["minimizes"] += 1
        else:
            phases["closed"] = True
        return {"attempted": True, "accepted": True}
    monkeypatch.setattr(media_sessions, "WindowsMediaSessions", Backend)
    monkeypatch.setattr(media_center, "MediaCenterRuntime", Runtime)
    monkeypatch.setattr(spotify_app, "launch_spotify", lambda **kwargs: calls.append(("uri", kwargs)) or True)
    monkeypatch.setattr(probe, "_spotify_probe_processes", lambda *_args: ())
    monkeypatch.setattr(probe, "_spotify_window_state", state)
    monkeypatch.setattr(probe, "_spotify_window_action", window_action)
    monkeypatch.setattr(probe.time, "monotonic", lambda: clock[0])
    def sleep(seconds):
        clock[0] += seconds
        runtime = phases.get("runtime")
        if condition == "later_playing" and clock[0] >= 7:
            runtime.snapshot = media_center.MediaCenterSnapshot(sessions=(session,), bgm_session_id="spotify", running=True)
        if phases["cold"] and runtime and runtime.pending_window:
            runtime.pending_window = not runtime.kwargs["spotify_window_minimizer"](1, is_current=lambda: runtime.running)
    monkeypatch.setattr(probe.time, "sleep", sleep)
    result = probe._spotify_window_startup(tmp_path, None, first_action=first_action, first_delay=first_delay)
    assert result["cleanup_ok"] and not result["writes"] and calls[-1] == ("stop",)
    if condition in ("process", "session", "external"):
        assert not result["ok"] and not result["request_queued"]
        assert calls == [("stop",)] and not result["trace"]
    elif condition == "no_window":
        assert not result["ok"] and clock[0] == 45
        assert not any(row[0] == "window" for row in calls)
        assert [row for row in calls if row[0] == "uri"] == [("uri", {"dj": True})]
    else:
        delay = 7 if first_delay and condition == "later_playing" else first_delay
        assert result["ok"] and clock[0] == 15 + delay
        expected = [("request", "play"), ("uri", {"dj": True})]
        if first_delay:
            expected.extend([("control", "spotify", "play"), ("window", "close", delay, False)])
        else:
            expected.extend([("window", first_action, 0, False), ("control", "spotify", "play")])
        if first_action == "minimize":
            expected.extend([("window", "minimize", 5, False), ("window", "close", 10, True)])
        assert calls[:-1] == expected
        timed = [row["at_ms"] for row in result["events"] if row["kind"] in ("initial_minimize", "initial_close", "delayed_close", "late_minimize", "close")]
        assert timed == ([delay * 1000] if first_delay else [0] if first_action == "close" else [0, 5000, 10000])
        assert not result["trace"][-1]["windows"][0]["visible"]
        assert result["final_media"]["sessions"][0]["status"] == "playing"
    json.dumps(result)


def source_database(tmp_path):
    roaming = tmp_path / "production-roaming"
    dbpath = roaming / "HomeworkHelper/homework_helper_data/app_data.db"
    dbpath.parent.mkdir(parents=True)
    with sqlite3.connect(dbpath) as db:
        db.execute("CREATE TABLE managed_processes (name TEXT,monitoring_path TEXT,default_volume INTEGER,default_muted INTEGER,credential TEXT)")
        db.execute("INSERT INTO managed_processes VALUES ('검수 게임','',55,0,'NEVER_EXPORT_SECRET')")
        db.execute("CREATE TABLE global_settings (screenshot_enabled INTEGER,obs_watch_output_dir INTEGER,recording_enabled INTEGER,remote_api_token TEXT)")
        db.execute("INSERT INTO global_settings VALUES (0,0,0,'NEVER_EXPORT_TOKEN')")
    return roaming, dbpath


def test_display_reader_only_exports_explicit_fields_and_preserves_database(tmp_path):
    roaming, dbpath = source_database(tmp_path)
    before = hashlib.sha256(dbpath.read_bytes()).hexdigest()
    result = probe._read_display(roaming)
    assert result["available"]
    assert result["games"] == [{"name": "검수 게임", "monitoring_path": "", "default_volume": 55,
                                 "default_muted": 0}]
    assert "NEVER_EXPORT" not in repr(result)
    assert before == hashlib.sha256(dbpath.read_bytes()).hexdigest()
    assert not dbpath.with_name(dbpath.name + "-journal").exists()


def test_missing_database_does_not_create_or_initialize_database(tmp_path):
    path = tmp_path / "missing"
    assert probe._read_display(path) == {"available": False, "games": [], "settings": {}}
    assert not path.exists()


def test_run_isolates_every_environment_before_native_or_gui_import(tmp_path, monkeypatch):
    for name in ("APPDATA", "LOCALAPPDATA", "HH_TEST_APPDATA_DIR"):
        monkeypatch.setenv(name, "original-operational-profile")
    seen = []
    def inspect():
        seen.extend(Path(os.environ[name]) for name in
                    ("APPDATA", "LOCALAPPDATA", "HH_TEST_APPDATA_DIR"))
        assert all(path.is_relative_to(tmp_path / "result/media-fixture") for path in seen)
        return {"ok": True}
    monkeypatch.setattr(probe, "_observe", inspect)
    assert probe.run(tmp_path, tmp_path / "operational", tmp_path / "result", "observe")["ok"]
    assert len(set(seen)) == 3


@pytest.mark.parametrize("scenario", ["audio", "focus", "bgm"])
def test_fixed_native_scenarios_dispatch_only_the_named_runner(tmp_path, monkeypatch, scenario):
    for name in ("APPDATA", "LOCALAPPDATA", "HH_TEST_APPDATA_DIR"):
        monkeypatch.setenv(name, "original")
    calls = []
    def runner(*args):
        calls.append(args)
        return {"ok": False, "scenario": scenario, "reason": "native 결과 확인 필요"}
    monkeypatch.setattr(probe, "_" + scenario, runner)
    result = probe.run(tmp_path, tmp_path, tmp_path / "result", scenario)
    assert result["ok"] is False and result["scenario"] == scenario and len(calls) == 1


def test_unknown_scenario_does_not_create_fixture(tmp_path):
    with pytest.raises(ValueError):
        probe.run(tmp_path, tmp_path, tmp_path / "result", "arbitrary-shell")
    assert not (tmp_path / "result").exists()


def test_observation_preserves_native_stage_errors_and_always_cleans_up(monkeypatch):
    from src.core import media_center, game_focus
    from src.utils import audio_control
    cleanup = []
    class Runtime:
        running = False
        snapshot = media_center.MediaCenterSnapshot(error="WinRT 준비 실패")
        def __init__(self, on_change):
            self.on_change = on_change
        def start(self, options):
            assert not any((options.auto_bgm, options.background_mute, options.auto_focus))
            self.on_change(self.snapshot)
            return True
        def stop(self, **_kwargs):
            cleanup.append(True)
            return True
    def failed():
        raise OSError("native test failure")
    monkeypatch.setattr(media_center, "MediaCenterRuntime", Runtime)
    monkeypatch.setattr(game_focus.WindowsGameFocusNative, "foreground", lambda _self: failed())
    monkeypatch.setattr(audio_control, "enumerate_sessions", failed)
    result = probe._observe()
    assert result["ok"] is False and result["cleanup_ok"] and cleanup == [True]
    assert result["samples"][0]["error"]
    assert {row["stage"] for row in result["native_errors"]} == {"foreground", "audio"}


def test_preview_renders_actual_widgets_without_operational_writer(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    for name in ("APPDATA", "LOCALAPPDATA", "HH_TEST_APPDATA_DIR"):
        monkeypatch.setenv(name, str(tmp_path / "original"))
    # SQLite·프로필 설정은 module import 전에 분리한다.
    probe._isolated_environment(tmp_path / "result")
    from PySide6.QtWidgets import QApplication
    from src.gui.main_window import MainWindow
    from src.gui.sidebar.sidebar_widget import SidebarWidget
    app = QApplication.instance() or QApplication([])
    del app
    original = MainWindow.INSTANCE
    monkeypatch.setattr(SidebarWidget, "_load_icon_async", lambda *_args: None)
    roaming, dbpath = source_database(tmp_path)
    before = dbpath.read_bytes()
    result = probe.run(Path(__file__).resolve().parents[1], roaming, tmp_path / "result", "preview")
    assert result["ok"] and result["game_count"] == 1
    assert len(result["images"]) == len(result["layouts"]) == 3
    assert all(image["base64"].startswith("iVBOR") for image in result["images"])
    assert [row["geometry"][3] for row in result["layouts"]][1:] == [760, 1080]
    assert result["commands"] == [] and result["fixture_saves"] == 0
    assert MainWindow.INSTANCE is original and dbpath.read_bytes() == before


@pytest.fixture
def owned_fixture(tmp_path, monkeypatch):
    root = tmp_path / "fixture"
    root.mkdir()
    child = SimpleNamespace(pid=111)
    calls = []
    monkeypatch.setattr(probe, "_spawn_fixture", lambda _dir, kind: (child, root, {"hwnd": 1111}))
    monkeypatch.setattr(probe, "_stop_fixture", lambda process, folder: calls.append((process.pid, folder)) or True)
    import psutil
    monkeypatch.setattr(psutil, "Process", lambda _pid: SimpleNamespace(
        create_time=lambda: time.time(), exe=lambda: "C:/fixture/pythonw.exe"))
    return root, calls


def test_audio_uses_owned_identity_and_restores_original_native_levels(tmp_path, monkeypatch, owned_fixture):
    from src.utils import audio_control
    monkeypatch.setitem(sys.modules, "pythoncom", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "comtypes", SimpleNamespace())
    class Session:
        pid = 111
        key = ("fixture-endpoint", "fixture-session")
        volume = .72
        muted = True
        def get_volume(self): return self.volume
        def get_mute(self): return self.muted
        def set_volume(self, value): self.volume = value
        def set_mute(self, value): self.muted = value
    session = Session()
    monkeypatch.setattr(audio_control, "enumerate_sessions", lambda: (session,))
    monkeypatch.setattr(audio_control, "verify_identity", lambda target: target.pid == 111)
    result = probe._audio(tmp_path)
    assert result["ok"] and len(result["steps"]) == 5
    assert all(row["ok"] for row in result["steps"])
    assert (session.volume, session.muted) == (.72, True)
    assert result["identity"]["user_muted"] is False and result["identity"]["user_volume"] == 55
    assert result["initial_audio_restored"] and result["fixture_exited"]
    assert owned_fixture[1] == [(111, owned_fixture[0])]


def test_audio_cleanup_exception_still_restores_and_stops_owned_fixture(tmp_path, monkeypatch, owned_fixture):
    from src.core.game_audio import GameAudioCoordinator
    from src.utils import audio_control
    monkeypatch.setitem(sys.modules, "pythoncom", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "comtypes", SimpleNamespace())
    session = SimpleNamespace(pid=111, key=("endpoint", "session"), get_volume=lambda: .55,
                              get_mute=lambda: False, set_volume=lambda _v: None, set_mute=lambda _v: None)
    monkeypatch.setattr(audio_control, "enumerate_sessions", lambda: (session,))
    monkeypatch.setattr(audio_control, "verify_identity", lambda _target: True)
    def failed(_self):
        raise RuntimeError("cleanup failed")
    monkeypatch.setattr(GameAudioCoordinator, "cleanup", failed)
    result = probe._audio(tmp_path)
    assert not result["ok"] and not result["cleanup_ok"]
    assert result["initial_audio_restored"] and result["fixture_exited"]
    assert result["errors"][0]["stage"] == "cleanup" and owned_fixture[1]


@pytest.mark.parametrize("accept", [True, False])
def test_focus_distinguishes_request_from_native_result_and_restores_foreground(tmp_path, monkeypatch, owned_fixture, accept):
    from src.core import game_focus
    foreground = [123, 1234]
    clock = [0.0]
    monkeypatch.setattr(probe.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(probe.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    class Native:
        def foreground(self): return tuple(foreground)
        def window(self, target): return 1111 if target.pid == 111 else None
        def is_window_hidden(self, hwnd): return False
        def is_related_foreground(self, target, pid): return False
        def focus(self, target, hwnd=None):
            if accept:
                foreground[:] = [target.pid, 1111]
            return accept
    monkeypatch.setattr(game_focus, "WindowsGameFocusNative", Native)
    restored = []
    def restore(hwnd):
        restored.append(hwnd)
        foreground[:] = [123, hwnd]
        return True
    monkeypatch.setattr(probe, "_restore_foreground", restore)
    monkeypatch.setattr(probe, "_wait", lambda predicate, _seconds: predicate())
    result = probe._focus(tmp_path)
    assert result["ok"] is accept and result["foreground_observed"] is accept
    assert result["requests"] == [{"pid": 111, "accepted": accept}]
    assert result["foreground_restored"] and result["fixture_exited"]
    assert restored == [1234] and owned_fixture[1]


@pytest.mark.parametrize("status, actions", [("playing", ["pause", "play"]), ("paused", ["play", "pause"]),
                                            ("stopped", []), ("missing", []), ("multiple", [])])
def test_bgm_only_controls_unambiguous_existing_session_and_restores_state(monkeypatch, status, actions):
    from src.core import media_center
    from src.core.media_sessions import MediaSessionInfo
    calls, cleanup = [], []
    initial = MediaSessionInfo("spotify", "Spotify.exe", status=status,
                               can_play=status == "paused", can_pause=status == "playing")
    sessions = (() if status == "missing" else (initial, initial) if status == "multiple" else (initial,))
    class Runtime:
        running = True
        def __init__(self, on_change, spotify_launcher):
            self.on_change, self.launcher = on_change, spotify_launcher
            self.snapshot = media_center.MediaCenterSnapshot(sessions=sessions, bgm_session_id="spotify", running=True)
        def start(self, options):
            assert not any((options.auto_bgm, options.background_mute, options.auto_focus))
            assert self.launcher() is False
            self.on_change(self.snapshot)
            return True
        def request(self, action, session_id):
            calls.append(action)
            assert session_id == "spotify"
            self.snapshot = media_center.MediaCenterSnapshot(
                sessions=(probe.replace(initial, status="playing" if action == "play" else "paused"),), running=True)
            return True
        def stop(self, **_kwargs):
            cleanup.append(True)
            return True
    monkeypatch.setattr(media_center, "MediaCenterRuntime", Runtime)
    monkeypatch.setattr(probe, "_wait", lambda predicate, _seconds: predicate())
    result = probe._bgm()
    json.dumps(result)
    assert result["ok"] is bool(actions) and result["supported"] is bool(actions)
    assert calls == actions and cleanup == [True]
    assert result["cleanup_ok"]
    if actions:
        assert result["playback_state_restored"]


@pytest.mark.parametrize("mode, uri_accepted, session_present", [
    ("cold", True, True), ("cold", True, False), ("cold", False, False),
    ("cold", False, True), ("warm-ready", None, True), ("warm-delayed", None, True),
    ("warm-timeout", None, False),
])
def test_explicit_spotify_prepare_observes_ready_session_without_reopening_warm_app(
        monkeypatch, mode, uri_accepted, session_present):
    from src.core import media_center, media_sessions, spotify_app
    calls, cleanup, launches, waits, instances = [], [], [], [], []
    session = media_sessions.MediaSessionInfo("spotify", "Spotify.exe", status="paused")
    def launch():
        launches.append(True)
        return uri_accepted
    class Runtime:
        PREPARE_TIMEOUT_SECONDS = 60
        def __init__(self, spotify_launcher):
            self.launcher = spotify_launcher
            self.snapshot = media_center.MediaCenterSnapshot(
                sessions=(session,) if mode == "warm-ready" else (), running=True)
            instances.append(self)
        def start(self, options):
            assert not any((options.auto_bgm, options.background_mute, options.auto_focus))
            return True
        def request(self, action):
            calls.append(action)
            if mode == "cold":
                self.launcher()
                self.snapshot = media_center.MediaCenterSnapshot(
                    sessions=(session,) if session_present else (), running=True)
            return True
        def stop(self, **_kwargs):
            cleanup.append(True)
            return True
    def wait(predicate, seconds):
        waits.append(seconds)
        if mode == "warm-delayed":
            assert not predicate()
            instances[0].snapshot = media_center.MediaCenterSnapshot(sessions=(session,), running=True)
        return predicate()
    monkeypatch.setattr(media_center, "MediaCenterRuntime", Runtime)
    monkeypatch.setattr(spotify_app, "launch_spotify", launch)
    monkeypatch.setattr(probe, "_wait", wait)
    result = probe._prepare_spotify()
    json.dumps(result)
    assert result["ok"] is (session_present and (mode != "cold" or uri_accepted))
    assert result["uri_requested"] is (mode == "cold")
    assert result["uri_accepted"] is uri_accepted and result["session_observed"] is session_present
    assert result["request_queued"] and result["play_requested"] is False
    assert calls == ["prepare"] and cleanup == [True] and waits == [60]
    assert launches == ([True] if mode == "cold" else [])
    assert len(result["launches"]) == (1 if mode == "cold" else 0)
    if not session_present:
        assert result["reason"]


def test_spotify_prepare_does_not_hide_request_failure_when_a_session_is_present(monkeypatch):
    from src.core import media_center
    from src.core.media_sessions import MediaSessionInfo
    snapshot = media_center.MediaCenterSnapshot(
        sessions=(MediaSessionInfo("spotify", "Spotify.exe"),),
        error="Spotify 준비 요청 실패", running=True,
    )
    runtime = SimpleNamespace(
        snapshot=snapshot, PREPARE_TIMEOUT_SECONDS=60,
        start=lambda _options: True, request=lambda _action: True,
        stop=lambda **_kwargs: True,
    )
    monkeypatch.setattr(media_center, "MediaCenterRuntime", lambda **_kwargs: runtime)
    monkeypatch.setattr(probe, "_wait", lambda predicate, _seconds: predicate())
    result = probe._prepare_spotify()
    assert not result["ok"] and result["session_observed"]
    assert result["error"] == result["reason"] == "Spotify 준비 요청 실패"
    assert result["uri_requested"] is False and result["uri_accepted"] is None
    assert result["launches"] == [] and not result["play_requested"]


@pytest.fixture
def redirected_fixture(tmp_path, monkeypatch):
    import psutil
    records = []
    root = tmp_path / "fixture-root"
    root.mkdir()
    class Process:
        pid = 222
        parent = 111
        created = 100.0
        executable = sys.executable
        command = [sys.executable, str(Path(probe.__file__).resolve()), "--fixture", "audio", "--root", str(root)]
        def exe(self): return self.executable
        def create_time(self): return self.created
        def cmdline(self): return self.command
        def ppid(self): return self.parent
        def parents(self): return []
        def wait(self, timeout):
            records.append(("actual", self.pid))
        @property
        def info(self): return {"pid": self.pid, "cmdline": self.command}
    process = Process()
    def lookup(pid):
        if pid != 222:
            raise psutil.NoSuchProcess(pid)
        return process
    monkeypatch.setattr(psutil, "Process", lookup)
    monkeypatch.setattr(psutil, "process_iter", lambda _attrs: [process])
    monkeypatch.setattr(probe, "_process_context", lambda _pid: ("owner-sid", 1))
    launcher = SimpleNamespace(pid=111, wait=lambda **_kwargs: records.append(("launcher", 111)),
                               poll=lambda: 0, returncode=0)
    return root, process, launcher, records


def test_owned_redirected_fixture_uses_os_identity_not_launcher_pid(redirected_fixture):
    root, process, launcher, records = redirected_fixture
    assert probe._owned_fixture(222, launcher.pid, root, "audio", 100) is process
    owned = probe._FixtureProcess(launcher, process)
    assert owned.pid == 222
    assert probe._stop_fixture(owned, root)
    assert records == [("actual", 222), ("launcher", 111)] and (root / "stop").exists()


@pytest.mark.parametrize("change", ["exe", "root", "ancestry", "sid", "session", "created"])
def test_owned_fixture_rejects_unrelated_or_reused_ready_pid(redirected_fixture, monkeypatch, change):
    root, process, launcher, _records = redirected_fixture
    if change == "exe": process.executable = "C:/unrelated/program.exe"
    if change == "root": process.command = [*process.command[:-1], str(root / "other")]
    if change == "ancestry": process.parent = 999
    if change == "created": process.created = 50
    if change in {"sid", "session"}:
        monkeypatch.setattr(probe, "_process_context", lambda pid: (
            ("other-sid", 1) if change == "sid" else ("owner-sid", 2)) if pid == 222 else ("owner-sid", 1))
    with pytest.raises(ValueError):
        probe._owned_fixture(222, launcher.pid, root, "audio", 100)


def test_spawn_waits_for_real_ready_after_launcher_has_already_exited(tmp_path, redirected_fixture, monkeypatch):
    _root, process, launcher, records = redirected_fixture
    import json
    def launch(command, **_kwargs):
        root = Path(command[-1])
        process.command = list(command)
        (root / "ready.json").write_text(json.dumps({"pid": 222}), encoding="utf-8")
        return launcher
    monkeypatch.setattr(probe.subprocess, "Popen", launch)
    monkeypatch.setattr(probe.time, "time", lambda: 100)
    child, root, ready = probe._spawn_fixture(tmp_path, "audio")
    assert child.pid == ready["pid"] == 222 and launcher.poll() == 0
    assert probe._stop_fixture(child, root)
    assert records == [("actual", 222), ("launcher", 111)]


def test_invalid_ready_pid_cleans_actual_owned_child_before_raising(tmp_path, redirected_fixture, monkeypatch):
    _root, process, launcher, records = redirected_fixture
    import json
    roots = []
    def launch(command, **_kwargs):
        root = Path(command[-1])
        roots.append(root)
        process.command = list(command)
        (root / "ready.json").write_text(json.dumps({"pid": 999}), encoding="utf-8")
        return launcher
    monkeypatch.setattr(probe.subprocess, "Popen", launch)
    monkeypatch.setattr(probe.time, "time", lambda: 100)
    import psutil
    with pytest.raises(psutil.NoSuchProcess):
        probe._spawn_fixture(tmp_path, "audio")
    assert (roots[0] / "stop").exists()
    assert records == [("actual", 222), ("launcher", 111)]


def test_focus_diagnostics_capture_exact_boundary_and_redact_secret_text():
    import logging
    logger = logging.getLogger("src.utils.windows")
    old_level, old_handlers = logger.level, list(logger.handlers)
    with probe._focus_diagnostics() as rows:
        logger.warning("Windows가 게임 창 전환을 허용하지 않음: pid=42 token=sensitive-value")
        logging.getLogger("unrelated.logger").warning("이 행은 focus 결과에 포함하지 않는다")
    assert len(rows) == 1 and rows[0]["logger"] == "src.utils.windows"
    assert "sensitive-value" not in rows[0]["message"] and "REDACTED" in rows[0]["message"]
    assert logger.level == old_level and logger.handlers == old_handlers


@pytest.mark.parametrize("other_playing, initial_status", [(False, "paused"), (False, "playing"), (True, "paused")])
def test_triggers_integrate_state_edges_and_restore_without_operational_data(tmp_path, monkeypatch, owned_fixture, other_playing, initial_status):
    from src.core import media_center
    from src.core.game_audio import GameAudioObservation
    from src.core.media_sessions import MediaSessionInfo
    from src.utils import audio_control
    commands, cleaned, active = [], [], []
    initial = MediaSessionInfo("spotify", "Spotify.exe", status=initial_status,
                               can_play=initial_status == "paused", can_pause=initial_status == "playing")
    other = MediaSessionInfo("firefox", "firefox.exe", status="playing")
    class Session:
        pid = 111
        key = ("endpoint", "session")
        volume = .72
        muted = False
        def get_volume(self): return self.volume
        def get_mute(self): return self.muted
        def set_volume(self, value): self.volume = value
        def set_mute(self, value): self.muted = value
    session = Session()
    class Runtime:
        def __init__(self, native_factory, spotify_launcher):
            self.native = native_factory()
            assert self.native.foreground()[0] != os.getpid() and spotify_launcher() is False
            self.snapshot = media_center.MediaCenterSnapshot(sessions=(initial, other) if other_playing else (initial,), running=True)
        def start(self, options):
            assert not any((options.auto_bgm, options.background_mute, options.auto_focus))
            active.append(True)
            return True
        def configure(self, options):
            if options.auto_bgm:
                self.snapshot = probe.replace(self.snapshot, sessions=(probe.replace(initial, status="playing"),))
            return True
        def update_targets(self, targets):
            target = targets[0]
            session.volume, session.muted = .55, target.user_muted
            observation = GameAudioObservation(target, True, .55, target.user_muted, False, not target.user_muted)
            self.snapshot = probe.replace(self.snapshot,
                sessions=(probe.replace(initial, status="playing" if target.user_muted else "paused"),),
                game_audio=(observation,))
        def request(self, action, session_id):
            commands.append((action, session_id))
            self.snapshot = probe.replace(self.snapshot, sessions=(probe.replace(initial, status="playing" if action == "play" else "paused"),))
            return True
        def stop(self, **_kwargs):
            cleaned.append(True)
            return True
    monkeypatch.setattr(media_center, "MediaCenterRuntime", Runtime)
    monkeypatch.setattr(audio_control, "enumerate_sessions", lambda: (session,))
    monkeypatch.setattr(audio_control, "verify_identity", lambda target: target.pid == 111)
    monkeypatch.setattr(probe, "_wait", lambda predicate, _seconds: predicate())
    result = probe._triggers(tmp_path)
    json.dumps(result)
    assert result["foreground_input"] == "synthetic" and cleaned == active == [True]
    if other_playing:
        assert result["ok"] is False and result["supported"] is False
        assert commands == [] and owned_fixture[1] == []
    else:
        assert result["ok"] and len(result["steps"]) == 5
        expected = (["pause"] if initial_status == "playing" else []) + ["pause", "play" if initial_status == "playing" else "pause"]
        assert commands == [(action, "spotify") for action in expected]
        assert result["playback_state_restored"] and result["audio_restored"] and result["fixture_exited"]
        assert (session.volume, session.muted) == (.72, False)


def test_firefox_fixture_is_local_only_and_does_not_configure_operational_profile(tmp_path):
    import wave
    profile, html = probe._firefox_fixture_files(tmp_path / "firefox-fixture", "QA-title")
    preferences = (profile / "user.js").read_text(encoding="utf-8")
    document = html.read_text(encoding="utf-8")
    assert '"media.autoplay.default", 0' in preferences
    assert '"dom.allow_scripts_to_close_windows", true' in preferences
    assert "remote-debugging" not in preferences and "marionette" not in preferences
    assert "http:" not in document and "https:" not in document
    assert "fixture.wav" in document and 'title: "QA-title"' in document
    assert "audio.pause(), 8000" in document and "window.close(), 16000" in document
    with wave.open(str(html.parent / "fixture.wav")) as stream:
        assert stream.getnframes() / stream.getframerate() == 20


@pytest.mark.parametrize("other_playing, mode", [(False, "normal"), (True, "normal"),
    (False, "rotating"), (False, "transient"), (False, "ambiguous"), (False, "changed-title"),
    (False, "failed-step"), (False, "deadline-close")])
def test_firefox_policy_uses_actual_session_phases_and_restores_bgm(tmp_path, monkeypatch, other_playing, mode):
    from src.core import media_center, game_focus
    from src.core.media_sessions import MediaSessionInfo
    initial = MediaSessionInfo("spotify", "Spotify.exe", status="paused", can_play=True)
    other = MediaSessionInfo("other", "other-player.exe", status="playing")
    runtime_holder, launches, closes, commands, cleanup = [], [], [], [], []
    close_pending = []
    class Runtime:
        def __init__(self, spotify_launcher, on_change):
            assert spotify_launcher() is False
            self.on_change = on_change
            self.snapshot = media_center.MediaCenterSnapshot(sessions=(initial, other) if other_playing else (initial,), running=True)
            runtime_holder.append(self)
        def start(self, options):
            assert not any((options.auto_bgm, options.background_mute, options.auto_focus))
            self.on_change(self.snapshot)
            return True
        def configure(self, options):
            if options.auto_bgm:
                self.snapshot = probe.replace(self.snapshot, sessions=(probe.replace(initial, status="playing"),))
                self.on_change(self.snapshot)
            return True
        def request(self, action, session_id):
            commands.append((action, session_id))
            selected = next(item for item in self.snapshot.sessions if item.session_id == session_id)
            self.snapshot = probe.replace(self.snapshot, sessions=(probe.replace(selected, status="paused"),))
            self.on_change(self.snapshot)
            return True
        def stop(self, **_kwargs):
            cleanup.append(True)
            return True
    def launch(executable, root, marker):
        launches.append((executable, root, marker))
        selected = probe.replace(initial, session_id="spotify-new" if mode in {"rotating", "transient", "changed-title"} else initial.session_id,
                                 title="different-track" if mode == "changed-title" else initial.title)
        spotify = (selected, probe.replace(selected, session_id="spotify-second")) if mode == "ambiguous" else (selected,)
        runtime_holder[0].snapshot = media_center.MediaCenterSnapshot(
            sessions=(*spotify, MediaSessionInfo("firefox-fixture", "firefox.exe", title=marker,
                                               status="unknown" if mode == "failed-step" else "playing")),
            media_hold=True, running=True)
        runtime_holder[0].on_change(runtime_holder[0].snapshot)
        if mode == "transient":
            runtime_holder[0].snapshot = probe.replace(runtime_holder[0].snapshot, sessions=tuple(
                probe.replace(item, status="paused") if item.app_id == "firefox.exe" else item
                for item in runtime_holder[0].snapshot.sessions))
            runtime_holder[0].on_change(runtime_holder[0].snapshot)
        return SimpleNamespace(pid=111)
    def close(browser, _diagnostics):
        closes.append(browser.pid)
        if mode == "deadline-close" and len(closes) == 1:
            close_pending.append(True)
            return True
        runtime_holder[0].snapshot = probe.replace(runtime_holder[0].snapshot, sessions=tuple(
            item for item in runtime_holder[0].snapshot.sessions if item.app_id == "Spotify.exe"))
        runtime_holder[0].on_change(runtime_holder[0].snapshot)
        return True
    def wait(predicate, _seconds):
        matched = predicate()
        if not matched and close_pending:
            close_pending.clear()
            runtime_holder[0].snapshot = probe.replace(runtime_holder[0].snapshot, sessions=(initial,))
            runtime_holder[0].on_change(runtime_holder[0].snapshot)
            return None  # 마지막 sleep 동안 도착했지만 loop의 deadline이 먼저 만료된 경우.
        if not matched:
            runtime = runtime_holder[0]
            runtime.snapshot = probe.replace(runtime.snapshot, sessions=tuple(
                probe.replace(session, status="paused") if session.app_id == "firefox.exe" else session
                for session in runtime.snapshot.sessions))
            runtime.on_change(runtime.snapshot)
        return predicate()
    monkeypatch.setattr(media_center, "MediaCenterRuntime", Runtime)
    monkeypatch.setattr(game_focus.WindowsGameFocusNative, "foreground", lambda _self: (123, 1234))
    monkeypatch.setattr(probe, "_firefox_path", lambda: tmp_path / "installed/firefox.exe")
    monkeypatch.setattr(probe, "_launch_firefox", launch)
    monkeypatch.setattr(probe, "_close_firefox", close)
    monkeypatch.setattr(probe, "_wait", wait)
    result = probe._firefox(tmp_path)
    json.dumps(result)
    assert cleanup == [True]
    expected_pass = not other_playing and mode not in {"ambiguous", "changed-title", "failed-step"}
    assert result["ok"] is expected_pass
    if other_playing:
        assert launches == closes == commands == [] and result["supported"] is False
    else:
        assert len(launches) == 1
        assert closes == ([111, 111] if expected_pass else [111])
        assert commands == ([] if mode in {"ambiguous", "changed-title"} else [(
            "pause", "spotify-new" if mode in {"rotating", "transient"} else "spotify")])
        assert bool(result["playback_state_restored"]) is (mode not in {"ambiguous", "changed-title"})
        assert result["fixture_closed"] and result["foreground_before"] == result["foreground_after"]
        if expected_pass:
            assert len(result["steps"]) == 5
        if mode in {"rotating", "transient"}:
            assert result["spotify_id_replacements"][0]["current_id"] == "spotify-new"
            assert result["spotify_id_replacements"][0]["original_id"] == "spotify"
        if mode == "transient":
            matched = result["steps"][1]["snapshot"]
            assert any(item["title"].startswith("HH-media-QA-") and item["status"] == "playing" for item in matched["sessions"])
            assert any(item["app_id"] == "Spotify.exe" and item["status"] == "paused" for item in matched["sessions"])
            assert len(result["trace"]) >= 3


@pytest.mark.parametrize("window_visible, same_session", [(False, True), (True, True), (True, False)])
def test_firefox_selects_verified_visible_window_owner_not_early_launcher(tmp_path, monkeypatch, window_visible, same_session):
    executable = tmp_path / "firefox.exe"
    class Process:
        def __init__(self, pid, parent): self.pid, self.parent = pid, parent
        def exe(self): return str(executable)
        def create_time(self): return 100
        def ppid(self): return self.parent
        def parents(self): return []
        def children(self, recursive): return [child]
    owner, child = Process(111, 42), Process(222, 111)
    monkeypatch.setattr(probe, "_process_context", lambda pid: (
        ("owner", 2) if pid == 222 and not same_session else ("owner", 1)))
    seen = []
    def windows(pids):
        seen.append(pids)
        return ([{"hwnd": 2222, "pid": 222, "rect": [0, 0, 800, 600], "title": "Firefox QA"}]
                if window_visible and 222 in pids else [])
    monkeypatch.setattr(probe, "_visible_firefox_windows", windows)
    result = probe._firefox_window_owner(owner, executable, 100)
    if window_visible and same_session:
        actual, diagnostics = result
        assert actual is child
        assert diagnostics["profile_owner_pid"] == 111 and diagnostics["window_pid"] == 222
        assert diagnostics["hwnd"] == 2222 and len(diagnostics["lineage"]) == 2
    else:
        assert result is None
    assert 111 in seen[0] and (222 in seen[0]) is same_session


@pytest.mark.parametrize("count", [0, 1, 2])
def test_focus_compare_selects_exactly_one_registered_same_session_identity(tmp_path, monkeypatch, count):
    import psutil
    from src.utils import audio_control
    path = tmp_path / "HomeworkHelper/homework_helper_data/app_data.db"
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE managed_processes(id TEXT,name TEXT,monitoring_path TEXT,secret TEXT)")
        db.execute("INSERT INTO managed_processes VALUES ('game','검수 게임','C:/game.exe','do-not-read')")
    before = path.read_bytes()
    processes = [SimpleNamespace(pid=100 + index, info={"exe": "C:/game.exe", "create_time": 1000}) for index in range(count)]
    monkeypatch.setattr(psutil, "process_iter", lambda _attrs: processes)
    monkeypatch.setattr(audio_control, "verify_identity", lambda target: target.pid >= 100)
    if count == 1:
        target, name = probe._focus_compare_target(tmp_path)
        assert target.pid == 100 and target.process_id == "game" and name == "검수 게임"
    else:
        with pytest.raises(ValueError):
            probe._focus_compare_target(tmp_path)
    assert path.read_bytes() == before


@pytest.mark.parametrize("already_running", [False, True])
def test_focus_compare_waits_for_new_game_and_does_not_refocus_existing_game(tmp_path, monkeypatch, already_running):
    from src.core import game_focus
    from src.core.game_audio import GameAudioTarget
    import json
    foreground, calls, queries = [10, 100], [], []
    clock = [0.0]
    target = GameAudioTarget("game", 111, time.time() - 10 if already_running else time.time() + 1, "game.exe", False, None)
    class Native:
        def foreground(self): return tuple(foreground)
        def window(self, selected): return 1111 if selected is target else None
        def is_window_hidden(self, hwnd): return False
        def is_related_foreground(self, target, pid): return False
        def focus(self, selected, hwnd=None):
            calls.append(selected.pid)
            foreground[:] = [111, 1111]
            return True
    def select(_source, _registered, allow_empty):
        queries.append(True)
        return (target, "검수 게임") if already_running or len(queries) > 1 else None
    monkeypatch.setattr(probe, "_focus_compare_registered", lambda _source: [("game", "검수 게임", "game.exe")])
    monkeypatch.setattr(probe, "_focus_compare_target", select)
    monkeypatch.setattr(probe, "_focus_compare_context", lambda selected: {"foreground": list(foreground), "last_input_tick": 1})
    monkeypatch.setattr(game_focus, "WindowsGameFocusNative", Native)
    monkeypatch.setattr(probe.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(probe.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    selected, name, _started, original, events = probe._focus_compare_startup(tmp_path, tmp_path)
    assert selected is target and name == "검수 게임" and original["foreground"] == [10, 100]
    assert calls == ([] if already_running else [111])
    assert game_focus.AutoFocusTracker.WINDOW_STABLE_SECONDS <= clock[0] < 60
    assert events[0]["kind"] == "waiting-for-registered-game"
    assert json.loads((tmp_path / "focus-progress.json").read_text())["events"] == events


def test_focus_compare_panel_records_gui_worker_and_native_style_key_events(tmp_path, monkeypatch):
    import json
    import threading
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QPushButton
    from src.core.game_audio import GameAudioTarget
    from src.utils import audio_control, windows
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    target = GameAudioTarget("game", 111, 100, "game.exe", False, None)
    foreground, restored, calls = [10, 100], [], []
    context = lambda _target: {"foreground": list(foreground), "last_input_tick": 1,
                                "native_thread_id": threading.get_native_id()}
    monkeypatch.setattr(probe, "_focus_compare_startup", lambda *_args: (target, "검수 게임", time.monotonic(), context(None), []))
    monkeypatch.setattr(probe, "_focus_compare_context", context)
    monkeypatch.setattr(audio_control, "verify_identity", lambda selected: selected is target)
    def focus(*_args):
        calls.append(threading.get_native_id())
        accepted = threading.current_thread() is threading.main_thread()
        if accepted:
            foreground[:] = [111, 1111]
        return accepted
    monkeypatch.setattr(windows, "focus_managed_process_window", focus)
    monkeypatch.setattr(probe, "_restore_foreground", lambda hwnd: restored.append(hwnd) or True)
    original_timer = QTimer.singleShot
    def timer(milliseconds, callback):
        milliseconds = 5 if milliseconds == 250 else 10 if milliseconds == 2000 else 2000 if milliseconds > 5000 else milliseconds
        return original_timer(milliseconds, callback)
    monkeypatch.setattr(QTimer, "singleShot", staticmethod(timer))
    pending = [("manual-gui", False), ("manual-worker", True), ("manual-delayed-worker", True)]
    pressed = []
    def press_when_ready():
        panel = next(view for view in app.topLevelWidgets() if view.windowTitle() == "HomeworkHelper · 게임 포커스 비교")
        if not pending:
            return
        name, keyboard = pending[0]
        button = panel.findChild(QPushButton, name)
        if button.isEnabled() and len(calls) >= 2 + len(pressed):
            pending.pop(0)
            pressed.append(name)
            if keyboard:
                button.setFocus()
                QTest.keyClick(button, Qt.Key.Key_Space)
            else:
                QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        original_timer(20, press_when_ready)
    original_timer(20, press_when_ready)
    result = probe._focus_compare(tmp_path, tmp_path)
    attempts = [row for row in result["events"] if row["kind"] == "attempt"]
    assert len(attempts) == 5 and len({row["before"]["native_thread_id"] for row in attempts}) >= 2
    assert attempts[0]["label"] == "background-gui" and attempts[1]["label"] == "background-worker"
    assert any(row["kind"] == "button_input_event" and row["event"] == "KeyPress" for row in result["events"])
    assert result["worker_stopped"] and result["foreground_restored"] and restored == [100]
    assert json.loads((tmp_path / "focus-progress.json").read_text())["finished"] is True


@pytest.mark.parametrize("mode", ["success", "ambiguous", "stale", "provider-error"])
def test_uia_focus_is_single_mta_request_with_identity_and_window_boundaries(monkeypatch, mode):
    import threading
    from src.core.game_audio import GameAudioTarget
    from src.utils import audio_control
    calls = []
    target = GameAudioTarget("game", 111, 100, "game.exe", False, None)
    window = {"hwnd": 1234, "visible": True, "rect": [0, 0, 100, 100]}
    context = {"foreground": [111, 1234], "target_windows": [window] * (2 if mode == "ambiguous" else 1)}
    monkeypatch.setattr(probe, "_focus_compare_context", lambda selected: dict(context))
    monkeypatch.setattr(audio_control, "verify_identity", lambda selected: mode != "stale")
    monkeypatch.setattr(probe.time, "sleep", lambda seconds: None)
    class ProviderError(Exception):
        hresult = -2147024891
    def focus():
        calls.append(("focus", threading.get_native_id()))
        if mode == "provider-error":
            raise ProviderError("token=SHOULD_REDACT")
    automation = SimpleNamespace(ElementFromHandle=lambda hwnd: calls.append(("element", hwnd)) or SimpleNamespace(SetFocus=focus))
    def create(clsid, interface):
        calls.append(("create", clsid, interface))
        return automation
    fake = SimpleNamespace(COINIT_MULTITHREADED=0,
        CoInitializeEx=lambda kind: calls.append(("init", kind, threading.get_native_id())),
        CoUninitialize=lambda: calls.append(("uninit",)),
        client=SimpleNamespace(GetModule=lambda dll: SimpleNamespace(IUIAutomation2="IUIAutomation2"), CreateObject=create))
    monkeypatch.setitem(sys.modules, "comtypes", fake)
    row = probe._uia_focus_attempt(target)
    assert calls[0][0:2] == ("init", 0) and calls[0][2] != threading.get_native_id()
    assert calls[-1] == ("uninit",) and row["worker_stopped"]
    assert len([call for call in calls if call[0] == "focus"]) == (mode in {"success", "provider-error"})
    assert row["accepted"] == (mode == "success")
    if mode in {"success", "provider-error"}:
        assert row["timeouts_ms"] == {"connection": 500, "transaction": 1500}
        assert row["after_250ms"]["foreground_observed"] and row["after_1s"]["foreground_observed"]
    if mode == "provider-error":
        assert row["hresult"] == "0x80070005" and "SHOULD_REDACT" not in row["error"]


def test_uia_orchestration_compares_only_owned_fixture_and_restores_original(tmp_path, monkeypatch):
    from src.core.game_audio import GameAudioTarget
    target = GameAudioTarget("game", 111, 100, "game.exe", False, None)
    calls = []
    monkeypatch.setattr(probe, "_focus_compare_target", lambda source: (target, "검수 게임"))
    monkeypatch.setattr(probe, "_focus_compare_context", lambda selected: {"foreground": [77, 777]})
    monkeypatch.setattr(probe, "_uia_focus_attempt", lambda selected: calls.append(("attempt", selected.pid)) or {"worker_stopped": True, "accepted": False})
    monkeypatch.setattr(probe, "_spawn_fixture", lambda root, kind: (SimpleNamespace(pid=222), tmp_path, {}))
    monkeypatch.setattr(probe, "_stop_fixture", lambda child, root: calls.append(("stop-fixture", child.pid)) or True)
    monkeypatch.setattr(probe, "_restore_foreground", lambda hwnd: calls.append(("restore", hwnd)) or True)
    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(Process=lambda pid: SimpleNamespace(create_time=lambda: 200, exe=lambda: "pythonw.exe")))
    result = probe._focus_uia(tmp_path, tmp_path)
    assert result["ok"] and result["foreground_restored"]
    assert calls == [("attempt", 111), ("attempt", 222), ("stop-fixture", 222), ("restore", 777)]


@pytest.mark.parametrize("game_appears", [True, False])
def test_focus_lifecycle_keeps_observing_window_replacement_to_deadline(tmp_path, monkeypatch, game_appears):
    import json
    from src.core import game_focus
    from src.core.game_audio import GameAudioTarget
    clock, polls, ticks, calls, owners = [0.0], [], [], [], []
    target = GameAudioTarget("game", 111, 100, "game.exe", False, None)
    monkeypatch.setattr(probe.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(probe.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(probe, "_focus_compare_registered", lambda source: [("game", "검수 게임", "game.exe")])
    ownership = {"qa_pid": 77, "ui_owner_pid": 888, "reason": "verified-installed-initial-gui"}
    monkeypatch.setattr(probe, "_focus_lifecycle_owner", lambda original: ownership)
    def selected(*_args, **_kwargs):
        polls.append(clock[0])
        return (target, "검수 게임") if game_appears and clock[0] >= .5 else None
    monkeypatch.setattr(probe, "_focus_compare_target", selected)
    class Native:
        def foreground(self): return (333, 3333) if 2 <= clock[0] < 4 else (999, 9999)
        def window(self, selected): return 1111 if clock[0] < 5 else 2222
        def is_window_hidden(self, hwnd): return False
        def is_related_foreground(self, selected, pid): return pid == 333
        def focus(self, selected, hwnd=None):
            calls.append((selected.pid, hwnd))
            return False
    class Tracker:
        def __init__(self, *, started_at_wall, native): self.native, self.requested = native, False
        def tick(self, targets, *_args):
            ticks.append(clock[0])
            owners.append(_args[-1])
            if targets and not self.requested:
                self.requested = True
                self.native.focus(targets[0], self.native.window(targets[0]))
        def cancel(self): pass
    monkeypatch.setattr(game_focus, "WindowsGameFocusNative", Native)
    monkeypatch.setattr(game_focus, "AutoFocusTracker", Tracker)
    monkeypatch.setattr(probe, "_process_context", lambda pid: ("S-1-test", 1))
    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(Process=lambda pid:
        SimpleNamespace(exe=lambda: "related.exe", create_time=lambda: 1)))
    def context(selected):
        return {"foreground": list(Native().foreground()), "last_input_tick": 10 if clock[0] < 7 else 11,
                "target_windows": [{"hwnd": Native().window(selected), "phase": "initial" if clock[0] < 5 else "replacement"}]
                if selected else []}
    monkeypatch.setattr(probe, "_focus_compare_context", context)
    result = probe._focus_lifecycle(tmp_path, tmp_path)
    assert result["ok"] is game_appears and not result["errors"]
    assert owners and set(owners) == {888} and result["ownership"] == ownership
    assert calls == ([(111, 1111)] if game_appears else [])
    deadline = next(row for row in result["events"] if row["kind"] == "deadline-observation")
    if game_appears:
        assert deadline["seconds_after_identity"] >= 125 and ticks[-1] >= 125.5
        states = [row for row in result["events"] if row["kind"] == "state"]
        assert any(row["related_foreground"] for row in states)
        assert any(row["context"]["target_windows"] and row["context"]["target_windows"][0]["phase"] == "replacement" for row in states)
        assert any(row["context"]["last_input_tick"] == 11 for row in states)
    else:
        assert clock[0] == 20 and deadline["seconds_after_identity"] is None
    assert len(polls) == len(set(polls))
    assert json.loads((tmp_path / "focus-lifecycle-progress.json").read_text())["finished"]


@pytest.mark.parametrize("mode", ["matching", "other-path", "other-session", "other-sid", "unreadable", "no-foreground"])
def test_focus_lifecycle_ui_owner_requires_exact_initial_install_and_same_user_session(monkeypatch, mode):
    reads = []
    expected = r"C:\Program Files\HomeworkHelper\homework_helper.exe"
    monkeypatch.setenv("ProgramFiles", r"C:\Program Files")
    monkeypatch.setattr(probe.os, "getpid", lambda: 77)
    def process(pid):
        reads.append(pid)
        if mode == "unreadable":
            raise PermissionError("not available")
        return SimpleNamespace(exe=lambda: r"D:\clone\HomeworkHelper\homework_helper.exe" if mode == "other-path" else expected,
                               create_time=lambda: 123.4)
    def context(pid):
        if pid == 888 and mode == "other-session":
            return "S-1-test", 2
        if pid == 888 and mode == "other-sid":
            return "S-2-other", 1
        return "S-1-test", 1
    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(Process=process))
    monkeypatch.setattr(probe, "_process_context", context)
    result = probe._focus_lifecycle_owner({"foreground": [0 if mode == "no-foreground" else 888, 9999]})
    assert result["qa_pid"] == 77
    assert result["ui_owner_pid"] == (888 if mode == "matching" else 77)
    assert reads == ([] if mode == "no-foreground" else [888])
    if mode == "matching":
        assert result["path"] == expected and result["sid"] == "S-1-test" and result["session_id"] == 1
