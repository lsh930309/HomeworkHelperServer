"""로그인한 Windows 사용자의 미디어 세션을 읽고 명시한 세션만 제어한다.

생성자는 I/O를 하지 않는다. 첫 async 호출부터 close까지 하나의 worker
thread/event loop에서 순서대로 호출한다. 세션 ID는 backend 수명 안에서만 유효하다.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import math
import ntpath
import sys
import threading
from collections.abc import Callable
from typing import Any


@dataclass(frozen=True)
class MediaSessionInfo:
    session_id: str
    app_id: str
    title: str = ""
    artist: str = ""
    status: str = "unknown"
    can_play: bool = False
    can_pause: bool = False
    can_previous: bool = False
    can_next: bool = False
    artwork: bytes = b""
    position_seconds: float | None = None
    duration_seconds: float | None = None
    timeline_updated_at: float | None = None
    playback_rate: float | None = None


def is_spotify_session(info: MediaSessionInfo) -> bool:
    """표시 제목이 아닌 정확한 실행 파일명/Store AUMID를 식별한다."""
    app_id = info.app_id.casefold()
    return (ntpath.basename(app_id) == "spotify.exe"
            or app_id == "spotifyab.spotifymusic_zpdnekdrzrea0!spotify")


@dataclass
class _Session:
    session_id: str
    native: Any
    title: str = ""
    artist: str = ""
    artwork: bytes = b""
    metadata_dirty: bool = True
    subscriptions: list[tuple[Callable, Any]] = field(default_factory=list)


_STATUS_NAMES = {0: "closed", 1: "opened", 2: "changing", 3: "stopped",
                 4: "playing", 5: "paused"}
_ACTIONS = {
    "play": ("is_play_enabled", "try_play_async"),
    "pause": ("is_pause_enabled", "try_pause_async"),
    "previous": ("is_previous_enabled", "try_skip_previous_async"),
    "next": ("is_next_enabled", "try_skip_next_async"),
}
_MAX_ARTWORK_BYTES = 2 * 1024 * 1024
_ARTWORK_BUDGET_SECONDS = 0.2


async def _read_artwork(reference) -> bytes:
    """읽기 스트림을 소유하는 worker에서 유한한 이미지 바이트만 가져온다."""
    if reference is None:
        return b""
    from winrt.windows.storage.streams import DataReader

    stream = await reference.open_read_async()
    try:
        size = int(stream.size)
        if not 0 < size <= _MAX_ARTWORK_BYTES:
            return b""
        reader = DataReader(stream)
        try:
            if await reader.load_async(size) != size:
                return b""
            data = bytearray(size)
            reader.read_bytes(data)
            return bytes(data)
        finally:
            try:
                reader.detach_stream()
            finally:
                reader.close()
    finally:
        stream.close()


def _timeline(native, playback) -> dict[str, float | None]:
    """표시용 시간은 선택 정보다. 공급자가 지원하지 않아도 재생을 막지 않는다."""
    values = dict(position_seconds=None, duration_seconds=None,
                  timeline_updated_at=None, playback_rate=None)
    try:
        timeline = native.get_timeline_properties()
        start = timeline.start_time.total_seconds()
        end = timeline.end_time.total_seconds()
        position = timeline.position.total_seconds()
        updated = timeline.last_updated_time
        if updated.tzinfo is None or updated.utcoffset() is None:
            return values
        timestamp = updated.timestamp()
        if (not all(math.isfinite(value) for value in (start, end, position, timestamp))
                or start < 0 or end <= start or not start <= position <= end
                or timestamp <= 0):
            return values
        values.update(position_seconds=position - start, duration_seconds=end - start,
                      timeline_updated_at=timestamp)
        rate = getattr(playback, "playback_rate", None)
        if rate is not None and math.isfinite(rate) and rate >= 0:
            values["playback_rate"] = float(rate)
    except Exception:
        pass
    return values


class WindowsMediaSessions:
    """GSMTC adapter. 주입 manager는 테스트에서 실제 Windows 호출을 피한다.

    Native equality/hash는 PyWinRT의 IInspectable identity 비교를 사용한다.
    따라서 get_sessions가 새 Python wrapper를 반환해도 같은 세션을 유지한다.
    on_change는 소유 event loop에서 실행되며 WinRT callback thread와 분리된다.
    """

    def __init__(self, manager=None, on_change: Callable[[], None] | None = None):
        self._manager = manager
        self._on_change = on_change
        self._loop = None
        self._thread_id = None
        self._manager_subscription = None
        self._sessions: dict[Any, _Session] = {}
        self._next_id = 0
        self._closed = False
        self._uninit_apartment = None

    async def _ensure_manager(self):
        if self._closed:
            raise RuntimeError("Media sessions backend is closed")
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
            self._thread_id = threading.get_ident()
        elif self._loop is not loop or self._thread_id != threading.get_ident():
            raise RuntimeError("Media sessions must use their owning worker loop")
        if self._manager is None:
            if sys.platform != "win32":
                raise OSError("Media sessions require Windows")
            from winrt.runtime import ApartmentType, init_apartment, uninit_apartment
            if self._uninit_apartment is None:
                init_apartment(ApartmentType.MULTI_THREADED)
                self._uninit_apartment = uninit_apartment
            from winrt.windows.media.control import (
                GlobalSystemMediaTransportControlsSessionManager,
            )
            self._manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
        if self._manager_subscription is None:
            token = self._manager.add_sessions_changed(self._sessions_changed)
            self._manager_subscription = (self._manager.remove_sessions_changed, token)
        return self._manager

    def _post_change(self, native=None, metadata=False):
        # Native callbacks may race with shutdown and must never raise into C++.
        loop = self._loop
        if self._closed or loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(self._changed, native, metadata)
        except RuntimeError:
            # The worker loop was closed between the check and scheduling.
            return

    def _sessions_changed(self, _sender, _args):
        self._post_change()

    def _changed(self, native, metadata):
        if self._closed:
            return
        if metadata and native in self._sessions:
            self._sessions[native].metadata_dirty = True
        if self._on_change is not None:
            self._on_change()

    @staticmethod
    def _unsubscribe(subscriptions):
        error = None
        for remove, token in subscriptions:
            try:
                remove(token)
            except Exception as exc:
                error = error or exc
        if error is not None:
            raise error

    def _refresh_sessions(self, manager):
        natives = tuple(manager.get_sessions())
        present = set(natives)
        for native in tuple(self._sessions):
            if native not in present:
                entry = self._sessions.pop(native)
                self._unsubscribe(entry.subscriptions)
        for native in natives:
            if native in self._sessions:
                continue
            self._next_id += 1
            entry = _Session(f"media-{self._next_id}", native)
            try:
                token = native.add_media_properties_changed(
                    lambda _s, _a, key=native: self._post_change(key, True))
                entry.subscriptions.append((native.remove_media_properties_changed, token))
                token = native.add_playback_info_changed(
                    lambda _s, _a, key=native: self._post_change(key))
                entry.subscriptions.append((native.remove_playback_info_changed, token))
            except Exception:
                self._unsubscribe(entry.subscriptions)
                raise
            self._sessions[native] = entry
        return tuple(self._sessions[native] for native in natives)

    async def snapshot(self) -> tuple[MediaSessionInfo, ...]:
        manager = await self._ensure_manager()
        result = []
        artwork_deadline = self._loop.time() + _ARTWORK_BUDGET_SECONDS
        for entry in self._refresh_sessions(manager):
            native = entry.native
            if entry.metadata_dirty:
                # Clear before awaiting so a change during the fetch stays dirty.
                entry.metadata_dirty = False
                try:
                    metadata = await native.try_get_media_properties_async()
                except BaseException:
                    entry.metadata_dirty = True
                    raise
                artwork = b""
                remaining = artwork_deadline - self._loop.time()
                try:
                    thumbnail = getattr(metadata, "thumbnail", None) if metadata is not None else None
                except Exception:
                    thumbnail = None
                if thumbnail is not None and remaining > 0:
                    try:
                        artwork = await asyncio.wait_for(
                            _read_artwork(thumbnail), remaining)
                    except asyncio.CancelledError:
                        entry.metadata_dirty = True
                        raise
                    except Exception:
                        # 표지 조회 실패는 기본 재생·상태 관측의 실패가 아니다.
                        pass
                if self._closed:
                    raise RuntimeError("Media sessions backend is closed")
                if native not in manager.get_sessions():
                    continue
                # 대기 중 메타데이터가 바뀌었으면 오래된 결과를 공개하지 않는다.
                if not entry.metadata_dirty:
                    entry.title = metadata.title if metadata is not None else ""
                    entry.artist = metadata.artist if metadata is not None else ""
                    entry.artwork = artwork
                    # 앞선 세션이 이미지 예산을 썼으면 다음 관측에서 한 번 준비한다.
                    entry.metadata_dirty = thumbnail is not None and remaining <= 0
            playback = native.get_playback_info()
            controls = playback.controls
            result.append(MediaSessionInfo(
                session_id=entry.session_id,
                app_id=native.source_app_user_model_id,
                title=entry.title,
                artist=entry.artist,
                status=_STATUS_NAMES.get(int(playback.playback_status), "unknown"),
                can_play=bool(controls.is_play_enabled),
                can_pause=bool(controls.is_pause_enabled),
                can_previous=bool(controls.is_previous_enabled),
                can_next=bool(controls.is_next_enabled),
                artwork=entry.artwork,
                **_timeline(native, playback),
            ))
        # 이미지 I/O 동안 종료된 세션은 이번 결과에서도 제외한다.
        live_ids = {entry.session_id for entry in self._refresh_sessions(manager)}
        return tuple(info for info in result if info.session_id in live_ids)

    async def control(self, session_id: str, action: str) -> bool:
        if action not in _ACTIONS:
            return False
        manager = await self._ensure_manager()
        entry = next((item for item in self._refresh_sessions(manager)
                      if item.session_id == session_id), None)
        if entry is None:
            return False
        capability, method = _ACTIONS[action]
        if not getattr(entry.native.get_playback_info().controls, capability):
            return False
        return bool(await getattr(entry.native, method)())

    def close(self) -> None:
        if self._closed:
            return
        if self._thread_id is not None and self._thread_id != threading.get_ident():
            raise RuntimeError("Close media sessions on their owning worker thread")
        self._closed = True
        subscriptions = [pair for entry in self._sessions.values()
                         for pair in entry.subscriptions]
        if self._manager_subscription is not None:
            subscriptions.append(self._manager_subscription)
        try:
            self._unsubscribe(subscriptions)
        finally:
            self._sessions.clear()
            self._manager_subscription = None
            self._manager = None
            self._on_change = None
            if self._uninit_apartment is not None:
                self._uninit_apartment()
                self._uninit_apartment = None
