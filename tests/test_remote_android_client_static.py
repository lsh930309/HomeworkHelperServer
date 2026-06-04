from pathlib import Path
import xml.etree.ElementTree as ET

ANDROID_ROOT = Path("remote_clients/android/HomeworkHelperRemote")
MAIN_SRC = ANDROID_ROOT / "app/src/main/java/dev/homeworkhelper/remote"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _android_sources() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in MAIN_SRC.rglob("*.kt"))


def test_android_project_keeps_compose_release_build_without_ssh_or_tailscale_deps():
    assert (ANDROID_ROOT / "settings.gradle.kts").exists()
    assert (ANDROID_ROOT / "gradlew").exists()
    assert (ANDROID_ROOT / "gradle/wrapper/gradle-wrapper.jar").exists()

    root_build = _read(ANDROID_ROOT / "build.gradle.kts")
    app_build = _read(ANDROID_ROOT / "app/build.gradle.kts")
    wrapper = _read(ANDROID_ROOT / "gradle/wrapper/gradle-wrapper.properties")

    for marker in [
        'id("com.android.application") version "8.13.0" apply false',
        'id("org.jetbrains.kotlin.android") version "2.2.21" apply false',
        'id("org.jetbrains.kotlin.plugin.compose") version "2.2.21" apply false',
        'implementation(platform("androidx.compose:compose-bom:2026.03.00"))',
        'implementation("androidx.activity:activity-compose:1.12.0")',
        'implementation("androidx.compose.material3:material3")',
        'implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.9.4")',
        'implementation("io.coil-kt.coil3:coil-compose:3.4.0")',
        'homeworkhelper.android.defaultRemoteBaseUrl',
        'SMARTTHINGS_DEBUG_PAT',
        'signingConfigs',
    ]:
        assert marker in root_build + app_build
    assert "gradle-9.5.0-bin.zip" in wrapper
    for forbidden in ["sshj", "bouncycastle", "tailscale", "REMOTE_NETWORK_MODE", "EMBEDDED_TAILNET_BRIDGE_CLASS"]:
        assert forbidden.lower() not in app_build.lower()


def test_android_manifest_preserves_permissions_without_tailscale_package_query():
    manifest_path = ANDROID_ROOT / "app/src/main/AndroidManifest.xml"
    ET.parse(manifest_path)
    manifest = _read(manifest_path)

    for marker in [
        'android.permission.INTERNET',
        'android.permission.ACCESS_NETWORK_STATE',
        'android.permission.PACKAGE_USAGE_STATS',
        'android.intent.action.MAIN',
        'android.intent.category.LAUNCHER',
        'android:name=".MainActivity"',
        'android:label="HomeworkHelper Remote"',
    ]:
        assert marker in manifest
    assert 'com.tailscale.ipn' not in manifest


def test_android_direct_https_and_host_delegated_power_contracts_are_present():
    sources = _android_sources()

    for marker in [
        "RemoteAppShell",
        "HomeTab",
        "SetupTab",
        "공유기 공인 IP",
        "공유기 WAN 공인 IPv4만 입력",
        "sslip.io",
        "Connection Doctor",
        "remote/access/status",
        "remote_access_readiness",
        "remote/power/status",
        "remote/power/actions/$encodedAction",
        "PowerAction.Wake",
        "PowerAction.Sleep",
        "PowerAction.Restart",
        "PowerAction.Shutdown",
        "hostDelegatedPowerReady",
        "supportsHostPowerAction",
        "Host HTTPS 위임",
        "SmartThings Wake",
        "SmartThings PAT",
        "selectSmartThingsWakeDevice",
        "RemoteNetworkController",
        "SystemRoute",
        "Public HTTPS direct mode has no client-side network lifecycle side effects.",
        "setupRepairInFlight",
        "repairEnvironment",
        "remote/processes/$encodedId/launch",
        "remote/processes/$encodedId/stop",
        "remote/pair/confirm",
        "remote/devices/$encodedId",
    ]:
        assert marker in sources

    for stale in [
        "Remote Agent URL",
        "Base URL",
        "Tailscale",
        "tailscale",
        "AndroidSSHPowerManager",
        "AndroidSSHKeyStore",
        "remote/power/ssh-key",
        "__HH_SSH_HEALTH_OK__",
        "__HH_REMOTE_POWER_ACCEPTED__",
        "SSH 자동 설정",
        "VPN ON/OFF",
        "Always-on VPN",
        "remote/tailscale/ensure",
        "remote/tokens/refresh",
        "refreshToken",
        "remote/power/{action}",
        "/remote/power/wake",
        "/remote/power/sleep",
        "/remote/power/restart",
        "/remote/power/shutdown",
    ]:
        assert stale not in sources


