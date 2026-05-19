from pathlib import Path
import xml.etree.ElementTree as ET


ANDROID_ROOT = Path("remote_clients/android/HomeworkHelperRemote")
MAIN_SRC = ANDROID_ROOT / "app/src/main/java/dev/homeworkhelper/remote"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _android_sources() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in MAIN_SRC.rglob("*.kt"))


def test_android_project_is_home_games_mvp_with_reproducible_compose_build():
    assert (ANDROID_ROOT / "settings.gradle.kts").exists()
    assert (ANDROID_ROOT / "gradlew").exists()
    assert (ANDROID_ROOT / "gradle/wrapper/gradle-wrapper.jar").exists()

    root_build = _read(ANDROID_ROOT / "build.gradle.kts")
    app_build = _read(ANDROID_ROOT / "app/build.gradle.kts")
    wrapper = _read(ANDROID_ROOT / "gradle/wrapper/gradle-wrapper.properties")

    assert 'id("com.android.application") version "8.13.0" apply false' in root_build
    assert 'id("org.jetbrains.kotlin.android") version "2.2.21" apply false' in root_build
    assert 'id("org.jetbrains.kotlin.plugin.compose") version "2.2.21" apply false' in root_build
    assert 'implementation(platform("androidx.compose:compose-bom:2026.03.00"))' in app_build
    assert 'implementation("androidx.activity:activity-compose:1.12.0")' in app_build
    assert 'implementation("androidx.compose.material3:material3")' in app_build
    assert 'implementation("androidx.lifecycle:lifecycle-runtime-compose:2.9.4")' in app_build
    assert 'implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.9.4")' in app_build
    assert 'implementation("io.coil-kt.coil3:coil-compose:3.4.0")' in app_build
    assert 'implementation("io.coil-kt.coil3:coil-network-okhttp:3.4.0")' in app_build
    assert "gradle-9.5.0-bin.zip" in wrapper

    for source_file in [
        "MainActivity.kt",
        "data/RemoteApiClient.kt",
        "data/RemoteModels.kt",
        "data/RemoteRepository.kt",
        "platform/Preferences.kt",
        "platform/TokenStore.kt",
        "state/RemoteViewModel.kt",
        "ui/AppShell.kt",
        "ui/HomeScreen.kt",
        "ui/RemoteTheme.kt",
        "ui/SetupTab.kt",
    ]:
        assert (MAIN_SRC / source_file).exists()
    assert Path("tools/fake_android_remote_agent.py").exists()
    assert Path("tools/smoke_android_fake_remote.py").exists()

    for legacy_file in [
        "RemoteAppViewModel.kt",
        "RemoteRepository.kt",
        "RemoteApiClient.kt",
        "RemoteModels.kt",
        "AndroidTokenStore.kt",
        "RemotePreferences.kt",
        "AndroidIntegration.kt",
        "ui/RemoteScreens.kt",
    ]:
        assert not (MAIN_SRC / legacy_file).exists()


def test_android_manifest_preserves_package_permissions_and_launcher_contract():
    manifest_path = ANDROID_ROOT / "app/src/main/AndroidManifest.xml"
    ET.parse(manifest_path)
    manifest = _read(manifest_path)

    assert 'android.permission.INTERNET' in manifest
    assert 'android.permission.ACCESS_NETWORK_STATE' in manifest
    assert 'android.permission.PACKAGE_USAGE_STATS' in manifest
    assert 'tools:ignore="ProtectedPermissions"' in manifest
    assert 'android.intent.action.MAIN' in manifest
    assert 'android.intent.category.LAUNCHER' in manifest
    assert 'android:usesCleartextTraffic="true"' in manifest
    assert 'android:name=".MainActivity"' in manifest
    assert 'android:label="HomeworkHelper Remote"' in manifest


