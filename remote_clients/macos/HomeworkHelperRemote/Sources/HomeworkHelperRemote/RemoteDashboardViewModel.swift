import Foundation
import AppKit
import SwiftUI

private actor RemoteDashboardService {
    let client: RemoteAPIClient

    init(client: RemoteAPIClient) {
        self.client = client
    }

    func status() async throws -> RemoteStatus { try await client.status() }
    func readiness() async throws -> RemoteReadiness { try await client.readiness() }
    func dashboardSummary() async throws -> RemoteDashboardSummary { try await client.dashboardSummary() }
    func beholderIncidents() async throws -> [RemoteBeholderIncident] { try await client.beholderIncidents() }
    func gameLinks() async throws -> [RemoteGameLink] { try await client.gameLinks() }
    func activeMobileSessions() async throws -> [RemoteMobileSession] { try await client.activeMobileSessions() }
    func powerSetup() async throws -> RemotePowerSetupResponse { try await client.powerSetup() }
    func registerPowerSSHKey(publicKey: String, label: String) async throws -> RemoteSSHKeyRegistrationResponse { try await client.registerPowerSSHKey(publicKey: publicKey, label: label) }
    func processes() async throws -> [RemoteProcess] { try await client.processes() }
    func devices() async throws -> [RemoteDevice] { try await client.devices() }
    func startMobileSession(gameLinkID: String) async throws -> RemoteMobileSession { try await client.startMobileSession(gameLinkID: gameLinkID) }
    func endMobileSession(sessionID: String) async throws -> RemoteMobileSession { try await client.endMobileSession(sessionID: sessionID) }
    func createGameLink(processID: String, androidPackageName: String) async throws -> RemoteGameLink {
        try await client.createGameLink(processID: processID, androidPackageName: androidPackageName)
    }
    func launchProcess(id: String) async throws -> RemoteCommandResult { try await client.launchProcess(id: id) }
    func confirmPairing(code: String, deviceName: String) async throws -> PairingConfirmResponse {
        try await client.confirmPairing(code: code, deviceName: deviceName)
    }
    func refreshToken() async throws -> PairingConfirmResponse { try await client.refreshToken() }
    func ensureServerTailscale() async throws -> RemoteTailscaleEnsureResponse { try await client.ensureServerTailscale() }
    func remoteLoggingConfig() async throws -> RemoteLoggingConfigResponse { try await client.remoteLoggingConfig() }
    func saveRemoteLoggingConfig(enabled: Bool) async throws -> RemoteLoggingConfigResponse { try await client.saveRemoteLoggingConfig(enabled: enabled) }
    func revokeDevice(id: String) async throws -> RevokeDeviceResponse { try await client.revokeDevice(id: id) }
    func purgeRevokedDevices() async throws -> PurgeDevicesResponse { try await client.purgeRevokedDevices() }
}


private enum RemoteClientPreferences {
    private static let preferenceSuiteOverrideKey = "HH_REMOTE_PREFS_SUITE"
    private static var defaults: UserDefaults {
        if let suite = ProcessInfo.processInfo.environment[preferenceSuiteOverrideKey]?.trimmingCharacters(in: .whitespacesAndNewlines),
           !suite.isEmpty,
           let scopedDefaults = UserDefaults(suiteName: suite) {
            return scopedDefaults
        }
        return UserDefaults.standard
    }
    private static let baseURLKey = "remote.baseURL"
    private static let deviceNameKey = "remote.deviceName"
    private static let powerConfigKey = "remote.powerConfig"
    private static let desktopLoggingEnabledKey = "remote.desktopLoggingEnabled"
    private static let loginLaunchShowsWindowKey = "remote.loginLaunchShowsWindow"
    private static let legacyMenuBarIconSymbolKey = "remote.menuBarIconSymbol"
    private static let menuBarIdleIconSymbolKey = "remote.menuBarIdleIconSymbol"
    private static let menuBarRunningIconSymbolKey = "remote.menuBarRunningIconSymbol"
    private static let menuBarOfflineIconSymbolKey = "remote.menuBarOfflineIconSymbol"
    private static let showPlaySummaryKey = "remote.showPlaySummary"
    private static let cycleProgressDisplayModeKey = "remote.cycleProgressDisplayMode"
    private static let mirrorPollIntervalSecondsKey = "remote.mirrorPollIntervalSeconds"
    private static let popoverGlassTransparencyKey = "remote.popoverGlassTransparency"
    private static let popoverGlobalShortcutEnabledKey = "remote.popoverGlobalShortcutEnabled"

    static func loadBaseURL() -> String {
        let stored = defaults.string(forKey: baseURLKey)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return stored.isEmpty ? "http://127.0.0.1:8000" : stored
    }

    static func saveBaseURL(_ value: String) {
        defaults.set(value.trimmingCharacters(in: .whitespacesAndNewlines), forKey: baseURLKey)
    }

    static func loadDeviceName() -> String {
        let stored = defaults.string(forKey: deviceNameKey)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return stored.isEmpty ? Host.current().localizedName ?? "Mac" : stored
    }

    static func saveDeviceName(_ value: String) {
        defaults.set(value.trimmingCharacters(in: .whitespacesAndNewlines), forKey: deviceNameKey)
    }

    static func loadPowerPreferences() -> RemotePowerConfigPayload {
        guard let data = defaults.data(forKey: powerConfigKey),
              let config = try? JSONDecoder().decode(RemotePowerConfigPayload.self, from: data) else {
            return RemotePowerConfigPayload()
        }
        return config
    }

    static func savePowerPreferences(_ config: RemotePowerConfigPayload) {
        if let data = try? JSONEncoder().encode(config) {
            defaults.set(data, forKey: powerConfigKey)
        }
    }

    static func loadDesktopLoggingEnabled() -> Bool {
        defaults.bool(forKey: desktopLoggingEnabledKey)
    }

    static func saveDesktopLoggingEnabled(_ enabled: Bool) {
        defaults.set(enabled, forKey: desktopLoggingEnabledKey)
    }

    static func loadLoginLaunchShowsWindow() -> Bool {
        defaults.object(forKey: loginLaunchShowsWindowKey) as? Bool ?? true
    }

    static func saveLoginLaunchShowsWindow(_ enabled: Bool) {
        defaults.set(enabled, forKey: loginLaunchShowsWindowKey)
    }

    static func loadMenuBarIdleIconSymbol() -> String {
        if let stored = validatedMenuBarSymbol(defaults.string(forKey: menuBarIdleIconSymbolKey)) {
            return stored
        }
        if let legacy = validatedMenuBarSymbol(defaults.string(forKey: legacyMenuBarIconSymbolKey)) {
            return legacy
        }
        return RemoteMenuBarIconChoice.idleDefaultSymbol
    }

    static func saveMenuBarIdleIconSymbol(_ symbol: String) {
        defaults.set(normalizedMenuBarSymbol(symbol, fallback: RemoteMenuBarIconChoice.idleDefaultSymbol), forKey: menuBarIdleIconSymbolKey)
    }

    static func loadMenuBarRunningIconSymbol() -> String {
        loadMenuBarIconSymbol(forKey: menuBarRunningIconSymbolKey, fallback: RemoteMenuBarIconChoice.runningDefaultSymbol)
    }

    static func saveMenuBarRunningIconSymbol(_ symbol: String) {
        defaults.set(normalizedMenuBarSymbol(symbol, fallback: RemoteMenuBarIconChoice.runningDefaultSymbol), forKey: menuBarRunningIconSymbolKey)
    }

    static func loadMenuBarOfflineIconSymbol() -> String {
        loadMenuBarIconSymbol(forKey: menuBarOfflineIconSymbolKey, fallback: RemoteMenuBarIconChoice.offlineDefaultSymbol)
    }

    static func saveMenuBarOfflineIconSymbol(_ symbol: String) {
        defaults.set(normalizedMenuBarSymbol(symbol, fallback: RemoteMenuBarIconChoice.offlineDefaultSymbol), forKey: menuBarOfflineIconSymbolKey)
    }

    private static func loadMenuBarIconSymbol(forKey key: String, fallback: String) -> String {
        validatedMenuBarSymbol(defaults.string(forKey: key)) ?? fallback
    }

    private static func normalizedMenuBarSymbol(_ symbol: String, fallback: String) -> String {
        validatedMenuBarSymbol(symbol) ?? fallback
    }

    private static func validatedMenuBarSymbol(_ symbol: String?) -> String? {
        let trimmed = symbol?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return RemoteMenuBarIconChoice.symbols.contains(trimmed) ? trimmed : nil
    }

    static func loadShowPlaySummary() -> Bool {
        if RemoteUITestFlags.showSummary {
            return true
        }
        return defaults.object(forKey: showPlaySummaryKey) as? Bool ?? true
    }

    static func saveShowPlaySummary(_ enabled: Bool) {
        defaults.set(enabled, forKey: showPlaySummaryKey)
    }

    static func loadCycleProgressDisplayMode() -> CycleProgressDisplayMode {
        let stored = defaults.string(forKey: cycleProgressDisplayModeKey) ?? ""
        return CycleProgressDisplayMode(rawValue: stored) ?? .remaining
    }

    static func saveCycleProgressDisplayMode(_ mode: CycleProgressDisplayMode) {
        defaults.set(mode.rawValue, forKey: cycleProgressDisplayModeKey)
    }

    static func loadPopoverGlassTransparency() -> RemotePopoverGlassTransparency {
        let stored = defaults.string(forKey: popoverGlassTransparencyKey) ?? ""
        return RemotePopoverGlassTransparency(rawValue: stored) ?? .standard
    }

    static func savePopoverGlassTransparency(_ transparency: RemotePopoverGlassTransparency) {
        defaults.set(transparency.rawValue, forKey: popoverGlassTransparencyKey)
    }

    static func loadPopoverGlobalShortcutEnabled() -> Bool {
        defaults.bool(forKey: popoverGlobalShortcutEnabledKey)
    }

    static func savePopoverGlobalShortcutEnabled(_ enabled: Bool) {
        defaults.set(enabled, forKey: popoverGlobalShortcutEnabledKey)
    }

    static func loadMirrorPollIntervalSeconds() -> Int {
        guard defaults.object(forKey: mirrorPollIntervalSecondsKey) != nil else { return 5 }
        return min(60, max(1, defaults.integer(forKey: mirrorPollIntervalSecondsKey)))
    }

    static func saveMirrorPollIntervalSeconds(_ seconds: Int) {
        defaults.set(min(60, max(1, seconds)), forKey: mirrorPollIntervalSecondsKey)
    }
}

enum RemoteMenuBarIconChoice {
    static let idleDefaultSymbol = "gamecontroller.fill"
    static let runningDefaultSymbol = "play.circle.fill"
    static let offlineDefaultSymbol = "power.circle.fill"
    static let symbols = [
        "gamecontroller.fill",
        "desktopcomputer",
        "menubar.rectangle",
        "play.circle.fill",
        "power.circle.fill",
        "bolt.circle.fill",
        "sparkles",
        "circle.fill",
        "moon.fill",
        "exclamationmark.circle.fill",
    ]
}

enum RemoteMenuBarPresentationState: Equatable {
    case idle
    case running
    case offline

    var tooltip: String {
        switch self {
        case .idle:
            return "HomeworkHelper Remote · 대기"
        case .running:
            return "HomeworkHelper Remote · 게임 실행 중"
        case .offline:
            return "HomeworkHelper Remote · 오프라인/Standalone"
        }
    }
}

