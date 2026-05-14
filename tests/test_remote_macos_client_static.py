from pathlib import Path


MACOS_ROOT = Path("remote_clients/macos/HomeworkHelperRemote")
SOURCE_ROOT = MACOS_ROOT / "Sources/HomeworkHelperRemote"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_macos_package_keeps_native_swiftui_executable_contract():
    package = _read(MACOS_ROOT / "Package.swift")
    app = _read(SOURCE_ROOT / "HomeworkHelperRemoteApp.swift")

    assert 'name: "HomeworkHelperRemote"' in package
    assert 'platforms: [.macOS(.v13)]' in package
    assert '.executableTarget(' in package
    assert 'path: "Sources/HomeworkHelperRemote"' in package
    assert 'import SwiftUI' in app
    assert '@main' in app
    assert 'struct HomeworkHelperRemoteApp: App' in app


def test_macos_models_track_remote_agent_snake_case_contract():
    models = _read(SOURCE_ROOT / "RemoteModels.swift")

    for model_name in [
        "RemoteStatus",
        "RemoteProcess",
        "RemoteShortcut",
        "RemoteCommandResult",
        "PairingConfirmResponse",
        "RemoteDevice",
        "RemoteDevicesResponse",
        "RemoteCapabilitiesResponse",
        "RemotePowerConfigPayload",
        "RemotePowerConfigResponse",
        "RemotePowerSetupResponse",
        "RemoteSSHKeyRegistrationResponse",
        "RemoteSmartThingsDevicesResponse",
        "RemoteSmartThingsDeviceCandidate",
        "RemoteReadiness",
        "RemoteGameLink",
        "RemoteGameLinksResponse",
        "RemoteMobileSession",
        "RemoteMobileSessionsResponse",
        "RemoteDashboardSummary",
        "RemoteBeholderIncident",
        "RemoteBeholderIncidentsResponse",
        "RevokeDeviceResponse",
        "RemoteTailscalePeer",
        "RemoteTailscaleSnapshot",
        "RemoteTailscaleEnsureResponse",
    ]:
        assert f"struct {model_name}" in models

    assert "struct Power: Decodable" in models
    assert "let readiness: RemoteReadiness?" in models
    assert "struct Metrics: Decodable" in models
    assert "struct Game: Decodable" in models
    assert "struct MobileMetrics: Decodable" in models
    assert "let power: Power?" in models
    assert "var supportedPowerActions: Set<String>" in models

    for coding_key in [
        'activeSessions = "active_sessions"',
        'processLaunch = "process_launch"',
        'shortcutOpen = "shortcut_open"',
        'dashboardSummary = "dashboard_summary"',
        'beholderIncidents = "beholder_incidents"',
        'gameLinks = "game_links"',
        'mobileSessions = "mobile_sessions"',
        'powerConfig = "power_config"',
        'powerControl = "power_control"',
        'authRequired = "auth_required"',
        'supportedActions = "supported_actions"',
        'targetHost = "target_host"',
        'smartthingsDeviceID = "smartthings_device_id"',
        'smartthingsCLIPath = "smartthings_cli_path"',
        'sshHost = "ssh_host"',
        'sshPort = "ssh_port"',
        'sshUser = "ssh_user"',
        'sshKeyPath = "ssh_key_path"',
        'statusTimeoutSeconds = "status_timeout_seconds"',
        'configPath = "config_path"',
        'configExists = "config_exists"',
        'wakeConfigured = "wake_configured"',
        'sshConfigured = "ssh_configured"',
        'remoteAPIVersion = "remote_api_version"',
        'serverTime = "server_time"',
        'monitoringPath = "monitoring_path"',
        'launchPath = "launch_path"',
        'preferredLaunchType = "preferred_launch_type"',
        'targetID = "target_id"',
        'targetName = "target_name"',
        'createdAt = "created_at"',
        'lastSeenAt = "last_seen_at"',
        'pcProcessID = "pc_process_id"',
        'pcDisplayName = "pc_display_name"',
        'androidPackageName = "android_package_name"',
        'androidLaunchIntentURI = "android_launch_intent_uri"',
        'androidStoreURL = "android_store_url"',
        'platformAccountHint = "platform_account_hint"',
        'hoyolabGameID = "hoyolab_game_id"',
        'syncStrategy = "sync_strategy"',
        'gameLinkID = "game_link_id"',
        'startedAt = "started_at"',
        'durationSeconds = "duration_seconds"',
        'mobileMetrics = "mobile_metrics"',
        'activeSeconds = "active_seconds"',
        'activeSessionCount = "active_session_count"',
        'sourceBreakdown = "source_breakdown"',
        'tokenRefreshedAt = "token_refreshed_at"',
        'revokedAt = "revoked_at"',
        'deviceID = "device_id"',
        'dailyAverageSeconds = "daily_average_seconds"',
        'totalSeconds = "total_seconds"',
        'topGame = "top_game"',
        'displayName = "display_name"',
        'userTitle = "user_title"',
        'riskLabels = "risk_labels"',
        'riskScore = "risk_score"',
    ]:
        assert coding_key in models


