from pathlib import Path
import xml.etree.ElementTree as ET


ANDROID_ROOT = Path("remote_clients/android/HomeworkHelperRemote")
MAIN_SRC = ANDROID_ROOT / "app/src/main/java/dev/homeworkhelper/remote"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


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
        "remote/processes/$id/launch",
        "remote/shortcuts/$id/open",
    ]:
        assert endpoint in api_client

    assert 'setRequestProperty("Authorization", "Bearer $bearerToken")' in api_client
    assert 'optString("name", item.optString("device_name"))' in api_client
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
    assert 'item.optString("token_refreshed_at")' in api_client
    assert 'fun dashboardSummary(): RemoteDashboardSummary' in api_client
    assert 'fun gameLinks(): List<RemoteGameLink>' in api_client
    assert 'fun createGameLink(processId: String, androidPackageName: String' in api_client
    assert 'fun startMobileSession(gameLinkId: String, source: String = "manual", startedAtSeconds: Double? = null)' in api_client
    assert 'body.put("started_at", startedAtSeconds)' in api_client
    assert 'fun endMobileSession(sessionId: String)' in api_client
    assert 'fun activeMobileSessions(): List<RemoteMobileSession>' in api_client
    assert 'json.getJSONArray("links")' in api_client
    assert 'item.optString("android_package_name")' in api_client
    assert 'fun beholderIncidents(): List<RemoteBeholderIncident>' in api_client
    assert 'item.optString("user_title")' in api_client
    assert 'item.optJSONArray("risk_labels")?.toStringList().orEmpty()' in api_client
    assert 'metrics.optDouble("daily_average_seconds")' in api_client
    assert 'metrics.optJSONObject("top_game")' in api_client
    assert 'json.optJSONObject("mobile_metrics")' in api_client
    assert 'mobileMetrics?.optDouble("total_seconds")' in api_client
    assert 'mobileMetrics?.optInt("active_session_count")' in api_client
    assert 'mobileTopGame?.optString("android_package_name")' in api_client
    assert 'optJSONArray("supported_actions")?.toStringSet().orEmpty()' in api_client
    assert 'targetHost = it.optString("target_host")' in api_client
    assert 'fun powerConfig(): RemotePowerConfigResponse' in api_client
    assert 'fun savePowerConfig(config: RemotePowerConfigPayload)' in api_client
    assert 'put("remote/power/config", body)' in api_client
    assert 'toPowerConfigResponse()' in api_client


def test_android_token_storage_uses_keystore_not_plaintext_preferences():
    token_store = _read(MAIN_SRC / "AndroidTokenStore.kt")
    preferences = _read(MAIN_SRC / "RemotePreferences.kt")
    main_activity = _read(MAIN_SRC / "MainActivity.kt")

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
    assert "tokenStore.saveToken(token)" in main_activity
    assert "preferences.clearLegacyToken()" in main_activity
    assert "토큰 삭제" in main_activity


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


def test_android_power_ui_uses_remote_power_capabilities_to_disable_actions():
    main_activity = _read(MAIN_SRC / "MainActivity.kt")
    models = _read(MAIN_SRC / "RemoteModels.kt")

    assert "fun isPowerActionEnabled(action: String): Boolean" in models
    assert "!powerControl || !currentPower.configured" in models
    assert "currentPower.supportedActions.contains(action)" in models
    assert "fun powerCommand(action: String)" in main_activity
    assert "status?.isPowerActionEnabled(action) == true" in main_activity
    assert "전원 제어 adapter가 설정되지" in main_activity
    assert 'enabled = isPowerActionEnabled("wake")' in main_activity
    assert 'enabled = isPowerActionEnabled("sleep")' in main_activity
    assert 'enabled = isPowerActionEnabled("restart")' in main_activity
    assert 'enabled = isPowerActionEnabled("shutdown")' in main_activity
    assert "지원 명령" in main_activity
    assert "전원 상태" in main_activity
    assert "전원 설정" in main_activity
    assert "전원 설정 저장" in main_activity
    assert "fun savePowerConfig()" in main_activity
    assert "플레이 요약" in main_activity
    assert "dashboardSummary" in main_activity
    assert "모바일 플레이" in main_activity
    assert "mobileSessionCount" in models
    assert "Beholder 알림" in main_activity
    assert "beholderIncidents" in main_activity
    assert "Android-PC 연결" in main_activity
    assert "gameLinks" in main_activity
    assert "Android 실행" in main_activity
    assert "모바일 시작" in main_activity
    assert "모바일 종료" in main_activity
    assert "fun startMobileSession(link: RemoteGameLink)" in main_activity
    assert "fun endMobileSession(session: RemoteMobileSession)" in main_activity
    assert "fun createGameLink()" in main_activity
    assert "Android-PC 연결 저장" in main_activity
    assert "gameLinkPackageName" in main_activity
    assert "fun refreshToken()" in main_activity
    assert "토큰 갱신" in main_activity
    assert "formatDuration" in main_activity


def test_android_usage_stats_ui_can_query_recent_foreground_app():
    main_activity = _read(MAIN_SRC / "MainActivity.kt")
    integration = _read(MAIN_SRC / "AndroidIntegration.kt")

    assert "var recentUsage by remember" in main_activity
    assert "androidIntegration.recentForegroundApp()" in main_activity
    assert "fun syncUsageStatsSessions()" in main_activity
    assert "activeUsageStatsMobileSessions()" in main_activity
    assert 'source = "usage_stats"' in main_activity
    assert "UsageSyncResult" in main_activity
    assert "Usage 동기화" in main_activity
    assert "최근 앱" in main_activity
    assert "최근 전면 앱" in main_activity
    assert "Usage Access 권한이 없거나 최근 전면 앱을 찾지 못했습니다." in main_activity
    assert "DEFAULT_USAGE_LOOKBACK_MILLIS" in integration
    assert "Context.USAGE_STATS_SERVICE" in integration
    assert "events.hasNextEvent()" in integration
    assert "events.getNextEvent(event)" in integration


def test_android_docs_pin_current_sdk_build_and_device_blocker():
    readme = _read(ANDROID_ROOT / "README.md")
    guide = _read(Path("docs/remote-controller/setup-guide.md"))
    todo = _read(Path("remote-controller-todo.md"))

    assert "Android SDK license" in readme
    assert "BUILD SUCCESSFUL" in readme
    assert "adb device/emulator" in readme
    assert 'build-tools;35.0.0' in readme
    assert 'platforms;android-36' in readme
    assert "Android Keystore" in guide
    assert "--require-branch dev-remote" in guide
    assert "--expect-main-hash 4052da3" in guide
    assert "--allow-android-device-blocker" in guide
    assert "usage_stats` 자동 세션 sync" in guide
    assert "game-link package Intent 실행 및 UsageStats 자동 세션 전환 smoke test" in readme
    assert "PC 게임과 Android package/deeplink 매칭 데이터 모델 추가" not in readme
    assert "[x] Android SDK License 수락 후 SDK platform/build-tools 설치" in todo
    assert "연결된 Android 기기 또는 emulator 확보" in todo
    assert "Android token 저장소를 Keystore 암호화 저장으로 교체" in todo