def test_android_ui_keeps_game_first_home_and_public_ip_only_setup_hierarchy():
    sources = _android_sources()

    for marker in [
        "NavigationBar",
        "NavigationBarItem",
        "RemoteTab.Home",
        "RemoteTab.Setup",
        "게임 상태와 빠른 실행",
        "등록된 게임",
        "PullToRefreshBox",
        "FloatingStatusMessage",
        "AsyncImage",
        "연결/페어링",
        "전원",
        "기기 관리",
        "앱 동작",
        "수동 포트포워딩은 TCP 443",
        "Remote Agent 8000은 외부에 직접 열지 않습니다",
        "DNS/TLS/Bearer/Remote Agent 검사는 내부 URL로 자동 수행",
    ]:
        assert marker in sources
    assert "RemoteTab.Power" not in sources
    assert "RemoteTab.More" not in sources


def test_android_fake_agent_and_smoke_follow_direct_https_contract():
    fake_agent = _read(Path("tools/fake_android_remote_agent.py"))
    smoke = _read(Path("tools/smoke_android_fake_remote.py"))

    for marker in [
        "/remote/status",
        "/remote/readiness",
        "/remote/access/status",
        "/remote/power/status",
        "/remote/power/actions/sleep",
        "/remote/processes/fake-game-a/launch",
        "/api/dashboard/icons/",
        "Fake public HTTPS route ready",
    ]:
        assert marker in fake_agent
    for stale in ["/remote/power/ssh-key", "Fake SSH public key registered", "/remote/tailscale/ensure"]:
        assert stale not in fake_agent

    for marker in [
        "adb",
        "reverse",
        "uiautomator",
        "android-v3-home",
        "android-v3-pull-refresh",
        "android-v3-launch",
        "공유기 공인 IP",
        "Connection Doctor",
        "launch/stop",
    ]:
        assert marker in smoke
    assert "Remote Agent URL" not in smoke
    assert "Tailscale 선택 fallback" not in smoke


def test_remote_docs_define_public_https_manual_port_forward_and_host_delegated_power():
    docs = "\n".join(
        _read(path)
        for path in [
            Path("README.md"),
            Path("docs/remote/setup-guide.md"),
            Path("docs/remote/android-client-design.md"),
            Path("docs/remote/connection-supervisor-protocol.md"),
            Path("docs/remote/macos-client-architecture.md"),
            ANDROID_ROOT / "README.md",
        ]
    )
    for marker in [
        "공개 HTTPS 직접접속",
        "공유기 WAN 공인 IPv4",
        "TCP 443 → Windows Host 38443",
        "Remote Agent 8000",
        "Wake는 SmartThings",
        "Host HTTPS 위임",
        "수동 포트포워딩",
    ]:
        assert marker in docs
    for stale in [
        "Tailscale 선택 fallback",
        "AndroidSSHPowerManager.kt",
        "TailscaleBinding.kt",
        "POST /remote/power/ssh-key",
        "OpenSSH automation protocol",
    ]:
        assert stale not in docs


def test_android_realhost_diagnostic_tool_is_safe_and_redacted():
    script = _read(Path("tools/diagnose_android_realhost.py"))

    for marker in [
        "diagnose_android_realhost.py",
        "read-only by default",
        "run-as",
        "shared_prefs_redacted",
        "asset_probe.json",
        "cached_processes",
        "uiautomator",
        "screencap",
        "logcat",
        "SENSITIVE_KEY_PATTERN",
        "host_power_commands",
        "app_data_clear",
        "device_revoke",
        "Android real-host diagnostic bundle written",
    ]:
        assert marker in script

    for forbidden in ["pm clear", "uninstall", "revokeDevice", "registerPowerSSHKey", "--allow-ssh-register"]:
        assert forbidden not in script