def test_macos_api_client_tracks_remote_agent_endpoints_and_auth():
    client = _read(SOURCE_ROOT / "RemoteAPIClient.swift")

    for endpoint in [
        'remote/status',
        'remote/capabilities',
        'remote/readiness',
        'remote/dashboard/summary',
        'remote/beholder/incidents',
        'remote/game-links',
        'remote/mobile-sessions/active',
        'remote/mobile-sessions/start',
        'remote/mobile-sessions/end',
        'remote/processes',
        'remote/shortcuts',
        'remote/power/\\(action)',
        'remote/power/config',
        'remote/power/setup',
        'remote/power/ssh-key',
        'remote/power/smartthings/devices',
        'remote/pair/confirm',
        'remote/tokens/refresh',
        'remote/logging/config',
        'remote/devices/revoked',
        'remote/tailscale/ensure',
        'remote/devices',
        'remote/processes/\\(id)/launch',
        'remote/shortcuts/\\(id)/open',
        'remote/devices/\\(id)',
    ]:
        assert endpoint in client

    assert 'request.setValue("Bearer \\(bearerToken)", forHTTPHeaderField: "Authorization")' in client
    assert 'request.setValue("application/json", forHTTPHeaderField: "Content-Type")' in client
    assert 'func gameLinks() async throws -> [RemoteGameLink]' in client
    assert 'func createGameLink(processID: String, androidPackageName: String' in client
    assert 'func startMobileSession(gameLinkID: String' in client
    assert 'func endMobileSession(sessionID: String)' in client
    assert 'func activeMobileSessions() async throws -> [RemoteMobileSession]' in client
    assert 'func powerConfig() async throws -> RemotePowerConfigResponse' in client
    assert 'func savePowerConfig(_ config: RemotePowerConfigPayload)' in client
    assert 'func powerSetup() async throws -> RemotePowerSetupResponse' in client
    assert 'func registerPowerSSHKey(publicKey: String, label: String)' in client
    assert 'func smartThingsDevices(cliPath: String?)' in client
    assert 'func ensureServerTailscale() async throws -> RemoteTailscaleEnsureResponse' in client
    assert 'request(path: path, method: "PUT")' in client
    assert 'URLSession(configuration: .ephemeral, delegate: nil, delegateQueue: OperationQueue())' in client
    assert 'let path = http.url?.path ?? "unknown endpoint"' in client
    assert 'RemoteAPIError.http(status: http.statusCode, message: "\\(path): \\(message)")' in client


def test_macos_keychain_store_uses_service_and_account_boundaries():
    keychain = _read(SOURCE_ROOT / "KeychainTokenStore.swift")

    assert 'import Security' in keychain
    assert 'kSecClassGenericPassword' in keychain
    assert 'kSecAttrService as String: service' in keychain
    assert 'kSecAttrAccount as String: account' in keychain
    assert 'dev.homeworkhelper.remote' in keychain
    assert 'remote-api-token' in keychain
    assert 'SecItemAdd' in keychain
    assert 'SecItemUpdate' in keychain
    assert 'SecItemDelete' in keychain
    assert 'protocol RemoteTokenStore' in keychain
    assert 'struct KeychainTokenStore: RemoteTokenStore' in keychain


