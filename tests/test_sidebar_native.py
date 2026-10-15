"""Windows 경계의 입력·거부·identity 계약. 실제 화면 검수와 구분한다."""
import ctypes
import sys
from types import SimpleNamespace

import pytest

from src.utils import windows
from src.gui.sidebar import win32_effects as effects


class NativeCall:
    def __init__(self, function):
        self.function = function

    def __call__(self, *args):
        return self.function(*args)


@pytest.fixture
def desktop(monkeypatch):
    import psutil
    from src.core import process_monitor
    calls = []
    state = SimpleNamespace(created=123.0, path="/game.exe", owner_matches=True,
                            running=True, foreground=0, allowed=True)
    process = SimpleNamespace(is_running=lambda: state.running, create_time=lambda: state.created,
                              exe=lambda: state.path)
    windows_by_id = {
        10: {"pid": 42, "visible": True, "rect": (0, 0, 300, 200), "iconic": False},
        20: {"pid": 42, "visible": True, "rect": (0, 0, 1920, 1080), "iconic": False},
        30: {"pid": 99, "visible": True, "rect": (0, 0, 4000, 4000), "iconic": False},
    }
    gui = SimpleNamespace(
        EnumWindows=lambda collect, extra: [collect(hwnd, extra) for hwnd in windows_by_id],
        IsWindowVisible=lambda hwnd: windows_by_id[hwnd]["visible"],
        IsIconic=lambda hwnd: windows_by_id[hwnd]["iconic"],
        GetWindowRect=lambda hwnd: windows_by_id[hwnd]["rect"],
        GetWindowPlacement=lambda hwnd: (0, 0, (0, 0), (0, 0), windows_by_id[hwnd]["rect"]),
        GetForegroundWindow=lambda: state.foreground,
    )
    process_api = SimpleNamespace(GetWindowThreadProcessId=lambda hwnd: (1, windows_by_id[hwnd]["pid"]))
    dll = SimpleNamespace(
        ShowWindowAsync=NativeCall(lambda hwnd, mode: calls.append(("restore", hwnd.value, mode)) or 1),
        SetForegroundWindow=NativeCall(lambda hwnd: calls.append(("foreground", hwnd.value)) or int(state.allowed)),
    )
    monkeypatch.setattr(windows, "is_windows", lambda: True)
    monkeypatch.setattr(psutil, "Process", lambda _pid: process)
    monkeypatch.setattr(process_monitor, "_belongs_to_current_user_session", lambda _p: state.owner_matches)
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: dll, raising=False)
    monkeypatch.setitem(sys.modules, "win32gui", gui)
    monkeypatch.setitem(sys.modules, "win32process", process_api)
    return state, windows_by_id, gui, calls


def test_focus_selects_largest_game_window_and_restores_minimized_window(desktop):
    _state, entries, _gui, calls = desktop
    entries[20]["iconic"] = True
    assert windows.focus_managed_process_window(42, 123.0, "/game.exe")
    assert calls == [("restore", 20, 9), ("foreground", 20)]


def test_focus_reuses_already_foreground_game_window_instead_of_another_large_window(desktop):
    state, _entries, _gui, calls = desktop
    state.foreground = 10
    assert windows.focus_managed_process_window(42, 123.0, "/game.exe")
    assert calls == [("foreground", 10)]


@pytest.mark.parametrize("field,value", [("created", 999.0), ("path", "/different.exe"),
                                         ("owner_matches", False), ("running", False)])
def test_focus_rejects_reused_pid_other_path_user_or_session(desktop, field, value):
    state, _entries, _gui, calls = desktop
    setattr(state, field, value)
    assert not windows.focus_managed_process_window(42, 123.0, "/game.exe")
    assert not calls


def test_focus_rechecks_identity_after_window_enumeration(desktop):
    state, _entries, gui, calls = desktop
    enumerate_windows = gui.EnumWindows
    def reuse_pid(collect, extra):
        enumerate_windows(collect, extra)
        state.created = 999.0
    gui.EnumWindows = reuse_pid
    assert not windows.focus_managed_process_window(42, 123.0, "/game.exe")
    assert not calls


def test_focus_missing_game_window_and_windows_denial_do_not_force_or_retry(desktop):
    state, entries, _gui, calls = desktop
    entries[10]["visible"] = entries[20]["visible"] = False
    assert not windows.focus_managed_process_window(42, 123.0, "/game.exe")
    assert not calls
    entries[20]["visible"] = True
    state.allowed = False
    assert not windows.focus_managed_process_window(42, 123.0, "/game.exe")
    assert calls == [("foreground", 20)]


@pytest.mark.parametrize("build,expected", [(17762, None), (17763, "accent"),
                                           (22000, "accent"), (22621, "dwm")])
def test_acrylic_uses_documented_dwm_build_boundary(monkeypatch, build, expected):
    calls = []
    monkeypatch.setattr(effects, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(effects, "_WINDOWS_BUILD", build)
    monkeypatch.setattr(effects, "_apply_dwm_backdrop", lambda *args: calls.append("dwm") or True)
    monkeypatch.setattr(effects, "_apply_acrylic_win10", lambda *args: calls.append("accent") or True)
    assert effects.apply_blur_effect(123, "acrylic") is (expected is not None)
    assert calls == ([expected] if expected else [])


def test_dwm_extends_glass_over_client_area_and_requests_acrylic(monkeypatch):
    calls = []
    def attribute(hwnd, key, value, _size):
        calls.append((getattr(key, "value", key), value._obj.value))
        return 0
    def extend(hwnd, margins):
        calls.append(("glass", margins._obj.left, margins._obj.right, margins._obj.top, margins._obj.bottom))
        return 0
    dll = SimpleNamespace(DwmSetWindowAttribute=NativeCall(attribute),
                          DwmExtendFrameIntoClientArea=NativeCall(extend))
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: dll, raising=False)
    assert effects._apply_dwm_backdrop(123, "acrylic")
    assert calls == [(20, 1), ("glass", -1, -1, -1, -1), (38, 3)]
