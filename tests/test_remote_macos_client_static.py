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
    assert "struct Diagnostics: Decodable" in models
    assert "let readiness: RemoteReadiness?" in models
    assert "struct Metrics: Decodable" in models
    assert "struct Game: Decodable" in models
    assert "struct MobileMetrics: Decodable" in models
    assert "let power: Power?" in models
    assert "let diagnostics: Diagnostics?" in models

    for coding_key in [
        'activeSessions = "active_sessions"',
        'processLaunch = "process_launch"',
        'processStop = "process_stop"',
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
        'remoteAPIVersion = "remote_api_version"',
        'serverTime = "server_time"',
        'stateRevision = "state_revision"',
        'updatedAt = "updated_at"',
        'durationMS = "duration_ms"',
        'monitoringPath = "monitoring_path"',
        'launchPath = "launch_path"',
        'preferredLaunchType = "preferred_launch_type"',
        'userCycleHours = "user_cycle_hours"',
        'schemaVersion = "schema_version"',
        'baseValue = "base_value"',
        'maxValue = "max_value"',
        'baseTimestamp = "base_timestamp"',
        'recoverySecondsPerUnit = "recovery_seconds_per_unit"',
        'fullRecoverySeconds = "full_recovery_seconds"',
        'cycleSeconds = "cycle_seconds"',
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
        'commandID = "command_id"',
        'acceptedAt = "accepted_at"',
        'refreshAfterMS = "refresh_after_ms"',
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
        'tailnetIP = "tailnet_ip"',
        'tailnetHostname = "tailnet_hostname"',
        'tailnetOS = "tailnet_os"',
        'pairingStatus = "pairing_status"',
        'connectivityState = "connectivity_state"',
        'healthMessage = "health_message"',
        'canRevoke = "can_revoke"',
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
        'remote/power/setup',
        'remote/power/ssh-key',
        'remote/pair/confirm',
        'remote/tokens/refresh',
        'remote/logging/config',
        'remote/devices/revoked',
        'remote/tailscale/ensure',
        'remote/devices',
        'remote/processes/\\(pathSegment(id))/launch',
        'remote/processes/\\(pathSegment(id))/stop',
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
    assert 'func stopProcess(id: String) async throws -> RemoteCommandResult' in client
    assert 'func powerSetup() async throws -> RemotePowerSetupResponse' in client
    assert 'func registerPowerSSHKey(publicKey: String, label: String)' in client
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


def test_macos_client_tailnet_device_management_is_read_only_and_self_sorted():
    app = _read(SOURCE_ROOT / "HomeworkHelperRemoteApp.swift")
    view_model = _read(SOURCE_ROOT / "RemoteDashboardViewModel.swift")

    assert 'private static let pairedDeviceIDKey = "remote.pairedDeviceID"' in view_model
    assert "rememberPairedDeviceID(response.id)" in view_model
    clear_local_pairing = view_model[
        view_model.index("func clearLocalPairing()") : view_model.index("private func preservePairingAfterAuthRejected")
    ]
    auth_rejected_pairing = view_model[
        view_model.index("private func preservePairingAfterAuthRejected") : view_model.index("private func rememberPairedDeviceID")
    ]
    assert 'RemoteClientPreferences.savePairedDeviceID("")' in clear_local_pairing
    assert "tokenStore.delete()" in clear_local_pairing
    assert "preservePairingAfterAuthRejected(error" in view_model
    assert "clearPairingAfterHostRevocation" not in view_model
    assert 'RemoteClientPreferences.savePairedDeviceID("")' not in auth_rejected_pairing
    assert "pairedDeviceID = \"\"" not in auth_rejected_pairing
    assert "tokenStore.delete()" not in auth_rejected_pairing
    assert "tokenText = \"\"" not in auth_rejected_pairing
    assert "devices = []" not in auth_rejected_pairing
    assert "로컬 토큰과 페어링 캐시는 보존" in view_model
    assert "token_present" in view_model
    assert "paired_device_id_present" in view_model
    assert "token_persisted" in view_model
    assert "pairingTokenStatusDisplay" in view_model
    assert "pairedDeviceIDDisplay" in view_model
    assert "var sortedDevices: [RemoteDevice]" in view_model
    assert "func isCurrentDevice(_ device: RemoteDevice) -> Bool" in view_model
    assert 'if device.role == "host" { return 2 }' in view_model
    assert "func canManageRemoteDevices(_ device: RemoteDevice? = nil) -> Bool" in view_model
    assert "false" in view_model[view_model.index("func canManageRemoteDevices") : view_model.index("var displayProcesses")]
    assert "ForEach(viewModel.sortedDevices)" in app
    assert "기기 목록을 읽기 전용으로 표시합니다" in app
    assert "Windows Host 원격 설정에서만 수행" in app
    assert "viewModel.devicePairingDisplay(device)" in app
    assert "viewModel.deviceConnectivityDisplay(device)" in app
    assert "viewModel.purgeRevokedDevices" not in app
    assert "viewModel.revoke(device)" not in app


def test_macos_popover_first_ui_preserves_remote_capabilities_contract():
    app = _read(SOURCE_ROOT / "HomeworkHelperRemoteApp.swift")
    view_model = _read(SOURCE_ROOT / "RemoteDashboardViewModel.swift")
    ui_test_flags = _read(SOURCE_ROOT / "RemoteUITestFlags.swift")
    window_accessor = _read(SOURCE_ROOT / "RemoteWindowAccessor.swift")
    liquid_glass = _read(SOURCE_ROOT / "RemoteLiquidGlass.swift")
    models = _read(SOURCE_ROOT / "RemoteModels.swift")
    cache = _read(SOURCE_ROOT / "RemoteClientCache.swift")
    supervisor = _read(SOURCE_ROOT / "RemoteConnectionSupervisor.swift")
    smart_poll = _read(SOURCE_ROOT / "RemoteSmartPollController.swift")
    tailscale = _read(SOURCE_ROOT / "TailscaleDiscovery.swift")
    local_ssh = _read(SOURCE_ROOT / "LocalSSHPowerManager.swift")
    local_power = _read(SOURCE_ROOT / "LocalPowerWakeManager.swift")
    local_moonlight = _read(SOURCE_ROOT / "LocalMoonlightManager.swift")
    global_shortcut = _read(SOURCE_ROOT / "RemoteGlobalShortcutRegistrar.swift")
    packager = _read(Path("tools/package_macos_remote_app.py"))

    assert "RemoteDashboardViewModel(" in app
    assert "bootstrapEnabled: !RemoteUITestFlags.skipExternalState" in app
    assert 'InMemoryTokenStore(initialToken: "ui-test-token")' in app
    assert "NSStatusItem" in app
    assert "statusItem(withLength: NSStatusItem.squareLength)" in app
    assert "image.isTemplate = true" in app
    assert "statusItemImage" not in app
    assert "image.isTemplate = false" not in app
    assert "menuBarPresentationState()" in view_model
    assert "RemoteMenuBarPresentationState" in view_model
    assert "menuBarIconSymbol(for state: RemoteMenuBarPresentationState)" in view_model
    assert "homeworkHelperRemoteMenuBarStatusDidChange" in app
    assert "homeworkHelperRemoteMenuBarIconDidChange" in app
    assert "homeworkHelperRemoteGlobalShortcutPressed" in app
    assert "installMoonlightStateObservers()" in app
    assert "NSWorkspace.didActivateApplicationNotification" in app
    assert "NSWorkspace.didLaunchApplicationNotification" in app
    assert "NSWorkspace.didTerminateApplicationNotification" in app
    assert "moonlightApplicationStateChanged" in app
    assert "app.bundleIdentifier == Self.moonlightBundleIdentifier" in app
    assert "statusItemClicked(_ sender: Any?)" in app
    assert "sendAction(on: [.leftMouseDown])" in app
    assert "installStatusItemClickMonitor()" in app
    assert "event.window === button.window" in app
    assert "scheduleStatusItemToggle(relativeTo: button)" in app
    assert "DispatchQueue.main.async { [weak self, weak button] in" in app
    assert "NSEvent.addGlobalMonitorForEvents(matching: [.leftMouseDown, .rightMouseDown])" in app
    assert "func applicationDidResignActive" in app
    assert "closePopoverForFocusLoss()" in app
    assert "func popoverDidClose" in app
    assert "removePopoverOutsideClickMonitor()" in app
    assert "focusPopoverWindow()" in app
    assert "window.makeKeyAndOrderFront(nil)" in app
    assert "clickStatusItemForUITest()" in app
    assert "NSApp.activate(ignoringOtherApps: true)" in app
    assert "NSApp.setActivationPolicy(.accessory)" in app
    assert "NSApp.setActivationPolicy(.regular)" not in app
    status_click_source = app.split("@objc func statusItemClicked", 1)[1].split("func clickStatusItemForUITest", 1)[0]
    show_popover_source = app.split("private func showPopoverFromStatusItem()", 1)[1].split("private func togglePopover", 1)[0]
    show_primary_source = app.split("static func showPrimaryInterface()", 1)[1].split("static func showUITestMainWindow", 1)[0]
    assert "openSettingsWindow" not in status_click_source
    assert "openSettingsWindow" not in show_popover_source
    assert "openSettingsWindow" not in show_primary_source
    assert "enum SettingsOpenSource" in app
    assert "case popoverButton" in app
    assert "case popoverShortcut" in app
    assert "case uiTest" in app
    settings_open_source = app.split("static func openSettingsWindow(source: SettingsOpenSource)", 1)[1].split("static func prepareSettingsWindow", 1)[0]
    assert "guard source == .uiTest || shared?.popover.isShown == true else { return }" in settings_open_source
    assert "beginExplicitSettingsOpen()" in settings_open_source
    assert "NSApp.setActivationPolicy(.accessory)" in settings_open_source
    assert "focusExistingSettingsWindow()" in settings_open_source
    assert "guard isExplicitSettingsOpenPending() else { return }" in settings_open_source
    assert "guard NSApp.windows.contains(where:" not in settings_open_source
    assert "static let settingsWindowIdentifier" in app
    assert "static let settingsWindowTitle" in app
    assert "static func prepareSettingsWindow(_ window: NSWindow)" in app
    assert "static func hideSettingsWindow(_ window: NSWindow?)" in app
    assert "restoreAccessoryIfNoVisibleUserWindows()" in app
    assert "private static func focusExistingSettingsWindow() -> Bool" in app
    assert "private static func settingsWindows() -> [NSWindow]" in app
    assert "private static func isVisibleUserWindow(_ window: NSWindow) -> Bool" in app
    assert "private static func beginExplicitSettingsOpen()" in app
    assert "private static func isExplicitSettingsOpenPending() -> Bool" in app
    assert "private static func clearExplicitSettingsOpen()" in app
    assert "installPopoverKeyDownMonitor()" in app
    assert "removePopoverKeyDownMonitor()" in app
    assert "event.keyCode == 43 && event.modifierFlags.contains(.command)" in app
    assert "openSettingsWindow(source: .popoverShortcut)" in app
    assert "NSPopover" in app
    assert "RemoteMenuBarPopoverPanel" not in app
    assert "MenuBarPopoverView" in app
    assert "RemoteAppDelegate.showPrimaryInterface" not in app  # reopen is delegate-owned, not menu-owned
    assert "showPopoverFromStatusItem()" in app
    assert "popover.contentSize = currentPopoverContentSize()" in app
    assert "popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)" in app
    show_popover_body = app.split("private func showPopover(relativeTo button: NSStatusBarButton)", 1)[1].split("private func focusPopoverWindow", 1)[0]
    assert "RemoteSharedModel.viewModel.refreshMoonlightSessionSnapshot()" in show_popover_body
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
    assert ".keyboardShortcut(\",\", modifiers: .command)" not in app
    assert 'Button("설정…")' not in app
    assert "CommandGroup(replacing: .appSettings)" in app
    assert "RemoteAppDelegate.openSettingsWindow()" not in app
    assert "RemoteAppDelegate.openSettingsWindow(source: .popoverButton)" in app
    assert "SettingsLink" not in app
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
    assert "ForEach(viewModel.displayProcesses)" in app
    assert "var displayProcesses: [RemoteProcess]" in view_model
    assert "static func sortedProcesses(_ processes: [RemoteProcess])" in view_model
    assert 'Locale(identifier: "ko_KR")' in view_model
    assert "viewModel.processes.prefix(5)" not in app
    assert "외 \\(viewModel.processes.count - 5)개" not in app
    assert "MenuBarGameRow(process: process, viewModel: viewModel)" in app
    assert "MenuBarGameStatusBadges(progress: process.progress, viewModel: viewModel)" in app
    assert "Task { await viewModel.launch(process) }" in app
    assert "MenuBarProcessActionButton" in app
    assert 'Image(systemName: isPending ? "hourglass" : style.icon)' in app
    assert "case stop" in app
    assert "Task { await viewModel.stop(process) }" in app
    assert "isPending: isRunningAction ? viewModel.isStopPending(process) : viewModel.isLaunchPending(process)" in app
    assert ".frame(width: RemotePopoverLayout.gameIconSize, height: RemotePopoverLayout.gameIconSize)" in app
    assert ".buttonStyle(.plain)" in app
    assert "MenuBarHoverTintModifier" in app
    assert ".menuBarHoverTint()" in app
    assert "MenuBarGameStatusBadges" in app
    assert "MenuBarProgressBadge" in app
    assert "MenuBarProgressMeter(progress: progress, viewModel: viewModel)" in app
    row_source = app.split("struct MenuBarGameRow", 1)[1].split("enum MenuBarProcessActionStyle", 1)[0]
    assert "ProgressView(" not in row_source
    assert ".truncationMode(.tail)" in row_source
    progress_meter_source = app.split("struct MenuBarProgressMeter", 1)[1].split("struct MenuBarProgressBadge", 1)[0]
    assert "progressTone" not in progress_meter_source
    assert "Color.accentColor.opacity(0.72)" in progress_meter_source
    assert "Color.accentColor.opacity(0.08)" in progress_meter_source
    assert "viewModel.progressMeterDisplayText(progress)" in progress_meter_source
    assert "MenuBarProgressVisuals.percentageText" not in progress_meter_source
    progress_badge_source = app.split("struct MenuBarProgressBadge", 1)[1].split("struct MenuBarGameStatusBadges", 1)[0]
    assert "MenuBarProgressVisuals.progressTone(percentage: progress.percentage)" in progress_badge_source
    assert "viewModel.trackBadgeDisplayText(progress)" in progress_badge_source
    assert "MenuBarProgressVisuals.progressTone(percentage: progress.percentage)" in app
    assert "Color(hue: hue, saturation: 0.76, brightness: 0.86)" in app
    assert "interpolatedColor" not in app
    assert "(0x44, 0xcc, 0x44)" not in app
    assert "(0xff, 0x44, 0x44)" not in app
    assert "struct MenuBarRunningBadge" not in app
    status_badges_source = app.split("struct MenuBarGameStatusBadges", 1)[1].split("struct HostStatusPill", 1)[0]
    assert "if let progress {" in status_badges_source
    assert "MenuBarRunningBadge()" not in status_badges_source
    assert "if viewModel.isProcessRunningCurrent(process)" not in status_badges_source
    assert 'Text("실행 중")' not in status_badges_source
    assert 'Text("실행 중")' not in app
    assert 'checkmark.circle.fill' not in app
    assert "runningOverlay" in app
    assert "playNeededDotOverlay" in app
    assert "if !process.playedToday" in app
    assert ".stroke(Color.green" in app
    assert ".fill(Color.red)" in app
    assert ".frame(width: RemotePopoverLayout.progressBadgeWidth, alignment: .center)" in app
    assert ".frame(width: RemotePopoverLayout.todayBadgeWidth, alignment: .center)" not in app
    assert ".fixedSize(horizontal: true, vertical: false)" in app
    assert "MenuBarProgressBadge(progress: progress, viewModel: viewModel)" in app
    assert "func menuBarSuppressFocusRing() -> some View" in app
    assert "focusable(false)" in app
    assert ".menuBarSuppressFocusRing()" in app
    assert 'Label("페어링 필요 · 설정 열기", systemImage: "link.badge.plus")' in app
    assert 'MenuBarPowerButton(action: "wake", label: "전원 켜기"' in app
    assert 'MenuBarPowerButton(action: "shutdown", label: "시스템 종료"' in app
    assert 'MenuBarFooterButton(title: "설정", systemImage: "gearshape")' in app
    assert "struct MenuBarCTAButton" in app
    assert "enum MenuBarCTAButtonLayout" in app
    assert "enum MenuBarCTAButtonTone" in app
    assert 'help: "새로고침"' in app
    assert 'layout: .iconOnly(width: 24, height: 22)' in app
    assert 'layout: .vertical(minHeight: 46)' in app
    assert 'tone: action == "shutdown" ? .destructive : .normal' in app
    assert 'MenuBarFooterButton(title: "앱 종료", systemImage: "power", tone: .destructive)' in app
    header_source = app.split("struct MenuBarPopoverView", 1)[1].split("VStack(alignment: .leading, spacing: 6)", 1)[0]
    assert 'Text("HomeworkHelper")' in header_source
    assert 'help: "새로고침"' in header_source
    assert header_source.index('Text("HomeworkHelper")') < header_source.index('help: "새로고침"') < header_source.index("Spacer()")
    assert "MenuBarMoonlightButton(viewModel: viewModel)" in app
    assert "struct MenuBarMoonlightButton" in app
    assert "viewModel.moonlightFooterButtonTitle" in app
    assert "viewModel.moonlightFooterButtonIcon" in app
    moonlight_button_source = app.split("struct MenuBarMoonlightButton", 1)[1].split("struct PlaySummaryView", 1)[0]
    assert "MenuBarCTAButton(" in moonlight_button_source
    assert "openSettingsWindow" not in header_source
    assert "openSettingsWindow" not in moonlight_button_source
    assert ".buttonStyle(.plain)" in app.split("struct MenuBarCTAButton", 1)[1].split("struct MenuBarPowerButton", 1)[0]
    assert ".menuBarHoverTint(disabled: disabled)" not in app.split("struct MenuBarMoonlightButton", 1)[1].split("struct PlaySummaryView", 1)[0]
    assert ".labelStyle(.iconOnly)" not in app

    assert "Settings {" in app
    assert "RemoteSettingsView" in app
    assert "RemoteSettingsTab" in app
    assert "TabView(selection: $selectedTab)" in app
    assert 'Label("연결", systemImage: "link")' in app
    assert 'Label("전원", systemImage: "bolt")' in app
    assert 'Label("기기", systemImage: "display.2")' in app
    assert 'Label("Moonlight", systemImage: "moon.stars")' in app
    assert 'Label("스케줄", systemImage: "calendar.badge.clock")' in app
    assert 'Label("Android", systemImage: "app.connected.to.app.below.fill")' not in app
    assert 'Label("앱", systemImage: "gearshape")' in app
    assert "RemoteSettingsContentSizePreferenceKey" in app
    assert "RemoteSettingsLayout" in app
    assert "RemoteSettingsSection" in app
    assert "static let controlWidth: CGFloat = 220" in app
    assert "struct SettingsControlRow" in app
    assert "struct SettingsToggleRow" in app
    assert ".frame(width: controlWidth, alignment: .trailing)" in app
    assert "SmartScheduleRuleEditor" in app
    assert "평일 스케줄 추가" in app
    assert "RemoteSmartScheduleRule" in view_model
    assert "remote.smartSchedule.rules" in view_model
    assert "startSmartScheduler()" in view_model
    assert "static let contentWidth: CGFloat = 392" in app
    assert "static let maxWindowWidth: CGFloat = 480" in app
    assert "measured.width * 1.06" in app
    assert "measured.height * 1.10" in app
    assert "SettingsActionGrid" in app
    assert ".toggleStyle(.switch)" in app
    assert 'SettingsToggleRow(title: "플레이 요약 표시", isOn: $viewModel.showPlaySummary)' in app
    assert 'SettingsToggleRow(title: "Popover 전역 단축키 사용", isOn: $viewModel.popoverGlobalShortcutEnabled)' in app
    assert 'SettingsControlRow("Moonlight host 선택")' in app
    assert 'SettingsControlRow("Moonlight 표시")' in app
    assert "MenuBarIconPickerRow(title: \"대기 상태 아이콘\", selection: $viewModel.menuBarIdleIconSymbol)" in app
    assert "MenuBarIconPickerRow(title: \"실행 중 아이콘\", selection: $viewModel.menuBarRunningIconSymbol)" in app
    assert "MenuBarIconPickerRow(title: \"오프라인/Standalone 아이콘\", selection: $viewModel.menuBarOfflineIconSymbol)" in app
    assert "struct MenuBarIconPickerRow" in app
    assert "SettingsControlRow(title)" in app
    assert ".padding(RemoteSettingsLayout.tabPadding)" in app
    assert "RemoteSettingsWindowAccessor(targetSize: targetSize)" in app
    assert "RemoteSettingsKeyboardShortcutBridge" in app
    assert "RemoteSettingsWindowDelegate" in window_accessor
    assert "RemoteAppDelegate.prepareSettingsWindow(window)" in window_accessor
    settings_window_accessor_source = window_accessor.split("struct RemoteSettingsWindowAccessor", 1)[1].split("struct RemoteSettingsKeyboardShortcutBridge", 1)[0]
    assert "makeKeyAndOrderFront" not in settings_window_accessor_source
    assert "orderFrontRegardless" not in settings_window_accessor_source
    assert "NSApp.activate" not in settings_window_accessor_source
    prepare_settings_source = app.split("static func prepareSettingsWindow(_ window: NSWindow)", 1)[1].split("static func hideSettingsWindow", 1)[0]
    assert "guard isExplicitSettingsOpenPending() else { return }" in prepare_settings_source
    assert "focusSettingsWindow(prepared)" in prepare_settings_source
    assert "RemoteAppDelegate.hideSettingsWindow(sender)" in window_accessor
    assert "RemoteAppDelegate.hideSettingsWindow(NSApp.keyWindow)" in app
    settings_keyboard_source = window_accessor.split("struct RemoteSettingsKeyboardShortcutBridge", 1)[1]
    assert "RemoteAppDelegate.hideSettingsWindow(window)" in settings_keyboard_source
    assert "window.orderOut(nil)" not in settings_keyboard_source
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
    assert 'SettingsControlRow("Popover 투명도")' in app
    assert 'Picker("", selection: $viewModel.popoverGlassTransparency)' in app
    assert "ForEach(RemotePopoverGlassTransparency.allCases)" in app
    assert ".remoteGlass(.popover, variant: viewModel.popoverGlassTransparency.glass)" in app
    assert "RemoteHostAvailabilityState" in supervisor
    assert "case agentUnavailable" in supervisor
    assert 'case .goingOffline: return "종료 대기 중"' in supervisor
    assert 'case .agentUnavailable: return "서버 응답 없음"' in supervisor
    assert "RemoteConnectionSupervisor" in supervisor
    assert "RemoteConnectionDecision" in supervisor
    assert "RemoteConnectionEvent" in supervisor
    assert "RemoteConnectionFailureKind" in supervisor
    assert "httpAgentUnavailable" in supervisor
    assert "case clientResumed" in supervisor
    assert "shouldForcePayloadSync" in supervisor
    assert "shouldProbeImmediately" in supervisor
    assert "hostAvailabilityState" in view_model
    assert "private enum HostReachability" in view_model
    assert "private enum TailnetManagementReachability" in view_model
    assert "private struct ConnectivityEvaluationLog" in view_model
    assert "writeConnectivityEvaluationLog" in view_model
    assert "guard remoteDesktopLoggingEnabled else { return }" in view_model
    assert '"connectivity.evaluate"' in view_model
    assert "bundle_release_id" in view_model
    assert "HHRemoteReleaseID" in view_model
    assert "HHRemoteGitHash" in view_model
    assert "bootstrapConnectionProgress" in view_model
    assert "private func evaluateConnectivity" in view_model
    assert 'trigger: "refresh"' in view_model
    assert 'trigger: "mirror"' in view_model
    assert "probeTailnetManagementReachability(for: client)" in view_model
    assert "LocalSSHPowerManager.health(config: powerConfig" in view_model
    assert "probeHostReachability(for: client)" in view_model
    assert "markHostUnreachable" in view_model
    assert "markHTTPAgentUnavailable" in view_model
    assert "applyReadiness(from status: RemoteStatus, using service: RemoteDashboardService)" in view_model
    assert "status.readiness == nil || status.readiness?.tailscaleReadiness.details == nil" in view_model
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
    assert "RemoteSmartPollController.steadyDelaySeconds" in view_model
    assert "enum RemotePayloadSyncScope" in smart_poll
    assert "launchChaseFallbackDelaysNanoseconds" in smart_poll
    assert "slowStatusThresholdMilliseconds" in smart_poll
    assert "appIsActive: NSApp.isActive" in view_model
    assert "unchangedRevisionPollCount" in view_model
    assert "slowStatusPollCount" in view_model
    assert "requestImmediateMirror(trigger:" in view_model
    assert 'trigger: "power.\\(action).accepted"' in view_model
    assert "runMirrorRemoteState(trigger:" in view_model
    assert "pendingMirrorRequest" in view_model
    assert "static let wakeReconnectSchedule" in supervisor
    assert "connectionLossReconnectSchedule" in supervisor
    assert "Remote Agent HTTP 첫 응답이 지연되고 있습니다" in supervisor
    assert "호스트 앱/API 서버가 굼뜨거나 DB 작업에 막혔을 수 있습니다" in supervisor
    assert "/api/gui/ping, /api/gui/health, /remote/status" in supervisor
    assert "Windows Remote Agent HTTP 첫 응답이 지연되고 있습니다" in view_model
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
    assert "페어링 토큰" in app
    assert "페어링 디바이스" in app
    assert "Bearer token" not in app
    assert "자동 설정 점검" in app
    assert "서버 Tailscale 확인/복구" in app
    assert "페어링 토큰 복구" in app
    assert "로컬 토큰 삭제" in app
    assert "Tailscale 서버/호스트 탐색" in app
    assert "전원 자동 설정" in app
    assert "전원 설정 저장" not in app
    assert "기기 관리" in app
    assert "현재 토큰 갱신" in app
    assert "Android-PC 연결" not in app
    assert "PC process ID" not in app
    assert "Android package" not in app
    assert "로그인 시 실행" in app
    assert "로그인 자동 실행 시 창 표시" not in app
    assert "loginLaunchShowsWindow" not in app
    assert "loginLaunchShowsWindow" not in view_model
    assert "loginLaunchShowsWindowKey" not in view_model
    assert "플레이 요약 표시" in app
    assert "비 HoYoLab 진행률 표시" in app
    assert "Popover 투명도" in app
    assert "메뉴바 아이콘" in app
    assert "Popover 전역 단축키 사용" in app
    assert "$viewModel.popoverGlobalShortcutEnabled" in app
    assert "globalShortcutStatusMessage" in app
    assert "popoverGlobalShortcutEnabledKey" in view_model
    assert "remote.popoverGlobalShortcutEnabled" in view_model
    assert "loadPopoverGlobalShortcutEnabled" in view_model
    assert "savePopoverGlobalShortcutEnabled" in view_model
    assert "updateGlobalShortcutRegistration" in view_model
    assert "RemoteGlobalShortcutRegistrar.shared.setEnabled" in view_model
    assert "import Carbon" in global_shortcut
    assert "RegisterEventHotKey" in global_shortcut
    assert "UnregisterEventHotKey" in global_shortcut
    assert "kVK_ANSI_G" in global_shortcut
    assert "cmdKey | optionKey" in global_shortcut
    assert "⌘⌥G" in global_shortcut
    assert "HomeworkHelperRemoteGlobalShortcutPressed" in global_shortcut
    assert "Moonlight 원격 플레이" in app
    assert "기존 Moonlight Desktop host가 HomeworkHelper host와 일치하면 설정을 수정하지 않고 그대로 사용합니다" in app
    assert "Moonlight 실행 버튼 연동" in app
    assert "$viewModel.moonlightBindingEnabled" in app
    assert "호스트 자동 깨우기 후 Moonlight 시작" not in app
    assert "$viewModel.moonlightAutoWakeBeforeStreamEnabled" not in app
    assert "손쉬운 사용" in app
    assert "viewModel.macAccessibilityPermissionDisplay" in app
    assert "viewModel.macAccessibilityPermissionGuidance" in app
    assert "viewModel.requestMacAccessibilityPermission()" in app
    assert "viewModel.openMacAccessibilitySettings()" in app
    assert "연동 상태" in app
    assert "Tailscale 등록 후보" in app
    assert "Pairing PIN" in app
    assert "Moonlight 설치" in app
    assert "Tailscale Direct로 등록" in app
    assert "Moonlight 설정 다시 읽기" in app
    assert "호스트 공인 IP 갱신" in app
    assert "viewModel.moonlightPublicIPDisplay" in app
    assert "viewModel.moonlightStalePublicIPWarning" in app
    assert "준비된 Desktop 세션은 popover에서 바로 실행합니다" in app
    assert "viewModel.moonlightSnapshot.readiness.label" in app
    assert "$viewModel.selectedMoonlightHostUUID" in app
    assert "viewModel.moonlightSelectableHosts" in app
    assert "LocalMoonlightManager" in local_moonlight
    assert "com.moonlight-stream.Moonlight" in local_moonlight
    assert "HH_REMOTE_MOONLIGHT_APP_PATHS" in local_moonlight
    assert "HH_REMOTE_MOONLIGHT_PREFS_PATH" in local_moonlight
    assert "HH_REMOTE_MOONLIGHT_IGNORE_RUNNING_APPS" in local_moonlight
    assert "com.moonlight-stream.Moonlight.plist" in local_moonlight
    assert '"hosts.size"' in local_moonlight
    assert 'let prefix = "hosts.\\(index)"' in local_moonlight
    assert '"\\(prefix).hostname"' in local_moonlight
    assert '"\\(prefix).uuid"' in local_moonlight
    assert 'prefix: "\\(prefix).apps"' in local_moonlight
    assert 'caseInsensitiveCompare("Desktop")' in local_moonlight
    assert "targetHostArgument" in local_moonlight
    assert "needsTailscaleRegistration" in local_moonlight
    assert "LocalMoonlightCommandResult" in local_moonlight
    assert "LocalMoonlightSessionSnapshot" in local_moonlight
    assert "desktopStreamProcessCount" in local_moonlight
    assert "hasFocusedApplication" in local_moonlight
    assert "apps.contains { $0.isActive }" in local_moonlight
    assert "hasDesktopStreamSession" in local_moonlight
    assert "isDesktopStreamVisible" in local_moonlight
    assert "hasDesktopSession" in local_moonlight
    assert "hasDesktopStreamSession || isVisible" in local_moonlight
    assert "targetHostArgument: String? = nil" in local_moonlight
    assert "processCommandLine(pid:" in local_moonlight
    assert "commandLineIndicatesDesktopStream" in local_moonlight
    assert "installViaHomebrew" in local_moonlight
    assert '["install", "--cask", "moonlight"]' in local_moonlight
    assert "static func pair(host: String, pin: String" in local_moonlight
    assert 'arguments: ["pair", trimmedHost, "--pin", trimmedPin]' in local_moonlight
    assert "static func listApps(host: String" in local_moonlight
    assert 'arguments: ["list", trimmedHost]' in local_moonlight
    assert "static func startDesktopStream" in local_moonlight
    assert 'arguments = ["stream", trimmedHost, appName]' in local_moonlight
    assert "static func quit(host: String" in local_moonlight
    assert 'arguments: ["quit", trimmedHost]' in local_moonlight
    assert "static func focusAndMoveToScreen" in local_moonlight
    assert "AXIsProcessTrustedWithOptions" in local_moonlight
    assert "kAXWindowsAttribute" in local_moonlight
    assert "forceTerminate" in local_moonlight
    assert "LocalMoonlightPublicIPCache" in local_moonlight
    assert "hostNameHints" in local_moonlight
    assert "publicIPHints" in local_moonlight
    assert "matchesPublicIP" in local_moonlight
    assert "stalePublicIPWarning" in local_moonlight
    assert "currentEndpointHost" in tailscale
    assert "directEndpointHosts" in tailscale
    assert "publicEndpointHosts" in tailscale
    assert "directForStreaming" in tailscale
    assert "streamingRouteSummary" in tailscale
    assert "derp(" in tailscale
    assert "peer-relay(" in tailscale
    assert '"CurAddr"' in tailscale
    assert '"Addrs"' in tailscale
    assert "LocalSSHPowerManager.publicIP" in view_model
    assert "installMoonlightViaHomebrew" in view_model
    assert "registerMoonlightViaTailscaleDirect" in view_model
    assert "moonlightBindingEnabledKey" in view_model
    assert "remote.moonlight.bindingEnabled" in view_model
    assert "moonlightAutoWakeBeforeStreamEnabledKey" not in view_model
    assert "remote.moonlight.autoWakeBeforeStreamEnabled" not in view_model
    assert '"Moonlight OFF" : "Moonlight ON"' in view_model
    assert 'moonlightSessionSnapshot.hasDesktopSession ? "stop.circle.fill" : "play.rectangle.fill"' in view_model
    moonlight_session_property = view_model.split("@Published private(set) var moonlightSessionSnapshot", 1)[1].split("@Published var moonlightBindingEnabled", 1)[0]
    assert "oldValue != moonlightSessionSnapshot" in moonlight_session_property
    assert "postMenuBarStatusDidChange()" in moonlight_session_property
    assert "defer { refreshMoonlightSessionSnapshot() }" in view_model
    assert "refreshMoonlightSessionSnapshot()" in view_model.split("private func mirrorRemoteState", 1)[1].split("private func shouldRefreshLocalSSHHealthAfterOnlineRecovery", 1)[0]
    assert 'return "화면 켜기"' not in view_model
    assert 'return "화면 보기"' not in view_model
    assert 'return "화면 끄기"' not in view_model
    assert 'return "깨우기"' not in view_model
    assert 'return "준비 중"' not in view_model
    assert "macAccessibilityPermissionDisplay" in view_model
    assert "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility" in view_model
    assert "PendingMoonlightWakeAction" in view_model
    assert "prepareMoonlightAutoWake(action:" in view_model
    assert "resumePendingMoonlightWakeActionIfReady" in view_model
    assert "clearPendingMoonlightWakeActionIfBlocked" in view_model
    assert "toggleMoonlightDesktopSession" in view_model
    assert "ensureMoonlightDesktopVisible" in view_model
    assert "stopMoonlightDesktopSession" in view_model
    assert "if moonlightSessionSnapshot.isRunning && !moonlightSessionSnapshot.hasDesktopSession" in view_model
    assert "await prepareMoonlightAutoWake(action: .streamOnly)" in view_model
    assert "hostAvailabilityState == .online" in view_model
    assert "if pendingMoonlightWakeAction != nil { return true }" in view_model
    assert "앱 종료 fallback만 수행합니다" in view_model
    assert "updateMoonlightPreferredScreen" in view_model
    assert "focusMoonlightOnPreferredScreen" in view_model
    assert "Accessibility 권한" in view_model
    assert 'if moonlightBindingEnabled, moonlightSnapshot.readiness == .ready' in view_model
    assert "generateMoonlightPairingPIN" in view_model
    assert "moonlightTailscaleRegistrationPeer" in view_model
    assert "Tailscale direct 경로 확인 중" in view_model
    assert "호스트 Sunshine/Apollo PIN 화면" in view_model
    assert "moonlightPublicIPCacheKey" in view_model
    assert "remote.moonlight.hostPublicIPCache" in view_model
    assert "srvcert" not in app
    assert "macAddress" not in local_moonlight
    assert "selectedMoonlightHostUUIDKey" in view_model
    assert "remote.moonlight.selectedHostUUID" in view_model
    assert "refreshMoonlightSnapshot" in view_model
    assert "moonlightSnapshot" in view_model
    assert "LocalMoonlightManager.snapshot" in view_model

    assert "RemoteClientPreferences" in view_model
    assert "UserDefaults.standard" in view_model
    assert '"HH_REMOTE_PREFS_SUITE"' in view_model
    assert "UserDefaults(suiteName: suite)" in view_model
    assert "func bootstrap() async" in view_model
    assert "func startMirroring()" in view_model
    assert "latestStatus.stateRevision != lastStateRevision" in view_model
    assert "handleRemoteFailure(error)" in view_model
    assert "private actor RemoteDashboardService" in view_model
    assert "private actor RemoteDashboardServiceGate" in view_model
    assert "private static let gate = RemoteDashboardServiceGate()" in view_model
    assert "Keep refreshes sequential" in view_model
    assert "func isPowerActionEnabled(_ action: String) -> Bool" in view_model
    assert "func isProcessRunningCurrent(_ process: RemoteProcess) -> Bool" in view_model
    assert "func isLaunchEnabled(_ process: RemoteProcess) -> Bool" in view_model
    assert "func isLaunchPending(_ process: RemoteProcess) -> Bool" in view_model
    assert "func isStopEnabled(_ process: RemoteProcess) -> Bool" in view_model
    assert "func isStopPending(_ process: RemoteProcess) -> Bool" in view_model
    assert "@Published private(set) var pendingLaunchProcessIDs" in view_model
    assert "@Published private(set) var pendingStopProcessIDs" in view_model
    assert "func processStatusText(_ process: RemoteProcess) -> String" in view_model
    assert "disconnectingPowerActions" in view_model
    assert "isDisconnectedPowerState" in view_model
    assert "client.power(action:" not in view_model
    assert "static let acceptedMarker" in local_ssh
    assert "static func command(for action: String)" in local_ssh
    assert "cmd /C" in local_ssh
    assert "shutdown /s /t 1 && echo \\(acceptedMarker)" in local_ssh
    assert "shutdown /r /t 1 && echo \\(acceptedMarker)" in local_ssh
    assert "cmd /C echo \\(acceptedMarker) && rundll32.exe powrprof.dll,SetSuspendState 0,0,0" in local_ssh
    assert "rundll32.exe powrprof.dll,SetSuspendState" in local_ssh
    assert 'connectionClosingActions: Set<String> = ["sleep", "restart", "shutdown"]' in local_ssh
    assert "if connectionClosingActions.contains(action)" in local_ssh
    assert '"ServerAliveInterval=2"' in local_ssh
    assert '"ServerAliveCountMax=2"' in local_ssh
    assert 'start "" rundll32.exe' not in local_ssh
    assert 'if action == "sleep", result.status == 0' not in local_ssh
    assert "combined.contains(Self.acceptedMarker)" in local_ssh
    assert '"IdentitiesOnly=yes"' in local_ssh
    assert "authenticated: Bool" in local_ssh
    assert "authenticated: true" in local_ssh
    assert "normalizedLocalSSHKeyPath()" in local_ssh
    assert "effectiveAuthorizedKeysPath" in models
    assert "authorizedKeysScope" in models
    assert "administratorsAuthorizedKeysActive" in models
    assert "aclRepairAttempted" in models
    assert "isHostAuthorizedKeysPath" in models
    assert "host-authorized-keys-rejected" in models
    assert "localSSHKeyFileExists" in models
    assert "hostSafeForRemoteSave" not in models
    assert "localSSHHealthReady" in view_model
    assert "localSSHHealthSummary" in view_model
    assert "verifyLocalSSHHealth" in view_model
    assert '"power.ssh_health"' in view_model
    assert "let previousAvailabilityState = hostAvailabilityState" in view_model
    assert "shouldRefreshLocalSSHHealthAfterOnlineRecovery(" in view_model
    assert "previousState != .online || decision.shouldForcePayloadSync" in view_model
    assert "refreshLocalSSHHealthAfterOnlineRecovery(using: service)" in view_model
    assert "private func refreshLocalSSHHealthAfterOnlineRecovery(using service: RemoteDashboardService) async" in view_model
    assert "localSSHHealthReady," in view_model
    assert "localSSHIdentityStatus" in view_model
    assert '"ssh_identity": identityStatus' in view_model
    assert '"power.local_ssh.started"' in view_model
    assert '"power.transition.accepted"' in view_model
    assert "requestScheduledMirror(trigger: \"power.\\(action).accepted\"" in view_model
    assert "setup.effectiveAuthorizedKeysPath" in app
    assert "setup.authorizedKeysScope" in app
    assert "viewModel.localSSHHealthSummary" in app
    assert "currentState == .goingOffline && !isOfflineHint" in supervisor
    assert "shouldForcePayloadSync: false" in supervisor
    assert "!viewModel.isPowerActionEnabled(action)" in app
    assert "!viewModel.isLaunchEnabled(process)" in app
    assert "!viewModel.isStopEnabled(process)" in app
    assert "viewModel.processStatusText(process)" in app
    assert "func launch(_ process: RemoteProcess) async" in view_model
    assert "func stop(_ process: RemoteProcess) async" in view_model
    launch_source = view_model.split("func launch(_ process: RemoteProcess) async", 1)[1].split("private static func isDisconnectedPowerState", 1)[0]
    assert "await refresh()" not in launch_source
    assert "await prepareMoonlightAutoWake(action: .launch(processID: process.id))" not in launch_source
    assert "startLaunchChase(processID: processID, refreshAfterMilliseconds: result.refreshAfterMS)" in launch_source
    assert "syncScope: .forceProcesses" in view_model
    assert "syncRemoteProcesses(using: service, client: client)" in view_model
    assert "func power(_ action: String) async" in view_model
    assert "func confirmPairing() async" in view_model
    assert "func recoverPairing" in view_model
    assert "func refreshToken() async" in view_model
    assert "func saveRemoteDesktopLogging" in view_model
    assert "runSetupAutomation" in view_model
    assert "ensureServerTailscale" in view_model
    assert "probeSmartThingsDevices" in view_model
    assert "refreshPowerSetup" in view_model
    assert "applySuggestedPowerHost" not in view_model
    assert "generateAndSendSSHKey" not in view_model
    assert "applySmartThingsDevice" not in view_model
    assert 'TextField("SmartThings device id"' not in app
    assert 'TextField("SmartThings CLI path"' not in app
    assert 'TextField("SSH host"' not in app
    assert 'TextField("SSH user"' not in app
    assert 'TextField("SSH key path"' not in app
    assert 'Button("전원 설정 저장")' not in app
    assert 'Button("자동 설정 점검")' in app
    assert 'Button("전원 준비 확인")' in app

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
    assert "smoke-moonlight-host" in _read(Path("tools/smoke_macos_remote_viewmodel.py"))
    assert '"HH_REMOTE_MOONLIGHT_IGNORE_RUNNING_APPS"] = "1"' in _read(Path("tools/smoke_macos_remote_viewmodel.py"))
    assert "offline moonlight wake" in _read(Path("tools/smoke_macos_remote_viewmodel.py"))
    assert "offline Moonlight ON should queue wake-and-stream instead of failing" in _read(Path("tools/smoke_macos_remote_viewmodel.py"))
    assert "Moonlight ON owns its wake-and-stream path" in _read(Path("tools/smoke_macos_remote_viewmodel.py"))
    assert "offline launch should stay disabled while Moonlight ON owns its wake-and-stream path" in _read(Path("tools/smoke_macos_remote_viewmodel.py"))
    assert "REMOTE_CONNECTION_SUPERVISOR" in _read(Path("tools/smoke_macos_remote_viewmodel.py"))
    assert "REMOTE_GLOBAL_SHORTCUT_REGISTRAR" in _read(Path("tools/smoke_macos_remote_viewmodel.py"))
    assert "displayProcesses should sort game names by Korean dictionary order" in _read(Path("tools/smoke_macos_remote_viewmodel.py"))
    assert "offline standalone process cards should recompute today's badge" in _read(Path("tools/smoke_macos_remote_viewmodel.py"))
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
    assert "progressMeterDisplayText" in view_model
    assert "trackBadgeDisplayText" in view_model
    assert "startLocalProgressTicker" in view_model
    assert "processWithLocalProgress" in view_model
    assert "allowProjection: false" in view_model
    assert 'existing?.source == "server_tracked"' in view_model
    assert "projectedProgress(from:" in view_model
    assert 'case "linear_percent_fill"' in view_model
    assert "locallyPlayedToday" in view_model
    assert "Calendar.current.isDate" in view_model
    assert "staminaRecoverySecondsPerPoint" in view_model
    assert "formatRemainingDuration" in view_model
    assert "LocalTailscalePingResult" in tailscale
    assert "private enum TailscaleCommand" in tailscale
    assert "case zshLoginShell" in tailscale
    assert 'return "/bin/zsh -lic tailscale"' in tailscale
    assert "var isShellBridge" in tailscale
    assert "POWERLEVEL9K_DISABLE_GITSTATUS" in tailscale
    assert "ZSH_DISABLE_COMPFIX" in tailscale
    assert 'return ("/bin/zsh", ["-lic", command])' in tailscale
    assert "shellQuote" in tailscale
    assert "tailscaleCommands()" in tailscale
    assert '"/Applications/Tailscale.app/Contents/MacOS/Tailscale"' in tailscale
    assert tailscale.index('"/Applications/Tailscale.app/Contents/MacOS/Tailscale"') < tailscale.index("commands.append(.zshLoginShell)")
    assert "Packaged apps do not inherit the user's interactive zsh aliases" in tailscale
    assert '["ping", "--timeout=\\(max(1, timeoutSeconds))s", trimmedHost]' in tailscale
    assert "hardTimeoutSeconds" in tailscale
    assert "noReplySignalCount" in tailscale
    assert "isRuntimeUnavailableMessage" in tailscale
    assert "gui failed to start" in tailscale
    assert "clierror" in tailscale
    assert "tailscale_executable_path" in view_model
    assert "tailscale_exit_status" in view_model
    assert "tailscale_stdout" in view_model
    assert "tailscale_stderr" in view_model
    assert "static let healthMarker" in local_ssh
    assert "static func health(config: RemotePowerConfigPayload" in local_ssh
    assert 'private static let preferredWakeDeviceName = "PC 켜기"' in local_power
    assert "static func resolveSmartThingsCLIPath" in local_power
    assert '["install", "smartthings"]' in local_power
    assert "parseSmartThingsTableRow" in local_power
    assert "preferredWakeDevice(from candidates" in local_power
    assert "LocalPowerWakeManager.resolveSmartThingsCLIPath(cliPath)" in models
    assert "설정된 SmartThings CLI 대신 Mac 로컬 CLI를 사용합니다." in local_power
    assert "applySmartThingsProbeResult" in view_model
    assert '"install_attempted"' in view_model
    assert '"auto_selected_device_id"' in view_model
    assert "HHRemoteReleaseID" in packager
    assert "--release-id" in packager
    assert "--git-hash" in packager
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
    assert "play.circle.fill" in view_model
    assert "power.circle.fill" in view_model
    for symbol in [
        "arcade.stick.console.fill",
        "play.rectangle.fill",
        "moon.stars.fill",
        "server.rack",
        "terminal",
        "wrench.and.screwdriver.fill",
        "display.2",
        "network",
        "paperplane.fill",
        "xmark.circle.fill",
    ]:
        assert symbol in view_model
    assert "wifi.slash" not in view_model
    assert "remote.menuBarIdleIconSymbol" in view_model
    assert "remote.menuBarRunningIconSymbol" in view_model
    assert "remote.menuBarOfflineIconSymbol" in view_model
    assert "remote.menuBarIconSymbol" in view_model
    assert 'MenuBarIconPickerRow(title: "대기 상태 아이콘", selection: $viewModel.menuBarIdleIconSymbol)' in app
    assert 'MenuBarIconPickerRow(title: "실행 중 아이콘", selection: $viewModel.menuBarRunningIconSymbol)' in app
    assert 'MenuBarIconPickerRow(title: "오프라인/Standalone 아이콘", selection: $viewModel.menuBarOfflineIconSymbol)' in app
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
