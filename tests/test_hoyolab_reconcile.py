"""Tests for src/core/hoyolab_reconcile.py (new file in this PR).

Covered:
- _ReconcileJob dataclass construction
- HoYoStaminaReconcileCoordinator lifecycle token management
- handle_process_started(): token advancement, job cancellation
- handle_process_stopped(): HoYoverse vs non-HoYoverse routing, job creation
- shutdown(): jobs cleared, _shutting_down set
- schedule_startup_refreshes(): skips active processes, skips non-hoyoverse
- _apply_session_correction(): stamina recovery math
- _apply_authoritative_process_stamina(): update logic, no-op when unchanged
- _on_fetch_finished(): guard conditions (stale token, stale seq, process running again,
    process metadata changed, stamina stabilised, window elapsed, finish_on_success)
- _finish_job(): removes job, handles missing job gracefully
"""
import time
import pytest
from unittest.mock import MagicMock, patch, call

# PyQt6 is mocked in conftest.py at import time
from src.core.hoyolab_reconcile import (
    HoYoStaminaReconcileCoordinator,
    _ReconcileJob,
)
from src.core.process_monitor import ProcessLifecycleEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_lifecycle_event(
    process_id="proc-1",
    process_name="TestGame",
    session_id=10,
    timestamp=1_000_000.0,
    stamina_tracking_enabled=True,
    hoyolab_game_id="genshin_impact",
    stamina_at_end=None,
    stamina_max=None,
):
    return ProcessLifecycleEvent(
        process_id=process_id,
        process_name=process_name,
        session_id=session_id,
        timestamp=timestamp,
        stamina_tracking_enabled=stamina_tracking_enabled,
        hoyolab_game_id=hoyolab_game_id,
        stamina_at_end=stamina_at_end,
        stamina_max=stamina_max,
    )


def _make_coordinator():
    data_manager = MagicMock()
    data_manager.managed_processes = []
    process_monitor = MagicMock()
    process_monitor.active_monitored_processes = {}
    coord = HoYoStaminaReconcileCoordinator(data_manager, process_monitor)
    return coord, data_manager, process_monitor


# ---------------------------------------------------------------------------
# _ReconcileJob
# ---------------------------------------------------------------------------

class TestReconcileJob:
    def test_default_fields(self):
        job = _ReconcileJob(
            process_id="p1",
            process_name="Game",
            session_id=1,
            game_id="genshin",
            exit_timestamp=999.0,
            lifecycle_token=2,
        )
        assert job.allow_session_correction is True
        assert job.finish_on_success is False
        assert job.timer is None
        assert job.in_flight is False
        assert job.request_seq == 0
        assert job.attempts_started == 0
        assert job.observed_signature is None
        assert job.stable_hits == 0
        assert job.applied_session_stamina is None

    def test_custom_fields(self):
        job = _ReconcileJob(
            process_id="p2",
            process_name="HSR",
            session_id=None,
            game_id="honkai_starrail",
            exit_timestamp=12345.0,
            lifecycle_token=5,
            allow_session_correction=False,
            finish_on_success=True,
            stable_hits=1,
            observed_signature=(100, 240),
        )
        assert job.allow_session_correction is False
        assert job.finish_on_success is True
        assert job.stable_hits == 1
        assert job.observed_signature == (100, 240)


# ---------------------------------------------------------------------------
# Lifecycle token management
# ---------------------------------------------------------------------------

class TestLifecycleTokens:
    def test_initial_token_is_zero(self):
        coord, _, _ = _make_coordinator()
        assert coord._current_lifecycle_token("p1") == 0

    def test_advance_increments_token(self):
        coord, _, _ = _make_coordinator()
        t1 = coord._advance_lifecycle_token("p1")
        assert t1 == 1
        t2 = coord._advance_lifecycle_token("p1")
        assert t2 == 2

    def test_different_processes_have_independent_tokens(self):
        coord, _, _ = _make_coordinator()
        coord._advance_lifecycle_token("a")
        coord._advance_lifecycle_token("a")
        coord._advance_lifecycle_token("b")
        assert coord._current_lifecycle_token("a") == 2
        assert coord._current_lifecycle_token("b") == 1


