from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.core.remote_local_store import remote_store


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _looks_like_tailscale_ip(value: str | None) -> bool:
    return bool(value and re.match(r"^100\.\d{1,3}\.\d{1,3}\.\d{1,3}$", value.strip()))


def _normalized_tailnet_binding(binding: dict[str, Any] | None) -> dict[str, Any]:
    if not binding:
        return {}
    tailnet_ip = str(binding.get("tailnet_ip") or "").strip()
    tailnet_ips = [
        str(ip).strip()
        for ip in (binding.get("tailnet_ips") or ([tailnet_ip] if tailnet_ip else []))
        if str(ip).strip()
    ]
    if tailnet_ip and tailnet_ip not in tailnet_ips:
        tailnet_ips.insert(0, tailnet_ip)
    return {
        "tailnet_ip": tailnet_ip,
        "tailnet_ips": tailnet_ips,
        "tailnet_dns_name": str(binding.get("tailnet_dns_name") or "").strip(),
        "tailnet_hostname": str(binding.get("tailnet_hostname") or "").strip(),
        "tailnet_os": str(binding.get("tailnet_os") or "").strip(),
        "tailnet_node_id": str(binding.get("tailnet_node_id") or "").strip(),
    }


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
        role: str = "client",
        tailnet_binding: dict[str, Any] | None = None,
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
            "last_source_ip": None,
            "revoked_at": None,
            "role": role or "client",
            **_normalized_tailnet_binding(tailnet_binding),
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

    def validate_token(self, token: str, *, now: float | None = None, source_ip: str | None = None) -> dict[str, Any] | None:
        now = now or time.time()
        token_hash = _sha256(token)
        state = self._read()
        matched: dict[str, Any] | None = None
        for device in state.get("devices", []):
            if device.get("revoked_at"):
                continue
            if secrets.compare_digest(str(device.get("token_hash") or ""), token_hash):
                device["last_seen_at"] = now
                self._observe_source_ip(device, source_ip)
                matched = self._public_device(device)
                break
        if matched:
            self._write(state)
        return matched

    def refresh_token(self, token: str, *, now: float | None = None, source_ip: str | None = None) -> dict[str, Any] | None:
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
            self._observe_source_ip(device, source_ip)
            device["token_refreshed_at"] = now
            self._write(state)
            public = self._public_device(device)
            public["token"] = next_token
            return public
        return None

    def list_devices(self) -> list[dict[str, Any]]:
        return [self._public_device(device) for device in self._read().get("devices", [])]

    def bind_tailnet_device(self, device_id: str, binding: dict[str, Any], *, now: float | None = None) -> bool:
        normalized = _normalized_tailnet_binding(binding)
        if not normalized.get("tailnet_ip"):
            return False
        state = self._read()
        for device in state.get("devices", []):
            if device.get("id") != device_id:
                continue
            device.update(normalized)
            device["tailnet_bound_at"] = now or time.time()
            self._write(state)
            return True
        return False

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
        default = {"schema_version": 2, "active_pairing": None, "devices": []}
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
        if int(data.get("schema_version") or 1) < 2:
            data["schema_version"] = 2
        for device in data.get("devices", []):
            device.setdefault("role", "client")
            device.setdefault("last_source_ip", None)
            device.setdefault("tailnet_ip", "")
            device.setdefault("tailnet_ips", [])
            device.setdefault("tailnet_dns_name", "")
            device.setdefault("tailnet_hostname", "")
            device.setdefault("tailnet_os", "")
            device.setdefault("tailnet_node_id", "")
        return data

    def _write(self, state: dict[str, Any]) -> None:
        state.setdefault("schema_version", 2)
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
            "role": device.get("role") or "client",
            "tailnet_ip": device.get("tailnet_ip") or "",
            "tailnet_ips": device.get("tailnet_ips") or [],
            "tailnet_dns_name": device.get("tailnet_dns_name") or "",
            "tailnet_hostname": device.get("tailnet_hostname") or "",
            "tailnet_os": device.get("tailnet_os") or "",
            "tailnet_node_id": device.get("tailnet_node_id") or "",
            "created_at": device.get("created_at"),
            "last_seen_at": device.get("last_seen_at"),
            "last_source_ip": device.get("last_source_ip"),
            "token_refreshed_at": device.get("token_refreshed_at"),
            "tailnet_bound_at": device.get("tailnet_bound_at"),
            "revoked_at": device.get("revoked_at"),
        }

    def _observe_source_ip(self, device: dict[str, Any], source_ip: str | None) -> None:
        source_ip = (source_ip or "").strip()
        if not source_ip:
            return
        device["last_source_ip"] = source_ip
        if not _looks_like_tailscale_ip(source_ip):
            return
        device["tailnet_ip"] = source_ip
        tailnet_ips = list(device.get("tailnet_ips") or [])
        if source_ip not in tailnet_ips:
            tailnet_ips.insert(0, source_ip)
        device["tailnet_ips"] = tailnet_ips
