"""사용자 세션의 미디어와 실제 Sidebar Widgets를 검수하는 공용 probe.

설치본·운영 writer를 생성하지 않는다. 호출자는 일반 InteractiveToken과 제한 시간을
소유하며, 이 모듈은 고정 시나리오만 실행하고 native 자원을 정상 정리한다.
"""
from __future__ import annotations

import base64
from collections import deque
from dataclasses import asdict, fields, is_dataclass, replace
from importlib import metadata
import os
import json
import logging
import ntpath
from contextlib import contextmanager
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import threading
import time
from types import SimpleNamespace
import uuid


SPOTIFY_WINDOW_SCENARIOS = ("spotify-window-observe", "spotify-window-open", "spotify-window-minimize", "spotify-window-close")
SCENARIOS = ("observe", "audio", "focus", "preview", "bgm", "prepare-spotify", "triggers", "firefox", "focus-compare", "focus-uia", "focus-lifecycle", *SPOTIFY_WINDOW_SCENARIOS)
GAME_FIELDS = ("name", "monitoring_path", "default_volume", "default_muted")
DISPLAY_FIELDS = (
    "sidebar_clock_enabled", "sidebar_clock_format", "sidebar_playtime_enabled",
    "sidebar_playtime_prefix", "sidebar_volume_section_enabled", "screenshot_enabled",
    "screenshot_save_dir", "recording_enabled", "obs_watch_output_dir",
    "obs_recording_output_dir",
)


def _media_session_payload(session) -> dict:
    """JSON 근거에는 표지 원문을 복제하지 않고 제공된 크기만 남긴다."""
    result = {field.name: getattr(session, field.name)
              for field in fields(session) if field.name != "artwork"}
    result["artwork_bytes"] = len(session.artwork)
    return result


def _media_snapshot_payload(snapshot) -> dict:
    result = {}
    for field in fields(snapshot):
        value = getattr(snapshot, field.name)
        if field.name == "sessions":
            result[field.name] = [_media_session_payload(session) for session in value]
        elif is_dataclass(value):
            result[field.name] = asdict(value)
        elif isinstance(value, tuple):
            result[field.name] = [asdict(item) if is_dataclass(item) else item for item in value]
        else:
            result[field.name] = value
    return result


def _spotify_probe_processes(source_appdata: Path, source_local_appdata: str | None):
    # 운영 환경값은 이 읽기 함수에만 적용한다. 제품 모듈은 격리 환경에서 먼저 로드한다.
    import psutil  # noqa: F401
    import src.core.process_monitor  # noqa: F401
    from src.core.spotify_app import spotify_processes
    values = {"APPDATA": str(source_appdata)}
    if source_local_appdata is not None:
        values["LOCALAPPDATA"] = source_local_appdata
    previous = {name: os.environ.get(name) for name in values}
    try:
        os.environ.update(values)
        return spotify_processes()
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _spotify_window_state(source_appdata: Path, source_local_appdata: str | None) -> dict:
    import win32gui
    import win32process
    processes = _spotify_probe_processes(source_appdata, source_local_appdata)
    by_pid = {process.pid: process for process in processes}
    windows = []
    def collect(hwnd, _unused):
        matched = None
        try:
            pid = win32process.GetWindowThreadProcessId(hwnd)[1]
            matched = by_pid.get(pid)
            if matched is None:
                return
            windows.append({"hwnd": int(hwnd), "pid": pid, "create_time": matched.create_time,
                            "path": matched.path, "visible": bool(win32gui.IsWindowVisible(hwnd)),
                            "iconic": bool(win32gui.IsIconic(hwnd)),
                            "rect": list(win32gui.GetWindowRect(hwnd)),
                            "class": win32gui.GetClassName(hwnd),
                            "owner": int(win32gui.GetWindow(hwnd, 4) or 0)})
        except Exception as error:
            if matched is not None:
                windows.append({"hwnd": int(hwnd), "pid": matched.pid, "gone": True,
                                "error_type": type(error).__name__})
    win32gui.EnumWindows(collect, None)
    return {"processes": [asdict(process) for process in processes], "windows": windows,
            "foreground_hwnd": int(win32gui.GetForegroundWindow() or 0)}


def _spotify_chrome_controls(window: dict) -> dict:
    """최상위 Spotify 창의 고정 메뉴 명칭만 읽는다. 클릭·포커스·본문 수집은 없다."""
    import comtypes
    from src.core.spotify_app import SpotifyProcess
    from src.utils.audio_control import verify_identity
    from src.gui.runtime_logging import redact_sensitive_text
    result = {"controls": [], "timeouts_ms": {"connection": 500, "transaction": 1500}}
    cancelled = threading.Event()
    target = SpotifyProcess(window["pid"], window["create_time"], window["path"])
    names = {"file", "파일", "exit", "종료", "quit", "close", "닫기", "minimize", "최소화",
             "spotify", "main menu", "메인 메뉴", "open menu", "메뉴 열기", "menu", "메뉴"}
    def worker():
        initialized = False
        automation = element = walker = None
        try:
            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
            initialized = True
            from comtypes import client
            import win32process
            if (cancelled.is_set() or not verify_identity(target)
                    or win32process.GetWindowThreadProcessId(window["hwnd"])[1] != target.pid):
                raise ValueError("Spotify 창 identity가 변경되어 UIA 조회를 중단했습니다.")
            module = client.GetModule("UIAutomationCore.dll")
            automation = client.CreateObject("{E22AD333-B25F-460C-83D0-0581107395C9}", interface=module.IUIAutomation2)
            automation.ConnectionTimeout, automation.TransactionTimeout = 500, 1500
            element = automation.ElementFromHandle(window["hwnd"])
            walker = automation.ControlViewWalker
            queue = deque([(element, 0)])
            visited, deadline = 0, time.monotonic() + 4
            while queue and visited < 40 and not cancelled.is_set() and time.monotonic() < deadline:
                node, depth = queue.popleft()
                visited += 1
                control_type = int(node.CurrentControlType)
                if control_type in (50000, 50009, 50010, 50011):
                    name = str(node.CurrentName or "")
                    if name.casefold().strip("& .…") in names:
                        result["controls"].append({"name": name, "control_type": control_type, "depth": depth})
                if depth >= 3:
                    continue
                child = walker.GetFirstChildElement(node)
                while child and len(queue) + visited < 40 and not cancelled.is_set() and time.monotonic() < deadline:
                    queue.append((child, depth + 1))
                    child = walker.GetNextSiblingElement(child)
            result["visited"] = visited
        except Exception as error:
            result.update(error_type=type(error).__name__, error=redact_sensitive_text(error))
        finally:
            queue = None
            node = child = walker = element = automation = None
            if initialized:
                comtypes.CoUninitialize()
    thread = threading.Thread(target=worker, name="SpotifyChromeUia", daemon=True)
    thread.start()
    thread.join(timeout=5)
    cancelled.set()
    return {**result, "controls": list(result["controls"]), "worker_stopped": not thread.is_alive()}