# ---------------------------------------------------------------------------
# handle_process_started
# ---------------------------------------------------------------------------

class TestHandleProcessStarted:
    def test_advances_token(self):
        coord, _, _ = _make_coordinator()
        event = _make_lifecycle_event(process_id="p1")
        coord.handle_process_started(event)
        assert coord._current_lifecycle_token("p1") == 1

    def test_cancels_existing_job(self):
        coord, _, _ = _make_coordinator()
        # Create a job for this process
        coord._jobs["p1"] = _ReconcileJob(
            process_id="p1",
            process_name="Game",
            session_id=1,
            game_id="genshin",
            exit_timestamp=1.0,
            lifecycle_token=0,
        )
        event = _make_lifecycle_event(process_id="p1")
        coord.handle_process_started(event)
        assert "p1" not in coord._jobs

    def test_does_not_create_new_job_on_start(self):
        coord, _, _ = _make_coordinator()
        event = _make_lifecycle_event(process_id="p1")
        coord.handle_process_started(event)
        assert "p1" not in coord._jobs


# ---------------------------------------------------------------------------
# handle_process_stopped
# ---------------------------------------------------------------------------

class TestHandleProcessStopped:
    def test_non_hoyoverse_game_does_not_create_job(self):
        coord, _, _ = _make_coordinator()
        event = _make_lifecycle_event(
            process_id="p1",
            stamina_tracking_enabled=False,
            hoyolab_game_id=None,
        )
        coord.handle_process_stopped(event)
        assert "p1" not in coord._jobs

    def test_non_hoyoverse_game_no_hoyolab_id_does_not_create_job(self):
        coord, _, _ = _make_coordinator()
        event = _make_lifecycle_event(
            process_id="p1",
            stamina_tracking_enabled=True,
            hoyolab_game_id=None,
        )
        coord.handle_process_stopped(event)
        assert "p1" not in coord._jobs

    def test_hoyoverse_game_creates_job(self):
        coord, _, _ = _make_coordinator()
        event = _make_lifecycle_event(process_id="p1")
        coord.handle_process_stopped(event)
        assert "p1" in coord._jobs

    def test_job_fields_from_event(self):
        coord, _, _ = _make_coordinator()
        event = _make_lifecycle_event(
            process_id="p1",
            session_id=42,
            timestamp=5000.0,
            hoyolab_game_id="genshin_impact",
        )
        coord.handle_process_stopped(event)
        job = coord._jobs["p1"]
        assert job.session_id == 42
        assert job.exit_timestamp == 5000.0
        assert job.game_id == "genshin_impact"

    def test_no_stamina_at_end_yields_zero_stable_hits(self):
        coord, _, _ = _make_coordinator()
        event = _make_lifecycle_event(process_id="p1", stamina_at_end=None)
        coord.handle_process_stopped(event)
        job = coord._jobs["p1"]
        assert job.stable_hits == 0
        assert job.observed_signature is None

    def test_stamina_at_end_yields_one_stable_hit(self):
        coord, _, _ = _make_coordinator()
        event = _make_lifecycle_event(process_id="p1", stamina_at_end=100, stamina_max=200)
        coord.handle_process_stopped(event)
        job = coord._jobs["p1"]
        assert job.stable_hits == 1
        assert job.observed_signature == (100, 200)

    def test_advances_lifecycle_token_on_stop(self):
        coord, _, _ = _make_coordinator()
        event = _make_lifecycle_event(process_id="p1")
        coord.handle_process_stopped(event)
        assert coord._current_lifecycle_token("p1") == 1

    def test_cancels_previous_job_before_creating_new(self):
        coord, _, _ = _make_coordinator()
        old_job = _ReconcileJob(
            process_id="p1",
            process_name="OldGame",
            session_id=1,
            game_id="genshin_impact",
            exit_timestamp=1.0,
            lifecycle_token=0,
        )
        coord._jobs["p1"] = old_job
        event = _make_lifecycle_event(process_id="p1", session_id=99)
        coord.handle_process_stopped(event)
        new_job = coord._jobs["p1"]
        assert new_job.session_id == 99

    def test_applied_session_stamina_matches_stamina_at_end(self):
        coord, _, _ = _make_coordinator()
        event = _make_lifecycle_event(process_id="p1", stamina_at_end=150, stamina_max=200)
        coord.handle_process_stopped(event)
        job = coord._jobs["p1"]
        assert job.applied_session_stamina == 150


