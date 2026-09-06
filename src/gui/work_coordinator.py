"""Bounded background work scheduling for the Qt GUI."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import logging
import threading
import time
from types import MappingProxyType
from typing import Any, Callable, Deque, Mapping

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

logger = logging.getLogger(__name__)


_DRAINING_POOLS: set["_PoolLifetime"] = set()
_DRAINING_POOLS_LOCK = threading.Lock()
_DETACHED_RAW_POOLS: set[QThreadPool] = set()
_DETACHED_RAW_POOLS_LOCK = threading.Lock()


def retain_detached_qthreadpool(pool: QThreadPool) -> None:
    """시간 안에 끝나지 않은 parentless pool의 소멸 대기를 피합니다."""
    with _DETACHED_RAW_POOLS_LOCK:
        _DETACHED_RAW_POOLS.add(pool)


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze(item) for item in value)
    return value


@dataclass(frozen=True, slots=True)
class WorkResult:
    lane: str
    key: str
    generation: int
    value: Any


@dataclass(frozen=True, slots=True)
class WorkError:
    lane: str
    key: str
    generation: int
    exception_type: str
    message: str


@dataclass(frozen=True, slots=True)
class WorkCoordinatorSnapshot:
    accepting: bool
    running_telemetry: tuple[str, ...]
    pending_telemetry: tuple[str, ...]
    running_lifecycle: tuple[str, ...]
    pending_lifecycle: Mapping[str, int]


@dataclass(slots=True)
class _WorkSpec:
    lane: str
    key: str
    generation: int
    function: Callable[..., Any]
    args: tuple[Any, ...]
    kwargs: dict[str, Any]


class _PoolLifetime:
    """Keep an unparented pool alive when shutdown reaches its deadline."""

    def __init__(self, max_threads: int) -> None:
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(max_threads)
        self.condition = threading.Condition()
        self.outstanding = 0
        self.detached = False

    def started(self) -> None:
        with self.condition:
            self.outstanding += 1

    def finished(self) -> None:
        remove = False
        with self.condition:
            self.outstanding = max(0, self.outstanding - 1)
            if not self.outstanding:
                self.condition.notify_all()
                remove = self.detached
        if remove:
            with _DRAINING_POOLS_LOCK:
                _DRAINING_POOLS.discard(self)

    def wait_until(self, deadline: float) -> bool:
        with self.condition:
            while self.outstanding:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                self.condition.wait(remaining)
            return True

    def detach(self) -> None:
        with self.condition:
            if not self.outstanding:
                return
            self.detached = True
            with _DRAINING_POOLS_LOCK:
                _DRAINING_POOLS.add(self)


class _WorkerSignals(QObject):
    completed = Signal(object, object, object)


class _Worker(QRunnable):
    def __init__(
        self,
        spec: _WorkSpec,
        signals: _WorkerSignals,
        shutdown_event: threading.Event,
        task_done: Callable[[], None],
    ) -> None:
        super().__init__()
        self._spec = spec
        self._signals = signals
        self._shutdown_event = shutdown_event
        self._task_done = task_done

    def run(self) -> None:
        value: Any = None
        error: BaseException | None = None
        try:
            if not self._shutdown_event.is_set():
                try:
                    value = self._spec.function(*self._spec.args, **self._spec.kwargs)
                except (KeyboardInterrupt, SystemExit) as exc:
                    error = RuntimeError(f"background worker interrupted: {type(exc).__name__}")
                except Exception as exc:
                    error = exc
            try:
                self._signals.completed.emit(self._spec, value, error)
            except RuntimeError:
                logger.debug("GUI background completion relay is already gone")
        finally:
            self._task_done()


class GuiWorkCoordinator(QObject):
    """Coalesce telemetry while preserving per-process lifecycle order."""

    result_ready = Signal(object)
    error_ready = Signal(object)

    DEFAULT_MAX_THREADS = 4
    DEFAULT_SHUTDOWN_DEADLINE_SECONDS = 2.0

    def __init__(self, parent: QObject | None = None, *, max_threads: int = 4) -> None:
        super().__init__(parent)
        if max_threads < 1 or max_threads > self.DEFAULT_MAX_THREADS:
            raise ValueError("max_threads must be between 1 and 4")
        self._lifetime = _PoolLifetime(max_threads)
        self._signals = _WorkerSignals()
        self._signals.completed.connect(self._on_completed)
        self._lock = threading.Lock()
        self._shutdown_event = threading.Event()
        self._accepting = True
        self._telemetry_generation: dict[str, int] = defaultdict(int)
        self._telemetry_running: dict[str, _WorkSpec] = {}
        self._telemetry_pending: dict[str, _WorkSpec] = {}
        self._lifecycle_generation: dict[str, int] = defaultdict(int)
        self._lifecycle_running: dict[str, _WorkSpec] = {}
        self._lifecycle_pending: dict[str, Deque[_WorkSpec]] = defaultdict(deque)
        self._signals_disconnected = False

    @property
    def pool(self) -> QThreadPool:
        return self._lifetime.pool

    def submit_telemetry(self, key: str, function: Callable[..., Any], *args: Any, **kwargs: Any) -> int | None:
        key = self._validate(key, function)
        with self._lock:
            if not self._accepting:
                return None
            self._telemetry_generation[key] += 1
            generation = self._telemetry_generation[key]
            spec = _WorkSpec("telemetry", key, generation, function, args, kwargs)
            if key in self._telemetry_running:
                self._telemetry_pending[key] = spec
                return generation
            self._telemetry_running[key] = spec
        self._start(spec)
        return generation

    def submit_lifecycle(self, process_id: str, function: Callable[..., Any], *args: Any, **kwargs: Any) -> int | None:
        key = self._validate(process_id, function)
        with self._lock:
            if not self._accepting:
                return None
            self._lifecycle_generation[key] += 1
            generation = self._lifecycle_generation[key]
            spec = _WorkSpec("lifecycle", key, generation, function, args, kwargs)
            if key in self._lifecycle_running:
                self._lifecycle_pending[key].append(spec)
                return generation
            self._lifecycle_running[key] = spec
        self._start(spec)
        return generation

    def invalidate_telemetry(self, key: str | None = None) -> None:
        with self._lock:
            keys = [key] if key is not None else list(
                set(self._telemetry_generation) | set(self._telemetry_running) | set(self._telemetry_pending)
            )
            for item in keys:
                self._telemetry_generation[item] += 1
                self._telemetry_pending.pop(item, None)

    def snapshot(self) -> WorkCoordinatorSnapshot:
        with self._lock:
            return WorkCoordinatorSnapshot(
                accepting=self._accepting,
                running_telemetry=tuple(sorted(self._telemetry_running)),
                pending_telemetry=tuple(sorted(self._telemetry_pending)),
                running_lifecycle=tuple(sorted(self._lifecycle_running)),
                pending_lifecycle=MappingProxyType({
                    key: len(queue) for key, queue in sorted(self._lifecycle_pending.items()) if queue
                }),
            )

    def shutdown(self, *, deadline_seconds: float = 2.0) -> bool:
        deadline_seconds = max(0.0, min(float(deadline_seconds), self.DEFAULT_SHUTDOWN_DEADLINE_SECONDS))
        with self._lock:
            self._accepting = False
            self._shutdown_event.set()
            self._telemetry_pending.clear()
            self._lifecycle_pending.clear()
            for key in tuple(self._telemetry_generation):
                self._telemetry_generation[key] += 1
        if not self._signals_disconnected:
            try:
                self._signals.completed.disconnect(self._on_completed)
            except (TypeError, RuntimeError):
                pass
            self._signals_disconnected = True
        drained = self._lifetime.wait_until(time.monotonic() + deadline_seconds)
        if not drained:
            self._lifetime.detach()
        return drained

    @staticmethod
    def _validate(key: str, function: Callable[..., Any]) -> str:
        normalized = str(key).strip()
        if not normalized:
            raise ValueError("work key must not be empty")
        if not callable(function):
            raise TypeError("function must be callable")
        return normalized

    def _start(self, spec: _WorkSpec) -> None:
        self._lifetime.started()
        self._lifetime.pool.start(_Worker(spec, self._signals, self._shutdown_event, self._lifetime.finished))

    @Slot(object, object, object)
    def _on_completed(self, spec: _WorkSpec, value: Any, error: BaseException | None) -> None:
        next_spec: _WorkSpec | None = None
        emit = False
        with self._lock:
            if spec.lane == "telemetry":
                if self._telemetry_running.get(spec.key) is not spec:
                    return
                self._telemetry_running.pop(spec.key, None)
                next_spec = self._telemetry_pending.pop(spec.key, None)
                if next_spec is not None and self._accepting:
                    self._telemetry_running[spec.key] = next_spec
                emit = self._accepting and spec.generation == self._telemetry_generation[spec.key]
            else:
                if self._lifecycle_running.get(spec.key) is not spec:
                    return
                self._lifecycle_running.pop(spec.key, None)
                queue = self._lifecycle_pending.get(spec.key)
                if queue and self._accepting:
                    next_spec = queue.popleft()
                    self._lifecycle_running[spec.key] = next_spec
                if queue is not None and not queue:
                    self._lifecycle_pending.pop(spec.key, None)
                emit = self._accepting
        if next_spec is not None:
            self._start(next_spec)
        if not emit:
            return
        if error is None:
            self.result_ready.emit(WorkResult(spec.lane, spec.key, spec.generation, _freeze(value)))
        else:
            self.error_ready.emit(
                WorkError(spec.lane, spec.key, spec.generation, type(error).__name__, str(error))
            )
