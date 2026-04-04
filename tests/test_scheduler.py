"""Tests for changes made to src/core/scheduler.py in this PR.

Covered (PR-introduced code only):
- build_visual_status_snapshot()
- invalidate_visual_status_snapshot()
- run_all_checks() refactored status-change detection logic using _last_visual_statuses
"""
import datetime
import pytest
from unittest.mock import MagicMock, patch

from src.core.scheduler import Scheduler, PROC_STATE_COMPLETED, PROC_STATE_INCOMPLETE, PROC_STATE_RUNNING
from src.data.data_models import ManagedProcess, GlobalSettings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_process(
    pid="proc-1",
    name="TestGame",
    stamina_tracking_enabled=False,
    hoyolab_game_id=None,
    last_played_timestamp=None,
):
    return ManagedProcess(
        id=pid,
        name=name,
        monitoring_path="/game/test.exe",
        launch_path="/game/test.exe",
        stamina_tracking_enabled=stamina_tracking_enabled,
        hoyolab_game_id=hoyolab_game_id,
        last_played_timestamp=last_played_timestamp,
    )


def _make_scheduler(processes=None, active_monitored=None):
    """Create a Scheduler with mocked dependencies."""
    data_manager = MagicMock()
    data_manager.managed_processes = processes or []
    data_manager.global_settings = GlobalSettings()

    notifier = MagicMock()

    process_monitor = MagicMock()
    process_monitor.active_monitored_processes = active_monitored or {}

    scheduler = Scheduler(data_manager, notifier, process_monitor)
    return scheduler


# ---------------------------------------------------------------------------
# build_visual_status_snapshot
# ---------------------------------------------------------------------------

class TestBuildVisualStatusSnapshot:
    """Tests for Scheduler.build_visual_status_snapshot()."""

    def test_empty_processes_returns_empty_dict(self):
        scheduler = _make_scheduler()
        snapshot = scheduler.build_visual_status_snapshot()
        assert snapshot == {}

    def test_snapshot_keys_match_process_ids(self):
        processes = [
            _make_process(pid="a"),
            _make_process(pid="b"),
            _make_process(pid="c"),
        ]
        scheduler = _make_scheduler(processes=processes)
        snapshot = scheduler.build_visual_status_snapshot()
        assert set(snapshot.keys()) == {"a", "b", "c"}

    def test_running_process_shows_running_state(self):
        proc = _make_process(pid="game-1")
        scheduler = _make_scheduler(
            processes=[proc],
            active_monitored={"game-1": {"pid": 123}},
        )
        snapshot = scheduler.build_visual_status_snapshot()
        assert snapshot["game-1"] == PROC_STATE_RUNNING

    def test_completed_process_with_no_schedule(self):
        proc = _make_process(pid="game-2")
        # No server_reset, no mandatory times, no cycle → completed by default
        scheduler = _make_scheduler(processes=[proc])
        snapshot = scheduler.build_visual_status_snapshot()
        assert snapshot["game-2"] == PROC_STATE_COMPLETED

    def test_snapshot_uses_provided_now_dt(self):
        proc = _make_process(pid="g1")
        scheduler = _make_scheduler(processes=[proc])
        fixed_dt = datetime.datetime(2024, 1, 1, 12, 0, 0)
        # Should not raise and should use the provided datetime
        snapshot = scheduler.build_visual_status_snapshot(now_dt=fixed_dt)
        assert "g1" in snapshot

    def test_snapshot_calls_determine_process_visual_status_for_each_process(self):
        processes = [_make_process(pid=f"p{i}") for i in range(3)]
        scheduler = _make_scheduler(processes=processes)
        with patch.object(scheduler, "determine_process_visual_status", return_value=PROC_STATE_COMPLETED) as mock_det:
            snapshot = scheduler.build_visual_status_snapshot()
        assert mock_det.call_count == 3

    def test_snapshot_with_multiple_states(self):
        """Mix of running, completed, incomplete processes."""
        running_proc = _make_process(pid="running")
        completed_proc = _make_process(pid="completed")

        scheduler = _make_scheduler(
            processes=[running_proc, completed_proc],
            active_monitored={"running": {"pid": 99}},
        )
        snapshot = scheduler.build_visual_status_snapshot()
        assert snapshot["running"] == PROC_STATE_RUNNING
        assert snapshot["completed"] == PROC_STATE_COMPLETED

    def test_snapshot_does_not_mutate_last_visual_statuses(self):
        """build_visual_status_snapshot must NOT update _last_visual_statuses."""
        proc = _make_process(pid="x1")
        scheduler = _make_scheduler(processes=[proc])
        assert scheduler._last_visual_statuses == {}
        scheduler.build_visual_status_snapshot()
        assert scheduler._last_visual_statuses == {}

    def test_snapshot_returns_new_dict_each_call(self):
        proc = _make_process(pid="y1")
        scheduler = _make_scheduler(processes=[proc])
        s1 = scheduler.build_visual_status_snapshot()
        s2 = scheduler.build_visual_status_snapshot()
        assert s1 is not s2