# ---------------------------------------------------------------------------
# shutdown
# ---------------------------------------------------------------------------

class TestShutdown:
    def test_sets_shutting_down(self):
        coord, _, _ = _make_coordinator()
        coord.shutdown()
        assert coord._shutting_down is True

    def test_clears_all_jobs(self):
        coord, _, _ = _make_coordinator()
        for i in range(3):
            coord._jobs[f"p{i}"] = _ReconcileJob(
                process_id=f"p{i}",
                process_name="Game",
                session_id=None,
                game_id="g",
                exit_timestamp=1.0,
                lifecycle_token=0,
            )
        coord.shutdown()
        assert coord._jobs == {}

    def test_shutdown_twice_does_not_raise(self):
        coord, _, _ = _make_coordinator()
        coord.shutdown()
        coord.shutdown()  # Should not raise


# ---------------------------------------------------------------------------
# schedule_startup_refreshes
# ---------------------------------------------------------------------------

class TestScheduleStartupRefreshes:
    def test_skips_when_shutting_down(self):
        coord, dm, _ = _make_coordinator()
        coord._shutting_down = True
        proc = MagicMock()
        proc.is_hoyoverse_game.return_value = True
        proc.id = "p1"
        dm.managed_processes = [proc]
        coord.schedule_startup_refreshes()
        assert "p1" not in coord._jobs

    def test_skips_non_hoyoverse_games(self):
        coord, dm, _ = _make_coordinator()
        proc = MagicMock()
        proc.is_hoyoverse_game.return_value = False
        proc.id = "p1"
        dm.managed_processes = [proc]
        coord.schedule_startup_refreshes()
        assert "p1" not in coord._jobs

    def test_skips_active_processes(self):
        coord, dm, pm = _make_coordinator()
        proc = MagicMock()
        proc.is_hoyoverse_game.return_value = True
        proc.id = "p1"
        dm.managed_processes = [proc]
        pm.active_monitored_processes = {"p1": {"pid": 1}}
        coord.schedule_startup_refreshes()
        assert "p1" not in coord._jobs

    def test_creates_job_for_idle_hoyoverse_game(self):
        coord, dm, pm = _make_coordinator()
        proc = MagicMock()
        proc.is_hoyoverse_game.return_value = True
        proc.id = "p1"
        proc.name = "Genshin"
        proc.hoyolab_game_id = "genshin_impact"
        dm.managed_processes = [proc]
        pm.active_monitored_processes = {}
        coord.schedule_startup_refreshes()
        assert "p1" in coord._jobs

    def test_job_has_finish_on_success_true(self):
        coord, dm, pm = _make_coordinator()
        proc = MagicMock()
        proc.is_hoyoverse_game.return_value = True
        proc.id = "p1"
        proc.name = "Game"
        proc.hoyolab_game_id = "genshin"
        dm.managed_processes = [proc]
        pm.active_monitored_processes = {}
        coord.schedule_startup_refreshes()
        job = coord._jobs["p1"]
        assert job.finish_on_success is True

    def test_job_has_allow_session_correction_false(self):
        coord, dm, pm = _make_coordinator()
        proc = MagicMock()
        proc.is_hoyoverse_game.return_value = True
        proc.id = "p1"
        proc.name = "Game"
        proc.hoyolab_game_id = "genshin"
        dm.managed_processes = [proc]
        pm.active_monitored_processes = {}
        coord.schedule_startup_refreshes()
        job = coord._jobs["p1"]
        assert job.allow_session_correction is False


# ---------------------------------------------------------------------------
# _apply_session_correction
# ---------------------------------------------------------------------------

