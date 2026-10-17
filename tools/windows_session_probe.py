"""Bounded, non-activating desktop observation or one authorized OBS normal close."""
from __future__ import annotations

import argparse
import ctypes
import json
from pathlib import Path
import sys
import time


def desktop(repo: Path, duration: int) -> dict:
    sys.path.insert(0, str(repo))
    import psutil
    import pywintypes
    import win32api
    import win32gui
    import win32process
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from src.utils.windows import get_visible_taskbar_work_area
    app = QApplication([])  # No shown widget, focus changes or product initialization.
    installed = Path(r"C:\Program Files\HomeworkHelper\homework_helper.exe")
    owned = set()
    for process in psutil.process_iter(["name"]):
        try:
            if (process.info["name"] or "").lower() == "homework_helper.exe" and Path(process.exe()) == installed:
                owned.add(process.pid)
        except psutil.Error:
            continue
    start = time.monotonic()
    samples, events, hooks = [], [], []

    def window(hwnd):
        if not hwnd:
            return None
        try:
            return {"hwnd": int(hwnd), "pid": win32process.GetWindowThreadProcessId(hwnd)[1],
                    "class": win32gui.GetClassName(hwnd), "visible": bool(win32gui.IsWindowVisible(hwnd)),
                    "rect": win32gui.GetWindowRect(hwnd),
                    "enabled": bool(win32gui.IsWindowEnabled(hwnd)),
                    "minimized": bool(win32gui.IsIconic(hwnd)),
                    "style": win32gui.GetWindowLong(hwnd, -16),
                    "extended_style": win32gui.GetWindowLong(hwnd, -20),
                    "dpi": int(user32.GetDpiForWindow(hwnd))}
        except (OSError, pywintypes.error):
            return {"hwnd": int(hwnd), "gone": True}

    def sample():
        windows = []
        def collect(hwnd, _):
            row = window(hwnd)
            if row and row.get("pid") in owned:
                windows.append(row)
        win32gui.EnumWindows(collect, None)
        sidebar = [row for row in windows if row.get("visible") and
                   row.get("class", "").startswith("Qt") and row["rect"][3] - row["rect"][1] > 300 and
                   any(abs(row["rect"][2] - row["rect"][0] - 280 * screen.devicePixelRatio()) < 2 for screen in app.screens())]
        ignore = sidebar[0]["hwnd"] if len(sidebar) == 1 else 0
        screens = []
        for screen in app.screens():
            geometry = screen.geometry()
            screens.append({"name": screen.name(), "primary": screen == app.primaryScreen(),
                            "geometry": geometry.getRect(), "work": screen.availableGeometry().getRect(),
                            "dpr": screen.devicePixelRatio(),
                            "native": get_visible_taskbar_work_area((geometry.x(), geometry.y()), ignore)})
        bars = []
        for name in ("Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
            hwnd = 0
            while True:
                hwnd = win32gui.FindWindowEx(0, hwnd, name, None)
                if not hwnd:
                    break
                bars.append(window(hwnd))
        cursor = win32gui.GetCursorPos()
        samples.append({"ms": round((time.monotonic() - start) * 1000, 2), "screens": screens,
                        "cursor": cursor, "cursor_window": window(win32gui.WindowFromPoint(cursor)),
                        "foreground": window(win32gui.GetForegroundWindow()), "windows": windows, "taskbars": bars})

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.GetDpiForWindow.argtypes = [ctypes.c_void_p]
    user32.GetDpiForWindow.restype = ctypes.c_uint
    callback_type = ctypes.WINFUNCTYPE(None, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p,
                                      ctypes.c_long, ctypes.c_long, ctypes.c_uint32, ctypes.c_uint32)
    def event(_hook, kind, hwnd, obj, child, _thread, timestamp):
        row = window(hwnd)
        if kind == 3 or (obj == 0 and row and (row.get("pid") in owned or row.get("class") in
                                              {"Shell_TrayWnd", "Shell_SecondaryTrayWnd"})):
            events.append({"ms": round((time.monotonic() - start) * 1000, 2), "event": kind,
                           "native_ms": timestamp, "window": row})
    callback = callback_type(event)
    user32.SetWinEventHook.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
                                      callback_type, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32]
    user32.SetWinEventHook.restype = ctypes.c_void_p
    user32.UnhookWinEvent.argtypes = [ctypes.c_void_p]
    try:
        if duration:
            for low, high in ((3, 3), (0x16, 0x17), (0x8000, 0x800B)):
                handle = user32.SetWinEventHook(low, high, None, callback, 0, 0, 2)
                if not handle:
                    raise ctypes.WinError(ctypes.get_last_error())
                hooks.append(handle)
        sample()
        if duration:
            timer = QTimer()
            timer.timeout.connect(sample)
            timer.start(200)
            QTimer.singleShot(duration * 1000, app.quit)
            app.exec()
        return {"samples": samples, "events": events}
    finally:
        for handle in hooks:
            user32.UnhookWinEvent(handle)


