from pathlib import Path


MACOS_ROOT = Path("remote_clients/macos/HomeworkHelperRemote")
SOURCE_ROOT = MACOS_ROOT / "Sources/HomeworkHelperRemote"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_macos_package_keeps_native_swiftui_executable_contract():
    package = _read(MACOS_ROOT / "Package.swift")
    app = _read(SOURCE_ROOT / "HomeworkHelperRemoteApp.swift")
    packager = _read(Path("tools/package_macos_remote_app.py"))

    assert 'name: "HomeworkHelperRemote"' in package
    assert 'platforms: [.macOS("26.0")]' in package
    assert '.macOS(.v13)' not in package
    assert '.executableTarget(' in package
    assert 'path: "Sources/HomeworkHelperRemote"' in package
    assert 'import SwiftUI' in app
    assert '@main' in app
    assert 'struct HomeworkHelperRemoteApp: App' in app
    assert '"LSUIElement": True' in packager


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
        'case state',
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
        'userCycleHours = "user_cycle_hours"',
        'staminaTrackingEnabled = "stamina_tracking_enabled"',
        'iconURL = "icon_url"',
        'iconURLs = "icon_urls"',
        'resourceIconURLs = "resource_icon_urls"',
        'remainingSeconds = "remaining_seconds"',
        'readyAt = "ready_at"',
        'staminaUpdatedAt = "stamina_updated_at"',
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
    assert "static func defaultSession(requestTimeout: TimeInterval = 5, resourceTimeout: TimeInterval = 8) -> URLSession" in client
    assert "configuration.timeoutIntervalForRequest = requestTimeout" in client
    assert "configuration.timeoutIntervalForResource = resourceTimeout" in client
    assert "configuration.waitsForConnectivity = false" in client
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
    assert 'final class InMemoryTokenStore: RemoteTokenStore' in keychain


