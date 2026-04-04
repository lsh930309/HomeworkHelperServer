"""Tests for changes in src/core/scheduler.py (PR scope only).

Changed behaviour:
- New _last_visual_statuses cache on Scheduler
- New build_visual_status_snapshot() method
- New invalidate_visual_status_snapshot() method
- run_all_checks() now uses _last_visual_statuses instead of computing
  both initial and final snapshots per call.
"""

import sys
import os
import datetime
import pytest
from unittest.mock import MagicMock, patch, call

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.data.data_models import ManagedProcess, GlobalSettings
from src.core.scheduler import Scheduler, PROC_STATE_COMPLETED, PROC_STATE_INCOMPLETE, PROC_STATE_RUNNING


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_process(
    proc_id="p1",
    name="GameA",
    last_played=None,
    server_reset=None,
    user_cycle=None,
    mandatory_times=None,
    is_mandatory_enabled=False,
    stamina_tracking=False,
    hoyolab_game_id=None,
):
    return ManagedProcess(
        id=proc_id,
        name=name,
        monitoring_path="/fake/game.exe",
        launch_path="/fake/game.exe",
        last_played_timestamp=last_played,
        server_reset_time_str=server_reset,
        user_cycle_hours=user_cycle,
        mandatory_times_str=mandatory_times or [],
        is_mandatory_time_enabled=is_mandatory_enabled,
        stamina_tracking_enabled=stamina_tracking,
        hoyolab_game_id=hoyolab_game_id,
    )


def _make_scheduler(processes=None, active_pids=None):
    """Return a Scheduler with mocked data_manager, notifier, and process_monitor."""
    dm = MagicMock()
    dm.managed_processes = processes or []
    dm.global_settings = GlobalSettings()

    notifier = MagicMock()

    pm = MagicMock()
    pm.active_monitored_processes = active_pids or {}

    scheduler = Scheduler(dm, notifier, pm)
    return scheduler, dm, notifier, pm


# ---------------------------------------------------------------------------
# build_visual_status_snapshot
# ---------------------------------------------------------------------------

class TestBuildVisualStatusSnapshot:

    def test_empty_processes_returns_empty_dict(self):
        scheduler, *_ = _make_scheduler()
        result = scheduler.build_visual_status_snapshot()
        assert result == {}

    def test_returns_dict_keyed_by_process_id(self):
        proc = _make_process(proc_id="p1")
        scheduler, *_ = _make_scheduler(processes=[proc])
        result = scheduler.build_visual_status_snapshot()
        assert "p1" in result

    def test_values_are_valid_state_strings(self):
        valid = {PROC_STATE_COMPLETED, PROC_STATE_INCOMPLETE, PROC_STATE_RUNNING}
        proc = _make_process(proc_id="p1")
        scheduler, *_ = _make_scheduler(processes=[proc])
        result = scheduler.build_visual_status_snapshot()
        assert result["p1"] in valid

    def test_running_process_reported_as_running(self):
        proc = _make_process(proc_id="p1")
        scheduler, _, _, pm = _make_scheduler(processes=[proc], active_pids={"p1": {}})
        result = scheduler.build_visual_status_snapshot()
        assert result["p1"] == PROC_STATE_RUNNING

    def test_accepts_explicit_now_dt(self):
        proc = _make_process(proc_id="p1")
        scheduler, *_ = _make_scheduler(processes=[proc])
        fixed_dt = datetime.datetime(2024, 1, 15, 10, 0, 0)
        result = scheduler.build_visual_status_snapshot(now_dt=fixed_dt)
        assert "p1" in result

    def test_multiple_processes(self):
        procs = [_make_process(proc_id=f"p{i}") for i in range(4)]
        scheduler, *_ = _make_scheduler(processes=procs)
        result = scheduler.build_visual_status_snapshot()
        assert set(result.keys()) == {"p0", "p1", "p2", "p3"}

    def test_snapshot_is_independent_copy(self):
        """Two calls should return independent dicts."""
        proc = _make_process(proc_id="p1")
        scheduler, *_ = _make_scheduler(processes=[proc])
        s1 = scheduler.build_visual_status_snapshot()
        s2 = scheduler.build_visual_status_snapshot()
        assert s1 is not s2

    def test_process_with_cycle_overdue_is_incomplete(self):
        """A process whose user cycle elapsed should show INCOMPLETE."""
        # last played 50 hours ago, cycle is 24 h
        past = datetime.datetime.now() - datetime.timedelta(hours=50)
        proc = _make_process(proc_id="p1", last_played=past.timestamp(), user_cycle=24)
        scheduler, *_ = _make_scheduler(processes=[proc])
        result = scheduler.build_visual_status_snapshot()
        assert result["p1"] == PROC_STATE_INCOMPLETE


# ---------------------------------------------------------------------------
# invalidate_visual_status_snapshot
# ---------------------------------------------------------------------------

class TestInvalidateVisualStatusSnapshot:

    def test_clears_cache(self):
        scheduler, *_ = _make_scheduler()
        scheduler._last_visual_statuses = {"p1": PROC_STATE_COMPLETED}
        scheduler.invalidate_visual_status_snapshot()
        assert scheduler._last_visual_statuses == {}

    def test_clears_non_empty_cache(self):
        scheduler, *_ = _make_scheduler()
        scheduler._last_visual_statuses = {f"p{i}": PROC_STATE_COMPLETED for i in range(5)}
        scheduler.invalidate_visual_status_snapshot()
        assert scheduler._last_visual_statuses == {}

    def test_idempotent_on_already_empty(self):
        scheduler, *_ = _make_scheduler()
        assert scheduler._last_visual_statuses == {}
        scheduler.invalidate_visual_status_snapshot()
        assert scheduler._last_visual_statuses == {}