enum CycleProgressDisplayMode: String, CaseIterable, Identifiable {
    case remaining
    case readyAt

    var id: String { rawValue }

    var label: String {
        switch self {
        case .remaining: return "잔여 시간"
        case .readyAt: return "완료 예정 시각"
        }
    }
}

private enum RemoteClientDesktopLogger {
    static func logPath() -> String {
        guard let desktop = FileManager.default.urls(for: .desktopDirectory, in: .userDomainMask).first else {
            return "HomeworkHelperRemoteClient.log"
        }
        return desktop.appendingPathComponent("HomeworkHelperRemoteClient.log").path
    }

    static func write(_ event: String, _ fields: [String: String] = [:]) {
        let payload = (["event": event, "ts": String(Date().timeIntervalSince1970)]).merging(fields) { _, new in new }
        guard let data = try? JSONSerialization.data(withJSONObject: payload),
              let line = String(data: data, encoding: .utf8),
              let desktop = FileManager.default.urls(for: .desktopDirectory, in: .userDomainMask).first else { return }
        let url = desktop.appendingPathComponent("HomeworkHelperRemoteClient.log")
        if !FileManager.default.fileExists(atPath: url.path) { FileManager.default.createFile(atPath: url.path, contents: nil) }
        if let handle = try? FileHandle(forWritingTo: url) {
            do {
                try handle.seekToEnd()
                try handle.write(contentsOf: Data((line + "\n").utf8))
                try handle.close()
            } catch {
                try? handle.close()
            }
        }
    }
}

@MainActor
final class RemoteDashboardViewModel: ObservableObject {
    @Published var baseURLText = RemoteClientPreferences.loadBaseURL() {
        didSet { RemoteClientPreferences.saveBaseURL(baseURLText) }
    }
    @Published var tokenText = "" {
        didSet {
            tokenStore.save(tokenText)
            postMenuBarStatusDidChange()
        }
    }
    @Published var pairingCode = ""
    @Published var deviceName = RemoteClientPreferences.loadDeviceName() {
        didSet { RemoteClientPreferences.saveDeviceName(deviceName) }
    }
    @Published var gameLinkProcessID = ""
    @Published var gameLinkAndroidPackage = ""
    @Published var powerConfig = RemoteClientPreferences.loadPowerPreferences() {
        didSet { RemoteClientPreferences.savePowerPreferences(powerConfig) }
    }
    @Published var powerSetup: RemotePowerSetupResponse?
    @Published var localSSHKey: LocalSSHKeyPair?
    @Published var localSSHHealth: LocalSSHPowerManager.HealthResult?
    @Published var smartThingsDevices: [String] = []
    @Published var smartThingsDeviceCandidates: [RemoteSmartThingsDeviceCandidate] = []
    @Published var readiness: RemoteReadiness?
    @Published var localTailscale: LocalTailscaleSnapshot?
    @Published var serverTailscaleEnsure: RemoteTailscaleEnsureResponse?
    @Published var setupProgress = "원격 설정 준비 전입니다."
    @Published var remoteDesktopLoggingEnabled = RemoteClientPreferences.loadDesktopLoggingEnabled()
    @Published var remoteDesktopLoggingPath = RemoteClientDesktopLogger.logPath()
    @Published var pairingRecoveryMessage = ""
    @Published var hostConnectionState = "unknown"
    @Published var hostAvailabilityState: RemoteHostAvailabilityState = .unknown
    @Published var status: RemoteStatus?
    @Published var dashboardSummary: RemoteDashboardSummary?
    @Published var beholderIncidents: [RemoteBeholderIncident] = []
    @Published var gameLinks: [RemoteGameLink] = []
    @Published var mobileSessions: [RemoteMobileSession] = []
    @Published var processes: [RemoteProcess] = RemoteClientCache.loadProcesses() {
        didSet { postMenuBarStatusDidChange() }
    }
    @Published var devices: [RemoteDevice] = []
    @Published var launchAtLoginEnabled = RemoteUITestFlags.skipExternalState ? false : RemoteLoginItemManager.isEnabled
    @Published var loginLaunchShowsWindow = RemoteClientPreferences.loadLoginLaunchShowsWindow() {
        didSet { RemoteClientPreferences.saveLoginLaunchShowsWindow(loginLaunchShowsWindow) }
    }
    @Published var menuBarIdleIconSymbol = RemoteClientPreferences.loadMenuBarIdleIconSymbol() {
        didSet {
            if !RemoteMenuBarIconChoice.symbols.contains(menuBarIdleIconSymbol) {
                menuBarIdleIconSymbol = RemoteMenuBarIconChoice.idleDefaultSymbol
                return
            }
            RemoteClientPreferences.saveMenuBarIdleIconSymbol(menuBarIdleIconSymbol)
            postMenuBarIconDidChange()
        }
    }
    @Published var menuBarRunningIconSymbol = RemoteClientPreferences.loadMenuBarRunningIconSymbol() {
        didSet {
            if !RemoteMenuBarIconChoice.symbols.contains(menuBarRunningIconSymbol) {
                menuBarRunningIconSymbol = RemoteMenuBarIconChoice.runningDefaultSymbol
                return
            }
            RemoteClientPreferences.saveMenuBarRunningIconSymbol(menuBarRunningIconSymbol)
            postMenuBarIconDidChange()
        }
    }
    @Published var menuBarOfflineIconSymbol = RemoteClientPreferences.loadMenuBarOfflineIconSymbol() {
        didSet {
            if !RemoteMenuBarIconChoice.symbols.contains(menuBarOfflineIconSymbol) {
                menuBarOfflineIconSymbol = RemoteMenuBarIconChoice.offlineDefaultSymbol
                return
            }
            RemoteClientPreferences.saveMenuBarOfflineIconSymbol(menuBarOfflineIconSymbol)
            postMenuBarIconDidChange()
        }
    }
    @Published var showPlaySummary = RemoteClientPreferences.loadShowPlaySummary() {
        didSet { RemoteClientPreferences.saveShowPlaySummary(showPlaySummary) }
    }
    @Published var cycleProgressDisplayMode = RemoteClientPreferences.loadCycleProgressDisplayMode() {
        didSet { RemoteClientPreferences.saveCycleProgressDisplayMode(cycleProgressDisplayMode) }
    }
    @Published var popoverGlassTransparency = RemoteClientPreferences.loadPopoverGlassTransparency() {
        didSet { RemoteClientPreferences.savePopoverGlassTransparency(popoverGlassTransparency) }
    }
    @Published var popoverGlobalShortcutEnabled = RemoteClientPreferences.loadPopoverGlobalShortcutEnabled() {
        didSet {
            RemoteClientPreferences.savePopoverGlobalShortcutEnabled(popoverGlobalShortcutEnabled)
            updateGlobalShortcutRegistration()
        }
    }
    @Published var globalShortcutStatusMessage = RemoteGlobalShortcutRegistrar.disabledMessage
    @Published var mirrorPollIntervalSeconds = RemoteClientPreferences.loadMirrorPollIntervalSeconds() {
        didSet {
            let clamped = min(60, max(1, mirrorPollIntervalSeconds))
            if clamped != mirrorPollIntervalSeconds {
                mirrorPollIntervalSeconds = clamped
                return
            }
            RemoteClientPreferences.saveMirrorPollIntervalSeconds(clamped)
        }
    }
    @Published var isLoading = false
    @Published var message = "Remote Agent에 연결하세요."


    var setupChecklist: [(String, String, Bool)] {
        let pairingHealthy = !tokenText.isEmpty && pairingRecoveryMessage.isEmpty
        let powerHealthy = powerConfig.localWakeConfigured || localSSHHealthReady
        let wakeDetail = powerConfig.smartthingsDeviceID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            ? "Wake 대상 자동 확인 필요"
            : "Wake 대상: \(powerConfig.smartthingsDeviceID)"
        let sshDetail = powerConfig.localSSHConfigured
            ? localSSHHealthSummary
            : "SSH key 자동 등록/health 확인 필요"
        let powerDetail = "\(wakeDetail) · \(sshDetail)"
        return [
            ("1. Mac Tailscale", localTailscale?.running == true ? "준비됨: \(localTailscale?.selfIPs.joined(separator: ", ") ?? "")" : "Tailscale 찾기/자동 실행 필요", localTailscale?.running == true),
            ("2. Windows 서버", hostConnectionState == "offline" ? "호스트 서버가 꺼져 있거나 Remote Agent에 연결할 수 없습니다." : (readiness?.serverModeReadiness.color == "green" ? readiness?.serverModeReadiness.message ?? "준비됨" : "Windows 앱의 설정 > 원격 설정에서 서버 모드와 페어링 코드를 확인"), hostConnectionState != "offline" && readiness?.serverModeReadiness.color == "green"),
            ("3. 페어링", pairingRecoveryMessage.isEmpty ? (tokenText.isEmpty ? "페어링 코드를 입력해 이 Mac을 등록" : "Keychain 토큰 저장됨") : pairingRecoveryMessage, pairingHealthy),
            ("4. 전원 관리", powerDetail, powerHealthy),
            ("5. 서버 Tailscale", serverTailscaleEnsure?.ready == true || readiness?.tailscaleReadiness.color == "green" ? "서버 Tailscale 준비됨" : "페어링 후 서버 Tailscale 확인/복구 실행", serverTailscaleEnsure?.ready == true || readiness?.tailscaleReadiness.color == "green")
        ]
    }

