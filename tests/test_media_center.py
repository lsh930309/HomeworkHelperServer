"""실제 오디오/Windows/DB 없이 worker 수명주기와 사용자 전환 계약을 검증한다."""
import asyncio
from contextlib import contextmanager
from dataclasses import FrozenInstanceError, replace
import os
import threading
import time

import pytest

from src.core.game_audio import GameAudioObservation, GameAudioTarget
from src.core.media_center import MediaCenterRuntime, MediaOptions
from src.core.media_sessions import MediaSessionInfo
from src.core.spotify_audio import SpotifyAudioSnapshot


def session(session_id="spotify", app_id="Spotify.exe", status="paused"):
    return MediaSessionInfo(session_id, app_id, status=status, can_play=True, can_pause=True)


def wait_for(condition, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.005)
    assert condition(), "worker 결과가 제한 시간에 도착하지 않았습니다."


class Backend:
    def __init__(self, sessions=()):
        self.sessions = tuple(sessions)
        self.commands = []
        self.reads = 0
        self.delay = 0
        self.error = None
        self.closed = False
        self.threads = set()
        self.busy = False
        self.control_entered = threading.Event()
        self.control_cancelled = threading.Event()
        self.block_control = False
        self.accept = True
        self.processes = ()
        self.process_error = None
        self.process_reads = 0

    async def snapshot(self):
        assert not self.busy, "snapshot/control must be serial"
        self.busy = True
        self.threads.add(threading.get_ident())
        try:
            self.reads += 1
            await asyncio.sleep(self.delay)
            if self.error:
                raise self.error
            return self.sessions
        finally:
            self.busy = False

    async def control(self, session_id, action):
        assert not self.busy, "snapshot/control must be serial"
        self.busy = True
        self.threads.add(threading.get_ident())
        self.control_entered.set()
        try:
            while self.block_control:
                await asyncio.sleep(0.01)
            self.commands.append((session_id, action))
            if not self.accept:
                return False
            if action in {"play", "pause"}:
                self.sessions = tuple(replace(item, status="playing" if action == "play" else "paused")
                                      if item.session_id == session_id else item
                                      for item in self.sessions)
            return True
        except asyncio.CancelledError:
            self.control_cancelled.set()
            raise
        finally:
            self.busy = False

    def close(self):
        self.threads.add(threading.get_ident())
        self.closed = True


class Audio:
    def __init__(self):
        self.targets = ()
        self.calls = []
        self.observed = {}
        self.cleaned = False
        self.cleanup_result = True
        self.threads = set()

    def update_targets(self, targets):
        self.targets = targets

    def reconcile(self, foreground_pid, *, background_mute):
        self.threads.add(threading.get_ident())
        self.calls.append((foreground_pid, background_mute))
        return tuple(GameAudioObservation(
            target, True, 0.5, target.user_muted,
            background_mute and target.pid != foreground_pid,
            self.observed.get(target.pid, not target.user_muted),
        ) for target in self.targets)

    def cleanup(self):
        self.threads.add(threading.get_ident())
        self.cleaned = True
        return self.cleanup_result


class SpotifyAudio:
    def __init__(self):
        self.state = SpotifyAudioSnapshot(37, False, True)
        self.commands, self.threads = [], set()
        self.accept = True

    def snapshot(self):
        self.threads.add(threading.get_ident())
        return self.state

    def set_volume(self, value):
        self.threads.add(threading.get_ident())
        self.commands.append(("volume", value))
        if self.accept:
            self.state = replace(self.state, volume=value)
        return self.accept

    def set_mute(self, value):
        self.threads.add(threading.get_ident())
        self.commands.append(("mute", value))
        if self.accept:
            self.state = replace(self.state, muted=value)
        return self.accept


class WindowMinimizer:
    """실제 창을 건드리지 않고 late window·guard·1회 적용을 관측한다."""
    def __init__(self):
        self.ready = False
        self.error = None
        self.before_apply = None
        self.calls, self.writes, self.guards_after_cancel = [], [], []

    def __call__(self, started_after, *, is_current):
        self.calls.append((started_after, threading.get_ident(), time.time()))
        if self.error:
            raise self.error
        if not self.ready:
            return False
        if self.before_apply is not None:
            self.before_apply()
            self.before_apply = None
            self.guards_after_cancel.append(is_current())
        if not is_current():
            return False
        self.writes.append(started_after)
        return True


class Native:
    def __init__(self):
        self.current = (100, 1000)

    def foreground(self):
        return self.current


class Focus:
    def __init__(self, **kwargs):
        self.arguments = kwargs
        self.ticks = []
        self.cancelled = False

    def tick(self, *args):
        self.ticks.append(args)

    def cancel(self):
        self.cancelled = True


