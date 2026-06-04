import importlib.util
import subprocess
import sys
from pathlib import Path


TOOLS = Path("tools")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _load_verifier_module():
    spec = importlib.util.spec_from_file_location(
        "verify_remote_controller",
        TOOLS / "verify_remote_controller.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_remote_verifier_runs_all_controller_validation_lanes():
    verifier = _read(TOOLS / "verify_remote_controller.py")

    for marker in [
        "tests/test_remote_routes.py",
        "tests/test_remote_macos_client_static.py",
        "tools/smoke_remote_controller_runtime.py",
        "tools/smoke_macos_remote_api_client.py",
        "tools/smoke_macos_remote_viewmodel.py",
        "macOS RemoteDashboardViewModel smoke",
        "swift",
        "branch discipline",
        "--require-branch",
        "--expect-main-hash",
        "branch/status/rev-parse",
    ]:
        assert marker in verifier

    assert "--skip-full-pytest" in verifier
    assert "test_remote_android_client_static.py" not in verifier
    assert "gradlew" not in verifier
    assert "Android APK" not in verifier


def test_remote_verifier_branch_discipline_passes_when_refs_match(monkeypatch):
    verifier = _load_verifier_module()

    responses = {
        ("branch", "--show-current"): subprocess.CompletedProcess((), 0, stdout="dev-remote\n", stderr=""),
        ("status", "--short", "--branch"): subprocess.CompletedProcess(
            (),
            0,
            stdout="## dev-remote...origin/dev-remote\n",
            stderr="",
        ),
        ("rev-parse", "--short", "main"): subprocess.CompletedProcess((), 0, stdout="4052da3\n", stderr=""),
        ("rev-parse", "--short", "origin/main"): subprocess.CompletedProcess((), 0, stdout="4052da3\n", stderr=""),
    }

    monkeypatch.setattr(verifier, "_git", lambda args: responses[tuple(args)])

    result = verifier._verify_branch_discipline("dev-remote", "4052da3")

    assert result.returncode == 0
    assert result.status == "passed"
    assert "current_branch: dev-remote" in result.output
    assert "main: 4052da3" in result.output
    assert "origin/main: 4052da3" in result.output


def test_remote_verifier_branch_discipline_fails_on_branch_or_main_drift(monkeypatch):
    verifier = _load_verifier_module()

    responses = {
        ("branch", "--show-current"): subprocess.CompletedProcess((), 0, stdout="main\n", stderr=""),
        ("status", "--short", "--branch"): subprocess.CompletedProcess((), 0, stdout="## main...origin/main\n", stderr=""),
        ("rev-parse", "--short", "main"): subprocess.CompletedProcess((), 0, stdout="deadbee\n", stderr=""),
        ("rev-parse", "--short", "origin/main"): subprocess.CompletedProcess((), 0, stdout="4052da3\n", stderr=""),
    }

    monkeypatch.setattr(verifier, "_git", lambda args: responses[tuple(args)])

    result = verifier._verify_branch_discipline("dev-remote", "4052da3")

    assert result.returncode == 1
    assert result.status == "failed"
    assert "expected branch 'dev-remote', found main" in result.output
    assert "expected main at 4052da3, found deadbee" in result.output


def test_macos_smokes_use_real_server_process_and_production_swift_client():
    runtime = _read(TOOLS / "smoke_remote_controller_runtime.py")
    macos = _read(TOOLS / "smoke_macos_remote_api_client.py")
    viewmodel = _read(TOOLS / "smoke_macos_remote_viewmodel.py")
    supervisor_smoke = _read(TOOLS / "smoke_macos_connection_supervisor.py")
    packager = _read(TOOLS / "package_macos_remote_app.py")
    setup_guide = _read(Path("docs") / "remote" / "setup-guide.md")
    scenario_doc = _read(Path("docs") / "remote" / "macos-connection-state-scenarios.md")

    assert "runpy.run_path('homework_helper.pyw')" in runtime
    assert "run_server_main" in runtime
    assert "remote/pair/start" in runtime
    assert "remote/pair/confirm" in runtime
    assert "remote/devices" in runtime

    assert "RemoteAPIClient.swift" in macos
    assert "RemoteModels.swift" in macos
    assert "LocalPowerWakeManager.swift" in macos
    assert "swiftc" in macos
    assert "confirmPairing" in macos
    assert "authedClient.status()" in macos
    assert "authedClient.capabilities()" in macos
    assert "authedClient.refreshToken()" in macos
    assert "refreshedClient.dashboardSummary()" in macos
    assert "refreshedClient.beholderIncidents()" in macos
    assert "refreshedClient.createGameLink" in macos
    assert "refreshedClient.startMobileSession" in macos
    assert "refreshedClient.endMobileSession" in macos
    assert "refreshedClient.activeMobileSessions()" in macos
    assert "mobileSummary.mobileMetrics" in macos
    assert "refreshedClient.gameLinks()" in macos
    assert "created game-link missing" in macos
    assert "started mobile session missing" in macos
    assert "mobile session end did not close" in macos
    assert "dashboard summary did not include the ended mobile session metrics" in macos
    assert "process seed failed" in macos
    assert "refreshedClient.devices()" in macos
    assert "process.communicate(timeout=5)" in macos
    assert "process.stdout.read()" not in macos

    assert "RemoteDashboardViewModel.swift" in viewmodel
    assert "KeychainTokenStore.swift" in viewmodel
    assert "InMemoryTokenStore" in viewmodel
    assert "RemoteDashboardViewModel(tokenStore: store)" in viewmodel
    assert "await viewModel.confirmPairing()" in viewmodel
    assert "await viewModel.createGameLink()" in viewmodel
    assert "await viewModel.startMobileSession(link)" in viewmodel
    assert "await viewModel.endMobileSession(active)" in viewmodel
    assert "await viewModel.refreshToken()" in viewmodel
    assert "await viewModel.refreshDevices()" in viewmodel
    assert "macOS RemoteDashboardViewModel smoke passed" in viewmodel
    assert "RemoteConnectionSupervisor.swift" in viewmodel
    assert "ssh power acceptance command" in viewmodel
    assert "LocalSSHPowerManager.command(for: \"sleep\")" in viewmodel
    assert "LocalSSHPowerManager.acceptedMarker" in viewmodel
    assert "HH_REMOTE_CACHE_DIR" in viewmodel
    assert "HH_REMOTE_PREFS_SUITE" in viewmodel
    assert "_assert_production_cache_unchanged" in viewmodel
    assert "_production_process_cache_path" in viewmodel
    assert "smoke_ssh_key" in viewmodel
    assert "Smoke Game" in viewmodel

    assert "RemoteConnectionSupervisor.swift" in supervisor_smoke
    assert "macOS RemoteConnectionSupervisor smoke passed" in supervisor_smoke
    assert "tailscale no reply should infer offline host" in supervisor_smoke
    assert "exhausted HTTP reconnect should become agentUnavailable" in supervisor_smoke
    assert "client resume should request immediate probe" in supervisor_smoke
    assert "tools/smoke_macos_connection_supervisor.py" in _read(TOOLS / "verify_remote_controller.py")

    assert "Stateful client smoke isolation contract" in setup_guide
    assert "HH_REMOTE_CACHE_DIR" in setup_guide
    assert "HH_REMOTE_PREFS_SUITE" in setup_guide
    assert "~/Library/Application Support/HomeworkHelperRemote/cache/processes.json" in setup_guide
    assert "production cache signature is unchanged" in setup_guide
    assert "tools/smoke_macos_connection_supervisor.py" in setup_guide
    assert "docs/remote/macos-connection-state-scenarios.md" in setup_guide

    for marker in [
        "External host shutdown / hibernate",
        "Tailscale reachable but HTTP server down",
        "Auth rejected",
        "Client wake command accepted",
        "Recovery with unchanged revision",
        "Mac sleep then resume",
    ]:
        assert marker in scenario_doc

    assert "swift\", \"build\", \"-c\", \"release" in packager
    assert "HomeworkHelperRemote.app" in packager
    assert "CFBundlePackageType" in packager
    assert "APPL" in packager
    assert "CFBundleIdentifier" in packager
    assert "HHRemoteReleaseID" in packager
    assert "HHRemoteGitHash" in packager
    assert "--release-id" in packager
    assert "--git-hash" in packager
    assert "NSAppTransportSecurity" in packager
    assert "NSAllowsArbitraryLoads" in packager
    assert "NSHighResolutionCapable" in packager
    assert "open {app}" in packager


def test_connectivity_smoke_supports_tailnet_or_lan_status_checks():
    connectivity = _read(TOOLS / "smoke_remote_controller_connectivity.py")

    for marker in [
        "--base-url",
        "--token",
        "--expect-auth",
        "--expect-no-auth",
        "/remote/status",
        "process_launch",
        "shortcut_open",
        "auth_required",
        "pairing",
        "power_control",
        "Remote Controller connectivity smoke passed",
    ]:
        assert marker in connectivity


def test_host_power_config_import_tools_are_removed():
    assert not Path("remote_power_config.example.json").exists()
    assert not (TOOLS / "check_remote_power_readiness.py").exists()
    assert not (TOOLS / "import_pcremote_power_config.py").exists()