def _spotify_window_action(window: dict, action: str, *, is_current) -> dict:
    """읽기 snapshot의 같은 사용자·프로세스·창에 고정 명령을 한 번만 전달한다."""
    import win32gui
    import win32process
    from src.core.spotify_app import SpotifyProcess
    from src.utils.audio_control import verify_identity
    if action not in ("minimize", "close"):
        raise ValueError("지원하지 않는 Spotify 창 명령입니다.")
    if action == "minimize":
        import ctypes
        from ctypes import wintypes
        show = ctypes.WinDLL("user32", use_last_error=True).ShowWindowAsync
        show.argtypes, show.restype = [wintypes.HWND, ctypes.c_int], wintypes.BOOL
    target = SpotifyProcess(window["pid"], window["create_time"], window["path"])
    hwnd = window["hwnd"]
    if (not is_current() or not verify_identity(target)
            or win32process.GetWindowThreadProcessId(hwnd)[1] != target.pid
            or not win32gui.IsWindowVisible(hwnd) or win32gui.GetWindow(hwnd, 4)
            or not is_current()):
        raise ValueError("Spotify 창 identity 또는 요청이 변경되어 명령을 보내지 않았습니다.")
    if action == "minimize" and win32gui.IsIconic(hwnd):
        return {"attempted": False, "accepted": None, "already_minimized": True}
    if not is_current():
        raise ValueError("Spotify 창 요청이 취소되어 명령을 보내지 않았습니다.")
    try:
        if action == "close":
            win32gui.PostMessage(hwnd, 0x0010, 0, 0)  # WM_CLOSE: 강제 종료·WM_QUIT가 아니다.
        elif not show(hwnd, 7):  # SW_SHOWMINNOACTIVE; 실제 완료는 trace로 별도 관측한다.
            raise OSError("Windows가 Spotify 창 최소화 요청을 수락하지 않았습니다.")
    except Exception as error:
        return {"attempted": True, "accepted": False, "error_type": type(error).__name__, "error": str(error)}
    return {"attempted": True, "accepted": True}


def _spotify_window_observe(source_appdata: Path, source_local_appdata: str | None,
                            scenario: str = "spotify-window-observe") -> dict:
    if scenario not in SPOTIFY_WINDOW_SCENARIOS:
        raise ValueError("지원하지 않는 Spotify 창 검수 시나리오입니다.")
    from src.core.media_center import MediaCenterRuntime, MediaOptions
    runtime = MediaCenterRuntime(spotify_launcher=lambda: False)
    started = runtime.start(MediaOptions(False, False, False))
    trace, cleanup, errors, chrome, request = [], False, [], None, None
    origin = time.monotonic()
    try:
        if started:
            _wait(lambda: runtime.snapshot.sessions or runtime.snapshot.error, 4)
        count = 81 if scenario.endswith("-open") else 8 if scenario.endswith("-observe") else 41
        for index in range(count):
            state = _spotify_window_state(source_appdata, source_local_appdata)
            trace.append({"at_ms": round((time.monotonic() - origin) * 1000, 2),
                          "utc": time.time(), **state,
                          "media": _media_snapshot_payload(runtime.snapshot)})
            if index == 0 and scenario != "spotify-window-observe":
                action = scenario.removeprefix("spotify-window-")
                request = {"action": action, "attempted": False, "accepted": None,
                           "at_ms": round((time.monotonic() - origin) * 1000, 2), "utc": time.time()}
                try:
                    if not started or not runtime.running:
                        raise ValueError("미디어 관측 worker가 준비되지 않아 명령을 보내지 않았습니다.")
                    if action == "open":
                        from src.core.spotify_app import launch_spotify
                        request["attempted"] = True
                        request["accepted"] = bool(launch_spotify())  # 고정 spotify: 한 번; Play 없음.
                        if not request["accepted"]:
                            raise OSError("Spotify URI 요청을 수락하지 않았습니다.")
                    else:
                        candidates = [window for window in state["windows"]
                                      if window.get("visible") and not window.get("owner") and not window.get("gone")]
                        if len(candidates) != 1:
                            raise ValueError("유일한 Spotify 메인 창을 확인하지 못해 명령을 보내지 않았습니다.")
                        request["target"] = candidates[0]
                        request.update(_spotify_window_action(candidates[0], action, is_current=lambda: runtime.running))
                        if request.get("error_type"):
                            errors.append({"stage": "request", **request})
                except Exception as error:
                    request.update(error_type=type(error).__name__, error=str(error))
                    errors.append({"stage": "request", **request})
            if index < count - 1:
                time.sleep(.125)
        candidates = [window for window in trace[-1]["windows"]
                      if window.get("visible") and not window.get("owner") and not window.get("gone")]
        if len(candidates) == 1 and scenario in ("spotify-window-observe", "spotify-window-open"):
            chrome = _spotify_chrome_controls(candidates[0])
    except Exception as error:
        errors.append({"error_type": type(error).__name__, "error": str(error)})
    finally:
        cleanup = runtime.stop(timeout_seconds=2)
    return {"ok": bool(started and trace and cleanup and not errors), "supported": True,
            "scenario": scenario, "trace": trace, "chrome": chrome, "request": request,
            "errors": errors, "cleanup_ok": cleanup, "writes": [],
            "limits": ["ok는 관측 절차 완료이며 창 최소화·트레이·재생 유지의 성공 판정이 아닙니다.",
                       "선택한 고정 창 명령 또는 URI 요청만 한 번 실행하며 Play·복원·재전송·강제 종료·설정 변경은 없습니다.",
                       "WM_CLOSE의 트레이 유지 여부는 Spotify 설정과 후속 process·GSMTC 관측으로 구분합니다."]}


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
                samples.append(_media_snapshot_payload(runtime.snapshot))
                if not runtime.running:
                    break
                if index < 2:
                    time.sleep(.4)
        else:
            samples.append(_media_snapshot_payload(runtime.snapshot))
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


@contextmanager
def _focus_diagnostics():
    from src.gui.runtime_logging import RedactingFormatter
    records = []
    class MemoryHandler(logging.Handler):
        def emit(self, record):
            if len(records) < 100:
                records.append({"logger": record.name, "level": record.levelname,
                                "message": self.format(record)})
    handler = MemoryHandler()
    handler.setFormatter(RedactingFormatter("%(message)s"))
    loggers = [logging.getLogger(name) for name in ("src.utils.windows", "src.core.game_focus")]
    levels = [logger.level for logger in loggers]
    for logger in loggers:
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    try:
        yield records
    finally:
        for logger, level in zip(loggers, levels):
            logger.removeHandler(handler)
            logger.setLevel(level)
        handler.close()


def _focus(result_dir: Path) -> dict:
    import psutil
    from src.core.game_audio import GameAudioTarget
    from src.core.game_focus import AutoFocusTracker, WindowsGameFocusNative

    native = WindowsGameFocusNative()
    original_pid, original_hwnd = native.foreground()
    requests = []
    class RecordingNative:
        foreground = native.foreground
        window = native.window
        is_window_hidden = native.is_window_hidden
        is_related_foreground = native.is_related_foreground
        def focus(self, target, hwnd=None):
            accepted = native.focus(target, hwnd)
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
        has_window = native.window(target) is not None
        with _focus_diagnostics() as diagnostics:
            deadline = time.monotonic() + tracker.WINDOW_STABLE_SECONDS + 1
            while not requests and time.monotonic() < deadline:
                tracker.tick((target,), *native.foreground(), time.monotonic(), os.getpid())
                time.sleep(.05)
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
            "diagnostics": diagnostics,
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
        result.update(steps=steps, original=_media_session_payload(original) if original else None,
                      playback_state_restored=restored, cleanup_ok=cleanup)
    result["ok"] = bool(result["supported"] and steps[0]["status_observed"] and restored and cleanup)
    result["limits"] = ["재생 상태만 복원하며 재생 위치의 정확한 역행·복구는 요청하지 않습니다.",
                        "Firefox 종료 구분·다른 미디어 보류 정책은 별도 검증 대상입니다."]
    return result