@contextmanager
def running(sessions=None, *, options=MediaOptions(), targets=(), processes=(), minimizer=None):
    backend, audio, native = Backend((session(),) if sessions is None else sessions), Audio(), Native()
    launches, changes, focuses = [], [], []
    backend.processes = processes

    def read_processes():
        backend.process_reads += 1
        backend.threads.add(threading.get_ident())
        if backend.process_error:
            raise backend.process_error
        return tuple(backend.processes)

    def focus_factory(**kwargs):
        focus = Focus(**kwargs)
        focuses.append(focus)
        return focus

    runtime = MediaCenterRuntime(
        changes.append, backend_factory=lambda: backend, audio_factory=lambda: audio,
        native_factory=lambda: native, focus_factory=focus_factory,
        spotify_launcher=lambda: launches.append("normal") or True,
        dj_launcher=lambda: launches.append("dj") or True,
        spotify_process_reader=read_processes, spotify_audio_factory=SpotifyAudio,
        spotify_window_minimizer=minimizer if minimizer is not None else lambda started_after, *, is_current: True,
    )
    runtime.POLL_SECONDS = 0.01
    runtime.IO_TIMEOUT_SECONDS = 0.5
    runtime.PREPARE_TIMEOUT_SECONDS = 0.15
    runtime.update_targets(targets)
    runtime.start(options)
    try:
        wait_for(lambda: backend.reads > 0)
        yield runtime, backend, audio, native, launches, changes, focuses
    finally:
        assert runtime.stop()


def test_constructor_and_inactive_configuration_have_no_io():
    def forbidden(*args, **kwargs):
        raise AssertionError("explicit start required")

    runtime = MediaCenterRuntime(backend_factory=forbidden, audio_factory=forbidden,
                                 native_factory=forbidden, focus_factory=forbidden,
                                 spotify_launcher=forbidden, dj_launcher=forbidden,
                                 spotify_process_reader=forbidden, spotify_audio_factory=forbidden,
                                 spotify_window_minimizer=forbidden)
    assert runtime.configure(MediaOptions(False, False, False))
    runtime.update_targets(())
    assert not runtime.running and not runtime.request("play")
    assert runtime.stop()
    assert not runtime.configure(MediaOptions())
    with pytest.raises(FrozenInstanceError):
        runtime.snapshot.error = "mutable"


def test_initial_trigger_plays_once_and_manual_pause_is_not_undone():
    with running() as (runtime, backend, *_):
        wait_for(lambda: backend.commands == [("spotify", "play")])
        assert runtime.request("pause")
        wait_for(lambda: backend.commands[-1] == ("spotify", "pause"))
        reads = backend.reads
        wait_for(lambda: backend.reads > reads + 5)
        assert backend.commands == [("spotify", "play"), ("spotify", "pause")]


def test_focused_game_audible_edges_pause_and_resume_but_unknown_does_not_resume():
    target = GameAudioTarget("game", 42, 1, "/game.exe", False, 50)
    with running(targets=(target,)) as (runtime, backend, audio, native, *_):
        wait_for(lambda: backend.commands == [("spotify", "play")])
        native.current = (42, 420)
        wait_for(lambda: backend.commands[-1] == ("spotify", "pause"))
        audio.observed[42] = None
        time.sleep(0.04)
        assert len(backend.commands) == 2
        audio.observed[42] = False
        wait_for(lambda: backend.commands[-1] == ("spotify", "play"))
        assert len(backend.commands) == 3
        assert not target.user_muted


def test_background_mute_failure_cannot_be_treated_as_quiet_for_automatic_play():
    target = GameAudioTarget("game", 42, 1, "/game.exe", False, 55)
    with running(options=MediaOptions(False), targets=(target,)) as (runtime, backend, audio, native, *_):
        # 브라우저가 전경인 상태에서 게임의 실제 음소거 적용/조회가 실패했다.
        audio.reconcile = lambda *_args, **_kwargs: (
            GameAudioObservation(target, False, None, None, True, None),)
        wait_for(lambda: runtime.snapshot.game_audio and not runtime.snapshot.game_audio[0].available)
        runtime.configure(MediaOptions())
        reads = backend.reads
        wait_for(lambda: backend.reads > reads + 5)
        assert backend.commands == [], "음소거 확인 실패를 무음으로 간주해 BGM을 자동 재생했다"
        # 실제 무음이 확인된 뒤에만 처음 유효한 자동 재생을 허용한다.
        audio.reconcile = lambda *_args, **_kwargs: (
            GameAudioObservation(target, True, .55, True, True, False),)
        wait_for(lambda: backend.commands == [("spotify", "play")])


def test_disabled_background_policy_does_not_gate_bgm_on_an_unfocused_game():
    target = GameAudioTarget("game", 42, 1, "/game.exe", False, 55)
    with running(options=MediaOptions(False, False, False), targets=(target,)) as (runtime, backend, audio, *_):
        audio.reconcile = lambda *_args, **_kwargs: (
            GameAudioObservation(target, False, None, None, False, None),)
        wait_for(lambda: runtime.snapshot.game_audio and not runtime.snapshot.game_audio[0].available)
        runtime.configure(MediaOptions(True, False, False))
        wait_for(lambda: backend.commands == [("spotify", "play")])


