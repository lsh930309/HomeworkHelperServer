"""Background persistence helper for provider credential health observations."""
from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QRunnable


logger = logging.getLogger(__name__)


class ProviderHealthPersistTask(QRunnable):
    """Persist provider credential health without blocking the Qt main thread."""

    def __init__(self, transport: Any, payload: dict[str, Any], *, context: str):
        super().__init__()
        self._transport = transport
        self.payload = dict(payload)
        self._context = context

    def run(self) -> None:
        try:
            self._transport.update_provider_credential_health(self.payload)
        except Exception as exc:  # pragma: no cover - defensive around UI background persistence
            logger.warning("%s provider health 저장 실패: %s", self._context, exc, exc_info=True)
