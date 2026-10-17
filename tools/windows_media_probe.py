"""사용자 세션의 미디어와 실제 Sidebar Widgets를 검수하는 공용 probe.

설치본·운영 writer를 생성하지 않는다. 호출자는 일반 InteractiveToken과 제한 시간을
소유하며, 이 모듈은 고정 시나리오만 실행하고 native 자원을 정상 정리한다.
"""
from __future__ import annotations

import base64
from dataclasses import asdict, replace
from importlib import metadata
import os
import json
import ntpath
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import uuid


SCENARIOS = ("observe", "audio", "focus", "preview", "bgm", "prepare-spotify")
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


def _wait(predicate, seconds: float = 5):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(.05)
    return None


def _process_context(pid: int) -> tuple[str, int]:
    import win32api
    import win32security as security
    handle = win32api.OpenProcess(0x1000, False, pid)
    try:
        token = security.OpenProcessToken(handle, security.TOKEN_QUERY)
        try:
            return (security.ConvertSidToStringSid(security.GetTokenInformation(token, security.TokenUser)[0]),
                    security.GetTokenInformation(token, security.TokenSessionId))
        finally:
            token.Close()
    finally:
        handle.Close()


def _path_key(path) -> str:
    return ntpath.normcase(ntpath.normpath(str(path)))


def _owned_fixture(pid: int, launcher_pid: int, root: Path, kind: str, started: float):
    """ready의 PID는 후보일 뿐이다. 실제 OS identity와 고유 실행 입력으로 소유권을 판정한다."""
    import psutil
    process = psutil.Process(pid)
    allowed = {_path_key(sys.executable), _path_key(getattr(sys, "_base_executable", sys.executable))}
    if _path_key(process.exe()) not in allowed or process.create_time() < started - .1:
        raise ValueError("검수 fixture 실행파일 또는 생성 시각이 일치하지 않습니다.")
    command = process.cmdline()
    expected = [str(Path(__file__).resolve()), "--fixture", kind, "--root", str(root)]
    if (len(command) != 6 or _path_key(command[1]) != _path_key(expected[0])
            or command[2:4] != expected[1:3] or command[4] != "--root"
            or _path_key(command[5]) != _path_key(root)):
        raise ValueError("검수 fixture의 고유 root·고정 실행 인자가 일치하지 않습니다.")
    # Windows venv의 pythonw launcher와 실제 base pythonw PID는 다를 수 있다.
    if (pid != launcher_pid and process.ppid() != launcher_pid
            and not any(parent.pid == launcher_pid for parent in process.parents())):
        raise ValueError("검수 fixture가 시작한 launcher의 자식이 아닙니다.")
    if _process_context(pid) != _process_context(os.getpid()):
        raise ValueError("검수 fixture의 Windows 사용자 또는 세션이 일치하지 않습니다.")
    return process


class _FixtureProcess:
    """launcher가 먼저 끝나도 실제 소유 child의 종료를 기다린다."""
    def __init__(self, launcher, process):
        self.launcher, self.process, self.pid = launcher, process, process.pid

    def wait(self, timeout):
        deadline = time.monotonic() + timeout
        self.process.wait(timeout=timeout)
        self.launcher.wait(timeout=max(.01, deadline - time.monotonic()))


def _cleanup_unready_fixture(launcher, root: Path, kind: str, started: float) -> bool:
    import psutil
    (root / "stop").touch()
    owned = []
    for process in psutil.process_iter(["pid", "cmdline"]):
        command = process.info.get("cmdline") or []
        if len(command) == 6 and _path_key(command[-1]) == _path_key(root):
            try:
                owned.append(_owned_fixture(process.pid, launcher.pid, root, kind, started))
            except (ValueError, psutil.Error):
                continue
    complete = True
    for process in owned:
        complete = _stop_fixture(_FixtureProcess(launcher, process), root) and complete
    if not owned:
        complete = _stop_fixture(launcher, root)
    return complete


def _spawn_fixture(result_dir: Path, kind: str):
    """다른 프로세스와 섞이지 않는 자기 fixture만 고정 child 모드로 생성한다."""
    root = result_dir / "media-fixture" / (kind + "-" + uuid.uuid4().hex[:8])
    root.mkdir(parents=True)
    started = time.time()
    child = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--fixture", kind, "--root", str(root)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        if not _wait(lambda: (root / "ready.json").is_file() or (root / "error.json").is_file(), 8):
            raise RuntimeError("검수 fixture 준비 시간이 만료됐습니다.")
        if not (root / "ready.json").is_file():
            detail = (root / "error.json").read_text(encoding="utf-8")
            raise RuntimeError(f"검수 fixture가 준비 전에 종료됐습니다: {detail}")
        ready = json.loads((root / "ready.json").read_text(encoding="utf-8"))
        process = _owned_fixture(int(ready["pid"]), child.pid, root, kind, started)
    except Exception as error:
        if not _cleanup_unready_fixture(child, root, kind, started):
            raise RuntimeError(f"{error}; fixture 정상 종료를 확인하지 못했습니다: {root}") from error
        raise
    return _FixtureProcess(child, process), root, ready


