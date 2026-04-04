"""Tests for new dataclasses added to src/core/process_monitor.py in this PR.

Covered:
- ProcessLifecycleEvent construction and is_hoyoverse_game()
- ProcessMonitorTickResult construction and field defaults
- check_and_update_statuses() return type and structure (via mocked psutil)
"""
import sys
import time
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

# Ensure conftest mocks are applied before project imports
from src.core.process_monitor import (
    ProcessLifecycleEvent,
    ProcessMonitorTickResult,
    ProcessMonitor,
)


# ---------------------------------------------------------------------------
# ProcessLifecycleEvent
# ---------------------------------------------------------------------------

class TestProcessLifecycleEvent:
    """Tests for the new ProcessLifecycleEvent frozen dataclass."""

    def _make_event(self, **overrides):
        defaults = dict(
            process_id="proc-1",
            process_name="TestGame",
            session_id=42,
            timestamp=1_000_000.0,
            stamina_tracking_enabled=False,
            hoyolab_game_id=None,
        )
        defaults.update(overrides)
        return ProcessLifecycleEvent(**defaults)

    def test_basic_construction(self):
        event = self._make_event()
        assert event.process_id == "proc-1"
        assert event.process_name == "TestGame"
        assert event.session_id == 42
        assert event.timestamp == 1_000_000.0
        assert event.stamina_tracking_enabled is False
        assert event.hoyolab_game_id is None

    def test_optional_fields_default_to_none(self):
        event = self._make_event()
        assert event.pid is None
        assert event.stamina_at_end is None
        assert event.stamina_max is None

    def test_optional_fields_explicit(self):
        event = self._make_event(pid=1234, stamina_at_end=100, stamina_max=240)
        assert event.pid == 1234
        assert event.stamina_at_end == 100
        assert event.stamina_max == 240

    def test_is_hoyoverse_game_false_when_tracking_disabled(self):
        event = self._make_event(
            stamina_tracking_enabled=False,
            hoyolab_game_id="genshin",
        )
        assert event.is_hoyoverse_game() is False

    def test_is_hoyoverse_game_false_when_no_game_id(self):
        event = self._make_event(
            stamina_tracking_enabled=True,
            hoyolab_game_id=None,
        )
        assert event.is_hoyoverse_game() is False

    def test_is_hoyoverse_game_true_when_both_set(self):
        event = self._make_event(
            stamina_tracking_enabled=True,
            hoyolab_game_id="genshin_impact",
        )
        assert event.is_hoyoverse_game() is True

    def test_is_hoyoverse_game_true_for_starrail(self):
        event = self._make_event(
            stamina_tracking_enabled=True,
            hoyolab_game_id="honkai_starrail",
        )
        assert event.is_hoyoverse_game() is True

    def test_is_hoyoverse_game_false_when_both_missing(self):
        event = self._make_event(
            stamina_tracking_enabled=False,
            hoyolab_game_id=None,
        )
        assert event.is_hoyoverse_game() is False

    def test_frozen_dataclass_immutable(self):
        """ProcessLifecycleEvent should be immutable (frozen=True)."""
        event = self._make_event()
        with pytest.raises((AttributeError, TypeError)):
            event.process_id = "changed"  # type: ignore[misc]

    def test_equality_same_values(self):
        e1 = self._make_event(timestamp=999.0)
        e2 = self._make_event(timestamp=999.0)
        assert e1 == e2

    def test_inequality_different_values(self):
        e1 = self._make_event(process_id="a")
        e2 = self._make_event(process_id="b")
        assert e1 != e2

    def test_session_id_none_is_valid(self):
        event = self._make_event(session_id=None)
        assert event.session_id is None


# ---------------------------------------------------------------------------
# ProcessMonitorTickResult
# ---------------------------------------------------------------------------

class TestProcessMonitorTickResult:
    """Tests for the new ProcessMonitorTickResult frozen dataclass."""

    def test_construction_changed_true(self):
        result = ProcessMonitorTickResult(changed=True)
        assert result.changed is True
        assert result.started == []
        assert result.stopped == []

    def test_construction_changed_false(self):
        result = ProcessMonitorTickResult(changed=False)
        assert result.changed is False

    def test_started_and_stopped_populated(self):
        evt = ProcessLifecycleEvent(
            process_id="p1",
            process_name="Game",
            session_id=1,
            timestamp=1.0,
            stamina_tracking_enabled=False,
            hoyolab_game_id=None,
        )
        result = ProcessMonitorTickResult(changed=True, started=[evt], stopped=[])
        assert len(result.started) == 1
        assert result.started[0].process_id == "p1"

    def test_stopped_events_populated(self):
        evt = ProcessLifecycleEvent(
            process_id="p2",
            process_name="Game2",
            session_id=2,
            timestamp=2.0,
            stamina_tracking_enabled=True,
            hoyolab_game_id="genshin_impact",
            stamina_at_end=150,
            stamina_max=180,
        )
        result = ProcessMonitorTickResult(changed=True, stopped=[evt])
        assert len(result.stopped) == 1
        assert result.stopped[0].stamina_at_end == 150
        assert result.stopped[0].stamina_max == 180

    def test_frozen_immutable(self):
        result = ProcessMonitorTickResult(changed=False)
        with pytest.raises((AttributeError, TypeError)):
            result.changed = True  # type: ignore[misc]

    def test_default_lists_are_independent(self):
        """Each instance must get its own default lists (not shared)."""
        r1 = ProcessMonitorTickResult(changed=False)
        r2 = ProcessMonitorTickResult(changed=False)
        # They're frozen, so we can only check identity
        # The important thing is they're separate list objects
        assert r1.started is not r2.started
        assert r1.stopped is not r2.stopped

    def test_equality(self):
        r1 = ProcessMonitorTickResult(changed=False, started=[], stopped=[])
        r2 = ProcessMonitorTickResult(changed=False, started=[], stopped=[])
        assert r1 == r2

    def test_inequality_on_changed(self):
        r1 = ProcessMonitorTickResult(changed=True)
        r2 = ProcessMonitorTickResult(changed=False)
        assert r1 != r2


