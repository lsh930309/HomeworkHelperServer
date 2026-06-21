"""Background persistence helper for provider credential health observations."""
from __future__ import annotations

import logging
from typing import Any

from PyQt6.QtCore import QRunnable


logger = logging.getLogger(__name__)


class ProviderHealthPersistTask(QRunnable):
    """Persist provider credential health without blocking the Qt main thread."""

    def __init__(self, data_manager: Any, payload: dict[str, Any], *, context: str):
        super().__init__()
        self._data_manager = data_manager
        self.payload = dict(payload)
        self._context = context

    def run(self) -> None:
        updater = getattr(self._data_manager, "update_provider_credential_health", None)
        if not callable(updater):
            return
        try:
            updater(
                self.payload["provider"],
                self.payload["status"],
                reason=self.payload["reason"],
                message=self.payload["message"],
                source=self.payload["source"],
                process_id=self.payload["process_id"],
                game_id=self.payload["game_id"],
                detected_at=self.payload["detected_at"],
            )
        except Exception as exc:  # pragma: no cover - defensive around UI background persistence
            logger.warning("%s provider health 저장 실패: %s", self._context, exc, exc_info=True)
