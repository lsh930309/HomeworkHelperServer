#!/usr/bin/env python3
"""Smoke test the Remote Controller API through the real server process.

This intentionally starts ``homework_helper.run_server_main()`` in a subprocess
instead of mounting the router in FastAPI's TestClient.  It verifies the path
used by native macOS/Android clients: HTTP status, loopback pairing, token
requirement after first device registration, and authenticated device listing.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


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


def _wait_for_status(base_url: str, *, timeout_seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            status, body = _json_request("GET", f"{base_url}/remote/status")
            if status == 200:
                return body
            last_error = RuntimeError(f"unexpected status {status}: {body}")
        except (URLError, TimeoutError, ConnectionError) as exc:
            last_error = exc
        time.sleep(0.2)
    raise RuntimeError(f"server did not become ready within {timeout_seconds}s: {last_error}")


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _run_smoke(base_url: str, *, timeout_seconds: float) -> None:
    status_body = _wait_for_status(base_url, timeout_seconds=timeout_seconds)
    _assert(status_body.get("app") == "HomeworkHelper", "remote status app mismatch")
    _assert(status_body.get("capabilities", {}).get("pairing") is True, "pairing capability missing")
    _assert(status_body.get("capabilities", {}).get("auth_required") is False, "fresh loopback server should not require auth before pairing")

    pair_status, pair_body = _json_request("POST", f"{base_url}/remote/pair/start")
    _assert(pair_status == 200, f"pair/start failed: {pair_status} {pair_body}")
    code = str(pair_body.get("code") or "")
    _assert(len(code) == 6 and code.isdigit(), f"pairing code should be 6 digits: {pair_body}")

    confirm_status, confirm_body = _json_request(
        "POST",
        f"{base_url}/remote/pair/confirm",
        body={"code": code, "device_name": "runtime-smoke", "platform": "macos"},
    )
    _assert(confirm_status == 200, f"pair/confirm failed: {confirm_status} {confirm_body}")
    token = str(confirm_body.get("token") or "")
    device_id = str(confirm_body.get("id") or "")
    _assert(token, f"pair/confirm did not return token: {confirm_body}")
    _assert(device_id, f"pair/confirm did not return device id: {confirm_body}")

    rejected_status, _rejected_body = _json_request("GET", f"{base_url}/remote/status")
    _assert(rejected_status == 401, f"remote/status should require token after pairing, got {rejected_status}")

    authed_status, authed_body = _json_request("GET", f"{base_url}/remote/status", token=token)
    _assert(authed_status == 200, f"authenticated remote/status failed: {authed_status} {authed_body}")
    _assert(authed_body.get("capabilities", {}).get("auth_required") is True, "auth_required should be true after pairing")

    devices_status, devices_body = _json_request("GET", f"{base_url}/remote/devices", token=token)
    _assert(devices_status == 200, f"remote/devices failed: {devices_status} {devices_body}")
    devices = devices_body.get("devices") or []
    _assert(any(device.get("id") == device_id for device in devices), f"paired device missing from list: {devices_body}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke test HomeworkHelper Remote Controller via real HTTP server process.")
    parser.add_argument("--host", default="127.0.0.1", help="Loopback host to bind the server to.")
    parser.add_argument("--port", type=int, default=0, help="Port to bind; 0 picks a free loopback port before launch.")
    parser.add_argument("--timeout", type=float, default=15.0, help="Seconds to wait for server readiness.")
    args = parser.parse_args(argv)

    port = args.port or _free_loopback_port()
    base_url = f"http://{args.host}:{port}"

    with tempfile.TemporaryDirectory(prefix="hh-remote-runtime-smoke-") as home:
        env = os.environ.copy()
        env.update(
            {
                "HOME": home,
                "HH_API_HOST": args.host,
                "HH_API_PORT": str(port),
                "HH_REMOTE_REQUIRE_AUTH": "0",
                "PYTHONPATH": str(PROJECT_ROOT),
            }
        )
        process = subprocess.Popen(
            [sys.executable, "-c", "import runpy; ns = runpy.run_path('homework_helper.pyw'); ns['run_server_main']()"],
            cwd=PROJECT_ROOT,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        try:
            _run_smoke(base_url, timeout_seconds=args.timeout)
            print(f"Remote Controller runtime smoke passed: {base_url}")
            return 0
        except Exception as exc:
            print(f"Remote Controller runtime smoke failed: {exc}", file=sys.stderr)
            with contextlib.suppress(Exception):
                if process.stdout:
                    print("\n--- server output ---", file=sys.stderr)
                    print(process.stdout.read(), file=sys.stderr)
            return 1
        finally:
            process.terminate()
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=5)
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
