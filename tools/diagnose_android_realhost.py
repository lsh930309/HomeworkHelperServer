#!/usr/bin/env python3
"""Collect a safe real-host Android HomeworkHelper diagnostic bundle.

The tool is intentionally read-only by default.  It preserves the current
pairing state and never clears app data, revokes devices, wakes/sleeps/reboots a
host, or prints bearer/private secrets.  Output is written under ignored
``artifacts/android-realhost-diagnostics/<timestamp>/`` for follow-up debugging.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_PACKAGE = "dev.homeworkhelper.remote"
PROG_NAME = "diagnose_android_realhost.py"
DEFAULT_ARTIFACT_ROOT = Path("artifacts/android-realhost-diagnostics")
SENSITIVE_KEY_PATTERN = re.compile(
    r"(token|bearer|private|secret|password|credential|encrypted|public[_\.-]?key|private[_\.-]?key|(^|[._-])pat($|[._-]))",
    re.IGNORECASE,
)


@dataclass
class CommandResult:
    args: list[str]
    returncode: int
    stdout: bytes
    stderr: bytes

    @property
    def text(self) -> str:
        return redact(self.stdout.decode("utf-8", errors="replace"))

    @property
    def error_text(self) -> str:
        return redact(self.stderr.decode("utf-8", errors="replace"))


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: ("<redacted>" if SENSITIVE_KEY_PATTERN.search(str(key)) else redact(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item) for item in value]
    if not isinstance(value, str):
        return value
    sanitized = value
    sanitized = re.sub(
        r'(<[^>]+name="[^"]*(?:token|bearer|private|secret|pat|password|credential|encrypted|key)[^"]*"[^>]*>)(.*?)(</[^>]+>)',
        r"\1<redacted>\3",
        sanitized,
        flags=re.IGNORECASE | re.DOTALL,
    )
    sanitized = re.sub(
        r'((?:token|bearer|private|secret|pat|password|credential|encrypted|key)[^=:\n]{0,32}[=:]\s*)([^\s,;]+)',
        r"\1<redacted>",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(r"Bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer <redacted>", sanitized, flags=re.IGNORECASE)
    return sanitized


def run(args: list[str], *, timeout: int = 20, check: bool = False, binary: bool = False) -> CommandResult:
    completed = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    result = CommandResult(args=args, returncode=completed.returncode, stdout=completed.stdout, stderr=completed.stderr)
    if check and result.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(args)}\n{result.error_text}")
    if not binary:
        # Force decoding through the redaction path in early development; the caller
        # still receives bytes, but any exception context avoids leaking secrets.
        _ = result.text
    return result


def adb_prefix(adb: str, serial: str | None) -> list[str]:
    prefix = [adb]
    if serial:
        prefix += ["-s", serial]
    return prefix


def adb_shell(adb: str, serial: str | None, *command: str, timeout: int = 20) -> CommandResult:
    return run(adb_prefix(adb, serial) + ["shell", *command], timeout=timeout)


def write_text(path: Path, value: str) -> None:
    path.write_text(redact(value), encoding="utf-8")


def parse_shared_pref_xml(xml_text: str) -> dict[str, Any]:
    values: dict[str, Any] = {}
    if not xml_text.strip():
        return values
    root = ET.fromstring(xml_text)
    for child in root:
        key = child.attrib.get("name", "")
        if not key:
            continue
        if child.tag == "boolean":
            value: Any = child.attrib.get("value", "false").lower() == "true"
        elif child.tag in {"int", "long", "float"}:
            raw = child.attrib.get("value", "0")
            value = int(raw) if child.tag in {"int", "long"} else float(raw)
        else:
            value = child.text or child.attrib.get("value", "")
        values[key] = "<redacted>" if SENSITIVE_KEY_PATTERN.search(key) else value
    return values


def read_shared_prefs(adb: str, serial: str | None, package: str, artifact_dir: Path) -> dict[str, Any]:
    shared_prefs_dir = f"/data/data/{package}/shared_prefs"
    listing = adb_shell(adb, serial, "run-as", package, "ls", shared_prefs_dir).text
    summary: dict[str, Any] = {}
    raw_dir = artifact_dir / "shared_prefs_redacted"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for name in [line.strip() for line in listing.splitlines() if line.strip().endswith(".xml")]:
        entry = f"{shared_prefs_dir}/{name}"
        result = adb_shell(adb, serial, "run-as", package, "cat", entry, timeout=10)
        xml_text = result.stdout.decode("utf-8", errors="replace")
        write_text(raw_dir / name, xml_text)
        try:
            summary[name] = parse_shared_pref_xml(xml_text)
        except ET.ParseError as exc:
            summary[name] = {"parse_error": str(exc)}
    return summary


def package_metadata(adb: str, serial: str | None, package: str) -> dict[str, Any]:
    dumpsys = adb_shell(adb, serial, "dumpsys", "package", package, timeout=20).text
    metadata: dict[str, Any] = {}
    for marker in ["versionName=", "versionCode=", "firstInstallTime=", "lastUpdateTime=", "targetSdk="]:
        match = re.search(rf"{re.escape(marker)}([^\s]+)", dumpsys)
        if match:
            metadata[marker.rstrip("=")] = match.group(1)
    metadata["raw_excerpt"] = "\n".join(
        line.strip()
        for line in dumpsys.splitlines()
        if any(token in line for token in ["versionName=", "versionCode=", "firstInstallTime=", "lastUpdateTime=", "targetSdk="])
    )
    return metadata


def collect_screenshot(adb: str, serial: str | None, artifact_dir: Path) -> dict[str, Any]:
    output = artifact_dir / "current_screen.png"
    result = run(adb_prefix(adb, serial) + ["exec-out", "screencap", "-p"], timeout=20, binary=True)
    if result.returncode == 0 and result.stdout:
        output.write_bytes(result.stdout)
        return {"path": str(output), "bytes": output.stat().st_size}
    return {"error": result.error_text or "screencap failed"}


def collect_ui_xml(adb: str, serial: str | None, artifact_dir: Path) -> dict[str, Any]:
    dump = adb_shell(adb, serial, "uiautomator", "dump", "/sdcard/homeworkhelper-window.xml", timeout=20)
    output = artifact_dir / "current_window.xml"
    result = run(adb_prefix(adb, serial) + ["exec-out", "cat", "/sdcard/homeworkhelper-window.xml"], timeout=10)
    adb_shell(adb, serial, "rm", "-f", "/sdcard/homeworkhelper-window.xml", timeout=10)
    if result.returncode == 0 and result.stdout:
        write_text(output, result.text)
        return {"path": str(output), "dump": dump.text.strip()}
    return {"error": result.error_text or dump.error_text or "uiautomator dump failed"}


def collect_logcat(adb: str, serial: str | None, package: str, artifact_dir: Path) -> dict[str, Any]:
    pid = adb_shell(adb, serial, "pidof", package, timeout=10).text.strip().split()
    output = artifact_dir / "logcat_redacted.txt"
    if pid:
        args = adb_prefix(adb, serial) + ["logcat", "-d", "--pid", pid[0], "-v", "time"]
    else:
        args = adb_prefix(adb, serial) + ["logcat", "-d", "-v", "time"]
    result = run(args, timeout=30)
    lines = result.text.splitlines()
    if not pid:
        lines = [line for line in lines if package in line or "HomeworkHelper" in line or "Coil" in line]
    write_text(output, "\n".join(lines[-500:]))
    return {"path": str(output), "pid": pid[0] if pid else None, "lines": min(len(lines), 500)}


def normalize_remote_url(base_url: str, value: str | None) -> str | None:
    raw = (value or "").strip().replace("&amp;", "&")
    if not raw:
        return None
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    return urllib.parse.urljoin(base_url.rstrip("/") + "/", raw.lstrip("/"))


def cached_processes_from_prefs(prefs: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    for pref_values in prefs.values():
        if not isinstance(pref_values, dict):
            continue
        base_url = str(pref_values.get("remote.base_url") or "")
        raw_processes = pref_values.get("remote.cached_processes_json")
        if isinstance(raw_processes, str) and raw_processes.strip().startswith("["):
            try:
                return base_url, json.loads(raw_processes)
            except json.JSONDecodeError:
                return base_url, []
    return "", []


def iter_asset_urls(base_url: str, processes: list[dict[str, Any]]) -> list[dict[str, str]]:
    assets: list[dict[str, str]] = []
    for process in processes:
        process_id = str(process.get("id") or process.get("name") or "unknown")
        candidates: list[tuple[str, str | None]] = [
            ("icon_url", process.get("icon_url")),
        ]
        candidates.extend((f"icon_urls.{key}", value) for key, value in (process.get("icon_urls") or {}).items())
        progress = process.get("progress") or {}
        candidates.append(("progress.resource_icon_url", progress.get("resource_icon_url")))
        candidates.extend((f"progress.resource_icon_urls.{key}", value) for key, value in (progress.get("resource_icon_urls") or {}).items())
        for field, raw in candidates:
            url = normalize_remote_url(base_url, str(raw) if raw is not None else None)
            if url:
                assets.append({"process": process_id, "field": field, "url": url})
    unique: dict[str, dict[str, str]] = {}
    for item in assets:
        unique.setdefault(item["url"], item)
    return list(unique.values())


def probe_assets(base_url: str, processes: list[dict[str, Any]], artifact_dir: Path) -> dict[str, Any]:
    probes = []
    for asset in iter_asset_urls(base_url, processes):
        started = time.time()
        request = urllib.request.Request(asset["url"], headers={"User-Agent": "HomeworkHelperAndroidRealHostDiagnostic/1.0"})
        result: dict[str, Any] = dict(asset)
        try:
            with urllib.request.urlopen(request, timeout=4) as response:
                response.read(128)
                result.update(
                    {
                        "ok": 200 <= response.status < 300,
                        "status": response.status,
                        "content_type": response.headers.get("Content-Type", ""),
                        "elapsed_ms": int((time.time() - started) * 1000),
                    }
                )
        except urllib.error.HTTPError as exc:
            result.update({"ok": False, "status": exc.code, "error": str(exc), "elapsed_ms": int((time.time() - started) * 1000)})
        except Exception as exc:  # noqa: BLE001 - report diagnostics without failing the bundle
            result.update({"ok": False, "status": None, "error": str(exc), "elapsed_ms": int((time.time() - started) * 1000)})
        probes.append(result)
    output = artifact_dir / "asset_probe.json"
    output.write_text(json.dumps(probes, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "path": str(output),
        "count": len(probes),
        "ok": sum(1 for item in probes if item.get("ok")),
        "failed": [item for item in probes if not item.get("ok")],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default="adb", help="adb executable path")
    parser.add_argument("--serial", help="specific adb serial")
    parser.add_argument("--package", default=DEFAULT_PACKAGE)
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    args = parser.parse_args(argv)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    artifact_dir = args.artifact_root / timestamp
    artifact_dir.mkdir(parents=True, exist_ok=True)

    devices = run([args.adb, "devices", "-l"], timeout=10).text
    write_text(artifact_dir / "adb_devices.txt", devices)

    summary: dict[str, Any] = {
        "generated_at": timestamp,
        "package": args.package,
        "serial": args.serial,
        "safety": {
            "read_only": True,
            "host_power_commands": False,
            "app_data_clear": False,
            "device_revoke": False,
            "host_https_delegated_power_mutation": False,
        },
        "package_metadata": package_metadata(args.adb, args.serial, args.package),
    }

    prefs = read_shared_prefs(args.adb, args.serial, args.package, artifact_dir)
    summary["shared_preferences"] = redact(prefs)
    base_url, processes = cached_processes_from_prefs(prefs)
    summary["cached_processes"] = {
        "base_url": base_url,
        "count": len(processes),
        "names": [str(item.get("name") or item.get("id") or "unknown") for item in processes],
    }
    if base_url and processes:
        summary["asset_probe"] = probe_assets(base_url, processes, artifact_dir)
    else:
        summary["asset_probe"] = {"skipped": "base_url or cached_processes missing"}

    summary["screen"] = collect_screenshot(args.adb, args.serial, artifact_dir)
    summary["ui_xml"] = collect_ui_xml(args.adb, args.serial, artifact_dir)
    summary["logcat"] = collect_logcat(args.adb, args.serial, args.package, artifact_dir)

    summary_path = artifact_dir / "summary.json"
    summary_path.write_text(json.dumps(redact(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Android real-host diagnostic bundle written: {summary_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
