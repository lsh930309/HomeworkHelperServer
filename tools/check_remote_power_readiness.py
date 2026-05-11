#!/usr/bin/env python3
"""Report Remote Controller power-adapter readiness without sending commands.

This preflight validates configuration shape and local tool/key paths only.  It
never calls SmartThings, never opens SSH, and never performs wake/shutdown/sleep
/restart actions.
"""

from __future__ import annotations

import argparse
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.core.remote_power import RemotePowerConfig
from src.data.database import data_dir


DEFAULT_CONFIG = Path(data_dir) / "remote_power_config.json"
POWER_ACTIONS = ("wake", "shutdown", "sleep", "restart")


@dataclass(frozen=True)
class PowerReadiness:
    config_path: Path
    config_exists: bool
    wake_configured: bool
    ssh_configured: bool
    smartthings_cli_path: str
    smartthings_cli_exists: bool
    ssh_host: str
    ssh_port: int
    ssh_user: str
    ssh_key_path: str
    ssh_key_exists: bool
    supported_actions: tuple[str, ...]

    @property
    def ready(self) -> bool:
        wake_ready = self.wake_configured and self.smartthings_cli_exists
        ssh_ready = self.ssh_configured and self.ssh_key_exists
        return wake_ready or ssh_ready


def _resolve_cli(path: str) -> str:
    if not path:
        return ""
    expanded = os.path.expanduser(path)
    if Path(expanded).exists():
        return expanded
    found = shutil.which(path)
    return found or expanded


def check_power_readiness(config_path: Path = DEFAULT_CONFIG) -> PowerReadiness:
    config = RemotePowerConfig.load(config_path)
    cli_path = _resolve_cli(config.smartthings_cli_path)
    key_path = os.path.expanduser(config.ssh_key_path) if config.ssh_key_path else ""
    actions: list[str] = []
    if config.wake_configured:
        actions.append("wake")
    if config.ssh_configured:
        actions.extend(["shutdown", "sleep", "restart"])
    return PowerReadiness(
        config_path=config_path,
        config_exists=config_path.exists(),
        wake_configured=config.wake_configured,
        ssh_configured=config.ssh_configured,
        smartthings_cli_path=cli_path,
        smartthings_cli_exists=bool(cli_path and Path(cli_path).exists()),
        ssh_host=config.ssh_host,
        ssh_port=config.ssh_port,
        ssh_user=config.ssh_user,
        ssh_key_path=key_path,
        ssh_key_exists=bool(key_path and Path(key_path).exists()),
        supported_actions=tuple(actions),
    )


def _print_report(result: PowerReadiness) -> None:
    print("Remote power readiness")
    print(f"- config_path: {result.config_path} ({'present' if result.config_exists else 'missing'})")
    print(f"- wake_configured: {result.wake_configured}")
    print(f"- smartthings_cli_path: {result.smartthings_cli_path or '(not set)'} ({'present' if result.smartthings_cli_exists else 'missing'})")
    print(f"- ssh_configured: {result.ssh_configured}")
    print(f"- ssh_host: {result.ssh_host or '(not set)'}")
    print(f"- ssh_port: {result.ssh_port}")
    print(f"- ssh_user: {result.ssh_user or '(not set)'}")
    print(f"- ssh_key_path: {result.ssh_key_path or '(not set)'} ({'present' if result.ssh_key_exists else 'missing'})")
    print(f"- supported_actions: {', '.join(result.supported_actions) if result.supported_actions else '(none)'}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Remote Controller power-adapter readiness without sending power commands.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--allow-blocker", action="store_true", help="Exit 0 when power config/tools are missing after printing the report.")
    args = parser.parse_args(argv)

    try:
        result = check_power_readiness(args.config)
        _print_report(result)
        if result.ready:
            print("Remote power readiness passed.")
            return 0
        print("Remote power readiness blocked: configure SmartThings CLI and/or SSH key settings before enabling power actions.")
        print("Template: remote_power_config.example.json")
        return 0 if args.allow_blocker else 2
    except Exception as exc:
        print(f"Remote power readiness failed unexpectedly: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