def _prepare_spotify() -> dict:
    """고정 prepare 명령 한 번만 실행한다. 로그인 정보 조회·Play 요청은 없다."""
    from src.core.media_center import MediaCenterRuntime, MediaOptions
    from src.core.media_sessions import is_spotify_session
    from src.core.spotify_app import launch_spotify

    launches = []
    def launch_once():
        try:
            accepted = bool(launch_spotify())
            launches.append({"uri_accepted": accepted})
            return accepted
        except Exception as error:
            launches.append({"uri_accepted": False, "type": type(error).__name__, "error": str(error)})
            raise
    runtime = MediaCenterRuntime(spotify_launcher=launch_once)
    started = runtime.start(MediaOptions(False, False, False))
    queued, sessions, cleanup = False, (), False
    try:
        if started:
            queued = runtime.request("prepare")
            if queued:
                # 실행 중인 앱은 URI를 다시 열지 않는다. 실제 세션 준비가 완료 기준이다.
                _wait(lambda: any(is_spotify_session(item) for item in runtime.snapshot.sessions)
                      or bool(runtime.snapshot.error), runtime.PREPARE_TIMEOUT_SECONDS)
            sessions = tuple(item for item in runtime.snapshot.sessions if is_spotify_session(item))
        error = runtime.snapshot.error
    finally:
        cleanup = runtime.stop(timeout_seconds=2)
    requested = bool(launches)
    accepted = launches[0]["uri_accepted"] if requested else None
    result = {"ok": bool(started and queued and sessions and cleanup and not error
                         and (not requested or (len(launches) == 1 and accepted))),
              "supported": True, "scenario": "prepare-spotify", "request_queued": queued,
              "launches": launches, "uri_requested": requested, "uri_accepted": accepted,
              "session_observed": bool(sessions),
              "sessions": [_media_session_payload(item) for item in sessions], "error": error,
              "cleanup_ok": cleanup, "play_requested": False}
    if error:
        result["reason"] = error
    elif not started or not queued:
        result["reason"] = "Spotify 준비 요청을 접수하지 못했습니다."
    elif requested and (len(launches) != 1 or not accepted):
        result["reason"] = "Spotify URI 실행 요청 수락을 확인하지 못했습니다. 자동 재시도하지 않습니다."
    elif accepted and not sessions:
        result["reason"] = ("Spotify URI 실행 요청은 수락됐지만 미디어 세션은 관측하지 못했습니다. "
                            "로그인 또는 트랙 선택이 필요한지는 화면에서 별도로 확인해야 합니다.")
    elif not sessions:
        result["reason"] = ("새 URI 실행 없이 기다렸지만 Spotify 미디어 세션을 관측하지 못했습니다. "
                            "실행 중인 앱을 자동으로 다시 열거나 Play를 요청하지 않았습니다.")
    return result


def _triggers(result_dir: Path) -> dict:
    """실제 Spotify·WASAPI 통합. foreground 입력만 명시적으로 합성한다."""
    import psutil
    from src.core.game_audio import GameAudioTarget
    from src.core.media_center import MediaCenterRuntime, MediaOptions
    from src.core.media_sessions import is_spotify_session
    from src.utils import audio_control

    deadline = time.monotonic() + 60  # fixture 준비·정상 정리 여유를 포함해 80초 안에 종료한다.
    foreground = [os.getpid() + 100000, 1]
    runtime = MediaCenterRuntime(native_factory=lambda: SimpleNamespace(
        foreground=lambda: tuple(foreground)), spotify_launcher=lambda: False)
    result = {"ok": False, "supported": False, "scenario": "triggers", "foreground_input": "synthetic",
              "limits": ["foreground만 합성 입력이며 Spotify/GSMTC/WASAPI는 실제 Windows 경로입니다.",
                         "실제 Firefox 재생·종료 감지는 이 시나리오에서 검수하지 않습니다."]}
    steps, errors, original, child, root, target, initial = [], [], None, None, None, None, {}
    audio_restored, playback_restored, cleanup, exited = True, False, True, True
    def wait(predicate, seconds=6):
        return _wait(predicate, max(0, min(seconds, deadline - time.monotonic())))
    def status_matches(status):
        return any(item.session_id == original.session_id and item.status == status
                   for item in runtime.snapshot.sessions)
    def record(name, predicate):
        matched = bool(wait(predicate))
        steps.append({"name": name, "ok": matched, "snapshot": _media_snapshot_payload(runtime.snapshot)})
        if not matched:
            raise RuntimeError(f"자동 미디어 통합 검수 결과를 확인하지 못했습니다: {name}")
    try:
        if not runtime.start(MediaOptions(False, False, False)):
            result["reason"] = runtime.snapshot.error or "미디어 worker 준비 실패"
            return result
        wait(lambda: runtime.snapshot.sessions or runtime.snapshot.error, 5)
        spotify = tuple(item for item in runtime.snapshot.sessions if is_spotify_session(item))
        if len(spotify) != 1 or spotify[0].status not in {"playing", "paused"}:
            result["reason"] = "playing/paused 상태의 명확한 기존 Spotify 세션 하나가 필요합니다."
            return result
        original = spotify[0]
        if any(item.status == "playing" and item.session_id != original.session_id
               for item in runtime.snapshot.sessions):
            result["reason"] = "다른 미디어가 재생 중이어서 자동 재생 검수를 수행하지 않았습니다."
            return result
        result["supported"] = True
        if original.status == "playing":
            queued = runtime.request("pause", original.session_id)
            if not queued or not wait(lambda: status_matches("paused")):
                raise RuntimeError("자동 Play 검수 전 명시적 일시정지 baseline을 만들지 못했습니다.")
        result["baseline_status"] = "paused"
        runtime.configure(MediaOptions(True, False, False))
        record("quiet-auto-play", lambda: status_matches("playing"))
        child, root, _ready = _spawn_fixture(result_dir, "audio")
        process = psutil.Process(child.pid)
        target = GameAudioTarget("media-trigger-fixture", child.pid, process.create_time(), process.exe(), False, 55)
        sessions = wait(lambda: tuple(item for item in audio_control.enumerate_sessions() if item.pid == child.pid), 5)
        if not sessions:
            raise RuntimeError("트리거 검수용 오디오 세션이 없습니다.")
        initial = {session.key: (session.get_volume(), session.get_mute()) for session in sessions}
        del sessions
        foreground[:] = [child.pid, 1]
        runtime.update_targets((target,))
        record("audible-game-pauses-bgm", lambda: status_matches("paused") and any(
            row.target.pid == child.pid and row.audible is True for row in runtime.snapshot.game_audio))
        runtime.update_targets((replace(target, user_muted=True),))
        record("user-mute-resumes-bgm", lambda: status_matches("playing") and any(
            row.target.pid == child.pid and row.available and row.muted is True
            for row in runtime.snapshot.game_audio))
        if not runtime.request("pause", original.session_id):
            raise RuntimeError("명시적 일시정지 요청이 접수되지 않았습니다.")
        record("manual-pause", lambda: status_matches("paused"))
        hold_until, stable = min(time.monotonic() + 1, deadline), True
        while time.monotonic() < hold_until:
            stable = stable and status_matches("paused")
            time.sleep(.05)
        steps.append({"name": "unchanged-context-does-not-replay", "ok": stable})
    except Exception as error:
        errors.append({"type": type(error).__name__, "error": str(error)})
    finally:
        runtime.configure(MediaOptions(False, False, False))
        if original is not None and result["supported"]:
            action = "play" if original.status == "playing" else "pause"
            queued = runtime.request(action, original.session_id)
            playback_restored = bool(wait(lambda: status_matches(original.status), 6)) if queued else False
        cleanup = runtime.stop(timeout_seconds=2)
        if target is not None and initial:
            audio_restored = False
            try:
                if audio_control.verify_identity(target):
                    sessions = tuple(item for item in audio_control.enumerate_sessions()
                                     if item.pid == target.pid and item.key in initial)
                    audio_restored = len(sessions) == len(initial)
                    for session in sessions:
                        volume, muted = initial[session.key]
                        session.set_volume(volume)
                        session.set_mute(muted)
                        audio_restored = audio_restored and abs(session.get_volume() - volume) < .001 and session.get_mute() == muted
                    del sessions
            except Exception as error:
                errors.append({"stage": "audio-restore", "type": type(error).__name__, "error": str(error)})
        if child is not None:
            exited = _stop_fixture(child, root)
        result.update(steps=steps, errors=errors, original=_media_session_payload(original) if original else None,
                      playback_state_restored=playback_restored, audio_restored=audio_restored,
                      cleanup_ok=cleanup, fixture_exited=exited)
    result["ok"] = bool(result["supported"] and len(steps) == 5 and all(row["ok"] for row in steps)
                        and not errors and playback_restored and audio_restored and cleanup and exited)
    return result


