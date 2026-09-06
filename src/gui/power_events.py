"""Windows native power-resume decoding and desired Qt timer state."""
from __future__ import annotations

from dataclasses import dataclass
import logging
import sys
import threading
import time
from typing import Callable, Iterable, Protocol

from PySide6.QtCore import QAbstractNativeEventFilter

logger = logging.getLogger(__name__)

WM_POWERBROADCAST = 0x0218
PBT_APMRESUMEAUTOMATIC = 0x0012


@dataclass(frozen=True, slots=True)
class PowerResumeEvent:
    occurred_at: float


class WindowsPowerEventParser:
    def __init__(self, *, debounce_seconds: float = 5.0, clock: Callable[[], float] = time.monotonic):
        self._debounce_seconds = max(0.0, float(debounce_seconds))
        self._clock = clock
        self._last_resume_at: float | None = None
        self._lock = threading.Lock()

    def parse(self, message: int, event_code: int) -> PowerResumeEvent | None:
        if int(message) != WM_POWERBROADCAST or int(event_code) != PBT_APMRESUMEAUTOMATIC:
            return None
        now = float(self._clock())
        with self._lock:
            if self._last_resume_at is not None and now - self._last_resume_at < self._debounce_seconds:
                return None
            self._last_resume_at = now
        return PowerResumeEvent(now)


def decode_windows_message(message: object) -> tuple[int, int] | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        address = int(message)
        native = ctypes.cast(address, ctypes.POINTER(wintypes.MSG)).contents
        return int(native.message), int(native.wParam)
    except (TypeError, ValueError, OverflowError, OSError):
        logger.debug("Windows native message decode failed", exc_info=True)
        return None


class WindowsPowerEventFilter(QAbstractNativeEventFilter):
    def __init__(
        self,
        callback: Callable[[PowerResumeEvent], None],
        *,
        parser: WindowsPowerEventParser | None = None,
        decoder: Callable[[object], tuple[int, int] | None] = decode_windows_message,
    ) -> None:
        super().__init__()
        self._callback = callback
        self._parser = parser or WindowsPowerEventParser()
        self._decoder = decoder

    def nativeEventFilter(self, event_type: bytes | bytearray | str, message: object):
        value = bytes(event_type).lower() if isinstance(event_type, (bytes, bytearray)) else str(event_type).encode().lower()
        if value not in {b"windows_generic_msg", b"windows_dispatcher_msg"}:
            return False, 0
        decoded = self._decoder(message)
        event = self._parser.parse(*decoded) if decoded is not None else None
        if event is not None:
            try:
                self._callback(event)
            except Exception:
                logger.exception("Windows resume callback failed")
        return False, 0


class TimerLike(Protocol):
    def start(self, msec: int) -> None: ...
    def stop(self) -> None: ...
    def isActive(self) -> bool: ...


@dataclass(slots=True)
class _TimerEntry:
    timer: TimerLike
    interval_ms: int
    enabled: bool
    suspension_owners: set[str]


class DesiredTimerRegistry:
    """정상 실행 의도와 일시 중단 상태를 분리해 보존합니다."""

    def __init__(self) -> None:
        self._entries: dict[str, _TimerEntry] = {}
        self._shutdown = False

    def register(self, name: str, timer: TimerLike, *, interval_ms: int, enabled: bool = True) -> None:
        if name in self._entries or interval_ms <= 0:
            raise ValueError(f"invalid timer registration: {name}")
        self._entries[name] = _TimerEntry(timer, int(interval_ms), bool(enabled), set())

    def suspend(self, owner: str, names: Iterable[str] | None = None) -> None:
        for entry in self._selected(names):
            entry.suspension_owners.add(owner)
            entry.timer.stop()

    def restart_desired(self) -> None:
        for entry in self._entries.values():
            if entry.enabled and not entry.suspension_owners and not self._shutdown:
                entry.timer.start(entry.interval_ms)
            elif entry.timer.isActive():
                entry.timer.stop()

    def shutdown(self) -> None:
        self._shutdown = True
        for entry in self._entries.values():
            if entry.timer.isActive():
                entry.timer.stop()

    def _selected(self, names: Iterable[str] | None) -> list[_TimerEntry]:
        if names is None:
            return list(self._entries.values())
        return [self._entries[name] for name in names]