# ---------------------------------------------------------------------------
# invalidate_visual_status_snapshot
# ---------------------------------------------------------------------------

class TestInvalidateVisualStatusSnapshot:
    """Tests for Scheduler.invalidate_visual_status_snapshot()."""

    def test_clears_last_visual_statuses(self):
        scheduler = _make_scheduler()
        scheduler._last_visual_statuses = {"proc-1": PROC_STATE_COMPLETED}
        scheduler.invalidate_visual_status_snapshot()
        assert scheduler._last_visual_statuses == {}

    def test_idempotent_when_already_empty(self):
        scheduler = _make_scheduler()
        assert scheduler._last_visual_statuses == {}
        scheduler.invalidate_visual_status_snapshot()
        assert scheduler._last_visual_statuses == {}

    def test_clears_large_snapshot(self):
        scheduler = _make_scheduler()
        scheduler._last_visual_statuses = {f"p{i}": PROC_STATE_COMPLETED for i in range(50)}
        scheduler.invalidate_visual_status_snapshot()
        assert scheduler._last_visual_statuses == {}

    def test_after_invalidate_run_all_checks_treats_first_call_as_no_change(self):
        """After invalidating, the next run_all_checks() initialises the cache
        without triggering a status-change callback."""
        proc = _make_process(pid="g1")
        scheduler = _make_scheduler(processes=[proc])
        callback = MagicMock()
        scheduler.status_change_callback = callback

        # Prime the cache
        scheduler._last_visual_statuses = {"g1": PROC_STATE_COMPLETED}
        # Invalidate
        scheduler.invalidate_visual_status_snapshot()
        # First run should re-initialise without firing callback
        result = scheduler.run_all_checks()
        assert result is False
        callback.assert_not_called()


# ---------------------------------------------------------------------------
# run_all_checks – new _last_visual_statuses logic
# ---------------------------------------------------------------------------

