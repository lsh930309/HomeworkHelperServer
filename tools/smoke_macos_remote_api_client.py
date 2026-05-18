#!/usr/bin/env python3
"""Smoke test the macOS RemoteAPIClient against a real Remote Agent.

The script starts ``homework_helper.pyw``'s server process on a temporary
loopback port, obtains a pairing code via HTTP, then compiles and runs a small
Swift program together with the production ``RemoteAPIClient.swift`` and
``RemoteModels.swift`` files.  This verifies the macOS-native client DTO,
endpoint, pairing-confirm, bearer-token, and device-list paths without launching
the full SwiftUI window.
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
import textwrap
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MACOS_SOURCE_DIR = PROJECT_ROOT / "remote_clients" / "macos" / "HomeworkHelperRemote" / "Sources" / "HomeworkHelperRemote"
REMOTE_API_CLIENT = MACOS_SOURCE_DIR / "RemoteAPIClient.swift"
REMOTE_MODELS = MACOS_SOURCE_DIR / "RemoteModels.swift"
LOCAL_POWER_WAKE_MANAGER = MACOS_SOURCE_DIR / "LocalPowerWakeManager.swift"


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


def _swift_smoke_source(base_url: str, pairing_code: str, process_id: str) -> str:
    return textwrap.dedent(
        f"""
        import Foundation

        @main
        struct MacOSRemoteAPIClientSmoke {{
            static func main() async {{
                do {{
                    guard let baseURL = URL(string: "{base_url}") else {{
                        throw RemoteAPIError.invalidURL
                    }}
                    let pairingClient = RemoteAPIClient(baseURL: baseURL, bearerToken: nil)
                    let pair = try await pairingClient.confirmPairing(code: "{pairing_code}", deviceName: "macos-api-client-smoke")
                    if pair.token.isEmpty {{
                        fatalError("pairing response did not include token")
                    }}
                    let authedClient = RemoteAPIClient(baseURL: baseURL, bearerToken: pair.token)
                    let status = try await authedClient.status()
                    if status.app != "HomeworkHelper" {{
                        fatalError("unexpected app: \\(status.app)")
                    }}
                    if status.capabilities.authRequired != true {{
                        fatalError("authRequired should be true after pairing")
                    }}
                    let capabilities = try await authedClient.capabilities()
                    if capabilities.remoteAPIVersion != status.remoteAPIVersion {{
                        fatalError("capabilities endpoint version drifted from status")
                    }}
                    if capabilities.capabilities.processLaunch != status.capabilities.processLaunch {{
                        fatalError("capabilities endpoint drifted from status processLaunch")
                    }}
                    let refreshed = try await authedClient.refreshToken()
                    if refreshed.token == pair.token {{
                        fatalError("token refresh did not rotate the bearer token")
                    }}
                    let refreshedClient = RemoteAPIClient(baseURL: baseURL, bearerToken: refreshed.token)
                    let createdGameLink = try await refreshedClient.createGameLink(processID: "{process_id}", androidPackageName: "dev.homeworkhelper.remote.smoke")
                    if createdGameLink.pcProcessID != "{process_id}" || createdGameLink.androidPackageName != "dev.homeworkhelper.remote.smoke" {{
                        fatalError("game-link create response did not preserve the mapping")
                    }}
                    let summary = try await refreshedClient.dashboardSummary()
                    if summary.metrics.sessionCount < 0 {{
                        fatalError("dashboard summary decoded an invalid session count")
                    }}
                    let incidents = try await refreshedClient.beholderIncidents()
                    let startedMobileSession = try await refreshedClient.startMobileSession(gameLinkID: createdGameLink.id)
                    if startedMobileSession.gameLinkID != createdGameLink.id || startedMobileSession.status != "active" {{
                        fatalError("mobile session start did not return an active linked session")
                    }}
                    let activeMobileSessions = try await refreshedClient.activeMobileSessions()
                    if !activeMobileSessions.contains(where: {{ $0.id == startedMobileSession.id }}) {{
                        fatalError("started mobile session missing from active list")
                    }}
                    let endedMobileSession = try await refreshedClient.endMobileSession(sessionID: startedMobileSession.id)
                    if endedMobileSession.status != "ended" || endedMobileSession.durationSeconds == nil {{
                        fatalError("mobile session end did not close the session")
                    }}
                    let mobileSummary = try await refreshedClient.dashboardSummary()
                    if mobileSummary.mobileMetrics?.sessionCount ?? 0 < 1 {{
                        fatalError("dashboard summary did not include the ended mobile session metrics")
                    }}
                    let gameLinks = try await refreshedClient.gameLinks()
                    if !gameLinks.contains(where: {{ $0.id == createdGameLink.id }}) {{
                        fatalError("created game-link missing from list response")
                    }}
                    let devices = try await refreshedClient.devices()
                    if !devices.contains(where: {{ $0.id == pair.id }}) {{
                        fatalError("paired device missing from device list")
                    }}
                    print("macOS RemoteAPIClient smoke passed: \\(status.remoteAPIVersion), devices=\\(devices.count), capabilities=ok, dashboard_sessions=\\(summary.metrics.sessionCount), beholder_incidents=\\(incidents.count), game_links=\\(gameLinks.count), mobile_session=\\(endedMobileSession.status), mobile_summary_sessions=\\(mobileSummary.mobileMetrics?.sessionCount ?? 0)")
                }} catch {{
                    fputs("macOS RemoteAPIClient smoke failed: \\(error)\\n", stderr)
                    Foundation.exit(1)
                }}
            }}
        }}
        """
    )


def _compile_and_run_swift_smoke(base_url: str, pairing_code: str, process_id: str, work_dir: Path) -> None:
    smoke_source = work_dir / "MacOSRemoteAPIClientSmoke.swift"
    binary = work_dir / "macos-remote-api-client-smoke"
    smoke_source.write_text(_swift_smoke_source(base_url, pairing_code, process_id), encoding="utf-8")
    compile_cmd = [
        "swiftc",
        "-parse-as-library",
        str(REMOTE_MODELS),
        str(LOCAL_POWER_WAKE_MANAGER),
        str(REMOTE_API_CLIENT),
        str(smoke_source),
        "-o",
        str(binary),
    ]
    compile_result = subprocess.run(compile_cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    if compile_result.returncode != 0:
        raise RuntimeError(f"swiftc failed ({compile_result.returncode}):\n{compile_result.stdout}")
    run_result = subprocess.run([str(binary)], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    if run_result.returncode != 0:
        raise RuntimeError(f"Swift smoke failed ({run_result.returncode}):\n{run_result.stdout}")
    print(run_result.stdout.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke test macOS RemoteAPIClient against the real Remote Agent.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args(argv)

    port = args.port or _free_loopback_port()
    base_url = f"http://{args.host}:{port}"

    with tempfile.TemporaryDirectory(prefix="hh-macos-api-client-smoke-") as temp_root:
        temp_dir = Path(temp_root)
        home = temp_dir / "home"
        home.mkdir()
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(home),
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
            _wait_for_status(base_url, timeout_seconds=args.timeout)
            seed_status, seed_body = _json_request(
                "POST",
                f"{base_url}/processes",
                body={
                    "id": "smoke-game",
                    "name": "Smoke Game",
                    "monitoring_path": "/Applications/Smoke.app",
                    "launch_path": "/Applications/Smoke.app",
                    "preferred_launch_type": "direct",
                },
            )
            if seed_status != 201:
                raise RuntimeError(f"process seed failed: {seed_status} {seed_body}")
            pair_status, pair_body = _json_request("POST", f"{base_url}/remote/pair/start")
            if pair_status != 200:
                raise RuntimeError(f"pair/start failed: {pair_status} {pair_body}")
            code = str(pair_body.get("code") or "")
            if len(code) != 6 or not code.isdigit():
                raise RuntimeError(f"unexpected pairing code payload: {pair_body}")
            _compile_and_run_swift_smoke(base_url, code, "smoke-game", temp_dir)
            return 0
        except Exception as exc:
            print(f"macOS RemoteAPIClient smoke failed: {exc}", file=sys.stderr)
            with contextlib.suppress(Exception):
                process.terminate()
                try:
                    output, _ = process.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    output, _ = process.communicate(timeout=5)
                if output:
                    print("\n--- server output ---", file=sys.stderr)
                    print(output, file=sys.stderr)
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