def test_other_media_pause_close_and_game_exit_do_not_bypass_hold():
    target = GameAudioTarget("game", 42, 1, "/game.exe", False, 50)
    with running(targets=(target,)) as (runtime, backend, audio, native, *_):
        wait_for(lambda: backend.commands == [("spotify", "play")])
        firefox = session("firefox", "Firefox.exe", "playing")
        backend.sessions += (firefox,)
        wait_for(lambda: runtime.snapshot.media_hold)
        wait_for(lambda: backend.commands[-1] == ("spotify", "pause"))
        backend.sessions = (session(), replace(firefox, status="paused"))
        native.current = (42, 420)
        wait_for(lambda: audio.calls[-1][0] == 42)
        backend.sessions = (session(),)
        native.current = (100, 1000)
        time.sleep(0.06)
        assert backend.commands == [("spotify", "play"), ("spotify", "pause")]
        assert runtime.request("play")
        wait_for(lambda: backend.commands[-1] == ("spotify", "play"))
        assert not runtime.snapshot.media_hold


def test_own_ui_preserves_game_context_and_null_foreground_is_unknown():
    target = GameAudioTarget("game", 42, 1, "/game.exe", False, 50)
    with running(targets=(target,)) as (_runtime, backend, audio, native, *_):
        native.current = (42, 420)
        wait_for(lambda: audio.calls[-1][0] == 42)
        native.current = (os.getpid(), 991)
        before = len(backend.commands)
        time.sleep(0.04)
        assert audio.calls[-1] == (42, True)
        assert len(backend.commands) == before
        native.current = (0, 0)
        time.sleep(0.04)
        assert audio.calls[-1] == (42, True)
        assert len(backend.commands) == before


def test_media_metadata_delay_does_not_block_audio_and_all_io_stays_on_one_worker():
    with running(options=MediaOptions(False)) as (runtime, backend, audio, *_):
        backend.delay = 0.12
        reads, audio_calls = backend.reads, len(audio.calls)
        wait_for(lambda: backend.reads > reads)
        wait_for(lambda: len(audio.calls) > audio_calls + 5)
        assert runtime.running
    assert backend.closed and audio.cleaned
    assert len(backend.threads | audio.threads) == 1
    assert threading.get_ident() not in backend.threads


def test_prepare_and_play_share_one_launch_and_expired_intent_does_not_restart():
    with running((), options=MediaOptions(False)) as (runtime, backend, _, _, launches, *_):
        assert runtime.request("prepare")
        wait_for(lambda: len(launches) == 1)
        assert not backend.commands
        assert runtime.request("play")
        time.sleep(.03)
        assert len(launches) == 1
        wait_for(lambda: "만료" in runtime.snapshot.error)
        backend.sessions = (session(),)
        time.sleep(0.04)
        assert not backend.commands and len(launches) == 1


def test_pending_play_is_cancelled_by_manual_pause_before_spotify_appears():
    with running(()) as (runtime, backend, _, _, launches, *_):
        wait_for(lambda: len(launches) == 1)
        assert runtime.request("pause")
        time.sleep(0.03)
        backend.sessions = (session(),)
        time.sleep(0.06)
        assert not backend.commands and len(launches) == 1


def test_pending_automatic_play_rechecks_game_state_before_sending():
    target = GameAudioTarget("game", 42, 1, "/game.exe", False, 50)
    with running((), targets=(target,)) as (runtime, backend, audio, native, launches, *_):
        wait_for(lambda: len(launches) == 1)
        native.current = (42, 420)
        wait_for(lambda: audio.calls[-1][0] == 42)
        backend.sessions = (session(),)
        time.sleep(0.05)
        assert not backend.commands


def test_multiple_spotify_sessions_need_selection_and_manual_non_bgm_control_is_explicit():
    with running((session("a"), session("b"))) as (runtime, backend, *_):
        wait_for(lambda: "여러 개" in runtime.snapshot.error)
        assert not backend.commands and runtime.snapshot.bgm_session_id is None
        assert runtime.request("select", "b")
        wait_for(lambda: runtime.snapshot.bgm_session_id == "b")
        assert runtime.request("play")
        wait_for(lambda: backend.commands == [("b", "play")])
        backend.sessions += (session("firefox", "Firefox.exe"),)
        wait_for(lambda: len(runtime.snapshot.sessions) == 3)
        assert runtime.request("play", "firefox")
        wait_for(lambda: ("firefox", "play") in backend.commands)
        assert all(command != ("a", "play") for command in backend.commands)


def test_old_selected_session_is_not_replaced_for_manual_control():
    with running((session("spotify"), session("other")), options=MediaOptions(False)) as (runtime, backend, *_):
        assert runtime.request("select", "spotify")
        wait_for(lambda: runtime.snapshot.bgm_session_id == "spotify")
        backend.sessions = (session("new"),)
        wait_for(lambda: runtime.snapshot.bgm_session_id is None)
        assert runtime.request("play", "spotify")
        time.sleep(0.04)
        assert not backend.commands


