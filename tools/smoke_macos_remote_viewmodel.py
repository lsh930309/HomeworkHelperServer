#!/usr/bin/env python3
"""Smoke test macOS RemoteDashboardViewModel against a real Remote Agent.

This drives the same ViewModel methods used by SwiftUI buttons while avoiding
fragile GUI click automation. The harness injects an in-memory token store and
runs against a temporary loopback Remote Agent.
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
REMOTE_MODELS = MACOS_SOURCE_DIR / "RemoteModels.swift"
REMOTE_API_CLIENT = MACOS_SOURCE_DIR / "RemoteAPIClient.swift"
KEYCHAIN_TOKEN_STORE = MACOS_SOURCE_DIR / "KeychainTokenStore.swift"
REMOTE_VIEW_MODEL = MACOS_SOURCE_DIR / "RemoteDashboardViewModel.swift"


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


def _swift_smoke_source(base_url: str, pairing_code: str) -> str:
    source = r'''
        import Foundation
        import SwiftUI

        final class InMemoryTokenStore: RemoteTokenStore {
            var token = ""
            func load() -> String { token }
            func save(_ token: String) { self.token = token }
            func delete() { token = "" }
        }

        func smokeStep(_ name: String) {
            fputs("step: \(name)\n", stderr)
            fflush(stderr)
        }

        @main
        struct MacOSRemoteViewModelSmoke {
            @MainActor
            static func main() async {
                smokeStep("init")
                let store = InMemoryTokenStore()
                let viewModel = RemoteDashboardViewModel(tokenStore: store)
                viewModel.baseURLText = "__BASE_URL__"
                viewModel.deviceName = "macos-viewmodel-smoke"
                viewModel.pairingCode = "__PAIRING_CODE__"

                smokeStep("confirmPairing")
                await viewModel.confirmPairing()
                guard !viewModel.tokenText.isEmpty, store.token == viewModel.tokenText else {
                    fatalError("pairing did not save token through injected store: \(viewModel.message)")
                }
                guard viewModel.status?.app == "HomeworkHelper" else {
                    fatalError("pairing refresh did not populate status: \(viewModel.message)")
                }
                guard viewModel.processes.contains(where: { $0.id == "smoke-game" }) else {
                    fatalError("refresh did not populate seeded process list: \(viewModel.message)")
                }
                guard viewModel.powerConfigResponse != nil else {
                    fatalError("refresh did not populate power config: \(viewModel.message)")
                }
                guard !viewModel.isPowerActionEnabled("shutdown") else {
                    fatalError("shutdown should be disabled when power adapter is unconfigured")
                }
                smokeStep("power guard")
                await viewModel.power("shutdown")
                guard viewModel.message.contains("전원 제어 adapter") else {
                    fatalError("disabled power action did not report local guard: \(viewModel.message)")
                }

                smokeStep("createGameLink")
                viewModel.gameLinkProcessID = "smoke-game"
                viewModel.gameLinkAndroidPackage = "dev.homeworkhelper.remote.viewmodel"
                await viewModel.createGameLink()
                guard let link = viewModel.gameLinks.first(where: { $0.pcProcessID == "smoke-game" && $0.androidPackageName == "dev.homeworkhelper.remote.viewmodel" }) else {
                    fatalError("createGameLink did not refresh created link: \(viewModel.message)")
                }
                guard viewModel.gameLinkAndroidPackage.isEmpty else {
                    fatalError("createGameLink should clear Android package input")
                }

                smokeStep("mobile session")
                await viewModel.startMobileSession(link)
                guard let active = viewModel.activeMobileSession(for: link) else {
                    fatalError("startMobileSession did not add active session: \(viewModel.message)")
                }
                await viewModel.endMobileSession(active)
                guard viewModel.activeMobileSession(for: link) == nil else {
                    fatalError("endMobileSession did not clear active session")
                }

                smokeStep("refresh token")
                let oldToken = viewModel.tokenText
                await viewModel.refreshToken()
                guard !viewModel.tokenText.isEmpty, viewModel.tokenText != oldToken, store.token == viewModel.tokenText else {
                    fatalError("refreshToken did not rotate and persist token: \(viewModel.message)")
                }
                smokeStep("refresh devices")
                await viewModel.refreshDevices()
                guard !viewModel.devices.isEmpty else {
                    fatalError("refreshDevices did not populate devices: \(viewModel.message)")
                }

                print("macOS RemoteDashboardViewModel smoke passed: processes=\(viewModel.processes.count), game_links=\(viewModel.gameLinks.count), devices=\(viewModel.devices.count), message=\(viewModel.message)")
            }
        }
    '''
    return textwrap.dedent(source).replace("__BASE_URL__", base_url).replace("__PAIRING_CODE__", pairing_code)


def _compile_and_run_swift_smoke(base_url: str, pairing_code: str, work_dir: Path, env: dict[str, str]) -> None:
    smoke_source = work_dir / "MacOSRemoteViewModelSmoke.swift"
    binary = work_dir / "macos-remote-viewmodel-smoke"
    smoke_source.write_text(_swift_smoke_source(base_url, pairing_code), encoding="utf-8")
    compile_cmd = [
        "swiftc",
        "-parse-as-library",
        str(REMOTE_MODELS),
        str(REMOTE_API_CLIENT),
        str(KEYCHAIN_TOKEN_STORE),
        str(REMOTE_VIEW_MODEL),
        str(smoke_source),
        "-o",
        str(binary),
    ]
    compile_result = subprocess.run(compile_cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    if compile_result.returncode != 0:
        raise RuntimeError(f"swiftc failed ({compile_result.returncode}):\n{compile_result.stdout}")
    try:
        run_result = subprocess.run([str(binary)], env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False, timeout=30)
    except subprocess.TimeoutExpired as exc:
        output = exc.stdout or ""
        if isinstance(output, bytes):
            output = output.decode("utf-8", errors="replace")
        raise RuntimeError(f"Swift ViewModel smoke timed out after {exc.timeout}s:\n{output}") from exc
    if run_result.returncode != 0:
        raise RuntimeError(f"Swift ViewModel smoke failed ({run_result.returncode}):\n{run_result.stdout}")
    print(run_result.stdout.strip())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smoke test macOS RemoteDashboardViewModel against the real Remote Agent.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args(argv)

    port = args.port or _free_loopback_port()
    base_url = f"http://{args.host}:{port}"

    with tempfile.TemporaryDirectory(prefix="hh-macos-viewmodel-smoke-") as temp_root:
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
            _compile_and_run_swift_smoke(base_url, code, temp_dir, env)
            return 0
        except Exception as exc:
            print(f"macOS RemoteDashboardViewModel smoke failed: {exc}", file=sys.stderr)
            with contextlib.suppress(Exception):
                process.terminate()
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
