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
        "platform/RemoteNetworkController.kt",
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
        "Host IP / hostname",
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
        "remote/processes/$encodedId/stop",
        "remote/pair/confirm",
        "remote/devices",
        "remote/power/status",
        "remote/power/setup",
        "process_launch",
        "process_stop",
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
    assert "Text(\"새로고침\")" not in sources

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
        "중단 요청을 접수했습니다.",
        "IMAGE_HITS",
        "swipe_down",
    ]:
        assert marker in smoke


def test_remote_docs_define_macos_reference_android_rebuild_and_shared_supervisor():
    macos = _read(Path("docs/remote/macos-client-architecture.md"))
    android = _read(Path("docs/remote/android-client-design.md"))
    supervisor = _read(Path("docs/remote/connection-supervisor-protocol.md"))
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
        "RemoteNetworkController.kt",
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
        "docs/remote/connection-supervisor-protocol.md",
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
    assert "docs/remote/connection-supervisor-protocol.md" in root_readme


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
        'SMARTTHINGS_DEFAULT_DEVICE_ID',
        '145ad447-9969-4ee7-bda0-1760430d9be1',
        'SMARTTHINGS_DEBUG_PAT',
        'DEFAULT_REMOTE_BASE_URL',
        'homeworkhelper.android.defaultRemoteBaseUrl',
        'REMOTE_NETWORK_MODE',
        'EMBEDDED_TAILNET_BRIDGE_CLASS',
        'EMBEDDED_TAILNET_CONTROL_URL',
        'EMBEDDED_TAILNET_HOSTNAME',
        'homeworkhelper.android.remoteNetworkMode',
        'homeworkhelper.android.embeddedTailnetBridgeClass',
        'homeworkhelper.android.embeddedTailnetAar',
        'homeworkhelper.android.embeddedTailnetControlUrl',
        'homeworkhelper.android.embeddedTailnetHostname',
        'implementation(files(embeddedTailnetAar))',
        'TsnetEmbeddedTailnetBridge',
        'SmartThings_Token',
        'local-artifacts/secrets/$name',
        'localPropertyOrSecretFile("smartthings.pat", "SmartThings_Token")',
        'homeworkhelper.android.debugStoreFile',
        'signingConfigs',
        'getByName("debug")',
        'buildConfig = true',
        'local.properties',
    ]:
        assert marker in app_build
    assert '<package android:name="com.tailscale.ipn" />' in manifest

    for marker in [
        "AndroidSSHPowerManager",
        "AndroidSSHKeyStore",
        "SecureStringStore",
        "AutomationPreferences",
        "RemoteNetworkController",
        "RemoteNetworkState",
        "RemoteNetworkStatus",
        "RemoteNetworkControllers",
        "RemoteNetworkSocketFactory",
        "RemoteHttpTransport",
        "RemoteHttpResponse",
        "EmbeddedTailnetBridge",
        "EmbeddedTailnetRemoteNetworkController",
        "TsnetEmbeddedTailnetBridge",
        "TSNET_BRIDGE_FACTORY_CLASS",
        "dev.homeworkhelper.remote.nativebridge.tailnetbridge.Tailnetbridge",
        "BuildConfig.EMBEDDED_TAILNET_CONTROL_URL",
        "BuildConfig.EMBEDDED_TAILNET_HOSTNAME",
        "ensureConnectedJson",
        "requestJson",
        "openTcp",
        "openRemoteNetworkAuth",
        "인증 열기",
        "RemoteNetworkUnavailableException",
        "ensureRemoteNetwork",
        "앱 전용 원격 네트워크",
        "Remote network mode",
        "Remote network bridge",
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
        "remote/devices/$encodedId",
        "remote/processes/$encodedId/stop",
        "com.tailscale.ipn",
        "com.tailscale.ipn.IPNReceiver",
        "CONNECT_VPN",
        "DISCONNECT_VPN",
        "ComponentName",
        "broadcastTarget",
        "automationAttempt",
        "pollingTimedOut",
        "sleepSafeMode",
        "tailscale.sleep_safe_mode",
        "includePackageFallback",
        "ACTION_APPLICATION_DETAILS_SETTINGS",
        "ACTION_VPN_SETTINGS",
        "openTailscaleAppSettings",
        "openVpnSettings",
        "TAILSCALE_CONNECT_MAX_ATTEMPTS",
        "TAILSCALE_CONNECT_RETRY_DELAY_MILLIS",
        "TAILSCALE_FOREGROUND_CONNECT_DELAY_MILLIS",
        "IPNReceiver component broadcast",
        "Broadcast target",
        "Tailscale retry",
        "Sleep-safe Tailscale 유지",
        "Tailscale sleep-safe",
        "Tailscale auto OFF effective",
        "Always-on VPN",
        "배터리 제한 없음",
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
        "PAT 저장",
        "deviceId만으로는 Cloud 명령을 보낼 수 없습니다.",
        "deviceId가 없습니다.",
        "SmartThings PAT/OAuth 인증",
        "디바이스 자동 조회/선택",
        "PC 켜기",
        "SMARTTHINGS_DEFAULT_DEVICE_ID",
        "SMARTTHINGS_DEFAULT_LOCATION_ID",
        "SMARTTHINGS_DEBUG_PAT",
        "BuildConfig.SMARTTHINGS_DEFAULT_DEVICE_ID",
        "BuildConfig.SMARTTHINGS_DEBUG_PAT",
        "BuildConfig.DEFAULT_REMOTE_BASE_URL",
        "BuildConfig.REMOTE_NETWORK_MODE",
        "BuildConfig.EMBEDDED_TAILNET_BRIDGE_CLASS",
        "RemoteNetworkUnavailableException(unavailableMessage(it))",
        "netlinkrib: permission denied",
        "Android 권한 제한으로 내장 tailnet 초기화가 거부되었습니다",
        "withSystemFallbackIfUnavailable",
        "systemFallback",
        "Android system route fallback",
        "remoteNetworkFailureState",
        "원격 네트워크 처리 실패",
        "normalizeRemoteBaseUrl",
        "remoteHostInputFromBaseUrl",
        "빌드 기본 Remote Agent URL",
        "페어링 성공:",
        "seedSmartThingsPatFromBuildConfig",
        "checkClientTailscaleAndRefresh",
        "waitForTailscaleActive",
        "TAILSCALE_CONNECT_TIMEOUT_MILLIS",
        "명시적 기기 revoke 전까지 유지",
    ]:
        assert marker in sources

    for forbidden in [
        "remote/tailscale/ensure",
        "remote/tokens/refresh",
        "refreshToken",
        "로컬 토큰 삭제",
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
        "/remote/devices",
        "/remote/tokens/refresh",
        "/remote/processes/fake-game-running/stop",
        "suggested_base_urls",
        "Fake SSH public key registered",
    ]:
        assert marker in fake_agent