def _firefox_path() -> Path | None:
    """설치 경로만 확인한다. Firefox 프로필·쿠키·자격 증명은 읽지 않는다."""
    candidates = [Path(os.environ[name]) / "Mozilla Firefox/firefox.exe"
                  for name in ("ProgramFiles", "ProgramFiles(x86)") if os.environ.get(name)]
    import winreg
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\firefox.exe") as key:
                candidates.append(Path(winreg.QueryValue(key, None)))
        except OSError:
            pass
    return next((path for path in candidates if path.name.casefold() == "firefox.exe" and path.is_file()), None)


def _write_quiet_wave(path: Path, seconds: int = 1) -> None:
    import math
    import struct
    import wave
    with wave.open(str(path), "wb") as stream:
        stream.setparams((1, 2, 22050, 22050 * seconds, "NONE", "not compressed"))
        stream.writeframes(b"".join(struct.pack("<h", int(32 * math.sin(2 * math.pi * 220 * index / 22050)))
                                    for index in range(22050 * seconds)))


def _firefox_fixture_files(root: Path, marker: str) -> tuple[Path, Path]:
    root.mkdir(parents=True)
    profile = root / "profile"
    profile.mkdir()
    prefs = {"media.autoplay.default": 0, "dom.allow_scripts_to_close_windows": True,
             "browser.aboutwelcome.enabled": False, "browser.shell.checkDefaultBrowser": False,
             "browser.startup.homepage_override.mstone": "ignore", "browser.tabs.warnOnClose": False}
    (profile / "user.js").write_text("\n".join(
        f"user_pref({json.dumps(name)}, {json.dumps(value)});" for name, value in prefs.items()), encoding="utf-8")
    _write_quiet_wave(root / "fixture.wav", seconds=20)
    html = root / "media.html"
    html.write_text("""<!doctype html><meta charset="utf-8"><title>HomeworkHelper media QA</title>
<p>HomeworkHelper의 격리된 Firefox 미디어 검수입니다. 잠시 후 이 창만 닫힙니다.</p>
<audio id="sample" src="fixture.wav" autoplay loop></audio><script>
const audio = document.getElementById('sample');
if ('mediaSession' in navigator) navigator.mediaSession.metadata = new MediaMetadata({title: MARKER, artist: 'HomeworkHelper QA'});
audio.play().then(() => { setTimeout(() => audio.pause(), 8000); setTimeout(() => window.close(), 16000); })
.catch(error => { document.body.append(String(error)); setTimeout(() => window.close(), 1000); });
</script>""".replace("MARKER", json.dumps(marker)), encoding="utf-8")
    return profile, html


def _visible_firefox_windows(pids: set[int]) -> list[dict]:
    import win32gui
    import win32process
    windows = []
    def collect(hwnd, _unused):
        pid = win32process.GetWindowThreadProcessId(hwnd)[1]
        if (pid in pids and win32gui.IsWindowVisible(hwnd)
                and win32gui.GetClassName(hwnd) == "MozillaWindowClass"):
            rect = win32gui.GetWindowRect(hwnd)
            if rect[2] > rect[0] and rect[3] > rect[1]:
                windows.append({"hwnd": int(hwnd), "pid": pid, "rect": list(rect),
                                "title": win32gui.GetWindowText(hwnd)})
    win32gui.EnumWindows(collect, None)
    return windows


def _firefox_window_owner(profile_owner, executable: Path, started: float):
    """고유 profile을 소유한 OS lineage 안에서 실제 보이는 Firefox 창의 owner를 고른다."""
    expected_context = _process_context(os.getpid())
    processes, details = {}, []
    for process in [profile_owner, *profile_owner.children(recursive=True)]:
        if (_path_key(process.exe()) != _path_key(executable) or process.create_time() < started - .1
                or _process_context(process.pid) != expected_context):
            continue
        if (process.pid != profile_owner.pid and process.ppid() != profile_owner.pid
                and not any(parent.pid == profile_owner.pid for parent in process.parents())):
            continue
        processes[process.pid] = process
        details.append({"pid": process.pid, "parent_pid": process.ppid(),
                        "created": process.create_time(), "path": process.exe()})
    windows = _visible_firefox_windows(set(processes))
    if not windows:
        return None
    selected = max(windows, key=lambda row: (row["rect"][2] - row["rect"][0]) * (row["rect"][3] - row["rect"][1]))
    return processes[selected["pid"]], {"profile_owner_pid": profile_owner.pid,
                                         "window_pid": selected["pid"], "hwnd": selected["hwnd"],
                                         "windows": windows, "lineage": details}


