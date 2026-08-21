"""Cross-thread-safe coordination for normal DB traffic and maintenance swaps.

The coordinator deliberately never keeps a thread-owned lock across a request,
SQLAlchemy session, or FastAPI ``yield`` boundary.  Request leases are counters
that may be released by a different worker thread and are idempotent.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from fastapi.responses import JSONResponse


DatabaseAccessMode = Literal["normal", "draining", "maintenance", "faulted"]


@dataclass(frozen=True)
class DatabaseAccessSnapshot:
    mode: DatabaseAccessMode
    active_requests: int
    maintenance_reason: str | None
    maintenance_elapsed_ms: float | None
    last_checkpoint_at: float | None
    fault_code: str | None
    fault_at: float | None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class DatabaseAccessUnavailable(RuntimeError):
    """Raised when a new DB request is rejected by coordinator state."""

    def __init__(self, mode: DatabaseAccessMode):
        self.mode = mode
        if mode == "faulted":
            self.status_code = 503
            self.code = "database_faulted"
            self.detail = "database access disabled after restore failure"
            self.retry_after_seconds = None
        else:
            self.status_code = 503
            self.code = "database_maintenance"
            self.detail = "database maintenance in progress"
            self.retry_after_seconds = 2
        super().__init__(self.detail)


class DatabaseDrainTimeout(RuntimeError):
    """Raised when active DB request leases do not drain before mutation."""

    status_code = 409
    code = "database_drain_timeout"

    def __init__(self, active_requests: int):
        self.active_requests = int(active_requests)
        super().__init__("database drain timed out")


class DatabaseFaultStatePersistenceError(RuntimeError):
    """Raised when a durable fault marker cannot be committed.

    A maintenance guard is written before live database mutation begins, so a
    failure here still leaves restart admission fail-closed.  Callers may keep
    their existing public restore error contract while recording this internal
    persistence failure.
    """

    def __init__(self, operation: str, cause: OSError):
        self.operation = operation
        self.cause = cause
        super().__init__(f"database fault state {operation} failed: {cause}")


def database_access_error_response(exc: DatabaseAccessUnavailable) -> JSONResponse:
    """Return the stable public response for a rejected DB request."""

    body: dict[str, object] = {"detail": exc.detail, "code": exc.code}
    headers: dict[str, str] = {}
    if exc.retry_after_seconds is not None:
        body["retry_after_seconds"] = exc.retry_after_seconds
        headers["Retry-After"] = str(exc.retry_after_seconds)
    return JSONResponse(status_code=exc.status_code, content=body, headers=headers)


def database_drain_timeout_response(exc: DatabaseDrainTimeout) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": str(exc),
            "code": exc.code,
            "active_requests": exc.active_requests,
        },
    )


async def database_access_exception_handler(_request, exc: DatabaseAccessUnavailable) -> JSONResponse:
    """FastAPI/Starlette exception handler preserving the top-level contract."""

    return database_access_error_response(exc)


async def database_drain_timeout_exception_handler(_request, exc: DatabaseDrainTimeout) -> JSONResponse:
    return database_drain_timeout_response(exc)


class DatabaseLease:
    """Ownerless, idempotent request admission lease."""

    def __init__(self, coordinator: "DatabaseMaintenanceCoordinator", route_name: str):
        self._coordinator = coordinator
        self.route_name = route_name
        self._released = False
        self._release_lock = threading.Lock()

    @property
    def released(self) -> bool:
        with self._release_lock:
            return self._released

    def release(self) -> None:
        with self._release_lock:
            if self._released:
                return
            self._released = True
        self._coordinator._release_request()

    def __enter__(self) -> "DatabaseLease":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()


class MaintenanceLease:
    """Idempotent exclusive maintenance state transition lease."""

    def __init__(
        self,
        coordinator: "DatabaseMaintenanceCoordinator",
        *,
        abort_mode: DatabaseAccessMode,
    ):
        self._coordinator = coordinator
        self._abort_mode = abort_mode
        self._released = False
        self._release_lock = threading.Lock()

    def release(self) -> None:
        with self._release_lock:
            if self._released:
                return
            self._released = True
        self._coordinator._finish_maintenance("normal")

    def mark_faulted(self, code: str) -> None:
        with self._release_lock:
            if self._released:
                return
            self._released = True
        self._coordinator._finish_faulted(code)

    def __enter__(self) -> "MaintenanceLease":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if exc_type is None:
            self.release()
            return
        with self._release_lock:
            if self._released:
                return
            self._released = True
        self._coordinator._finish_maintenance(self._abort_mode)


class DatabaseMaintenanceCoordinator:
    """Admit concurrent requests and exclusively drain them for DB swaps."""

    def __init__(
        self,
        *,
        fault_state_path: str | os.PathLike[str] | None = None,
        release_id: str | None = None,
        clock=time.time,
        monotonic=time.monotonic,
    ):
        self._condition = threading.Condition(threading.Lock())
        self._fault_persistence_lock = threading.Lock()
        self._state_generation = 0
        self._clock = clock
        self._monotonic = monotonic
        self._fault_state_path = Path(fault_state_path) if fault_state_path else None
        self._release_id = release_id or os.environ.get("HOMEWORK_HELPER_RELEASE_ID") or "unknown"
        self._mode: DatabaseAccessMode = "normal"
        self._active_requests = 0
        self._maintenance_reason: str | None = None
        self._maintenance_started_monotonic: float | None = None
        self._last_checkpoint_at: float | None = None
        self._fault_code: str | None = None
        self._fault_at: float | None = None
        self._load_fault_state()

    def acquire_request(self, route_name: str) -> DatabaseLease:
        with self._condition:
            if self._mode != "normal":
                raise DatabaseAccessUnavailable(self._mode)
            self._active_requests += 1
        return DatabaseLease(self, route_name)

    def try_acquire_request(self, route_name: str) -> DatabaseLease | None:
        """Non-blocking admission intended for optional periodic work."""

        with self._condition:
            if self._mode != "normal":
                return None
            self._active_requests += 1
        return DatabaseLease(self, route_name)

    def acquire_fault_recovery_read(self, route_name: str) -> DatabaseLease:
        """Admit a read used solely to inspect recovery data while faulted.

        Fault recovery reads share the active-request counter with ordinary
        requests.  Consequently ``begin_fault_recovery`` drains them before a
        live database replace and cannot race an open SQLite read handle.
        """

        with self._condition:
            if self._mode != "faulted":
                raise DatabaseAccessUnavailable(self._mode)
            self._active_requests += 1
        return DatabaseLease(self, route_name)

    def begin_maintenance(
        self,
        reason: str,
        drain_timeout_seconds: float = 5.0,
    ) -> MaintenanceLease:
        return self._begin_maintenance(
            reason,
            drain_timeout_seconds=drain_timeout_seconds,
            required_mode="normal",
        )

    def begin_fault_recovery(
        self,
        reason: str,
        drain_timeout_seconds: float = 5.0,
    ) -> MaintenanceLease:
        return self._begin_maintenance(
            reason,
            drain_timeout_seconds=drain_timeout_seconds,
            required_mode="faulted",
        )

    def _begin_maintenance(
        self,
        reason: str,
        *,
        drain_timeout_seconds: float,
        required_mode: DatabaseAccessMode,
    ) -> MaintenanceLease:
        timeout = max(0.0, float(drain_timeout_seconds))
        with self._condition:
            if self._mode != required_mode:
                raise DatabaseAccessUnavailable(self._mode)
            return_mode = required_mode
            self._mode = "draining"
            self._maintenance_reason = reason
            self._maintenance_started_monotonic = self._monotonic()
            deadline = self._monotonic() + timeout
            while self._active_requests:
                remaining = deadline - self._monotonic()
                if remaining <= 0:
                    active_requests = self._active_requests
                    self._mode = return_mode
                    self._clear_maintenance_metadata()
                    self._condition.notify_all()
                    raise DatabaseDrainTimeout(active_requests)
                self._condition.wait(remaining)

        # Arm a durable write-ahead guard outside the condition lock.  If the
        # process exits during restore, or the detailed fault sentinel later
        # cannot be committed, the next process still starts faulted.  A guard
        # failure occurs before the caller can mutate the live database.
        try:
            self._arm_maintenance_guard(reason, required_mode=required_mode)
        except OSError as exc:
            with self._condition:
                if self._mode == "draining":
                    self._mode = return_mode
                    self._clear_maintenance_metadata()
                    self._condition.notify_all()
            raise DatabaseFaultStatePersistenceError("guard_write", exc) from exc

        with self._condition:
            if self._mode != "draining":
                raise DatabaseAccessUnavailable(self._mode)
            self._mode = "maintenance"
        return MaintenanceLease(self, abort_mode=return_mode)

    def snapshot(self) -> DatabaseAccessSnapshot:
        with self._condition:
            elapsed_ms = None
            if self._maintenance_started_monotonic is not None:
                elapsed_ms = max(
                    0.0,
                    (self._monotonic() - self._maintenance_started_monotonic) * 1000.0,
                )
            return DatabaseAccessSnapshot(
                mode=self._mode,
                active_requests=self._active_requests,
                maintenance_reason=self._maintenance_reason,
                maintenance_elapsed_ms=elapsed_ms,
                last_checkpoint_at=self._last_checkpoint_at,
                fault_code=self._fault_code,
                fault_at=self._fault_at,
            )

    def record_checkpoint(self, timestamp: float | None = None) -> None:
        with self._condition:
            self._last_checkpoint_at = self._clock() if timestamp is None else float(timestamp)

    def _release_request(self) -> None:
        with self._condition:
            if self._active_requests <= 0:
                return
            self._active_requests -= 1
            if self._active_requests == 0:
                self._condition.notify_all()

    def _finish_maintenance(self, mode: DatabaseAccessMode) -> None:
        with self._condition:
            if self._mode != "maintenance":
                return

        if mode == "normal":
            try:
                self._remove_fault_state()
            except OSError as exc:
                fault_at = self._clock()
                with self._condition:
                    if self._mode == "maintenance":
                        self._mode = "faulted"
                        self._state_generation += 1
                        self._fault_code = "database_fault_state_clear_failed"
                        self._fault_at = fault_at
                        self._clear_maintenance_metadata()
                        self._condition.notify_all()
                raise DatabaseFaultStatePersistenceError("sentinel_clear", exc) from exc

        with self._condition:
            if self._mode != "maintenance":
                return
            self._mode = mode
            self._state_generation += 1
            self._clear_maintenance_metadata()
            if mode == "normal":
                self._fault_code = None
                self._fault_at = None
            self._condition.notify_all()

    def _finish_faulted(self, code: str) -> None:
        fault_at = self._clock()
        with self._condition:
            self._mode = "faulted"
            self._state_generation += 1
            transition_generation = self._state_generation
            self._fault_code = str(code)
            self._fault_at = fault_at
            self._clear_maintenance_metadata()
            self._condition.notify_all()
        try:
            self._write_fault_state(
                transition_generation,
                fault_code=str(code),
                fault_at=fault_at,
            )
        except OSError as exc:
            # Do not downgrade or swallow this failure.  The maintenance guard
            # remains on disk so a new process still denies ordinary DB access.
            raise DatabaseFaultStatePersistenceError("sentinel_write", exc) from exc

    def _clear_maintenance_metadata(self) -> None:
        self._maintenance_reason = None
        self._maintenance_started_monotonic = None

    def _load_fault_state(self) -> None:
        path = self._fault_state_path
        if path is None:
            return
        candidates = (
            path,
            self._temporary_path(path),
            self._maintenance_guard_path(path),
            self._temporary_path(self._maintenance_guard_path(path)),
        )
        existing = next((candidate for candidate in candidates if candidate.exists()), None)
        if existing is None:
            return
        try:
            payload = json.loads(existing.read_text(encoding="utf-8"))
            self._fault_code = str(payload["code"])
            self._fault_at = float(payload["timestamp"])
            self._mode = "faulted"
            self._state_generation += 1
        except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            self._fault_code = "database_fault_state_unreadable"
            self._fault_at = self._clock()
            self._mode = "faulted"
            self._state_generation += 1

    @staticmethod
    def _temporary_path(path: Path) -> Path:
        return path.with_name(path.name + ".tmp")

    @staticmethod
    def _maintenance_guard_path(path: Path) -> Path:
        return path.with_name(path.name + ".guard")

    @staticmethod
    def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
        """Atomically commit JSON and flush both content and directory metadata.

        The temporary file is intentionally retained on failure.  Startup
        treats any canonical, guard, or pending marker as faulted, including a
        partially-written file whose JSON cannot be decoded.
        """

        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = DatabaseMaintenanceCoordinator._temporary_path(path)
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        with temporary.open("wb") as output:
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        with path.open("rb") as committed:
            os.fsync(committed.fileno())
        if os.name != "nt":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)

    def _arm_maintenance_guard(
        self,
        _reason: str,
        *,
        required_mode: DatabaseAccessMode,
    ) -> None:
        path = self._fault_state_path
        if path is None:
            return
        if required_mode == "faulted":
            # The canonical sentinel or the guard that caused startup to enter
            # faulted mode is already the durable write-ahead marker.
            return
        guard_path = self._maintenance_guard_path(path)
        database_path = path.parent / "app_data.db"
        database_sha256 = self._database_sha256(database_path)
        self._atomic_write_json(
            guard_path,
            {
                "code": "database_maintenance_interrupted",
                "timestamp": self._clock(),
                "release_id": self._release_id,
                "database_path": str(database_path),
                "database_sha256": database_sha256,
            },
        )

    @staticmethod
    def _database_sha256(database_path: Path) -> str | None:
        if not database_path.exists():
            return None
        digest = hashlib.sha256()
        try:
            with database_path.open("rb") as database_file:
                for chunk in iter(lambda: database_file.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError:
            return None
        return digest.hexdigest()

    def _write_fault_state(
        self,
        expected_generation: int,
        *,
        fault_code: str,
        fault_at: float,
    ) -> None:
        path = self._fault_state_path
        if path is None:
            return
        with self._fault_persistence_lock:
            with self._condition:
                if (
                    self._state_generation != expected_generation
                    or self._mode != "faulted"
                    or self._fault_code != fault_code
                    or self._fault_at != fault_at
                ):
                    return
            database_path = path.parent / "app_data.db"
            database_sha256 = self._database_sha256(database_path)
            payload = {
                "code": fault_code,
                "timestamp": fault_at,
                "release_id": self._release_id,
                "database_path": str(database_path),
                "database_sha256": database_sha256,
            }
            self._atomic_write_json(path, payload)

    def _remove_fault_state(self) -> None:
        path = self._fault_state_path
        if path is not None:
            with self._fault_persistence_lock:
                with self._condition:
                    if self._mode != "maintenance":
                        return
                for candidate in (
                    path,
                    self._temporary_path(path),
                    self._maintenance_guard_path(path),
                    self._temporary_path(self._maintenance_guard_path(path)),
                ):
                    try:
                        candidate.unlink()
                    except FileNotFoundError:
                        pass


def create_database_coordinator(data_directory: str | os.PathLike[str]) -> DatabaseMaintenanceCoordinator:
    from src.core.runtime_identity import runtime_identity

    return DatabaseMaintenanceCoordinator(
        fault_state_path=Path(data_directory) / "database_fault_state.json",
        release_id=str(runtime_identity()["release_id"]),
    )