# ---------------------------------------------------------------------------
# ProcessMonitor.check_and_update_statuses() – return type
# ---------------------------------------------------------------------------

class TestCheckAndUpdateStatusesReturnType:
    """Verify check_and_update_statuses() returns ProcessMonitorTickResult
    (not a plain bool as in the old implementation)."""

    def _make_data_manager(self, processes=None):
        dm = MagicMock()
        dm.managed_processes = processes or []
        return dm

    def test_returns_process_monitor_tick_result(self):
        dm = self._make_data_manager()
        monitor = ProcessMonitor(dm)
        with patch("psutil.process_iter", return_value=[]):
            result = monitor.check_and_update_statuses()
        assert isinstance(result, ProcessMonitorTickResult)

    def test_no_processes_no_change(self):
        dm = self._make_data_manager()
        monitor = ProcessMonitor(dm)
        with patch("psutil.process_iter", return_value=[]):
            result = monitor.check_and_update_statuses()
        assert result.changed is False
        assert result.started == []
        assert result.stopped == []

    def test_process_stops_emits_stopped_event(self):
        """A process that was active but is no longer running generates a stopped event."""
        import uuid

        managed = MagicMock()
        managed.id = str(uuid.uuid4())
        managed.name = "TestGame"
        managed.monitoring_path = "/games/test.exe"
        managed.stamina_tracking_enabled = False
        managed.hoyolab_game_id = None
        managed.stamina_max = None
        managed.is_hoyoverse_game.return_value = False
        managed.last_played_timestamp = None

        dm = self._make_data_manager(processes=[managed])
        dm.end_session.return_value = MagicMock(session_duration=60.0)
        dm.update_process.return_value = True

        monitor = ProcessMonitor(dm)
        # Mark process as previously active
        cached_path = "/games/test.exe"
        import os
        normalized = os.path.normcase(os.path.abspath(cached_path))
        monitor.active_monitored_processes[managed.id] = {
            "pid": 9999,
            "exe": normalized,
            "start_time_approx": time.time() - 100,
            "session_id": 7,
        }

        # Patch managed_proc.monitoring_path to match the normalized form
        managed.monitoring_path = normalized

        # psutil returns no processes matching our path
        with patch("psutil.process_iter", return_value=[]):
            result = monitor.check_and_update_statuses()

        assert result.changed is True
        assert len(result.stopped) == 1
        stopped = result.stopped[0]
        assert stopped.process_id == managed.id
        assert stopped.process_name == "TestGame"
        assert stopped.session_id == 7
        assert stopped.stamina_tracking_enabled is False

    def test_stopped_event_carries_stamina_fields(self):
        """Stopped event for a HoYoverse game carries stamina_at_end and stamina_max."""
        import uuid, os

        managed = MagicMock()
        managed.id = str(uuid.uuid4())
        managed.name = "Genshin"
        managed.stamina_tracking_enabled = True
        managed.hoyolab_game_id = "genshin_impact"
        managed.stamina_max = 200
        managed.is_hoyoverse_game.return_value = True
        managed.last_played_timestamp = None

        dm = self._make_data_manager(processes=[managed])
        dm.end_session.return_value = MagicMock(session_duration=30.0)
        dm.update_process.return_value = True

        monitor = ProcessMonitor(dm)
        # Stub _update_stamina_on_game_exit to return a value
        monitor._update_stamina_on_game_exit = MagicMock(return_value=120)

        normalized = "/games/genshin.exe"
        managed.monitoring_path = normalized
        monitor.active_monitored_processes[managed.id] = {
            "pid": 1111,
            "exe": normalized,
            "start_time_approx": time.time() - 200,
            "session_id": 5,
        }

        with patch("psutil.process_iter", return_value=[]):
            result = monitor.check_and_update_statuses()

        assert len(result.stopped) == 1
        evt = result.stopped[0]
        assert evt.stamina_at_end == 120
        assert evt.stamina_max == 200
        assert evt.is_hoyoverse_game() is True