def _launch_firefox(executable: Path, root: Path, marker: str):
    import psutil
    profile, html = _firefox_fixture_files(root, marker)
    started = time.time()
    launcher = subprocess.Popen([str(executable), "--no-remote", "--profile", str(profile), html.as_uri()],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    def owned():
        for candidate in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                command = candidate.info.get("cmdline") or []
                if "--profile" not in command:
                    continue
                index = command.index("--profile")
                if index + 1 >= len(command) or _path_key(command[index + 1]) != _path_key(profile):
                    continue
                if (_path_key(candidate.exe()) != _path_key(executable) or candidate.create_time() < started - .1
                        or "--no-remote" not in command or html.as_uri() not in command):
                    continue
                if (candidate.pid != launcher.pid and candidate.ppid() != launcher.pid
                        and not any(parent.pid == launcher.pid for parent in candidate.parents())):
                    continue
                if _process_context(candidate.pid) != _process_context(os.getpid()):
                    continue
                selected = _firefox_window_owner(candidate, executable, started)
                if selected is None:
                    continue
                actual, diagnostics = selected
                browser = _FixtureProcess(launcher, actual)
                browser.diagnostics = {"launcher_pid": launcher.pid, **diagnostics}
                return browser
            except (psutil.Error, ValueError):
                continue
        return None
    browser = _wait(owned, 8)
    if browser is None:
        raise RuntimeError(f"Firefox 전용 프로필의 실행 identity를 확인하지 못했습니다: {root}")
    return browser


def _close_firefox(browser, diagnostics=None) -> bool:
    """검증한 새 프로필 main PID의 창만 WM_CLOSE로 정상 종료한다."""
    import psutil
    import win32gui
    import win32process
    try:
        if not browser.process.is_running():
            browser.wait(timeout=1)
            return True
        children = browser.process.children(recursive=True)
        def close(hwnd, _unused):
            if win32process.GetWindowThreadProcessId(hwnd)[1] == browser.pid:
                win32gui.PostMessage(hwnd, 0x0010, 0, 0)
        win32gui.EnumWindows(close, None)
        deadline = time.monotonic() + 8
        browser.wait(timeout=8)
        for process in children:
            process.wait(timeout=max(.01, deadline - time.monotonic()))
        return True
    except Exception as error:
        if diagnostics is not None:
            diagnostics.append({"stage": "firefox-close", "type": type(error).__name__, "error": str(error)})
        return False


def _firefox(result_dir: Path) -> dict:
    from src.core.game_focus import WindowsGameFocusNative
    from src.core.media_center import MediaCenterRuntime, MediaOptions
    from src.core.media_sessions import is_spotify_session
    executable = _firefox_path()
    result = {"ok": False, "supported": False, "scenario": "firefox",
              "limits": ["로컬 HTML/WAV와 새 전용 프로필만 사용합니다. 운영 Firefox 프로필·확장·원격 디버깅은 사용하지 않습니다.",
                         "외부 콘텐츠는 요청하지 않지만 Firefox 자체 배경 네트워크의 전역 차단을 보장하는 검사는 아닙니다."]}
    if executable is None:
        result["reason"] = "설치된 Firefox 실행파일 경로를 확인하지 못했습니다."
        return result
    trace_start = time.monotonic()
    trace = deque(maxlen=400)
    def on_change(snapshot):
        trace.append((time.monotonic(), snapshot))
    runtime = MediaCenterRuntime(on_change=on_change, spotify_launcher=lambda: False)
    native = WindowsGameFocusNative()
    original_foreground = native.foreground()
    original, browser, steps, errors = None, None, [], []
    seen_ids, replacements = set(), []
    restored, closed, cleanup = False, True, True
    marker = "HH-media-QA-" + uuid.uuid4().hex[:12]
    deadline = time.monotonic() + 70
    def wait(predicate, seconds):
        # 이 함수의 모든 predicate는 immutable runtime snapshot/trace만 읽는다.
        # 마지막 sleep 동안 도착한 결과를 deadline 검사 때문에 버리지 않는다.
        value = _wait(predicate, max(0, min(seconds, deadline - time.monotonic())))
        return value or predicate()
    def current_spotify(snapshot):
        # QA 관측·명시적 복원용 재확인이다. 제품에 stale ID 재매핑 경로를 넣지 않는다.
        candidates = tuple(item for item in snapshot.sessions if is_spotify_session(item))
        if len(candidates) != 1:
            return None
        candidate = candidates[0]
        if ((candidate.app_id.casefold(), candidate.title, candidate.artist)
                != (original.app_id.casefold(), original.title, original.artist)):
            return None
        if candidate.session_id not in seen_ids:
            seen_ids.add(candidate.session_id)
            replacements.append({"at_ms": round((time.monotonic() - trace_start) * 1000, 2),
                                 "original_id": original.session_id, "current_id": candidate.session_id,
                                 "app_id": candidate.app_id, "title": candidate.title, "artist": candidate.artist})
        return candidate
    def bgm(status, snapshot=None):
        selected = current_spotify(runtime.snapshot if snapshot is None else snapshot)
        return selected is not None and selected.status == status
    def simultaneous(snapshot, firefox_status):
        return (any(item.title == marker and item.status == firefox_status for item in snapshot.sessions)
                and bgm("paused", snapshot))
    def require(name, predicate, seconds, *, since=None):
        matched = []
        def check():
            samples = [(time.monotonic(), runtime.snapshot)]
            if since is not None:
                samples.extend((timestamp, snapshot) for timestamp, snapshot in trace.copy() if timestamp >= since)
            for timestamp, snapshot in samples:
                if predicate(snapshot):
                    matched[:] = [timestamp, snapshot]
                    return True
            return False
        ok = bool(wait(check, seconds))
        steps.append({"name": name, "ok": ok,
                      "at_ms": round(((matched[0] if matched else time.monotonic()) - trace_start) * 1000, 2),
                      "snapshot": _media_snapshot_payload(matched[1] if matched else runtime.snapshot)})
        if not ok:
            raise RuntimeError(f"Firefox 실제 미디어 상태를 확인하지 못했습니다: {name}")
    try:
        if not runtime.start(MediaOptions(False, False, False)):
            result["reason"] = runtime.snapshot.error or "미디어 worker 시작 실패"
            return result
        wait(lambda: runtime.snapshot.sessions or runtime.snapshot.error, 5)
        spotify = tuple(item for item in runtime.snapshot.sessions if is_spotify_session(item))
        if len(spotify) != 1 or spotify[0].status not in {"playing", "paused"}:
            result["reason"] = "명확한 기존 playing/paused Spotify 세션 하나가 필요합니다."
            return result
        original = spotify[0]
        seen_ids.add(original.session_id)
        if any(item.status == "playing" and item.session_id != original.session_id for item in runtime.snapshot.sessions):
            result["reason"] = "다른 미디어가 재생 중이므로 검수하지 않았습니다."
            return result
        result["supported"] = True
        runtime.configure(MediaOptions(True, False, False))
        require("bgm-playing-baseline", lambda snapshot: bgm("playing", snapshot), 6)
        closed = False  # 준비 identity 미확인도 browser 종료 확인 실패로 보고한다.
        launched_at = time.monotonic()
        browser = _launch_firefox(executable, result_dir / "media-fixture" / marker, marker)
        result["fixture_pid"] = browser.pid
        result["fixture_identity"] = getattr(browser, "diagnostics", {})
        require("firefox-playing-pauses-bgm", lambda snapshot: simultaneous(snapshot, "playing"), 12, since=launched_at)
        require("firefox-paused-keeps-bgm-hold", lambda snapshot: simultaneous(snapshot, "paused") and snapshot.media_hold,
                12, since=trace_start + steps[-1]["at_ms"] / 1000)
        closed = _close_firefox(browser, errors)
        require("firefox-session-ended-keeps-bgm-hold", lambda snapshot: not any(
            item.title == marker for item in snapshot.sessions) and bgm("paused", snapshot) and snapshot.media_hold, 8)
        stable_until = time.monotonic() + 1
        stable = True
        while time.monotonic() < stable_until:
            stable = stable and bgm("paused") and runtime.snapshot.media_hold
            time.sleep(.05)
        steps.append({"name": "after-close-no-replay", "ok": stable})
    except Exception as error:
        errors.append({"type": type(error).__name__, "error": str(error)})
    finally:
        if browser is not None:
            closed = _close_firefox(browser, errors)
        runtime.configure(MediaOptions(False, False, False))
        if original is not None and result["supported"]:
            selected = current_spotify(runtime.snapshot)
            queued = selected is not None and runtime.request("play" if original.status == "playing" else "pause", selected.session_id)
            restored = bool(wait(lambda: bgm(original.status), 6)) if queued else False
        cleanup = runtime.stop(timeout_seconds=2)
        result.update(steps=steps, errors=errors, original=_media_session_payload(original) if original else None,
                      playback_state_restored=restored, fixture_closed=closed, cleanup_ok=cleanup,
                      foreground_before=original_foreground, foreground_after=native.foreground(),
                      spotify_id_replacements=replacements,
                      trace=[{"at_ms": round((timestamp - trace_start) * 1000, 2), "snapshot": _media_snapshot_payload(snapshot)}
                             for timestamp, snapshot in trace.copy()])
    result["ok"] = bool(result["supported"] and len(steps) == 5 and all(row["ok"] for row in steps)
                        and not errors and restored and closed and cleanup)
    return result


def _focus_compare_registered(source_appdata: Path):
    path = source_appdata / "HomeworkHelper/homework_helper_data/app_data.db"
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2) as db:
        return list(db.execute("SELECT id,name,monitoring_path FROM managed_processes"))


def _focus_compare_target(source_appdata: Path, registered=None, *, allow_empty=False):
    import psutil
    from src.core.game_audio import GameAudioTarget
    from src.core.process_monitor import _normalize_process_path
    from src.utils.audio_control import verify_identity
    registered = _focus_compare_registered(source_appdata) if registered is None else registered
    matches = []
    for process in psutil.process_iter(["pid", "exe", "create_time"]):
        for process_id, name, executable in registered:
            if (process.info.get("exe") and executable
                    and _normalize_process_path(process.info["exe"]) == _normalize_process_path(executable)):
                target = GameAudioTarget(process_id, process.pid, process.info["create_time"], executable, False, None)
                if verify_identity(target):
                    matches.append((target, name))
    if not matches and allow_empty:
        return None
    if len(matches) != 1:
        raise ValueError(f"실행 중인 등록 게임이 정확히 하나여야 합니다: 관측={len(matches)}")
    return matches[0]


