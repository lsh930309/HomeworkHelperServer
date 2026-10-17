"""GSMTC를 fake로 주입하여 OS·재생·설정에 접근하지 않고 계약을 검증한다."""
import asyncio
from dataclasses import FrozenInstanceError
from enum import IntEnum
from types import SimpleNamespace

import pytest

from src.core import media_sessions as module
from src.core.media_sessions import MediaSessionInfo, WindowsMediaSessions, is_spotify_session


class Status(IntEnum):
    PLAYING = 4
    PAUSED = 5


class Events:
    def __init__(self):
        self.handlers = {}
        self.serial = 0
        self.removed = []

    def add(self, event, handler):
        self.serial += 1
        token = self.serial
        self.handlers[token] = (event, handler)
        return token

    def remove(self, event, token):
        assert self.handlers.pop(token)[0] == event
        self.removed.append((event, token))

    def fire(self, event):
        for name, handler in tuple(self.handlers.values()):
            if name == event:
                handler(self, None)


class Session(Events):
    def __init__(self, identity, app_id="Spotify.exe", title="곡", artist="가수"):
        super().__init__()
        self.identity = identity
        self.source_app_user_model_id = app_id
        self.metadata = SimpleNamespace(title=title, artist=artist)
        self.playback = SimpleNamespace(playback_status=Status.PLAYING, controls=SimpleNamespace(
            is_play_enabled=True, is_pause_enabled=True,
            is_previous_enabled=True, is_next_enabled=True))
        self.reads = 0
        self.commands = []
        self.accept = True

    def __eq__(self, other):
        return isinstance(other, Session) and self.identity == other.identity

    def __hash__(self):
        return hash(self.identity)

    def get_playback_info(self):
        return self.playback

    async def try_get_media_properties_async(self):
        self.reads += 1
        if isinstance(self.metadata, BaseException):
            raise self.metadata
        return self.metadata

    def add_media_properties_changed(self, callback):
        return self.add("metadata", callback)

    def remove_media_properties_changed(self, token):
        self.remove("metadata", token)

    def add_playback_info_changed(self, callback):
        return self.add("playback", callback)

    def remove_playback_info_changed(self, token):
        self.remove("playback", token)

    async def try_play_async(self):
        self.commands.append("play")
        return self.accept

    async def try_pause_async(self):
        self.commands.append("pause")
        return self.accept

    async def try_skip_previous_async(self):
        self.commands.append("previous")
        return self.accept

    async def try_skip_next_async(self):
        self.commands.append("next")
        return self.accept


class Manager(Events):
    def __init__(self, *sessions):
        super().__init__()
        self.sessions = sessions

    def get_sessions(self):
        return self.sessions

    def add_sessions_changed(self, callback):
        return self.add("sessions", callback)

    def remove_sessions_changed(self, token):
        self.remove("sessions", token)


def test_snapshot_keeps_native_identity_across_wrappers_and_separates_same_app():
    async def scenario():
        first, second = Session(1), Session(2)
        manager = Manager(first, second)
        backend = WindowsMediaSessions(manager)
        initial = await backend.snapshot()
        assert len(initial) == 2 and initial[0].session_id != initial[1].session_id
        assert initial[0].status == "playing"
        manager.sessions = (Session(2), Session(1))
        updated = await backend.snapshot()
        assert [info.session_id for info in updated] == [initial[1].session_id, initial[0].session_id]
        assert (first.reads, second.reads) == (1, 1)
        assert await backend.control(initial[1].session_id, "pause")
        assert first.commands == [] and second.commands == ["pause"]
        backend.close()
        assert not first.handlers and not second.handlers and not manager.handlers
    asyncio.run(scenario())


def test_metadata_refreshes_only_after_event_and_playback_is_live():
    async def scenario():
        session = Session(1)
        manager = Manager(session)
        changes = []
        backend = WindowsMediaSessions(manager, on_change=lambda: changes.append(True))
        assert (await backend.snapshot())[0].title == "곡"
        session.playback.playback_status = Status.PAUSED
        session.fire("playback")
        await asyncio.sleep(0)
        assert (await backend.snapshot())[0].status == "paused"
        assert session.reads == 1
        session.metadata = SimpleNamespace(title="다음 곡", artist="다른 가수")
        session.fire("metadata")
        await asyncio.sleep(0)
        assert (await backend.snapshot())[0].title == "다음 곡"
        assert session.reads == 2 and len(changes) == 2
        backend.close()
    asyncio.run(scenario())


