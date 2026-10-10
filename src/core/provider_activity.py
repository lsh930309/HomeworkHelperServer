"""In-memory provider overlap logging without admission or persistence."""
from __future__ import annotations

from contextlib import contextmanager
import logging
import threading
from typing import Iterator

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_active = 0


@contextmanager
def provider_activity(provider: str, operation: str) -> Iterator[None]:
    global _active
    with _lock:
        _active += 1
        overlap = _active
    logger.info("provider work start: provider=%s operation=%s overlap=%s", provider, operation, overlap)
    try:
        yield
    finally:
        with _lock:
            _active = max(0, _active - 1)
            remaining = _active
        logger.info("provider work end: provider=%s operation=%s overlap=%s", provider, operation, remaining)