def _focus_compare_context(target) -> dict:
    import ctypes
    from ctypes import wintypes as wt
    import win32gui
    import win32process
    from src.core.game_focus import WindowsGameFocusNative
    from src.gui.runtime_logging import redact_sensitive_text
    def token_context(pid):
        import win32api
        import win32security as security
        try:
            sid, session = _process_context(pid)
            handle = win32api.OpenProcess(0x1000, False, pid)
            try:
                token = security.OpenProcessToken(handle, security.TOKEN_QUERY)
                try:
                    elevated = bool(security.GetTokenInformation(token, security.TokenElevation))
                finally:
                    token.Close()
            finally:
                handle.Close()
            return {"pid": pid, "sid": sid, "session_id": session, "elevated": elevated}
        except Exception as error:
            return {"pid": pid, "error_type": type(error).__name__, "error": redact_sensitive_text(error)}
    class LastInput(ctypes.Structure):
        _fields_ = [("cbSize", wt.UINT), ("dwTime", wt.DWORD)]
    class GuiInfo(ctypes.Structure):
        _fields_ = [("cbSize", wt.DWORD), ("flags", wt.DWORD), *[(name, wt.HWND) for name in (
            "hwndActive", "hwndFocus", "hwndCapture", "hwndMenuOwner", "hwndMoveSize", "hwndCaret")], ("rcCaret", wt.RECT)]
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LastInput)]
    user32.GetLastInputInfo.restype = wt.BOOL
    user32.GetGUIThreadInfo.argtypes = [wt.DWORD, ctypes.POINTER(GuiInfo)]
    user32.GetGUIThreadInfo.restype = wt.BOOL
    dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
    dwmapi.DwmGetWindowAttribute.argtypes = [wt.HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]
    dwmapi.DwmGetWindowAttribute.restype = ctypes.c_long
    info = LastInput(ctypes.sizeof(LastInput), 0)
    input_ok = bool(user32.GetLastInputInfo(ctypes.byref(info)))
    foreground = WindowsGameFocusNative().foreground()
    foreground_thread = win32process.GetWindowThreadProcessId(foreground[1])[0] if foreground[1] else 0
    gui = GuiInfo()
    gui.cbSize = ctypes.sizeof(GuiInfo)
    gui_ok = bool(user32.GetGUIThreadInfo(foreground_thread, ctypes.byref(gui)))
    windows = []
    def collect(hwnd, _unused):
        matched = False
        try:
            thread, pid = win32process.GetWindowThreadProcessId(hwnd)
            if target is not None and pid == target.pid:
                matched = True
                cloaked = wt.DWORD()
                cloak_result = dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
                windows.append({"hwnd": int(hwnd), "thread_id": thread, "visible": bool(win32gui.IsWindowVisible(hwnd)),
                                "minimized": bool(win32gui.IsIconic(hwnd)), "rect": list(win32gui.GetWindowRect(hwnd)),
                                "owner": int(win32gui.GetWindow(hwnd, 4) or 0),
                                "style": win32gui.GetWindowLong(hwnd, -16), "ex_style": win32gui.GetWindowLong(hwnd, -20),
                                "cloaked": int(cloaked.value) if cloak_result == 0 else None,
                                "cloaked_hresult": f"0x{cloak_result & 0xffffffff:08x}",
                                "class": win32gui.GetClassName(hwnd),
                                "title": redact_sensitive_text(win32gui.GetWindowText(hwnd))})
        except Exception as error:
            # 창 교체 중의 HWND 소멸을 전체 125초 관찰 실패로 확대하지 않는다.
            if matched:
                windows.append({"hwnd": int(hwnd), "gone": True, "error_type": type(error).__name__})
    win32gui.EnumWindows(collect, None)
    return {"pid": os.getpid(), "native_thread_id": threading.get_native_id(), "foreground": list(foreground),
            "caller_token": token_context(os.getpid()), "target_token": token_context(target.pid) if target else None,
            "foreground_thread_id": foreground_thread, "last_input_ok": input_ok, "last_input_tick": info.dwTime,
            "gui_info_ok": gui_ok, "gui_active": int(gui.hwndActive or 0), "gui_focus": int(gui.hwndFocus or 0),
            "target_windows": windows}


def _focus_compare_startup(source_appdata: Path, result_dir: Path):
    from src.core.game_focus import AutoFocusTracker, WindowsGameFocusNative
    started, original, events = time.monotonic(), _focus_compare_context(None), []
    registered, native = _focus_compare_registered(source_appdata), WindowsGameFocusNative()
    target, name, prior = None, None, None
    ready_window, ready_since = None, None
    def progress(kind, **values):
        events.append({"at_ms": round((time.monotonic() - started) * 1000, 2), "kind": kind, **values})
        path = result_dir / "focus-progress.json"
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"scenario": "focus-compare", "finished": False, "phase": "startup",
            "target": asdict(target) if target else None, "name": name, "events": events}, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
    class TracedNative:
        foreground = native.foreground
        window = native.window
        is_window_hidden = native.is_window_hidden
        is_related_foreground = native.is_related_foreground
        def focus(self, selected, hwnd=None):
            before = _focus_compare_context(selected)
            accepted = native.focus(selected, hwnd)
            time.sleep(.25)
            progress("startup-focus-request", accepted=accepted, before=before, after_250ms=_focus_compare_context(selected))
            return accepted
    tracker = AutoFocusTracker(started_at_wall=time.time(), native=TracedNative())
    tracker.tick((), *native.foreground(), started, os.getpid())
    progress("waiting-for-registered-game", maximum_seconds=60)
    with _focus_diagnostics() as diagnostics:
        while time.monotonic() - started < 60:
            matched = _focus_compare_target(source_appdata, registered, allow_empty=True)
            if matched:
                target, name = matched
            foreground = native.foreground()
            hwnd = native.window(target) if target is not None else None
            ready = hwnd is not None
            candidate = (target.pid, hwnd) if ready else None
            if candidate != ready_window:
                ready_window, ready_since = candidate, time.monotonic() if ready else None
            if prior != (foreground, target.pid if target else None, ready):
                progress("startup-state", foreground=list(foreground), window_ready=ready, context=_focus_compare_context(target))
                prior = (foreground, target.pid if target else None, ready)
            tracker.tick((target,) if matched else (), *foreground, time.monotonic(), os.getpid())
            if ready and time.monotonic() - ready_since >= AutoFocusTracker.WINDOW_STABLE_SECONDS:
                break
            time.sleep(.2)
    tracker.cancel()
    progress("startup-finished", diagnostics=diagnostics)
    if target is None:
        raise ValueError("60초 안에 실행 중인 등록 게임 하나를 확인하지 못했습니다.")
    return target, name, started, original, events


