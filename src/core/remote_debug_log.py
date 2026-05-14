from __future__ import annotations

import json
import os
import platform
import time
from pathlib import Path
from typing import Any

from src.data.database import data_dir

CONFIG_PATH = Path(data_dir) / "remote_debug_logging.json"


def desktop_log_path(filename: str = "HomeworkHelperRemoteHost.log") -> Path:
    if platform.system().lower() == "windows":
        candidates = [
            Path(os.environ.get("USERPROFILE") or str(Path.home())) / "Desktop",
            Path(os.environ.get("ONEDRIVE") or "") / "Desktop" if os.environ.get("ONEDRIVE") else None,
            Path(os.environ.get("OneDriveConsumer") or "") / "Desktop" if os.environ.get("OneDriveConsumer") else None,
        ]
        for candidate in candidates:
            if candidate and candidate.exists():
                return candidate / filename
        return (Path(os.environ.get("USERPROFILE") or str(Path.home())) / "Desktop") / filename
    desktop = Path.home() / "Desktop"
    return (desktop if desktop.exists() else Path.home()) / filename


def load_config() -> dict[str, Any]:
    if os.environ.get("HH_REMOTE_DESKTOP_LOG") in {"1", "true", "yes", "on"}:
        return {"enabled": True, "path": str(desktop_log_path())}
    if not CONFIG_PATH.exists():
        return {"enabled": False, "path": str(desktop_log_path())}
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"enabled": False, "path": str(desktop_log_path())}
    return {"enabled": bool(data.get("enabled")), "path": str(data.get("path") or desktop_log_path())}


def save_config(enabled: bool, path: str | None = None) -> dict[str, Any]:
    payload = {"enabled": bool(enabled), "path": str(path or desktop_log_path())}
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def write_event(event: str, **fields: Any) -> None:
    try:
        config = load_config()
        if not config.get("enabled"):
            return
        path = Path(str(config.get("path") or desktop_log_path()))
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({"ts": time.time(), "event": event, **fields}, ensure_ascii=False, sort_keys=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        return
