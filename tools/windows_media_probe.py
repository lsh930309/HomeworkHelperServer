"""사용자 세션의 미디어와 실제 Sidebar Widgets를 검수하는 공용 probe.

설치본·운영 writer를 생성하지 않는다. 호출자는 일반 InteractiveToken과 제한 시간을
소유하며, 이 모듈은 고정 시나리오만 실행하고 native 자원을 정상 정리한다.
"""
from __future__ import annotations

import base64
from dataclasses import asdict
from importlib import metadata
import os
from pathlib import Path
import platform
import sqlite3
import sys
import threading
import time
from types import SimpleNamespace


SCENARIOS = ("observe", "audio", "focus", "preview", "bgm")
GAME_FIELDS = ("name", "monitoring_path", "default_volume", "default_muted")
DISPLAY_FIELDS = (
    "sidebar_clock_enabled", "sidebar_clock_format", "sidebar_playtime_enabled",
    "sidebar_playtime_prefix", "sidebar_volume_section_enabled", "screenshot_enabled",
    "screenshot_save_dir", "recording_enabled", "obs_watch_output_dir",
    "obs_recording_output_dir",
)


def _isolated_environment(result_dir: Path) -> dict[str, str | None]:
    root = result_dir.resolve() / "media-fixture"
    paths = {"APPDATA": root / "roaming", "LOCALAPPDATA": root / "local",
             "HH_TEST_APPDATA_DIR": root / "state"}
    previous = {name: os.environ.get(name) for name in paths}
    for name, path in paths.items():
        path.mkdir(parents=True, exist_ok=True)
        os.environ[name] = str(path)
    return previous


def _read_display(source_appdata: Path) -> dict:
    """운영 DB는 읽기 전용이며 이름·경로·표시 설정만 명시적으로 선택한다."""
    path = source_appdata / "HomeworkHelper/homework_helper_data/app_data.db"
    if not path.is_file():
        return {"games": [], "settings": {}, "available": False}
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2) as db:
        db.row_factory = sqlite3.Row
        def columns(table, requested):
            present = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
            return [name for name in requested if name in present]
        game_fields = columns("managed_processes", GAME_FIELDS)
        settings_fields = columns("global_settings", DISPLAY_FIELDS)
        games = ([dict(row) for row in db.execute(
            "SELECT " + ",".join(game_fields) + " FROM managed_processes")]
                 if game_fields else [])
        row = (db.execute("SELECT " + ",".join(settings_fields) +
                          " FROM global_settings LIMIT 1").fetchone() if settings_fields else None)
    return {"games": games, "settings": dict(row) if row else {}, "available": True}