def test_stop_cancels_inflight_command_and_rejects_late_requests():
    with running(options=MediaOptions(False)) as (runtime, backend, audio, *_):
        backend.block_control = True
        assert runtime.request("play")
        assert backend.control_entered.wait(1)
        assert runtime.stop(timeout_seconds=0.5)
        assert backend.control_cancelled.is_set()
        assert not backend.commands and backend.closed and audio.cleaned
        assert not runtime.running and not runtime.request("play")
        assert not runtime.snapshot.running


def test_media_failure_preserves_game_observation_and_does_not_send_stale_commands():
    with running(options=MediaOptions(False)) as (runtime, backend, audio, *_):
        backend.error = OSError("unavailable")
        wait_for(lambda: "조회 실패" in runtime.snapshot.error)
        before = len(audio.calls)
        assert runtime.request("play")
        wait_for(lambda: len(audio.calls) > before + 3)
        assert not backend.commands


def test_options_disable_pending_auto_and_focus_reenable_baselines_existing_games():
    with running(()) as (runtime, backend, audio, native, launches, changes, focuses):
        wait_for(lambda: len(launches) == 1)
        runtime.configure(MediaOptions(False, False, False))
        wait_for(lambda: audio.calls[-1][1] is False)
        backend.sessions = (session(),)
        time.sleep(0.04)
        assert not backend.commands and focuses[0].cancelled
        runtime.configure(MediaOptions(False, False, True))
        wait_for(lambda: len(focuses) == 2)
        assert focuses[1].ticks


def test_reapplying_identical_options_does_not_cancel_pending_play():
    options = MediaOptions()
    with running((), options=options) as (runtime, backend, _, _, launches, *_):
        wait_for(lambda: len(launches) == 1)
        runtime.configure(options)
        backend.sessions = (session(),)
        wait_for(lambda: backend.commands == [("spotify", "play")])
        assert len(launches) == 1


def test_command_rejection_stays_visible_after_successful_state_reads():
    with running(options=MediaOptions(False)) as (runtime, backend, *_):
        backend.accept = False
        assert runtime.request("play")
        wait_for(lambda: "수락하지" in runtime.snapshot.error)
        reads = backend.reads
        wait_for(lambda: backend.reads > reads + 4)
        assert "수락하지" in runtime.snapshot.error
        assert runtime.snapshot.sessions[0].status == "paused"
        backend.accept = True
        assert runtime.request("play")
        wait_for(lambda: not runtime.snapshot.error)


def test_stop_reports_restore_failure_without_leaving_a_worker_alive():
    backend, audio = Backend(), Audio()
    audio.cleanup_result = False
    runtime = MediaCenterRuntime(backend_factory=lambda: backend, audio_factory=lambda: audio,
                                 native_factory=Native, focus_factory=Focus,
                                 spotify_process_reader=lambda: (), spotify_audio_factory=SpotifyAudio,
                                 spotify_launcher=lambda: True, dj_launcher=lambda: True,
                                 spotify_window_minimizer=lambda started_after, *, is_current: True)
    runtime.POLL_SECONDS = 0.01
    runtime.start(MediaOptions(False))
    wait_for(lambda: backend.reads > 0)
    assert not runtime.stop()
    assert not runtime.running and backend.closed and audio.cleaned
    assert "복원하지" in runtime.snapshot.error
    assert not runtime.configure(MediaOptions())


def test_snapshot_timeout_keeps_audio_loop_alive_and_stop_cleans_up():
    with running(options=MediaOptions(False)) as (runtime, backend, audio, *_):
        runtime.IO_TIMEOUT_SECONDS = 0.02
        backend.delay = 1
        wait_for(lambda: "조회 실패" in runtime.snapshot.error)
        before = len(audio.calls)
        wait_for(lambda: len(audio.calls) > before + 3)
        assert runtime.running and not backend.commands


def test_runtime_can_restart_only_after_worker_finished_with_a_fresh_epoch():
    with running(options=MediaOptions(False)) as (runtime, backend, *_):
        assert runtime.request("pause")
        assert runtime.stop()
        first_epoch = runtime._epoch
        runtime.start(MediaOptions(False))
        wait_for(lambda: runtime.running and runtime.snapshot.running)
        assert runtime._epoch == first_epoch + 1
        assert not runtime.snapshot.media_hold


def test_cold_play_launches_dj_once_and_waits_for_play_capability():
    with running(()) as (runtime, backend, _, _, launches, *_):
        runtime.PREPARE_TIMEOUT_SECONDS = .5
        wait_for(lambda: launches == ["dj"])
        backend.sessions = (replace(session(), status="opened", can_play=False),)
        wait_for(lambda: runtime.snapshot.sessions == backend.sessions)
        before_deadline = runtime._pending.deadline
        for _ in range(5):
            assert runtime.request("prepare") and runtime.request("play")
            time.sleep(.005)
        wait_for(lambda: not runtime._requests)
        assert not backend.commands and launches == ["dj"]
        assert runtime._pending.deadline == before_deadline
        backend.sessions = (session(),)
        wait_for(lambda: backend.commands == [("spotify", "play")])
        time.sleep(.03)
        assert launches == ["dj"] and backend.commands == [("spotify", "play")]