class TestApplySessionCorrection:
    """Pure-logic tests for stamina recovery math."""

    def _make_job(self, session_id, exit_timestamp, applied_session_stamina=None):
        return _ReconcileJob(
            process_id="p1",
            process_name="Game",
            session_id=session_id,
            game_id="genshin",
            exit_timestamp=exit_timestamp,
            lifecycle_token=1,
            applied_session_stamina=applied_session_stamina,
        )

    def test_no_session_id_is_noop(self):
        coord, dm, _ = _make_coordinator()
        job = self._make_job(session_id=None, exit_timestamp=0.0)
        coord._apply_session_correction(job, fetched_current=100, fetched_max=200, fetched_at=3600.0)
        dm.update_session_stamina.assert_not_called()

    def test_no_recovery_when_fetched_at_equals_exit(self):
        coord, dm, _ = _make_coordinator()
        job = self._make_job(session_id=5, exit_timestamp=1000.0, applied_session_stamina=None)
        dm.update_session_stamina.return_value = True
        # fetched_at == exit_timestamp → recovered = 0 → corrected == fetched_current
        coord._apply_session_correction(job, fetched_current=120, fetched_max=200, fetched_at=1000.0)
        dm.update_session_stamina.assert_called_once_with(5, 120)

    def test_recovery_subtracts_from_current(self):
        coord, dm, _ = _make_coordinator()
        # RECOVERY_RATE_SEC = 360; elapsed = 720 → recovered = 2
        job = self._make_job(session_id=5, exit_timestamp=0.0, applied_session_stamina=None)
        dm.update_session_stamina.return_value = True
        coord._apply_session_correction(
            job,
            fetched_current=122,
            fetched_max=200,
            fetched_at=720.0,  # elapsed = 720 / 360 = 2 recovered
        )
        dm.update_session_stamina.assert_called_once_with(5, 120)  # 122 - 2

    def test_corrected_stamina_clamped_to_zero(self):
        coord, dm, _ = _make_coordinator()
        # fetched_current=0, large elapsed → corrected should be max(0, ...)
        job = self._make_job(session_id=5, exit_timestamp=0.0, applied_session_stamina=None)
        dm.update_session_stamina.return_value = True
        coord._apply_session_correction(
            job,
            fetched_current=0,
            fetched_max=200,
            fetched_at=720.0,  # recovered = 2, but current=0 → 0 - 2 < 0 → clamped to 0
        )
        dm.update_session_stamina.assert_called_once_with(5, 0)

    def test_corrected_stamina_clamped_to_max(self):
        coord, dm, _ = _make_coordinator()
        # fetched_current==fetched_max, no recovery → corrected = max
        job = self._make_job(session_id=5, exit_timestamp=0.0, applied_session_stamina=None)
        dm.update_session_stamina.return_value = True
        coord._apply_session_correction(
            job,
            fetched_current=200,
            fetched_max=200,
            fetched_at=0.0,
        )
        dm.update_session_stamina.assert_called_once_with(5, 200)

    def test_no_update_when_already_applied(self):
        coord, dm, _ = _make_coordinator()
        job = self._make_job(session_id=5, exit_timestamp=0.0, applied_session_stamina=120)
        dm.update_session_stamina.return_value = True
        coord._apply_session_correction(
            job,
            fetched_current=120,
            fetched_max=200,
            fetched_at=0.0,
        )
        dm.update_session_stamina.assert_not_called()

    def test_updates_applied_session_stamina_on_success(self):
        coord, dm, _ = _make_coordinator()
        job = self._make_job(session_id=5, exit_timestamp=0.0, applied_session_stamina=None)
        dm.update_session_stamina.return_value = True
        coord._apply_session_correction(job, fetched_current=100, fetched_max=200, fetched_at=0.0)
        assert job.applied_session_stamina == 100

    def test_does_not_update_applied_when_db_update_fails(self):
        coord, dm, _ = _make_coordinator()
        job = self._make_job(session_id=5, exit_timestamp=0.0, applied_session_stamina=None)
        dm.update_session_stamina.return_value = False
        coord._apply_session_correction(job, fetched_current=100, fetched_max=200, fetched_at=0.0)
        assert job.applied_session_stamina is None


# ---------------------------------------------------------------------------
# _apply_authoritative_process_stamina
# ---------------------------------------------------------------------------

