"""초기화 실패·중지 경합·이전 GUI owner를 독립된 fake로 검증한다."""
import asyncio
from contextlib import contextmanager
from dataclasses import replace
import threading
import time
from types import SimpleNamespace

import pytest

from src.core.game_audio import GameAudioCoordinator, GameAudioTarget
from src.core.media_center import MediaCenterRuntime, MediaOptions

from test_game_audio import Backend as WasapiBackend, Session as WasapiSession
from test_media_center import Backend, Focus, Native, SpotifyAudio, session


def wait_for(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(.002)
    assert predicate()


class HeldSnapshotBackend(Backend):
    """첫 관측 반환을 제어해 설정 변경과 native 명령 사이의 순서를 고정한다."""
    def __init__(self, sessions):
        super().__init__(sessions)
        self.entered = threading.Event()
        self.release = asyncio.Event()
        self.loop = None

    async def snapshot(self):
        self.loop = asyncio.get_running_loop()
        self.entered.set()
        await self.release.wait()
        return await super().snapshot()

    def release_snapshot(self):
        self.loop.call_soon_threadsafe(self.release.set)

    def hold_next_snapshot(self):
        self.entered.clear()
        self.loop.call_soon_threadsafe(self.release.clear)


@contextmanager
def coordinated_runtime(*, sessions=(), targets=(), wasapi_sessions=(), options=MediaOptions(),
                        foreground=(100, 1000), launches=None):
    """실제 worker/오디오 조정자와 fake OS 경계만 연결한다."""
    backend = HeldSnapshotBackend(sessions)
    wasapi = WasapiBackend(*wasapi_sessions)
    native = Native()
    native.current = foreground
    published = threading.Event()

    def changed(snapshot):
        if backend.reads:
            published.set()

    def no_launch():
        raise AssertionError("등록된 fake Spotify 외 앱 실행은 허용하지 않는다")

    runtime = MediaCenterRuntime(
        changed, backend_factory=lambda: backend,
        audio_factory=lambda: GameAudioCoordinator(wasapi),
        native_factory=lambda: native, focus_factory=Focus,
        spotify_launcher=no_launch if launches is None else lambda: launches.append("normal") or True,
        dj_launcher=no_launch if launches is None else lambda: launches.append("dj") or True,
        spotify_opener=no_launch if launches is None else lambda: launches.append("open") or True,
        spotify_process_reader=lambda: (), spotify_audio_factory=SpotifyAudio,
        spotify_window_reader=lambda *_args, **_kwargs: None,
        spotify_window_closer=lambda *_args, **_kwargs: False,
    )
    # 첫 game 관측 뒤에는 다음 tick 없이 사용자 수정/stop 순서를 검증한다.
    runtime.POLL_SECONDS = 60
    runtime.IO_TIMEOUT_SECONDS = 2
    runtime.update_targets(targets)
    assert runtime.start(options)
    try:
        assert backend.entered.wait(1)
        yield runtime, backend, wasapi, published
    finally:
        assert runtime.stop(timeout_seconds=1)


@pytest.mark.parametrize("initial_muted,latest_muted", [(False, True), (True, False)])
def test_stop_before_next_audio_tick_restores_latest_user_mute(initial_muted, latest_muted):
    target = GameAudioTarget("game", 42, 123, "/game.exe", initial_muted, None)
    game = WasapiSession()
    with coordinated_runtime(targets=(target,), wasapi_sessions=(game,),
                             options=MediaOptions(False, True, False)) as (runtime, _backend, wasapi, _):
        assert runtime.snapshot.game_audio[0].policy_muted
        assert game.muted
        runtime.update_targets((replace(target, user_muted=latest_muted),))
        assert runtime.stop(timeout_seconds=1)
        assert game.muted is latest_muted
        assert wasapi.enumerations == 2  # 최초 적용과 cleanup만 실행했다.


def test_stop_reconciles_latest_active_and_retired_targets_without_touching_other_apps():
    first = GameAudioTarget("first", 42, 123, "/first.exe", False, None)
    second = GameAudioTarget("second", 99, 456, "/second.exe", False, None)
    first_audio, second_audio, unrelated = WasapiSession(), WasapiSession(pid=99), WasapiSession(pid=777)
    with coordinated_runtime(targets=(first, second), wasapi_sessions=(first_audio, second_audio, unrelated),
                             options=MediaOptions(False, True, False)) as (runtime, *_):
        assert first_audio.muted and second_audio.muted
        runtime.update_targets((replace(second, user_muted=True),))
        assert runtime.stop(timeout_seconds=1)
        assert not first_audio.muted and second_audio.muted
        assert unrelated.writes == []


@pytest.mark.parametrize("action,disable,manual,expected", [
    pytest.param("pause", True, False, [], id="auto-off-blocks-pause"),
    pytest.param("play", True, False, [], id="auto-off-blocks-play"),
    pytest.param("pause", True, True, [("spotify", "pause")], id="manual-pause-with-auto-off"),
    pytest.param("pause", False, False, [("spotify", "pause")], id="enabled-automatic-pause"),
])
def test_auto_off_during_snapshot_preserves_only_explicit_control(action, disable, manual, expected):
    sessions = ((session(status="playing"), session("firefox", "Firefox.exe", "playing"))
                if action == "pause" else (session(),))
    with coordinated_runtime(sessions=sessions, options=MediaOptions(True, True, False)) as (runtime, backend, _, published):
        if disable:
            assert runtime.configure(MediaOptions(False, True, False))
        if manual:
            assert runtime.request("pause")
        backend.release_snapshot()
        assert published.wait(1)
        assert backend.commands == expected


@pytest.mark.parametrize("background_mute,actual_state,status,expected", [
    pytest.param(True, "audible", "paused", [], id="background-audible-blocks-play"),
    pytest.param(True, "audible", "playing", [("spotify", "pause")], id="background-audible-pauses-bgm"),
    pytest.param(True, "unknown", "paused", [], id="unknown-background-stays-unknown"),
    pytest.param(True, "quiet", "paused", [("spotify", "play")], id="confirmed-background-quiet-allows-play"),
    pytest.param(False, "audible", "paused", [("spotify", "play")], id="auto-mute-off-uses-foreground-only"),
])
def test_actual_background_audio_controls_bgm_when_automatic_muting_is_enabled(
    background_mute, actual_state, status, expected,
):
    target = GameAudioTarget("game", 42, 123, "/game.exe", False, None)
    game = WasapiSession()
    game.ignore_mute = actual_state == "audible"
    wasapi_sessions = () if actual_state == "unknown" else (game,)
    with coordinated_runtime(sessions=(session(status=status),), targets=(target,),
                             wasapi_sessions=wasapi_sessions,
                             options=MediaOptions(True, background_mute, False)) as (runtime, backend, _, published):
        observation = runtime.snapshot.game_audio[0]
        assert observation.audible is ({"audible": True, "unknown": None, "quiet": False}[actual_state])
        backend.release_snapshot()
        assert published.wait(1)
        assert backend.commands == expected


def test_audible_background_game_pauses_bgm_despite_quiet_foreground_and_unknown_game():
    foreground = GameAudioTarget("foreground", 42, 123, "/foreground.exe", True, None)
    background = GameAudioTarget("background", 99, 456, "/background.exe", False, None)
    unknown = GameAudioTarget("unknown", 199, 789, "/unknown.exe", False, None)
    quiet_audio, audible_audio = WasapiSession(muted=True), WasapiSession(pid=99)
    audible_audio.ignore_mute = True
    with coordinated_runtime(sessions=(session(status="playing"),),
                             targets=(foreground, background, unknown),
                             wasapi_sessions=(quiet_audio, audible_audio),
                             options=MediaOptions(True, True, False),
                             foreground=(42, 420)) as (runtime, backend, _, published):
        observations = runtime.snapshot.game_audio
        assert tuple(item.audible for item in observations) == (False, True, None)
        assert tuple(item.available for item in observations) == (True, True, False)
        backend.release_snapshot()
        assert published.wait(1)
        assert backend.commands == [("spotify", "pause")]


@pytest.mark.parametrize("background_mute,actual_state,status,expected", [
    pytest.param(True, "audible", "playing", [("spotify", "pause")], id="known-audible-pauses-without-foreground"),
    pytest.param(True, "audible", "paused", [], id="known-audible-blocks-play-without-foreground"),
    pytest.param(True, "quiet", "paused", [], id="quiet-does-not-prove-foreground-without-window"),
    pytest.param(True, "unknown", "paused", [], id="unknown-does-not-prove-quiet-without-window"),
    pytest.param(False, "audible", "playing", [], id="auto-mute-off-preserves-foreground-gate"),
])
def test_missing_foreground_preserves_known_audible_game_without_resuming_unknown_context(
    background_mute, actual_state, status, expected,
):
    target = GameAudioTarget("game", 42, 123, "/game.exe", actual_state == "quiet", None)
    game = WasapiSession(muted=actual_state == "quiet")
    wasapi_sessions = () if actual_state == "unknown" else (game,)
    with coordinated_runtime(sessions=(session(status=status),), targets=(target,),
                             wasapi_sessions=wasapi_sessions,
                             options=MediaOptions(True, background_mute, False),
                             foreground=(None, None)) as (runtime, backend, _, published):
        observation = runtime.snapshot.game_audio[0]
        assert observation.audible is {"audible": True, "quiet": False, "unknown": None}[actual_state]
        backend.release_snapshot()
        assert published.wait(1)
        assert backend.commands == expected


@pytest.mark.parametrize("sessions,expected", [
    pytest.param((session(status="playing"),), [("spotify", "pause")], id="playing-bgm-paused-once"),
    pytest.param((session(),), [], id="already-paused-no-op"),
    pytest.param((), [], id="absent-bgm-no-op-without-cold-start"),
    pytest.param((session("firefox", "Firefox.exe", "playing"),), [], id="other-media-untouched"),
])
def test_explicit_auto_off_pause_uses_fresh_worker_bgm_state(sessions, expected):
    with coordinated_runtime(sessions=sessions, options=MediaOptions(True, True, False)) as (runtime, backend, _, published):
        assert runtime.configure(MediaOptions(False, True, False))
        assert runtime.request("pause_bgm_if_playing")
        backend.release_snapshot()
        assert published.wait(1)
        assert backend.commands == expected
        assert not runtime.snapshot.error
        assert runtime.snapshot.options.auto_bgm is False


@pytest.mark.parametrize("before,after,expected", [
    pytest.param("paused", "playing", [("spotify", "pause")], id="new-playing-state-pauses"),
    pytest.param("playing", "paused", [], id="new-paused-state-no-op"),
])
def test_explicit_auto_off_pause_does_not_use_previously_published_bgm_status(before, after, expected):
    with coordinated_runtime(sessions=(session(status=before),),
                             options=MediaOptions(False, True, False)) as (runtime, backend, _, published):
        backend.release_snapshot()
        assert published.wait(1)
        assert runtime.snapshot.sessions[0].status == before
        backend.hold_next_snapshot()
        assert runtime.request("pause_bgm_if_playing")
        assert backend.entered.wait(1)
        backend.sessions = (session(status=after),)
        backend.release_snapshot()
        wait_for(lambda: runtime.snapshot.sessions[0].status == after)
        assert backend.commands == expected
        assert not runtime.snapshot.error


def test_explicit_auto_off_pause_cancels_pending_automatic_play_and_later_manual_play_still_works():
    launches = []
    with coordinated_runtime(options=MediaOptions(True, True, False), launches=launches) as (runtime, backend, _, published):
        backend.release_snapshot()
        assert published.wait(1)
        assert runtime._pending is not None and runtime._pending.automatic
        assert launches == ["dj"]
        backend.hold_next_snapshot()
        runtime._notify_worker()
        assert backend.entered.wait(1)
        assert runtime.configure(MediaOptions(False, True, False))
        assert runtime.request("pause_bgm_if_playing")
        backend.sessions = (session(),)
        backend.release_snapshot()
        wait_for(lambda: bool(runtime.snapshot.sessions))
        assert runtime._pending is None and backend.commands == []
        assert not runtime.snapshot.error and launches == ["dj"]
        assert runtime.request("play")
        wait_for(lambda: backend.commands == [("spotify", "play")])
        assert launches == ["dj"]


def test_reenabled_auto_bgm_blocks_an_older_explicit_off_pause_waiting_for_snapshot():
    with coordinated_runtime(sessions=(session(status="playing"),),
                             options=MediaOptions(True, True, False)) as (runtime, backend, _, published):
        assert runtime.configure(MediaOptions(False, True, False))
        assert runtime.request("pause_bgm_if_playing")
        assert runtime.configure(MediaOptions(True, True, False))
        backend.release_snapshot()
        assert published.wait(1)
        assert backend.commands == []
        assert not runtime.snapshot.error
        assert runtime.snapshot.options.auto_bgm is True


def test_explicit_off_pause_without_playing_bgm_preserves_manual_preparation():
    launches = []
    with coordinated_runtime(options=MediaOptions(False, True, False), launches=launches) as (runtime, backend, _, published):
        assert runtime.request("play")
        backend.release_snapshot()
        assert published.wait(1)
        pending = runtime._pending
        assert pending is not None and not pending.automatic
        assert launches == ["dj"]
        backend.hold_next_snapshot()
        assert runtime.request("pause_bgm_if_playing")
        assert backend.entered.wait(1)
        backend.release_snapshot()
        wait_for(lambda: backend.reads >= 2)
        backend.hold_next_snapshot()
        runtime._notify_worker()
        assert backend.entered.wait(1)  # 직전 요청 처리가 끝난 다음 cycle이다.
        assert runtime._pending is pending and not runtime.snapshot.error
        assert not backend.commands and launches == ["dj"]
        backend.sessions = (session(),)
        backend.release_snapshot()
        wait_for(lambda: backend.commands == [("spotify", "play")])


@pytest.mark.parametrize("status,actions,expected", [
    pytest.param("playing", ("pause_bgm_if_playing", "play"),
                 [("spotify", "pause"), ("spotify", "play")], id="pause-then-play"),
    pytest.param("paused", ("play", "pause_bgm_if_playing"),
                 [("spotify", "play"), ("spotify", "pause")], id="play-then-pause"),
])
def test_explicit_off_pause_and_manual_play_in_one_snapshot_keep_last_user_intent(status, actions, expected):
    with coordinated_runtime(sessions=(session(status=status),),
                             options=MediaOptions(False, True, False)) as (runtime, backend, _, published):
        for action in actions:
            assert runtime.request(action)
        backend.release_snapshot()
        assert published.wait(1)
        assert backend.commands == expected
        assert not runtime.snapshot.error


def test_stop_before_worker_initialization_never_opens_native_resources():
    entered, release = threading.Event(), threading.Event()
    native_calls = []

    def forbidden(*_args, **_kwargs):
        native_calls.append(True)
        raise AssertionError("중지된 실행은 native 자원을 생성하지 않아야 한다")

    class HeldRuntime(MediaCenterRuntime):
        def _thread_main(self):
            entered.set()
            release.wait(1.0)
            super()._thread_main()

    runtime = HeldRuntime(
        backend_factory=forbidden, audio_factory=forbidden,
        native_factory=forbidden, focus_factory=forbidden,
        spotify_launcher=forbidden,
    )
    runtime.start()
    assert entered.wait(1.0)
    try:
        assert not runtime.stop(timeout_seconds=0)
        assert not runtime.configure(MediaOptions(False, False, False))
        assert not runtime.request("play")
    finally:
        release.set()
        assert runtime.stop(timeout_seconds=1)
    assert not runtime.running and not runtime.snapshot.running
    assert native_calls == []


def test_later_factory_failure_cleans_already_created_audio_and_backend():
    cleanup_calls, callbacks = [], []

    class Backend:
        def close(self):
            cleanup_calls.append("backend")

    class Audio:
        def update_targets(self, _targets):
            pass

        def cleanup(self):
            cleanup_calls.append("audio")
            return True

    def focus_failure(**_kwargs):
        raise RuntimeError("controlled focus initialization failure")

    runtime = MediaCenterRuntime(
        callbacks.append, backend_factory=Backend, audio_factory=Audio,
        native_factory=lambda: object(), focus_factory=focus_failure,
        spotify_launcher=lambda: (_ for _ in ()).throw(AssertionError("no playback")),
    )
    runtime.start(MediaOptions(False, False, False))
    wait_for(lambda: bool(callbacks) and not runtime.running)
    assert cleanup_calls == ["audio", "backend"]
    assert "controlled focus initialization failure" in runtime.snapshot.error
    assert not runtime.snapshot.running
    assert not runtime.request("play") and not runtime.configure(MediaOptions())
    assert not runtime.stop()


def test_audio_cleanup_exception_still_closes_media_backend_and_blocks_normal_completion():
    closed = threading.Event()
    read = threading.Event()

    class Backend:
        async def snapshot(self):
            read.set()
            return ()

        def close(self):
            closed.set()

    class Audio:
        def update_targets(self, _targets):
            pass

        def reconcile(self, *_args, **_kwargs):
            return ()

        def cleanup(self):
            raise RuntimeError("controlled restore failure")

    runtime = MediaCenterRuntime(
        backend_factory=Backend, audio_factory=Audio,
        native_factory=lambda: SimpleNamespace(foreground=lambda: (100, 1000)),
        focus_factory=lambda **_kwargs: SimpleNamespace(cancel=lambda: None),
        spotify_launcher=lambda: (_ for _ in ()).throw(AssertionError("no playback")),
    )
    runtime.start(MediaOptions(False, False, False))
    assert read.wait(1.0)
    assert not runtime.stop(timeout_seconds=1)
    assert closed.is_set() and not runtime.running
    assert "controlled restore failure" in runtime.snapshot.error
    assert not runtime.request("play")


def test_old_runtime_callback_cannot_replace_new_runtime_projection():
    from src.gui.main_window import MainWindow

    old_owner, new_owner = object(), object()
    old_snapshot, new_snapshot = object(), object()
    view = SimpleNamespace(
        _shutting_down=False, _beholder_restore_runtime_suspended=False,
        _media_center=new_owner, _media_center_snapshot=None,
        _sidebar_controller=SimpleNamespace(dispatch_media_state=lambda _snapshot: None),
    )
    MainWindow._on_media_center_snapshot(view, (old_owner, old_snapshot))
    assert view._media_center_snapshot is None
    MainWindow._on_media_center_snapshot(view, (new_owner, new_snapshot))
    assert view._media_center_snapshot is new_snapshot
    view._shutting_down = True
    MainWindow._on_media_center_snapshot(view, (new_owner, old_snapshot))
    assert view._media_center_snapshot is new_snapshot


def test_windows_library_imports_precede_worker_mta_initialization(monkeypatch):
    import builtins
    import src.core.media_center as module
    from test_media_center import Audio, Backend, Focus, Native

    original_import = builtins.__import__
    events = []
    caller = threading.get_ident()
    pythoncom = SimpleNamespace(
        COINIT_MULTITHREADED=0,
        CoInitializeEx=lambda flag: events.append(("mta", threading.get_ident(), flag)),
        CoUninitialize=lambda: events.append(("uninit", threading.get_ident())),
    )

    def tracked_import(name, *args, **kwargs):
        if name in {"pythoncom", "comtypes"}:
            events.append((name, threading.get_ident()))
            return pythoncom if name == "pythoncom" else SimpleNamespace()
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(module, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(builtins, "__import__", tracked_import)
    backend = Backend()
    runtime = MediaCenterRuntime(
        backend_factory=lambda: backend, audio_factory=Audio, focus_factory=Focus,
        native_factory=Native,
    )
    assert runtime.start(MediaOptions(False, False, False))
    try:
        wait_for(lambda: backend.reads > 0)
    finally:
        assert runtime.stop()
    assert events[:2] == [("pythoncom", caller), ("comtypes", caller)]
    mta = next(event for event in events if event[0] == "mta")
    assert mta[1] != caller and mta[2] == 0
    assert events[-1] == ("uninit", mta[1])


def test_windows_library_load_failure_never_creates_worker(monkeypatch):
    import builtins
    import src.core.media_center as module

    original_import = builtins.__import__

    def failed_import(name, *args, **kwargs):
        if name == "comtypes":
            raise ImportError("controlled missing Windows library")
        if name == "pythoncom":
            return SimpleNamespace()
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(module, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(builtins, "__import__", failed_import)
    runtime = MediaCenterRuntime()
    assert not runtime.start()
    assert not runtime.running and not runtime.request("play")
    assert "controlled missing Windows library" in runtime.snapshot.error
    assert runtime.stop()
