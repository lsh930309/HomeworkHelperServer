from pathlib import Path


TOOLS = Path("tools")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_remote_verifier_runs_all_controller_validation_lanes():
    verifier = _read(TOOLS / "verify_remote_controller.py")

    for marker in [
        "tests/test_remote_routes.py",
        "tests/test_remote_android_client_static.py",
        "tests/test_remote_macos_client_static.py",
        "tools/smoke_remote_controller_runtime.py",
        "tools/smoke_macos_remote_api_client.py",
        "tools/check_remote_power_readiness.py",
        "tools/check_android_sdk_readiness.py",
        "tools/smoke_android_remote_controller.py",
        "swift",
        "./gradlew",
        ":app:assembleDebug",
        "--stacktrace",
    ]:
        assert marker in verifier

    assert "--allow-android-license-blocker" in verifier
    assert "ANDROID_LICENSE_MARKERS" in verifier
    assert "blocked: android-sdk-license" in verifier
    assert "--skip-full-pytest" in verifier


def test_android_sdk_readiness_script_reports_blockers_without_mutating_sdk():
    readiness = _read(TOOLS / "check_android_sdk_readiness.py")

    for marker in [
        "platform-tools",
        "platforms;android-36",
        "build-tools;35.0.0",
        "android-sdk-license",
        "android-sdk-preview-license",
        "--allow-blocker",
        "sdkmanager --licenses",
        "sdkmanager --install",
    ]:
        assert marker in readiness

    assert "subprocess.run" not in readiness
    assert "check_readiness" in readiness
    assert "return 0 if args.allow_blocker else 2" in readiness


def test_android_apk_smoke_distinguishes_missing_apk_from_device_launch():
    smoke = _read(TOOLS / "smoke_android_remote_controller.py")

    for marker in [
        "app-debug.apk",
        "dev.homeworkhelper.remote",
        "dev.homeworkhelper.remote/.MainActivity",
        "--allow-missing-apk",
        "adb install",
        "am",  # shell am start command pieces are built as argv entries.
        "start",
        "android.intent.action.MAIN",
        "android.intent.category.LAUNCHER",
        "android.permission.INTERNET",
        "--report-usage-access",
        "--require-usage-access",
        "--open-usage-access-settings",
        "GET_USAGE_STATS",
        "android.settings.USAGE_ACCESS_SETTINGS",
        "UsageStats appop",
        "UsageStats access not allowed",
    ]:
        assert marker in smoke

    assert "return 0 if args.allow_missing_apk else 2" in smoke
    assert "Expected exactly one connected adb device" in smoke
    assert "Package {args.package} is not installed" in smoke


def test_macos_smokes_use_real_server_process_and_production_swift_client():
    runtime = _read(TOOLS / "smoke_remote_controller_runtime.py")
    macos = _read(TOOLS / "smoke_macos_remote_api_client.py")

    assert "runpy.run_path('homework_helper.pyw')" in runtime
    assert "run_server_main" in runtime
    assert "remote/pair/start" in runtime
    assert "remote/pair/confirm" in runtime
    assert "remote/devices" in runtime

    assert "RemoteAPIClient.swift" in macos
    assert "RemoteModels.swift" in macos
    assert "swiftc" in macos
    assert "confirmPairing" in macos
    assert "authedClient.status()" in macos
    assert "authedClient.dashboardSummary()" in macos
    assert "authedClient.devices()" in macos


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


def test_remote_power_readiness_reports_config_without_sending_power_commands():
    readiness = _read(TOOLS / "check_remote_power_readiness.py")

    for marker in [
        "remote_power_config.json",
        "remote_power_config.example.json",
        "smartthings_cli_path",
        "ssh_host",
        "ssh_key_path",
        "--allow-blocker",
        "Remote power readiness blocked",
        "supported_actions",
    ]:
        assert marker in readiness

    assert "perform(" not in readiness
    assert "subprocess.run" not in readiness
