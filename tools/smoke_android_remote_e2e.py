#!/usr/bin/env python3
"""End-to-end smoke the Android Remote app on a connected device/emulator.

The smoke starts a real loopback Remote Agent on host port 8000, installs and
clears the debug APK, drives the Compose UI through adb/uiautomator, completes
pairing, verifies encrypted token persistence across app restart, and exercises
game-link/mobile-session/UsageStats UI paths that are only meaningful on an
Android runtime.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ANDROID_ROOT = PROJECT_ROOT / "remote_clients" / "android" / "HomeworkHelperRemote"
DEFAULT_APK = ANDROID_ROOT / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
DEFAULT_PACKAGE = "dev.homeworkhelper.remote"
DEFAULT_ACTIVITY = "dev.homeworkhelper.remote/.MainActivity"
DEFAULT_ADB = Path("/opt/homebrew/share/android-commandlinetools/platform-tools/adb")


@dataclass(frozen=True)
class NodeHit:
    text: str
    bounds: tuple[int, int, int, int]

    @property
    def center(self) -> tuple[int, int]:
        left, top, right, bottom = self.bounds
        return ((left + right) // 2, (top + bottom) // 2)


def _run(command: list[str], *, timeout: float = 30.0, check: bool = False) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    if check and completed.returncode != 0:
        raise RuntimeError(f"{' '.join(command)} failed ({completed.returncode}):\n{completed.stdout}")
    return completed


def _adb(adb: str, device: str | None, *args: str, timeout: float = 30.0, check: bool = True) -> subprocess.CompletedProcess[str]:
    command = [adb]
    if device:
        command.extend(["-s", device])
    command.extend(args)
    return _run(command, timeout=timeout, check=check)


def _connected_device(adb: str, explicit: str | None) -> str:
    result = _run([adb, "devices"], check=True)
    devices: list[str] = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    if explicit:
        if explicit not in devices:
            raise RuntimeError(f"Requested adb device {explicit!r} is not connected. Connected: {devices}")
        return explicit
    if len(devices) != 1:
        raise RuntimeError(f"Expected exactly one connected adb device; connected={devices}. Use --device.")
    return devices[0]


def _json_request(method: str, url: str, *, body: dict[str, Any] | None = None, token: str | None = None) -> tuple[int, dict[str, Any]]:
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=2) as response:
            payload = response.read().decode("utf-8")
            return response.status, json.loads(payload) if payload else {}
    except HTTPError as exc:
        payload = exc.read().decode("utf-8")
        try:
            parsed = json.loads(payload) if payload else {}
        except json.JSONDecodeError:
            parsed = {"raw": payload}
        return exc.code, parsed


def _wait_for_status(base_url: str, *, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            status, body = _json_request("GET", f"{base_url}/remote/status")
            if status == 200 and body.get("app") == "HomeworkHelper":
                return
            last_error = RuntimeError(f"unexpected status {status}: {body}")
        except (URLError, TimeoutError, ConnectionError) as exc:
            last_error = exc
        time.sleep(0.2)
    raise RuntimeError(f"server did not become ready within {timeout_seconds}s: {last_error}")


def _parse_bounds(raw: str) -> tuple[int, int, int, int]:
    match = re.fullmatch(r"\[(\d+),(\d+)]\[(\d+),(\d+)]", raw)
    if not match:
        raise ValueError(f"invalid bounds: {raw}")
    return tuple(int(group) for group in match.groups())  # type: ignore[return-value]


def _dump_ui(adb: str, device: str | None) -> tuple[str, ET.Element]:
    _adb(adb, device, "shell", "uiautomator", "dump", "/sdcard/window.xml", timeout=10)
    xml = _adb(adb, device, "exec-out", "cat", "/sdcard/window.xml", timeout=10).stdout
    return xml, ET.fromstring(xml)


def _find_text(root: ET.Element, text: str) -> NodeHit | None:
    for node in root.iter("node"):
        node_text = node.attrib.get("text", "")
        if node_text == text:
            return NodeHit(node_text, _parse_bounds(node.attrib.get("bounds", "")))
    return None


def _find_tappable_text(root: ET.Element, text: str) -> NodeHit | None:
    path: list[ET.Element] = []

    def visit(node: ET.Element) -> NodeHit | None:
        path.append(node)
        if node.attrib.get("text") == text:
            for ancestor in reversed(path):
                if ancestor.attrib.get("clickable") == "true" and ancestor.attrib.get("enabled") == "true":
                    return NodeHit(text, _parse_bounds(ancestor.attrib.get("bounds", "")))
            return NodeHit(text, _parse_bounds(node.attrib.get("bounds", "")))
        for child in node:
            found = visit(child)
            if found:
                return found
        path.pop()
        return None

    return visit(root)


def _find_text_containing(root: ET.Element, text: str) -> NodeHit | None:
    for node in root.iter("node"):
        node_text = node.attrib.get("text", "")
        if text in node_text:
            return NodeHit(node_text, _parse_bounds(node.attrib.get("bounds", "")))
    return None


def _find_ancestor_edit_text(root: ET.Element, label: str) -> NodeHit | None:
    path: list[ET.Element] = []

    def visit(node: ET.Element) -> NodeHit | None:
        path.append(node)
        if node.attrib.get("text") == label:
            for ancestor in reversed(path[:-1]):
                if ancestor.attrib.get("class") == "android.widget.EditText":
                    return NodeHit(label, _parse_bounds(ancestor.attrib.get("bounds", "")))
        for child in node:
            found = visit(child)
            if found:
                return found
        path.pop()
        return None

    return visit(root)


def _tap(adb: str, device: str | None, hit: NodeHit) -> None:
    x, y = hit.center
    _adb(adb, device, "shell", "input", "tap", str(x), str(y))


def _tap_text(adb: str, device: str | None, text: str, *, timeout: float = 20.0, scroll: bool = True) -> NodeHit:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _, root = _dump_ui(adb, device)
        hit = _find_tappable_text(root, text)
        if hit:
            _tap(adb, device, hit)
            return hit
        if scroll:
            _adb(adb, device, "shell", "input", "swipe", "540", "2050", "540", "650", "350")
        time.sleep(0.5)
    raise RuntimeError(f"Could not find text {text!r} in Android UI")


def _tap_edit_by_label(adb: str, device: str | None, label: str, *, timeout: float = 20.0) -> NodeHit:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _, root = _dump_ui(adb, device)
        hit = _find_ancestor_edit_text(root, label)
        if hit:
            _tap(adb, device, hit)
            return hit
        _adb(adb, device, "shell", "input", "swipe", "540", "2050", "540", "650", "350")
        time.sleep(0.5)
    raise RuntimeError(f"Could not find text field labelled {label!r}")


def _wait_text_contains(adb: str, device: str | None, text: str, *, timeout: float = 20.0, scroll: bool = False) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        xml, root = _dump_ui(adb, device)
        hit = _find_text_containing(root, text)
        if hit:
            return hit.text
        if scroll:
            _adb(adb, device, "shell", "input", "swipe", "540", "2050", "540", "650", "350")
        time.sleep(0.5)
    raise RuntimeError(f"Timed out waiting for Android UI text containing {text!r}. Last XML:\n{xml[:4000]}")


def _scroll_to_top(adb: str, device: str | None) -> None:
    for _ in range(4):
        _adb(adb, device, "shell", "input", "swipe", "540", "650", "540", "2050", "250")


def _input_text(adb: str, device: str | None, value: str) -> None:
    escaped = value.replace(" ", "%s").replace("&", "\\&")
    _adb(adb, device, "shell", "input", "text", escaped)


def _replace_text(adb: str, device: str | None, value: str, *, max_delete: int = 120) -> None:
    _adb(adb, device, "shell", "input", "keyevent", "KEYCODE_MOVE_END")
    for _ in range(max_delete):
        _adb(adb, device, "shell", "input", "keyevent", "KEYCODE_DEL")
    _input_text(adb, device, value)


def _secure_prefs(adb: str, device: str | None, package_name: str) -> str:
    return _adb(
        adb,
        device,
        "shell",
        "run-as",
        package_name,
        "cat",
        "shared_prefs/homeworkhelper_remote_secure.xml",
        timeout=10,
    ).stdout


def _start_server(port: int, temp_dir: Path, host: str) -> subprocess.Popen[str]:
    home = temp_dir / "home"
    home.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "HH_API_HOST": host,
            "HH_API_PORT": str(port),
            "HH_REMOTE_REQUIRE_AUTH": "0",
            "PYTHONPATH": str(PROJECT_ROOT),
        }
    )
    return subprocess.Popen(
        [sys.executable, "-c", "import runpy; ns = runpy.run_path('homework_helper.pyw'); ns['run_server_main']()"],
        cwd=PROJECT_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Android Remote app e2e smoke against a real loopback Remote Agent.")
    parser.add_argument("--adb", default=str(DEFAULT_ADB), help="Path to adb.")
    parser.add_argument("--device", default=None, help="Explicit adb serial.")
    parser.add_argument("--apk", type=Path, default=DEFAULT_APK, help="Debug APK to install.")
    parser.add_argument("--package", default=DEFAULT_PACKAGE, help="Android package name.")
    parser.add_argument("--activity", default=DEFAULT_ACTIVITY, help="Activity component to launch.")
    parser.add_argument("--port", type=int, default=8000, help="Host Remote Agent port.")
    parser.add_argument("--host-bind", default="127.0.0.1", help="Host interface for the temporary Remote Agent.")
    parser.add_argument(
        "--android-base-url",
        default=None,
        help="Remote Agent URL typed into the Android app. Defaults to emulator-friendly http://10.0.2.2:<port>.",
    )
    parser.add_argument(
        "--adb-reverse",
        action="store_true",
        help="Run adb reverse tcp:<port> tcp:<port> and use Android URL http://127.0.0.1:<port>; useful for physical devices.",
    )
    args = parser.parse_args(argv)

    if not args.apk.exists():
        print(f"Android APK missing: {args.apk}", file=sys.stderr)
        return 2
    adb = args.adb
    device = _connected_device(adb, args.device)
    base_url = f"http://127.0.0.1:{args.port}"
    android_base_url = args.android_base_url or (
        f"http://127.0.0.1:{args.port}" if args.adb_reverse else f"http://10.0.2.2:{args.port}"
    )

    with tempfile.TemporaryDirectory(prefix="hh-android-e2e-") as temp_root:
        temp_dir = Path(temp_root)
        reverse_enabled = False
        server: subprocess.Popen[str] | None = None
        if args.adb_reverse:
            try:
                _adb(adb, device, "reverse", f"tcp:{args.port}", f"tcp:{args.port}", timeout=10)
                reverse_enabled = True
            except Exception as exc:
                print(f"Android Remote e2e smoke failed: adb reverse failed: {exc}", file=sys.stderr)
                return 1
        try:
            server = _start_server(args.port, temp_dir, args.host_bind)
            _wait_for_status(base_url, timeout_seconds=20)
            seed_status, seed_body = _json_request(
                "POST",
                f"{base_url}/processes",
                body={
                    "id": "android-e2e-game",
                    "name": "Android E2E Game",
                    "monitoring_path": "/Applications/AndroidE2E.app",
                    "launch_path": "/Applications/AndroidE2E.app",
                    "preferred_launch_type": "direct",
                },
            )
            if seed_status != 201:
                raise RuntimeError(f"process seed failed: {seed_status} {seed_body}")
            link_status, link_body = _json_request(
                "POST",
                f"{base_url}/remote/game-links",
                body={
                    "pc_process_id": "android-e2e-game",
                    "android_package_name": args.package,
                    "sync_strategy": "manual",
                },
            )
            if link_status != 200:
                raise RuntimeError(f"game-link seed failed: {link_status} {link_body}")

            pair_status, pair_body = _json_request("POST", f"{base_url}/remote/pair/start")
            if pair_status != 200:
                raise RuntimeError(f"pair/start failed: {pair_status} {pair_body}")
            pairing_code = str(pair_body.get("code") or "")
            if len(pairing_code) != 6 or not pairing_code.isdigit():
                raise RuntimeError(f"unexpected pairing code payload: {pair_body}")

            print(_adb(adb, device, "install", "-r", str(args.apk), timeout=60).stdout.rstrip())
            _adb(adb, device, "shell", "pm", "clear", args.package)
            _adb(adb, device, "shell", "appops", "set", args.package, "GET_USAGE_STATS", "allow")
            _adb(adb, device, "shell", "am", "start", "-n", args.activity)
            _wait_text_contains(adb, device, "HomeworkHelper Remote", timeout=20)
            _scroll_to_top(adb, device)

            _tap_edit_by_label(adb, device, "Remote Agent URL")
            _replace_text(adb, device, android_base_url)
            _adb(adb, device, "shell", "input", "keyevent", "BACK")

            _tap_edit_by_label(adb, device, "Pairing code")
            _input_text(adb, device, pairing_code)
            _adb(adb, device, "shell", "input", "keyevent", "BACK")
            _tap_text(adb, device, "페어링 완료")
            _wait_text_contains(adb, device, "동기화 완료", timeout=30)
            _wait_text_contains(adb, device, "Android-PC 연결", timeout=20, scroll=True)

            _tap_text(adb, device, "모바일 시작", timeout=20, scroll=True)
            _wait_text_contains(adb, device, "모바일 종료", timeout=30, scroll=True)
            _tap_text(adb, device, "모바일 종료", timeout=20, scroll=True)
            _wait_text_contains(adb, device, "모바일 시작", timeout=30, scroll=True)
            _tap_text(adb, device, "Usage 동기화", timeout=20, scroll=True)
            usage_message = _wait_text_contains(adb, device, "최근 전면 앱", timeout=30, scroll=True)

            secure_before_restart = _secure_prefs(adb, device, args.package)
            if "encrypted_bearer_token" not in secure_before_restart or "v1:" not in secure_before_restart:
                raise RuntimeError(f"encrypted token was not persisted in secure prefs:\n{secure_before_restart}")

            _adb(adb, device, "shell", "am", "force-stop", args.package)
            _adb(adb, device, "shell", "am", "start", "-n", args.activity)
            _wait_text_contains(adb, device, "HomeworkHelper Remote", timeout=20)
            _tap_text(adb, device, "새로고침", timeout=20, scroll=False)
            _wait_text_contains(adb, device, "동기화 완료", timeout=30)
            secure_after_restart = _secure_prefs(adb, device, args.package)
            if "encrypted_bearer_token" not in secure_after_restart:
                raise RuntimeError("encrypted token disappeared after restart")

            print(
                "Android Remote e2e smoke passed: "
                f"device={device}, pairing=ok, encrypted_token=ok, restart_refresh=ok, "
                f"mobile_session=ok, android_base_url={android_base_url!r}, usage_message={usage_message!r}"
            )
            return 0
        except Exception as exc:
            print(f"Android Remote e2e smoke failed: {exc}", file=sys.stderr)
            with contextlib.suppress(Exception):
                output, _ = server.communicate(timeout=3)
                if output:
                    print("\n--- server output ---", file=sys.stderr)
                    print(output, file=sys.stderr)
            return 1
        finally:
            if server is not None:
                server.terminate()
            if reverse_enabled:
                with contextlib.suppress(Exception):
                    _adb(adb, device, "reverse", "--remove", f"tcp:{args.port}", timeout=10, check=False)
            if server is not None:
                with contextlib.suppress(subprocess.TimeoutExpired):
                    server.wait(timeout=5)
                if server.poll() is None:
                    server.kill()
                server.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
