"""autofocus 수명주기는 fake만 사용하며 실제 창·게임·호스트를 조작하지 않는다."""
from dataclasses import replace
import sys
from types import SimpleNamespace

import pytest

from src.core.game_audio import GameAudioTarget
from src.core.game_focus import AutoFocusTracker, WindowsGameFocusNative
from src.core import game_focus as module


def game(process_id="game", pid=42, create_time=101.0, path=r"C:\Game.exe"):
    return GameAudioTarget(process_id, pid, create_time, path, False, 50)


class Native:
    def __init__(self):
        self.ready = set()
        self.calls = []
        self.queries = []
        self.accept = True
        self.error = None

    def has_window(self, target):
        self.queries.append(target.pid)
        if self.error is not None:
            raise self.error
        return target.pid in self.ready

    def focus(self, target):
        self.calls.append(target)
        return self.accept


def tracker(native):
    value = AutoFocusTracker(100.0, native=native)
    value.tick((), 10, 100, 0.0, 99)
    return value


def tick(value, targets, *, pid=10, hwnd=100, now=1.0):
    value.tick(tuple(targets), pid, hwnd, now, 99)


def test_first_baseline_and_preexisting_process_never_focus():
    native = Native()
    native.ready = {42, 43, 44}
    value = AutoFocusTracker(100.0, native=native)
    existing = game()
    tick(value, [existing])
    tick(value, [existing, game("old", 43, 99.0), game("same-time", 44, 100.0)])
    assert native.calls == native.queries == []


def test_waits_for_visible_window_then_focuses_exactly_once():
    native = Native()
    value = tracker(native)
    target = game()
    tick(value, [target])
    tick(value, [target], now=50)
    assert native.calls == []
    native.ready.add(target.pid)
    tick(value, [target], now=60)
    tick(value, [replace(target, user_volume=0, user_muted=True)], now=61)
    tick(value, [], now=62)
    tick(value, [target], now=63)
    assert native.calls == [target]


def test_windows_rejection_is_logged_and_not_retried(caplog):
    native = Native()
    native.ready.add(42)
    native.accept = False
    value = tracker(native)
    tick(value, [game()])
    tick(value, [game()], now=2)
    assert len(native.calls) == 1
    assert "허용되지 않음" in caplog.text


def test_waiting_expires_at_deadline_without_focus():
    native = Native()
    value = tracker(native)
    tick(value, [game()], now=1)
    native.ready.add(42)
    tick(value, [game()], now=121)
    tick(value, [game()], now=122)
    assert native.calls == []


@pytest.mark.parametrize("pid,hwnd", [(20, 200), (10, 101)])
def test_foreign_pid_or_window_change_cancels_waiting(pid, hwnd):
    native = Native()
    value = tracker(native)
    tick(value, [game()])
    tick(value, [game()], pid=pid, hwnd=hwnd, now=2)
    native.ready.add(42)
    tick(value, [game()], now=3)
    assert native.calls == []


def test_own_app_and_transient_zero_focus_do_not_cancel():
    native = Native()
    value = tracker(native)
    target = game()
    tick(value, [target])
    tick(value, [target], pid=99, hwnd=900, now=2)
    tick(value, [target], pid=0, hwnd=0, now=3)
    native.ready.add(42)
    tick(value, [target], now=4)
    assert native.calls == [target]


def test_initial_own_foreground_does_not_swallow_first_foreign_choice():
    native = Native()
    value = tracker(native)
    tick(value, [game()], pid=99, hwnd=900)
    tick(value, [game()], pid=20, hwnd=200, now=2)
    native.ready.add(42)
    tick(value, [game()], pid=20, hwnd=200, now=3)
    assert native.calls == []


def test_game_already_foreground_consumes_attempt_without_native_focus():
    native = Native()
    native.ready.add(42)
    value = tracker(native)
    tick(value, [game()], pid=42, hwnd=420)
    tick(value, [game()], now=2)
    assert native.calls == native.queries == []


def test_removed_target_and_pid_replacement_do_not_inherit_wait():
    native = Native()
    value = tracker(native)
    original = game()
    tick(value, [original])
    tick(value, [], now=2)
    native.ready.add(42)
    tick(value, [original], now=3)
    assert native.calls == []
    replacement = replace(original, create_time=102.0)
    tick(value, [replacement], now=4)
    assert native.calls == [replacement]


def test_simultaneous_games_focus_only_the_newest_and_do_not_chain():
    native = Native()
    native.ready = {42, 43}
    value = tracker(native)
    older, newer = game(), game("newer", 43, 102.0)
    tick(value, [older, newer])
    tick(value, [older, newer], now=2)
    assert native.calls == [newer]


def test_newer_launch_replaces_pending_older_launch():
    native = Native()
    value = tracker(native)
    older, newer = game(), game("newer", 43, 102.0)
    tick(value, [older])
    tick(value, [older, newer], now=2)
    native.ready = {42, 43}
    tick(value, [older, newer], now=3)
    assert native.calls == [newer]


def test_cancel_preserves_seen_and_reset_establishes_new_baseline():
    native = Native()
    value = tracker(native)
    target = game()
    tick(value, [target])
    value.cancel()
    native.ready = {42, 43}
    tick(value, [target], now=2)
    assert native.calls == []
    value.reset()
    other = game("other", 43, 103.0)
    tick(value, [target, other], now=3)
    tick(value, [target, other], now=4)
    assert native.calls == []


def test_native_query_error_is_reported_and_consumes_wait(caplog):
    native = Native()
    native.error = OSError("enumeration unavailable")
    value = tracker(native)
    tick(value, [game()])
    native.error = None
    native.ready.add(42)
    tick(value, [game()], now=2)
    assert native.calls == []
    assert "관찰 또는 요청 실패" in caplog.text


def test_native_constructor_has_no_os_activity_and_focus_reuses_existing_helper(monkeypatch):
    from src.utils import windows
    calls = []
    monkeypatch.setattr(windows, "focus_managed_process_window", lambda *args: calls.append(args) or False)
    native = WindowsGameFocusNative()
    target = game()
    assert not native.focus(target)
    assert calls == [(target.pid, target.create_time, target.path)]


def test_native_readiness_requires_visible_matching_pid_and_nonzero_area(monkeypatch):
    windows = {
        1: (False, 42, (0, 0, 800, 600), False),
        2: (True, 7, (0, 0, 800, 600), False),
        3: (True, 42, (0, 0, 0, 600), False),
    }
    fake_gui = SimpleNamespace(
        GetForegroundWindow=lambda: 2,
        EnumWindows=lambda callback, extra: [callback(hwnd, extra) for hwnd in windows],
        IsWindowVisible=lambda hwnd: windows[hwnd][0],
        IsIconic=lambda hwnd: windows[hwnd][3],
        GetWindowRect=lambda hwnd: windows[hwnd][2],
        GetWindowPlacement=lambda hwnd: (0, 0, (0, 0), (0, 0), windows[hwnd][2]),
    )
    fake_process = SimpleNamespace(GetWindowThreadProcessId=lambda hwnd: (1, windows[hwnd][1]))
    monkeypatch.setattr(module, "os", SimpleNamespace(name="nt"))
    monkeypatch.setitem(sys.modules, "win32gui", fake_gui)
    monkeypatch.setitem(sys.modules, "win32process", fake_process)
    native = WindowsGameFocusNative()
    assert native.foreground() == (7, 2)
    assert not native.has_window(game())
    windows[4] = (True, 42, (10, 10, 810, 610), True)
    assert native.has_window(game())
    windows.clear()
    fake_gui.GetForegroundWindow = lambda: 0
    assert native.foreground() == (0, 0)