def test_android_home_games_mvp_implements_required_remote_contracts():
    sources = _android_sources()

    for marker in [
        "RemoteAppShell",
        "NavigationBar",
        "NavigationBarItem",
        "RemoteTab",
        "HomeTab",
        "SetupTab",
        "홈",
        "설정",
        "게임 상태와 빠른 실행",
        "등록된 게임",
        "아래로 당겨 새로고침",
        "PullToRefreshBox",
        "FloatingStatusMessage",
        "AsyncImage",
        "Remote Agent URL",
        "6자리 페어링 코드",
        "실행",
        "실행중",
        "오늘 실행",
        "stale",
        "AuthRejected",
        "OfflineExpected",
        "AgentUnavailable",
        "AndroidKeyStore",
        "remote/status",
        "remote/readiness",
        "remote/processes",
        "remote/processes/$encodedId/launch",
        "remote/pair/confirm",
        "remote/power/status",
        "remote/power/setup",
        "process_launch",
        "auth_required",
        "is_running",
        "played_today",
        "status_text",
        "icon_url",
        "icon_urls",
        "resource_icon_url",
        "resource_icon_urls",
    ]:
        assert marker in sources

    for marker in [
        "HomeworkHelperRemoteRebuildScaffold",
        "Android rebuild scaffold",
        "RemoteHomeScreen",
    ]:
        assert marker not in sources

    for stale in [
        "RemoteAppViewModel",
        "RemoteScreens",
        "remote/power/config",
        "remote/power/{action}",
        "/remote/power/wake",
        "/remote/power/sleep",
        "/remote/power/restart",
        "/remote/power/shutdown",
        "remote/power/smartthings/devices",
        "Full-parity",
        "Tailscale-first Android client",
        "Android-PC 연결 저장",
        "PowerTab",
        "MoreTab",
        "더보기",
    ]:
        assert stale not in sources

    assert "RemoteTab.Power" not in sources
    assert "RemoteTab.More" not in sources
    assert "onClick = onRefresh" not in sources
    assert 'Text("새로고침")' not in sources

def test_android_v3_theme_assets_and_fake_smoke_contract_are_declared():
    sources = _android_sources()
    fake_agent = _read(Path("tools/fake_android_remote_agent.py"))
    smoke = _read(Path("tools/smoke_android_fake_remote.py"))

    for marker in [
        "RemoteTheme",
        "isSystemInDarkTheme()",
        "lightColorScheme",
        "darkColorScheme",
    ]:
        assert marker in sources

    for marker in [
        "Fake Android Remote Agent",
        "/remote/status",
        "/remote/readiness",
        "/remote/processes",
        "/remote/power/status",
        "/remote/power/setup",
        "/remote/processes/fake-game-a/launch",
        "/api/dashboard/icons/",
        "/api/dashboard/resource-icons/",
        "Content-Type",
        "image/png",
        "IMAGE_HITS",
    ]:
        assert marker in fake_agent

    for marker in [
        "adb",
        "reverse",
        "uiautomator",
        "android-v3-home",
        "android-v3-pull-refresh",
        "android-v3-launch",
        "Fake Game A 실행 요청을 접수했습니다.",
        "IMAGE_HITS",
        "swipe_down",
    ]:
        assert marker in smoke


def test_remote_docs_define_macos_reference_android_rebuild_and_shared_supervisor():
    macos = _read(Path("docs/remote/macos-client-architecture.md"))
    android = _read(Path("docs/remote/android-client-design.md"))
    supervisor = _read(Path("REMOTE_CONNECTION_SUPERVISOR.md"))
    setup = _read(Path("docs/remote/setup-guide.md"))
    android_readme = _read(ANDROID_ROOT / "README.md")
    root_readme = _read(Path("README.md"))

    for marker in [
        "macOS Remote Client Architecture",
        "menu-bar popover",
        "Android implication",
        "RemoteConnectionSupervisor",
        "The host does not expose `/remote/power/{action}`",
        "tools/smoke_macos_remote_viewmodel.py",
    ]:
        assert marker in macos

    for marker in [
        "Android Remote Client Rebuild Design",
        "The Android home screen is the equivalent of the macOS popover",
        "Home / Games",
        "Information-only Power/More tabs are consolidated",
        "Pull-to-refresh",
        "Discard before rebuilding",
        "Do not use:",
        "/remote/power/config",
        "/remote/power/{action}",
        "process icon URLs",
        "resource_icon_url",
        "Coil memory/disk caching",
        "SmartThings PAT input",
        "`PC 켜기` device auto-selection",
        "AndroidSSHPowerManager.kt",
        "TailscaleBinding.kt",
    ]:
        assert marker in android

    for marker in [
        "Remote Connection Supervisor, Pairing, and Power Protocol",
        "OpenSSH automation protocol",
        "SSH command acceptance",
        "__HH_REMOTE_POWER_ACCEPTED__",
        "Android-local direct adapters may enable power buttons",
        "SmartThings REST with PAT-based `PC 켜기` device auto-selection",
        "The supervisor never parses raw SSH stdout/stderr",
    ]:
        assert marker in supervisor

    for marker in [
        "Android client v3 game-first UX",
        "docs/remote/macos-client-architecture.md",
        "docs/remote/android-client-design.md",
        "REMOTE_CONNECTION_SUPERVISOR.md",
        "Fake Remote Agent smoke is the default development loop",
    ]:
        assert marker in setup

    for marker in [
        "v3 game-first UX",
        "Do not resurrect the deleted Android full-parity code",
        "two bottom tabs",
    ]:
        assert marker in android_readme

    assert "docs/remote/macos-client-architecture.md" in root_readme
    assert "docs/remote/android-client-design.md" in root_readme
    assert "REMOTE_CONNECTION_SUPERVISOR.md" in root_readme