    var isPaired: Bool { !tokenText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    var localSSHHealthReady: Bool {
        localSSHHealth?.authenticated == true
    }

    var localSSHHealthSummary: String {
        guard let localSSHHealth else { return "SSH health 미확인" }
        if localSSHHealth.authenticated { return "SSH 인증 확인됨" }
        return localSSHHealth.message
    }

    var hostStatusLabel: String {
        if !isPaired { return "페어링 해제됨" }
        if isLoading, hostAvailabilityState == .online { return "동기화 중" }
        if hostAvailabilityState == .authRejected { return RemoteHostAvailabilityState.authRejected.label }
        return hostAvailabilityState.label
    }

    var hostStatusColor: Color {
        if isLoading, hostAvailabilityState == .online { return .blue }
        return isPaired ? hostAvailabilityState.color : .secondary
    }

    var hostAllowsRemoteCommands: Bool {
        isPaired && hostAvailabilityState == .online
    }

    var displayProcesses: [RemoteProcess] {
        Self.sortedProcesses(processes)
    }

    func isProcessRunningCurrent(_ process: RemoteProcess) -> Bool {
        hostAvailabilityState == .online && process.isRunning
    }

    func menuBarPresentationState() -> RemoteMenuBarPresentationState {
        guard isPaired, hostAvailabilityState == .online else { return .offline }
        if displayProcesses.contains(where: { isProcessRunningCurrent($0) }) {
            return .running
        }
        return .idle
    }

    func menuBarIconSymbol(for state: RemoteMenuBarPresentationState) -> String {
        switch state {
        case .idle:
            return menuBarIdleIconSymbol
        case .running:
            return menuBarRunningIconSymbol
        case .offline:
            return menuBarOfflineIconSymbol
        }
    }

    func isLaunchEnabled(_ process: RemoteProcess) -> Bool {
        hostAllowsRemoteCommands && !isLoading && !process.isRunning
    }

    func processRuntimeHelp(_ process: RemoteProcess) -> String {
        let runningText = isProcessRunningCurrent(process) ? "실행 중" : (process.isRunning ? "마지막 동기화 기준 실행 중" : "대기")
        return "\(runningText) · \(process.playedToday ? "오늘 실행" : "오늘 미실행")"
    }

    func processStatusText(_ process: RemoteProcess) -> String {
        if hostAvailabilityState != .online, process.isRunning {
            return "마지막 동기화: 실행 중"
        }
        return process.statusText ?? "대기"
    }

    private let tokenStore: any RemoteTokenStore
    private let bootstrapEnabled: Bool
    private var mirrorTask: Task<Void, Never>?
    private var localProgressTask: Task<Void, Never>?
    private var resumeObservers: [NSObjectProtocol] = []
    private var lastStateRevision: String?
    private var consecutiveMirrorFailures = 0
    private var reconnectSchedule: [UInt64] = []
    private static let localProgressTickSeconds: UInt64 = 30
    private static let staminaRecoverySecondsPerPoint: Double = 360
    private static let disconnectingPowerActions: Set<String> = ["shutdown", "sleep", "restart"]

    init(tokenStore: any RemoteTokenStore = KeychainTokenStore(), bootstrapEnabled: Bool = true) {
        self.tokenStore = tokenStore
        self.bootstrapEnabled = bootstrapEnabled
        tokenText = bootstrapEnabled ? tokenStore.load() : "ui-test-token"
        if bootstrapEnabled {
            installClientResumeObservers()
        }
        if !bootstrapEnabled {
            applyUITestSnapshot()
        }
        updateGlobalShortcutRegistration()
    }

    deinit {
        mirrorTask?.cancel()
        localProgressTask?.cancel()
        RemoteGlobalShortcutRegistrar.shared.unregister()
        for observer in resumeObservers {
            NotificationCenter.default.removeObserver(observer)
            NSWorkspace.shared.notificationCenter.removeObserver(observer)
        }
    }

    private func installClientResumeObservers() {
        let wakeObserver = NSWorkspace.shared.notificationCenter.addObserver(
            forName: NSWorkspace.didWakeNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor [weak self] in
                await self?.handleClientResumed()
            }
        }
        let activeObserver = NotificationCenter.default.addObserver(
            forName: NSApplication.didBecomeActiveNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self, self.hostAvailabilityState != .online else { return }
                await self.handleClientResumed()
            }
        }
        resumeObservers.append(contentsOf: [wakeObserver, activeObserver])
    }

    private func applyUITestSnapshot() {
        tokenText = "ui-test-token"
        setHostAvailability(.online, clearPairingRecovery: true)
        pairingRecoveryMessage = ""
        message = "GUI 검수 모드: 외부 상태 접근 없이 샘플 데이터를 표시합니다."
        setupProgress = "GUI 검수 모드입니다. Keychain, 네트워크, Tailscale 자동 점검을 건너뜁니다."
        let readySection = RemoteReadiness.Section(
            state: "ready",
            color: "green",
            message: "GUI 검수용 준비됨",
            activeIncidents: 0,
            authRequired: false,
            supportedActions: ["wake", "sleep", "restart", "shutdown"],
            suggestedBaseURLs: [],
            details: nil
        )
        readiness = RemoteReadiness(
            beholderHealth: readySection,
            remoteConnectivity: readySection,
            serverModeReadiness: readySection,
            powerReadiness: readySection,
            tailscaleReadiness: readySection
        )
        status = RemoteStatus(
            app: "HomeworkHelper",
            remoteAPIVersion: "ui-test",
            serverTime: Date().timeIntervalSince1970,
            stateRevision: "ui-test",
            updatedAt: Date().timeIntervalSince1970,
            counts: RemoteStatus.Counts(processes: 4, shortcuts: 0, activeSessions: 0),
            capabilities: RemoteStatus.Capabilities(
                processLaunch: true,
                shortcutOpen: true,
                dashboardSummary: true,
                beholderIncidents: true,
                gameLinks: true,
                mobileSessions: true,
                powerConfig: false,
                powerControl: true,
                beholder: true,
                authRequired: true,
                pairing: true
            ),
            power: RemoteStatus.Power(
                configured: true,
                state: "on",
                status: "ready",
                supportedActions: ["wake", "sleep", "restart", "shutdown"],
                targetHost: "ui-test-host"
            ),
            readiness: readiness
        )
        processes = Self.uiTestProcesses()
        dashboardSummary = RemoteDashboardSummary(
            range: RemoteDashboardSummary.Range(start: "ui-test", end: "ui-test"),
            metrics: RemoteDashboardSummary.Metrics(
                totalSeconds: 13200,
                dailyAverageSeconds: 3600,
                playedDays: 4,
                sessionCount: 7,
                topGame: RemoteDashboardSummary.Game(displayName: "명조: 워더링 웨이브", totalSeconds: 5400, sessionCount: 2)
            ),
            mobileMetrics: RemoteDashboardSummary.MobileMetrics(
                totalSeconds: 2400,
                activeSeconds: 1200,
                sessionCount: 2,
                activeSessionCount: 0,
                sourceBreakdown: ["android": 2],
                topGame: RemoteDashboardSummary.MobileMetrics.Game(
                    displayName: "붕괴: 스타레일",
                    androidPackageName: "com.HoYoverse.hkrpgoversea",
                    totalSeconds: 2400,
                    sessionCount: 2,
                    activeSessionCount: 0
                )
            )
        )
    }

    private static func uiTestProcesses() -> [RemoteProcess] {
        let json = """
        [
          {"id":"ww","name":"명조: 워더링 웨이브","monitoring_path":null,"launch_path":null,"preferred_launch_type":"process","last_played_timestamp":null,"stamina_current":120,"stamina_max":240,"progress":{"kind":"stamina","percentage":50,"display_text":"내일 낮 12시 완료","stamina_current":120,"stamina_max":240,"hoyolab_game_id":null,"resource_icon_url":null,"resource_icon_urls":null,"remaining_seconds":36000,"ready_at":1893500000},"icon_url":null,"icon_urls":null,"is_running":false,"played_today":true,"status_text":"오늘 실행"},
          {"id":"nikke","name":"승리의 여신: 니케","monitoring_path":null,"launch_path":null,"preferred_launch_type":"process","last_played_timestamp":null,"stamina_current":160,"stamina_max":240,"progress":{"kind":"stamina","percentage":66,"display_text":"내일 낮 12시 완료","stamina_current":160,"stamina_max":240,"hoyolab_game_id":null,"resource_icon_url":null,"resource_icon_urls":null,"remaining_seconds":28800,"ready_at":1893500000},"icon_url":null,"icon_urls":null,"is_running":false,"played_today":true,"status_text":"오늘 실행"},
          {"id":"zzz","name":"젠레스 존 제로","monitoring_path":null,"launch_path":null,"preferred_launch_type":"process","last_played_timestamp":null,"stamina_current":44,"stamina_max":240,"progress":{"kind":"stamina","percentage":18,"display_text":"44/240","stamina_current":44,"stamina_max":240,"hoyolab_game_id":null,"resource_icon_url":null,"resource_icon_urls":null,"remaining_seconds":72000,"ready_at":1893500000},"icon_url":null,"icon_urls":null,"is_running":false,"played_today":false,"status_text":"대기"},
          {"id":"hsr","name":"붕괴: 스타레일","monitoring_path":null,"launch_path":null,"preferred_launch_type":"process","last_played_timestamp":null,"stamina_current":37,"stamina_max":300,"progress":{"kind":"stamina","percentage":12,"display_text":"37/300","stamina_current":37,"stamina_max":300,"hoyolab_game_id":null,"resource_icon_url":null,"resource_icon_urls":null,"remaining_seconds":84000,"ready_at":1893500000},"icon_url":null,"icon_urls":null,"is_running":true,"played_today":true,"status_text":"실행 중"}
        ]
        """
        return (try? JSONDecoder().decode([RemoteProcess].self, from: Data(json.utf8))) ?? []
    }

    private var client: RemoteAPIClient? {
        guard let url = URL(string: baseURLText), url.scheme != nil else { return nil }
        return RemoteAPIClient(baseURL: url, bearerToken: tokenText.isEmpty ? nil : tokenText)
    }

    private var service: RemoteDashboardService? {
        guard let client else { return nil }
        return RemoteDashboardService(client: client)
    }

    private enum HostReachability {
        case reachable(ConnectivityProbeDetail)
        case unreachable(ConnectivityProbeDetail)
        case skipped(ConnectivityProbeDetail)
    }

    private enum TailnetManagementReachability {
        case reachable(ConnectivityProbeDetail)
        case unreachable(ConnectivityProbeDetail)
        case unavailable(ConnectivityProbeDetail)
        case skipped(ConnectivityProbeDetail)
    }

    private struct ConnectivityProbeDetail {
        let outcome: String
        let message: String
        let elapsedSeconds: TimeInterval
        let executablePath: String
        let exitStatus: String
        let stdout: String
        let stderr: String
        let timedOut: Bool

        init(
            outcome: String,
            message: String,
            elapsedSeconds: TimeInterval,
            executablePath: String = "",
            exitStatus: String = "",
            stdout: String = "",
            stderr: String = "",
            timedOut: Bool = false
        ) {
            self.outcome = outcome
            self.message = message
            self.elapsedSeconds = elapsedSeconds
            self.executablePath = executablePath
            self.exitStatus = exitStatus
            self.stdout = stdout
            self.stderr = stderr
            self.timedOut = timedOut
        }

        static func skipped(_ message: String) -> ConnectivityProbeDetail {
            ConnectivityProbeDetail(outcome: "skipped", message: message, elapsedSeconds: 0)
        }
    }

    private struct TailnetManagementProbe {
        let reachability: TailnetManagementReachability
        let tailscale: ConnectivityProbeDetail?
        let ssh: ConnectivityProbeDetail?
    }

    private struct ConnectivityEvaluationLog {
        let trigger: String
        var httpOutcome = "not_attempted"
        var httpFailureKind = ""
        var httpMessage = ""
        var httpElapsedSeconds: TimeInterval = 0
        var tailscale: ConnectivityProbeDetail?
        var ssh: ConnectivityProbeDetail?
        var finalState = "unknown"
        var finalMessage = ""

        var fields: [String: String] {
            var values = [
                "trigger": trigger,
                "http_outcome": httpOutcome,
                "http_failure_kind": httpFailureKind,
                "http_message": httpMessage,
                "http_elapsed_seconds": Self.format(httpElapsedSeconds),
                "final_state": finalState,
                "final_message": finalMessage,
            ]
            if let tailscale {
                values["tailscale_outcome"] = tailscale.outcome
                values["tailscale_message"] = tailscale.message
                values["tailscale_elapsed_seconds"] = Self.format(tailscale.elapsedSeconds)
                values["tailscale_executable_path"] = tailscale.executablePath
                values["tailscale_exit_status"] = tailscale.exitStatus
                values["tailscale_stdout"] = tailscale.stdout
                values["tailscale_stderr"] = tailscale.stderr
                values["tailscale_timed_out"] = String(tailscale.timedOut)
            } else {
                values["tailscale_outcome"] = "not_attempted"
            }
            if let ssh {
                values["ssh_outcome"] = ssh.outcome
                values["ssh_message"] = ssh.message
                values["ssh_elapsed_seconds"] = Self.format(ssh.elapsedSeconds)
                values["ssh_executable_path"] = ssh.executablePath
                values["ssh_exit_status"] = ssh.exitStatus
                values["ssh_stdout"] = ssh.stdout
                values["ssh_stderr"] = ssh.stderr
                values["ssh_timed_out"] = String(ssh.timedOut)
            } else {
                values["ssh_outcome"] = "not_attempted"
            }
            return values
        }

        private static func format(_ value: TimeInterval) -> String {
            String(format: "%.2f", value)
        }
    }

    private func setHostAvailability(_ state: RemoteHostAvailabilityState, clearPairingRecovery: Bool = false) {
        hostAvailabilityState = state
        hostConnectionState = state.connectionState
        if clearPairingRecovery {
            pairingRecoveryMessage = ""
        }
        postMenuBarStatusDidChange()
    }

    private func postMenuBarStatusDidChange() {
        NotificationCenter.default.post(name: Notification.Name("HomeworkHelperRemoteMenuBarStatusDidChange"), object: nil)
    }

    private func postMenuBarIconDidChange() {
        NotificationCenter.default.post(name: Notification.Name("HomeworkHelperRemoteMenuBarIconDidChange"), object: nil)
    }

    private func updateGlobalShortcutRegistration() {
        guard bootstrapEnabled else {
            globalShortcutStatusMessage = RemoteGlobalShortcutRegistrar.disabledMessage
            return
        }
        globalShortcutStatusMessage = RemoteGlobalShortcutRegistrar.shared.setEnabled(popoverGlobalShortcutEnabled)
    }

    private func supervisorDecision(_ event: RemoteConnectionEvent) -> RemoteConnectionDecision {
        RemoteConnectionSupervisor.decide(
            event: event,
            currentState: hostAvailabilityState,
            reconnectScheduleIsEmpty: reconnectSchedule.isEmpty
        )
    }

    private func applyConnectionDecision(_ decision: RemoteConnectionDecision, updateMessage: Bool = true) {
        if decision.shouldLoadCache, processes.isEmpty {
            processes = RemoteClientCache.loadProcesses()
        }
        if let schedule = decision.reconnectSchedule {
            reconnectSchedule = schedule
        }
        if let state = decision.availabilityState {
            setHostAvailability(state, clearPairingRecovery: decision.shouldClearPairingRecovery)
            if state == .authRejected, let message = decision.message {
                pairingRecoveryMessage = message
            }
        } else if decision.shouldClearPairingRecovery {
            pairingRecoveryMessage = ""
        }
        if decision.shouldRefreshLocalProgress {
            refreshLocalProcessDisplay()
        }
        if updateMessage, let message = decision.message {
            setupProgress = message
            self.message = message
        }
    }

    private func shouldProbeTailscalePing(for url: URL) -> Bool {
        guard let host = url.host?.trimmingCharacters(in: .whitespacesAndNewlines), !host.isEmpty else { return false }
        let lowered = host.lowercased()
        if ["127.0.0.1", "::1", "localhost", "0.0.0.0"].contains(lowered) { return false }
        if Self.isLikelyTailscaleHost(lowered) { return true }
        return localTailscale?.peers.contains { peer in
            peer.ips.contains(host)
                || peer.hostname.lowercased() == lowered
                || peer.dnsName.lowercased().trimmingCharacters(in: CharacterSet(charactersIn: ".")) == lowered
        } == true
    }

    private static func isLikelyTailscaleHost(_ host: String) -> Bool {
        if host.hasSuffix(".ts.net") || host.contains(".ts.net:") { return true }
        if host.hasPrefix("fd7a:115c:a1e0:") { return true }
        let parts = host.split(separator: ".").compactMap { Int($0) }
        guard parts.count == 4 else { return false }
        return parts[0] == 100 && (64...127).contains(parts[1])
    }

    private func probeHostReachability(for client: RemoteAPIClient) async -> HostReachability {
        guard shouldProbeTailscalePing(for: client.baseURL), let host = client.baseURL.host else {
            return .skipped(.skipped("loopback, 비-Tailscale 또는 호스트 없는 URL은 tailscale ping을 건너뜁니다."))
        }
        let startedAt = Date()
        let result = await TailscaleDiscovery.ping(host: host, timeoutSeconds: 2)
        let detail = ConnectivityProbeDetail(
            outcome: "\(result.outcome)",
            message: result.message,
            elapsedSeconds: Date().timeIntervalSince(startedAt),
            executablePath: result.executablePath ?? "",
            exitStatus: result.exitStatus.map(String.init) ?? "",
            stdout: result.stdout,
            stderr: result.stderr,
            timedOut: result.timedOut
        )
        switch result.outcome {
        case .reachable:
            return .reachable(detail)
        case .unreachable:
            return .unreachable(detail)
        case .unavailable:
            return .unreachable(detail)
        }
    }

    private func shouldProbeSSHHealth(for client: RemoteAPIClient) -> Bool {
        guard powerConfig.localSSHConfigured else { return false }
        let sshHost = powerConfig.sshHost.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !sshHost.isEmpty else { return false }
        guard let httpHost = client.baseURL.host?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased(), !httpHost.isEmpty else {
            return Self.isLikelyTailscaleHost(sshHost)
        }
        return sshHost == httpHost || Self.isLikelyTailscaleHost(sshHost)
    }

    private func probeTailnetManagementReachability(for client: RemoteAPIClient) async -> TailnetManagementProbe {
        switch await probeHostReachability(for: client) {
        case .reachable(let detail):
            let management = ConnectivityProbeDetail(outcome: "reachable", message: "tailscale ping OK: \(detail.message)", elapsedSeconds: detail.elapsedSeconds)
            return TailnetManagementProbe(reachability: .reachable(management), tailscale: detail, ssh: nil)
        case .unreachable(let detail):
            return TailnetManagementProbe(reachability: .unreachable(detail), tailscale: detail, ssh: nil)
        case .skipped(let detail):
            guard shouldProbeSSHHealth(for: client) else {
                return TailnetManagementProbe(reachability: .skipped(detail), tailscale: detail, ssh: nil)
            }
            let startedAt = Date()
            let ssh = await LocalSSHPowerManager.health(config: powerConfig, timeoutSeconds: 3)
            let sshDetail = ConnectivityProbeDetail(
                outcome: "\(ssh.outcome)",
                message: ssh.message,
                elapsedSeconds: Date().timeIntervalSince(startedAt),
                executablePath: ssh.executablePath,
                exitStatus: ssh.exitStatus.map(String.init) ?? "",
                stdout: ssh.stdout,
                stderr: ssh.stderr,
                timedOut: false
            )
            switch ssh.outcome {
            case .reachable:
                let management = ConnectivityProbeDetail(outcome: "reachable", message: "SSH management OK: \(ssh.message)", elapsedSeconds: sshDetail.elapsedSeconds)
                return TailnetManagementProbe(reachability: .reachable(management), tailscale: detail, ssh: sshDetail)
            case .unreachable:
                let management = ConnectivityProbeDetail(outcome: "unreachable", message: "tailscale ping skipped; SSH health unreachable: \(ssh.message)", elapsedSeconds: sshDetail.elapsedSeconds)
                return TailnetManagementProbe(reachability: .unreachable(management), tailscale: detail, ssh: sshDetail)
            case .unavailable:
                let management = ConnectivityProbeDetail(outcome: "unavailable", message: "tailscale ping skipped; SSH health unavailable: \(ssh.message)", elapsedSeconds: sshDetail.elapsedSeconds)
                return TailnetManagementProbe(reachability: .unavailable(management), tailscale: detail, ssh: sshDetail)
            }
        }
    }

    @discardableResult
    private func markHostUnreachable(_ detail: String, updateMessage: Bool = true) -> RemoteConnectionDecision {
        consecutiveMirrorFailures += 1
        let decision = supervisorDecision(.tailscaleReachability(result: .unreachable(detail)))
        applyConnectionDecision(decision, updateMessage: updateMessage)
        return decision
    }

    @discardableResult
    private func markHTTPAgentUnavailable(_ error: Error, detail: String, updateMessage: Bool = true) -> RemoteConnectionDecision {
        consecutiveMirrorFailures += 1
        let decision = supervisorDecision(.httpAgentUnavailable(kind: failureKind(for: error), detail: detail))
        applyConnectionDecision(decision, updateMessage: updateMessage)
        return decision
    }

    @discardableResult
    private func evaluateConnectivity(
        using service: RemoteDashboardService,
        client: RemoteAPIClient,
        trigger: String,
        updateMessage: Bool = true
    ) async -> (status: RemoteStatus, decision: RemoteConnectionDecision)? {
        var evaluationLog = ConnectivityEvaluationLog(trigger: trigger)
        let httpStartedAt = Date()
        do {
            let latestStatus = try await service.status()
            let decision = applyRemoteStatus(latestStatus)
            evaluationLog.httpOutcome = "success"
            evaluationLog.httpElapsedSeconds = Date().timeIntervalSince(httpStartedAt)
            evaluationLog.finalState = hostAvailabilityState.rawValue
            evaluationLog.finalMessage = message
            writeConnectivityEvaluationLog(evaluationLog)
            return (latestStatus, decision)
        } catch {
            let kind = failureKind(for: error)
            evaluationLog.httpOutcome = "failed"
            evaluationLog.httpFailureKind = "\(kind)"
            evaluationLog.httpMessage = error.localizedDescription
            evaluationLog.httpElapsedSeconds = Date().timeIntervalSince(httpStartedAt)
            if kind == .authRejected {
                let decision = supervisorDecision(.httpStatusFailed(kind: kind))
                applyConnectionDecision(decision, updateMessage: updateMessage)
                evaluationLog.finalState = hostAvailabilityState.rawValue
                evaluationLog.finalMessage = decision.message ?? message
                writeConnectivityEvaluationLog(evaluationLog)
                return nil
            }

            let management = await probeTailnetManagementReachability(for: client)
            evaluationLog.tailscale = management.tailscale
            evaluationLog.ssh = management.ssh
            let decision: RemoteConnectionDecision
            switch management.reachability {
            case .unreachable(let detail):
                decision = markHostUnreachable(detail.message, updateMessage: updateMessage)
            case .reachable(let detail):
                decision = markHTTPAgentUnavailable(error, detail: detail.message, updateMessage: updateMessage)
            case .unavailable(let detail):
                decision = markHTTPAgentUnavailable(error, detail: detail.message, updateMessage: updateMessage)
            case .skipped(let detail):
                decision = markHTTPAgentUnavailable(error, detail: detail.message, updateMessage: updateMessage)
            }
            evaluationLog.finalState = hostAvailabilityState.rawValue
            evaluationLog.finalMessage = decision.message ?? message
            writeConnectivityEvaluationLog(evaluationLog)
            return nil
        }
    }

    private func handlePayloadSyncFailure(_ error: Error, fallbackMessage: String? = nil) {
        if isAuthFailure(error) {
            handleRemoteFailure(error)
            return
        }
        if processes.isEmpty {
            processes = RemoteClientCache.loadProcesses()
        }
        refreshLocalProcessDisplay()
        message = fallbackMessage ?? "Remote Agent 상태는 응답했지만 일부 데이터 동기화에 실패했습니다. 캐시 데이터와 standalone 진행률을 유지합니다. (\(error.localizedDescription))"
    }

    private func writeConnectivityEvaluationLog(_ evaluationLog: ConnectivityEvaluationLog) {
        guard remoteDesktopLoggingEnabled else { return }
        var fields = evaluationLog.fields
        fields["bundle_version"] = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? ""
        fields["bundle_build"] = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? ""
        fields["bundle_release_id"] = Bundle.main.object(forInfoDictionaryKey: "HHRemoteReleaseID") as? String ?? ""
        fields["bundle_git_hash"] = Bundle.main.object(forInfoDictionaryKey: "HHRemoteGitHash") as? String ?? ""
        if let dirty = Bundle.main.object(forInfoDictionaryKey: "HHRemoteGitDirty") as? Bool {
            fields["bundle_git_dirty"] = String(dirty)
        } else {
            fields["bundle_git_dirty"] = ""
        }
        fields["base_url_host"] = client?.baseURL.host ?? ""
        fields["availability_label"] = hostAvailabilityState.label
        RemoteClientDesktopLogger.write("connectivity.evaluate", fields)
    }

    @discardableResult
    private func applyRemoteStatus(_ latestStatus: RemoteStatus, clearPairingRecovery: Bool = true) -> RemoteConnectionDecision {
        status = latestStatus
        consecutiveMirrorFailures = 0
        let decision = supervisorDecision(
            .httpStatusSucceeded(
                powerHint: latestStatus.power?.state ?? latestStatus.power?.status,
                stateRevision: latestStatus.stateRevision
            )
        )
        applyConnectionDecision(decision, updateMessage: false)
        if clearPairingRecovery, decision.shouldClearPairingRecovery {
            pairingRecoveryMessage = ""
        }
        if let statusReadiness = latestStatus.readiness {
            readiness = statusReadiness
        }
        return decision
    }

    private func beginPowerTransition(for action: String) {
        consecutiveMirrorFailures = 0
        applyConnectionDecision(supervisorDecision(.powerIntentAccepted(action: action)), updateMessage: false)
    }

    private func nextMirrorDelaySeconds() -> UInt64 {
        if reconnectSchedule.isEmpty == false {
            return reconnectSchedule.removeFirst()
        }
        let exhaustedDecision = supervisorDecision(.scheduleExhausted)
        if exhaustedDecision != .none {
            applyConnectionDecision(exhaustedDecision, updateMessage: false)
            return 60
        }
        switch hostAvailabilityState {
        case .offlineExpected, .agentUnavailable, .authRejected:
            return 60
        default:
            if consecutiveMirrorFailures > 0 { return 60 }
            return UInt64(mirrorPollIntervalSeconds)
        }
    }

    private func isAuthFailure(_ error: Error) -> Bool {
        failureKind(for: error) == .authRejected
    }

    private func urlError(from error: Error) -> URLError? {
        if let urlError = error as? URLError { return urlError }
        let nsError = error as NSError
        if nsError.domain == NSURLErrorDomain {
            return URLError(URLError.Code(rawValue: nsError.code))
        }
        if let underlying = nsError.userInfo[NSUnderlyingErrorKey] as? URLError {
            return underlying
        }
        if let underlying = nsError.userInfo[NSUnderlyingErrorKey] as? NSError,
           underlying.domain == NSURLErrorDomain {
            return URLError(URLError.Code(rawValue: underlying.code))
        }
        return nil
    }

    private func failureKind(for error: Error) -> RemoteConnectionFailureKind {
        let raw = error.localizedDescription
        if raw.contains("HTTP 401") || raw.contains("HTTP 403") {
            return .authRejected
        }
        if let code = urlError(from: error)?.code {
            switch code {
            case .timedOut:
                return .timedOut
            case .cannotConnectToHost:
                return .cannotConnect
            case .cannotFindHost, .dnsLookupFailed:
                return .dnsFailed
            case .networkConnectionLost, .notConnectedToInternet:
                return .networkLost
            case .internationalRoamingOff, .callIsActive, .dataNotAllowed:
                return .otherConnectivity
            default:
                break
            }
        }
        let lowered = raw.lowercased()
        if lowered.contains("timed out") {
            return .timedOut
        }
        if lowered.contains("could not connect")
            || lowered.contains("cannot connect")
            || lowered.contains("no route to host")
            || lowered.contains("host is down")
            || lowered.contains("server")
            || lowered.contains("서버") {
            return .cannotConnect
        }
        if lowered.contains("connection lost")
            || lowered.contains("not connected")
            || lowered.contains("offline")
            || lowered.contains("no reply")
            || lowered.contains("network")
            || lowered.contains("연결") {
            return .otherConnectivity
        }
        return .nonConnectivity
    }

    private func handleRemoteFailure(_ error: Error, updateMessage: Bool = true) {
        consecutiveMirrorFailures += 1
        let kind = failureKind(for: error)
        let decision = supervisorDecision(.httpStatusFailed(kind: kind))
        if decision != .none {
            applyConnectionDecision(decision, updateMessage: updateMessage)
            return
        }

        if updateMessage { message = connectionGuidance(for: error) }
    }

    private func fillDefaultSSHFields() {
        fillDefaultPowerHostFromBaseURL()
        if powerConfig.sshUser.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
           let hostUser = powerSetup?.user.trimmingCharacters(in: .whitespacesAndNewlines),
           !hostUser.isEmpty {
            powerConfig.sshUser = hostUser
        }
        let normalizedKeyPath = powerConfig.normalizedLocalSSHKeyPath()
        if powerConfig.sshKeyPath.trimmingCharacters(in: .whitespacesAndNewlines) != normalizedKeyPath {
            powerConfig.sshKeyPath = normalizedKeyPath
        }
    }

    private func fillDefaultPowerHostFromBaseURL() {
        if powerConfig.sshHost.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
           let host = URL(string: baseURLText)?.host?.trimmingCharacters(in: .whitespacesAndNewlines),
           !host.isEmpty {
            powerConfig.sshHost = host
        }
    }

    private var baseURLNeedsTailnetSuggestion: Bool {
        let trimmed = baseURLText.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty || trimmed.contains("127.0.0.1") || trimmed.contains("localhost")
    }

    private func bootstrapConnectionProgress(localTailscale snapshot: LocalTailscaleSnapshot) -> String {
        switch hostAvailabilityState {
        case .authRejected:
            return "호스트가 저장 토큰을 거부했습니다. 토큰은 보존했으니 Windows 앱의 원격 설정에서 디바이스 상태를 확인하세요."
        case .online:
            return isPaired ? "저장된 Keychain 토큰으로 자동 연결했습니다." : "서버를 찾았습니다. Windows 원격 설정에서 페어링 코드를 발급해 입력하세요."
        case .offlineExpected:
            return "호스트 Tailscale ping 응답이 없어 호스트가 최대 절전/종료 상태이거나 Tailscale이 비활성화된 것으로 판단했습니다. 캐시 데이터는 standalone으로 유지합니다."
        case .agentUnavailable:
            return "호스트 관리 계층은 확인됐지만 Windows Remote Agent HTTP 응답이 없습니다. Windows 앱 서버 모드와 방화벽/포트 8000을 확인하세요."
        case .waking:
            return "호스트 부팅을 기다리는 중입니다. 연결이 복구되면 자동으로 데이터를 다시 미러링합니다."
        case .restarting:
            return "호스트 재시동을 기다리는 중입니다. 연결이 복구되면 자동으로 데이터를 다시 미러링합니다."
        case .goingOffline:
            return "호스트가 절전/종료 상태로 전환되는지 확인 중입니다."
        case .reconnecting:
            return "호스트 연결을 다시 확인하는 중입니다. 캐시 데이터는 standalone으로 유지합니다."
        case .unknown:
            return snapshot.running
                ? "Tailscale은 준비됐지만 Windows Remote Agent 상태를 아직 확정하지 못했습니다."
                : "Tailscale 또는 Windows Remote Agent가 아직 준비되지 않았습니다. 자동 설정 점검을 실행하세요."
        }
    }

    func bootstrap() async {
        guard bootstrapEnabled else {
            applyUITestSnapshot()
            return
        }
        startLocalProgressTicker()
        setupProgress = "저장된 연결 정보와 Tailscale 후보를 확인 중..."
        let snapshot = await TailscaleDiscovery.status()
        localTailscale = snapshot
        if baseURLNeedsTailnetSuggestion, let url = snapshot.suggestedBaseURLs.first {
            baseURLText = url
            setupProgress = "저장된 Base URL이 없어서 Windows Desktop 후보를 적용했습니다: \(url)"
        }
        if let logging = try? await service?.remoteLoggingConfig() {
            remoteDesktopLoggingPath = logging.path
        }
        if isPaired {
            await recoverPairing(silent: true)
        }
        if !isPaired || hostAvailabilityState == .online || hostAvailabilityState == .unknown {
            await refresh()
        }
        setupProgress = bootstrapConnectionProgress(localTailscale: snapshot)
        startMirroring()
    }

    func startMirroring() {
        guard bootstrapEnabled, mirrorTask == nil else { return }
        mirrorTask = Task { [weak self] in
            while !Task.isCancelled {
                let seconds: UInt64 = await MainActor.run {
                    guard let self else { return 15 }
                    return self.nextMirrorDelaySeconds()
                }
                try? await Task.sleep(nanoseconds: seconds * 1_000_000_000)
                guard !Task.isCancelled else { break }
                await self?.mirrorRemoteState()
            }
        }
    }

    func startLocalProgressTicker() {
        guard bootstrapEnabled, localProgressTask == nil else { return }
        localProgressTask = Task { [weak self] in
            while !Task.isCancelled {
                try? await Task.sleep(nanoseconds: Self.localProgressTickSeconds * 1_000_000_000)
                guard !Task.isCancelled else { break }
                await MainActor.run {
                    self?.refreshLocalProcessDisplay()
                }
            }
        }
    }

    private func handleClientResumed() async {
        let decision = supervisorDecision(.clientResumed)
        applyConnectionDecision(decision, updateMessage: false)
        guard decision.shouldProbeImmediately, isPaired else { return }
        await mirrorRemoteState()
    }

    func setLaunchAtLogin(_ enabled: Bool) {
        do {
            try RemoteLoginItemManager.setEnabled(enabled)
            launchAtLoginEnabled = RemoteLoginItemManager.isEnabled
            message = launchAtLoginEnabled ? "로그인 시 실행을 활성화했습니다." : "로그인 시 실행을 비활성화했습니다."
        } catch {
            launchAtLoginEnabled = RemoteLoginItemManager.isEnabled
            message = "로그인 시 실행 설정 실패: \(error.localizedDescription)"
        }
    }

    func cachedIconURL(for process: RemoteProcess, preferredSize: Int = 256) -> URL? {
        RemoteClientCache.cachedIconURL(for: process, preferredSize: preferredSize)
    }

    func cachedResourceIconURL(for process: RemoteProcess, preferredSize: Int = 128) -> URL? {
        RemoteClientCache.cachedResourceIconURL(for: process, preferredSize: preferredSize)
    }

    func remoteIconURL(for process: RemoteProcess, preferredSize: Int = 256) -> URL? {
        guard let client else { return nil }
        return RemoteClientCache.remoteIconURL(for: process, baseURL: client.baseURL, preferredSize: preferredSize)
    }

    func remoteResourceIconURL(for process: RemoteProcess, preferredSize: Int = 128) -> URL? {
        guard let client else { return nil }
        return RemoteClientCache.remoteResourceIconURL(for: process, baseURL: client.baseURL, preferredSize: preferredSize)
    }

    func progressDisplayText(_ progress: RemoteProcess.Progress) -> String {
        guard progress.kind == "cycle", cycleProgressDisplayMode == .readyAt, let readyAt = progress.readyAt else {
            return progress.displayText
        }
        return "\(Self.formatCycleReadyAt(readyAt)) 완료"
    }

    private func refreshLocalProcessDisplay() {
        guard !processes.isEmpty else { return }
        processes = processes.map {
            Self.processWithLocalProgress(
                $0,
                now: Date(),
                recomputePlayedToday: hostAvailabilityState != .online
            )
        }
    }

    private static func processWithLocalProgress(_ process: RemoteProcess, now: Date, recomputePlayedToday: Bool) -> RemoteProcess {
        let progress = localProgress(for: process, now: now) ?? process.progress
        let playedToday = recomputePlayedToday ? locallyPlayedToday(for: process, now: now) : process.playedToday
        let statusText = recomputePlayedToday && !process.isRunning ? (playedToday ? "오늘 실행" : "대기") : process.statusText
        return RemoteProcess(
            processID: process.processID,
            name: process.name,
            monitoringPath: process.monitoringPath,
            launchPath: process.launchPath,
            preferredLaunchType: process.preferredLaunchType,
            lastPlayedTimestamp: process.lastPlayedTimestamp,
            userCycleHours: process.userCycleHours,
            staminaTrackingEnabled: process.staminaTrackingEnabled,
            hoyolabGameID: process.hoyolabGameID,
            staminaCurrent: process.staminaCurrent,
            staminaMax: process.staminaMax,
            staminaUpdatedAt: process.staminaUpdatedAt,
            progress: progress,
            iconURL: process.iconURL,
            iconURLs: process.iconURLs,
            isRunning: process.isRunning,
            playedToday: playedToday,
            statusText: statusText
        )
    }

    private static func locallyPlayedToday(for process: RemoteProcess, now: Date) -> Bool {
        guard let lastPlayed = process.lastPlayedTimestamp else { return false }
        return Calendar.current.isDate(Date(timeIntervalSince1970: lastPlayed), inSameDayAs: now)
    }

    private static func localProgress(for process: RemoteProcess, now: Date) -> RemoteProcess.Progress? {
        let existing = process.progress
        if process.staminaTrackingEnabled,
           (process.hoyolabGameID ?? existing?.hoyolabGameID) != nil,
           let current = process.staminaCurrent ?? existing?.staminaCurrent,
           let maximum = process.staminaMax ?? existing?.staminaMax,
           maximum > 0 {
            let elapsed = max(0, now.timeIntervalSince1970 - (process.staminaUpdatedAt ?? now.timeIntervalSince1970))
            let recovered = Int(elapsed / Self.staminaRecoverySecondsPerPoint)
            let predicted = min(maximum, max(0, current + recovered))
            let remainingSeconds = max(0, (maximum - predicted) * Int(Self.staminaRecoverySecondsPerPoint))
            return RemoteProcess.Progress(
                kind: "stamina",
                percentage: min(max((Double(predicted) / Double(maximum)) * 100.0, 0.0), 100.0),
                displayText: "\(predicted)/\(maximum)",
                staminaCurrent: predicted,
                staminaMax: maximum,
                hoyolabGameID: process.hoyolabGameID ?? existing?.hoyolabGameID,
                resourceIconURL: existing?.resourceIconURL,
                resourceIconURLs: existing?.resourceIconURLs,
                remainingSeconds: remainingSeconds,
                readyAt: now.addingTimeInterval(Double(remainingSeconds)).timeIntervalSince1970
            )
        }

        guard let lastPlayed = process.lastPlayedTimestamp,
              let cycleHours = process.userCycleHours,
              cycleHours > 0 else {
            return existing
        }
        let elapsed = max(0, now.timeIntervalSince1970 - lastPlayed)
        let cycleSeconds = Double(cycleHours) * 3600.0
        let percentage = min(max((elapsed / cycleSeconds) * 100.0, 0.0), 100.0)
        let remainingSeconds = max(0, Int(cycleSeconds - elapsed))
        return RemoteProcess.Progress(
            kind: "cycle",
            percentage: percentage,
            displayText: Self.formatRemainingDuration(seconds: remainingSeconds),
            staminaCurrent: nil,
            staminaMax: nil,
            hoyolabGameID: existing?.hoyolabGameID,
            resourceIconURL: existing?.resourceIconURL,
            resourceIconURLs: existing?.resourceIconURLs,
            remainingSeconds: remainingSeconds,
            readyAt: now.addingTimeInterval(Double(remainingSeconds)).timeIntervalSince1970
        )
    }

    private static func formatRemainingDuration(seconds: Int) -> String {
        if seconds <= 0 { return "0분" }
        let hours = seconds / 3600
        if hours >= 24 {
            let days = hours / 24
            let remainderHours = hours % 24
            return remainderHours > 0 ? "\(days)일 \(remainderHours)시간" : "\(days)일"
        }
        if hours >= 1 { return "\(hours)시간" }
        return "\(max(0, seconds / 60))분"
    }

    private static let koreanProcessSortLocale = Locale(identifier: "ko_KR")

    static func sortedProcesses(_ processes: [RemoteProcess]) -> [RemoteProcess] {
        processes.sorted { lhs, rhs in
            let nameOrder = lhs.name.compare(
                rhs.name,
                options: [.caseInsensitive, .diacriticInsensitive, .widthInsensitive, .numeric],
                range: nil,
                locale: koreanProcessSortLocale
            )
            if nameOrder != .orderedSame {
                return nameOrder == .orderedAscending
            }
            return lhs.id.compare(
                rhs.id,
                options: [.caseInsensitive, .diacriticInsensitive, .widthInsensitive, .numeric],
                range: nil,
                locale: Locale(identifier: "en_US_POSIX")
            ) == .orderedAscending
        }
    }

    func displayIconImage(for process: RemoteProcess, preferredSize: Int = 256, displayPointSize: CGFloat) -> NSImage? {
        RemoteClientCache.displayIconImage(for: process, preferredSize: preferredSize, displayPointSize: displayPointSize)
    }

    func displayResourceIconImage(for process: RemoteProcess, preferredSize: Int = 128, displayPointSize: CGFloat) -> NSImage? {
        RemoteClientCache.displayResourceIconImage(for: process, preferredSize: preferredSize, displayPointSize: displayPointSize)
    }

    private static func formatCycleReadyAt(_ timestamp: Double) -> String {
        let date = Date(timeIntervalSince1970: timestamp)
        let calendar = Calendar.current
        let startOfToday = calendar.startOfDay(for: Date())
        let startOfTarget = calendar.startOfDay(for: date)
        let dayDelta = calendar.dateComponents([.day], from: startOfToday, to: startOfTarget).day ?? 0
        let dayText: String
        switch dayDelta {
        case -1:
            dayText = "어제"
        case 0:
            dayText = "오늘"
        case 1:
            dayText = "내일"
        case ..<(-1):
            dayText = "\(abs(dayDelta))일 전"
        default:
            dayText = "\(dayDelta)일 후"
        }

        let hour = calendar.component(.hour, from: date)
        let period: String
        switch hour {
        case 5...10:
            period = "아침"
        case 11...16:
            period = "낮"
        case 17...20:
            period = "저녁"
        default:
            period = "밤"
        }
        let displayHour = hour % 12 == 0 ? 12 : hour % 12
        return "\(dayText) \(period) \(displayHour)시"
    }

    private func connectionGuidance(for error: Error) -> String {
        let raw = error.localizedDescription
        if raw.contains("HTTP 401") || raw.contains("HTTP 403") {
            return "저장된 페어링 토큰이 호스트에서 거부되었습니다. 로컬 토큰은 보존되며, Windows 앱의 원격 설정에서 디바이스 폐기 여부를 확인하세요. (\(raw))"
        }
        if raw.localizedCaseInsensitiveContains("could not connect") || raw.localizedCaseInsensitiveContains("timed out") || raw.localizedCaseInsensitiveContains("서버") {
            return "Windows Remote Agent에 연결하지 못했습니다. Windows 앱 서버 모드, Tailscale IP, 방화벽/포트 8000을 확인하세요. (\(raw))"
        }
        return raw
    }

    func recoverPairing(silent: Bool = false) async {
        guard isPaired else {
            pairingRecoveryMessage = "페어링 코드가 필요합니다."
            setupProgress = "Windows 앱의 [설정 > 원격 설정]에서 페어링 코드를 발급해 입력하세요."
            return
        }
        if !silent {
            isLoading = true
        }
        defer { if !silent { isLoading = false } }
        guard let client, let service else {
            pairingRecoveryMessage = "Remote Agent URL이 올바르지 않습니다."
            setupProgress = pairingRecoveryMessage
            return
        }
        guard let _ = await evaluateConnectivity(using: service, client: client, trigger: silent ? "recoverPairing.silent" : "recoverPairing", updateMessage: !silent) else {
            if hostAvailabilityState != .authRejected {
                setupProgress = "호스트가 오프라인이거나 Remote Agent가 응답하지 않습니다. 저장된 토큰과 캐시 데이터는 보존합니다."
            }
            return
        }
        setupProgress = "저장된 Keychain 토큰으로 페어링을 확인했습니다."
        devices = (try? await service.devices()) ?? devices
    }

    func clearLocalPairing() {
        tokenText = ""
        devices = []
        pairingRecoveryMessage = "이 Mac의 로컬 토큰을 삭제했습니다. 서버 등록은 Windows 원격 설정에서 언페어링하세요."
        setupProgress = pairingRecoveryMessage
        message = pairingRecoveryMessage
    }

    func runSetupAutomation() async {
        isLoading = true
        defer { isLoading = false }
        setupProgress = "1/5 Mac Tailscale 확인 중..."
        let local = await TailscaleDiscovery.ensureReady()
        localTailscale = local
        if let url = local.suggestedBaseURLs.first, baseURLText.contains("127.0.0.1") || baseURLText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            baseURLText = url
        }

        setupProgress = "2/5 Mac SmartThings wake 대상 확인 중..."
        let smartThingsPath = powerConfig.smartthingsCLIPath.trimmingCharacters(in: .whitespacesAndNewlines)
        let smartThings = await LocalPowerWakeManager.probeDevices(cliPath: smartThingsPath)
        let selected = applySmartThingsProbeResult(smartThings, updateMessage: false)
        if remoteDesktopLoggingEnabled {
            RemoteClientDesktopLogger.write(
                "power.smartthings.local_devices",
                [
                    "available": String(smartThings.available),
                    "cli_path": smartThings.cliPath ?? "",
                    "install_attempted": String(smartThings.installAttempted ?? false),
                    "install_succeeded": String(smartThings.installSucceeded ?? false),
                    "candidates": String(smartThings.deviceCandidates.count),
                    "auto_selected_device_id": selected?.id ?? "",
                    "message": smartThings.message,
                ]
            )
        }

        guard let client else {
            setupProgress = "Base URL이 올바르지 않습니다."
            message = setupProgress
            return
        }
        let service = RemoteDashboardService(client: client)
        setupProgress = "3/5 Windows Remote Agent 상태 확인 중..."
        guard let evaluation = await evaluateConnectivity(using: service, client: client, trigger: "setupAutomation.status") else {
            if hostAvailabilityState != .authRejected {
                setupProgress = "Tailscale/SSH 관리 계층 또는 Windows Remote Agent가 아직 준비되지 않았습니다. 저장된 캐시 데이터는 유지합니다."
            }
            return
        }
        let latestStatus = evaluation.status
        if latestStatus.readiness == nil {
            readiness = try? await service.readiness()
        } else {
            readiness = latestStatus.readiness
        }
        powerSetup = try? await service.powerSetup()
        fillDefaultSSHFields()
        if isPaired {
            _ = await verifyLocalSSHHealth(updateMessage: false)
        }

        if isPaired {
            setupProgress = "4/5 페어링 토큰 복구와 등록 디바이스 확인 중..."
            await recoverPairing(silent: true)
            devices = (try? await service.devices()) ?? devices
            serverTailscaleEnsure = try? await service.ensureServerTailscale()
            if let evaluation = await evaluateConnectivity(using: service, client: client, trigger: "setupAutomation.pairedStatus") {
                readiness = evaluation.status.readiness
            }
        } else {
            setupProgress = "4/5 페어링 대기: Windows 앱의 설정 > 원격 설정에서 코드를 발급해 입력하세요."
        }

        setupProgress = isPaired ? "5/5 자동 설정 점검 완료. Wake/SSH 상태를 클라이언트 로컬 설정으로 관리합니다. SSH 상태: \(localSSHHealthSummary)." : "페어링 코드를 입력하면 자동 설정을 계속할 수 있습니다."
        message = setupProgress
    }

    func ensureServerTailscale() async {
        guard let service else {
            message = "Remote Agent URL이 올바르지 않습니다."
            return
        }
        guard isPaired else {
            message = "서버 Tailscale 복구는 페어링 후 사용할 수 있습니다."
            return
        }
        isLoading = true
        defer { isLoading = false }
        do {
            serverTailscaleEnsure = try await service.ensureServerTailscale()
            if let client, let evaluation = await evaluateConnectivity(using: service, client: client, trigger: "ensureServerTailscale") {
                readiness = evaluation.status.readiness
            }
            message = serverTailscaleEnsure?.message ?? "서버 Tailscale 확인 완료"
        } catch {
            if let client {
                _ = await evaluateConnectivity(using: service, client: client, trigger: "ensureServerTailscale.failure")
            } else {
                handleRemoteFailure(error)
            }
        }
    }

    func refresh() async {
        guard bootstrapEnabled else {
            applyUITestSnapshot()
            return
        }
        guard let client else {
            message = "Remote Agent URL이 올바르지 않습니다."
            return
        }
        await refresh(using: RemoteDashboardService(client: client), includeDevices: !tokenText.isEmpty)
    }

    private func mirrorRemoteState() async {
        guard let client else { return }
        let service = RemoteDashboardService(client: client)
        let previousAvailabilityState = hostAvailabilityState
        guard let evaluation = await evaluateConnectivity(using: service, client: client, trigger: "mirror", updateMessage: false) else {
            return
        }
        let latestStatus = evaluation.status
        let shouldRefreshSSHHealthAfterRecovery = shouldRefreshLocalSSHHealthAfterOnlineRecovery(
            previousState: previousAvailabilityState,
            decision: evaluation.decision
        )
        if latestStatus.readiness == nil {
            readiness = try? await service.readiness()
        }
        guard evaluation.decision.shouldForcePayloadSync || latestStatus.stateRevision != lastStateRevision || lastStateRevision == nil else {
            refreshLocalProcessDisplay()
            if shouldRefreshSSHHealthAfterRecovery {
                await refreshLocalSSHHealthAfterOnlineRecovery(using: service)
            }
            return
        }
        lastStateRevision = latestStatus.stateRevision
        await syncRemotePayloads(using: service, client: client)
        if shouldRefreshSSHHealthAfterRecovery {
            await refreshLocalSSHHealthAfterOnlineRecovery(using: service)
        }
    }

    private func shouldRefreshLocalSSHHealthAfterOnlineRecovery(
        previousState: RemoteHostAvailabilityState,
        decision: RemoteConnectionDecision
    ) -> Bool {
        guard isPaired, hostAvailabilityState == .online else { return false }
        return previousState != .online || decision.shouldForcePayloadSync
    }

    private func refreshLocalSSHHealthAfterOnlineRecovery(using service: RemoteDashboardService) async {
        powerSetup = try? await service.powerSetup()
        fillDefaultSSHFields()
        _ = await verifyLocalSSHHealth(updateMessage: false)
    }

    private func syncRemotePayloads(using service: RemoteDashboardService, client: RemoteAPIClient) async {
        do {
            dashboardSummary = try await service.dashboardSummary()
            beholderIncidents = try await service.beholderIncidents()
            let remoteProcesses = try await service.processes()
            RemoteClientCache.saveProcesses(remoteProcesses)
            processes = remoteProcesses.map { Self.processWithLocalProgress($0, now: Date(), recomputePlayedToday: false) }
            await RemoteClientCache.cacheIcons(for: remoteProcesses, baseURL: client.baseURL)
        } catch {
            if processes.isEmpty {
                processes = RemoteClientCache.loadProcesses()
            }
            refreshLocalProcessDisplay()
            handlePayloadSyncFailure(error)
        }
    }

    private func refresh(using service: RemoteDashboardService, includeDevices: Bool) async {
        isLoading = true
        defer { isLoading = false }
        guard let client else { return }
        guard let evaluation = await evaluateConnectivity(using: service, client: client, trigger: "refresh") else { return }
        let latestStatus = evaluation.status
        do {
            // Keep refreshes sequential. The Remote Agent's file-backed device
            // registry updates token last-seen metadata during auth checks, so
            // parallel authenticated requests can race on that registry file.
            lastStateRevision = latestStatus.stateRevision
            if latestStatus.readiness == nil {
                readiness = try? await service.readiness()
            }
            dashboardSummary = try await service.dashboardSummary()
            beholderIncidents = try await service.beholderIncidents()
            gameLinks = try await service.gameLinks()
            mobileSessions = try await service.activeMobileSessions()
            powerSetup = try? await service.powerSetup()
            fillDefaultSSHFields()
            _ = await verifyLocalSSHHealth(updateMessage: false)
            let remoteProcesses = try await service.processes()
            RemoteClientCache.saveProcesses(remoteProcesses)
            processes = remoteProcesses.map { Self.processWithLocalProgress($0, now: Date(), recomputePlayedToday: false) }
            await RemoteClientCache.cacheIcons(for: remoteProcesses, baseURL: client.baseURL)
            if includeDevices {
                devices = try await service.devices()
            }
            message = "동기화 완료: 게임 \(processes.count)개, 연결 \(gameLinks.count)개, 모바일 세션 \(mobileSessions.count)개"
        } catch {
            handlePayloadSyncFailure(error)
            if isAuthFailure(error) {
                setupProgress = pairingRecoveryMessage
            }
        }
    }


    func discoverTailscale() async {
        message = "Tailscale CLI 확인 중..."
        let snapshot = await TailscaleDiscovery.ensureReady()
        localTailscale = snapshot
        if let url = snapshot.suggestedBaseURLs.first {
            baseURLText = url
            setupProgress = "Tailscale 후보를 Base URL로 적용했습니다: \(url)"
            message = setupProgress
        } else {
            message = snapshot.message
        }
    }

    func applySuggestedBaseURL(_ url: String) {
        baseURLText = url
        message = "Base URL 적용: \(url)"
    }

    func activeMobileSession(for link: RemoteGameLink) -> RemoteMobileSession? {
        mobileSessions.first { $0.gameLinkID == link.id && $0.status == "active" }
    }

    func startMobileSession(_ link: RemoteGameLink) async {
        guard let service else { return }
        do {
            let session = try await service.startMobileSession(gameLinkID: link.id)
            mobileSessions = try await service.activeMobileSessions()
            message = "'\(session.pcDisplayName ?? session.pcProcessID)' 모바일 세션을 시작했습니다."
        } catch {
            message = error.localizedDescription
        }
    }

    func endMobileSession(_ session: RemoteMobileSession) async {
        guard let service else { return }
        do {
            let ended = try await service.endMobileSession(sessionID: session.id)
            mobileSessions = try await service.activeMobileSessions()
            message = "'\(ended.pcDisplayName ?? ended.pcProcessID)' 모바일 세션을 종료했습니다."
        } catch {
            message = error.localizedDescription
        }
    }

    func createGameLink() async {
        guard let service else { return }
        let processID = gameLinkProcessID.trimmingCharacters(in: .whitespacesAndNewlines)
        let packageName = gameLinkAndroidPackage.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !processID.isEmpty, !packageName.isEmpty else {
            message = "PC process ID와 Android package name을 입력하세요."
            return
        }
        do {
            let link = try await service.createGameLink(processID: processID, androidPackageName: packageName)
            gameLinks = try await service.gameLinks()
            gameLinkAndroidPackage = ""
            message = "'\(link.pcDisplayName ?? link.pcProcessID)'와 \(link.androidPackageName) 연결을 저장했습니다."
        } catch {
            message = error.localizedDescription
        }
    }

    func launch(_ process: RemoteProcess) async {
        guard isLaunchEnabled(process) else {
            message = hostAvailabilityState == .online ? "이미 실행 중이거나 동기화 중입니다." : "호스트 연결이 복구된 뒤 실행할 수 있습니다. 캐시된 게임 상태는 standalone으로 계속 갱신합니다."
            return
        }
        guard let service else { return }
        do {
            let result = try await service.launchProcess(id: process.id)
            message = result.message
            await refresh()
        } catch {
            message = error.localizedDescription
        }
    }

    private static func isDisconnectedPowerState(_ state: RemoteHostAvailabilityState) -> Bool {
        [.offlineExpected, .waking, .restarting, .goingOffline, .reconnecting, .agentUnavailable, .authRejected].contains(state)
    }

    func isPowerActionEnabled(_ action: String) -> Bool {
        if action == "wake", powerConfig.localWakeConfigured { return true }
        if Self.disconnectingPowerActions.contains(action),
           powerConfig.localSSHConfigured,
           localSSHHealthReady,
           !Self.isDisconnectedPowerState(hostAvailabilityState) {
            return true
        }
        return false
    }

    func power(_ action: String) async {
        guard isPowerActionEnabled(action) else {
            message = "전원 명령은 클라이언트의 SmartThings/OpenSSH 직접 경로가 준비되어야 사용할 수 있습니다."
            return
        }
        if remoteDesktopLoggingEnabled {
            RemoteClientDesktopLogger.write("power.click", ["action": action])
        }
        if action == "wake", powerConfig.localWakeConfigured {
            if await localWake() {
                beginPowerTransition(for: "wake")
            }
            return
        }

        if Self.disconnectingPowerActions.contains(action), powerConfig.localSSHConfigured {
            if await localSSH(action) {
                beginPowerTransition(for: action)
            }
            return
        }
        message = "전원 명령은 클라이언트의 SmartThings/OpenSSH 직접 경로가 준비되어야 사용할 수 있습니다."
    }

    @discardableResult
    func localWake() async -> Bool {
        do {
            message = try await LocalPowerWakeManager.wake(config: powerConfig)
            if remoteDesktopLoggingEnabled {
                RemoteClientDesktopLogger.write(
                    "power.local_wake",
                    [
                        "status": "accepted",
                        "cli_path": LocalPowerWakeManager.resolveSmartThingsCLIPath(powerConfig.smartthingsCLIPath) ?? powerConfig.smartthingsCLIPath,
                        "device_id": powerConfig.smartthingsDeviceID,
                    ]
                )
            }
            return true
        } catch {
            message = error.localizedDescription
            if remoteDesktopLoggingEnabled {
                RemoteClientDesktopLogger.write(
                    "power.local_wake",
                    [
                        "status": "failed",
                        "cli_path": LocalPowerWakeManager.resolveSmartThingsCLIPath(powerConfig.smartthingsCLIPath) ?? powerConfig.smartthingsCLIPath,
                        "device_id": powerConfig.smartthingsDeviceID,
                        "message": error.localizedDescription,
                    ]
                )
            }
            return false
        }
    }

    @discardableResult
    private func verifyLocalSSHHealth(updateMessage: Bool = true) async -> Bool {
        guard powerConfig.localSSHConfigured else {
            localSSHHealth = nil
            return false
        }
        let result = await LocalSSHPowerManager.health(config: powerConfig, timeoutSeconds: 3)
        localSSHHealth = result
        if remoteDesktopLoggingEnabled {
            RemoteClientDesktopLogger.write(
                "power.ssh_health",
                [
                    "host": powerConfig.sshHost,
                    "user": powerConfig.sshUser,
                    "outcome": "\(result.outcome)",
                    "authenticated": String(result.authenticated),
                    "exit_status": result.exitStatus.map(String.init) ?? "",
                    "message": result.message,
                ]
            )
        }
        if updateMessage {
            message = result.authenticated
                ? "SSH health 인증 확인 완료: \(result.host)"
                : "SSH key 등록은 확인했지만 실제 SSH 인증은 실패했습니다: \(result.message)"
        }
        return result.authenticated
    }

    @discardableResult
    func localSSH(_ action: String) async -> Bool {
        let identityStatus = powerConfig.localSSHIdentityStatus
        do {
            message = try await LocalSSHPowerManager.run(action: action, config: powerConfig)
            if remoteDesktopLoggingEnabled {
                RemoteClientDesktopLogger.write("power.local_ssh", ["action": action, "host": powerConfig.sshHost, "user": powerConfig.sshUser, "status": "accepted", "ssh_identity": identityStatus])
            }
            return true
        } catch {
            message = error.localizedDescription
            localSSHHealth = nil
            if remoteDesktopLoggingEnabled {
                RemoteClientDesktopLogger.write("power.local_ssh", ["action": action, "host": powerConfig.sshHost, "user": powerConfig.sshUser, "status": "failed", "ssh_identity": identityStatus, "message": error.localizedDescription])
            }
            return false
        }
    }


    func refreshPowerSetup() async {
        guard let service else { return }
        do {
            powerSetup = try await service.powerSetup()
            if powerConfig.smartthingsCLIPath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                if let local = LocalPowerWakeManager.smartThingsCLICandidates().first {
                    powerConfig.smartthingsCLIPath = local
                }
            }
            fillDefaultSSHFields()
            _ = await verifyLocalSSHHealth(updateMessage: false)
            message = "\(powerSetup?.message ?? "전원 준비 상태 확인 완료") · \(localSSHHealthSummary)"
        } catch {
            message = connectionGuidance(for: error)
        }
    }

    func probeSmartThingsDevices() async {
        let cliPath = powerConfig.smartthingsCLIPath.trimmingCharacters(in: .whitespacesAndNewlines)
        let result = await LocalPowerWakeManager.probeDevices(cliPath: cliPath)
        let selected = applySmartThingsProbeResult(result, updateMessage: true)
        if remoteDesktopLoggingEnabled {
            RemoteClientDesktopLogger.write(
                "power.smartthings.local_devices",
                [
                    "available": String(result.available),
                    "cli_path": result.cliPath ?? "",
                    "install_attempted": String(result.installAttempted ?? false),
                    "install_succeeded": String(result.installSucceeded ?? false),
                    "candidates": String(result.deviceCandidates.count),
                    "auto_selected_device_id": selected?.id ?? "",
                    "message": result.message,
                ]
            )
        }
    }

    @discardableResult
    private func applySmartThingsProbeResult(_ result: RemoteSmartThingsDevicesResponse, updateMessage: Bool) -> RemoteSmartThingsDeviceCandidate? {
        smartThingsDevices = result.devices
        smartThingsDeviceCandidates = result.deviceCandidates
        let shouldUpdateCLIPath = powerConfig.smartthingsCLIPath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            || LocalPowerWakeManager.isLocalSmartThingsCLIPath(powerConfig.smartthingsCLIPath)
        if let cliPath = result.cliPath, shouldUpdateCLIPath {
            powerConfig.smartthingsCLIPath = cliPath
        }
        let selected = LocalPowerWakeManager.preferredWakeDevice(from: result.deviceCandidates)
        if let selected {
            powerConfig.smartthingsDeviceID = selected.id
        }
        if updateMessage {
            message = selected.map { "\(result.message) Wake 대상 자동 선택: \($0.name)" } ?? result.message
        }
        return selected
    }


    private func completePairingOnboarding(using service: RemoteDashboardService) async {
        setupProgress = "PIN 확인 완료: Tailscale, SSH key, SmartThings 전원 설정을 자동 점검합니다."
        serverTailscaleEnsure = try? await service.ensureServerTailscale()
        powerSetup = try? await service.powerSetup()
        var sshOnboardingReady = false
        var sshOnboardingMessage = "SSH health 미확인"
        if powerConfig.smartthingsCLIPath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            if let local = LocalPowerWakeManager.smartThingsCLICandidates().first {
                powerConfig.smartthingsCLIPath = local
            }
        }
        fillDefaultSSHFields()

        do {
            powerConfig.sshKeyPath = powerConfig.normalizedLocalSSHKeyPath()
            let key = try await LocalSSHKeyManager.ensureKeyPair(privateKeyPath: powerConfig.sshKeyPath)
            localSSHKey = key
            powerConfig.sshKeyPath = key.privateKeyPath
            _ = try await service.registerPowerSSHKey(publicKey: key.publicKey, label: deviceName)
            sshOnboardingReady = await verifyLocalSSHHealth(updateMessage: false)
            sshOnboardingMessage = localSSHHealthSummary
        } catch {
            sshOnboardingReady = false
            sshOnboardingMessage = error.localizedDescription
            setupProgress = "SSH key 자동 등록은 실패했습니다. Windows 원격 설정 또는 mac 전원 설정에서 다시 시도하세요: \(error.localizedDescription)"
        }

        let smartThingsCLIPath = powerConfig.smartthingsCLIPath.trimmingCharacters(in: .whitespacesAndNewlines)
        let result = await LocalPowerWakeManager.probeDevices(cliPath: smartThingsCLIPath)
        if remoteDesktopLoggingEnabled {
            let selected = LocalPowerWakeManager.preferredWakeDevice(from: result.deviceCandidates)
            RemoteClientDesktopLogger.write(
                "power.smartthings.local_devices",
                [
                    "available": String(result.available),
                    "cli_path": result.cliPath ?? "",
                    "install_attempted": String(result.installAttempted ?? false),
                    "install_succeeded": String(result.installSucceeded ?? false),
                    "candidates": String(result.deviceCandidates.count),
                    "auto_selected_device_id": selected?.id ?? "",
                    "message": result.message,
                ]
            )
        }
        _ = applySmartThingsProbeResult(result, updateMessage: false)
        if let latestStatus = try? await service.status() {
            applyRemoteStatus(latestStatus)
            readiness = latestStatus.readiness ?? readiness
        }
        setupProgress = sshOnboardingReady
            ? (smartThingsDeviceCandidates.count > 1 && powerConfig.smartthingsDeviceID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                ? "PIN 설정 대부분 완료. SSH 인증 확인됨. SmartThings 후보가 여러 개라 wake 대상을 확인하세요."
                : "PIN 1회 입력으로 가능한 원격 연결 설정과 SSH 인증을 자동 완료했습니다.")
            : "PIN 페어링은 완료됐지만 SSH 인증 확인이 필요합니다: \(sshOnboardingMessage)"
    }

    func confirmPairing() async {
        guard let client else {
            message = "Remote Agent URL이 올바르지 않습니다."
            return
        }
        guard !pairingCode.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
            message = "페어링 코드를 입력하세요."
            return
        }
        isLoading = true
        defer { isLoading = false }
        do {
            let service = RemoteDashboardService(client: client)
            let response = try await service.confirmPairing(code: pairingCode, deviceName: deviceName)
            tokenText = response.token
            pairingCode = ""
            pairingRecoveryMessage = ""
            readiness = response.onboarding?.readiness ?? readiness
            powerSetup = response.onboarding?.powerSetup ?? powerSetup
            fillDefaultSSHFields()
            let pairedService = RemoteDashboardService(client: RemoteAPIClient(baseURL: client.baseURL, bearerToken: response.token))
            await completePairingOnboarding(using: pairedService)
            message = localSSHHealthReady
                ? "'\(response.name)' 디바이스 페어링 및 자동 설정을 완료했습니다."
                : "'\(response.name)' 디바이스 페어링은 완료됐지만 SSH 인증 확인이 필요합니다: \(localSSHHealthSummary)"
            if remoteDesktopLoggingEnabled { RemoteClientDesktopLogger.write("pairing.complete", ["device": response.name]) }
            await refresh(using: pairedService, includeDevices: true)
        } catch {
            message = error.localizedDescription
        }
    }

    func refreshToken() async {
        guard let service else { return }
        do {
            let response = try await service.refreshToken()
            tokenText = response.token
            pairingRecoveryMessage = ""
            setupProgress = "현재 디바이스 토큰을 갱신하고 Keychain에 저장했습니다."
            message = "'\(response.name)' 디바이스 토큰을 갱신하고 Keychain에 저장했습니다."
            await refreshDevices()
        } catch {
            message = error.localizedDescription
        }
    }


    func saveRemoteDesktopLogging(enabled: Bool) async {
        remoteDesktopLoggingEnabled = enabled
        RemoteClientPreferences.saveDesktopLoggingEnabled(enabled)
        let localPath = RemoteClientDesktopLogger.logPath()
        do {
            guard let service else {
                remoteDesktopLoggingPath = localPath
                message = enabled ? "Mac 클라이언트 진단 로그를 저장합니다: \(localPath)" : "원격 진단 로그 저장을 껐습니다."
                if enabled { RemoteClientDesktopLogger.write("client.logging.enabled", ["host_log": "unavailable"]) }
                return
            }
            let config = try await service.saveRemoteLoggingConfig(enabled: enabled)
            remoteDesktopLoggingPath = "\(localPath) / host: \(config.path)"
            message = enabled ? "원격 진단 로그를 저장합니다: \(remoteDesktopLoggingPath)" : "원격 진단 로그 저장을 껐습니다."
            if enabled { RemoteClientDesktopLogger.write("client.logging.enabled", ["host_log": config.path]) }
        } catch {
            remoteDesktopLoggingPath = localPath
            message = enabled ? "Mac 클라이언트 로그는 켰지만 host 로그 설정 동기화는 실패했습니다: \(connectionGuidance(for: error))" : "Mac 클라이언트 로그는 껐지만 host 로그 설정 동기화는 실패했습니다: \(connectionGuidance(for: error))"
            if enabled { RemoteClientDesktopLogger.write("client.logging.enabled", ["host_log": "sync_failed"]) }
        }
    }

    func purgeRevokedDevices() async {
        guard let service else { return }
        do {
            let result = try await service.purgeRevokedDevices()
            devices = try await service.devices()
            message = "폐기된 기기 \(result.removed)개를 정리했습니다."
        } catch {
            message = connectionGuidance(for: error)
        }
    }

    func refreshDevices() async {
        guard let service else { return }
        do {
            devices = try await service.devices()
            message = "등록 디바이스 \(devices.count)개를 불러왔습니다."
        } catch {
            message = error.localizedDescription
        }
    }

    func revoke(_ device: RemoteDevice) async {
        guard let service else { return }
        do {
            let result = try await service.revokeDevice(id: device.id)
            message = result.revoked ? "'\(device.name)' 디바이스 토큰을 폐기했습니다." : "디바이스 토큰 폐기에 실패했습니다."
            if tokenText.isEmpty == false {
                await refreshDevices()
            }
        } catch {
            message = error.localizedDescription
        }
    }
}
