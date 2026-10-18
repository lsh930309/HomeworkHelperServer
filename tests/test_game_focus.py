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
        self.windows = {}
        self.related = set()
        self.hidden = set()
        self.calls = []
        self.queries = []
        self.accept = True
        self.error = None
        self.current_foreground = (10, 100)

    def window(self, target):
        self.queries.append(target.pid)
        if self.error is not None:
            raise self.error
        return self.windows.get(target.pid)

    def is_related_foreground(self, target, pid):
        return pid in self.related

    def is_window_hidden(self, hwnd):
        return hwnd in self.hidden

    def focus(self, target, hwnd=None):
        self.calls.append((target, hwnd))
        if self.accept:
            self.current_foreground = (target.pid, hwnd)
        return self.accept

    def foreground(self):
        return self.current_foreground


def tracker(native):
    value = AutoFocusTracker(100.0, native=native)
    value.tick((), 10, 100, 0.0, 99)
    return value


def tick(value, targets, *, pid=10, hwnd=100, now=1.0):
    value.tick(tuple(targets), pid, hwnd, now, 99)


def test_first_baseline_and_preexisting_process_never_focus():
    native = Native()
    native.windows = {42: 420, 43: 430, 44: 440}
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
    native.windows[target.pid] = 420
    tick(value, [target], now=60)
    tick(value, [replace(target, user_volume=0, user_muted=True)], now=61)
    tick(value, [], now=62)
    tick(value, [target], now=63)
    assert native.calls == [(target, 420)]


def test_windows_rejection_is_logged_and_not_retried(caplog):
    native = Native()
    native.windows[42] = 420
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
    native.windows[42] = 420
    tick(value, [game()], now=121)
    tick(value, [game()], now=122)
    assert native.calls == []


def test_visible_window_requires_one_second_of_continuous_observation():
    native = Native()
    native.windows[42] = 420
    value = tracker(native)
    target = game()
    tick(value, [target], now=1)
    tick(value, [target], now=1.999)
    assert native.calls == []
    tick(value, [target], now=2)
    tick(value, [target], now=3)
    assert native.calls == [(target, 420)]


def test_short_background_splash_missed_in_foreground_does_not_consume_request():
    native = Native()
    native.related.add(43)
    native.windows[42] = 420
    value = tracker(native)
    target = game()
    # A appears only in background samples while its SDK owns foreground.
    tick(value, [target], pid=43, hwnd=430, now=1)
    tick(value, [target], pid=43, hwnd=430, now=1.25)
    native.windows.clear()
    tick(value, [target], pid=43, hwnd=430, now=1.5)
    native.windows[42] = 421
    tick(value, [target], pid=43, hwnd=430, now=2)
    tick(value, [target], pid=43, hwnd=430, now=2.75)
    assert native.calls == []
    tick(value, [target], pid=43, hwnd=430, now=3)
    assert native.calls == [(target, 421)]


def test_window_absence_resets_continuous_readiness_even_when_same_hwnd_returns():
    native = Native()
    native.windows[42] = 420
    value = tracker(native)
    target = game()
    tick(value, [target], now=1)
    tick(value, [target], now=1.5)
    native.windows.clear()
    tick(value, [target], now=1.75)
    native.windows[42] = 420
    tick(value, [target], now=2)
    tick(value, [target], now=2.75)
    assert native.calls == []
    tick(value, [target], now=3)
    assert native.calls == [(target, 420)]


def test_late_candidate_cannot_extend_deadline_to_finish_readiness():
    native = Native()
    value = tracker(native)
    target = game()
    tick(value, [target], now=0)
    native.windows[42] = 420
    tick(value, [target], now=119.5)
    tick(value, [target], now=120)
    tick(value, [target], now=120.5)
    assert native.calls == []


@pytest.mark.parametrize("pid,hwnd", [(20, 200), (10, 101)])
def test_foreign_pid_or_window_change_cancels_waiting(pid, hwnd):
    native = Native()
    value = tracker(native)
    tick(value, [game()])
    tick(value, [game()], pid=pid, hwnd=hwnd, now=2)
    native.windows[42] = 420
    tick(value, [game()], now=3)
    assert native.calls == []


def test_own_app_and_transient_zero_focus_do_not_cancel():
    native = Native()
    value = tracker(native)
    target = game()
    tick(value, [target])
    tick(value, [target], pid=99, hwnd=900, now=2)
    tick(value, [target], pid=0, hwnd=0, now=3)
    native.windows[42] = 420
    tick(value, [target], now=4)
    tick(value, [target], now=5)
    assert native.calls == [(target, 420)]


def test_initial_own_foreground_does_not_swallow_first_foreign_choice():
    native = Native()
    value = tracker(native)
    tick(value, [game()], pid=99, hwnd=900)
    tick(value, [game()], pid=20, hwnd=200, now=2)
    native.windows[42] = 420
    tick(value, [game()], pid=20, hwnd=200, now=3)
    assert native.calls == []


