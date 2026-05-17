from pathlib import Path
import xml.etree.ElementTree as ET


ANDROID_ROOT = Path("remote_clients/android/HomeworkHelperRemote")
MAIN_SRC = ANDROID_ROOT / "app/src/main/java/dev/homeworkhelper/remote"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _android_sources() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in MAIN_SRC.rglob("*.kt"))


def test_android_project_contains_reproducible_compose_build_contract():
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
    assert "gradle-9.5.0-bin.zip" in wrapper

    for source_file in [
        "MainActivity.kt",
        "RemoteAppViewModel.kt",
        "RemoteRepository.kt",
        "RemoteApiClient.kt",
        "RemoteModels.kt",
        "AndroidTokenStore.kt",
        "RemotePreferences.kt",
        "AndroidIntegration.kt",
        "ui/RemoteScreens.kt",
    ]:
        assert (MAIN_SRC / source_file).exists()


def test_android_manifest_declares_remote_and_mobile_runtime_permissions():
    manifest_path = ANDROID_ROOT / "app/src/main/AndroidManifest.xml"
    ET.parse(manifest_path)
    manifest = _read(manifest_path)

    assert 'android.permission.INTERNET' in manifest
    assert 'android.permission.PACKAGE_USAGE_STATS' in manifest
    assert 'tools:ignore="ProtectedPermissions"' in manifest
    assert 'android.intent.action.MAIN' in manifest
    assert 'android.intent.category.LAUNCHER' in manifest
    assert 'android:usesCleartextTraffic="true"' in manifest


def test_android_api_client_tracks_remote_agent_contract():
    api_client = _read(MAIN_SRC / "RemoteApiClient.kt")
    models = _read(MAIN_SRC / "RemoteModels.kt")

    for endpoint in [
        "remote/status",
        "remote/capabilities",
        "remote/dashboard/summary",
        "remote/beholder/incidents",
        "remote/game-links",
        "remote/mobile-sessions/active",
        "remote/mobile-sessions/start",
        "remote/mobile-sessions/end",
        "remote/processes",
        "remote/shortcuts",
        "remote/power/$action",
        "remote/power/config",
        "remote/pair/confirm",
        "remote/tokens/refresh",
        "remote/devices",
        "remote/devices/revoked",
        "remote/readiness",
        "remote/logging/config",
        "remote/tailscale/ensure",
        "remote/power/setup",
        "remote/power/ssh-key",
        "remote/power/smartthings/devices",
        "remote/processes/${pathSegment(id)}/launch",
        "remote/shortcuts/${pathSegment(id)}/open",
    ]:
        assert endpoint in api_client

    assert 'setRequestProperty("Authorization", "Bearer $bearerToken")' in api_client
    assert 'deviceName = optString("name", optString("device_name"))' in api_client
    assert "data class RemoteStatus" in models
    assert "data class RemoteCapabilities" in models
    assert "data class RemoteDashboardSummary" in models
    assert "data class RemoteBeholderIncident" in models
    assert "data class RemoteGameLink" in models
    assert "data class RemoteMobileSession" in models
    assert "data class RemotePowerStatus" in models
    assert "data class RemotePowerConfigPayload" in models
    assert "data class RemotePowerConfigResponse" in models
    assert "fun isPowerActionEnabled(action: String): Boolean" in models
    assert "val supportedActions: Set<String>" in models
    assert "data class PairingResult" in models
    assert "data class RemoteDevice" in models
    assert "tokenRefreshedAt" in models
    assert 'optJSONObject("power")' in api_client
    assert 'capabilities.optBoolean("dashboard_summary")' in api_client
    assert 'capabilities.optBoolean("beholder_incidents")' in api_client
    assert 'capabilities.optBoolean("game_links")' in api_client
    assert 'capabilities.optBoolean("mobile_sessions")' in api_client
    assert 'capabilities.optBoolean("power_config")' in api_client
    assert 'fun capabilities(): RemoteCapabilities' in api_client
    assert 'processLaunch = capabilities.optBoolean("process_launch")' in api_client
    assert 'fun refreshToken(): PairingResult' in api_client
    assert 'post("remote/tokens/refresh", "{}")' in api_client
    assert 'tokenRefreshedAt = optString("token_refreshed_at")' in api_client
    assert 'fun dashboardSummary(): RemoteDashboardSummary' in api_client
    assert 'fun gameLinks(): List<RemoteGameLink>' in api_client
    assert 'fun createGameLink(processId: String, androidPackageName: String' in api_client
    assert 'fun startMobileSession(gameLinkId: String, source: String = "manual", startedAtSeconds: Double? = null)' in api_client
    assert 'body.put("started_at", startedAtSeconds)' in api_client
    assert 'fun endMobileSession(sessionId: String)' in api_client
    assert 'fun activeMobileSessions(): List<RemoteMobileSession>' in api_client
    assert 'json.optJSONArray("links")' in api_client
    assert 'androidPackageName = optString("android_package_name")' in api_client
    assert 'fun beholderIncidents(): List<RemoteBeholderIncident>' in api_client
    assert 'userTitle = item.optString("user_title")' in api_client
    assert 'riskLabels = item.optJSONArray("risk_labels")?.toStringList().orEmpty()' in api_client
    assert 'metrics.optDouble("daily_average_seconds")' in api_client
    assert 'metrics.optJSONObject("top_game")' in api_client
    assert 'json.optJSONObject("mobile_metrics")' in api_client
    assert 'mobileMetrics?.optDouble("total_seconds")' in api_client
    assert 'mobileMetrics?.optInt("active_session_count")' in api_client
    assert 'mobileTopGame?.optString("android_package_name")' in api_client
    assert 'optJSONArray("supported_actions")?.toStringSet().orEmpty()' in api_client
    assert 'targetHost = optString("target_host")' in api_client
    assert 'fun powerConfig(): RemotePowerConfigResponse' in api_client
    assert 'fun savePowerConfig(config: RemotePowerConfigPayload)' in api_client
    assert 'put("remote/power/config", body)' in api_client
    assert 'toPowerConfigResponse()' in api_client