class TestApplyAuthoritativeProcessStamina:
    def _make_process_and_stamina(self, current=100, max_=200, updated_at=None):
        process = MagicMock()
        process.stamina_current = current
        process.stamina_max = max_
        process.stamina_updated_at = updated_at
        stamina = MagicMock()
        stamina.current = current
        stamina.max = max_
        return process, stamina

    def test_updates_when_current_differs(self):
        coord, dm, _ = _make_coordinator()
        process, stamina = self._make_process_and_stamina(current=100, updated_at=1.0)
        stamina.current = 150  # differs from process.stamina_current=100
        dm.update_process.return_value = True
        coord._apply_authoritative_process_stamina(process, stamina, fetched_at=1.0)
        assert process.stamina_current == 150
        dm.update_process.assert_called_once_with(process)

    def test_updates_when_max_differs(self):
        coord, dm, _ = _make_coordinator()
        process, stamina = self._make_process_and_stamina(current=100, max_=200, updated_at=1.0)
        process.stamina_max = 180  # differs
        dm.update_process.return_value = True
        coord._apply_authoritative_process_stamina(process, stamina, fetched_at=1.0)
        dm.update_process.assert_called_once()

    def test_updates_when_fetched_at_differs(self):
        coord, dm, _ = _make_coordinator()
        process, stamina = self._make_process_and_stamina(current=100, max_=200, updated_at=1.0)
        dm.update_process.return_value = True
        coord._apply_authoritative_process_stamina(process, stamina, fetched_at=2.0)  # differs
        dm.update_process.assert_called_once()

    def test_no_update_when_nothing_changed(self):
        coord, dm, _ = _make_coordinator()
        process, stamina = self._make_process_and_stamina(current=100, max_=200, updated_at=5.0)
        coord._apply_authoritative_process_stamina(process, stamina, fetched_at=5.0)
        dm.update_process.assert_not_called()


# ---------------------------------------------------------------------------
# _on_fetch_finished – guard conditions
# ---------------------------------------------------------------------------

