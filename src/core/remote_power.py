from __future__ import annotations

import platform
import subprocess
import threading
import time
import uuid
from typing import Callable, Sequence

PowerRunner = Callable[[Sequence[str]], object]

_HOST_ACTION_COMMANDS: dict[str, list[str]] = {
    "sleep": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,0,0"],
    "restart": ["shutdown", "/r", "/t", "0"],
    "shutdown": ["shutdown", "/s", "/t", "0"],
}


class UnsupportedPowerController:
    """Host-side power action adapter for unsupported platforms."""

    configured = False

    def status(self) -> dict[str, object]:
        return _host_delegated_status(self.__class__.__name__)

    def schedule_action(self, action: str, *, delay_seconds: float = 0.35) -> dict[str, object]:
        return _unsupported_action_result(action)


class ConfigurablePowerController:
    """Host HTTPS-delegated power controller.

    Wake remains client-owned through SmartThings because this deployment cannot
    forward WoL packets through the router.  The host exposes only a narrow,
    authenticated HTTPS surface for local Windows sleep/restart/shutdown.
    """

    def __init__(self, *, runner: PowerRunner | None = None):
        self._runner = runner or _default_runner

    @property
    def configured(self) -> bool:
        return _is_windows()

    def status(self) -> dict[str, object]:
        return _host_delegated_status(self.__class__.__name__)

    def schedule_action(self, action: str, *, delay_seconds: float = 0.35) -> dict[str, object]:
        normalized = action.strip().lower()
        if normalized not in _HOST_ACTION_COMMANDS:
            raise ValueError(f"지원하지 않는 전원 명령입니다: {action}")
        if not _is_windows():
            return _unsupported_action_result(normalized)

        command_id = f"power.{normalized}:{uuid.uuid4().hex}"
        command = _HOST_ACTION_COMMANDS[normalized]
        thread = threading.Thread(
            target=_run_after_delay,
            args=(self._runner, command, delay_seconds),
            name=f"HomeworkHelperPower-{normalized}",
            daemon=True,
        )
        thread.start()
        return {
            "accepted": True,
            "command": f"power.{normalized}",
            "target": "host",
            "status": "accepted",
            "message": f"호스트에 {normalized} 명령을 예약했습니다. Wake는 SmartThings 클라이언트 경로를 계속 사용합니다.",
            "command_id": command_id,
            "accepted_at": time.time(),
            "refresh_after_ms": 1500,
            "action": normalized,
        }


def _is_windows() -> bool:
    return platform.system().lower() == "windows"


def _host_delegated_status(adapter: str) -> dict[str, object]:
    windows = _is_windows()
    actions = sorted(_HOST_ACTION_COMMANDS) if windows else []
    return {
        "configured": windows,
        "state": "ready" if windows else "unsupported",
        "status": "ready" if windows else "unsupported",
        "adapter": adapter,
        "host_platform": platform.system() or "unknown",
        "supported_actions": actions,
        "host_actions": actions,
        "target_host": "localhost" if windows else "",
        "wake_mode": "smartthings_client",
        "ssh_required": False,
        "ssh_host_configured": False,
        "smartthings_configured": False,
        "message": (
            "Wake는 클라이언트 SmartThings 경로를 사용하고, 절전/재시작/종료는 인증된 HTTPS Remote Agent가 호스트 로컬 명령으로 수행합니다."
            if windows
            else "호스트 위임 전원 명령은 Windows 호스트에서만 지원합니다. Wake는 클라이언트 SmartThings 경로를 사용합니다."
        ),
    }


def _unsupported_action_result(action: str) -> dict[str, object]:
    return {
        "accepted": False,
        "command": f"power.{action}",
        "target": "host",
        "status": "unsupported",
        "message": "호스트 위임 전원 명령은 Windows 호스트에서만 지원합니다.",
        "command_id": None,
        "accepted_at": None,
        "refresh_after_ms": None,
        "action": action,
    }


def _default_runner(command: Sequence[str]) -> object:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(list(command), close_fds=True, creationflags=creationflags)


def _run_after_delay(runner: PowerRunner, command: Sequence[str], delay_seconds: float) -> None:
    time.sleep(max(0.0, delay_seconds))
    try:
        runner(command)
    except Exception:
        # The HTTP response has already been returned.  Failures are intentionally
        # swallowed here and should be diagnosed through host logs/audit trails.
        return