def test_initial_app_auto_hide_reveals_external_context_then_tracks_replacement_game_window():
    native = Native()
    value = tracker(native)
    target = game()
    tick(value, [target], pid=99, hwnd=900)
    native.hidden.add(900)
    tick(value, [target], pid=10, hwnd=100, now=2)
    native.windows[42] = 420
    tick(value, [target], pid=42, hwnd=420, now=3)
    native.windows.clear()
    native.related.add(43)
    tick(value, [target], pid=43, hwnd=430, now=4)
    native.windows[42] = 421
    tick(value, [target], pid=43, hwnd=430, now=5)
    tick(value, [target], pid=43, hwnd=430, now=6)
    assert native.calls == [(target, 421)]


def test_visible_initial_app_does_not_rebase_user_external_choice():
    native = Native()
    value = tracker(native)
    target = game()
    tick(value, [target], pid=99, hwnd=900)
    tick(value, [target], pid=10, hwnd=100, now=2)
    native.windows[42] = 421
    tick(value, [target], pid=10, hwnd=100, now=3)
    assert native.calls == []


def test_auto_hide_rebase_is_once_and_later_external_selection_cancels():
    native = Native()
    value = tracker(native)
    target = game()
    tick(value, [target], pid=99, hwnd=900)
    native.hidden.add(900)
    tick(value, [target], pid=10, hwnd=100, now=2)
    tick(value, [target], pid=20, hwnd=200, now=3)
    native.windows[42] = 421
    tick(value, [target], pid=10, hwnd=100, now=4)
    assert native.calls == []


def test_game_foreground_retains_observation_until_initial_deadline_without_native_focus():
    native = Native()
    native.windows[42] = 420
    value = tracker(native)
    tick(value, [game()], pid=42, hwnd=420)
    tick(value, [game()], pid=42, hwnd=420, now=60)
    tick(value, [game()], pid=42, hwnd=420, now=120)
    tick(value, [game()], now=121)
    tick(value, [game()], now=122)
    assert native.calls == []


def test_transient_game_window_then_sdk_then_main_window_gets_first_request():
    native = Native()
    value = tracker(native)
    target = game()
    native.windows[42] = 420
    tick(value, [target], pid=42, hwnd=420)
    native.windows.clear()
    native.related.add(43)
    tick(value, [target], pid=43, hwnd=430, now=2)
    tick(value, [target], pid=43, hwnd=430, now=40)
    assert native.calls == []
    native.windows[42] = 421
    tick(value, [target], pid=43, hwnd=430, now=60)
    tick(value, [target], pid=43, hwnd=430, now=61)
    assert native.calls == [(target, 421)]


def test_same_transient_hwnd_is_not_requested_after_sdk_takes_foreground():
    native = Native()
    native.related.add(43)
    value = tracker(native)
    target = game()
    tick(value, [target])
    native.windows[42] = 420
    tick(value, [target], pid=42, hwnd=420, now=2)
    tick(value, [target], pid=43, hwnd=430, now=3)
    tick(value, [target], now=4)
    assert native.calls == []
    native.windows[42] = 421
    tick(value, [target], now=5)
    tick(value, [target], now=6)
    assert native.calls == [(target, 421)]


def test_unrelated_foreground_after_transient_window_cancels_main_window_request():
    native = Native()
    native.windows[42] = 420
    value = tracker(native)
    target = game()
    tick(value, [target], pid=42, hwnd=420)
    native.windows.clear()
    tick(value, [target], pid=20, hwnd=200, now=2)
    native.windows[42] = 421
    tick(value, [target], now=3)
    assert native.calls == []


def test_same_pid_external_window_change_still_cancels_after_transient_game_window():
    native = Native()
    native.windows[42] = 420
    value = tracker(native)
    target = game()
    tick(value, [target], pid=42, hwnd=420)
    native.windows.clear()
    tick(value, [target], pid=10, hwnd=101, now=2)
    native.windows[42] = 421
    tick(value, [target], now=3)
    assert native.calls == []


def test_window_replacements_and_related_sdk_do_not_extend_initial_deadline():
    native = Native()
    native.related.add(43)
    value = tracker(native)
    target = game()
    tick(value, [target], pid=42, hwnd=420, now=1)
    tick(value, [target], pid=43, hwnd=430, now=119)
    native.windows[42] = 421
    tick(value, [target], pid=43, hwnd=430, now=121)
    tick(value, [target], now=122)
    assert native.calls == []