class TestRunAllChecksStatusCaching:
    """Tests for the refactored run_all_checks() change-detection logic."""

    def test_first_call_returns_false_and_initialises_cache(self):
        proc = _make_process(pid="g1")
        scheduler = _make_scheduler(processes=[proc])
        # _last_visual_statuses starts empty
        result = scheduler.run_all_checks()
        assert result is False
        assert "g1" in scheduler._last_visual_statuses

    def test_second_call_no_change_returns_false(self):
        proc = _make_process(pid="g1")
        scheduler = _make_scheduler(processes=[proc])
        scheduler.run_all_checks()  # initialise cache
        result = scheduler.run_all_checks()
        assert result is False

    def test_status_change_returns_true(self):
        """When the visual status changes between calls, run_all_checks returns True."""
        proc = _make_process(pid="g1")
        scheduler = _make_scheduler(processes=[proc])
        # Prime the cache with a different state
        scheduler._last_visual_statuses = {"g1": PROC_STATE_INCOMPLETE}
        # Now determine_process_visual_status will return COMPLETED (no schedule)
        result = scheduler.run_all_checks()
        assert result is True

    def test_status_change_fires_callback(self):
        proc = _make_process(pid="g1")
        scheduler = _make_scheduler(processes=[proc])
        callback = MagicMock()
        scheduler.status_change_callback = callback
        # Prime with different state
        scheduler._last_visual_statuses = {"g1": PROC_STATE_INCOMPLETE}
        scheduler.run_all_checks()
        callback.assert_called_once()

    def test_no_change_does_not_fire_callback(self):
        proc = _make_process(pid="g1")
        scheduler = _make_scheduler(processes=[proc])
        callback = MagicMock()
        scheduler.status_change_callback = callback
        # Initialise cache first (first call never fires callback)
        scheduler.run_all_checks()
        # Second call with same state
        scheduler.run_all_checks()
        callback.assert_not_called()

    def test_cache_updated_after_change(self):
        proc = _make_process(pid="g1")
        scheduler = _make_scheduler(processes=[proc])
        scheduler._last_visual_statuses = {"g1": PROC_STATE_INCOMPLETE}
        scheduler.run_all_checks()
        # After change detection, cache should hold the latest value
        assert scheduler._last_visual_statuses.get("g1") == PROC_STATE_COMPLETED

    def test_cache_updated_when_no_change(self):
        proc = _make_process(pid="g1")
        scheduler = _make_scheduler(processes=[proc])
        scheduler.run_all_checks()  # init
        old_cache = dict(scheduler._last_visual_statuses)
        scheduler.run_all_checks()  # no change
        # Cache should still reflect current state
        assert scheduler._last_visual_statuses == old_cache

    def test_callback_none_does_not_raise_on_change(self):
        """status_change_callback is None by default; should not raise."""
        proc = _make_process(pid="g1")
        scheduler = _make_scheduler(processes=[proc])
        assert scheduler.status_change_callback is None
        scheduler._last_visual_statuses = {"g1": PROC_STATE_INCOMPLETE}
        # Should not raise
        result = scheduler.run_all_checks()
        assert result is True

    def test_new_process_added_triggers_change(self):
        """Adding a new process that wasn't in the old snapshot triggers a change."""
        proc1 = _make_process(pid="p1")
        proc2 = _make_process(pid="p2")

        # Scheduler initially knows only p1
        scheduler = _make_scheduler(processes=[proc1])
        scheduler.run_all_checks()  # seed cache with only p1

        # Now data_manager has two processes
        scheduler.data_manager.managed_processes = [proc1, proc2]

        result = scheduler.run_all_checks()
        assert result is True

    def test_process_removed_triggers_change(self):
        """Removing a process that was in the old snapshot triggers a change."""
        proc1 = _make_process(pid="p1")
        proc2 = _make_process(pid="p2")

        scheduler = _make_scheduler(processes=[proc1, proc2])
        scheduler.run_all_checks()  # seed cache with p1+p2

        # Now only p1 remains
        scheduler.data_manager.managed_processes = [proc1]

        result = scheduler.run_all_checks()
        assert result is True

    def test_initial_empty_processes_first_call_returns_false(self):
        scheduler = _make_scheduler(processes=[])
        result = scheduler.run_all_checks()
        assert result is False

    def test_last_visual_statuses_initialised_on_first_call(self):
        """_last_visual_statuses should be non-empty after the first call
        (when processes exist)."""
        proc = _make_process(pid="init-test")
        scheduler = _make_scheduler(processes=[proc])
        assert scheduler._last_visual_statuses == {}
        scheduler.run_all_checks()
        assert "init-test" in scheduler._last_visual_statuses