def _focus_compare(source_appdata: Path, result_dir: Path) -> dict:
    from PySide6.QtCore import QObject, QEvent, QEventLoop, QTimer, Qt, Signal
    from PySide6.QtWidgets import QApplication, QLabel, QPushButton, QVBoxLayout, QWidget
    from src.utils.audio_control import verify_identity
    from src.utils.windows import focus_managed_process_window
    from src.gui.runtime_logging import redact_sensitive_text
    target, name, started, original, records = _focus_compare_startup(source_appdata, result_dir)
    app = QApplication.instance() or QApplication([])
    loop, workers = QEventLoop(), []
    busy, closing = False, False
    progress_path = result_dir / "focus-progress.json"
    def publish(row=None):
        if row is not None:
            records.append({"at_ms": round((time.monotonic() - started) * 1000, 2), **row})
        value = {"scenario": "focus-compare", "target": asdict(target), "name": name, "events": records,
                 "panel_pid": os.getpid(), "finished": closing}
        temporary = progress_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        temporary.replace(progress_path)
    class Panel(QWidget):
        def closeEvent(self, event):
            nonlocal closing
            closing = True
            event.accept()
            loop.quit()
    class Signals(QObject):
        done = Signal(object)
    class ClickEvents(QObject):
        def eventFilter(self, watched, event):
            if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease,
                                QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
                row = {"kind": "button_input_event", "button": watched.objectName(),
                       "event": event.type().name, "spontaneous": event.spontaneous()}
                row.update({"key": event.key(), "auto_repeat": event.isAutoRepeat()} if event.type() in (
                    QEvent.Type.KeyPress, QEvent.Type.KeyRelease) else {"mouse_button": event.button().name})
                publish(row)
            return False
    panel, signals, clicks = Panel(), Signals(), ClickEvents()
    panel.setWindowTitle("HomeworkHelper · 게임 포커스 비교")
    panel.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    layout = QVBoxLayout(panel)
    status = QLabel(f"대상: {name} · PID {target.pid}\n먼저 입력 없이 GUI/worker 시도를 기록합니다.")
    layout.addWidget(status)
    buttons = []
    def enable(value):
        for button in buttons:
            button.setEnabled(value)
    def finished(row):
        nonlocal busy
        if closing:
            return
        busy = False
        publish(row)
        if row["label"] == "background-gui":
            attempt("background-worker", True, False)
        else:
            enable(True)
            status.setText(f"대상: {name} · PID {target.pid}\n자동 비교 완료. 실제 버튼 클릭으로 비교하세요.")
    signals.done.connect(finished, Qt.ConnectionType.QueuedConnection)
    def attempt(label, worker, manual):
        nonlocal busy
        if closing or busy:
            return
        busy = True
        enable(False)
        def call():
            row = {"kind": "attempt", "label": label, "manual": manual, "thread": "worker" if worker else "gui"}
            try:
                row["before"] = _focus_compare_context(target)
                row["input_changed_since_start"] = row["before"]["last_input_tick"] != original["last_input_tick"]
                row["identity_valid"] = verify_identity(target)
                with _focus_diagnostics() as diagnostics:
                    row["accepted"] = (focus_managed_process_window(target.pid, target.create_time, target.path)
                                       if row["identity_valid"] else False)
                row["diagnostics"] = diagnostics
            except Exception as error:
                row.update(accepted=False, error=redact_sensitive_text(error), error_type=type(error).__name__)
            def after():
                try:
                    row["after_250ms"] = _focus_compare_context(target)
                    row["foreground_observed"] = row["after_250ms"]["foreground"][0] == target.pid
                except Exception as error:
                    row.update(foreground_observed=False, observation_error=redact_sensitive_text(error))
                signals.done.emit(row)
            if worker:
                time.sleep(.25)
                after()
            else:
                QTimer.singleShot(250, after)
        if worker:
            thread = threading.Thread(target=call, daemon=True, name="FocusCompareWorker")
            workers.append(thread)
            thread.start()
        else:
            call()
    def manual(label, worker, delayed=False):
        nonlocal busy
        publish({"kind": "button_activated", "label": label, "panel_active": panel.isActiveWindow()})
        if delayed:
            panel.raise_()
            panel.activateWindow()
            busy = True
            enable(False)
            def delayed_call():
                nonlocal busy
                busy = False
                attempt(label, worker, True)
            QTimer.singleShot(2000, delayed_call)
        else:
            attempt(label, worker, True)
    for label, text, worker, delayed in (("manual-gui", "GUI에서 게임 포커스", False, False),
                                        ("manual-worker", "worker에서 게임 포커스", True, False),
                                        ("manual-delayed-worker", "QA 활성화 후 2초 뒤 worker", True, True)):
        button = QPushButton(text)
        button.setObjectName(label)
        button.installEventFilter(clicks)
        button.clicked.connect(lambda _checked=False, key=label, work=worker, delay=delayed: manual(key, work, delay))
        buttons.append(button)
        layout.addWidget(button)
    enable(False)
    panel.resize(460, 220)
    panel.show()
    publish({"kind": "ready", "panel_hwnd": int(panel.winId()), "context": original})
    QTimer.singleShot(0, lambda: attempt("background-gui", False, False))
    QTimer.singleShot(max(1, round((85 - (time.monotonic() - started)) * 1000)), panel.close)
    loop.exec()
    panel.hide()
    for thread in workers:
        thread.join(timeout=1)
    worker_stopped = not any(thread.is_alive() for thread in workers)
    restored = _restore_foreground(original["foreground"][1]) if worker_stopped else False
    publish({"kind": "finished", "worker_stopped": worker_stopped, "foreground_restored": restored})
    return {"ok": worker_stopped, "supported": True, "scenario": "focus-compare", "target": asdict(target),
            "name": name, "events": records, "foreground_restored": restored, "worker_stopped": worker_stopped,
            "progress_file": str(progress_path), "limits": ["이 비교는 현재 한 게임의 포커스 요청 근거이며 개별 수락을 성공으로 확대하지 않습니다."]}


def _focus_lifecycle_owner(original: dict) -> dict:
    """시작 전경이 검증된 설치 GUI인 경우에만 그 UI 수명주기를 재현한다."""
    import psutil
    from src.gui.runtime_logging import redact_sensitive_text
    own = os.getpid()
    result = {"qa_pid": own, "ui_owner_pid": own, "reason": "qa-default"}
    candidate = original["foreground"][0]
    if not candidate:
        return result
    expected = ntpath.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                           "HomeworkHelper", "homework_helper.exe")
    try:
        process = psutil.Process(candidate)
        executable = process.exe()
        if _path_key(executable) != _path_key(expected):
            result["reason"] = "initial-foreground-not-installed-gui"
            return result
        context = _process_context(candidate)
        if context != _process_context(own):
            result["reason"] = "initial-foreground-other-user-session"
            return result
        result.update(ui_owner_pid=candidate, reason="verified-installed-initial-gui",
                      path=executable, created=process.create_time(), sid=context[0], session_id=context[1])
    except Exception as error:
        result.update(reason="initial-gui-unverified", error_type=type(error).__name__, error=redact_sensitive_text(error))
    return result