def test_android_token_storage_uses_keystore_not_plaintext_preferences():
    token_store = _read(MAIN_SRC / "AndroidTokenStore.kt")
    preferences = _read(MAIN_SRC / "RemotePreferences.kt")
    main_activity = _read(MAIN_SRC / "MainActivity.kt")
    sources = _android_sources()

    assert "AndroidKeyStore" in token_store
    assert "KeyGenParameterSpec" in token_store
    assert "KeyProperties.KEY_ALGORITHM_AES" in token_store
    assert "KeyProperties.BLOCK_MODE_GCM" in token_store
    assert "AES/GCM/NoPadding" in token_store
    assert "GCMParameterSpec" in token_store
    assert "encrypted_bearer_token" in token_store

    assert "legacyToken()" in preferences
    assert "clearLegacyToken()" in preferences
    assert "putString(KEY_LEGACY_TOKEN" not in preferences
    assert "AndroidTokenStore(context)" in main_activity
    assert "tokenStore.saveToken(state.token)" in sources
    assert "preferences.clearLegacyToken()" in sources
    assert "토큰 삭제" in sources


def test_android_local_integration_covers_intent_and_usage_access_boundaries():
    integration = _read(MAIN_SRC / "AndroidIntegration.kt")

    assert "getLaunchIntentForPackage" in integration
    assert "ACTION_USAGE_ACCESS_SETTINGS" in integration
    assert "OPSTR_GET_USAGE_STATS" in integration
    assert "unsafeCheckOpNoThrow" in integration
    assert "FLAG_ACTIVITY_NEW_TASK" in integration
    assert "data class AndroidUsageSnapshot" in integration
    assert "UsageStatsManager" in integration
    assert "queryEvents" in integration
    assert "UsageEvents.Event.MOVE_TO_FOREGROUND" in integration
    assert "UsageEvents.Event.ACTIVITY_RESUMED" in integration
    assert "recentForegroundApp" in integration
    assert "TAILSCALE_PACKAGE" in integration
    assert "com.tailscale.ipn" in integration
    assert "openTailscaleInstallPage" in integration
    assert "ACTION_APPLICATION_DETAILS_SETTINGS" in integration


