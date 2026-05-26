#!/usr/bin/env python3
"""Smoke test macOS RemoteDashboardViewModel against a real Remote Agent.

This drives the same ViewModel methods used by SwiftUI buttons while avoiding
fragile GUI click automation. The harness injects an in-memory token store and
runs against a temporary loopback Remote Agent.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
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
LOCAL_SSH_KEY_MANAGER = MACOS_SOURCE_DIR / "LocalSSHKeyManager.swift"
LOCAL_POWER_WAKE_MANAGER = MACOS_SOURCE_DIR / "LocalPowerWakeManager.swift"
LOCAL_SSH_POWER_MANAGER = MACOS_SOURCE_DIR / "LocalSSHPowerManager.swift"
LOCAL_MOONLIGHT_MANAGER = MACOS_SOURCE_DIR / "LocalMoonlightManager.swift"
TAILSCALE_DISCOVERY = MACOS_SOURCE_DIR / "TailscaleDiscovery.swift"
REMOTE_CLIENT_CACHE = MACOS_SOURCE_DIR / "RemoteClientCache.swift"
REMOTE_CONNECTION_SUPERVISOR = MACOS_SOURCE_DIR / "RemoteConnectionSupervisor.swift"
REMOTE_SMART_POLL_CONTROLLER = MACOS_SOURCE_DIR / "RemoteSmartPollController.swift"
REMOTE_LOGIN_ITEM_MANAGER = MACOS_SOURCE_DIR / "RemoteLoginItemManager.swift"
REMOTE_UI_TEST_FLAGS = MACOS_SOURCE_DIR / "RemoteUITestFlags.swift"
REMOTE_GLOBAL_SHORTCUT_REGISTRAR = MACOS_SOURCE_DIR / "RemoteGlobalShortcutRegistrar.swift"
REMOTE_VIEW_MODEL = MACOS_SOURCE_DIR / "RemoteDashboardViewModel.swift"


def _production_process_cache_path() -> Path:
    return Path.home() / "Library" / "Application Support" / "HomeworkHelperRemote" / "cache" / "processes.json"


def _file_signature(path: Path) -> tuple[bool, int, int, str]:
    if not path.exists():
        return (False, 0, 0, "")
    data = path.read_bytes()
    stat = path.stat()
    return (True, stat.st_size, stat.st_mtime_ns, hashlib.sha256(data).hexdigest())


def _assert_production_cache_unchanged(before: tuple[bool, int, int, str]) -> None:
    path = _production_process_cache_path()
    after = _file_signature(path)
    if after != before:
        raise RuntimeError(
            "macOS ViewModel smoke mutated the production process cache. "
            f"Tests must use HH_REMOTE_CACHE_DIR, not {path}"
        )


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


def _swift_smoke_source(base_url: str, offline_base_url: str, pairing_code: str, smartthings_cli: str, ssh_key_path: str) -> str:
    source = r'''
        import Foundation
        import SwiftUI

        final class SmokeInMemoryTokenStore: RemoteTokenStore {
            var token = ""
            func load() -> String { token }
            func save(_ token: String) { self.token = token }
            func delete() { token = "" }
        }

        enum RemotePopoverGlassTransparency: String {
            case standard
            case high
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
                if let suite = ProcessInfo.processInfo.environment["HH_REMOTE_PREFS_SUITE"],
                   let defaults = UserDefaults(suiteName: suite) {
                    defaults.removePersistentDomain(forName: suite)
                    defaults.set("sparkles", forKey: "remote.menuBarIconSymbol")
                }
                let store = SmokeInMemoryTokenStore()
                let viewModel = RemoteDashboardViewModel(tokenStore: store)
                guard viewModel.menuBarIdleIconSymbol == "sparkles",
                      viewModel.menuBarRunningIconSymbol == "play.circle.fill",
                      viewModel.menuBarOfflineIconSymbol == "power.circle.fill" else {
                    fatalError("stateful menu bar icons should migrate the legacy idle icon and keep state defaults")
                }
                guard viewModel.moonlightSnapshot.readiness == .missingApp else {
                    fatalError("smoke should use isolated Moonlight overrides instead of reading production Moonlight state")
                }
                viewModel.addDefaultSmartScheduleRule()
                guard viewModel.smartScheduleRules.count == 1,
                      viewModel.smartScheduleRules[0].weekdayDisplay == "월~금",
                      viewModel.smartScheduleRules[0].wakeHost == true else {
                    fatalError("default smart schedule should create a weekday wake macro")
                }
                viewModel.smartScheduleRules.removeAll()
                viewModel.menuBarRunningIconSymbol = "moon.fill"
                guard viewModel.menuBarIconSymbol(for: .running) == "moon.fill" else {
                    fatalError("running menu bar icon should be user-selectable")
                }
                let staminaProgress = RemoteProcess.Progress(
                    kind: "stamina",
                    percentage: 18,
                    displayText: "서버 자원 표시",
                    staminaCurrent: 44,
                    staminaMax: 240,
                    hoyolabGameID: "zzz",
                    resourceIconURL: nil,
                    resourceIconURLs: nil,
                    remainingSeconds: 7200,
                    readyAt: Date().addingTimeInterval(7200).timeIntervalSince1970
                )
                let cycleProgress = RemoteProcess.Progress(
                    kind: "cycle",
                    percentage: 42,
                    displayText: "2시간",
                    staminaCurrent: nil,
                    staminaMax: nil,
                    hoyolabGameID: nil,
                    resourceIconURL: nil,
                    resourceIconURLs: nil,
                    remainingSeconds: 7200,
                    readyAt: Date().addingTimeInterval(7200).timeIntervalSince1970
                )
                viewModel.cycleProgressDisplayMode = .remaining
                guard viewModel.progressMeterDisplayText(staminaProgress) == "서버 자원 표시",
                      viewModel.progressMeterDisplayText(cycleProgress) == "42%",
                      viewModel.trackBadgeDisplayText(staminaProgress) == "2시간",
                      viewModel.trackBadgeDisplayText(cycleProgress) == "2시간" else {
                    fatalError("progress meter should show stamina resources while track badge should show remaining time")
                }
                viewModel.cycleProgressDisplayMode = .readyAt
                guard viewModel.trackBadgeDisplayText(staminaProgress).hasSuffix("완료"),
                      viewModel.trackBadgeDisplayText(cycleProgress).hasSuffix("완료"),
                      viewModel.trackBadgeDisplayText(staminaProgress) != "44/240" else {
                    fatalError("track badge should show ready-at text for all progress kinds when preferred")
                }
                viewModel.baseURLText = "__BASE_URL__"
                viewModel.deviceName = "macos-viewmodel-smoke"
                viewModel.powerConfig.sshKeyPath = "__SMOKE_SSH_KEY__"
                viewModel.powerConfig.smartthingsCLIPath = "__SMARTTHINGS_CLI__"
                viewModel.pairingCode = "__PAIRING_CODE__"

                smokeStep("ssh power acceptance command")
                let sleepCommand = try! LocalSSHPowerManager.command(for: "sleep")
                guard sleepCommand.contains(LocalSSHPowerManager.acceptedMarker),
                      sleepCommand.contains("rundll32.exe powrprof.dll,SetSuspendState 0,0,0"),
                      sleepCommand.contains("start") == false else {
                    fatalError("sleep command should emit the acceptance marker before the direct rundll32 invocation that works over Windows OpenSSH")
                }
                let shutdownCommand = try! LocalSSHPowerManager.command(for: "shutdown")
                guard shutdownCommand.contains(LocalSSHPowerManager.acceptedMarker),
                      shutdownCommand.contains("shutdown /s /t 1") else {
                    fatalError("shutdown command should require command success before the acceptance marker")
                }
                let restartCommand = try! LocalSSHPowerManager.command(for: "restart")
                guard restartCommand.contains(LocalSSHPowerManager.acceptedMarker),
                      restartCommand.contains("shutdown /r /t 1") else {
                    fatalError("restart command should leave time for the acceptance marker after scheduling reboot")
                }

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
                guard let launchProcess = viewModel.processes.first(where: { $0.id == "smoke-game" }) else {
                    fatalError("seeded process missing before launch")
                }
                viewModel.hostAvailabilityState = .offlineExpected
                guard !viewModel.isLaunchEnabled(launchProcess) else {
                    fatalError("offline launch should stay disabled; Moonlight ON no longer doubles as a host wake CTA")
                }
                viewModel.hostAvailabilityState = .online
                let hostLabelBeforeLaunch = viewModel.hostStatusLabel
                smokeStep("launch command scoped mirror")
                await viewModel.launch(launchProcess)
                guard viewModel.hostStatusLabel == hostLabelBeforeLaunch,
                      viewModel.hostStatusLabel == "페어링됨" else {
                    fatalError("launch should not churn the host connection pill: before=\(hostLabelBeforeLaunch) after=\(viewModel.hostStatusLabel)")
                }
                guard viewModel.isLaunchPending(launchProcess) else {
                    fatalError("launch should enter row-scoped pending state instead of global refresh")
                }
                try? await Task.sleep(nanoseconds: 6_000_000_000)
                guard viewModel.menuBarPresentationState() == .idle,
                      viewModel.menuBarIconSymbol(for: .idle) == "sparkles" else {
                    fatalError("online paired host without running games should use the idle menu bar icon")
                }
                viewModel.processes = [
                    RemoteProcess(
                        processID: "sort-hi",
                        name: "힣 테스트",
                        monitoringPath: nil,
                        launchPath: nil,
                        preferredLaunchType: nil,
                        lastPlayedTimestamp: nil,
                        userCycleHours: nil,
                        staminaTrackingEnabled: false,
                        hoyolabGameID: nil,
                        staminaCurrent: nil,
                        staminaMax: nil,
                        staminaUpdatedAt: nil,
                        progress: nil,
                        iconURL: nil,
                        iconURLs: nil,
                        isRunning: false,
                        playedToday: false,
                        statusText: nil
                    ),
                    RemoteProcess(
                        processID: "sort-ga",
                        name: "가 테스트",
                        monitoringPath: nil,
                        launchPath: nil,
                        preferredLaunchType: nil,
                        lastPlayedTimestamp: nil,
                        userCycleHours: nil,
                        staminaTrackingEnabled: false,
                        hoyolabGameID: nil,
                        staminaCurrent: nil,
                        staminaMax: nil,
                        staminaUpdatedAt: nil,
                        progress: nil,
                        iconURL: nil,
                        iconURLs: nil,
                        isRunning: false,
                        playedToday: false,
                        statusText: nil
                    ),
                    RemoteProcess(
                        processID: "sort-na",
                        name: "나 테스트",
                        monitoringPath: nil,
                        launchPath: nil,
                        preferredLaunchType: nil,
                        lastPlayedTimestamp: nil,
                        userCycleHours: nil,
                        staminaTrackingEnabled: false,
                        hoyolabGameID: nil,
                        staminaCurrent: nil,
                        staminaMax: nil,
                        staminaUpdatedAt: nil,
                        progress: nil,
                        iconURL: nil,
                        iconURLs: nil,
                        isRunning: false,
                        playedToday: false,
                        statusText: nil
                    )
                ]
                guard viewModel.displayProcesses.map({ $0.name }) == ["가 테스트", "나 테스트", "힣 테스트"] else {
                    fatalError("displayProcesses should sort game names by Korean dictionary order: \(viewModel.displayProcesses.map { $0.name })")
                }
                viewModel.processes = [
                    RemoteProcess(
                        processID: "running-game",
                        name: "실행 중",
                        monitoringPath: nil,
                        launchPath: nil,
                        preferredLaunchType: nil,
                        lastPlayedTimestamp: nil,
                        userCycleHours: nil,
                        staminaTrackingEnabled: false,
                        hoyolabGameID: nil,
                        staminaCurrent: nil,
                        staminaMax: nil,
                        staminaUpdatedAt: nil,
                        progress: nil,
                        iconURL: nil,
                        iconURLs: nil,
                        isRunning: true,
                        playedToday: false,
                        statusText: "실행 중"
                    )
                ]
                guard viewModel.menuBarPresentationState() == .running else {
                    fatalError("online paired host with any running game should use the running menu bar icon")
                }
                guard viewModel.isStopEnabled(viewModel.processes[0]) else {
                    fatalError("online running game should expose the remote stop action")
                }
                guard RemoteClientCache.loadProcesses().contains(where: { $0.id == "smoke-game" }) else {
                    fatalError("refresh did not write process snapshot cache")
                }
                guard viewModel.powerSetup != nil else {
                    fatalError("refresh did not populate power setup: \(viewModel.message)")
                }
                guard viewModel.powerConfig.smartthingsDeviceID == "145ad447-9969-4ee7-bda0-1760430d9be1" else {
                    fatalError("SmartThings PC 켜기 device was not auto-selected: \(viewModel.powerConfig.smartthingsDeviceID) message=\(viewModel.message)")
                }
                smokeStep("offline local wake")
                viewModel.hostConnectionState = "offline"
                viewModel.powerConfig.smartthingsDeviceID = "smoke-device"
                await viewModel.power("wake")
                guard viewModel.message.contains("wake 신호") else {
                    fatalError("offline local wake did not use SmartThings fallback: \(viewModel.message)")
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

                smokeStep("closed port connection loss")
                viewModel.baseURLText = "__OFFLINE_BASE_URL__"
                viewModel.processes = [
                    RemoteProcess(
                        processID: "offline-yesterday",
                        name: "어제 실행",
                        monitoringPath: nil,
                        launchPath: nil,
                        preferredLaunchType: nil,
                        lastPlayedTimestamp: Date().addingTimeInterval(-36 * 3600).timeIntervalSince1970,
                        userCycleHours: 24,
                        staminaTrackingEnabled: false,
                        hoyolabGameID: nil,
                        staminaCurrent: nil,
                        staminaMax: nil,
                        staminaUpdatedAt: nil,
                        progress: nil,
                        iconURL: nil,
                        iconURLs: nil,
                        isRunning: false,
                        playedToday: true,
                        statusText: "오늘 실행"
                    ),
                    RemoteProcess(
                        processID: "offline-no-timestamp",
                        name: "기록 없음",
                        monitoringPath: nil,
                        launchPath: nil,
                        preferredLaunchType: nil,
                        lastPlayedTimestamp: nil,
                        userCycleHours: 24,
                        staminaTrackingEnabled: false,
                        hoyolabGameID: nil,
                        staminaCurrent: nil,
                        staminaMax: nil,
                        staminaUpdatedAt: nil,
                        progress: nil,
                        iconURL: nil,
                        iconURLs: nil,
                        isRunning: false,
                        playedToday: true,
                        statusText: "오늘 실행"
                    )
                ]
                await viewModel.refresh()
                guard viewModel.hostAvailabilityState != .online else {
                    fatalError("closed port refresh should not leave host online")
                }
                guard !viewModel.processes.isEmpty else {
                    fatalError("closed port refresh should preserve cached standalone process cards")
                }
                guard viewModel.menuBarPresentationState() == .offline,
                      viewModel.menuBarIconSymbol(for: .offline) == "power.circle.fill" else {
                    fatalError("offline standalone mode should use the offline menu bar icon")
                }
                guard viewModel.processes.allSatisfy({ $0.playedToday == false && $0.statusText == "대기" }) else {
                    fatalError("offline standalone process cards should recompute today's badge from lastPlayedTimestamp: \(viewModel.processes)")
                }

                print("macOS RemoteDashboardViewModel smoke passed: processes=\(viewModel.processes.count), game_links=\(viewModel.gameLinks.count), devices=\(viewModel.devices.count), message=\(viewModel.message)")
            }
        }
    '''
    return (
        textwrap.dedent(source)
        .replace("__BASE_URL__", base_url)
        .replace("__OFFLINE_BASE_URL__", offline_base_url)
        .replace("__PAIRING_CODE__", pairing_code)
        .replace("__SMARTTHINGS_CLI__", smartthings_cli)
        .replace("__SMOKE_SSH_KEY__", ssh_key_path)
    )


def _compile_and_run_swift_smoke(base_url: str, offline_base_url: str, pairing_code: str, smartthings_cli: str, ssh_key_path: str, work_dir: Path, env: dict[str, str]) -> None:
    smoke_source = work_dir / "MacOSRemoteViewModelSmoke.swift"
    binary = work_dir / "macos-remote-viewmodel-smoke"
    smoke_source.write_text(_swift_smoke_source(base_url, offline_base_url, pairing_code, smartthings_cli, ssh_key_path), encoding="utf-8")
    compile_cmd = [
        "swiftc",
        "-parse-as-library",
        str(REMOTE_MODELS),
        str(REMOTE_API_CLIENT),
        str(KEYCHAIN_TOKEN_STORE),
        str(LOCAL_SSH_KEY_MANAGER),
        str(LOCAL_POWER_WAKE_MANAGER),
        str(LOCAL_SSH_POWER_MANAGER),
        str(LOCAL_MOONLIGHT_MANAGER),
        str(TAILSCALE_DISCOVERY),
        str(REMOTE_CLIENT_CACHE),
        str(REMOTE_CONNECTION_SUPERVISOR),
        str(REMOTE_SMART_POLL_CONTROLLER),
        str(REMOTE_LOGIN_ITEM_MANAGER),
        str(REMOTE_UI_TEST_FLAGS),
        str(REMOTE_GLOBAL_SHORTCUT_REGISTRAR),
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
    production_cache_signature = _file_signature(_production_process_cache_path())

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
                "HH_REMOTE_CACHE_DIR": str(temp_dir / "remote-client-cache"),
                "HH_REMOTE_PREFS_SUITE": f"dev.homeworkhelper.remote.smoke.{os.getpid()}",
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
                    "monitoring_path": "/bin/echo",
                    "launch_path": "/bin/echo",
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
            fake_smartthings = temp_dir / "smartthings"
            fake_smartthings.write_text(
                """#!/bin/sh