def test_android_embedded_tailnet_bridge_sources_and_builder_are_declared():
    native_dir = ANDROID_ROOT / "native/tailnetbridge"
    bridge_go = _read(native_dir / "bridge.go")
    bridge_test = _read(native_dir / "bridge_test.go")
    go_mod = _read(native_dir / "go.mod")
    builder = _read(Path("tools/build_android_tailnet_bridge.py"))

    for path in [
        native_dir / "go.mod",
        native_dir / "go.sum",
        native_dir / "bridge.go",
        native_dir / "bridge_test.go",
        Path("tools/build_android_tailnet_bridge.py"),
    ]:
        assert path.exists()

    for marker in [
        "tailscale.com/tsnet",
        "tailscale.com/ipn/ipnstate",
        "EnsureConnectedJson",
        "StatusJson",
        "RequestJson",
        "OpenTcp",
        "Read",
        "Write",
        "CloseConn",
        "ControlURL",
        "Ephemeral:  false",
        "UserLogf",
        "server.Up(ctx)",
        "LocalClient()",
        "AuthURL",
        "TailscaleIPs",
    ]:
        assert marker in bridge_go

    for marker in [
        "TestParseHeaders",
        "TestEncodeStatusKeepsAuthURLReadable",
    ]:
        assert marker in bridge_test

    for marker in [
        "go 1.26.3",
        "tool golang.org/x/mobile/cmd/gobind",
        "tailscale.com v1.98.5",
        "golang.org/x/mobile",
    ]:
        assert marker in go_mod

    for marker in [
        "gomobile",
        "bind",
        'DEFAULT_TARGET = "android/arm64"',
        'DEFAULT_ANDROID_API = "26"',
        'parser.add_argument("--androidapi", default=DEFAULT_ANDROID_API)',
        "-javapkg=dev.homeworkhelper.remote.nativebridge",
        "local-artifacts/android-tailnet/homeworkhelper-tailnet.aar",
        "jni/arm64-v8a/libgojni.so",
        "dev/homeworkhelper/remote/nativebridge/tailnetbridge/Bridge.class",
        "homeworkhelper.android.embeddedTailnetAar",
    ]:
        assert marker in builder