def test_android_power_ui_uses_remote_power_capabilities_to_disable_actions():
    sources = _android_sources()
    models = _read(MAIN_SRC / "RemoteModels.kt")

    assert "fun isPowerActionEnabled(action: String): Boolean" in models
    assert "!powerControl || !currentPower.configured" in models
    assert "currentPower.supportedActions.contains(action)" in models
    assert "fun powerCommand(action: String)" in sources
    assert "state.status?.isPowerActionEnabled(action) == true" in sources
    assert "전원 제어 adapter가 설정되지" in sources
    assert 'enabled = viewModel.isPowerActionEnabled("wake")' in sources
    assert 'enabled = viewModel.isPowerActionEnabled("sleep")' in sources
    assert 'enabled = viewModel.isPowerActionEnabled("restart")' in sources
    assert 'enabled = viewModel.isPowerActionEnabled("shutdown")' in sources
    assert "지원 명령" in sources
    assert "전원 상태" in sources
    assert "전원 설정" in sources
    assert "전원 설정 저장" in sources
    assert "fun savePowerConfig()" in sources
    assert "플레이 요약" in sources
    assert "dashboardSummary" in sources
    assert "모바일 플레이" in sources
    assert "mobileSessionCount" in models
    assert "Beholder 알림" in sources
    assert "beholderIncidents" in sources
    assert "Android-PC 연결" in sources
    assert "gameLinks" in sources
    assert "Android 실행" in sources
    assert "모바일 시작" in sources
    assert "모바일 종료" in sources
    assert "fun startMobileSession(link: RemoteGameLink)" in sources
    assert "fun endMobileSession(session: RemoteMobileSession)" in sources
    assert "fun createGameLink()" in sources
    assert "Android-PC 연결 저장" in sources
    assert "gameLinkPackageName" in sources
    assert "fun refreshToken()" in sources
    assert "토큰 갱신" in sources
    assert "formatDuration" in sources
    assert "RemoteReadiness" in models
    assert "RemoteLoggingConfigResponse" in models
    assert "RemotePowerSetupResponse" in models
    assert "updateSystemDarkMode" in sources
    assert "systemThemeLabel" in sources
    assert "snapshotStaleReason" in sources
    assert "baseUrlError" in sources
    assert "applySuggestedBaseUrl" in sources
    assert "validateBaseUrl" in sources
    assert "toUserMessage" in sources
    assert "headerStatusColor" in sources
    assert "headerStatusLabel" in sources
    assert "StaleSnapshotBanner" in sources
    assert "listState.scrollToItem(0)" in sources
    assert "시스템 테마" in sources
    assert "Remote Agent URL은 http:// 또는 https://로 시작해야 합니다." in sources
    assert "마지막 성공 데이터 표시 중" in sources
    assert "isLoopbackBaseUrl" in sources
    assert "looksLikeLoopbackUrl" in sources
    assert "ADB reverse/로컬 테스트용" in sources
    assert "PC 활성 세션" in sources
    assert "활성 모바일 세션" in sources


def test_android_usage_stats_ui_can_query_recent_foreground_app():
    sources = _android_sources()
    integration = _read(MAIN_SRC / "AndroidIntegration.kt")

    assert "recentUsage: AndroidUsageSnapshot?" in sources
    assert "androidIntegration.recentForegroundApp()" in sources
    assert "fun syncUsageStatsSessions()" in sources
    assert "activeUsageStatsMobileSessions()" in sources
    assert 'source = "usage_stats"' in sources
    assert "UsageSyncResult" in sources
    assert "Usage 동기화" in sources
    assert "최근 앱" in sources
    assert "최근 전면 앱" in sources
    assert "Usage Access 권한이 없거나 최근 전면 앱을 찾지 못했습니다." in sources
    assert "DEFAULT_USAGE_LOOKBACK_MILLIS" in integration
    assert "Context.USAGE_STATS_SERVICE" in integration
    assert "events.hasNextEvent()" in integration
    assert "events.getNextEvent(event)" in integration