def test_macos_power_ui_uses_remote_power_capabilities_to_disable_actions():
    app = _read(SOURCE_ROOT / "HomeworkHelperRemoteApp.swift")
    view_model = _read(SOURCE_ROOT / "RemoteDashboardViewModel.swift")

    assert "RemoteDashboardViewModel()" in app
    assert "RemoteClientPreferences" in view_model
    assert "UserDefaults.standard" in view_model
    assert "func bootstrap() async" in view_model
    assert ".frame(minWidth: 1100, minHeight: 680)" in app
    assert "ScrollView {" in app
    assert "GroupBox(\"Remote Agent\")" in app
    assert ".navigationSplitViewColumnWidth(min: 360, ideal: 420, max: 520)" in app
    assert "struct SidebarInfoRow: View" in app
    assert "http://windows-host-or-tailnet-ip:8000" in app
    assert "페어링 후 Keychain에 저장됩니다" in app
    assert "6자리 코드" in app
    assert "페어링 및 자동 설정" in app
    assert "private actor RemoteDashboardService" in view_model
    assert "Keep refreshes sequential" in view_model
    assert "func isPowerActionEnabled(_ action: String) -> Bool" in view_model
    assert "status.capabilities.powerControl" in view_model
    assert "status.power?.configured == true" in view_model
    assert "status.supportedPowerActions" in view_model
    assert "!viewModel.isPowerActionEnabled(action)" in app
    assert "전원 제어 adapter가 설정되지" in view_model
    assert "지원 명령" in app
    assert "전원 상태" in app
    assert "전원 설정" in app
    assert "전원 설정 저장" in app
    assert "Tailscale 찾기" in app
    assert "ensureReady" in _read(SOURCE_ROOT / "TailscaleDiscovery.swift")
    assert "pkgs.tailscale.com/stable/?v=latest" in _read(SOURCE_ROOT / "TailscaleDiscovery.swift")
    assert "ReadinessPill" in app
    assert "savePowerConfig" in view_model
    assert "플레이 요약" in app
    assert "dashboardSummary" in view_model
    assert "모바일 플레이" in app
    assert "mobileMetrics" in app
    assert "formatDuration" in app
    assert "Beholder 알림" in app
    assert "beholderIncidents" in app
    assert "Android-PC 연결" in app
    assert "모바일 세션은 수동 시작/종료와 Android UsageStats sync 흐름에 사용됩니다." in app
    assert "모바일 세션 sync는 후속 단계에서 연결합니다." not in app
    assert "gameLinks" in view_model
    assert "mobileSessions" in view_model
    assert "func startMobileSession(_ link: RemoteGameLink) async" in view_model
    assert "func endMobileSession(_ session: RemoteMobileSession) async" in view_model
    assert "func createGameLink() async" in view_model
    assert "연결 저장" in app
    assert "gameLinkAndroidPackage" in view_model
    assert "func refreshToken() async" in view_model
    assert "현재 토큰 갱신" in app
    assert "원격 설정 자동화" in app
    assert "6자리 PIN" in app
    assert "Windows에서 먼저" in app
    assert "이 Mac에서" in app
    assert "SetupInstructionBlock" in app
    assert "viewModel.bootstrap()" in app
    assert "자동 설정 점검" in app
    assert "서버 Tailscale 확인/복구" in app
    assert "페어링 토큰 복구" in app
    assert "로컬 토큰 삭제" in app
    assert "SetupChecklistRow" in app
    assert "runSetupAutomation" in view_model
    assert "ensureServerTailscale" in view_model
    assert "applySuggestedPowerHost" in view_model
    assert "serverTailscaleEnsure" in view_model
    assert "setupChecklist" in view_model
    assert "connectionGuidance" in view_model
    assert "hostConnectionState" in view_model
    assert "RemoteClientPreferences.loadPowerConfig" in view_model
    assert "remoteDesktopLoggingEnabled" in view_model
    assert "saveRemoteDesktopLogging" in view_model
    assert "purgeRevokedDevices" in view_model
    assert "func localWake() async" in view_model
    assert "powerConfig.localWakeConfigured" in view_model
    assert "completePairingOnboarding" in view_model
    assert "PIN 1회 입력으로 가능한 원격 연결 설정을 자동 완료했습니다." in view_model
    assert "func recoverPairing" in view_model
    assert "func clearLocalPairing" in view_model
    assert "pairingRecoveryMessage" in view_model
    assert "저장된 Keychain 토큰으로 자동 연결했습니다." in view_model
    assert "SSH host 채우기" in app
    assert "Windows 전원 준비" in app
    assert "준비 상태 확인" in app
    assert "SSH key 생성/전송" in app
    assert "SmartThings 기기 확인" in app
    assert "LocalSSHKeyManager" in _read(SOURCE_ROOT / "LocalSSHKeyManager.swift")
    assert "LocalPowerWakeManager" in _read(SOURCE_ROOT / "LocalPowerWakeManager.swift")
    assert "smartThingsCLICandidates" in _read(SOURCE_ROOT / "LocalPowerWakeManager.swift")
    assert "probeDevices" in _read(SOURCE_ROOT / "LocalPowerWakeManager.swift")
    assert "SmartThingsJSONDevice" in _read(SOURCE_ROOT / "LocalPowerWakeManager.swift")
    assert "hostSafeForRemoteSave" in _read(SOURCE_ROOT / "RemoteModels.swift")
    assert "preservingLocalWake" in _read(SOURCE_ROOT / "RemoteModels.swift")
    assert "applyHostPowerConfig" in view_model
    assert 'if action == "wake", powerConfig.localWakeConfigured' in view_model
    assert "power.smartthings.local_devices" in view_model
    assert "LocalPowerWakeManager.isLocalSmartThingsCLIPath" in view_model
    assert "devices:commands" in _read(SOURCE_ROOT / "LocalPowerWakeManager.swift")
    assert "ssh-keygen" in _read(SOURCE_ROOT / "LocalSSHKeyManager.swift")
    assert "generateAndSendSSHKey" in view_model
    assert "probeSmartThingsDevices" in view_model
    assert "refreshPowerSetup" in view_model
    assert "smartThingsDeviceCandidates" in view_model
    assert "applySmartThingsDevice" in view_model
    assert "SmartThings device 후보" in app
    assert "호스트 서버가 꺼져 있거나 Remote Agent에 연결할 수 없습니다." in app
    assert "원격 진단 로그를 바탕 화면에 저장" in app
    assert "폐기된 기기 정리" in app
