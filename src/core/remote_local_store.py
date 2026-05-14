from __future__ import annotations

import hashlib
import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.data.database import data_dir


@dataclass(frozen=True)
class RemoteLocalStore:
    """Durable JSON store for remote runtime/config files under app data.

    Remote files are intentionally kept outside the main SQLite schema when
    they contain bearer-token hashes, local power/runtime config, rotating logs,
    or other host-local operational state.  Writes are atomic, backed up, and
    recorded in a small manifest so Beholder/diagnostics can detect accidental
    evaporation or corruption.
    """

    root: Path = field(default_factory=lambda: Path(data_dir) / "remote")
    legacy_root: Path = field(default_factory=lambda: Path(data_dir))
    max_backups: int = 10

    def path(self, filename: str) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root / filename
        legacy = self.legacy_root / filename
        if not target.exists() and legacy.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(legacy, target)
            self._update_manifest(target)
        return target

    def read_json(self, filename: str, default: dict[str, Any]) -> dict[str, Any]:
        path = self.path(filename)
        if not path.exists():
            return dict(default)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            restored = self.restore_latest_backup(filename)
            if restored is not None:
                return restored
            return dict(default)
        return data if isinstance(data, dict) else dict(default)

    def write_json(self, filename: str, payload: dict[str, Any]) -> Path:
        path = self.path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            self._backup(path)
        tmp = path.with_suffix(path.suffix + f".tmp.{int(time.time() * 1000)}")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(path)
        self._update_manifest(path)
        return path

    def append_jsonl(self, filename: str, payload: dict[str, Any]) -> Path:
        path = self.path(filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        self._update_manifest(path)
        return path

    def restore_latest_backup(self, filename: str) -> dict[str, Any] | None:
        backup_dir = self.root / "backups"
        backups = sorted(backup_dir.glob(f"{filename}.*.bak"), key=lambda item: item.stat().st_mtime, reverse=True)
        for backup in backups:
            try:
                data = json.loads(backup.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            target = self.root / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(backup, target)
            self._update_manifest(target)
            return data if isinstance(data, dict) else None
        return None

    def manifest(self) -> dict[str, Any]:
        path = self.root / "manifest.json"
        if not path.exists():
            return {"schema_version": 1, "files": {}}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"schema_version": 1, "files": {}}
        data.setdefault("schema_version", 1)
        data.setdefault("files", {})
        return data

    def integrity_report(self) -> dict[str, Any]:
        manifest = self.manifest()
        issues: list[dict[str, Any]] = []
        for name, meta in manifest.get("files", {}).items():
            path = self.root / name
            if not path.exists():
                issues.append({"file": name, "issue": "missing"})
                continue
            digest = self._sha256(path)
            if digest != meta.get("sha256"):
                issues.append({"file": name, "issue": "sha256_mismatch"})
        return {"ok": not issues, "issues": issues, "manifest": manifest}

    def _backup(self, path: Path) -> None:
        backup_dir = self.root / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / f"{path.name}.{int(time.time() * 1000)}.bak"
        shutil.copy2(path, backup)
        backups = sorted(backup_dir.glob(f"{path.name}.*.bak"), key=lambda item: item.stat().st_mtime, reverse=True)
        for old in backups[self.max_backups:]:
            old.unlink(missing_ok=True)

    def _update_manifest(self, path: Path) -> None:
        if path.name == "manifest.json" or not path.exists():
            return
        manifest = self.manifest()
        rel = path.name if path.parent == self.root else str(path.relative_to(self.root))
        manifest.setdefault("files", {})[rel] = {
            "sha256": self._sha256(path),
            "size": path.stat().st_size,
            "updated_at": time.time(),
        }
        manifest_path = self.root / "manifest.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = manifest_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(manifest_path)

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()


_DEFAULT_STORE = RemoteLocalStore()


def remote_store() -> RemoteLocalStore:
    return _DEFAULT_STORE