def _stop_fixture(child, root: Path) -> bool:
    import psutil
    (root / "stop").touch()
    try:
        child.wait(timeout=4)
        return True
    except (subprocess.TimeoutExpired, psutil.TimeoutExpired):
        return False  # 강제 종료·자동 재실행은 하지 않으며 child 자체 상한은 90초다.


def _audio(result_dir: Path) -> dict:
    import pythoncom  # noqa: F401; caller STA initialization precedes COM access.
    import comtypes  # noqa: F401
    import psutil
    from src.core.game_audio import GameAudioCoordinator, GameAudioTarget
    from src.utils import audio_control

    child, root, _ready = _spawn_fixture(result_dir, "audio")
    target = None
    coordinator = GameAudioCoordinator()
    initial, steps, errors = {}, [], []
    restored, cleaned, exited = False, False, False
    try:
        process = psutil.Process(child.pid)
        target = GameAudioTarget("media-probe-audio", child.pid, process.create_time(), process.exe(), False, 55)
        sessions = _wait(lambda: tuple(session for session in audio_control.enumerate_sessions()
                                       if session.pid == child.pid), 5)
        if not sessions:
            raise RuntimeError("검수 fixture의 WASAPI 세션이 생성되지 않았습니다.")
        initial = {session.key: (session.get_volume(), session.get_mute()) for session in sessions}
        del sessions
        cases = (("foreground", target, child.pid, False, False, 0.55),
                 ("background-muted", target, 0, True, True, 0.55),
                 ("user-muted", replace(target, user_muted=True), child.pid, True, True, 0.55),
                 ("zero-volume", replace(target, user_volume=0), child.pid, True, False, 0.0),
                 ("return-foreground", target, child.pid, True, False, 0.55))
        for label, current, foreground, background, muted, volume in cases:
            coordinator.update_targets((current,))
            rows = coordinator.reconcile(foreground, background_mute=background)
            observed = rows[0] if rows else None
            matched = bool(observed and observed.available and observed.muted == muted
                           and observed.volume is not None and abs(observed.volume - volume) < .02
                           and observed.audible == (volume > 0 and not muted))
            steps.append({"name": label, "ok": matched,
                          "observation": asdict(observed) if observed else None})
    except Exception as error:
        errors.append({"type": type(error).__name__, "error": str(error)})
    finally:
        try:
            cleaned = coordinator.cleanup()
        except Exception as error:
            errors.append({"stage": "cleanup", "type": type(error).__name__, "error": str(error)})
        try:
            if initial and audio_control.verify_identity(target):
                sessions = tuple(session for session in audio_control.enumerate_sessions()
                                 if session.pid == child.pid and session.key in initial)
                restored = len(sessions) == len(initial)
                for session in sessions:
                    volume, muted = initial[session.key]
                    session.set_volume(volume)
                    session.set_mute(muted)
                    restored = restored and abs(session.get_volume() - volume) < .001 and session.get_mute() == muted
                del sessions
        except Exception as error:
            errors.append({"stage": "restore", "type": type(error).__name__, "error": str(error)})
        finally:
            exited = _stop_fixture(child, root)
    return {"ok": len(steps) == 5 and all(row["ok"] for row in steps) and cleaned and restored and exited and not errors,
            "supported": True, "scenario": "audio", "fixture_pid": child.pid,
            "identity": asdict(target) if target else None, "steps": steps, "errors": errors,
            "cleanup_ok": cleaned, "initial_audio_restored": restored, "fixture_exited": exited,
            "limits": ["실제 WASAPI를 사용하며 foreground 입력은 검수용으로 고정합니다."]}


def _restore_foreground(hwnd: int) -> bool:
    import win32gui
    if not hwnd:
        return False
    if win32gui.GetForegroundWindow() == hwnd:
        return True
    if not win32gui.IsWindow(hwnd):
        return False
    try:
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        return False
    return bool(_wait(lambda: win32gui.GetForegroundWindow() == hwnd, 1))