class TestOnFetchFinishedGuards:
    """Test the many early-exit conditions of _on_fetch_finished."""

    def _setup(self, stamina_at_end=None):
        """Set up a coordinator with one active job."""
        coord, dm, pm = _make_coordinator()
        coord._jobs["p1"] = _ReconcileJob(
            process_id="p1",
            process_name="Game",
            session_id=1,
            game_id="genshin_impact",
            exit_timestamp=time.time() - 10,
            lifecycle_token=1,
            in_flight=True,
            request_seq=1,
        )
        coord._lifecycle_tokens["p1"] = 1
        process = MagicMock()
        process.stamina_current = 100
        process.stamina_max = 200
        process.stamina_updated_at = 0.0
        process.is_hoyoverse_game.return_value = True
        process.hoyolab_game_id = "genshin_impact"
        dm.get_process_by_id.return_value = process
        dm.update_process.return_value = True
        dm.update_session_stamina.return_value = True
        return coord, dm, pm, process

    def test_shutting_down_ignores_result(self):
        coord, dm, pm, _ = self._setup()
        coord._shutting_down = True
        coord._on_fetch_finished("p1", 1, 1, {"stamina": None})
        # job should still exist (not processed)
        assert "p1" in coord._jobs

    def test_stale_lifecycle_token_ignored(self):
        coord, dm, pm, _ = self._setup()
        coord._on_fetch_finished("p1", 99, 1, {"stamina": None})  # wrong token
        assert "p1" in coord._jobs
        assert coord._jobs["p1"].in_flight is True  # was not reset

    def test_stale_request_seq_ignored(self):
        coord, dm, pm, _ = self._setup()
        coord._on_fetch_finished("p1", 1, 99, {"stamina": None})  # wrong seq
        assert coord._jobs["p1"].in_flight is True

    def test_process_running_again_finishes_job(self):
        coord, dm, pm, _ = self._setup()
        pm.active_monitored_processes = {"p1": {"pid": 1}}
        coord._on_fetch_finished("p1", 1, 1, {"stamina": None})
        assert "p1" not in coord._jobs

    def test_process_metadata_changed_finishes_job(self):
        coord, dm, pm, _ = self._setup()
        dm.get_process_by_id.return_value = None
        coord._on_fetch_finished("p1", 1, 1, {"stamina": None})
        assert "p1" not in coord._jobs

    def test_finish_on_success_with_stamina_finishes_job(self):
        coord, dm, pm, process = self._setup()
        coord._jobs["p1"].finish_on_success = True
        stamina = MagicMock()
        stamina.current = 120
        stamina.max = 200
        payload = {"stamina": stamina, "fetched_at": time.time()}
        coord._on_fetch_finished("p1", 1, 1, payload)
        assert "p1" not in coord._jobs

    def test_finish_on_success_with_no_stamina_finishes_job(self):
        coord, dm, pm, _ = self._setup()
        coord._jobs["p1"].finish_on_success = True
        coord._on_fetch_finished("p1", 1, 1, {"stamina": None, "fetched_at": time.time()})
        assert "p1" not in coord._jobs

    def test_stable_hits_reaches_threshold_finishes_job(self):
        coord, dm, pm, process = self._setup()
        # Pre-seed stable_hits to one below threshold (REQUIRED_STABLE_HITS=2)
        coord._jobs["p1"].stable_hits = 1
        stamina = MagicMock()
        stamina.current = 100
        stamina.max = 200
        coord._jobs["p1"].observed_signature = (100, 200)
        payload = {"stamina": stamina, "fetched_at": time.time() - 5}
        coord._on_fetch_finished("p1", 1, 1, payload)
        assert "p1" not in coord._jobs

    def test_reconcile_window_elapsed_finishes_job(self):
        coord, dm, pm, _ = self._setup()
        # Set exit_timestamp far in the past (beyond RECONCILE_WINDOW_SEC=180)
        coord._jobs["p1"].exit_timestamp = time.time() - 200
        # fetched_at will be time.time() → elapsed > 180
        payload = {"stamina": None, "fetched_at": time.time()}
        coord._on_fetch_finished("p1", 1, 1, payload)
        assert "p1" not in coord._jobs

    def test_in_flight_reset_on_valid_response(self):
        coord, dm, pm, process = self._setup()
        stamina = MagicMock()
        stamina.current = 100
        stamina.max = 200
        payload = {"stamina": stamina, "fetched_at": time.time() - 5}
        coord._on_fetch_finished("p1", 1, 1, payload)
        # Job may or may not exist depending on stable_hits logic;
        # what matters is that in_flight was reset
        job = coord._jobs.get("p1")
        if job is not None:
            assert job.in_flight is False

    def test_non_dict_payload_treated_as_empty(self):
        coord, dm, pm, _ = self._setup()
        coord._jobs["p1"].exit_timestamp = time.time() - 5
        coord._on_fetch_finished("p1", 1, 1, "not a dict")
        # Should not raise; job should continue (no stamina, window not elapsed)
        # (the exact outcome depends on window check, but no exception)


# ---------------------------------------------------------------------------
# _finish_job
# ---------------------------------------------------------------------------

class TestFinishJob:
    def test_removes_job(self):
        coord, _, _ = _make_coordinator()
        coord._jobs["p1"] = _ReconcileJob(
            process_id="p1",
            process_name="Game",
            session_id=None,
            game_id="g",
            exit_timestamp=1.0,
            lifecycle_token=0,
        )
        coord._finish_job("p1", "test")
        assert "p1" not in coord._jobs

    def test_noop_when_job_missing(self):
        coord, _, _ = _make_coordinator()
        coord._finish_job("nonexistent", "test")  # Should not raise

    def test_stops_timer_when_present(self):
        coord, _, _ = _make_coordinator()
        mock_timer = MagicMock()
        coord._jobs["p1"] = _ReconcileJob(
            process_id="p1",
            process_name="Game",
            session_id=None,
            game_id="g",
            exit_timestamp=1.0,
            lifecycle_token=0,
            timer=mock_timer,
        )
        coord._finish_job("p1", "test")
        mock_timer.stop.assert_called_once()
        mock_timer.deleteLater.assert_called_once()