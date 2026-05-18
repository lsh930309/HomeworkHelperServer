from __future__ import annotations

import platform


class UnsupportedPowerController:
    """Read-only power readiness adapter.

    Power side effects are intentionally owned by remote clients. The host API
    only reports setup/readiness so clients can decide whether their direct
    SmartThings/OpenSSH command path is usable.
    """

    configured = False

    def status(self) -> dict[str, object]:
        return _client_managed_status(self.__class__.__name__)


class ConfigurablePowerController:
    """Compatibility name for the host's client-managed power contract.

    Older builds stored SmartThings and SSH fields on the host, but the current
    design keeps those values on each client.  The host must not persist wake
    device ids, local SmartThings paths, SSH targets, or private-key paths.
    """

    configured = False

    def status(self) -> dict[str, object]:
        return _client_managed_status(self.__class__.__name__)


def _client_managed_status(adapter: str) -> dict[str, object]:
    return {
        "configured": False,
        "state": "client_managed",
        "status": "client_managed",
        "adapter": adapter,
        "host_platform": platform.system() or "unknown",
        "supported_actions": [],
        "target_host": "",
        "ssh_host_configured": False,
        "smartthings_configured": False,
        "message": "전원 실행은 클라이언트가 SmartThings/OpenSSH 직접 경로로 관리합니다. 호스트는 OpenSSH key 등록/준비 상태만 제공합니다.",
    }
