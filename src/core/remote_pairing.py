from __future__ import annotations

import hashlib
import json
import secrets
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.core.remote_local_store import remote_store


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass
class RemoteDeviceRegistry:
    """File-backed pairing and device-token registry for remote clients."""

    path: Path = field(default_factory=lambda: remote_store().path("remote_devices.json"))
    code_ttl_seconds: int = 300

    def start_pairing(self, *, now: float | None = None) -> dict[str, Any]:
        now = now or time.time()
        code = f"{secrets.randbelow(1_000_000):06d}"
        state = self._read()
        state["active_pairing"] = {
            "code_hash": _sha256(code),
            "expires_at": now + self.code_ttl_seconds,
            "created_at": now,
        }
        self._write(state)
        return {"code": code, "expires_at": state["active_pairing"]["expires_at"]}

    def confirm_pairing(
        self,
        *,
        code: str,
        device_name: str,
        platform: str | None = None,
        now: float | None = None,
    ) -> dict[str, Any] | None:
        now = now or time.time()
        state = self._read()
        active = state.get("active_pairing") or {}
        expires_at = float(active.get("expires_at") or 0)
        if not active or expires_at < now:
            return None
        if not secrets.compare_digest(str(active.get("code_hash") or ""), _sha256(code)):
            return None

        token = secrets.token_urlsafe(32)
        device = {
            "id": str(uuid.uuid4()),
            "name": device_name.strip() or "Unnamed device",
            "platform": platform or "unknown",
            "token_hash": _sha256(token),
            "created_at": now,
            "last_seen_at": None,
            "revoked_at": None,
        }
        devices = state.setdefault("devices", [])
        devices.append(device)
        state["active_pairing"] = None
        self._write(state)
        public = self._public_device(device)
        public["token"] = token
        return public

    def has_active_devices(self) -> bool:
        state = self._read()
        return any(not device.get("revoked_at") for device in state.get("devices", []))

    def has_registered_devices(self) -> bool:
        return bool(self._read().get("devices", []))

    def validate_token(self, token: str, *, now: float | None = None) -> dict[str, Any] | None:
        now = now or time.time()
        token_hash = _sha256(token)
        state = self._read()
        matched: dict[str, Any] | None = None
        for device in state.get("devices", []):
            if device.get("revoked_at"):
                continue
            if secrets.compare_digest(str(device.get("token_hash") or ""), token_hash):
                device["last_seen_at"] = now
                matched = self._public_device(device)
                break
        if matched:
            self._write(state)
        return matched

    def refresh_token(self, token: str, *, now: float | None = None) -> dict[str, Any] | None:
        """Rotate an active device token and return the new bearer token.

        The old token becomes invalid immediately. Static HH_REMOTE_TOKEN values
        are intentionally not refreshable because they are not device-bound.
        """

        now = now or time.time()
        token_hash = _sha256(token)
        state = self._read()
        for device in state.get("devices", []):
            if device.get("revoked_at"):
                continue
            if not secrets.compare_digest(str(device.get("token_hash") or ""), token_hash):
                continue
            next_token = secrets.token_urlsafe(32)
            device["token_hash"] = _sha256(next_token)
            device["last_seen_at"] = now
            device["token_refreshed_at"] = now
            self._write(state)
            public = self._public_device(device)
            public["token"] = next_token
            return public
        return None

    def list_devices(self) -> list[dict[str, Any]]:
        return [self._public_device(device) for device in self._read().get("devices", [])]

    def revoke_device(self, device_id: str, *, now: float | None = None) -> bool:
        now = now or time.time()
        state = self._read()
        changed = False
        for device in state.get("devices", []):
            if device.get("id") == device_id and not device.get("revoked_at"):
                device["revoked_at"] = now
                changed = True
                break
        if changed:
            self._write(state)
        return changed

    def purge_revoked_devices(self) -> int:
        state = self._read()
        before = len(state.get("devices", []))
        state["devices"] = [device for device in state.get("devices", []) if not device.get("revoked_at")]
        removed = before - len(state["devices"])
        if removed:
            self._write(state)
        return removed

    def _read(self) -> dict[str, Any]:
        default = {"schema_version": 1, "active_pairing": None, "devices": []}
        try:
            if self.path.parent == remote_store().root:
                data = remote_store().read_json(self.path.name, default)
            elif self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
            else:
                data = default
        except (OSError, json.JSONDecodeError):
            data = default
        data.setdefault("schema_version", 1)
        data.setdefault("active_pairing", None)
        data.setdefault("devices", [])
        return data

    def _write(self, state: dict[str, Any]) -> None:
        state.setdefault("schema_version", 1)
        if self.path.parent == remote_store().root:
            remote_store().write_json(self.path.name, state)
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    def _public_device(self, device: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": device.get("id"),
            "name": device.get("name"),
            "platform": device.get("platform"),
            "created_at": device.get("created_at"),
            "last_seen_at": device.get("last_seen_at"),
            "token_refreshed_at": device.get("token_refreshed_at"),
            "revoked_at": device.get("revoked_at"),
        }