def test_login_autostart_process_waits_for_session_without_another_uri():
    with running((), processes=(object(),)) as (runtime, backend, _, _, launches, *_):
        wait_for(lambda: runtime._pending is not None)
        assert backend.process_reads == 1 and launches == []
        assert runtime.request("prepare") and runtime.request("play")
        time.sleep(.03)
        assert not backend.commands and not launches and backend.process_reads == 1
        backend.sessions = (session(),)
        wait_for(lambda: backend.commands == [("spotify", "play")])
        assert threading.get_ident() not in backend.threads


def test_already_playing_session_completes_cold_preparation_without_play_command():
    with running(()) as (runtime, backend, _, _, launches, *_):
        wait_for(lambda: launches == ["dj"])
        backend.sessions = (session(status="playing"),)
        wait_for(lambda: runtime.snapshot.sessions == backend.sessions and runtime._pending is None)
        assert not backend.commands and launches == ["dj"]


def test_warm_play_resumes_existing_session_without_dj_or_process_lookup():
    with running(options=MediaOptions(False)) as (runtime, backend, _, _, launches, *_):
        assert runtime.request("play")
        wait_for(lambda: backend.commands == [("spotify", "play")])
        for _ in range(5):
            assert runtime.request("play")
        time.sleep(.04)
        assert backend.commands == [("spotify", "play")] and not launches and backend.process_reads == 0


def test_prepare_only_opens_normal_app_once_and_never_creates_play_intent():
    with running((), options=MediaOptions(False)) as (runtime, backend, _, _, launches, *_):
        assert runtime.request("prepare")
        wait_for(lambda: launches == ["normal"])
        for _ in range(10):
            assert runtime.request("prepare")
        backend.sessions = (session(),)
        wait_for(lambda: runtime.snapshot.sessions == backend.sessions and runtime._pending is None)
        assert runtime.request("prepare")
        time.sleep(.03)
        assert launches == ["normal"] and not backend.commands


def test_repeated_prepare_play_does_not_extend_initial_deadline():
    with running((), options=MediaOptions(False)) as (runtime, backend, _, _, launches, *_):
        assert runtime.request("prepare")
        wait_for(lambda: launches == ["normal"])
        deadline = runtime._pending.deadline
        for _ in range(8):
            assert runtime.request("play") and runtime.request("prepare")
            time.sleep(.008)
        assert runtime._pending.deadline == deadline
        wait_for(lambda: "만료" in runtime.snapshot.error)
        backend.sessions = (session(),)
        time.sleep(.04)
        assert launches == ["normal"] and not backend.commands


def test_other_media_cancels_delayed_automatic_play_and_hold_survives_close():
    with running(()) as (runtime, backend, _, _, launches, *_):
        wait_for(lambda: launches == ["dj"])
        backend.sessions = (session("firefox", "Firefox.exe", "playing"),)
        wait_for(lambda: runtime.snapshot.media_hold and runtime._pending is None)
        backend.sessions = (session(),)
        time.sleep(.04)
        assert not backend.commands and launches == ["dj"]


def test_selection_cancels_preparation_instead_of_retargeting_late_play():
    with running((), options=MediaOptions(False), processes=(object(),)) as (runtime, backend, *_):
        assert runtime.request("play")
        wait_for(lambda: runtime._pending is not None)
        backend.sessions = (session("a"), session("b"))
        wait_for(lambda: len(runtime.snapshot.sessions) == 2)
        assert runtime.request("select", "b")
        wait_for(lambda: runtime.snapshot.bgm_session_id == "b")
        assert runtime._pending is None and not backend.commands


def test_explicit_dj_sends_one_content_uri_and_does_not_enforce_it_periodically():
    with running(options=MediaOptions(False)) as (runtime, backend, _, _, launches, *_):
        for _ in range(10):
            assert runtime.request("dj")
        wait_for(lambda: backend.commands == [("spotify", "play")])
        assert launches == ["dj"]
        backend.sessions = (session(status="paused"),)
        time.sleep(.04)
        assert launches == ["dj"] and backend.commands == [("spotify", "play")]


def test_explicit_dj_upgrades_existing_preparation_without_resetting_deadline():
    with running((), options=MediaOptions(False)) as (runtime, backend, _, _, launches, *_):
        assert runtime.request("prepare")
        wait_for(lambda: launches == ["normal"])
        deadline = runtime._pending.deadline
        assert runtime.request("dj")
        wait_for(lambda: launches == ["normal", "dj"])
        assert runtime._pending.deadline == deadline
        assert runtime.request("dj") and runtime.request("prepare")
        backend.sessions = (session(),)
        wait_for(lambda: backend.commands == [("spotify", "play")])
        assert launches == ["normal", "dj"]