def test_macos_popover_first_ui_preserves_remote_capabilities_contract():
    app = _read(SOURCE_ROOT / "HomeworkHelperRemoteApp.swift")
    view_model = _read(SOURCE_ROOT / "RemoteDashboardViewModel.swift")
    ui_test_flags = _read(SOURCE_ROOT / "RemoteUITestFlags.swift")
    window_accessor = _read(SOURCE_ROOT / "RemoteWindowAccessor.swift")
    liquid_glass = _read(SOURCE_ROOT / "RemoteLiquidGlass.swift")
    models = _read(SOURCE_ROOT / "RemoteModels.swift")
    cache = _read(SOURCE_ROOT / "RemoteClientCache.swift")
    supervisor = _read(SOURCE_ROOT / "RemoteConnectionSupervisor.swift")
    tailscale = _read(SOURCE_ROOT / "TailscaleDiscovery.swift")
    local_ssh = _read(SOURCE_ROOT / "LocalSSHPowerManager.swift")

    assert "RemoteDashboardViewModel(" in app
    assert "bootstrapEnabled: !RemoteUITestFlags.skipExternalState" in app
    assert 'InMemoryTokenStore(initialToken: "ui-test-token")' in app
    assert "NSStatusItem" in app
    assert "statusItem(withLength: NSStatusItem.squareLength)" in app
    assert "statusItemClicked(_ sender: Any?)" in app
    assert "sendAction(on: [.leftMouseDown])" in app
    assert "installStatusItemClickMonitor()" in app
    assert "event.window === button.window" in app
    assert "clickStatusItemForUITest()" in app
    assert "NSApp.activate(ignoringOtherApps: true)" in app
    assert "NSPopover" in app
    assert "RemoteMenuBarPopoverPanel" not in app
    assert "MenuBarPopoverView" in app
    assert "RemoteAppDelegate.showPrimaryInterface" not in app  # reopen is delegate-owned, not menu-owned
    assert "showPopoverFromStatusItem()" in app
    assert "popover.contentSize = currentPopoverContentSize()" in app
    assert "popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)" in app
    assert "popover.behavior = .transient" in app
    assert "RemotePlaceholderWindowAccessor" in app
    assert "schedulePlaceholderHide()" in app
    assert "Window(RemoteAppDelegate.placeholderWindowTitle, id: RemoteAppDelegate.placeholderWindowIdentifier)" in app
    scene_source = app.split("var body: some Scene", 1)[1].split("Settings {", 1)[0]
    assert "RemoteDashboardView(viewModel" not in scene_source
    assert "SidebarCommands()" not in scene_source
    assert "homeworkHelperRemoteToggleSidebar" not in scene_source
    assert "showMainWindow:" not in app
    assert "창 열기" not in app
    assert "창 숨기기" not in app
    assert ".keyboardShortcut(\"r\", modifiers: .command)" in app
    assert ".keyboardShortcut(\",\", modifiers: .command)" in app
    assert "RemoteAppDelegate.openSettingsWindow()" in app
    assert "RemoteSettingsOpenBridge" in app
    assert "@Environment(\\.openSettings)" in app
    assert "homeworkHelperRemoteOpenSettings" in app
    assert "NotificationCenter.default.post(name: .homeworkHelperRemoteOpenSettings" in app
    assert "openSettings()" in app
    assert 'Selector(("showSettingsWindow:"))' in app
    assert 'Selector(("showPreferencesWindow:"))' in app

    assert "GlassEffectContainer" in app
    assert "RemoteAppKitLiquidGlassBackground" in liquid_glass
    assert "RemoteGlassBackground" not in app
    assert "NSVisualEffectView" not in window_accessor
    assert "NSGlassEffectView" in liquid_glass
    assert "NSGlassEffectContainerView" in liquid_glass
    assert "glassEffect" in liquid_glass
    assert "enum RemotePopoverGlassTransparency" in liquid_glass
    assert "case standard" in liquid_glass
    assert "case high" in liquid_glass
    assert "return Glass.regular" in liquid_glass
    assert "return Glass.clear" in liquid_glass
    assert "variant: Glass? = nil" in liquid_glass
    assert "GroupBox(" not in app.replace("RemoteGlassGroupBox", "")
    assert ".thinMaterial" not in app

    assert "RemotePopoverLayout" in app
    assert "static let minWidth: CGFloat = 380" in app
    assert "static let maxWidth: CGFloat = 560" in app
    assert "static let gameIconSize: CGFloat = 34" in app
    assert "static let gameTileCornerRadius: CGFloat = 10" in app
    assert "static let progressBadgeWidth: CGFloat = 132 * 0.90" in app
    assert "static let progressMeterHeight: CGFloat = 12" in app
    assert "static let todayBadgeWidth: CGFloat = 16" in app
    assert "static let statusBadgeSpacing: CGFloat = 4" in app
    assert "let progressStatusClusterWidth = progressBadgeWidth + statusBadgeSpacing + todayBadgeWidth" in app
    assert "static func contentWidth(processes: [RemoteProcess])" in app
    assert "ForEach(viewModel.processes)" in app
    assert "viewModel.processes.prefix(5)" not in app
    assert "외 \\(viewModel.processes.count - 5)개" not in app
    assert "MenuBarGameRow(process: process, viewModel: viewModel)" in app
    assert "Task { await viewModel.launch(process) }" in app
    assert "MenuBarLaunchButton" in app
    assert 'Image(systemName: "play.fill")' in app
    assert ".frame(width: RemotePopoverLayout.gameIconSize, height: RemotePopoverLayout.gameIconSize)" in app
    assert ".buttonStyle(.plain)" in app
    assert "MenuBarHoverTintModifier" in app
    assert ".menuBarHoverTint()" in app
    assert "MenuBarGameStatusBadges" in app
    assert "MenuBarProgressBadge" in app
    assert "MenuBarProgressMeter(progress: progress)" in app
    row_source = app.split("struct MenuBarGameRow", 1)[1].split("struct MenuBarLaunchButton", 1)[0]
    assert "ProgressView(" not in row_source
    assert ".truncationMode(.tail)" in row_source
    progress_meter_source = app.split("struct MenuBarProgressMeter", 1)[1].split("struct MenuBarProgressBadge", 1)[0]
    assert "progressTone" not in progress_meter_source
    assert "Color.accentColor.opacity(0.72)" in progress_meter_source
    assert "Color.accentColor.opacity(0.08)" in progress_meter_source
    progress_badge_source = app.split("struct MenuBarProgressBadge", 1)[1].split("struct MenuBarGameStatusBadges", 1)[0]
    assert "MenuBarProgressVisuals.progressTone(percentage: progress.percentage)" in progress_badge_source
    assert "Text(MenuBarProgressVisuals.percentageText(progress.percentage))" in app
    assert "MenuBarProgressVisuals.progressTone(percentage: progress.percentage)" in app
    assert "(0x44, 0xcc, 0x44)" in app
    assert "(0xff, 0x44, 0x44)" in app
    running_badge_source = app.split("struct MenuBarRunningBadge", 1)[1].split("struct MenuBarProgressBadge", 1)[0]
    assert 'Text("실행 중")' in running_badge_source
    assert ".frame(width: RemotePopoverLayout.progressBadgeWidth, alignment: .center)" in running_badge_source
    status_badges_source = app.split("struct MenuBarGameStatusBadges", 1)[1].split("struct HostStatusPill", 1)[0]
    assert "if viewModel.isProcessRunningCurrent(process)" in status_badges_source
    assert "MenuBarRunningBadge()" in status_badges_source
    assert "} else if let progress {" in status_badges_source
    assert 'Text("실행 중")' not in status_badges_source
    assert 'Text("실행 중")' in app
    assert 'checkmark.circle.fill' in app
    assert ".frame(width: RemotePopoverLayout.progressBadgeWidth, alignment: .center)" in app
    assert ".frame(width: RemotePopoverLayout.todayBadgeWidth, alignment: .center)" in app
    assert ".fixedSize(horizontal: true, vertical: false)" in app
    assert "MenuBarProgressBadge(progress: progress, viewModel: viewModel)" in app
    assert "func menuBarSuppressFocusRing() -> some View" in app
    assert "focusable(false)" in app
    assert ".menuBarSuppressFocusRing()" in app
    assert 'Label("페어링 필요 · 설정 열기", systemImage: "link.badge.plus")' in app
    assert 'MenuBarPowerButton(action: "wake", label: "전원 켜기"' in app
    assert 'MenuBarPowerButton(action: "shutdown", label: "시스템 종료"' in app
    assert 'MenuBarFooterButton(title: "설정", systemImage: "gearshape")' in app
    assert 'MenuBarFooterButton(title: "새로고침", systemImage: "arrow.clockwise")' in app
    assert 'MenuBarFooterButton(title: "앱 종료", systemImage: "power")' in app
    assert ".labelStyle(.iconOnly)" in app  # still used where icon-only is intentional

    assert "Settings {" in app
    assert "RemoteSettingsView" in app
    assert "RemoteSettingsTab" in app
    assert "TabView(selection: $selectedTab)" in app
    assert 'Label("연결", systemImage: "link")' in app
    assert 'Label("전원", systemImage: "bolt")' in app
    assert 'Label("기기", systemImage: "display.2")' in app
    assert 'Label("Android", systemImage: "app.connected.to.app.below.fill")' in app
    assert 'Label("앱", systemImage: "gearshape")' in app
    assert "RemoteSettingsContentSizePreferenceKey" in app
    assert "RemoteSettingsLayout" in app
    assert "RemoteSettingsSection" in app
    assert "static let contentWidth: CGFloat = 392" in app
    assert "static let maxWindowWidth: CGFloat = 480" in app
    assert "measured.width * 1.06" in app
    assert "measured.height * 1.10" in app
    assert "SettingsActionGrid" in app
    assert ".padding(RemoteSettingsLayout.tabPadding)" in app
    assert "RemoteSettingsWindowAccessor(targetSize: targetSize)" in app
    assert "RemoteSettingsKeyboardShortcutBridge" in app
    assert "event.keyCode == 53" in window_accessor
    assert "isCommandReturn" in window_accessor
    assert "!self.isEditingText(in: window)" in window_accessor
    assert "상태 동기화 주기" in app
    assert "$viewModel.mirrorPollIntervalSeconds" in app
    assert "in: 1...60" in app
    assert "기본값은 5초" in app
    assert "mirrorPollIntervalSecondsKey" in view_model
    assert "loadMirrorPollIntervalSeconds" in view_model
    assert "saveMirrorPollIntervalSeconds" in view_model
    assert "popoverGlassTransparencyKey" in view_model
    assert "remote.popoverGlassTransparency" in view_model
    assert "loadPopoverGlassTransparency" in view_model
    assert "savePopoverGlassTransparency" in view_model
    assert "@Published var popoverGlassTransparency" in view_model
    assert 'Picker("Popover 투명도", selection: $viewModel.popoverGlassTransparency)' in app
    assert "ForEach(RemotePopoverGlassTransparency.allCases)" in app
    assert ".remoteGlass(.popover, variant: viewModel.popoverGlassTransparency.glass)" in app
    assert "RemoteHostAvailabilityState" in supervisor
    assert "case agentUnavailable" in supervisor
    assert 'case .agentUnavailable: return "서버 응답 없음"' in supervisor
    assert "RemoteConnectionSupervisor" in supervisor
    assert "RemoteConnectionDecision" in supervisor
    assert "RemoteConnectionEvent" in supervisor
    assert "RemoteConnectionFailureKind" in supervisor
    assert "case clientResumed" in supervisor
    assert "shouldForcePayloadSync" in supervisor
    assert "shouldProbeImmediately" in supervisor
    assert "hostAvailabilityState" in view_model
    assert "private enum HostReachability" in view_model
    assert "probeHostReachability(for: client)" in view_model
    assert "markHostUnreachable" in view_model
    assert "supervisorDecision(_ event: RemoteConnectionEvent)" in view_model
    assert "applyConnectionDecision(_ decision: RemoteConnectionDecision" in view_model
    assert "installClientResumeObservers" in view_model
    assert "NSWorkspace.didWakeNotification" in view_model
    assert "NSApplication.didBecomeActiveNotification" in view_model
    assert "handleClientResumed" in view_model
    assert "isLikelyTailscaleHost" in view_model
    assert 'host.hasSuffix(".ts.net")' in view_model
    assert "parts[0] == 100 && (64...127).contains(parts[1])" in view_model
    assert "localTailscale?.peers.contains" in view_model
    assert "TailscaleDiscovery.ping(host: host, timeoutSeconds: 2)" in view_model
    assert "private func nextMirrorDelaySeconds() -> UInt64" in view_model
    assert "static let wakeReconnectSchedule" in supervisor
    assert "connectionLossReconnectSchedule" in supervisor
    assert "호스트가 계속 응답하지 않습니다" in supervisor
    assert "서버 응답 없음 상태로 전환했습니다" in supervisor
    assert "Array(repeating: UInt64(1), count: 15)" in supervisor
    assert "Array(repeating: UInt64(2), count: 15)" in supervisor
    assert "Array(repeating: UInt64(5), count: 24)" in supervisor
    assert "beginPowerTransition(for: action)" in view_model
    assert "setHostAvailability(state, clearPairingRecovery: decision.shouldClearPairingRecovery)" in view_model
    assert "authRejected" in view_model
    assert "return NSApp.isActive ? 5 : 15" not in view_model

    assert "연결/페어링" in app
    assert "6자리 코드" in app
    assert "페어링 및 자동 설정" in app
    assert "자동 설정 점검" in app
    assert "서버 Tailscale 확인/복구" in app
    assert "페어링 토큰 복구" in app
    assert "로컬 토큰 삭제" in app
    assert "Tailscale 서버/호스트 탐색" in app
    assert "전원/SSH/SmartThings" in app
    assert "전원 설정 저장" in app
    assert "기기 관리" in app
    assert "현재 토큰 갱신" in app
    assert "Android-PC 연결" in app
    assert "로그인 시 실행" in app
    assert "로그인 자동 실행 시 창 표시" in app
    assert "플레이 요약 표시" in app
    assert "비 HoYoLab 진행률 표시" in app
    assert "Popover 투명도" in app
    assert "메뉴바 아이콘" in app

    assert "RemoteClientPreferences" in view_model
    assert "UserDefaults.standard" in view_model
    assert '"HH_REMOTE_PREFS_SUITE"' in view_model
    assert "UserDefaults(suiteName: suite)" in view_model
    assert "func bootstrap() async" in view_model
    assert "func startMirroring()" in view_model
    assert "latestStatus.stateRevision != lastStateRevision" in view_model
    assert "handleRemoteFailure(error)" in view_model
    assert "private actor RemoteDashboardService" in view_model
    assert "Keep refreshes sequential" in view_model
    assert "func isPowerActionEnabled(_ action: String) -> Bool" in view_model
    assert "func isProcessRunningCurrent(_ process: RemoteProcess) -> Bool" in view_model
    assert "func isLaunchEnabled(_ process: RemoteProcess) -> Bool" in view_model
    assert "func processStatusText(_ process: RemoteProcess) -> String" in view_model
    assert "status.capabilities.powerControl" in view_model
    assert "status.power?.configured == true" in view_model
    assert "status.supportedPowerActions" in view_model
    assert "disconnectingPowerActions" in view_model
    assert "static let acceptedMarker" in local_ssh
    assert "static func command(for action: String)" in local_ssh
    assert "cmd /C" in local_ssh
    assert "shutdown /s /t 0 && echo" in local_ssh
    assert "rundll32.exe powrprof.dll,SetSuspendState" in local_ssh
    assert "combined.contains(Self.acceptedMarker)" in local_ssh
    assert "!viewModel.isPowerActionEnabled(action)" in app
    assert "!viewModel.isLaunchEnabled(process)" in app
    assert "viewModel.processStatusText(process)" in app
    assert "func launch(_ process: RemoteProcess) async" in view_model
    assert "func power(_ action: String) async" in view_model
    assert "func confirmPairing() async" in view_model
    assert "func recoverPairing" in view_model
    assert "func refreshToken() async" in view_model
    assert "func saveRemoteDesktopLogging" in view_model
    assert "runSetupAutomation" in view_model
    assert "ensureServerTailscale" in view_model
    assert "applySuggestedPowerHost" in view_model
    assert "generateAndSendSSHKey" in view_model
    assert "probeSmartThingsDevices" in view_model
    assert "refreshPowerSetup" in view_model
    assert "applySmartThingsDevice" in view_model

    assert "GameProgressView" in app
    assert "GameIconView" in app
    assert "ResourceIconView" in app
    assert "ProgressView(value: min(max(progress.percentage, 0), 100), total: 100)" in app
    assert "resourceIconURL" in models
    assert "cachedResourceIconURL" in cache
    assert 'private static let iconCacheVersion = "v3_pixels"' in cache
    assert '"HH_REMOTE_CACHE_DIR"' in cache
    assert 'private static var cacheDirectoryOverride' in cache
    assert 'ProcessInfo.processInfo.environment[cacheDirectoryOverrideKey]' in cache
    assert 'isSmokeOnlySnapshot' in cache
    assert 'processes.first?.id == "smoke-game"' in cache
    assert '"HH_REMOTE_CACHE_DIR": str(temp_dir / "remote-client-cache")' in _read(Path("tools/smoke_macos_remote_viewmodel.py"))
    assert '"HH_REMOTE_PREFS_SUITE": f"dev.homeworkhelper.remote.smoke.{os.getpid()}"' in _read(Path("tools/smoke_macos_remote_viewmodel.py"))
    assert "REMOTE_CONNECTION_SUPERVISOR" in _read(Path("tools/smoke_macos_remote_viewmodel.py"))
    assert "tools/smoke_macos_connection_supervisor.py" in _read(Path("tests/test_remote_verifier_contract.py"))
    assert "_assert_production_cache_unchanged" in _read(Path("tools/smoke_macos_remote_viewmodel.py"))
    assert "_production_process_cache_path" in _read(Path("tools/smoke_macos_remote_viewmodel.py"))
    assert 'viewModel.powerConfig.sshKeyPath = "__SMOKE_SSH_KEY__"' in _read(Path("tools/smoke_macos_remote_viewmodel.py"))
    assert 'viewModel.powerConfig.smartthingsCLIPath = "__SMARTTHINGS_CLI__"' in _read(Path("tools/smoke_macos_remote_viewmodel.py"))
    assert 'smoke_ssh_key = temp_dir / "smoke_ssh" / "homeworkhelper_remote_ed25519"' in _read(Path("tools/smoke_macos_remote_viewmodel.py"))
    assert "validatedCachedURL" in cache
    assert "decodedPixelDimension(data) >= preferredSize" in cache
    assert "displayThumbnailImage" in cache
    assert "displayScale()" in cache
    assert "func displayIconImage" in view_model
    assert "func displayResourceIconImage" in view_model
    assert "viewModel.displayIconImage" in app
    assert "viewModel.displayResourceIconImage" in app
    assert "RemoteClientCache.loadProcesses" in view_model
    assert "RemoteClientCache.saveProcesses" in view_model
    assert "RemoteClientCache.cacheIcons" in view_model
    assert "CycleProgressDisplayMode" in view_model
    assert "progressDisplayText" in view_model
    assert "startLocalProgressTicker" in view_model
    assert "processWithLocalProgress" in view_model
    assert "staminaRecoverySecondsPerPoint" in view_model
    assert "formatRemainingDuration" in view_model
    assert "LocalTailscalePingResult" in tailscale
    assert '["ping", "--timeout=\\(max(1, timeoutSeconds))s", trimmedHost]' in tailscale
    for marker in ["어제", "오늘", "내일", "일 전", "일 후", "아침", "낮", "저녁", "밤"]:
        assert marker in view_model

    assert "dashboardSummary" in view_model
    assert "mobileMetrics" in app
    assert "formatDuration" in app
    assert "Beholder 알림" in app
    assert "beholderIncidents" in app
    assert "gameLinks" in view_model
    assert "mobileSessions" in view_model
    assert "func startMobileSession(_ link: RemoteGameLink) async" in view_model
    assert "func endMobileSession(_ session: RemoteMobileSession) async" in view_model
    assert "func createGameLink() async" in view_model
    assert "RemoteLoginItemManager" in view_model
    assert "RemoteMenuBarIconChoice" in view_model
    assert "gamecontroller.fill" in view_model
    assert "NSApp.currentEvent?.clickCount" not in app
    assert "popover.performClose(nil)" in app
    assert "window.orderOut(nil)" in app
    assert ".close()" not in app
    assert "--ui-test-show-popover" in ui_test_flags
    assert "HH_REMOTE_SHOW_POPOVER" in ui_test_flags
    assert "--ui-test-click-status-item" in ui_test_flags
    assert "HH_REMOTE_CLICK_STATUS_ITEM" in ui_test_flags
    assert "--ui-test-open-settings" in ui_test_flags
    assert "HH_REMOTE_OPEN_SETTINGS" in ui_test_flags
    assert "showUITestPopoverWindow" in app
    assert "--ui-test-no-external-state" in ui_test_flags
    assert "HH_REMOTE_NO_EXTERNAL_STATE" in ui_test_flags
