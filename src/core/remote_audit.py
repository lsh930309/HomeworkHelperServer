from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.data.database import data_dir


@dataclass
class RemoteAuditLogger:
    """Append-only JSONL audit log for remote-control commands."""

    path: Path = field(default_factory=lambda: Path(data_dir) / "remote_command_audit.jsonl")

    def record(
        self,
        *,
        command: str,
        accepted: bool,
        status: str,
        target_id: str | None = None,
        target_name: str | None = None,
        target: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = {
            "id": str(uuid.uuid4()),
            "created_at": time.time(),
            "command": command,
            "accepted": accepted,
            "status": status,
            "target_id": target_id,
            "target_name": target_name,
            "target": target,
            "metadata": metadata or {},
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
        return event