def test_android_shared_contract_parity_and_settings_hierarchy_are_present():
    sources = _android_sources()
    smoke = _read(Path("tools/smoke_android_fake_remote.py"))

    for marker in [
        "SetupSection.Connection",
        "SetupSection.Power",
        "SetupSection.Devices",
        "SetupSection.App",
        "연결/페어링",
        "Tailscale 기반환경",
        "기기 관리",
        "앱 동작",
        "RemoteDevice",
        "revokeDevice",
        "purgeRevokedDevices",
        "stopInFlightId",
        "onStopProcess",
        "schemaVersion",
        "sourceLabel",
        "projectedPercentage",
        "projectedDisplayText",
        "state_revision",
        "Tailscale ON/OFF",
        "RemoteNetworkController",
        "Remote network state",
        "tailscale.connect_on_app_foreground",
        "tailscale.disconnect_on_app_background",
        "tailscale.sleep_safe_mode",
    ]:
        assert marker in sources

    for marker in [
        "연결/페어링",
        "Tailscale 기반환경",
        "⚙ 앱",
        "launch/stop",
    ]:
        assert marker in smoke


def test_android_realhost_repair_and_resource_diagnostics_are_present():
    sources = _android_sources()

    for marker in [
        "setupRepairInFlight",
        "repairEnvironment",
        "repairSshDefaults",
        "shouldReplaceSshHost",
        "sshHasKnownBadEndpoint",
        "resetSshHealthTrust",
        "127.0.0.1",
        "fake-user",
        "환경 자동 복구",
        "전원 명령은 실행하지 않습니다.",
        "테스트/loopback SSH 설정을 실제 host 후보로 복구했습니다.",
        "lifecycle 자동화가 켜져 있으면",
        "onRepairEnvironment",
        'replace("&amp;", "&")',
        "iconFailed",
        "MaterialTheme.colorScheme.error",
    ]:
        assert marker in sources


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
        "--allow-ssh-register",
        "host_power_commands",
        "app_data_clear",
        "device_revoke",
        "ssh_registration_performed",
        "Android real-host diagnostic bundle written",
    ]:
        assert marker in script

    for forbidden in [
        "pm clear",
        "uninstall",
        "revokeDevice",
        "PowerAction",
        "SmartThingsClient(",
        "registerPowerSSHKey",
    ]:
        assert forbidden not in script


def test_flutter_visual_poc_is_fixture_only_and_separate_from_production_android():
    poc = Path("remote_clients/flutter_poc")
    assert (poc / "README.md").exists()
    assert (poc / "pubspec.yaml").exists()
    assert (poc / "lib/main.dart").exists()
    assert (poc / "assets/remote_processes.sample.json").exists()

    readme = _read(poc / "README.md")
    pubspec = _read(poc / "pubspec.yaml")
    main = _read(poc / "lib/main.dart")
    fixture = _read(poc / "assets/remote_processes.sample.json")

    for marker in [
        "생산 Android 클라이언트 교체가 아닌 UI 품질 비교용 POC",
        "실제 host pair/token/SSH/Tailscale/SmartThings 상태를 건드리지 않고 fixture JSON만 렌더링합니다",
        "remote_clients/android/HomeworkHelperRemote",
    ]:
        assert marker in readme

    for marker in [
        "homeworkhelper_flutter_poc",
        "uses-material-design: true",
        "assets/remote_processes.sample.json",
    ]:
        assert marker in pubspec

    for marker in [
        "FixtureHomeScreen",
        "GlassPanel",
        "PowerDock",
        "server_tracked",
        "timestamp_derived",
    ]:
        assert marker in main + fixture
