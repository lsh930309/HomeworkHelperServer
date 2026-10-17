"""공용 media probe의 운영 데이터 비변경·환경 격리·시각 검수 경계를 확인한다."""
import hashlib
import os
from pathlib import Path
import sqlite3

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
def test_not_implemented_native_scenarios_are_never_reported_as_pass(tmp_path, monkeypatch, scenario):
    for name in ("APPDATA", "LOCALAPPDATA", "HH_TEST_APPDATA_DIR"):
        monkeypatch.setenv(name, "original")
    result = probe.run(tmp_path, tmp_path, tmp_path / "result", scenario)
    assert result["ok"] is False and result["supported"] is False
    assert result["scenario"] == scenario and result["reason"]


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