def test_process_observation_error_does_not_guess_absent_and_launch():
    with running((), options=MediaOptions(False)) as (runtime, backend, _, _, launches, *_):
        backend.process_error = OSError("권한 없음")
        assert runtime.request("play")
        wait_for(lambda: "실행 상태 조회 실패" in runtime.snapshot.error)
        assert not launches and not backend.commands and runtime._pending is None


def test_spotify_volume_and_mute_are_real_worker_observations_without_autoplay():
    with running(options=MediaOptions(False)) as (runtime, backend, _, _, launches, *_):
        wait_for(lambda: runtime.snapshot.spotify_audio == SpotifyAudioSnapshot(37, False, True))
        controller = runtime._spotify_audio
        generation = runtime._generation
        assert runtime.request("volume", value=62) and runtime.request("mute", value=True)
        wait_for(lambda: runtime.snapshot.spotify_audio == SpotifyAudioSnapshot(62, True, True))
        assert controller.commands == [("volume", 62), ("mute", True)]
        assert runtime._generation == generation and not backend.commands and not launches
        controller.state = SpotifyAudioSnapshot(19, False, True)
        wait_for(lambda: runtime.snapshot.spotify_audio == controller.state)
        assert len(controller.commands) == 2 and threading.get_ident() not in controller.threads


def test_volume_and_mute_do_not_cancel_pending_play_or_publish_unapplied_values():
    with running(()) as (runtime, backend, _, _, launches, *_):
        wait_for(lambda: launches == ["dj"])
        controller, deadline = runtime._spotify_audio, runtime._pending.deadline
        controller.accept = False
        assert runtime.request("volume", value=81)
        wait_for(lambda: "실제로 적용" in runtime.snapshot.error)
        assert runtime.snapshot.spotify_audio.volume == 37
        assert runtime._pending.deadline == deadline
        controller.accept = True
        assert runtime.request("mute", value=True)
        backend.sessions = (session(),)
        wait_for(lambda: backend.commands == [("spotify", "play")])
        assert runtime.snapshot.spotify_audio == SpotifyAudioSnapshot(37, True, True)
        assert launches == ["dj"]


@pytest.mark.parametrize("action,value", [("volume", -1), ("volume", 101), ("volume", True),
                                         ("volume", 1.1), ("volume", None), ("mute", 1), ("mute", None),
                                         ("play", 42)])
def test_invalid_spotify_mix_requests_do_not_queue_or_write(action, value):
    with running(options=MediaOptions(False)) as (runtime, backend, *_):
        assert not runtime.request(action, value=value)
        assert not runtime._spotify_audio.commands and not backend.commands


def test_play_pause_play_keeps_last_intent_and_does_not_use_pre_pause_playing_snapshot():
    with running((session(status="playing"),), options=MediaOptions(False)) as (runtime, backend, *_):
        backend.delay = .03
        before = backend.reads
        wait_for(lambda: backend.reads > before)
        assert runtime.request("play") and runtime.request("pause") and runtime.request("play")
        wait_for(lambda: backend.commands == [("spotify", "pause"), ("spotify", "play")])
        assert backend.sessions[0].status == "playing"


@pytest.mark.parametrize("action,status", [("prepare", "paused"), ("play", "playing")])
def test_warm_success_clears_prior_command_failure_without_another_control(action, status):
    with running(options=MediaOptions(False)) as (runtime, backend, _, _, launches, *_):
        backend.accept = False
        assert runtime.request("play")
        wait_for(lambda: "수락하지" in runtime.snapshot.error)
        backend.sessions = (session(status=status),)
        wait_for(lambda: runtime.snapshot.sessions == backend.sessions)
        before = list(backend.commands)
        assert runtime.request(action)
        wait_for(lambda: not runtime.snapshot.error)
        assert backend.commands == before and not launches


@pytest.mark.parametrize("action,status", [("prepare", "paused"), ("play", "playing")])
def test_new_preparation_after_timeout_clears_error_only_when_session_is_ready(action, status):
    with running((), options=MediaOptions(False), processes=(object(),)) as (runtime, backend, _, _, launches, *_):
        assert runtime.request("prepare")
        wait_for(lambda: "만료" in runtime.snapshot.error)
        assert runtime.request(action)
        wait_for(lambda: runtime._pending is not None)
        assert "만료" in runtime.snapshot.error
        backend.sessions = (session(status=status),)
        wait_for(lambda: runtime._pending is None and not runtime.snapshot.error)
        assert not backend.commands and not launches


def test_warm_prepare_or_already_playing_does_not_clear_spotify_audio_failure():
    with running(options=MediaOptions(False)) as (runtime, backend, *_):
        runtime._spotify_audio.accept = False
        assert runtime.request("volume", value=80)
        wait_for(lambda: "실제로 적용" in runtime.snapshot.error)
        error = runtime.snapshot.error
        assert runtime.request("prepare")
        backend.sessions = (session(status="playing"),)
        wait_for(lambda: runtime.snapshot.sessions == backend.sessions)
        assert runtime.request("play")
        time.sleep(.03)
        assert runtime.snapshot.error == error


