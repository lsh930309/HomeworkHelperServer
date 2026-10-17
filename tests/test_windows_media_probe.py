"""공용 media probe의 운영 데이터 비변경·환경 격리·시각 검수 경계를 확인한다."""
import hashlib
import os
from pathlib import Path
import sqlite3
import sys
import time
from types import SimpleNamespace

import pytest

from tools import windows_media_probe as probe


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
    class Native:
        def foreground(self): return tuple(foreground)
        def has_window(self, target): return target.pid == 111
        def focus(self, target):
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
    assert result["ok"] is bool(actions) and result["supported"] is bool(actions)
    assert calls == actions and cleanup == [True]
    assert result["cleanup_ok"]
    if actions:
        assert result["playback_state_restored"]


@pytest.mark.parametrize("uri_accepted, session_present", [(True, True), (True, False), (False, False)])
def test_explicit_spotify_prepare_launches_once_without_play_or_credentials(monkeypatch, uri_accepted, session_present):
    from src.core import media_center, media_sessions
    calls, cleanup, launches = [], [], []
    session = media_sessions.MediaSessionInfo("spotify", "Spotify.exe", status="paused")
    def launch():
        launches.append(True)
        return uri_accepted
    class Runtime:
        def __init__(self, spotify_launcher):
            self.launcher = spotify_launcher
            self.snapshot = media_center.MediaCenterSnapshot(running=True)
        def start(self, options):
            assert not any((options.auto_bgm, options.background_mute, options.auto_focus))
            return True
        def request(self, action):
            calls.append(action)
            self.launcher()
            self.snapshot = media_center.MediaCenterSnapshot(sessions=(session,) if session_present else (), running=True)
            return True
        def stop(self, **_kwargs):
            cleanup.append(True)
            return True
    monkeypatch.setattr(media_center, "MediaCenterRuntime", Runtime)
    monkeypatch.setattr(media_sessions, "launch_spotify", launch)
    monkeypatch.setattr(probe, "_wait", lambda predicate, _seconds: predicate())
    result = probe._prepare_spotify()
    assert result["ok"] is (uri_accepted and session_present)
    assert result["uri_accepted"] is uri_accepted and result["session_observed"] is session_present
    assert result["request_queued"] and result["play_requested"] is False
    assert calls == ["prepare"] and launches == cleanup == [True]
    if not session_present:
        assert result["reason"]


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
    target = GameAudioTarget("game", 111, time.time() - 10 if already_running else time.time() + 1, "game.exe", False, None)
    class Native:
        def foreground(self): return tuple(foreground)
        def has_window(self, selected): return selected is target
        def focus(self, selected):
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
    monkeypatch.setattr(probe.time, "sleep", lambda _seconds: None)
    selected, name, _started, original, events = probe._focus_compare_startup(tmp_path, tmp_path)
    assert selected is target and name == "검수 게임" and original["foreground"] == [10, 100]
    assert calls == ([] if already_running else [111])
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