def _focus(result_dir: Path) -> dict:
    import psutil
    from src.core.game_audio import GameAudioTarget
    from src.core.game_focus import AutoFocusTracker, WindowsGameFocusNative

    native = WindowsGameFocusNative()
    original_pid, original_hwnd = native.foreground()
    requests = []
    class RecordingNative:
        def has_window(self, target):
            return native.has_window(target)
        def focus(self, target):
            accepted = native.focus(target)
            requests.append({"pid": target.pid, "accepted": accepted})
            return accepted
    start = time.time()
    tracker = AutoFocusTracker(started_at_wall=start, native=RecordingNative())
    tracker.tick((), original_pid, original_hwnd, time.monotonic(), os.getpid())
    child, root, ready = _spawn_fixture(result_dir, "focus")
    restored, exited = False, False
    try:
        process = psutil.Process(child.pid)
        target = GameAudioTarget("media-probe-focus", child.pid, process.create_time(), process.exe(), False, None)
        has_window = native.has_window(target)
        foreground = native.foreground()
        tracker.tick((target,), *foreground, time.monotonic(), os.getpid())
        observed = _wait(lambda: native.foreground()[0] == child.pid, 1) is True
        for _ in range(3):
            tracker.tick((target,), *native.foreground(), time.monotonic(), os.getpid())
        actual = native.foreground()
    finally:
        tracker.cancel()
        restored = _restore_foreground(original_hwnd)
        exited = _stop_fixture(child, root)
    return {"ok": has_window and len(requests) == 1 and requests[0]["accepted"] and observed and restored and exited,
            "supported": True, "scenario": "focus", "fixture_pid": child.pid,
            "fixture_hwnd": ready.get("hwnd"), "window_ready": has_window,
            "requests": requests, "foreground_observed": observed, "foreground_after": actual,
            "original_foreground": [original_pid, original_hwnd], "foreground_restored": restored,
            "fixture_exited": exited,
            "limits": ["Windows 전경 전환 거절은 요청 수락과 실제 전환 결과로 구분합니다."]}


def _bgm() -> dict:
    from src.core.media_center import MediaCenterRuntime, MediaOptions
    from src.core.media_sessions import is_spotify_session

    first = threading.Event()
    runtime = MediaCenterRuntime(on_change=lambda _snapshot: first.set(), spotify_launcher=lambda: False)
    started = runtime.start(MediaOptions(False, False, False))
    steps, restored, cleanup, original = [], False, False, None
    result = {"ok": False, "supported": False, "scenario": "bgm"}
    try:
        if not started:
            result["reason"] = runtime.snapshot.error or "미디어 worker를 시작하지 못했습니다."
            return result
        first.wait(4)
        _wait(lambda: runtime.snapshot.sessions or runtime.snapshot.error or not runtime.running, 4)
        spotify = tuple(item for item in runtime.snapshot.sessions if is_spotify_session(item))
        if len(spotify) != 1:
            result["reason"] = "기존 Spotify 세션이 없거나 여러 개이므로 실행·재생하지 않았습니다."
            return result
        original = spotify[0]
        can_transition = ((original.status == "playing" and original.can_pause)
                          or (original.status == "paused" and original.can_play))
        if not can_transition:
            result["reason"] = "현재 상태에서 실행할 Play 또는 Pause 명령 지원을 확인하지 못했습니다."
            return result
        result["supported"] = True
        desired = "paused" if original.status == "playing" else "playing"
        command = "pause" if desired == "paused" else "play"
        accepted = runtime.request(command, original.session_id)
        observed = bool(_wait(lambda: any(item.session_id == original.session_id and item.status == desired
                                          for item in runtime.snapshot.sessions), 5)) if accepted else False
        steps.append({"action": command, "queued": accepted, "status_observed": observed})
    finally:
        if original is not None and result.get("supported"):
            # 종료된 세션이나 다른 세션을 자동 대체하지 않는다. URI 실행도 허용하지 않는다.
            same = any(item.session_id == original.session_id for item in runtime.snapshot.sessions)
            action = "play" if original.status == "playing" else "pause"
            accepted = same and runtime.request(action, original.session_id)
            matching = bool(_wait(lambda: any(item.session_id == original.session_id and item.status == original.status
                                              for item in runtime.snapshot.sessions), 5)) if accepted else False
            # 첫 전환을 못 봤다면 같은 원래 상태는 아직 도착하지 않은 응답일 수 있다.
            restored = matching and bool(steps and steps[0]["status_observed"])
            steps.append({"action": action, "queued": accepted, "original_status_observed": matching,
                          "restored": restored})
        cleanup = runtime.stop(timeout_seconds=2)
        result.update(steps=steps, original=asdict(original) if original else None,
                      playback_state_restored=restored, cleanup_ok=cleanup)
    result["ok"] = bool(result["supported"] and steps[0]["status_observed"] and restored and cleanup)
    result["limits"] = ["재생 상태만 복원하며 재생 위치의 정확한 역행·복구는 요청하지 않습니다.",
                        "Firefox 종료 구분·다른 미디어 보류 정책은 별도 검증 대상입니다."]
    return result


