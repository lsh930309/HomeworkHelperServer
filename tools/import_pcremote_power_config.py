#!/usr/bin/env python3
"""Import the old standalone pc_remote power constants into HomeworkHelper.

The old PCRemote Swift menu-bar utility stored user-specific power settings as
`private enum Config { static let ... }` constants.  HomeworkHelper uses the
same SmartThings WoL + SSH data but stores it in the fixed
remote_power_config.json schema consumed by src.core.remote_power.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
DEFAULT_SOURCE = PROJECT_ROOT.parent / "pc_remote" / "Sources" / "PCRemote" / "PCRemoteApp.swift"


@dataclass(frozen=True)
class ImportedPowerConfig:
    smartthings_device_id: str = ""
    smartthings_cli_path: str = ""
    ssh_host: str = ""
    ssh_port: int = 22
    ssh_user: str = ""
    ssh_key_path: str = ""
    status_timeout_seconds: float = 4.0


_STRING_FIELDS = {
    "wolDeviceId": "smartthings_device_id",
    "wolCliPath": "smartthings_cli_path",
    "pcHost": "ssh_host",
    "sshUser": "ssh_user",
    "sshKeyPath": "ssh_key_path",
}


def parse_pc_remote_swift(source: str) -> ImportedPowerConfig:
    values: dict[str, object] = {}
    for swift_name, target_name in _STRING_FIELDS.items():
        match = re.search(rf"static\s+let\s+{re.escape(swift_name)}\s*=\s*\"([^\"]*)\"", source)
        if match:
            values[target_name] = match.group(1)
    port_match = re.search(r"static\s+let\s+sshPort(?:\s*:\s*UInt16)?\s*=\s*(\d+)", source)
    if port_match:
        values["ssh_port"] = int(port_match.group(1))
    return ImportedPowerConfig(**values)


def default_output_path() -> Path:
    from src.data.database import data_dir

    return Path(data_dir) / "remote_power_config.json"


def write_config(config: ImportedPowerConfig, output: Path, *, backup: bool = True) -> Path | None:
    output.parent.mkdir(parents=True, exist_ok=True)
    backup_path = None
    if backup and output.exists():
        backup_path = output.with_suffix(output.suffix + ".bak")
        shutil.copy2(output, backup_path)
    output.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return backup_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import pc_remote power constants into HomeworkHelper remote_power_config.json.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help=f"Default: {DEFAULT_SOURCE}")
    parser.add_argument("--output", type=Path, default=None, help="Default: HomeworkHelper data_dir/remote_power_config.json")
    parser.add_argument("--no-backup", action="store_true", help="Do not create .bak when output exists.")
    parser.add_argument("--print-only", action="store_true", help="Parse and print JSON without writing.")
    args = parser.parse_args(argv)

    if not args.source.exists():
        print(f"pc_remote source not found: {args.source}", file=sys.stderr)
        return 1
    config = parse_pc_remote_swift(args.source.read_text(encoding="utf-8"))
    payload = json.dumps(asdict(config), ensure_ascii=False, indent=2)
    if args.print_only:
        print(payload)
        return 0
    output = args.output or default_output_path()
    backup_path = write_config(config, output, backup=not args.no_backup)
    print(f"Imported pc_remote power config: {output}")
    if backup_path:
        print(f"Previous config backup: {backup_path}")
    print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
