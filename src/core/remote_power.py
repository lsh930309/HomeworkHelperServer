from __future__ import annotations

import json
import os
import platform
import socket
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal, Sequence

from src.core.remote_local_store import remote_store


PowerAction = Literal["wake", "shutdown", "sleep", "restart"]


@dataclass(frozen=True)
class PowerActionResult:
    """Normalized result for remote desktop power commands."""

    accepted: bool
    action: PowerAction | str
    status: str
    message: str


class UnsupportedPowerController:
    """Safe default power adapter used until a concrete environment is wired.

    The first remote-controller milestone must not expose arbitrary shell power
    commands.  This adapter gives native clients a stable capability contract
    while reporting that the current runtime is not yet configured for power
    control.
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
            "message": "원격 전원 제어 adapter가 아직 설정되지 않았습니다.",
        }

    def perform(self, action: PowerAction) -> PowerActionResult:
        return PowerActionResult(
            accepted=False,
            action=action,
            status="unsupported",
            message="원격 전원 제어 adapter가 아직 설정되지 않았습니다.",
        )


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
        return bool(self.ssh_host and self.ssh_user and self.ssh_key_path and self.ssh_port)

    @property
    def configured(self) -> bool:
        return self.wake_configured or self.ssh_configured


class ConfigurablePowerController:
    """SmartThings WoL + SSH power adapter based on pc_remote.

    This class only exposes an allowlisted command set.  It never accepts raw
    shell input from remote clients.
    """

    def __init__(
        self,
        config: RemotePowerConfig | None = None,
        *,
        runner: Callable[[Sequence[str], float], bool] | None = None,
        tcp_checker: Callable[[str, int, float], bool] | None = None,
    ):
        self.config = config or RemotePowerConfig.load()
        self._runner = runner or self._run_process
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
            "message": "전원 제어 adapter가 설정되었습니다." if self.config.configured else "원격 전원 제어 adapter가 아직 설정되지 않았습니다.",
        }

    def perform(self, action: PowerAction) -> PowerActionResult:
        if action == "wake":
            return self._wake()
        if action == "shutdown":
            return self._ssh_action(action, "shutdown /s /t 0")
        if action == "sleep":
            return self._ssh_action(
                action,
                "rundll32.exe powrprof.dll,SetSuspendState 0,0,0",
                extra_args=["-o", "ServerAliveInterval=2", "-o", "ServerAliveCountMax=2"],
            )
        if action == "restart":
            return self._ssh_action(action, "shutdown /r /t 0")
        return PowerActionResult(False, action, "unsupported", "지원하지 않는 전원 명령입니다.")

    def _wake(self) -> PowerActionResult:
        if not self.config.wake_configured:
            return PowerActionResult(False, "wake", "not_configured", "SmartThings WoL 설정이 없습니다.")
        ok = self._runner(
            [self.config.smartthings_cli_path, "devices:commands", self.config.smartthings_device_id, "switch:on"],
            30.0,
        )
        return PowerActionResult(ok, "wake", "accepted" if ok else "failed", "WoL 신호 전송 완료" if ok else "WoL 신호 전송 실패")

    def _ssh_action(self, action: PowerAction, command: str, *, extra_args: list[str] | None = None) -> PowerActionResult:
        if not self.config.ssh_configured:
            return PowerActionResult(False, action, "not_configured", "SSH 전원 제어 설정이 없습니다.")
        key_path = os.path.expanduser(self.config.ssh_key_path)
        args = [
            "/usr/bin/ssh",
            "-i",
            key_path,
            "-p",
            str(self.config.ssh_port),
            "-o",
            "ConnectTimeout=5",
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=no",
        ]
        args.extend(extra_args or [])
        args.extend([f"{self.config.ssh_user}@{self.config.ssh_host}", command])
        ok = self._runner(args, 20.0)
        return PowerActionResult(ok, action, "accepted" if ok else "failed", "전원 명령 전송 완료" if ok else "전원 명령 전송 실패")

    def _run_process(self, args: Sequence[str], timeout_seconds: float) -> bool:
        try:
            result = subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=timeout_seconds, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return False
        return result.returncode == 0

    def _check_tcp(self, host: str, port: int, timeout_seconds: float) -> bool:
        try:
            with socket.create_connection((host, port), timeout=timeout_seconds):
                return True
        except OSError:
            return False