def test_android_docs_track_current_parity_plan_and_verification():
    readme = _read(ANDROID_ROOT / "README.md")
    guide = _read(Path("docs/remote/setup-guide.md"))
    design = _read(Path("docs/remote/android-client-design.md"))
    root_readme = _read(Path("README.md"))

    for marker in [
        "Full-parity",
        "Android Keystore",
        "build-tools;35.0.0",
        "platforms;android-36",
        "내부 테스트 → 실기기 테스트",
        "tools/verify_android_internal.py",
        "tools/verify_android_device.py",
        "adb reverse",
    ]:
        assert marker in readme

    for marker in [
        "HomeworkHelper Remote Client Setup Guide",
        "Remote Agent",
        "Android Keystore",
        "docs/remote/android-client-design.md",
        "tools/verify_remote_controller.py",
        "tools/verify_android_internal.py",
        "tools/verify_android_device.py",
        "adb reverse",
    ]:
        assert marker in guide

    for marker in [
        "Android Remote Client Full-Parity Design",
        "Full-parity matrix",
        "RemoteAppViewModel",
        "RemoteRepository",
        "UsageStats",
        "Tailscale",
        "two automated stages",
        "Stage 1 — Internal tests",
        "Stage 2 — Physical-device automated tests",
        "tools/verify_android_internal.py",
        "tools/verify_android_device.py",
        "adb reverse",
    ]:
        assert marker in design

    assert "docs/remote/setup-guide.md" in root_readme
    assert "docs/remote/android-client-design.md" in root_readme
    assert "remote_clients/android/HomeworkHelperRemote/README.md" in root_readme

    for stale in [
        "No space left on device",
        "docs/remote-controller/setup-guide.md",
        "remote-controller-todo.md",
        "remote-controller-work-report.md",
        "remote-controller-completion-audit.md",
    ]:
        assert stale not in readme
        assert stale not in guide
        assert stale not in design

    for obsolete_path in [
        Path("docs/remote-controller/setup-guide.md"),
        Path("docs/remote/archive/remote-controller-todo.md"),
        Path("docs/remote/archive/remote-controller-work-report.md"),
        Path("docs/remote/archive/remote-controller-completion-audit.md"),
        Path("docs/remote/archive/remote-controller-technical-review.md"),
        Path("docs/remote/connectivity-automation-live-check.md"),
        Path("docs/remote/macos-client-test-tutorial.md"),
        Path("macos-client-regression-checklist.md"),
        Path("macos26-liquid-glass-upgrade-plan.md"),
    ]:
        assert not obsolete_path.exists()


def test_android_two_stage_verification_scripts_are_the_primary_entrypoints():
    internal = _read(Path("tools/verify_android_internal.py"))
    device = _read(Path("tools/verify_android_device.py"))
    e2e = _read(Path("tools/smoke_android_remote_e2e.py"))

    for marker in [
        "tests/test_remote_android_client_static.py",
        "tools/check_android_sdk_readiness.py",
        ":app:assembleDebug",
        "tools/check_android_apk_artifact.py",
        "Android internal verification passed",
    ]:
        assert marker in internal

    for marker in [
        "tools/smoke_android_remote_controller.py",
        "--report-usage-access",
        "tools/smoke_android_remote_e2e.py",
        "--adb-reverse",
        "--android-base-url",
        "http://127.0.0.1:{args.port}",
        "Android physical-device verification passed",
    ]:
        assert marker in device

    for marker in [
        "--android-base-url",
        "--host-bind",
        "--adb-reverse",
        "reverse",
        "Remote Agent URL",
        "_replace_text",
        "android_base_url",
    ]:
        assert marker in e2e
