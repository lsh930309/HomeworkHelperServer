"""Thread-owner-independent coordination helpers for daily check-in runs."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, TypeAlias


DailyCheckInFlightKey: TypeAlias = tuple[str, str, str, str, float]


def make_daily_checkin_flight_key(
    operation: object,
    provider: object,
    process_id: object,
    game_id: object,
    period_start: object,
) -> DailyCheckInFlightKey:
    """Return the canonical key shared by manual and run-due entrypoints."""
    return (
        str(operation or ""),
        str(provider or ""),
        str(process_id or ""),
        str(game_id or ""),
        float(period_start),
    )


class DailyCheckInAlreadyInFlight(RuntimeError):
    """Raised when the same daily check-in operation is already executing."""

    def __init__(self, key: DailyCheckInFlightKey):
        super().__init__("daily_checkin_in_flight")
        self.key = key
        self.code = "daily_checkin_in_flight"


@dataclass
class DailyCheckInFlightLease:
    """Idempotent lease that may be released by any thread."""

    key: DailyCheckInFlightKey
    _release_callback: Callable[[DailyCheckInFlightKey], None]
    _released: bool = False
    _release_lock: threading.Lock = field(
        default_factory=threading.Lock,
        repr=False,
        compare=False,
    )

    def release(self) -> None:
        with self._release_lock:
            if self._released:
                return
            self._released = True
        self._release_callback(self.key)

    def __enter__(self) -> "DailyCheckInFlightLease":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()


class DailyCheckInSingleFlight:
    """Non-blocking keyed admission controller for provider operations."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: set[DailyCheckInFlightKey] = set()

    def try_acquire(
        self,
        operation: object,
        provider: object,
        process_id: object,
        game_id: object,
        period_start: object,
    ) -> DailyCheckInFlightLease | None:
        key = make_daily_checkin_flight_key(
            operation,
            provider,
            process_id,
            game_id,
            period_start,
        )
        with self._lock:
            if key in self._active:
                return None
            self._active.add(key)
        return DailyCheckInFlightLease(key, self._release)

    def acquire_or_raise(
        self,
        operation: object,
        provider: object,
        process_id: object,
        game_id: object,
        period_start: object,
    ) -> DailyCheckInFlightLease:
        lease = self.try_acquire(
            operation,
            provider,
            process_id,
            game_id,
            period_start,
        )
        if lease is None:
            raise DailyCheckInAlreadyInFlight(
                make_daily_checkin_flight_key(
                    operation,
                    provider,
                    process_id,
                    game_id,
                    period_start,
                )
            )
        return lease

    def _release(self, key: DailyCheckInFlightKey) -> None:
        with self._lock:
            self._active.discard(key)

    def snapshot(self) -> tuple[DailyCheckInFlightKey, ...]:
        with self._lock:
            return tuple(sorted(self._active))


def monotonic_deadline(
    timeout_seconds: float,
    *,
    now: Callable[[], float] = time.monotonic,
) -> float:
    """Create an absolute monotonic deadline for a bounded run-due batch."""
    return now() + max(float(timeout_seconds), 0.0)


def remaining_deadline_seconds(
    deadline: float,
    *,
    now: Callable[[], float] = time.monotonic,
) -> float:
    """Return remaining batch time without ever producing a negative value."""
    return max(float(deadline) - now(), 0.0)


def bounded_provider_timeout_seconds(
    deadline: float,
    maximum_seconds: float,
    *,
    now: Callable[[], float] = time.monotonic,
) -> float:
    """Clamp one provider call to both its own limit and the batch deadline."""
    return min(
        remaining_deadline_seconds(deadline, now=now),
        max(float(maximum_seconds), 0.0),
    )


daily_checkin_singleflight = DailyCheckInSingleFlight()
