"""초기화 실패·중지 경합·이전 GUI owner를 독립된 fake로 검증한다."""
import threading
import time
from types import SimpleNamespace

from src.core.media_center import MediaCenterRuntime, MediaOptions


def wait_for(predicate, timeout=1.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(.002)
    assert predicate()


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