# ---------------------------------------------------------------------------
# run_all_checks — caching behaviour
# ---------------------------------------------------------------------------

class TestRunAllChecksCaching:

    def test_first_call_returns_false_and_initialises_cache(self):
        """First invocation must always return False and populate cache."""
        proc = _make_process(proc_id="p1")
        scheduler, dm, notifier, pm = _make_scheduler(processes=[proc])
        # Patch sub-checks to no-ops so they don't interfere
        scheduler.check_daily_reset_tasks = MagicMock()
        scheduler.check_sleep_corrected_cycles = MagicMock()
        scheduler.check_mandatory_times = MagicMock()
        scheduler.check_user_cycles = MagicMock()
        scheduler.check_stamina_notifications = MagicMock()

        result = scheduler.run_all_checks()
        assert result is False
        assert scheduler._last_visual_statuses != {}

    def test_second_call_with_same_status_returns_false(self):
        proc = _make_process(proc_id="p1")
        scheduler, *_ = _make_scheduler(processes=[proc])
        for attr in ["check_daily_reset_tasks", "check_sleep_corrected_cycles",
                     "check_mandatory_times", "check_user_cycles", "check_stamina_notifications"]:
            setattr(scheduler, attr, MagicMock())

        scheduler.run_all_checks()  # first call — initialises
        result = scheduler.run_all_checks()  # second call — same status
        assert result is False

    def test_status_change_returns_true_and_calls_callback(self):
        """If status changes between two calls, run_all_checks must return True."""
        proc = _make_process(proc_id="p1")
        scheduler, dm, _, pm = _make_scheduler(processes=[proc])
        for attr in ["check_daily_reset_tasks", "check_sleep_corrected_cycles",
                     "check_mandatory_times", "check_user_cycles", "check_stamina_notifications"]:
            setattr(scheduler, attr, MagicMock())

        callback = MagicMock()
        scheduler.status_change_callback = callback

        # First call — primes cache with COMPLETED
        pm.active_monitored_processes = {}
        scheduler.run_all_checks()

        # Second call — process is now running
        pm.active_monitored_processes = {"p1": {}}
        result = scheduler.run_all_checks()

        assert result is True
        callback.assert_called_once()

    def test_status_change_without_callback_still_returns_true(self):
        proc = _make_process(proc_id="p1")
        scheduler, dm, _, pm = _make_scheduler(processes=[proc])
        for attr in ["check_daily_reset_tasks", "check_sleep_corrected_cycles",
                     "check_mandatory_times", "check_user_cycles", "check_stamina_notifications"]:
            setattr(scheduler, attr, MagicMock())

        scheduler.status_change_callback = None
        pm.active_monitored_processes = {}
        scheduler.run_all_checks()

        pm.active_monitored_processes = {"p1": {}}
        result = scheduler.run_all_checks()
        assert result is True

    def test_cache_is_updated_after_change(self):
        """After detecting a change, _last_visual_statuses should reflect the new state."""
        proc = _make_process(proc_id="p1")
        scheduler, dm, _, pm = _make_scheduler(processes=[proc])
        for attr in ["check_daily_reset_tasks", "check_sleep_corrected_cycles",
                     "check_mandatory_times", "check_user_cycles", "check_stamina_notifications"]:
            setattr(scheduler, attr, MagicMock())

        pm.active_monitored_processes = {}
        scheduler.run_all_checks()

        pm.active_monitored_processes = {"p1": {}}
        scheduler.run_all_checks()

        assert scheduler._last_visual_statuses.get("p1") == PROC_STATE_RUNNING

    def test_after_invalidate_first_call_semantics_repeat(self):
        """After invalidating, the next run_all_checks should behave like the first call again."""
        proc = _make_process(proc_id="p1")
        scheduler, dm, _, pm = _make_scheduler(processes=[proc])
        for attr in ["check_daily_reset_tasks", "check_sleep_corrected_cycles",
                     "check_mandatory_times", "check_user_cycles", "check_stamina_notifications"]:
            setattr(scheduler, attr, MagicMock())

        pm.active_monitored_processes = {"p1": {}}
        scheduler.run_all_checks()  # initialise

        # Now invalidate
        scheduler.invalidate_visual_status_snapshot()
        assert scheduler._last_visual_statuses == {}

        # Next call should return False (re-initialise semantics)
        result = scheduler.run_all_checks()
        assert result is False
        assert scheduler._last_visual_statuses != {}

    def test_cache_initialised_empty_at_construction(self):
        scheduler, *_ = _make_scheduler()
        assert scheduler._last_visual_statuses == {}

    def test_no_processes_run_all_checks_returns_false(self):
        scheduler, *_ = _make_scheduler(processes=[])
        for attr in ["check_daily_reset_tasks", "check_sleep_corrected_cycles",
                     "check_mandatory_times", "check_user_cycles", "check_stamina_notifications"]:
            setattr(scheduler, attr, MagicMock())
        # First call
        assert scheduler.run_all_checks() is False
        # Second call — no change
        assert scheduler.run_all_checks() is False

    def test_callback_not_called_on_first_run(self):
        """Callback must not fire on the first (cache-priming) call."""
        proc = _make_process(proc_id="p1")
        scheduler, *_ = _make_scheduler(processes=[proc])
        for attr in ["check_daily_reset_tasks", "check_sleep_corrected_cycles",
                     "check_mandatory_times", "check_user_cycles", "check_stamina_notifications"]:
            setattr(scheduler, attr, MagicMock())
        cb = MagicMock()
        scheduler.status_change_callback = cb
        scheduler.run_all_checks()
        cb.assert_not_called()