def test_missing_disabled_unknown_and_rejected_controls_never_target_another_session():
    async def scenario():
        session = Session(1)
        manager = Manager(session)
        backend = WindowsMediaSessions(manager)
        info, = await backend.snapshot()
        assert not await backend.control("missing", "play")
        assert not await backend.control(info.session_id, "toggle")
        session.playback.controls.is_pause_enabled = False
        assert not await backend.control(info.session_id, "pause")
        session.accept = False
        assert not await backend.control(info.session_id, "play")
        assert session.commands == ["play"]
        manager.sessions = ()
        assert not await backend.control(info.session_id, "next")
        assert not session.handlers
        manager.sessions = (Session(3),)
        replacement, = await backend.snapshot()
        assert replacement.session_id != info.session_id
        assert not await backend.control(info.session_id, "play")
        backend.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("action", ["play", "pause", "previous", "next"])
def test_explicit_supported_actions(action):
    async def scenario():
        session = Session(1)
        backend = WindowsMediaSessions(Manager(session))
        info, = await backend.snapshot()
        assert await backend.control(info.session_id, action)
        assert session.commands == [action]
        backend.close()
    asyncio.run(scenario())


def test_getter_errors_are_not_misreported_as_empty_snapshot_and_metadata_retries():
    async def scenario():
        session = Session(1)
        session.metadata = OSError("session unavailable")
        backend = WindowsMediaSessions(Manager(session))
        with pytest.raises(OSError, match="session unavailable"):
            await backend.snapshot()
        session.metadata = SimpleNamespace(title="복구", artist="")
        assert (await backend.snapshot())[0].title == "복구"
        assert session.reads == 2
        session.get_playback_info = lambda: (_ for _ in ()).throw(OSError("playback read failed"))
        with pytest.raises(OSError, match="playback read failed"):
            await backend.snapshot()
        backend.close()
    asyncio.run(scenario())


def test_close_revokes_events_and_discards_already_queued_callbacks():
    async def scenario():
        session = Session(1)
        manager = Manager(session)
        changes = []
        backend = WindowsMediaSessions(manager, on_change=lambda: changes.append(True))
        await backend.snapshot()
        manager.fire("sessions")
        session.fire("metadata")
        backend.close()
        backend.close()
        await asyncio.sleep(0)
        assert changes == []
        assert len(manager.removed) == 1 and len(session.removed) == 2
        with pytest.raises(RuntimeError, match="closed"):
            await backend.snapshot()
    asyncio.run(scenario())


def test_metadata_change_while_fetching_is_observed_by_the_next_snapshot():
    async def scenario():
        session = Session(1)
        backend = WindowsMediaSessions(Manager(session))
        started, release = asyncio.Event(), asyncio.Event()

        async def delayed_metadata():
            started.set()
            await release.wait()
            return SimpleNamespace(title="이전 곡", artist="")

        session.try_get_media_properties_async = delayed_metadata
        pending = asyncio.create_task(backend.snapshot())
        await started.wait()
        session.fire("metadata")
        await asyncio.sleep(0)
        release.set()
        assert (await pending)[0].title == "이전 곡"

        async def current_metadata():
            return SimpleNamespace(title="새 곡", artist="")

        session.try_get_media_properties_async = current_metadata
        assert (await backend.snapshot())[0].title == "새 곡"
        backend.close()
    asyncio.run(scenario())


def test_close_attempts_every_unsubscribe_even_if_one_fails():
    async def scenario():
        session = Session(1)
        manager = Manager(session)
        original_remove = session.remove_media_properties_changed

        def remove_then_fail(token):
            original_remove(token)
            raise OSError("unsubscribe failed")

        session.remove_media_properties_changed = remove_then_fail
        backend = WindowsMediaSessions(manager)
        await backend.snapshot()
        with pytest.raises(OSError, match="unsubscribe failed"):
            backend.close()
        assert session.handlers == manager.handlers == {}
    asyncio.run(scenario())


@pytest.mark.parametrize("app_id, expected", [
    ("Spotify.exe", True), (r"C:\Users\User\Spotify.exe", True),
    ("SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify", True),
    ("spotify.EXE", True), ("Spotify.exe.backup", False),
    ("NotSpotify.exe", False), ("Spotify", False),
    ("SpotifyAB.SpotifyMusic_other!Spotify", False),
    ("firefox.exe", False),
])
def test_spotify_identity_is_exact_and_ignores_title(app_id, expected):
    assert is_spotify_session(MediaSessionInfo("id", app_id, title="Spotify")) is expected


def test_info_is_immutable():
    info = MediaSessionInfo("id", "app")
    with pytest.raises(FrozenInstanceError):
        info.status = "playing"


def test_constructor_does_not_touch_windows_and_nonwindows_calls_fail_explicitly(monkeypatch):
    monkeypatch.setattr(module.sys, "platform", "darwin")
    backend = WindowsMediaSessions()
    with pytest.raises(OSError, match="Windows"):
        asyncio.run(backend.snapshot())
    backend.close()
    with pytest.raises(OSError, match="Windows"):
        module.launch_spotify()


def test_launch_requests_only_fixed_spotify_uri_once(monkeypatch):
    requests = []
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(module.os, "startfile", requests.append, raising=False)
    assert module.launch_spotify()
    assert requests == ["spotify:"]
