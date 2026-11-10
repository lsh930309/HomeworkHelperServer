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


@pytest.mark.parametrize("replacement", ["removed", "foreign-owner", "hidden"])
def test_automatic_focus_never_reselects_a_replaced_candidate(desktop, replacement):
    _state, entries, _gui, calls = desktop
    selected = windows.managed_process_window(42, 123.0, "/game.exe")
    assert selected == 20 and not calls
    if replacement == "removed":
        del entries[selected]
    elif replacement == "foreign-owner":
        entries[selected]["pid"] = 99
    else:
        entries[selected]["visible"] = False
    # A different valid game window still exists, but the expired selection must fail.
    assert not windows.focus_managed_process_window(42, 123.0, "/game.exe", hwnd=selected)
    assert calls == []


def test_automatic_focus_uses_the_exact_observed_window_even_when_smaller(desktop):
    _state, _entries, _gui, calls = desktop
    assert windows.focus_managed_process_window(42, 123.0, "/game.exe", hwnd=10)
    assert calls == [("foreground", 10)]


@pytest.mark.parametrize("build", [17763, 22000, 22621, 26200])
def test_nonactivating_sidebar_uses_one_accent_path_on_supported_windows(monkeypatch, build):
    calls = []
    monkeypatch.setattr(effects, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(effects, "_WINDOWS_BUILD", build)
    def apply(hwnd, data):
        policy = ctypes.cast(data._obj.pData, ctypes.POINTER(effects._ACCENT_POLICY)).contents
        calls.append((hwnd.value, data._obj.Attribute, policy.AccentState, policy.AccentFlags, policy.GradientColor))
        return 1
    dll = SimpleNamespace(SetWindowCompositionAttribute=NativeCall(apply))
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: dll, raising=False)
    assert effects.apply_blur_effect(123)
    assert calls == [(123, 19, 4, 0, 0x99130C08)]
    assert dll.SetWindowCompositionAttribute.restype is ctypes.wintypes.BOOL


@pytest.mark.parametrize("platform,build,hwnd", [("darwin",26200,123), ("win32",17762,123), ("win32",26200,0)])
def test_unavailable_acrylic_does_not_invoke_native_api(monkeypatch, platform, build, hwnd):
    monkeypatch.setattr(effects, "sys", SimpleNamespace(platform=platform))
    monkeypatch.setattr(effects, "_WINDOWS_BUILD", build)
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_a, **_k: pytest.fail("unsupported native call"), raising=False)
    assert not effects.apply_blur_effect(hwnd)


@pytest.mark.parametrize("fail", ["return_false", "native_error"])
def test_acrylic_failure_is_reported_without_another_backend_or_retry(monkeypatch, caplog, fail):
    monkeypatch.setattr(effects, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(effects, "_WINDOWS_BUILD", 26200)
    calls = []
    def apply(*_args):
        calls.append(True)
        if fail == "native_error":
            raise OSError("composition unavailable")
        return 0
    dll = SimpleNamespace(SetWindowCompositionAttribute=NativeCall(apply))
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_a, **_k: dll, raising=False)
    assert not effects.apply_blur_effect(123)
    assert calls == [True]
    assert "Acrylic" in caplog.text