@pytest.mark.parametrize("accepted", [True, False])
def test_background_transient_request_is_not_repeated_for_replacement_hwnd(accepted):
    native = Native()
    native.accept = accepted
    native.windows[42] = 420
    value = tracker(native)
    target = game()
    tick(value, [target])
    tick(value, [target], now=2)
    native.windows.clear()
    tick(value, [target], now=3)
    native.windows[42] = 421
    tick(value, [target], now=4)
    tick(value, [target], now=5)
    assert native.calls == [(target, 420)]


def test_removed_target_and_pid_replacement_do_not_inherit_wait():
    native = Native()
    value = tracker(native)
    original = game()
    tick(value, [original])
    tick(value, [], now=2)
    native.windows[42] = 420
    tick(value, [original], now=3)
    assert native.calls == []
    replacement = replace(original, create_time=102.0)
    tick(value, [replacement], now=4)
    tick(value, [replacement], now=5)
    assert native.calls == [(replacement, 420)]


def test_simultaneous_games_focus_only_the_newest_and_do_not_chain():
    native = Native()
    native.windows = {42: 420, 43: 430}
    value = tracker(native)
    older, newer = game(), game("newer", 43, 102.0)
    tick(value, [older, newer])
    tick(value, [older, newer], now=2)
    assert native.calls == [(newer, 430)]


def test_newer_launch_replaces_pending_older_launch():
    native = Native()
    value = tracker(native)
    older, newer = game(), game("newer", 43, 102.0)
    tick(value, [older])
    tick(value, [older, newer], now=2)
    native.windows = {42: 420, 43: 430}
    tick(value, [older, newer], now=3)
    tick(value, [older, newer], now=4)
    assert native.calls == [(newer, 430)]


def test_cancel_preserves_seen_and_reset_establishes_new_baseline():
    native = Native()
    value = tracker(native)
    target = game()
    tick(value, [target])
    value.cancel()
    native.windows = {42: 420, 43: 430}
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
    native.windows[42] = 420
    tick(value, [game()], now=2)
    assert native.calls == []
    assert "관찰 또는 요청 실패" in caplog.text


def test_native_constructor_has_no_os_activity_and_focus_reuses_existing_helper(monkeypatch):
    from src.utils import windows
    calls = []
    monkeypatch.setattr(windows, "focus_managed_process_window", lambda *args, **kwargs: calls.append((args, kwargs)) or False)
    native = WindowsGameFocusNative()
    target = game()
    assert not native.focus(target)
    assert not native.focus(target, 420)
    assert calls == [
        ((target.pid, target.create_time, target.path), {"hwnd": None}),
        ((target.pid, target.create_time, target.path), {"hwnd": 420}),
    ]


def test_native_window_uses_shared_identity_checked_finder(monkeypatch):
    from src.utils import windows
    calls = []
    monkeypatch.setattr(windows, "managed_process_window", lambda *args: calls.append(args) or 420)
    target = game()
    assert WindowsGameFocusNative().window(target) == 420
    assert calls == [(target.pid, target.create_time, target.path)]


def test_native_foreground_reports_pid_and_hwnd_and_handles_no_foreground(monkeypatch):
    hwnd = [200]
    monkeypatch.setattr(module, "os", SimpleNamespace(name="nt"))
    monkeypatch.setitem(sys.modules, "win32gui", SimpleNamespace(GetForegroundWindow=lambda: hwnd[0]))
    monkeypatch.setitem(sys.modules, "win32process", SimpleNamespace(GetWindowThreadProcessId=lambda _hwnd: (1, 20)))
    native = WindowsGameFocusNative()
    assert native.foreground() == (20, 200)
    hwnd[0] = 0
    assert native.foreground() == (0, 0)


@pytest.mark.parametrize("case,expected", [
    ("current-descendant", True), ("root-reused", False),
    ("intermediate-reused", False), ("unrelated", False),
    ("other-user-session", False), ("invalid-target", False),
])
def test_native_child_relationship_requires_current_root_identity_and_chronology(monkeypatch, case, expected):
    import psutil
    from src.core import process_monitor
    from src.utils import audio_control
    parent = lambda pid, stamp: SimpleNamespace(pid=pid, create_time=lambda: stamp)
    root = parent(42, 101.0 if case != "root-reused" else 102.0)
    intermediate = parent(30, 102.0 if case != "intermediate-reused" else 104.0)
    ancestors = [intermediate, root] if case != "unrelated" else [intermediate]
    child = SimpleNamespace(pid=43, create_time=lambda: 103.0, parents=lambda: ancestors)
    monkeypatch.setattr(module, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(psutil, "Process", lambda _pid: child)
    monkeypatch.setattr(audio_control, "verify_identity", lambda _target: case != "invalid-target")
    monkeypatch.setattr(process_monitor, "_belongs_to_current_user_session", lambda _process: case != "other-user-session")
    assert WindowsGameFocusNative().is_related_foreground(game(), 43) is expected