if [ "$1" = "devices" ]; then
  cat <<'EOF'
───────────────────────────────────────────────────────────────────────────────────────────────
 #  Label                Name                     Type    Device Id
───────────────────────────────────────────────────────────────────────────────────────────────
 1  PC 켜기              vWOL.v1                  LAN     145ad447-9969-4ee7-bda0-1760430d9be1
 2  PC 플러그            Samjin Wi-Fi Smart Plug  MQTT    1693383e-f46b-4e90-ba3b-1d0aca9c27bf
───────────────────────────────────────────────────────────────────────────────────────────────
EOF
  exit 0
fi
exit 0
""",
                encoding="utf-8",
            )
            fake_smartthings.chmod(0o755)
            smoke_ssh_key = temp_dir / "smoke_ssh" / "homeworkhelper_remote_ed25519"
            env["HH_REMOTE_MOONLIGHT_APP_PATHS"] = str(temp_dir / "MissingMoonlight.app")
            env["HH_REMOTE_MOONLIGHT_PREFS_PATH"] = str(temp_dir / "missing-moonlight.plist")
            offline_base_url = f"http://127.0.0.1:{_free_loopback_port()}"
            _compile_and_run_swift_smoke(base_url, offline_base_url, code, str(fake_smartthings), str(smoke_ssh_key), temp_dir, env)
            _assert_production_cache_unchanged(production_cache_signature)
            return 0
        except Exception as exc:
            print(f"macOS RemoteDashboardViewModel smoke failed: {exc}", file=sys.stderr)
            try:
                _assert_production_cache_unchanged(production_cache_signature)
            except Exception as guard_exc:
                print(f"macOS RemoteDashboardViewModel smoke isolation guard failed: {guard_exc}", file=sys.stderr)
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