def _focus_lifecycle(source_appdata: Path, result_dir: Path) -> dict:
    """최초 identity 이후 125초 동안 실제 tracker와 창 교체를 계속 관찰한다."""
    import psutil
    from src.core.game_focus import AutoFocusTracker, WindowsGameFocusNative
    from src.gui.runtime_logging import redact_sensitive_text
    native, registered = WindowsGameFocusNative(), _focus_compare_registered(source_appdata)
    started, original = time.monotonic(), _focus_compare_context(None)
    ownership = _focus_lifecycle_owner(original)
    ui_owner_pid = ownership["ui_owner_pid"]
    target, name, first_seen, prior, foreground_info = None, None, None, None, None
    events, requests, errors = [], [], []
    path = result_dir / "focus-lifecycle-progress.json"
    def publish(kind, **values):
        events.append({"at_ms": round((time.monotonic() - started) * 1000, 2), "kind": kind, **values})
        value = {"scenario": "focus-lifecycle", "target": asdict(target) if target else None,
                 "name": name, "events": events, "ownership": ownership, "finished": kind == "finished"}
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)
    class TracedNative:
        foreground = native.foreground
        window = native.window
        is_window_hidden = native.is_window_hidden
        is_related_foreground = native.is_related_foreground
        def focus(self, selected, hwnd=None):
            before = _focus_compare_context(selected)
            accepted = native.focus(selected, hwnd)
            time.sleep(.25)
            row = {"target": asdict(selected), "hwnd": hwnd, "accepted": accepted,
                   "before": before, "after_250ms": _focus_compare_context(selected)}
            requests.append(row)
            publish("focus-request", **row)
            return accepted
    tracker = AutoFocusTracker(started_at_wall=time.time(), native=TracedNative())
    tracker.tick((), *native.foreground(), started, ui_owner_pid)
    publish("waiting-for-registered-game", maximum_seconds=20, observe_after_identity_seconds=125)
    with _focus_diagnostics() as diagnostics:
        try:
            while time.monotonic() < (started + 20 if first_seen is None else first_seen + 125):
                matched = _focus_compare_target(source_appdata, registered, allow_empty=True)
                target, name = matched if matched else (None, None)
                if target is not None and first_seen is None:
                    first_seen = time.monotonic()
                context = _focus_compare_context(target)
                foreground = context["foreground"]
                related = native.is_related_foreground(target, foreground[0]) if target is not None else False
                if foreground_info is None or foreground_info.get("pid") != foreground[0]:
                    foreground_info = {"pid": foreground[0]}
                    if foreground[0]:
                        try:
                            process = psutil.Process(foreground[0])
                            sid, session = _process_context(foreground[0])
                            foreground_info.update(path=process.exe(), created=process.create_time(), sid=sid, session_id=session)
                        except Exception as error:
                            foreground_info.update(error_type=type(error).__name__, error=redact_sensitive_text(error))
                state = {"target": asdict(target) if target else None, "context": context,
                         "related_foreground": related, "foreground_process": foreground_info}
                fingerprint = json.dumps(state, sort_keys=True)
                if fingerprint != prior:
                    publish("state", **state)
                    prior = fingerprint
                tracker.tick((target,) if target else (), *foreground, time.monotonic(), ui_owner_pid)
                time.sleep(.25)
            # 대기 마지막 sleep 사이에 경계를 넘긴 경우도 실제 제품에 한 번 전달한다.
            tracker.tick((target,) if target else (), *native.foreground(), time.monotonic(), ui_owner_pid)
            publish("deadline-observation", context=_focus_compare_context(target),
                    seconds_after_identity=time.monotonic() - first_seen if first_seen is not None else None)
        except Exception as error:
            errors.append({"error_type": type(error).__name__, "error": redact_sensitive_text(error)})
        finally:
            tracker.cancel()
    publish("finished", diagnostics=diagnostics, errors=errors)
    return {"ok": first_seen is not None and not errors, "supported": True, "scenario": "focus-lifecycle",
            "events": events, "requests": requests, "errors": errors, "original": original, "ownership": ownership,
            "progress_file": str(path), "limits": ["입력 tick 변화는 OS 세션 입력 관측이며 사용자 의도·물리 입력을 증명하지 않습니다.",
            "진단 완료와 자동 포커스 성공은 구분하며 게임 실행·종료·키 입력·창 생성은 하지 않습니다."]}


def _uia_focus_attempt(target) -> dict:
    import comtypes  # main thread import precedes explicit worker MTA initialization.
    from src.utils.audio_control import verify_identity
    from src.gui.runtime_logging import redact_sensitive_text
    row, cancelled = {"target": asdict(target), "accepted": False}, threading.Event()
    def worker():
        initialized = False
        try:
            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
            initialized = True
            from comtypes import client
            row["before"] = _focus_compare_context(target)
            if not verify_identity(target):
                raise ValueError("게임 실행 identity가 변경되어 UIA 요청을 거부했습니다.")
            windows = [window for window in row["before"]["target_windows"] if window.get("visible")
                       and window["rect"][2] > window["rect"][0] and window["rect"][3] > window["rect"][1]]
            if len(windows) != 1:
                raise ValueError(f"UIA 대상의 보이는 최상위 창이 정확히 하나여야 합니다: {len(windows)}")
            row["hwnd"] = windows[0]["hwnd"]
            module = client.GetModule("UIAutomationCore.dll")
            automation = client.CreateObject("{E22AD333-B25F-460C-83D0-0581107395C9}", interface=module.IUIAutomation2)
            automation.ConnectionTimeout, automation.TransactionTimeout = 500, 1500
            row["timeouts_ms"] = {"connection": automation.ConnectionTimeout, "transaction": automation.TransactionTimeout}
            element = automation.ElementFromHandle(row["hwnd"])
            if cancelled.is_set() or not verify_identity(target):
                raise ValueError("UIA 요청이 취소됐거나 실행 identity가 변경됐습니다.")
            element.SetFocus()  # 정상 반환과 실제 전경 전환은 별도 관측한다.
            row["accepted"] = True
        except Exception as error:
            row.update(error_type=type(error).__name__, error=redact_sensitive_text(error))
            if hasattr(error, "hresult"):
                row["hresult"] = f"0x{error.hresult & 0xffffffff:08x}"
        finally:
            if initialized:
                for delay, field in ((.25, "after_250ms"), (.75, "after_1s")):
                    time.sleep(delay)
                    try:
                        row[field] = _focus_compare_context(target)
                        row[field]["foreground_observed"] = row[field]["foreground"][0] == target.pid
                    except Exception as error:
                        row[field] = {"error_type": type(error).__name__, "error": redact_sensitive_text(error)}
                element = automation = None  # release COM interfaces before uninitialization.
                comtypes.CoUninitialize()
    thread = threading.Thread(target=worker, name="FocusUiaMta", daemon=True)
    thread.start()
    thread.join(timeout=8)
    cancelled.set()
    row["worker_stopped"] = not thread.is_alive()
    return row


def _focus_uia(source_appdata: Path, result_dir: Path) -> dict:
    import psutil
    from src.core.game_audio import GameAudioTarget
    target, name = _focus_compare_target(source_appdata)
    original = _focus_compare_context(target)
    attempts, child, root, exited, restored = [], None, None, True, False
    try:
        attempts.append({"kind": "registered-game", **_uia_focus_attempt(target)})
        if attempts[-1]["worker_stopped"]:
            child, root, _ready = _spawn_fixture(result_dir, "focus")
            process = psutil.Process(child.pid)
            fixture = GameAudioTarget("media-uia-fixture", child.pid, process.create_time(), process.exe(), False, None)
            attempts.append({"kind": "owned-normal-fixture", **_uia_focus_attempt(fixture)})
    finally:
        if child is not None:
            exited = _stop_fixture(child, root)
        stopped = all(row["worker_stopped"] for row in attempts)
        restored = _restore_foreground(original["foreground"][1]) if stopped else False
    return {"ok": len(attempts) == 2 and stopped and exited, "supported": True, "scenario": "focus-uia",
            "name": name, "original": original, "attempts": attempts, "fixture_exited": exited,
            "foreground_restored": restored, "limits": ["ok는 진단 완료이며 UIA 수락·실제 전경 전환은 각 관측으로 판단합니다.",
            "게임 실행·종료, 가짜 입력, UIAccess·권한·Windows 설정 변경과 제품 fallback은 없습니다."]}


def _fixture_main(kind: str, root: Path) -> int:
    """최대 90초의 소유 fixture. 프로덕션 모듈·DB·설정을 읽지 않는다."""
    def ready(**values):
        path = root / "ready.tmp"
        path.write_text(json.dumps({"pid": os.getpid(), **values}), encoding="utf-8")
        path.replace(root / "ready.json")
    if kind == "audio":
        import winsound
        wav = root / "fixture.wav"
        _write_quiet_wave(wav)
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
    original_environment = _isolated_environment(result_dir)
    sys.path.insert(0, str(repo))
    if scenario == "observe":
        return _observe()
    if scenario in SPOTIFY_WINDOW_SCENARIOS:
        if scenario != "spotify-window-observe":
            return _spotify_window_observe(source_appdata, original_environment["LOCALAPPDATA"], scenario)
        return _spotify_window_observe(source_appdata, original_environment["LOCALAPPDATA"])
    if scenario == "preview":
        return _preview(source_appdata, result_dir)
    if scenario == "audio":
        return _audio(result_dir)
    if scenario == "focus":
        return _focus(result_dir)
    if scenario == "prepare-spotify":
        return _prepare_spotify()
    if scenario == "triggers":
        return _triggers(result_dir)
    if scenario == "firefox":
        return _firefox(result_dir)
    if scenario == "focus-compare":
        return _focus_compare(source_appdata, result_dir)
    if scenario == "focus-uia":
        return _focus_uia(source_appdata, result_dir)
    if scenario == "focus-lifecycle":
        return _focus_lifecycle(source_appdata, result_dir)
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