def _versions() -> dict:
    result = {"python": platform.python_version(), "platform": platform.platform()}
    for name in ("PySide6", "pycaw", "pywin32", "winrt-Windows.Media.Control",
                 "winrt-runtime"):
        try:
            result[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            result[name] = None
    return result


def _observe() -> dict:
    from src.core.media_center import MediaCenterRuntime, MediaOptions
    from src.core.game_focus import WindowsGameFocusNative
    from src.utils import audio_control

    first = threading.Event()
    runtime = MediaCenterRuntime(on_change=lambda _snapshot: first.set())
    started = runtime.start(MediaOptions(False, False, False))
    samples = []
    cleanup = True
    native_errors, foreground, audio = [], None, None
    try:
        if started:
            first.wait(4)
            for index in range(3):
                samples.append(asdict(runtime.snapshot))
                if not runtime.running:
                    break
                if index < 2:
                    time.sleep(.4)
        else:
            samples.append(asdict(runtime.snapshot))
        try:
            foreground = WindowsGameFocusNative().foreground()
        except Exception as error:
            native_errors.append({"stage": "foreground", "type": type(error).__name__, "error": str(error)})
        try:
            sessions = audio_control.enumerate_sessions()
            audio = {"endpoints_with_sessions": len({item.endpoint_id for item in sessions}),
                     "sessions": len(sessions)}
            del sessions  # STA handles never enter the media worker.
        except Exception as error:
            native_errors.append({"stage": "audio", "type": type(error).__name__, "error": str(error)})
    finally:
        cleanup = runtime.stop(timeout_seconds=2)
    errors = [sample["error"] for sample in samples if sample["error"]]
    return {"ok": started and cleanup and bool(samples) and not errors and not native_errors,
            "supported": True, "scenario": "observe", "samples": samples,
            "cleanup_ok": cleanup, "foreground": foreground, "audio": audio,
            "writes": [], "native_errors": native_errors, "versions": _versions()}


def _preview(source_appdata: Path, result_dir: Path) -> dict:
    from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QPoint
    from PySide6.QtWidgets import QApplication, QPushButton
    from src.core.media_center import MediaCenterSnapshot, MediaOptions
    from src.core.media_sessions import MediaSessionInfo
    from src.data.data_models import GlobalSettings, ManagedProcess
    from src.gui.main_window import MainWindow
    from src.gui.sidebar.sidebar_widget import SidebarWidget

    display = _read_display(source_appdata)
    app = QApplication.instance() or QApplication([])
    screen = app.primaryScreen()
    if screen is None:
        raise RuntimeError("사용자 세션에 표시 가능한 화면이 없습니다.")
    original_instance = MainWindow.INSTANCE
    games = [ManagedProcess(id=f"preview-game-{index}", name=row.get("name") or "게임",
                            monitoring_path=row.get("monitoring_path") or "",
                            launch_path="", default_volume=row.get("default_volume"),
                            default_muted=bool(row.get("default_muted")))
             for index, row in enumerate(display["games"])]
    settings = GlobalSettings()
    for name, value in display["settings"].items():
        setattr(settings, name, value)
    # 갤러리는 허용된 폴더를 읽기만 한다. source가 없어도 운영 기본 폴더를 추측하지 않는다.
    if not settings.screenshot_save_dir:
        capture_dir = result_dir / "media-fixture/captures"
        capture_dir.mkdir(parents=True, exist_ok=True)
        settings.screenshot_save_dir = str(capture_dir)
    saves, commands = [], []
    manager = SimpleNamespace(managed_processes=games, global_settings=settings,
                              update_process=lambda process: saves.append(process.to_dict()))
    active = {game.id: {"pid": 0, "start_time_approx": time.time() - 600,
                       "exe": game.monitoring_path} for game in games[:2]}
    MainWindow.INSTANCE = SimpleNamespace(
        process_monitor=SimpleNamespace(active_monitored_processes=active),
        _shutting_down=False, _beholder_restore_runtime_suspended=False)
    snapshot = MediaCenterSnapshot(
        sessions=(MediaSessionInfo("preview-spotify", "Spotify.exe",
                                   "검수용 긴 곡명 · Quiet afternoon in the city", "Preview artist",
                                   "playing", True, True, True, True),),
        bgm_session_id="preview-spotify", options=MediaOptions(), running=True)
    view = None
    try:
        view = SidebarWidget(
            manager, screen=screen, on_audio_change=lambda _process: True,
            audio_state=lambda _key: (True, None),
            on_media_options=lambda _options: False,
            on_media_command=lambda *args: commands.append(args) or False,
            media_state=lambda: snapshot)
        view.set_recording_output_dir(getattr(settings, "obs_recording_output_dir", "") or "")
        images, layouts = [], []
        actual = view._compute_geometry()
        for label, height in (("work-area", actual.height()), ("height-760", 760),
                              ("height-1080", 1080)):
            view.setGeometry(actual.x(), actual.y(), 280, height)
            view.refresh_content()
            # 실위젯의 시각 상태는 유지하되 검수 중 실제 동작으로 이어지는 클릭은 받지 않는다.
            for button in view.findChildren(QPushButton):
                if button.receivers("2clicked(bool)"):
                    button.clicked.disconnect()
            view.show()  # WA_ShowWithoutActivating is the product widget contract.
            view.apply_visual_settings()
            for _ in range(8):
                app.processEvents()
                time.sleep(.025)
            controls = []
            for control in view.findChildren(QPushButton):
                if control.isVisible():
                    point = control.mapTo(view, QPoint(0, 0))
                    controls.append({"name": control.objectName(),
                                     "label": control.accessibleName() or control.text(),
                                     "rect": [point.x(), point.y(), control.width(), control.height()]})
            pixmap = view.grab()
            encoded = QByteArray()
            buffer = QBuffer(encoded)
            buffer.open(QIODevice.OpenModeFlag.WriteOnly)
            if not pixmap.save(buffer, "PNG"):
                raise RuntimeError("Sidebar PNG 저장에 실패했습니다.")
            images.append({"name": f"sidebar-{label}.png",
                           "base64": bytes(encoded.toBase64()).decode("ascii")})
            layouts.append({"name": label, "geometry": list(view.geometry().getRect()),
                            "dpr": pixmap.devicePixelRatio(), "controls": controls,
                            "scroll_max": view._main_scroll.verticalScrollBar().maximum(),
                            "gallery_height": view._gallery.height(),
                            "media_geometry": list(view._media_center_panel.geometry().getRect())})
            view.hide()
        return {"ok": True, "supported": True, "scenario": "preview", "images": images,
                "layouts": layouts, "source_display_available": display["available"],
                "game_count": len(games), "fixture_saves": len(saves), "commands": commands,
                "versions": _versions(),
                "limits": ["실제 Widgets 렌더링이며 DWM 배경 블러의 화면 합성 캡처는 아닙니다.",
                           "게임 실행·종료·촬영·녹화 명령은 수행하지 않았습니다."]}
    finally:
        if view is not None:
            view.hide()
            view.cleanup(deadline_ms=2000)
            view.close()
            app.processEvents()
        MainWindow.INSTANCE = original_instance


def run(repo: Path, source_appdata: Path, result_dir: Path, scenario: str) -> dict:
    """고정 시나리오 결과를 반환한다. 미구현 검수는 성공으로 보고하지 않는다."""
    if scenario not in SCENARIOS:
        raise ValueError("지원하지 않는 미디어 검수 시나리오입니다.")
    result_dir.mkdir(parents=True, exist_ok=True)
    _isolated_environment(result_dir)
    sys.path.insert(0, str(repo))
    if scenario == "observe":
        return _observe()
    if scenario == "preview":
        return _preview(source_appdata, result_dir)
    return {"ok": False, "supported": False, "scenario": scenario,
            "reason": "실제 재생·오디오·포커스 조작 검수는 아직 이 probe에 구현되지 않았습니다."}
