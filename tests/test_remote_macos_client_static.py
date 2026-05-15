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
        'stateRevision = "state_revision"',
        'updatedAt = "updated_at"',
        'monitoringPath = "monitoring_path"',
        'launchPath = "launch_path"',
        'preferredLaunchType = "preferred_launch_type"',
        'iconURL = "icon_url"',
        'iconURLs = "icon_urls"',
        'resourceIconURLs = "resource_icon_urls"',
        'remainingSeconds = "remaining_seconds"',
        'readyAt = "ready_at"',
        'isRunning = "is_running"',
        'playedToday = "played_today"',
        'statusText = "status_text"',
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
        'remote/processes/\\(pathSegment(id))/launch',
        'remote/shortcuts/\\(id)/open',
        'remote/devices/\\(id)',
    ]:
        assert endpoint in client

    assert 'request.setValue("Bearer \\(bearerToken)", forHTTPHeaderField: "Authorization")' in client
    assert "private func pathSegment(_ value: String)" in client
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
    window_accessor = _read(SOURCE_ROOT / "RemoteWindowAccessor.swift")
    assert "RemoteWindowLayout.contentSize" in app
    assert "RemoteWindowLayout.maxWindowSize" in window_accessor
    assert "NSScreen.main?.visibleFrame" in window_accessor
    assert "compactWindowHeight" in window_accessor
    assert "window.minSize = size" in window_accessor
    assert ".windowResizability(.contentSize)" in app
    assert "RemoteWindowAccessor" in app
    assert "RemoteGlassBackground" in app
    assert "NSVisualEffectView" in window_accessor
    assert "window.isOpaque = false" in window_accessor
    assert "ScrollView {" in app
    assert "GroupBox(\"연결\")" in app
    assert "NavigationSplitView" not in app
    assert "@State private var sidebarVisible = false" in app
    assert ".homeworkHelperRemoteMainWindowWillShow" in app
    assert ".onAppear { sidebarVisible = false }" in app
    assert "NotificationCenter.default.publisher(for: .homeworkHelperRemoteMainWindowWillShow)" in app
    assert "sidebarVisible.toggle()" in app
    assert "struct SidebarInfoRow: View" in app
    assert "http://windows-tailnet-ip:8000" in app
    assert "페어링 후에는 토큰/기기 관리 항목을 기본 화면에서 숨깁니다." in app
    assert "6자리 코드" in app
    assert "페어링 및 자동 설정" in app
    assert "Settings {" in app
    assert "RemoteSettingsView" in app
    assert "TabView" in app
    assert 'Label("연결", systemImage: "link")' in app
    assert 'Label("전원", systemImage: "bolt")' in app
    assert 'Label("기기", systemImage: "display.2")' in app
    assert 'Label("Android", systemImage: "app.connected.to.app.below.fill")' in app
    assert 'Label("앱", systemImage: "gearshape")' in app
    assert "struct SettingsOpenButton: View" in app
    assert "SettingsLink" in app
    assert 'Selector(("showSettingsWindow:"))' in app
    assert 'Selector(("showPreferencesWindow:"))' in app
    assert "AdvancedRemoteSettingsView" in app
    assert "GameProgressView" in app
    assert "RemoteGameCard" in app
    assert "GameIconView" in app
    assert "DraggableHorizontalScrollView" in app
    assert "hasHorizontalScroller = false" in app
    assert "mouseDragged" in app
    assert "gameViewportWidth(cardCount:" in app
    assert "ProgressView(value: min(max(progress.percentage, 0), 100), total: 100)" in app
    assert "GroupBox(\"상태\")" not in app
    assert 'Label("새로고침", systemImage: "arrow.clockwise")' in app
    assert ".labelStyle(.iconOnly)" in app
    assert "Label(viewModel.isLoading ? \"연결 중...\" : \"새로고침\", systemImage: \"arrow.clockwise\")" not in app
    assert "ResourceIconView" in app
    assert "resourceIconURL" in _read(SOURCE_ROOT / "RemoteModels.swift")
    assert "cachedResourceIconURL" in _read(SOURCE_ROOT / "RemoteClientCache.swift")
    cache = _read(SOURCE_ROOT / "RemoteClientCache.swift")
    assert 'private static let iconCacheVersion = "v3_pixels"' in cache
    assert "validatedCachedURL" in cache
    assert "decodedPixelDimension(data) >= preferredSize" in cache
    assert "displayThumbnailImage" in cache
    assert "displayScale()" in cache
    assert "icon.diagnostic" in cache
    assert "display_point_size" in cache
    assert "let preferredSize = 256" in cache
    assert "let preferredSize = 128" in cache
    assert "func displayIconImage" in view_model
    assert "func displayResourceIconImage" in view_model
    assert "viewModel.displayIconImage" in app
    assert "viewModel.displayResourceIconImage" in app
    assert "displaySize: 24" in app
    assert "displaySize: 12" in app
    assert "RemoteClientCache.loadProcesses" in view_model
    assert "RemoteClientCache.saveProcesses" in view_model
    assert "RemoteClientCache.cacheIcons" in view_model
    assert "func startMirroring()" in view_model
    assert "latestStatus.stateRevision != lastStateRevision" in view_model
    assert "return NSApp.isActive ? 5 : 15" in view_model
    assert "if self.consecutiveMirrorFailures > 0 { return 60 }" in view_model
    assert "private actor RemoteDashboardService" in view_model
    assert "Keep refreshes sequential" in view_model
    assert "func isPowerActionEnabled(_ action: String) -> Bool" in view_model
    assert "status.capabilities.powerControl" in view_model
    assert "status.power?.configured == true" in view_model
    assert "status.supportedPowerActions" in view_model
    assert "!viewModel.isPowerActionEnabled(action)" in app
    assert "전원 제어 adapter가 설정되지" in view_model
    assert "지원 명령" in app
    assert "PC 전원" in app
    assert "PowerSquareButton" in app
    assert "전원 설정" in app
    assert "전원/SSH/SmartThings" in app
    assert "전원 설정 저장" in app
    assert "Tailscale 서버/호스트 탐색" in app
    assert 'Label("탐색", systemImage: "network")' not in app
    assert "ensureReady" in _read(SOURCE_ROOT / "TailscaleDiscovery.swift")
    assert "pkgs.tailscale.com/stable/?v=latest" in _read(SOURCE_ROOT / "TailscaleDiscovery.swift")
    assert "ReadinessPill" in app
    assert "savePowerConfig" in view_model
    assert "플레이 요약" in app
    assert "플레이 요약 표시" in app
    assert "showPlaySummary" in view_model
    assert "viewModel.showPlaySummary && viewModel.dashboardSummary != nil" in app
    assert "static let compactWindowHeight: CGFloat = 312" in window_accessor
    assert "height: min(maxSize.height, max(compactWindowHeight, rawHeight))" in window_accessor
    assert "게임 실행, 진행률, 전원 제어를 빠르게 확인합니다." not in app
    assert "homeworkHelperRemoteToggleSidebar" in app
    assert "homeworkHelperRemoteRefreshRequested" in app
    assert ".onExitCommand" in app
    assert "hideMainWindow()" in app
    assert "CommandMenu(\"원격\")" in app
    command_menu_source = app.split("CommandMenu(\"원격\")", 1)[1].split("Settings {", 1)[0]
    assert "if #available(macOS 14.0, *)" in command_menu_source
    assert "SettingsLink" in command_menu_source
    assert command_menu_source.index("SettingsLink") < command_menu_source.index("RemoteAppDelegate.openSettingsWindow()")
    assert ".keyboardShortcut(\"r\", modifiers: .command)" in app
    assert ".keyboardShortcut(\"s\", modifiers: [.command, .shift])" in app
    assert ".keyboardShortcut(\"w\", modifiers: .command)" in app
    assert ".keyboardShortcut(\",\", modifiers: .command)" in app
    assert "비 HoYoLab 진행률 표시" in app
    assert "CycleProgressDisplayMode" in view_model
    assert "cycleProgressDisplayMode" in view_model
    assert "progressDisplayText" in view_model
    for marker in ["어제", "오늘", "내일", "일 전", "일 후", "아침", "낮", "저녁", "밤"]:
        assert marker in view_model
    assert "dateFormat" not in view_model
    assert "viewModel.progressDisplayText(progress)" in app
    assert "dashboardSummary" in view_model
    assert "모바일 플레이" in app
    assert "mobileMetrics" in app
    assert "formatDuration" in app
    assert "Beholder 알림" in app
    assert "beholderIncidents" in app
    assert "Android-PC 연결" in app
    assert "Android 클라이언트가 준비될 때 사용할 매핑입니다." in app
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
    assert "기기 관리" in app
    assert "연결/페어링" in app
    assert "SetupInstructionBlock" in app
    assert "viewModel.bootstrap()" in app
    assert "자동 설정 점검" in app
    assert "서버 Tailscale 확인/복구" in app
    assert "페어링 토큰 복구" in app
    assert "로컬 토큰 삭제" in app
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
    confirm_pairing_source = view_model.split("func confirmPairing() async", 1)[1].split("func refreshToken() async", 1)[0]
    assert 'pairingRecoveryMessage = ""' in confirm_pairing_source
    assert 'pairingRecoveryMessage = "페어링 완료' not in confirm_pairing_source
    assert "message = \"'\\(response.name)' 디바이스 페어링 및 자동 설정을 완료했습니다.\"" in confirm_pairing_source
    assert "func recoverPairing" in view_model
    recover_pairing_source = view_model.split("func recoverPairing", 1)[1].split("func clearLocalPairing", 1)[0]
    assert "refreshToken()" not in recover_pairing_source
    assert 'tokenText = ""' not in recover_pairing_source
    assert "저장된 토큰 확인에 실패했습니다" in recover_pairing_source
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
    assert "localSSHConfigured" in _read(SOURCE_ROOT / "RemoteModels.swift")
    assert "applyHostPowerConfig" in view_model
    assert "fillDefaultSSHFields" in view_model
    assert "powerSetup?.user" in view_model
    assert "LocalSSHKeyManager.defaultPrivateKeyPath" in view_model
    assert 'if action == "wake", powerConfig.localWakeConfigured' in view_model
    assert "LocalSSHPowerManager" in _read(SOURCE_ROOT / "LocalSSHPowerManager.swift")
    assert "power.local_ssh" in view_model
    assert "power.click" in view_model
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
    assert "기본 화면에서는 숨깁니다." in app
    assert "원격 진단 로그를 바탕 화면에 저장" in app
    assert "폐기된 기기 정리" in app
    assert "NSStatusItem" in app
    assert "MenuBarPopoverView" in app
    assert ".interpolation(.high)" in app
    assert ".antialiased(true)" in app
    assert ".minimumScaleFactor(0.68)" in app
    assert ".allowsTightening(true)" in app
    assert "gamecontroller.fill" in view_model
    assert "로그인 시 실행" in app
    assert "로그인 자동 실행 시 창 표시" in app
    assert "메뉴바 아이콘" in app
    assert "RemoteMenuBarIconChoice" in view_model
    assert "NSApp.currentEvent?.clickCount" not in app
    assert "popover.performClose(nil)" in app
    assert "HomeworkHelperRemoteMainWindow" in _read(SOURCE_ROOT / "RemoteWindowAccessor.swift")
    assert "HostStatusPill" in app
    assert 'Label("창 열기", systemImage: "macwindow")' in app
    assert 'Label("새로고침", systemImage: "arrow.clockwise")' in app
    assert 'Label("앱 종료", systemImage: "power")' in app
    assert "HStack(spacing: 8)" in app
    assert "외 \\(viewModel.processes.count - 5)개" in app
    assert "RemoteLoginItemManager" in view_model
