"""Tests for the new dataclasses and return-type changes in src/core/process_monitor.py."""

import sys
import os
import pytest
from unittest.mock import MagicMock, patch

# conftest.py already installed stubs; ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.core.process_monitor import ProcessLifecycleEvent, ProcessMonitorTickResult


# ---------------------------------------------------------------------------
# ProcessLifecycleEvent
# ---------------------------------------------------------------------------

class TestProcessLifecycleEvent:
    """Tests for the new ProcessLifecycleEvent frozen dataclass."""

    def _make_event(self, **overrides):
        defaults = dict(
            process_id="proc-1",
            process_name="Game A",
            session_id=42,
            timestamp=1_700_000_000.0,
            stamina_tracking_enabled=True,
            hoyolab_game_id="genshin",
        )
        defaults.update(overrides)
        return ProcessLifecycleEvent(**defaults)

    def test_basic_construction(self):
        evt = self._make_event()
        assert evt.process_id == "proc-1"
        assert evt.process_name == "Game A"
        assert evt.session_id == 42
        assert evt.timestamp == 1_700_000_000.0
        assert evt.stamina_tracking_enabled is True
        assert evt.hoyolab_game_id == "genshin"

    def test_optional_fields_default_to_none(self):
        evt = self._make_event()
        assert evt.pid is None
        assert evt.stamina_at_end is None
        assert evt.stamina_max is None

    def test_optional_fields_set_explicitly(self):
        evt = self._make_event(pid=1234, stamina_at_end=100, stamina_max=200)
        assert evt.pid == 1234
        assert evt.stamina_at_end == 100
        assert evt.stamina_max == 200

    def test_is_hoyoverse_game_true(self):
        evt = self._make_event(stamina_tracking_enabled=True, hoyolab_game_id="genshin")
        assert evt.is_hoyoverse_game() is True

    def test_is_hoyoverse_game_false_tracking_disabled(self):
        evt = self._make_event(stamina_tracking_enabled=False, hoyolab_game_id="genshin")
        assert evt.is_hoyoverse_game() is False

    def test_is_hoyoverse_game_false_no_game_id(self):
        evt = self._make_event(stamina_tracking_enabled=True, hoyolab_game_id=None)
        assert evt.is_hoyoverse_game() is False

    def test_is_hoyoverse_game_false_both_conditions_unmet(self):
        evt = self._make_event(stamina_tracking_enabled=False, hoyolab_game_id=None)
        assert evt.is_hoyoverse_game() is False

    def test_is_frozen(self):
        """ProcessLifecycleEvent is a frozen dataclass; mutation must raise."""
        evt = self._make_event()
        with pytest.raises((AttributeError, TypeError)):
            evt.process_id = "other"  # type: ignore[misc]

    def test_event_with_no_session_id(self):
        evt = self._make_event(session_id=None)
        assert evt.session_id is None

    def test_event_equality(self):
        evt1 = self._make_event(timestamp=100.0)
        evt2 = self._make_event(timestamp=100.0)
        assert evt1 == evt2

    def test_event_inequality_different_timestamp(self):
        evt1 = self._make_event(timestamp=100.0)
        evt2 = self._make_event(timestamp=200.0)
        assert evt1 != evt2

    def test_non_hoyoverse_game_no_stamina_data(self):
        """Non-Hoyoverse events should have no stamina values."""
        evt = self._make_event(
            stamina_tracking_enabled=False,
            hoyolab_game_id=None,
            stamina_at_end=None,
            stamina_max=None,
        )
        assert evt.is_hoyoverse_game() is False
        assert evt.stamina_at_end is None

    def test_zero_stamina_at_end_is_valid(self):
        """stamina_at_end=0 should be preserved (not treated as None)."""
        evt = self._make_event(stamina_at_end=0, stamina_max=160)
        assert evt.stamina_at_end == 0


# ---------------------------------------------------------------------------
# ProcessMonitorTickResult
# ---------------------------------------------------------------------------

class TestProcessMonitorTickResult:
    """Tests for the new ProcessMonitorTickResult frozen dataclass."""

    def _make_event(self, process_id="p1"):
        return ProcessLifecycleEvent(
            process_id=process_id,
            process_name="Game",
            session_id=1,
            timestamp=0.0,
            stamina_tracking_enabled=False,
            hoyolab_game_id=None,
        )

    def test_changed_false_empty_lists(self):
        result = ProcessMonitorTickResult(changed=False)
        assert result.changed is False
        assert result.started == []
        assert result.stopped == []

    def test_changed_true_with_events(self):
        evt = self._make_event()
        result = ProcessMonitorTickResult(changed=True, started=[evt], stopped=[])
        assert result.changed is True
        assert len(result.started) == 1
        assert result.started[0].process_id == "p1"
        assert result.stopped == []

    def test_stopped_events_populated(self):
        evt = self._make_event("p2")
        result = ProcessMonitorTickResult(changed=True, started=[], stopped=[evt])
        assert len(result.stopped) == 1
        assert result.stopped[0].process_id == "p2"

    def test_multiple_started_events(self):
        events = [self._make_event(f"p{i}") for i in range(3)]
        result = ProcessMonitorTickResult(changed=True, started=events)
        assert len(result.started) == 3

    def test_is_frozen(self):
        result = ProcessMonitorTickResult(changed=False)
        with pytest.raises((AttributeError, TypeError)):
            result.changed = True  # type: ignore[misc]

    def test_default_started_and_stopped_are_independent_instances(self):
        """Each instance should get its own default list, not share one."""
        r1 = ProcessMonitorTickResult(changed=False)
        r2 = ProcessMonitorTickResult(changed=False)
        # Frozen dataclass — the lists should be separate objects
        assert r1.started is not r2.started
        assert r1.stopped is not r2.stopped