def test_legacy_android_completion_docs_and_claims_are_removed():
    assert not Path("ANDROID_CLIENT_DEVICE_QA_REPORT.md").exists()

    checked_text = "\n".join(
        _read(path)
        for path in [
            Path("README.md"),
            Path("docs/remote/setup-guide.md"),
            Path("docs/remote/android-client-design.md"),
            ANDROID_ROOT / "README.md",
        ]
    )
    for stale in [
        "implemented Android rebuild baseline",
        "Current Android baseline:",
        "full-parity target and implementation sequence",
        "Full-parity 설계를 따라",
        "Android physical-device verification passed",
        "실기기 개선/검증 보고서",
    ]:
        assert stale not in checked_text


def test_android_internal_verifier_remains_home_mvp_build_entrypoint():
    internal = _read(Path("tools/verify_android_internal.py"))
    artifact = _read(Path("tools/check_android_apk_artifact.py"))

    for marker in [
        "tests/test_remote_android_client_static.py",
        "tools/check_android_sdk_readiness.py",
        ":app:assembleDebug",
        "tools/check_android_apk_artifact.py",
        "Android internal verification passed",
    ]:
        assert marker in internal

    for marker in [
        "dev.homeworkhelper.remote",
        "android.permission.INTERNET",
        "android.permission.ACCESS_NETWORK_STATE",
        "android.permission.PACKAGE_USAGE_STATS",
        "Android APK artifact passed",
    ]:
        assert marker in artifact


def test_android_power_automation_binds_tailscale_ssh_and_smartthings_autoselect():
    sources = _android_sources()
    manifest = _read(ANDROID_ROOT / "app/src/main/AndroidManifest.xml")
    app_build = _read(ANDROID_ROOT / "app/build.gradle.kts")
    fake_agent = _read(Path("tools/fake_android_remote_agent.py"))

    for marker in [
        'implementation("com.hierynomus:sshj:0.40.0")',
        'implementation("org.bouncycastle:bcprov-jdk18on:1.80.2")',
        '<package android:name="com.tailscale.ipn" />',
    ]:
        assert marker in app_build + manifest

    for marker in [
        "AndroidSSHPowerManager",
        "AndroidSSHKeyStore",
        "SecureStringStore",
        "AutomationPreferences",
        "TailscaleBinding",
        "SmartThingsClient",
        "SMARTTHINGS_DEFAULT_WAKE_LABEL = \"PC 켜기\"",
        "selectSmartThingsWakeDevice",
        "devices?capability=switch",
        "devices/${deviceId}/commands",
        "__HH_SSH_HEALTH_OK__",
        "__HH_REMOTE_POWER_ACCEPTED__",
        "androidCompatibleSshConfig",
        "ensurePackagedBouncyCastleProvider",
        "BouncyCastleProvider",
        "PACKAGED_BOUNCY_CASTLE_CLASS",
        "curve25519",
        "setKeyExchangeFactories",
        "remote/power/ssh-key",
        "remote/tailscale/ensure",
        "com.tailscale.ipn",
        "PowerAction.Wake",
        "PowerAction.Sleep",
        "PowerAction.Restart",
        "PowerAction.Shutdown",
        "Fingerprint:",
        "maybeAutoCompleteSshAutomation",
        "completeSshAutomation",
        "SSH key 등록과 health 확인을 자동 완료했습니다.",
        "SSH 자동 설정",
        "Health 재확인",
        "페어링 또는 온라인 복구 후 key 등록과 SSH health는 자동으로 시도됩니다.",
        "deviceId 수동 입력 fallback",
        "디바이스 자동 조회/선택",
        "PC 켜기",
    ]:
        assert marker in sources

    for forbidden in [
        "remote/power/{action}",
        "/remote/power/wake",
        "/remote/power/sleep",
        "/remote/power/restart",
        "/remote/power/shutdown",
        "smartthings.com/v1" + "/remote",
    ]:
        assert forbidden not in sources

    for marker in [
        "/remote/power/ssh-key",
        "/remote/tailscale/ensure",
        "suggested_base_urls",
        "Fake SSH public key registered",
    ]:
        assert marker in fake_agent