def test_same_play_on_every_ready_snapshot_does_not_starve_pending_completion(monkeypatch):
    with running((), options=MediaOptions(False)) as (runtime, backend, _, _, launches, *_):
        runtime.PREPARE_TIMEOUT_SECONDS = .5
        assert runtime.request("play")
        wait_for(lambda: runtime._pending is not None)
        deadline = runtime._pending.deadline
        snapshot = backend.snapshot
        repeated = []
        async def ready_snapshot_with_same_request():
            result = await snapshot()
            repeated.append(runtime.request("play"))
            return result
        monkeypatch.setattr(backend, "snapshot", ready_snapshot_with_same_request)
        backend.sessions = (session(),)
        wait_for(lambda: backend.commands == [("spotify", "play")], timeout=.15)
        assert time.monotonic() < deadline and runtime._pending is None
        before = len(repeated)
        wait_for(lambda: len(repeated) >= before + 4)
        assert all(repeated) and backend.commands == [("spotify", "play")] and launches == ["dj"]


@pytest.mark.parametrize("native_status", ["paused", "playing"])
def test_cold_background_prepare_waits_for_late_window_without_replaying(native_status):
    minimizer = WindowMinimizer()
    with running((), options=MediaOptions(False), minimizer=minimizer) as (runtime, backend, _, _, launches, *_):
        runtime.PREPARE_TIMEOUT_SECONDS = .5
        requested_at = time.time()
        assert runtime.request("play")
        wait_for(lambda: launches == ["dj"] and bool(minimizer.calls))
        deadline = runtime._pending.deadline
        backend.sessions = (session(status=native_status),)
        expected = [("spotify", "play")] if native_status == "paused" else []
        wait_for(lambda: runtime.snapshot.sessions and runtime.snapshot.sessions[0].status == "playing")
        assert backend.commands == expected and runtime._pending is not None
        assert runtime._pending.play_requested
        before = len(minimizer.calls)
        for _ in range(3):
            assert runtime.request("play") and runtime.request("prepare")
        wait_for(lambda: len(minimizer.calls) >= before + 2)
        assert runtime._pending.deadline == deadline and not minimizer.writes
        minimizer.ready = True
        wait_for(lambda: len(minimizer.writes) == 1 and runtime._pending is None)
        assert all(requested_at <= started <= invoked for started, _thread, invoked in minimizer.calls)
        assert threading.get_ident() not in {thread for _started, thread, _invoked in minimizer.calls}
        # 사용자가 다시 복원해도 같은 준비를 완료한 후에는 창에 재접근하지 않는다.
        calls = len(minimizer.calls)
        before = backend.reads
        assert runtime.request("prepare") and runtime.request("play")
        wait_for(lambda: backend.reads >= before + 4)
        assert len(minimizer.calls) == calls and len(minimizer.writes) == 1
        assert backend.commands == expected and launches == ["dj"]


def test_prepare_only_keeps_late_window_work_without_adding_play():
    minimizer = WindowMinimizer()
    with running((), options=MediaOptions(False), minimizer=minimizer) as (runtime, backend, _, _, launches, *_):
        assert runtime.request("prepare")
        wait_for(lambda: launches == ["normal"] and bool(minimizer.calls))
        backend.sessions = (session(),)
        wait_for(lambda: runtime.snapshot.sessions == backend.sessions)
        assert runtime._pending is not None and not backend.commands
        minimizer.ready = True
        wait_for(lambda: minimizer.writes and runtime._pending is None)
        assert not backend.commands and launches == ["normal"]


@pytest.mark.parametrize("action,existing_session", [("play", True), ("play", False), ("dj", True), ("dj", False)])
def test_warm_process_or_session_is_never_automatically_minimized(action, existing_session):
    minimizer = WindowMinimizer()
    minimizer.ready = True
    with running((session(),) if existing_session else (), options=MediaOptions(False),
                 processes=(object(),), minimizer=minimizer) as (runtime, backend, _, _, launches, *_):
        assert runtime.request(action)
        if not existing_session:
            wait_for(lambda: runtime._pending is not None)
            backend.sessions = (session(),)
        wait_for(lambda: backend.commands == [("spotify", "play")])
        before = backend.reads
        wait_for(lambda: backend.reads >= before + 3)
        assert not minimizer.calls and not minimizer.writes
        assert launches == (["dj"] if action == "dj" else [])


