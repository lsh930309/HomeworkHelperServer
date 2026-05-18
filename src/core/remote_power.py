from __future__ import annotations

import json
import os
import platform
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from src.core.remote_local_store import remote_store


class UnsupportedPowerController:
    """Read-only power readiness adapter.

    Power side effects are intentionally owned by remote clients. The host API
    only reports setup/readiness so clients can decide whether their direct
    SmartThings/OpenSSH command path is usable.
    """

    configured = False

    def status(self) -> dict[str, object]:
        return {
            "configured": False,
            "state": "unknown",
            "status": "unknown",
            "adapter": self.__class__.__name__,
            "host_platform": platform.system() or "unknown",
            "supported_actions": [],
            "target_host": "",
            "message": "클라이언트 직접 전원 경로(SmartThings/OpenSSH)가 아직 설정되지 않았습니다.",
        }


@dataclass(frozen=True)
class RemotePowerConfig:
    """Configuration adapted from the standalone pc_remote project."""

    smartthings_device_id: str = ""
    smartthings_cli_path: str = ""
    ssh_host: str = ""
    ssh_port: int = 22
    ssh_user: str = ""
    ssh_key_path: str = ""
    status_timeout_seconds: float = 4.0

    @staticmethod
    def sanitize_smartthings_cli_path(path: str) -> str:
        value = str(path or "").strip()
        if platform.system().lower() == "windows" and value.startswith("/"):
            return ""
        return value

    @classmethod
    def load(cls, path: Path | None = None) -> "RemotePowerConfig":
        path = path or remote_store().path("remote_power_config.json")
        data: dict[str, object] = {}
        if path.exists():
            try:
                data.update(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                data = {}

        env_map = {
            "smartthings_device_id": "HH_REMOTE_SMARTTHINGS_DEVICE_ID",
            "smartthings_cli_path": "HH_REMOTE_SMARTTHINGS_CLI_PATH",
            "ssh_host": "HH_REMOTE_SSH_HOST",
            "ssh_port": "HH_REMOTE_SSH_PORT",
            "ssh_user": "HH_REMOTE_SSH_USER",
            "ssh_key_path": "HH_REMOTE_SSH_KEY_PATH",
            "status_timeout_seconds": "HH_REMOTE_STATUS_TIMEOUT_SECONDS",
        }
        for key, env_name in env_map.items():
            if os.environ.get(env_name):
                data[key] = os.environ[env_name]

        return cls(
            smartthings_device_id=str(data.get("smartthings_device_id") or ""),
            smartthings_cli_path=cls.sanitize_smartthings_cli_path(str(data.get("smartthings_cli_path") or "")),
            ssh_host=str(data.get("ssh_host") or ""),
            ssh_port=int(data.get("ssh_port") or 22),
            ssh_user=str(data.get("ssh_user") or ""),
            ssh_key_path=str(data.get("ssh_key_path") or ""),
            status_timeout_seconds=float(data.get("status_timeout_seconds") or 4.0),
        )

    @property
    def wake_configured(self) -> bool:
        return bool(self.smartthings_device_id and self.smartthings_cli_path)

    @property
    def ssh_configured(self) -> bool:
        return bool(self.ssh_host and self.ssh_user and self.ssh_port)

    @property
    def configured(self) -> bool:
        return self.wake_configured or self.ssh_configured


class ConfigurablePowerController:
    """Read-only SmartThings/OpenSSH readiness model based on pc_remote.

    The original pc_remote contract sends wake/sleep/shutdown/restart directly
    from the client device. This server-side object therefore reports config and
    TCP readiness only; it must not execute power commands on behalf of clients.
    """

    def __init__(
        self,
        config: RemotePowerConfig | None = None,
        *,
        tcp_checker: Callable[[str, int, float], bool] | None = None,
    ):
        self.config = config or RemotePowerConfig.load()
        self._tcp_checker = tcp_checker or self._check_tcp

    @property
    def configured(self) -> bool:
        return self.config.configured

    def status(self) -> dict[str, object]:
        supported_actions = []
        if self.config.wake_configured:
            supported_actions.append("wake")
        if self.config.ssh_configured:
            supported_actions.extend(["shutdown", "sleep", "restart"])
        state = "unknown"
        if self.config.ssh_configured:
            state = "on" if self._tcp_checker(self.config.ssh_host, self.config.ssh_port, self.config.status_timeout_seconds) else "off"
        return {
            "configured": self.config.configured,
            "state": state,
            "status": state,
            "adapter": self.__class__.__name__,
            "host_platform": platform.system() or "unknown",
            "supported_actions": supported_actions,
            "target_host": self.config.ssh_host if self.config.ssh_configured else "",
            "ssh_host_configured": bool(self.config.ssh_host),
            "smartthings_configured": self.config.wake_configured,
            "message": (
                "클라이언트 직접 전원 경로(SmartThings/OpenSSH) 설정이 준비되었습니다."
                if self.config.configured
                else "클라이언트 직접 전원 경로(SmartThings/OpenSSH)가 아직 설정되지 않았습니다."
            ),
        }

    def _check_tcp(self, host: str, port: int, timeout_seconds: float) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout_seconds):
                return True
        except OSError:
            return False