def _prepare_spotify() -> dict:
    """고정 prepare 명령 한 번만 실행한다. 로그인 정보 조회·Play 요청은 없다."""
    from src.core.media_center import MediaCenterRuntime, MediaOptions
    from src.core.media_sessions import is_spotify_session, launch_spotify

    launched = threading.Event()
    launches = []
    def launch_once():
        try:
            accepted = bool(launch_spotify())
            launches.append({"uri_accepted": accepted})
            return accepted
        except Exception as error:
            launches.append({"uri_accepted": False, "type": type(error).__name__, "error": str(error)})
            raise
        finally:
            launched.set()
    runtime = MediaCenterRuntime(spotify_launcher=launch_once)
    started = runtime.start(MediaOptions(False, False, False))
    queued, sessions, cleanup = False, (), False
    try:
        if started:
            queued = runtime.request("prepare")
            if queued and launched.wait(4) and launches[0]["uri_accepted"]:
                _wait(lambda: any(is_spotify_session(item) for item in runtime.snapshot.sessions), 10)
            sessions = tuple(item for item in runtime.snapshot.sessions if is_spotify_session(item))
        error = runtime.snapshot.error
    finally:
        cleanup = runtime.stop(timeout_seconds=2)
    accepted = len(launches) == 1 and launches[0]["uri_accepted"]
    result = {"ok": bool(started and queued and accepted and sessions and cleanup),
              "supported": True, "scenario": "prepare-spotify", "request_queued": queued,
              "launches": launches, "uri_accepted": accepted, "session_observed": bool(sessions),
              "sessions": [asdict(item) for item in sessions], "error": error,
              "cleanup_ok": cleanup, "play_requested": False}
    if accepted and not sessions:
        result["reason"] = ("Spotify URI 실행 요청은 수락됐지만 미디어 세션은 관측하지 못했습니다. "
                            "로그인 또는 트랙 선택이 필요한지는 화면에서 별도로 확인해야 합니다.")
    elif not accepted:
        result["reason"] = "Spotify URI 실행 요청 수락을 확인하지 못했습니다. 자동 재시도하지 않습니다."
    return result


def _fixture_main(kind: str, root: Path) -> int:
    """최대 90초의 소유 fixture. 프로덕션 모듈·DB·설정을 읽지 않는다."""
    def ready(**values):
        path = root / "ready.tmp"
        path.write_text(json.dumps({"pid": os.getpid(), **values}), encoding="utf-8")
        path.replace(root / "ready.json")
    if kind == "audio":
        import math
        import struct
        import wave
        import winsound
        wav = root / "fixture.wav"
        with wave.open(str(wav), "wb") as stream:
            stream.setparams((1, 2, 22050, 22050, "NONE", "not compressed"))
            # 약 -60dB의 신호로 오디오 세션만 유지한다.
            stream.writeframes(b"".join(struct.pack("<h", int(32 * math.sin(2 * math.pi * 220 * index / 22050)))
                                        for index in range(22050)))
        winsound.PlaySound(str(wav), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP)
        try:
            ready()
            _wait(lambda: (root / "stop").exists(), 90)
        finally:
            winsound.PlaySound(None, 0)
        return 0
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import QApplication, QLabel
    app = QApplication([])
    window = QLabel("HomeworkHelper · 자동 포커스 검수 창")
    window.setWindowTitle("HomeworkHelper media QA fixture")
    window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    window.resize(420, 180)
    window.show()
    app.processEvents()
    ready(hwnd=int(window.winId()))
    timer = QTimer()
    timer.timeout.connect(lambda: app.quit() if (root / "stop").exists() else None)
    timer.start(50)
    QTimer.singleShot(90000, app.quit)
    return app.exec()


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
    if scenario == "audio":
        return _audio(result_dir)
    if scenario == "focus":
        return _focus(result_dir)
    if scenario == "prepare-spotify":
        return _prepare_spotify()
    return _bgm()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="고정 media QA fixture child")
    parser.add_argument("--fixture", choices=("audio", "focus"), required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    try:
        code = _fixture_main(args.fixture, args.root)
    except Exception as error:
        (args.root / "error.json").write_text(json.dumps(
            {"type": type(error).__name__, "error": str(error)}, ensure_ascii=False), encoding="utf-8")
        code = 1
    raise SystemExit(code)