# ---------------------------------------------------------------------------
# ProcessMonitor.check_and_update_statuses return type
# ---------------------------------------------------------------------------

class TestProcessMonitorCheckReturnType:
    """Verify that check_and_update_statuses returns ProcessMonitorTickResult."""

    def _make_data_manager(self):
        dm = MagicMock()
        dm.managed_processes = []
        return dm

    def test_returns_tick_result_instance(self):
        from src.core.process_monitor import ProcessMonitor

        with patch("src.core.process_monitor.psutil") as mock_psutil:
            mock_psutil.process_iter.return_value = []
            monitor = ProcessMonitor(self._make_data_manager())
            result = monitor.check_and_update_statuses()

        assert isinstance(result, ProcessMonitorTickResult)

    def test_no_processes_returns_unchanged(self):
        from src.core.process_monitor import ProcessMonitor

        with patch("src.core.process_monitor.psutil") as mock_psutil:
            mock_psutil.process_iter.return_value = []
            monitor = ProcessMonitor(self._make_data_manager())
            result = monitor.check_and_update_statuses()

        assert result.changed is False
        assert result.started == []
        assert result.stopped == []

    def test_process_disappears_generates_stopped_event(self):
        """When a previously-active process is no longer running, a stopped event is emitted."""
        from src.core.process_monitor import ProcessMonitor

        managed = MagicMock()
        managed.id = "proc-x"
        managed.name = "TestGame"
        managed.monitoring_path = "/some/game.exe"
        managed.stamina_tracking_enabled = False
        managed.hoyolab_game_id = None
        managed.stamina_max = None
        managed.is_hoyoverse_game.return_value = False
        managed.last_played_timestamp = None

        dm = MagicMock()
        dm.managed_processes = [managed]
        dm.update_process.return_value = True
        dm.end_session.return_value = MagicMock(session_duration=120.0)

        with patch("src.core.process_monitor.psutil") as mock_psutil:
            mock_psutil.process_iter.return_value = []
            mock_psutil.NoSuchProcess = Exception
            mock_psutil.AccessDenied = Exception

            monitor = ProcessMonitor(dm)
            # Manually mark as active
            monitor.active_monitored_processes["proc-x"] = {
                "pid": 9999,
                "exe": "/some/game.exe",
                "start_time_approx": 0.0,
                "session_id": 5,
            }

            with patch("src.core.process_monitor.ProcessMonitor._normalize_path",
                       side_effect=lambda p: p):
                result = monitor.check_and_update_statuses()

        assert result.changed is True
        assert len(result.stopped) == 1
        stopped = result.stopped[0]
        assert stopped.process_id == "proc-x"
        assert stopped.session_id == 5
        assert stopped.is_hoyoverse_game() is False

    def test_stopped_hoyoverse_event_carries_stamina_fields(self):
        """Stopped event for a Hoyoverse game should carry stamina_at_end and stamina_max."""
        from src.core.process_monitor import ProcessMonitor

        managed = MagicMock()
        managed.id = "proc-hsr"
        managed.name = "HonkaiSR"
        managed.monitoring_path = "/hsr/game.exe"
        managed.stamina_tracking_enabled = True
        managed.hoyolab_game_id = "honkai_starrail"
        managed.stamina_max = 240
        managed.is_hoyoverse_game.return_value = True
        managed.last_played_timestamp = None

        dm = MagicMock()
        dm.managed_processes = [managed]
        dm.update_process.return_value = True
        dm.end_session.return_value = MagicMock(session_duration=60.0)

        with patch("src.core.process_monitor.psutil") as mock_psutil:
            mock_psutil.process_iter.return_value = []
            mock_psutil.NoSuchProcess = Exception
            mock_psutil.AccessDenied = Exception

            monitor = ProcessMonitor(dm)
            monitor.active_monitored_processes["proc-hsr"] = {
                "pid": 1111,
                "exe": "/hsr/game.exe",
                "start_time_approx": 0.0,
                "session_id": 10,
            }

            # Stub out HoYoLab service as unavailable
            with patch.object(monitor, "_update_stamina_on_game_exit", return_value=None):
                with patch("src.core.process_monitor.ProcessMonitor._normalize_path",
                           side_effect=lambda p: p):
                    result = monitor.check_and_update_statuses()

        assert len(result.stopped) == 1
        evt = result.stopped[0]
        assert evt.stamina_tracking_enabled is True
        assert evt.hoyolab_game_id == "honkai_starrail"
        assert evt.stamina_max == 240