def close_obs(repo: Path, appdata: Path, pid: int, created: float, sid: str, session: int) -> dict:
    import psutil
    import win32gui
    from windows_host_probe import process_rows, database_state, obs_outputs
    rows = [row for row in process_rows(Path(r"C:\Program Files\HomeworkHelper")) if row["pid"] == pid]
    if len(rows) != 1:
        raise ValueError("OBS PID is no longer present")
    row = rows[0]
    if (row["name"] != "obs64.exe" or row.get("error") or row["sid"] != sid or
            row["session"] != session or abs(row["created"] - created) >= .01):
        raise ValueError("OBS identity changed")
    db = database_state(appdata / "HomeworkHelper/homework_helper_data/app_data.db")
    if not db.get("available") or db.get("open_sessions"):
        raise ValueError("Game session active or unknown")
    outputs = obs_outputs(repo, appdata, rows)
    if outputs.get("error") or not outputs["outputs"] or any(value is not False for value in outputs["outputs"].values()):
        raise ValueError("OBS output active or unknown")
    import win32process
    windows = []
    def collect(hwnd, _):
        if win32process.GetWindowThreadProcessId(hwnd)[1] == pid and win32gui.GetWindowText(hwnd).startswith("OBS "):
            windows.append(hwnd)
    win32gui.EnumWindows(collect, None)
    if len(windows) != 1:
        raise ValueError("OBS main window ambiguous")
    process = psutil.Process(pid)
    if process.exe() != row["path"] or abs(process.create_time() - created) >= .01:
        raise ValueError("OBS identity changed before close")
    win32gui.PostMessage(windows[0], 0x0010, 0, 0)  # WM_CLOSE; no forced termination.
    try:
        process.wait(timeout=20)
    except psutil.TimeoutExpired:
        raise ValueError("OBS normal close timed out")
    return {"exited": True, "pid": pid}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("desktop", "close-obs", "media-qa"))
    p.add_argument("--scenario", choices=("observe", "preview", "audio", "focus", "focus-compare", "bgm", "prepare-spotify", "triggers", "firefox"), default="observe")
    p.add_argument("--repo", type=Path, required=True)
    p.add_argument("--appdata", type=Path, required=True)
    p.add_argument("--result", type=Path, required=True)
    p.add_argument("--duration", type=int, default=0, choices=range(121))
    p.add_argument("--pid", type=int)
    p.add_argument("--created", type=float)
    p.add_argument("--sid", required=True)
    p.add_argument("--session", type=int, required=True)
    args = p.parse_args(argv)
    import os
    os.environ["APPDATA"] = str(args.appdata)
    os.environ["HH_TEST_APPDATA_DIR"] = str(args.result.parent / "isolated-appdata")
    os.environ.pop("QT_QPA_PLATFORM", None)
    def publish(value):
        temporary = args.result.with_suffix(".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        temporary.replace(args.result)
    try:
        import win32api
        import win32security as security
        token = security.OpenProcessToken(win32api.GetCurrentProcess(), security.TOKEN_QUERY)
        try:
            if (security.ConvertSidToStringSid(security.GetTokenInformation(token, security.TokenUser)[0]) != args.sid or
                    security.GetTokenInformation(token, security.TokenSessionId) != args.session):
                raise ValueError("Interactive user/session changed")
        finally:
            token.Close()
        if args.command == "media-qa":
            sys.path.insert(0, str(args.repo / "tools"))
            from windows_media_probe import run
            result = run(args.repo, args.appdata, args.result.parent, args.scenario)
        elif args.command == "desktop":
            result = desktop(args.repo, args.duration)
        else:
            result = close_obs(args.repo, args.appdata, args.pid, args.created, args.sid, args.session)
        publish({"ok": True, "result": result})
        return 0
    except Exception as error:
        failure = {"ok": False, "error": str(error) if isinstance(error, ValueError) else type(error).__name__}
        if args.command == "media-qa":
            import traceback
            sys.path.insert(0, str(args.repo))
            from src.gui.runtime_logging import redact_sensitive_text
            failure["error"] = redact_sensitive_text(traceback.format_exc())
        publish(failure)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