@pytest.mark.parametrize("cancel", ["pause", "select", "stop", "auto-off", "audible-game", "other-media", "deadline"])
def test_cancelled_or_expired_preparation_never_handles_late_window(cancel):
    minimizer = WindowMinimizer()
    target = GameAudioTarget("game", 42, 1, "/game.exe", False, 50)
    with running((), targets=(target,), minimizer=minimizer) as (runtime, backend, _, native, launches, *_):
        wait_for(lambda: launches == ["dj"] and bool(minimizer.calls))
        if cancel == "pause":
            assert runtime.request("pause")
        elif cancel == "select":
            backend.sessions = (session("a"), session("b"))
            wait_for(lambda: len(runtime.snapshot.sessions) == 2)
            assert runtime.request("select", "b")
        elif cancel == "stop":
            assert runtime.stop()
        elif cancel == "auto-off":
            assert runtime.configure(MediaOptions(False))
        elif cancel == "audible-game":
            native.current = (42, 420)
        elif cancel == "other-media":
            backend.sessions = (session("firefox", "Firefox.exe", "playing"),)
            wait_for(lambda: runtime.snapshot.media_hold)
        if cancel != "stop":
            wait_for(lambda: runtime._pending is None)
        calls = len(minimizer.calls)
        minimizer.ready = True
        if cancel != "select":
            backend.sessions = (session(),)
        if cancel != "stop":
            before = backend.reads
            wait_for(lambda: backend.reads >= before + 4)
        assert len(minimizer.calls) == calls and not minimizer.writes and not backend.commands
        assert launches == ["dj"]


def test_window_observation_error_is_logged_once_without_failing_playback(caplog):
    minimizer = WindowMinimizer()
    minimizer.error = OSError("minimize fixture failure")
    with running((), options=MediaOptions(False), minimizer=minimizer) as (runtime, backend, _, _, launches, *_):
        assert runtime.request("play")
        wait_for(lambda: bool(minimizer.calls))
        backend.sessions = (session(),)
        wait_for(lambda: backend.commands == [("spotify", "play")] and runtime._pending is None)
        before = backend.reads
        wait_for(lambda: backend.reads >= before + 4)
        assert len(minimizer.calls) == 1 and not minimizer.writes and launches == ["dj"]
        assert not runtime.snapshot.error and runtime.running
        assert "minimize fixture failure" in caplog.text


@pytest.mark.parametrize("cancel", ["pause", "auto-off"])
def test_native_window_guard_rechecks_cancellation_immediately_before_application(cancel):
    minimizer = WindowMinimizer()
    with running((), minimizer=minimizer) as (runtime, backend, *_):
        wait_for(lambda: bool(minimizer.calls))
        minimizer.before_apply = (lambda: runtime.request("pause")) if cancel == "pause" else (
            lambda: runtime.configure(MediaOptions(False)))
        minimizer.ready = True
        wait_for(lambda: bool(minimizer.guards_after_cancel))
        wait_for(lambda: runtime._pending is None)
        assert minimizer.guards_after_cancel == [False] and not minimizer.writes
        backend.sessions = (session(),)
        before = backend.reads
        wait_for(lambda: backend.reads >= before + 3)
        assert not backend.commands


def test_prepare_completed_before_late_window_can_upgrade_to_one_play():
    minimizer = WindowMinimizer()
    with running((), options=MediaOptions(False), minimizer=minimizer) as (runtime, backend, _, _, launches, *_):
        assert runtime.request("prepare")
        wait_for(lambda: launches == ["normal"])
        backend.sessions = (session(),)
        wait_for(lambda: runtime.snapshot.sessions == backend.sessions)
        assert runtime._pending is not None and not runtime._pending.play_requested and not backend.commands
        deadline = runtime._pending.deadline
        assert runtime.request("play")
        wait_for(lambda: backend.commands == [("spotify", "play")])
        assert runtime._pending.deadline == deadline and runtime._pending.play_requested
        minimizer.ready = True
        wait_for(lambda: runtime._pending is None)
        assert len(minimizer.writes) == 1 and launches == ["normal"]


def test_late_window_deadline_after_play_does_not_report_playback_failure():
    minimizer = WindowMinimizer()
    with running((), options=MediaOptions(False), minimizer=minimizer) as (runtime, backend, *_):
        assert runtime.request("play")
        wait_for(lambda: bool(minimizer.calls))
        backend.sessions = (session(),)
        wait_for(lambda: backend.commands == [("spotify", "play")])
        wait_for(lambda: runtime._pending is None)
        assert not runtime.snapshot.error and runtime.snapshot.sessions[0].status == "playing"
        calls = len(minimizer.calls)
        minimizer.ready = True
        before = backend.reads
        wait_for(lambda: backend.reads >= before + 3)
        assert len(minimizer.calls) == calls and not minimizer.writes


def test_prepare_only_ready_session_does_not_turn_missing_window_into_playback_error():
    minimizer = WindowMinimizer()
    with running((), options=MediaOptions(False), minimizer=minimizer) as (runtime, backend, *_):
        assert runtime.request("prepare")
        wait_for(lambda: bool(minimizer.calls))
        backend.sessions = (session(),)
        wait_for(lambda: runtime.snapshot.sessions == backend.sessions)
        assert not runtime._pending.play_requested
        wait_for(lambda: runtime._pending is None)
        assert not backend.commands and not runtime.snapshot.error
