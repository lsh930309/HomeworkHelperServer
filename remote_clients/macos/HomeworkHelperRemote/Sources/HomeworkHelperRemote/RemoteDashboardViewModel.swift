import Foundation
import AppKit
import SwiftUI

private actor RemoteDashboardServiceGate {
    private var locked = false
    private var waiters: [CheckedContinuation<Void, Never>] = []

    private func waitForTurn() async {
        if !locked {
            locked = true
            return
        }
        await withCheckedContinuation { continuation in
            waiters.append(continuation)
        }
    }

    private func finishTurn() {
        if waiters.isEmpty {
            locked = false
        } else {
            waiters.removeFirst().resume()
        }
    }

    func run<T>(_ operation: () async throws -> T) async rethrows -> T {
        await waitForTurn()
        defer { finishTurn() }
        return try await operation()
    }
}

private actor RemoteDashboardService {
    private static let gate = RemoteDashboardServiceGate()
    let client: RemoteAPIClient

    init(client: RemoteAPIClient) {
        self.client = client
    }

    func status() async throws -> RemoteStatus { try await Self.gate.run { try await client.status() } }
    func readiness() async throws -> RemoteReadiness { try await Self.gate.run { try await client.readiness() } }
    func dashboardSummary() async throws -> RemoteDashboardSummary { try await Self.gate.run { try await client.dashboardSummary() } }
    func beholderIncidents() async throws -> [RemoteBeholderIncident] { try await Self.gate.run { try await client.beholderIncidents() } }
    func gameLinks() async throws -> [RemoteGameLink] { try await Self.gate.run { try await client.gameLinks() } }
    func activeMobileSessions() async throws -> [RemoteMobileSession] { try await Self.gate.run { try await client.activeMobileSessions() } }
    func powerSetup() async throws -> RemotePowerSetupResponse { try await Self.gate.run { try await client.powerSetup() } }
    func registerPowerSSHKey(publicKey: String, label: String) async throws -> RemoteSSHKeyRegistrationResponse {
        try await Self.gate.run { try await client.registerPowerSSHKey(publicKey: publicKey, label: label) }
    }
    func processes() async throws -> [RemoteProcess] { try await Self.gate.run { try await client.processes() } }
    func devices() async throws -> [RemoteDevice] { try await Self.gate.run { try await client.devices() } }
    func startMobileSession(gameLinkID: String) async throws -> RemoteMobileSession {
        try await Self.gate.run { try await client.startMobileSession(gameLinkID: gameLinkID) }
    }
    func endMobileSession(sessionID: String) async throws -> RemoteMobileSession {
        try await Self.gate.run { try await client.endMobileSession(sessionID: sessionID) }
    }
    func createGameLink(processID: String, androidPackageName: String) async throws -> RemoteGameLink {
        try await Self.gate.run {
            try await client.createGameLink(processID: processID, androidPackageName: androidPackageName)
        }
    }
    func launchProcess(id: String) async throws -> RemoteCommandResult { try await Self.gate.run { try await client.launchProcess(id: id) } }
    func stopProcess(id: String) async throws -> RemoteCommandResult { try await Self.gate.run { try await client.stopProcess(id: id) } }
    func confirmPairing(code: String, deviceName: String) async throws -> PairingConfirmResponse {
        try await Self.gate.run { try await client.confirmPairing(code: code, deviceName: deviceName) }
    }
    func refreshToken() async throws -> PairingConfirmResponse { try await Self.gate.run { try await client.refreshToken() } }
    func ensureServerTailscale() async throws -> RemoteTailscaleEnsureResponse { try await Self.gate.run { try await client.ensureServerTailscale() } }
    func remoteLoggingConfig() async throws -> RemoteLoggingConfigResponse { try await Self.gate.run { try await client.remoteLoggingConfig() } }
    func saveRemoteLoggingConfig(enabled: Bool) async throws -> RemoteLoggingConfigResponse {
        try await Self.gate.run { try await client.saveRemoteLoggingConfig(enabled: enabled) }
    }
    func revokeDevice(id: String) async throws -> RevokeDeviceResponse { try await Self.gate.run { try await client.revokeDevice(id: id) } }
    func purgeRevokedDevices() async throws -> PurgeDevicesResponse { try await Self.gate.run { try await client.purgeRevokedDevices() } }
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
    private static let pairedDeviceIDKey = "remote.pairedDeviceID"
    private static let powerConfigKey = "remote.powerConfig"
    private static let desktopLoggingEnabledKey = "remote.desktopLoggingEnabled"
    private static let legacyMenuBarIconSymbolKey = "remote.menuBarIconSymbol"
    private static let menuBarIdleIconSymbolKey = "remote.menuBarIdleIconSymbol"
    private static let menuBarRunningIconSymbolKey = "remote.menuBarRunningIconSymbol"
    private static let menuBarOfflineIconSymbolKey = "remote.menuBarOfflineIconSymbol"
    private static let showPlaySummaryKey = "remote.showPlaySummary"
    private static let cycleProgressDisplayModeKey = "remote.cycleProgressDisplayMode"
    private static let mirrorPollIntervalSecondsKey = "remote.mirrorPollIntervalSeconds"
    private static let popoverGlassTransparencyKey = "remote.popoverGlassTransparency"
    private static let popoverGlobalShortcutEnabledKey = "remote.popoverGlobalShortcutEnabled"
    private static let selectedMoonlightHostUUIDKey = "remote.moonlight.selectedHostUUID"
    private static let moonlightPublicIPCacheKey = "remote.moonlight.hostPublicIPCache"
    private static let moonlightBindingEnabledKey = "remote.moonlight.bindingEnabled"
    private static let smartScheduleRulesKey = "remote.smartSchedule.rules"

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

    static func loadPairedDeviceID() -> String {
        defaults.string(forKey: pairedDeviceIDKey)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    }

    static func savePairedDeviceID(_ value: String) {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty {
            defaults.removeObject(forKey: pairedDeviceIDKey)
            return
        }
        defaults.set(trimmed, forKey: pairedDeviceIDKey)
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

    static func loadSelectedMoonlightHostUUID() -> String {
        defaults.string(forKey: selectedMoonlightHostUUIDKey)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
    }

    static func saveSelectedMoonlightHostUUID(_ value: String) {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty {
            defaults.removeObject(forKey: selectedMoonlightHostUUIDKey)
            return
        }
        defaults.set(trimmed, forKey: selectedMoonlightHostUUIDKey)
    }

    static func loadMoonlightPublicIPCache() -> LocalMoonlightPublicIPCache? {
        guard let data = defaults.data(forKey: moonlightPublicIPCacheKey) else { return nil }
        return try? JSONDecoder().decode(LocalMoonlightPublicIPCache.self, from: data)
    }

    static func saveMoonlightPublicIPCache(_ cache: LocalMoonlightPublicIPCache?) {
        guard let cache else {
            defaults.removeObject(forKey: moonlightPublicIPCacheKey)
            return
        }
        if let data = try? JSONEncoder().encode(cache) {
            defaults.set(data, forKey: moonlightPublicIPCacheKey)
        }
    }

    static func loadMoonlightBindingEnabled() -> Bool {
        defaults.bool(forKey: moonlightBindingEnabledKey)
    }

    static func saveMoonlightBindingEnabled(_ enabled: Bool) {
        defaults.set(enabled, forKey: moonlightBindingEnabledKey)
    }

    static func loadSmartScheduleRules() -> [RemoteSmartScheduleRule] {
        guard let data = defaults.data(forKey: smartScheduleRulesKey),
              let rules = try? JSONDecoder().decode([RemoteSmartScheduleRule].self, from: data) else {
            return []
        }
        return rules.map { rule in
            var normalized = rule
            normalized.hour = min(23, max(0, normalized.hour))
            normalized.minute = min(59, max(0, normalized.minute))
            normalized.weekdays = Array(Set(normalized.weekdays.filter { (1...7).contains($0) })).sorted()
            return normalized
        }
    }

    static func saveSmartScheduleRules(_ rules: [RemoteSmartScheduleRule]) {
        if let data = try? JSONEncoder().encode(rules) {
            defaults.set(data, forKey: smartScheduleRulesKey)
        }
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

private enum PendingMoonlightWakeAction: Equatable {
    case streamOnly

    var label: String {
        switch self {
        case .streamOnly:
            return "Moonlight Desktop 시작"
        }
    }
}

enum RemoteSmartScheduleDisplayTarget: String, Codable, CaseIterable, Identifiable, Hashable {
    case lastPopover
    case main

    var id: String { rawValue }

    var label: String {
        switch self {
        case .lastPopover:
            return "현재/최근 Popover 화면"
        case .main:
            return "메인 디스플레이"
        }
    }
}

struct RemoteSmartScheduleRule: Codable, Identifiable, Equatable {
    var id: String
    var name: String
    var enabled: Bool
    var weekdays: [Int]
    var hour: Int
    var minute: Int
    var wakeHost: Bool
    var startMoonlight: Bool
    var displayTarget: RemoteSmartScheduleDisplayTarget
    var lastRunKey: String?

    static func weekdayMorning() -> RemoteSmartScheduleRule {
        RemoteSmartScheduleRule(
            id: UUID().uuidString,
            name: "평일 원격 플레이 준비",
            enabled: true,
            weekdays: [2, 3, 4, 5, 6],
            hour: 9,
            minute: 0,
            wakeHost: true,
            startMoonlight: false,
            displayTarget: .lastPopover,
            lastRunKey: nil
        )
    }

    var clampedHour: Int { min(23, max(0, hour)) }
    var clampedMinute: Int { min(59, max(0, minute)) }

    var timeDisplay: String {
        String(format: "%02d:%02d", clampedHour, clampedMinute)
    }

    var weekdayDisplay: String {
        let names = [1: "일", 2: "월", 3: "화", 4: "수", 5: "목", 6: "금", 7: "토"]
        let normalized = Set(weekdays.filter { (1...7).contains($0) })
        if normalized == Set([2, 3, 4, 5, 6]) { return "월~금" }
        if normalized == Set([1, 2, 3, 4, 5, 6, 7]) { return "매일" }
        return (1...7).compactMap { normalized.contains($0) ? names[$0] : nil }.joined(separator: "·")
    }

    var actionSummary: String {
        var actions: [String] = []
        if wakeHost { actions.append("Wake") }
        if startMoonlight { actions.append("Moonlight") }
        return actions.isEmpty ? "동작 없음" : actions.joined(separator: " + ")
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
    private static let shortDateTimeFormatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "ko_KR")
        formatter.dateStyle = .short
        formatter.timeStyle = .short
        return formatter
    }()

    @Published var baseURLText = RemoteClientPreferences.loadBaseURL() {
        didSet {
            RemoteClientPreferences.saveBaseURL(baseURLText)
            refreshMoonlightSnapshot()
        }
    }
    @Published var selectedMoonlightHostUUID = RemoteClientPreferences.loadSelectedMoonlightHostUUID() {
        didSet {
            RemoteClientPreferences.saveSelectedMoonlightHostUUID(selectedMoonlightHostUUID)
            refreshMoonlightSnapshot()
        }
    }
    @Published private(set) var moonlightPublicIPCache = RemoteClientPreferences.loadMoonlightPublicIPCache()
    @Published private(set) var moonlightSnapshot = LocalMoonlightManager.snapshot(
        selectedHostUUID: RemoteClientPreferences.loadSelectedMoonlightHostUUID(),
        baseURLHost: URL(string: RemoteClientPreferences.loadBaseURL())?.host,
        publicIPCache: RemoteClientPreferences.loadMoonlightPublicIPCache()
    )
    @Published private(set) var moonlightSetupInProgress = false
    @Published private(set) var moonlightPairingPIN = ""
    @Published private(set) var moonlightTailscalePing: LocalTailscalePingResult?
    @Published private(set) var moonlightLastCommandSummary = ""
    @Published private(set) var moonlightSessionSnapshot = LocalMoonlightManager.sessionSnapshot()
    @Published var moonlightBindingEnabled = RemoteClientPreferences.loadMoonlightBindingEnabled() {
        didSet { RemoteClientPreferences.saveMoonlightBindingEnabled(moonlightBindingEnabled) }
    }
    private var moonlightPreferredScreenFrame: CGRect?
    private var pendingMoonlightWakeAction: PendingMoonlightWakeAction?
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
    @Published private(set) var pairedDeviceID = RemoteClientPreferences.loadPairedDeviceID()
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
    @Published var localTailscale: LocalTailscaleSnapshot? {
        didSet {
            if let localTailscale {
                updateMoonlightPublicIPCacheFromTailscale(localTailscale)
            }
            refreshMoonlightSnapshot()
        }
    }
    @Published var serverTailscaleEnsure: RemoteTailscaleEnsureResponse?
    @Published var setupProgress = "원격 설정 준비 전입니다."
    @Published var remoteDesktopLoggingEnabled = RemoteClientPreferences.loadDesktopLoggingEnabled()
    @Published var remoteDesktopLoggingPath = RemoteClientDesktopLogger.logPath()
    @Published var pairingRecoveryMessage = ""
    @Published var hostConnectionState = "unknown"
    @Published var hostAvailabilityState: RemoteHostAvailabilityState = .unknown
    @Published var status: RemoteStatus?
    @Published var dashboardSummary: RemoteDashboardSummary? {
        didSet { postMenuBarStatusDidChange() }
    }
    @Published var beholderIncidents: [RemoteBeholderIncident] = [] {
        didSet { postMenuBarStatusDidChange() }
    }
    @Published var gameLinks: [RemoteGameLink] = []
    @Published var mobileSessions: [RemoteMobileSession] = []
    @Published var processes: [RemoteProcess] = RemoteClientCache.loadProcesses() {
        didSet { postMenuBarStatusDidChange() }
    }
    @Published var devices: [RemoteDevice] = [] {
        didSet { refreshMoonlightSnapshot() }
    }
    @Published var launchAtLoginEnabled = RemoteUITestFlags.skipExternalState ? false : RemoteLoginItemManager.isEnabled
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
        didSet {
            RemoteClientPreferences.saveShowPlaySummary(showPlaySummary)
            postMenuBarStatusDidChange()
            if showPlaySummary, dashboardSummary == nil {
                Task { await refreshDashboardSummaryForDisplay() }
            }
        }
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
    @Published var smartScheduleRules = RemoteClientPreferences.loadSmartScheduleRules() {
        didSet {
            let normalized = Self.normalizedSmartScheduleRules(smartScheduleRules)
            if normalized != smartScheduleRules {
                smartScheduleRules = normalized
                return
            }
            RemoteClientPreferences.saveSmartScheduleRules(smartScheduleRules)
        }
    }
    @Published private(set) var smartScheduleLastEvent = "스케줄 대기 중"
    @Published var isLoading = false
    @Published private(set) var pendingLaunchProcessIDs: Set<String> = []
    @Published private(set) var pendingStopProcessIDs: Set<String> = []
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
            ("1. Mac Tailscale", localTailscale?.running == true ? "준비됨: \(localTailscale?.selfIPs.joined(separator: ", ") ?? "")" : "기반환경 상태: \(localTailscale?.foundationState ?? "unknown") · Tailscale 설치/실행/로그인 필요", localTailscale?.running == true),
            ("2. Windows 서버", hostConnectionState == "offline" ? "호스트 서버가 꺼져 있거나 Remote Agent에 연결할 수 없습니다." : (readiness?.serverModeReadiness.color == "green" ? readiness?.serverModeReadiness.message ?? "준비됨" : "Windows 앱의 설정 > 원격 설정에서 서버 모드와 페어링 코드를 확인"), hostConnectionState != "offline" && readiness?.serverModeReadiness.color == "green"),
            ("3. 페어링", pairingRecoveryMessage.isEmpty ? (tokenText.isEmpty ? "페어링 코드를 입력해 이 Mac을 등록" : "Keychain 토큰 저장됨") : pairingRecoveryMessage, pairingHealthy),
            ("4. 전원 관리", powerDetail, powerHealthy),
            ("5. 서버 Tailscale", serverTailscaleEnsure?.ready == true || readiness?.tailscaleReadiness.color == "green" ? "서버 Tailscale 준비됨" : "페어링 후 서버 Tailscale 확인/복구 실행", serverTailscaleEnsure?.ready == true || readiness?.tailscaleReadiness.color == "green")
        ]
    }

    var isPaired: Bool { !tokenText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    var moonlightSelectableHosts: [LocalMoonlightHostCandidate] {
        moonlightSnapshot.usableHosts.filter { !$0.uuid.isEmpty }
    }

    var moonlightSelectedHostDisplay: String {
        guard let target = moonlightSnapshot.targetHost else {
            return moonlightSnapshot.readiness.label
        }
        return "\(target.displayTitle) · \(target.targetHostArgument)"
    }

    var moonlightInstallationDisplay: String {
        guard let installation = moonlightSnapshot.installation else { return "미설치" }
        return "\(installation.version) · \(installation.appPath)"
    }

    var moonlightHomebrewDisplay: String {
        LocalMoonlightManager.resolveHomebrewExecutablePath() ?? "Homebrew 없음"
    }

    var moonlightCanInstallViaHomebrew: Bool {
        moonlightSnapshot.installation == nil && LocalMoonlightManager.resolveHomebrewExecutablePath() != nil && !moonlightSetupInProgress
    }

    var moonlightTailscaleRegistrationDisplay: String {
        guard let peer = moonlightTailscaleRegistrationPeer() else {
            if localTailscale?.running == true { return "등록 후보 없음" }
            return "Tailscale 준비 필요"
        }
        let route = moonlightTailscalePing?.streamingRouteSummary.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        let routeSuffix = route.isEmpty ? "" : " · \(route)"
        return "\(peer.hostname.isEmpty ? peer.dnsStem : peer.hostname) · \(moonlightTailscaleRegistrationHost(from: peer) ?? "-")\(routeSuffix)"
    }

    var moonlightCanRegisterViaTailscale: Bool {
        moonlightSnapshot.installation != nil
            && moonlightSnapshot.readiness != .ready
            && moonlightTailscaleRegistrationPeer() != nil
            && !moonlightSetupInProgress
    }

    var moonlightPairingPINDisplay: String {
        moonlightPairingPIN.isEmpty ? "미시작" : moonlightPairingPIN
    }

    var moonlightFooterButtonTitle: String {
        moonlightSessionSnapshot.hasDesktopSession ? "Moonlight OFF" : "Moonlight ON"
    }

    var moonlightFooterButtonIcon: String {
        moonlightSessionSnapshot.hasDesktopSession ? "stop.circle.fill" : "play.rectangle.fill"
    }

    var moonlightFooterButtonDisabled: Bool {
        if moonlightSetupInProgress { return true }
        if pendingMoonlightWakeAction != nil { return true }
        return false
    }

    var moonlightBindingStatusDisplay: String {
        let optIn = moonlightBindingEnabled ? "Opt-in ON" : "Opt-in OFF"
        let session: String
        if moonlightSessionSnapshot.isDesktopStreamVisible {
            session = "Desktop 세션 표시 중"
        } else if moonlightSessionSnapshot.hasDesktopStreamSession {
            session = "Desktop 세션 실행 중 · 창 미표시"
        } else if moonlightSessionSnapshot.isVisible {
            session = "Moonlight 창 표시 중 · Desktop 세션으로 간주"
        } else if moonlightSessionSnapshot.isRunning {
            session = "Moonlight 실행 중 · Desktop 세션 미확인"
        } else if let pendingMoonlightWakeAction {
            session = "호스트 부팅 후 \(pendingMoonlightWakeAction.label) 대기 중"
        } else {
            session = "세션 없음"
        }
        return "\(optIn) · \(session)"
    }

    var macAccessibilityPermissionDisplay: String {
        LocalMoonlightManager.accessibilityPermissionReady(prompt: false)
            ? "허용됨"
            : "권한 필요 · 업데이트 후 재등록 필요 가능"
    }

    var macAccessibilityPermissionGuidance: String {
        if LocalMoonlightManager.accessibilityPermissionReady(prompt: false) {
            return "Moonlight 창 포커스/다중 디스플레이 이동 권한이 준비되어 있습니다."
        }
        return "macOS가 업데이트된 앱 번들을 별도 항목으로 판단하면 기존 손쉬운 사용 허용이 적용되지 않을 수 있습니다. 권한 요청 후에도 실패하면 기존 HomeworkHelper Remote 항목을 제거하고 새 앱을 다시 추가하세요."
    }

    func requestMacAccessibilityPermission() {
        let trusted = LocalMoonlightManager.accessibilityPermissionReady(prompt: true)
        if trusted {
            message = "손쉬운 사용 권한이 이미 허용되어 있습니다."
        } else {
            message = "macOS 손쉬운 사용 권한 요청을 열었습니다. 권한이 갱신되지 않으면 기존 항목 제거 후 새 앱을 다시 추가하세요."
        }
        refreshMoonlightSessionSnapshot()
    }

    func openMacAccessibilitySettings() {
        guard let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility") else { return }
        NSWorkspace.shared.open(url)
        message = "시스템 설정 > 개인정보 보호 및 보안 > 손쉬운 사용에서 HomeworkHelper Remote 권한을 확인하세요."
    }

    private func isMoonlightAutoWakeEligibleState(_ state: RemoteHostAvailabilityState) -> Bool {
        switch state {
        case .offlineExpected, .agentUnavailable, .reconnecting, .waking:
            return true
        case .unknown:
            return hostConnectionState == "offline"
        case .online, .goingOffline, .restarting, .authRejected:
            return false
        }
    }

    var moonlightPublicIPDisplay: String {
        guard let cache = moonlightPublicIPCache else { return "미수집" }
        let formatted = Self.shortDateTimeFormatter.string(from: cache.collectedDate)
        let peer = cache.matchedPeerHostName.trimmingCharacters(in: .whitespacesAndNewlines)
        let peerSuffix = peer.isEmpty ? "" : " · \(peer)"
        return "\(cache.ip) · \(cache.source) · \(formatted)\(peerSuffix)"
    }

    var moonlightStalePublicIPWarning: String {
        moonlightSnapshot.stalePublicIPWarning
    }

    func updateMoonlightPreferredScreen(_ screen: NSScreen?) {
        moonlightPreferredScreenFrame = (screen ?? NSScreen.main)?.visibleFrame
    }

    func refreshMoonlightSessionSnapshot() {
        moonlightSessionSnapshot = LocalMoonlightManager.sessionSnapshot(
            targetHostArgument: moonlightSnapshot.targetHost?.targetHostArgument
        )
    }

    func refreshMoonlightSnapshot() {
        moonlightSnapshot = LocalMoonlightManager.snapshot(
            selectedHostUUID: selectedMoonlightHostUUID,
            baseURLHost: URL(string: baseURLText)?.host,
            hostNameHints: moonlightHostNameHints(),
            publicIPHints: moonlightPublicIPHints(),
            publicIPCache: moonlightPublicIPCache
        )
        refreshMoonlightSessionSnapshot()
    }

    func refreshMoonlightPublicIPViaSSH() async {
        guard powerConfig.localSSHConfigured else {
            message = "SSH 전원 설정이 준비되어야 호스트 공인 IP를 수동 갱신할 수 있습니다."
            return
        }
        message = "SSH로 호스트 공인 IP를 확인 중..."
        let result = await LocalSSHPowerManager.publicIP(config: powerConfig, timeoutSeconds: 8)
        guard let ip = result.ip else {
            message = "호스트 공인 IP 확인 실패: \(result.message)"
            return
        }
        let cache = LocalMoonlightPublicIPCache(
            ip: ip,
            source: "ssh",
            collectedAt: Date().timeIntervalSince1970,
            matchedPeerHostName: powerConfig.sshHost
        )
        saveMoonlightPublicIPCache(cache)
        message = "호스트 공인 IP를 갱신했습니다: \(ip)"
    }

    func installMoonlightViaHomebrew() async {
        guard !moonlightSetupInProgress else { return }
        guard moonlightSnapshot.installation == nil else {
            message = "Moonlight가 이미 설치되어 있습니다."
            refreshMoonlightSnapshot()
            return
        }
        moonlightSetupInProgress = true
        moonlightLastCommandSummary = ""
        message = "Homebrew로 Moonlight 설치 중..."
        let result = await LocalMoonlightManager.installViaHomebrew()
        moonlightLastCommandSummary = result.outputSummary
        moonlightSetupInProgress = false
        refreshMoonlightSnapshot()
        if result.succeeded, moonlightSnapshot.installation != nil {
            message = "Moonlight 설치를 확인했습니다. 이제 Tailscale Direct 등록 또는 기존 host 감지를 진행할 수 있습니다."
        } else if result.succeeded {
            message = "Moonlight 설치 명령은 완료됐지만 앱을 아직 찾지 못했습니다. 설치 위치를 확인한 뒤 설정을 다시 읽어 주세요."
        } else {
            message = "Moonlight 설치 실패: \(result.outputSummary)"
        }
    }

    func registerMoonlightViaTailscaleDirect() async {
        guard !moonlightSetupInProgress else { return }
        guard let installation = moonlightSnapshot.installation else {
            message = "Moonlight가 설치되어 있어야 Tailscale Direct 등록을 진행할 수 있습니다."
            return
        }
        guard let peer = moonlightTailscaleRegistrationPeer(),
              let targetHost = moonlightTailscaleRegistrationHost(from: peer) else {
            message = "HomeworkHelper host와 연결된 Tailscale 등록 후보를 찾지 못했습니다."
            return
        }

        moonlightSetupInProgress = true
        moonlightLastCommandSummary = ""
        moonlightTailscalePing = nil
        message = "Tailscale direct 경로 확인 중: \(targetHost)"

        let ping = await TailscaleDiscovery.ping(host: targetHost, timeoutSeconds: 5)
        moonlightTailscalePing = ping
        guard ping.directForStreaming else {
            moonlightSetupInProgress = false
            let route = ping.streamingRouteSummary.trimmingCharacters(in: .whitespacesAndNewlines)
            message = "Moonlight 스트리밍용 Tailscale direct 연결을 확인하지 못했습니다. \(route.isEmpty ? ping.message : route)"
            return
        }

        let pin = Self.generateMoonlightPairingPIN()
        moonlightPairingPIN = pin
        message = "Moonlight pairing 시작: 호스트 Sunshine/Apollo PIN 화면에서 \(pin)을 승인하세요."
        let pairResult = await LocalMoonlightManager.pair(host: targetHost, pin: pin, installation: installation, timeoutSeconds: 120)
        moonlightLastCommandSummary = pairResult.outputSummary
        if pairResult.succeeded {
            let listResult = await LocalMoonlightManager.listApps(host: targetHost, installation: installation, timeoutSeconds: 45)
            let listSummary = listResult.outputSummary
            moonlightLastCommandSummary = [pairResult.outputSummary, listSummary]
                .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                .filter { !$0.isEmpty }
                .joined(separator: "\n")
            refreshMoonlightSnapshot()
            if listResult.succeeded {
                message = "Moonlight Tailscale Direct 등록을 완료했고 앱 목록을 확인했습니다."
            } else {
                message = "Moonlight pairing은 완료됐지만 앱 목록 확인은 실패했습니다: \(listSummary)"
            }
        } else {
            message = "Moonlight pairing 완료를 확인하지 못했습니다. 호스트에서 PIN 승인 상태를 확인하세요: \(pairResult.outputSummary)"
        }
        moonlightSetupInProgress = false
    }

    func toggleMoonlightDesktopSession() async {
        guard !moonlightSetupInProgress else { return }
        refreshMoonlightSessionSnapshot()
        if moonlightSessionSnapshot.hasDesktopSession {
            await stopMoonlightDesktopSession()
            return
        }
        if !moonlightBindingEnabled {
            moonlightBindingEnabled = true
        }
        guard hostAvailabilityState == .online else {
            await prepareMoonlightAutoWake(action: .streamOnly)
            return
        }
        _ = await ensureMoonlightDesktopVisible(trigger: "moonlight.button")
    }

    private func prepareMoonlightAutoWake(action: PendingMoonlightWakeAction) async {
        guard pendingMoonlightWakeAction == nil else {
            message = "이미 호스트 부팅 후 \(pendingMoonlightWakeAction?.label ?? "Moonlight 동작")을 기다리는 중입니다."
            return
        }
        guard moonlightSnapshot.readiness == .ready else {
            message = "Moonlight Desktop host가 준비된 뒤 자동 깨우기를 사용할 수 있습니다."
            return
        }
        guard powerConfig.localWakeConfigured else {
            message = "SmartThings Wake 설정이 준비되어야 호스트를 자동으로 깨운 뒤 Moonlight를 시작할 수 있습니다."
            return
        }
        guard isMoonlightAutoWakeEligibleState(hostAvailabilityState) else {
            message = "현재 호스트 상태(\(hostAvailabilityState.label))에서는 자동 깨우기 후 Moonlight 동작을 시작하지 않습니다."
            return
        }

        pendingMoonlightWakeAction = action
        if !moonlightBindingEnabled {
            moonlightBindingEnabled = true
        }

        if hostAvailabilityState == .waking {
            message = "호스트 부팅을 기다린 뒤 \(action.label)을 이어갑니다."
            requestImmediateMirror(trigger: "moonlight.autoWake.alreadyWaking", syncScope: .revisionAware)
            return
        }

        message = "호스트를 깨운 뒤 \(action.label)을 이어갑니다."
        guard await localWake() else {
            pendingMoonlightWakeAction = nil
            return
        }
        beginPowerTransition(for: "wake")
        message = "Wake 명령을 전달했습니다. 호스트가 온라인이 되면 \(action.label)을 자동으로 이어갑니다."
    }

    private func resumePendingMoonlightWakeActionIfReady(trigger: String) async {
        guard pendingMoonlightWakeAction != nil,
              hostAvailabilityState == .online else { return }
        pendingMoonlightWakeAction = nil
        if !moonlightBindingEnabled {
            moonlightBindingEnabled = true
        }

        _ = await ensureMoonlightDesktopVisible(trigger: "\(trigger).autoWake.stream")
    }

    private func clearPendingMoonlightWakeActionIfBlocked() {
        guard let action = pendingMoonlightWakeAction else { return }
        switch hostAvailabilityState {
        case .authRejected:
            pendingMoonlightWakeAction = nil
            message = "호스트 인증이 거부되어 \(action.label)을 중단했습니다. 페어링 상태를 확인하세요."
        case .offlineExpected, .agentUnavailable:
            guard reconnectSchedule.isEmpty else { return }
            pendingMoonlightWakeAction = nil
            message = "호스트가 온라인으로 복구되지 않아 \(action.label)을 중단했습니다. 전원/네트워크 상태를 확인한 뒤 다시 시도하세요."
        default:
            break
        }
    }

    private func ensureMoonlightDesktopVisible(trigger: String) async -> Bool {
        guard moonlightBindingEnabled else { return false }
        guard hostAvailabilityState == .online else { return false }
        guard moonlightSnapshot.readiness == .ready,
              let target = moonlightSnapshot.targetHost,
              let installation = moonlightSnapshot.installation else {
            message = "Moonlight Desktop host가 준비되지 않았습니다."
            return false
        }
        guard ensureMoonlightAccessibilityIfNeeded() else { return false }

        moonlightSetupInProgress = true
        moonlightLastCommandSummary = ""
        refreshMoonlightSessionSnapshot()

        if moonlightSessionSnapshot.isRunning && !moonlightSessionSnapshot.hasDesktopSession {
            let cleanup = await LocalMoonlightManager.terminateRunningApplications()
            moonlightLastCommandSummary = cleanup.outputSummary
            refreshMoonlightSessionSnapshot()
        }

        if !moonlightSessionSnapshot.hasDesktopSession {
            let start = LocalMoonlightManager.startDesktopStream(host: target.targetHostArgument, installation: installation)
            moonlightLastCommandSummary = [moonlightLastCommandSummary, start.outputSummary]
                .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
                .filter { !$0.isEmpty }
                .joined(separator: "\n")
            guard start.succeeded else {
                moonlightSetupInProgress = false
                refreshMoonlightSessionSnapshot()
                message = "\(trigger): Moonlight Desktop 시작 실패: \(start.outputSummary)"
                return false
            }
            try? await Task.sleep(nanoseconds: 1_500_000_000)
            refreshMoonlightSessionSnapshot()
        }

        let focus = await focusMoonlightOnPreferredScreen()
        moonlightLastCommandSummary = [moonlightLastCommandSummary, focus.outputSummary]
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .joined(separator: "\n")
        moonlightSetupInProgress = false
        refreshMoonlightSessionSnapshot()
        if moonlightSessionSnapshot.hasDesktopSession || focus.succeeded {
            message = "Moonlight Desktop 세션을 현재 화면으로 불러왔습니다."
            return true
        }
        message = "\(trigger): Moonlight Desktop focus 실패: \(focus.outputSummary)"
        return false
    }

    private func stopMoonlightDesktopSession() async {
        moonlightSetupInProgress = true
        moonlightLastCommandSummary = ""
        let quit: LocalMoonlightCommandResult
        if let target = moonlightSnapshot.targetHost {
            quit = await LocalMoonlightManager.quit(host: target.targetHostArgument, installation: moonlightSnapshot.installation)
        } else {
            quit = LocalMoonlightCommandResult(
                action: "moonlight quit",
                executablePath: "",
                arguments: [],
                exitStatus: 0,
                stdout: "Moonlight quit 대상 host를 찾지 못해 앱 종료 fallback만 수행합니다.",
                stderr: "",
                timedOut: false
            )
        }
        let terminate = await LocalMoonlightManager.terminateRunningApplications()
        moonlightLastCommandSummary = [quit.outputSummary, terminate.outputSummary]
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .joined(separator: "\n")
        moonlightSetupInProgress = false
        refreshMoonlightSessionSnapshot()
        message = terminate.succeeded ? "Moonlight Desktop 세션을 종료했습니다." : "Moonlight 종료를 시도했습니다: \(terminate.outputSummary)"
    }

    private func focusMoonlightOnPreferredScreen() async -> LocalMoonlightCommandResult {
        let requiresAccessibility = NSScreen.screens.count > 1
        let frame = requiresAccessibility ? (moonlightPreferredScreenFrame ?? NSScreen.main?.visibleFrame) : nil
        var last = LocalMoonlightManager.focusAndMoveToScreen(
            visibleFrame: frame,
            requireAccessibility: requiresAccessibility,
            promptForAccessibility: false
        )
        if last.succeeded { return last }
        for _ in 0..<6 {
            try? await Task.sleep(nanoseconds: 500_000_000)
            last = LocalMoonlightManager.focusAndMoveToScreen(
                visibleFrame: frame,
                requireAccessibility: requiresAccessibility,
                promptForAccessibility: false
            )
            if last.succeeded { return last }
        }
        return last
    }

    private func ensureMoonlightAccessibilityIfNeeded() -> Bool {
        guard NSScreen.screens.count > 1 else { return true }
        guard !LocalMoonlightManager.accessibilityPermissionReady(prompt: true) else { return true }
        moonlightLastCommandSummary = "다중 디스플레이에서 Moonlight 창을 이동하려면 macOS Accessibility 권한이 필요합니다."
        message = "Moonlight 창을 현재 화면으로 옮기려면 손쉬운 사용 권한이 필요합니다. 업데이트 후 권한이 꼬이면 기존 항목 제거 후 새 앱을 다시 추가하세요."
        return false
    }

    private func saveMoonlightPublicIPCache(_ cache: LocalMoonlightPublicIPCache?) {
        moonlightPublicIPCache = cache
        RemoteClientPreferences.saveMoonlightPublicIPCache(cache)
        refreshMoonlightSnapshot()
    }

    private func updateMoonlightPublicIPCacheFromTailscale(_ snapshot: LocalTailscaleSnapshot) {
        let windowsPeers = snapshot.peers.filter { peer in
            peer.os.lowercased().contains("windows") && !peer.publicEndpointHosts.isEmpty
        }
        guard let peer = preferredMoonlightEndpointPeer(from: windowsPeers),
              let ip = peer.publicEndpointHosts.first else {
            return
        }
        if moonlightPublicIPCache?.ip == ip, moonlightPublicIPCache?.source == "tailscale" {
            return
        }
        saveMoonlightPublicIPCache(LocalMoonlightPublicIPCache(
            ip: ip,
            source: "tailscale",
            collectedAt: Date().timeIntervalSince1970,
            matchedPeerHostName: peer.hostname
        ))
    }

    private func preferredMoonlightEndpointPeer(from peers: [LocalTailscalePeer]) -> LocalTailscalePeer? {
        guard !peers.isEmpty else { return nil }
        let currentTarget = moonlightSnapshot.targetHost?.hostname.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() ?? ""
        if !currentTarget.isEmpty,
           let matched = peers.first(where: { $0.hostname.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() == currentTarget }) {
            return matched
        }
        return peers.count == 1 ? peers[0] : nil
    }

    private func moonlightTailscaleRegistrationPeer() -> LocalTailscalePeer? {
        guard let localTailscale, localTailscale.running else { return nil }
        let windowsPeers = localTailscale.peers.filter { peer in
            peer.online
                && peer.primaryIPv4 != nil
                && (peer.os.lowercased().contains("windows")
                    || "\(peer.hostname) \(peer.dnsName)".lowercased().contains("desktop"))
        }
        guard !windowsPeers.isEmpty else { return nil }

        if let baseHost = URL(string: baseURLText)?.host?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased(),
           !baseHost.isEmpty,
           let matched = windowsPeers.first(where: { peer in
               peer.ips.map { $0.lowercased() }.contains(baseHost)
                   || peer.dnsName.trimmingCharacters(in: CharacterSet(charactersIn: ".")).lowercased() == baseHost
                   || peer.dnsStem.lowercased() == baseHost
           }) {
            return matched
        }

        let hostDeviceHints = devices
            .filter { $0.role == "host" }
            .flatMap { device -> [String] in
                [device.name, device.tailnetHostname ?? ""]
            }
            .filter { !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
        for hint in hostDeviceHints {
            if let matched = windowsPeers.first(where: { peerMatchesHostName($0, hint: hint) }) {
                return matched
            }
        }

        return windowsPeers.count == 1 ? windowsPeers[0] : nil
    }

    private func moonlightTailscaleRegistrationHost(from peer: LocalTailscalePeer) -> String? {
        peer.primaryIPv4 ?? peer.dnsName.trimmingCharacters(in: CharacterSet(charactersIn: ".")).nilIfBlank
    }

    private func peerMatchesHostName(_ peer: LocalTailscalePeer, hint: String) -> Bool {
        let normalizedHint = Self.canonicalHostToken(hint)
        guard !normalizedHint.isEmpty else { return false }
        return [peer.hostname, peer.dnsName, peer.dnsStem]
            .map(Self.canonicalHostToken)
            .contains(normalizedHint)
    }

    private func moonlightHostNameHints() -> [String] {
        var hints: [String] = []
        if let localTailscale {
            for peer in localTailscale.peers {
                hints.append(peer.hostname)
                hints.append(peer.dnsName)
                hints.append(peer.dnsStem)
            }
        }
        for device in devices where device.role == "host" {
            hints.append(device.name)
            if let tailnetHostname = device.tailnetHostname { hints.append(tailnetHostname) }
        }
        return Self.uniqueNonEmpty(hints)
    }

    private func moonlightPublicIPHints() -> [String] {
        var hints: [String] = []
        if let moonlightPublicIPCache {
            hints.append(moonlightPublicIPCache.ip)
        }
        if let localTailscale {
            hints.append(contentsOf: localTailscale.peers.flatMap { $0.publicEndpointHosts })
        }
        return Self.uniqueNonEmpty(hints)
    }

    private static func uniqueNonEmpty(_ values: [String]) -> [String] {
        var seen = Set<String>()
        return values.compactMap { value in
            let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
            let key = trimmed.lowercased()
            guard !trimmed.isEmpty, !seen.contains(key) else { return nil }
            seen.insert(key)
            return trimmed
        }
    }

    private static func canonicalHostToken(_ value: String) -> String {
        value
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .trimmingCharacters(in: CharacterSet(charactersIn: "."))
            .split(separator: ".")
            .first
            .map(String.init)?
            .lowercased()
            .replacingOccurrences(of: "_", with: "-") ?? ""
    }

    private static func generateMoonlightPairingPIN() -> String {
        String(format: "%04d", Int.random(in: 0...9999))
    }

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
        if isLoading, hostAvailabilityState == .online, pendingLaunchProcessIDs.isEmpty { return "동기화 중" }
        if hostAvailabilityState == .authRejected { return RemoteHostAvailabilityState.authRejected.label }
        return hostAvailabilityState.label
    }

    var hostStatusColor: Color {
        if isLoading, hostAvailabilityState == .online, pendingLaunchProcessIDs.isEmpty { return .blue }
        return isPaired ? hostAvailabilityState.color : .secondary
    }

    var hostAllowsRemoteCommands: Bool {
        isPaired && hostAvailabilityState == .online
    }

    var sortedDevices: [RemoteDevice] {
        sortedDeviceList(devices)
    }

    func isCurrentDevice(_ device: RemoteDevice) -> Bool {
        !pairedDeviceID.isEmpty && device.id == pairedDeviceID
    }

    func deviceSubtitle(_ device: RemoteDevice) -> String {
        let os = device.tailnetOS?.nilIfBlank ?? device.platform?.nilIfBlank ?? "unknown"
        let ip = device.tailnetIP?.nilIfBlank
        let role = device.role?.nilIfBlank ?? "unknown"
        if let ip {
            return "\(role) · \(os) · \(ip)"
        }
        return "\(role) · \(os)"
    }

    func devicePairingDisplay(_ device: RemoteDevice) -> String {
        if isCurrentDevice(device) { return "-" }
        if device.role == "host" { return "호스트" }
        if device.role == "client" { return "표시 불가" }
        switch device.pairingStatus {
        case "paired": return "페어링됨"
        case "revoked": return "폐기됨"
        case "tailnet_unpaired": return "미페어링"
        default: return device.pairingStatus?.nilIfBlank ?? "-"
        }
    }

    func deviceConnectivityDisplay(_ device: RemoteDevice) -> String {
        if isCurrentDevice(device) { return "-" }
        if device.role == "host" { return hostAvailabilityState.label }
        if device.role == "client" { return "표시 불가" }
        switch device.connectivityState {
        case "active": return "정상"
        case "local": return "로컬"
        case "tailnet_online", "tailnet_online_unpaired": return "Tailnet 온라인"
        case "tailnet_offline", "tailnet_offline_unpaired": return "Tailnet 오프라인"
        case "stale_or_offline": return "대기/오프라인"
        case "revoked": return "폐기됨"
        default: return device.connectivityState?.nilIfBlank ?? "-"
        }
    }

    func canManageRemoteDevices(_ device: RemoteDevice? = nil) -> Bool {
        false
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
        guard !pendingLaunchProcessIDs.contains(process.id), !process.isRunning else { return false }
        return hostAllowsRemoteCommands
    }

    func isLaunchPending(_ process: RemoteProcess) -> Bool {
        pendingLaunchProcessIDs.contains(process.id)
    }

    func processRuntimeHelp(_ process: RemoteProcess) -> String {
        if isLaunchPending(process) {
            return "실행 명령 전달 후 호스트 실행 상태를 빠르게 확인 중"
        }
        if isStopPending(process) {
            return "종료 명령 전달 후 호스트 실행 상태를 빠르게 확인 중"
        }
        let runningText = isProcessRunningCurrent(process) ? "실행 중" : (process.isRunning ? "마지막 동기화 기준 실행 중" : "대기")
        return "\(runningText) · \(process.playedToday ? "오늘 실행" : "오늘 미실행")"
    }

    func processStatusText(_ process: RemoteProcess) -> String {
        if isLaunchPending(process) {
            return "실행 확인 중"
        }
        if isStopPending(process) {
            return "종료 확인 중"
        }
        if hostAvailabilityState != .online, process.isRunning {
            return "마지막 동기화: 실행 중"
        }
        return process.statusText ?? "대기"
    }

    func isStopEnabled(_ process: RemoteProcess) -> Bool {
        process.isRunning
            && hostAvailabilityState == .online
            && (status?.capabilities.processStop ?? false)
            && !pendingStopProcessIDs.contains(process.id)
    }

    func isStopPending(_ process: RemoteProcess) -> Bool {
        pendingStopProcessIDs.contains(process.id)
    }

    func addDefaultSmartScheduleRule() {
        smartScheduleRules.append(RemoteSmartScheduleRule.weekdayMorning())
    }

    func removeSmartScheduleRule(id: String) {
        smartScheduleRules.removeAll { $0.id == id }
    }

    func setSmartScheduleWeekday(ruleID: String, weekday: Int, enabled: Bool) {
        guard (1...7).contains(weekday),
              let index = smartScheduleRules.firstIndex(where: { $0.id == ruleID }) else { return }
        var weekdays = Set(smartScheduleRules[index].weekdays)
        if enabled {
            weekdays.insert(weekday)
        } else {
            weekdays.remove(weekday)
        }
        smartScheduleRules[index].weekdays = Array(weekdays).sorted()
    }

    private static func normalizedSmartScheduleRules(_ rules: [RemoteSmartScheduleRule]) -> [RemoteSmartScheduleRule] {
        rules.map { rule in
            var normalized = rule
            normalized.name = normalized.name.trimmingCharacters(in: .whitespacesAndNewlines)
            if normalized.name.isEmpty { normalized.name = "스마트 스케줄" }
            normalized.hour = min(23, max(0, normalized.hour))
            normalized.minute = min(59, max(0, normalized.minute))
            normalized.weekdays = Array(Set(normalized.weekdays.filter { (1...7).contains($0) })).sorted()
            return normalized
        }
    }

    private let tokenStore: any RemoteTokenStore
    private let bootstrapEnabled: Bool
    private var mirrorTask: Task<Void, Never>?
    private var localProgressTask: Task<Void, Never>?
    private var smartScheduleTask: Task<Void, Never>?
    private var resumeObservers: [NSObjectProtocol] = []
    private var lastStateRevision: String?
    private var unchangedRevisionPollCount = 0
    private var slowStatusPollCount = 0
    private var consecutiveMirrorFailures = 0
    private var reconnectSchedule: [UInt64] = []
    private var mirrorExecutionInProgress = false
    private var pendingMirrorRequest: (trigger: String, syncScope: RemotePayloadSyncScope)?
    private var launchChaseTasks: [String: Task<Void, Never>] = [:]
    private var stopChaseTasks: [String: Task<Void, Never>] = [:]
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
        startSmartScheduler()
    }

    deinit {
        mirrorTask?.cancel()
        localProgressTask?.cancel()
        smartScheduleTask?.cancel()
        launchChaseTasks.values.forEach { $0.cancel() }
        stopChaseTasks.values.forEach { $0.cancel() }
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
                processStop: true,
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
            readiness: readiness,
            diagnostics: nil
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

    private func startSmartScheduler() {
        guard bootstrapEnabled, smartScheduleTask == nil else { return }
        smartScheduleTask = Task { [weak self] in
            while !Task.isCancelled {
                await self?.evaluateSmartSchedules(now: Date())
                try? await Task.sleep(nanoseconds: 30_000_000_000)
            }
        }
    }

    private func evaluateSmartSchedules(now: Date) async {
        guard !smartScheduleRules.isEmpty else { return }
        let calendar = Calendar.current
        let weekday = calendar.component(.weekday, from: now)
        let hour = calendar.component(.hour, from: now)
        let minute = calendar.component(.minute, from: now)
        let runKey = Self.smartScheduleRunKey(for: now)

        for rule in smartScheduleRules
        where rule.enabled
            && rule.weekdays.contains(weekday)
            && rule.clampedHour == hour
            && rule.clampedMinute == minute
            && rule.lastRunKey != runKey
            && (rule.wakeHost || rule.startMoonlight) {
            markSmartScheduleRule(rule.id, lastRunKey: runKey)
            await executeSmartSchedule(rule)
        }
    }

    private static func smartScheduleRunKey(for date: Date) -> String {
        let components = Calendar.current.dateComponents([.year, .month, .day, .hour, .minute], from: date)
        return String(format: "%04d-%02d-%02d %02d:%02d", components.year ?? 0, components.month ?? 0, components.day ?? 0, components.hour ?? 0, components.minute ?? 0)
    }

    private func markSmartScheduleRule(_ id: String, lastRunKey: String) {
        guard let index = smartScheduleRules.firstIndex(where: { $0.id == id }) else { return }
        smartScheduleRules[index].lastRunKey = lastRunKey
    }

    private func executeSmartSchedule(_ rule: RemoteSmartScheduleRule) async {
        smartScheduleLastEvent = "\(rule.name) 실행 중 · \(rule.timeDisplay)"
        message = "스마트 스케줄 '\(rule.name)' 실행: \(rule.actionSummary)"

        if rule.displayTarget == .main {
            moonlightPreferredScreenFrame = NSScreen.main?.visibleFrame
        }

        if rule.startMoonlight {
            if !moonlightBindingEnabled {
                moonlightBindingEnabled = true
            }
            if hostAvailabilityState == .online {
                _ = await ensureMoonlightDesktopVisible(trigger: "smartSchedule.\(rule.id)")
            } else if rule.wakeHost {
                await prepareMoonlightAutoWake(action: .streamOnly)
            } else {
                message = "스마트 스케줄 '\(rule.name)'은 Moonlight 시작을 요청했지만 호스트가 온라인이 아닙니다."
            }
        } else if rule.wakeHost {
            if powerConfig.localWakeConfigured {
                await power("wake")
            } else {
                message = "스마트 스케줄 '\(rule.name)'은 Wake를 요청했지만 SmartThings Wake 설정이 준비되지 않았습니다."
            }
        }

        smartScheduleLastEvent = "\(rule.name) 마지막 실행 · \(Self.shortDateTimeFormatter.string(from: Date()))"
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
                clearPairingAfterHostRevocation(error)
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
            clearPairingAfterHostRevocation(error)
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
        if remoteDesktopLoggingEnabled {
            RemoteClientDesktopLogger.write(
                "power.transition.accepted",
                [
                    "action": action,
                    "availability_state": hostAvailabilityState.rawValue,
                    "availability_label": hostAvailabilityState.label,
                ]
            )
        }
        if action == "wake" {
            requestImmediateMirror(trigger: "power.\(action).accepted", syncScope: .revisionAware)
        } else {
            requestScheduledMirror(trigger: "power.\(action).accepted", syncScope: .revisionAware)
        }
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
        return RemoteSmartPollController.steadyDelaySeconds(
            availabilityState: hostAvailabilityState,
            consecutiveMirrorFailures: consecutiveMirrorFailures,
            userBaseIntervalSeconds: mirrorPollIntervalSeconds,
            appIsActive: NSApp.isActive,
            unchangedRevisionPollCount: unchangedRevisionPollCount,
            slowStatusPollCount: slowStatusPollCount
        )
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
        if kind == .authRejected {
            clearPairingAfterHostRevocation(error)
            return
        }
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
            return "호스트 관리 계층은 확인됐지만 Windows Remote Agent HTTP 첫 응답이 지연되고 있습니다. 호스트 앱/API 서버가 굼뜨거나 DB 작업에 막혔는지 확인하세요."
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
                await self?.runMirrorRemoteState(trigger: "mirror", syncScope: .revisionAware)
            }
        }
    }

    private func requestImmediateMirror(trigger: String, syncScope: RemotePayloadSyncScope = .revisionAware) {
        guard bootstrapEnabled, isPaired else { return }
        Task { [weak self] in
            await self?.runMirrorRemoteState(trigger: trigger, syncScope: syncScope)
        }
    }

    private func requestScheduledMirror(trigger: String, syncScope: RemotePayloadSyncScope = .revisionAware) {
        guard bootstrapEnabled, isPaired else { return }
        Task { [weak self] in
            let seconds: UInt64 = await MainActor.run {
                guard let self else { return 15 }
                return self.nextMirrorDelaySeconds()
            }
            try? await Task.sleep(nanoseconds: seconds * 1_000_000_000)
            guard !Task.isCancelled else { return }
            await self?.runMirrorRemoteState(trigger: trigger, syncScope: syncScope)
        }
    }

    private func enqueuePendingMirror(trigger: String, syncScope: RemotePayloadSyncScope) {
        if let pending = pendingMirrorRequest {
            pendingMirrorRequest = (
                trigger: "\(pending.trigger)+\(trigger)",
                syncScope: pending.syncScope.merged(with: syncScope)
            )
        } else {
            pendingMirrorRequest = (trigger: trigger, syncScope: syncScope)
        }
    }

    private func runMirrorRemoteState(trigger: String, syncScope: RemotePayloadSyncScope) async {
        guard !mirrorExecutionInProgress else {
            enqueuePendingMirror(trigger: trigger, syncScope: syncScope)
            return
        }
        mirrorExecutionInProgress = true
        await mirrorRemoteState(trigger: trigger, syncScope: syncScope)
        mirrorExecutionInProgress = false

        if let pending = pendingMirrorRequest {
            pendingMirrorRequest = nil
            await runMirrorRemoteState(trigger: pending.trigger, syncScope: pending.syncScope)
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
        await runMirrorRemoteState(trigger: "clientResumed", syncScope: .revisionAware)
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

    func progressMeterDisplayText(_ progress: RemoteProcess.Progress) -> String {
        if (progress.kind == "stamina" || progress.kind == "resource"),
           !progress.displayText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            return progress.displayText
        }
        return Self.percentageText(progress.percentage)
    }

    func trackBadgeDisplayText(_ progress: RemoteProcess.Progress) -> String {
        let projectedReadyAt = progress.readyAt ?? progress.projection?.readyAt
        let projectedRemainingSeconds = progress.remainingSeconds ?? progress.projection?.remainingSeconds
        if cycleProgressDisplayMode == .readyAt, let readyAt = projectedReadyAt {
            return "\(Self.formatCycleReadyAt(readyAt)) 완료"
        }
        if let remainingSeconds = projectedRemainingSeconds {
            return Self.formatRemainingDuration(seconds: remainingSeconds)
        }
        return progress.displayText
    }

    private static func percentageText(_ percentage: Double) -> String {
        "\(Int(min(max(percentage, 0), 100).rounded()))%"
    }

    private func refreshLocalProcessDisplay() {
        guard !processes.isEmpty else { return }
        let shouldProjectLocally = hostAvailabilityState != .online
        processes = processes.map {
            Self.processWithLocalProgress(
                $0,
                now: Date(),
                recomputePlayedToday: shouldProjectLocally,
                allowProjection: shouldProjectLocally
            )
        }
    }

    private static func processWithLocalProgress(
        _ process: RemoteProcess,
        now: Date,
        recomputePlayedToday: Bool,
        allowProjection: Bool
    ) -> RemoteProcess {
        let progress = allowProjection ? (localProgress(for: process, now: now) ?? process.progress) : process.progress
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
        if let existing, let projected = projectedProgress(from: existing, process: process, now: now) {
            return projected
        }
        if existing?.source == "server_tracked" {
            return existing
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
            schemaVersion: existing?.schemaVersion ?? 1,
            source: existing?.source ?? "timestamp_derived",
            kind: "cycle",
            percentage: percentage,
            displayText: Self.formatRemainingDuration(seconds: remainingSeconds),
            status: existing?.status ?? "ok",
            provider: existing?.provider,
            key: existing?.key,
            label: existing?.label,
            updatedAt: existing?.updatedAt,
            projection: existing?.projection,
            staminaCurrent: nil,
            staminaMax: nil,
            hoyolabGameID: existing?.hoyolabGameID,
            resourceIconURL: existing?.resourceIconURL,
            resourceIconURLs: existing?.resourceIconURLs,
            remainingSeconds: remainingSeconds,
            readyAt: now.addingTimeInterval(Double(remainingSeconds)).timeIntervalSince1970
        )
    }

    private static func projectedProgress(
        from progress: RemoteProcess.Progress,
        process: RemoteProcess,
        now: Date
    ) -> RemoteProcess.Progress? {
        guard let projection = progress.projection else { return nil }
        let nowTimestamp = now.timeIntervalSince1970
        switch projection.strategy {
        case "linear_recovery":
            guard let baseValue = projection.baseValue,
                  let maxValue = projection.maxValue,
                  maxValue > 0 else { return nil }
            let baseTimestamp = projection.baseTimestamp ?? progress.updatedAt ?? nowTimestamp
            let recoverySecondsPerUnit = projection.recoverySecondsPerUnit ?? Self.staminaRecoverySecondsPerPoint
            guard recoverySecondsPerUnit > 0 else { return nil }
            let elapsed = max(0, nowTimestamp - baseTimestamp)
            let recovered = floor(elapsed / recoverySecondsPerUnit)
            let projectedValue = min(maxValue, max(0, baseValue + recovered))
            let remainingSeconds = max(0, Int((maxValue - projectedValue) * recoverySecondsPerUnit))
            let readyAt = nowTimestamp + Double(remainingSeconds)
            return RemoteProcess.Progress(
                schemaVersion: progress.schemaVersion,
                source: progress.source,
                kind: progress.kind,
                percentage: min(max((projectedValue / maxValue) * 100.0, 0.0), 100.0),
                displayText: "\(Int(projectedValue))/\(Int(maxValue))",
                status: progress.status,
                provider: progress.provider,
                key: progress.key,
                label: progress.label,
                updatedAt: progress.updatedAt,
                projection: projection,
                staminaCurrent: Int(projectedValue),
                staminaMax: Int(maxValue),
                hoyolabGameID: progress.hoyolabGameID ?? process.hoyolabGameID,
                resourceIconURL: progress.resourceIconURL,
                resourceIconURLs: progress.resourceIconURLs,
                remainingSeconds: remainingSeconds,
                readyAt: readyAt
            )
        case "linear_percent_fill":
            guard let baseValue = projection.baseValue else { return nil }
            let maxValue = projection.maxValue ?? 100.0
            guard maxValue > 0 else { return nil }
            let baseTimestamp = projection.baseTimestamp ?? progress.updatedAt ?? nowTimestamp
            let fullRecoverySeconds = projection.fullRecoverySeconds ?? (24 * 60 * 60)
            guard fullRecoverySeconds > 0 else { return nil }
            let elapsed = max(0, nowTimestamp - baseTimestamp)
            let projectedValue = min(maxValue, max(0, baseValue + (elapsed * maxValue / fullRecoverySeconds)))
            let remainingSeconds = max(0, Int((maxValue - projectedValue) * fullRecoverySeconds / maxValue))
            let readyAt = nowTimestamp + Double(remainingSeconds)
            return RemoteProcess.Progress(
                schemaVersion: progress.schemaVersion,
                source: progress.source,
                kind: progress.kind,
                percentage: min(max(projectedValue, 0.0), 100.0),
                displayText: String(format: "%.1f%%", min(max(projectedValue, 0.0), 100.0)),
                status: progress.status,
                provider: progress.provider,
                key: progress.key,
                label: progress.label,
                updatedAt: progress.updatedAt,
                projection: projection,
                staminaCurrent: progress.staminaCurrent,
                staminaMax: progress.staminaMax,
                hoyolabGameID: progress.hoyolabGameID ?? process.hoyolabGameID,
                resourceIconURL: progress.resourceIconURL,
                resourceIconURLs: progress.resourceIconURLs,
                remainingSeconds: remainingSeconds,
                readyAt: readyAt
            )
        case "cycle_elapsed":
            guard let baseTimestamp = projection.baseTimestamp,
                  let cycleSeconds = projection.cycleSeconds,
                  cycleSeconds > 0 else { return nil }
            let elapsed = max(0, nowTimestamp - baseTimestamp)
            let percentage = min(max((elapsed / cycleSeconds) * 100.0, 0.0), 100.0)
            let remainingSeconds = max(0, Int(cycleSeconds - elapsed))
            let readyAt = nowTimestamp + Double(remainingSeconds)
            return RemoteProcess.Progress(
                schemaVersion: progress.schemaVersion,
                source: progress.source,
                kind: progress.kind,
                percentage: percentage,
                displayText: Self.formatRemainingDuration(seconds: remainingSeconds),
                status: progress.status,
                provider: progress.provider,
                key: progress.key,
                label: progress.label,
                updatedAt: progress.updatedAt,
                projection: projection,
                staminaCurrent: progress.staminaCurrent,
                staminaMax: progress.staminaMax,
                hoyolabGameID: progress.hoyolabGameID ?? process.hoyolabGameID,
                resourceIconURL: progress.resourceIconURL,
                resourceIconURLs: progress.resourceIconURLs,
                remainingSeconds: remainingSeconds,
                readyAt: readyAt
            )
        default:
            return nil
        }
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

    private func sortedDeviceList(_ devices: [RemoteDevice]) -> [RemoteDevice] {
        devices.sorted { lhs, rhs in
            let lhsRank = deviceSortRank(lhs)
            let rhsRank = deviceSortRank(rhs)
            if lhsRank != rhsRank { return lhsRank < rhsRank }
            let nameOrder = deviceSortName(lhs).compare(
                deviceSortName(rhs),
                options: [.caseInsensitive, .diacriticInsensitive, .widthInsensitive, .numeric],
                range: nil,
                locale: Self.koreanProcessSortLocale
            )
            if nameOrder != .orderedSame { return nameOrder == .orderedAscending }
            return lhs.id < rhs.id
        }
    }

    private func deviceSortRank(_ device: RemoteDevice) -> Int {
        if isCurrentDevice(device) { return 0 }
        if device.role == "host" { return 2 }
        return 1
    }

    private func deviceSortName(_ device: RemoteDevice) -> String {
        device.name.nilIfBlank
            ?? device.tailnetHostname?.nilIfBlank
            ?? device.tailnetIP?.nilIfBlank
            ?? device.id
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
            return "호스트에서 이 Mac의 페어링이 해제되어 로컬 토큰을 삭제했습니다. 다시 페어링하세요. (\(raw))"
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
        if let remoteDevices = try? await service.devices() {
            applyDevices(remoteDevices)
        }
    }

    func clearLocalPairing() {
        RemoteClientPreferences.savePairedDeviceID("")
        pairedDeviceID = ""
        tokenStore.delete()
        tokenText = ""
        devices = []
        pairingRecoveryMessage = "이 Mac의 로컬 토큰을 삭제했습니다. 서버 등록은 Windows 원격 설정에서 언페어링하세요."
        setupProgress = pairingRecoveryMessage
        message = pairingRecoveryMessage
    }

    private func clearPairingAfterHostRevocation(_ error: Error) {
        RemoteClientPreferences.savePairedDeviceID("")
        pairedDeviceID = ""
        tokenStore.delete()
        tokenText = ""
        devices = []
        setHostAvailability(.authRejected, clearPairingRecovery: false)
        let guidance = connectionGuidance(for: error)
        pairingRecoveryMessage = guidance
        setupProgress = guidance
        message = guidance
    }

    private func rememberPairedDeviceID(_ id: String) {
        RemoteClientPreferences.savePairedDeviceID(id)
        pairedDeviceID = id.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func applyDevices(_ remoteDevices: [RemoteDevice]) {
        devices = sortedDeviceList(remoteDevices)
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
        await applyReadiness(from: latestStatus, using: service)
        powerSetup = try? await service.powerSetup()
        fillDefaultSSHFields()
        if isPaired {
            _ = await verifyLocalSSHHealth(updateMessage: false)
        }

        if isPaired {
            setupProgress = "4/5 페어링 토큰 복구와 등록 디바이스 확인 중..."
            await recoverPairing(silent: true)
            if let remoteDevices = try? await service.devices() {
                applyDevices(remoteDevices)
            }
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

    private func updateSmartPollingSignals(latestStatus: RemoteStatus, willSyncPayload: Bool) {
        if willSyncPayload || lastStateRevision == nil || latestStatus.stateRevision != lastStateRevision {
            unchangedRevisionPollCount = 0
        } else {
            unchangedRevisionPollCount += 1
        }

        if RemoteSmartPollController.shouldTreatStatusAsSlow(durationMilliseconds: latestStatus.diagnostics?.durationMS) {
            slowStatusPollCount += 1
        } else {
            slowStatusPollCount = 0
        }
    }

    private func mirrorRemoteState(trigger: String = "mirror", syncScope: RemotePayloadSyncScope = .revisionAware) async {
        guard let client else { return }
        let service = RemoteDashboardService(client: client)
        let previousAvailabilityState = hostAvailabilityState
        guard let evaluation = await evaluateConnectivity(using: service, client: client, trigger: trigger, updateMessage: false) else {
            return
        }
        let latestStatus = evaluation.status
        let shouldRefreshSSHHealthAfterRecovery = shouldRefreshLocalSSHHealthAfterOnlineRecovery(
            previousState: previousAvailabilityState,
            decision: evaluation.decision
        )
        await applyReadiness(from: latestStatus, using: service)
        let revisionRequiresSync = evaluation.decision.shouldForcePayloadSync || latestStatus.stateRevision != lastStateRevision || lastStateRevision == nil
        let shouldSyncPayload = revisionRequiresSync || syncScope != .revisionAware
        updateSmartPollingSignals(latestStatus: latestStatus, willSyncPayload: shouldSyncPayload)
        guard shouldSyncPayload else {
            refreshLocalProcessDisplay()
            if shouldRefreshSSHHealthAfterRecovery {
                await refreshLocalSSHHealthAfterOnlineRecovery(using: service)
            }
            await resumePendingMoonlightWakeActionIfReady(trigger: trigger)
            clearPendingMoonlightWakeActionIfBlocked()
            return
        }
        lastStateRevision = latestStatus.stateRevision
        let effectiveSyncScope: RemotePayloadSyncScope = evaluation.decision.shouldForcePayloadSync ? .forceFull : syncScope
        switch effectiveSyncScope {
        case .revisionAware, .forceFull:
            await syncRemotePayloads(using: service, client: client)
        case .forceProcesses:
            await syncRemoteProcesses(using: service, client: client)
        }
        if shouldRefreshSSHHealthAfterRecovery {
            await refreshLocalSSHHealthAfterOnlineRecovery(using: service)
        }
        await resumePendingMoonlightWakeActionIfReady(trigger: trigger)
        clearPendingMoonlightWakeActionIfBlocked()
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

    private func applyReadiness(from status: RemoteStatus, using service: RemoteDashboardService) async {
        if status.readiness == nil || status.readiness?.tailscaleReadiness.details == nil {
            readiness = try? await service.readiness()
        } else {
            readiness = status.readiness
        }
    }

    private func syncRemoteProcesses(using service: RemoteDashboardService, client: RemoteAPIClient) async {
        do {
            let remoteProcesses = try await service.processes()
            RemoteClientCache.saveProcesses(remoteProcesses)
            processes = remoteProcesses.map { Self.processWithLocalProgress($0, now: Date(), recomputePlayedToday: false, allowProjection: false) }
            await RemoteClientCache.cacheIcons(for: remoteProcesses, baseURL: client.baseURL)
        } catch {
            if processes.isEmpty {
                processes = RemoteClientCache.loadProcesses()
            }
            refreshLocalProcessDisplay()
            handlePayloadSyncFailure(
                error,
                fallbackMessage: "Remote Agent 상태는 응답했지만 게임 실행 상태 동기화에 실패했습니다. 캐시 데이터와 standalone 진행률을 유지합니다. (\(error.localizedDescription))"
            )
        }
    }

    private func syncRemotePayloads(using service: RemoteDashboardService, client: RemoteAPIClient) async {
        do {
            dashboardSummary = try await service.dashboardSummary()
            beholderIncidents = try await service.beholderIncidents()
            let remoteProcesses = try await service.processes()
            RemoteClientCache.saveProcesses(remoteProcesses)
            processes = remoteProcesses.map { Self.processWithLocalProgress($0, now: Date(), recomputePlayedToday: false, allowProjection: false) }
            await RemoteClientCache.cacheIcons(for: remoteProcesses, baseURL: client.baseURL)
        } catch {
            if processes.isEmpty {
                processes = RemoteClientCache.loadProcesses()
            }
            refreshLocalProcessDisplay()
            handlePayloadSyncFailure(error)
        }
    }

    private func refreshDashboardSummaryForDisplay() async {
        guard showPlaySummary, dashboardSummary == nil, let service else { return }
        do {
            dashboardSummary = try await service.dashboardSummary()
        } catch {
            handlePayloadSyncFailure(
                error,
                fallbackMessage: "플레이 요약을 불러오지 못했습니다. 연결 상태를 확인한 뒤 새로고침하세요. (\(error.localizedDescription))"
            )
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
            updateSmartPollingSignals(latestStatus: latestStatus, willSyncPayload: true)
            lastStateRevision = latestStatus.stateRevision
            await applyReadiness(from: latestStatus, using: service)
            dashboardSummary = try await service.dashboardSummary()
            beholderIncidents = try await service.beholderIncidents()
            gameLinks = try await service.gameLinks()
            mobileSessions = try await service.activeMobileSessions()
            powerSetup = try? await service.powerSetup()
            fillDefaultSSHFields()
            _ = await verifyLocalSSHHealth(updateMessage: false)
            let remoteProcesses = try await service.processes()
            RemoteClientCache.saveProcesses(remoteProcesses)
            processes = remoteProcesses.map { Self.processWithLocalProgress($0, now: Date(), recomputePlayedToday: false, allowProjection: false) }
            await RemoteClientCache.cacheIcons(for: remoteProcesses, baseURL: client.baseURL)
            if includeDevices {
                applyDevices(try await service.devices())
            }
            let hadPendingMoonlightWakeAction = pendingMoonlightWakeAction != nil
            await resumePendingMoonlightWakeActionIfReady(trigger: "refresh")
            if !hadPendingMoonlightWakeAction {
                message = "동기화 완료: 게임 \(processes.count)개, 연결 \(gameLinks.count)개, 모바일 세션 \(mobileSessions.count)개"
            }
        } catch {
            handlePayloadSyncFailure(error)
            if isAuthFailure(error) {
                setupProgress = pairingRecoveryMessage
            }
        }
    }


    func discoverTailscale() async {
        message = "Tailscale CLI 확인 중..."
        let snapshot = await TailscaleDiscovery.activateNetwork()
        localTailscale = snapshot
        if let url = snapshot.suggestedBaseURLs.first {
            baseURLText = url
            setupProgress = "Tailscale 후보를 Base URL로 적용했습니다: \(url)"
            message = setupProgress
        } else {
            message = snapshot.message
        }
    }

    func activateLocalTailscale() async {
        isLoading = true
        defer { isLoading = false }
        setupProgress = "Mac Tailscale 기반환경을 설치/실행/활성화하는 중..."
        let snapshot = await TailscaleDiscovery.activateNetwork()
        localTailscale = snapshot
        setupProgress = snapshot.running ? "Mac Tailscale 활성화 완료: \(snapshot.selfIPs.joined(separator: ", "))" : snapshot.message
        message = setupProgress
    }

    func deactivateLocalTailscale() async {
        isLoading = true
        defer { isLoading = false }
        setupProgress = "Mac Tailscale 네트워크를 비활성화하는 중..."
        let snapshot = await TailscaleDiscovery.deactivateNetwork()
        localTailscale = snapshot
        setupProgress = snapshot.message
        message = setupProgress
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

    private func startLaunchChase(processID: String, refreshAfterMilliseconds: Int?) {
        launchChaseTasks[processID]?.cancel()
        let delays = RemoteSmartPollController.launchChaseDelaysNanoseconds(refreshAfterMilliseconds: refreshAfterMilliseconds)
        launchChaseTasks[processID] = Task { [weak self] in
            var resolved = false
            for delay in delays {
                if delay > 0 {
                    try? await Task.sleep(nanoseconds: delay)
                }
                guard !Task.isCancelled else { return }
                await self?.runMirrorRemoteState(trigger: "launch.chase", syncScope: .forceProcesses)
                guard !Task.isCancelled else { return }
                if self?.isLaunchChaseResolved(processID: processID) == true {
                    resolved = true
                    break
                }
            }
            self?.finishLaunchChase(processID: processID, resolved: resolved)
        }
    }

    private func isLaunchChaseResolved(processID: String) -> Bool {
        if hostAvailabilityState != .online { return true }
        return processes.first { $0.id == processID }?.isRunning == true
    }

    private func finishLaunchChase(processID: String, resolved: Bool) {
        pendingLaunchProcessIDs.remove(processID)
        launchChaseTasks[processID] = nil
        if resolved, hostAvailabilityState == .online {
            message = "게임 실행 상태를 확인했습니다."
        } else if hostAvailabilityState == .online {
            message = "게임 실행 명령을 전달했습니다. 실행 상태는 다음 동기화에서 계속 확인합니다."
        }
    }

    private func startStopChase(processID: String, refreshAfterMilliseconds: Int?) {
        stopChaseTasks[processID]?.cancel()
        let delays = RemoteSmartPollController.launchChaseDelaysNanoseconds(refreshAfterMilliseconds: refreshAfterMilliseconds)
        stopChaseTasks[processID] = Task { [weak self] in
            var resolved = false
            for delay in delays {
                if delay > 0 {
                    try? await Task.sleep(nanoseconds: delay)
                }
                guard !Task.isCancelled else { return }
                await self?.runMirrorRemoteState(trigger: "stop.chase", syncScope: .forceProcesses)
                guard !Task.isCancelled else { return }
                if self?.isStopChaseResolved(processID: processID) == true {
                    resolved = true
                    break
                }
            }
            self?.finishStopChase(processID: processID, resolved: resolved)
        }
    }

    private func isStopChaseResolved(processID: String) -> Bool {
        if hostAvailabilityState != .online { return true }
        return processes.first { $0.id == processID }?.isRunning != true
    }

    private func finishStopChase(processID: String, resolved: Bool) {
        pendingStopProcessIDs.remove(processID)
        stopChaseTasks[processID] = nil
        if resolved, hostAvailabilityState == .online {
            message = "게임 종료 상태를 확인했습니다."
        } else if hostAvailabilityState == .online {
            message = "게임 종료 명령을 전달했습니다. 종료 상태는 다음 동기화에서 계속 확인합니다."
        }
    }

    func stop(_ process: RemoteProcess) async {
        guard isStopEnabled(process) else {
            message = hostAvailabilityState == .online ? "게임 종료를 요청할 수 없는 상태입니다." : "호스트 연결이 복구된 뒤 실행 중 게임을 종료할 수 있습니다."
            return
        }
        guard let service else { return }
        let processID = process.id
        pendingStopProcessIDs.insert(processID)
        do {
            let result = try await service.stopProcess(id: process.id)
            message = result.message
            if result.accepted {
                startStopChase(processID: processID, refreshAfterMilliseconds: result.refreshAfterMS)
            } else {
                pendingStopProcessIDs.remove(processID)
            }
        } catch {
            pendingStopProcessIDs.remove(processID)
            stopChaseTasks[processID]?.cancel()
            stopChaseTasks[processID] = nil
            if case RemoteAPIError.http(let statusCode, _) = error, statusCode == 409 {
                await runMirrorRemoteState(trigger: "stop.conflict", syncScope: .forceProcesses)
                message = "호스트에서 실행 중인 게임 프로세스를 찾지 못했습니다. 상태를 다시 동기화했습니다."
                return
            }
            if let client {
                _ = await evaluateConnectivity(using: service, client: client, trigger: "stop.failure")
            }
            message = error.localizedDescription
        }
    }

    func launch(_ process: RemoteProcess) async {
        guard isLaunchEnabled(process) else {
            message = hostAvailabilityState == .online ? "이미 실행 중이거나 실행 확인 중입니다." : "호스트 연결이 복구된 뒤 실행할 수 있습니다. 캐시된 게임 상태는 standalone으로 계속 갱신합니다."
            return
        }
        guard let service else { return }
        let processID = process.id
        pendingLaunchProcessIDs.insert(processID)
        do {
            let result = try await service.launchProcess(id: process.id)
            message = result.message
            if result.accepted {
                startLaunchChase(processID: processID, refreshAfterMilliseconds: result.refreshAfterMS)
                if moonlightBindingEnabled, moonlightSnapshot.readiness == .ready {
                    _ = await ensureMoonlightDesktopVisible(trigger: "launch.\(processID)")
                }
            } else {
                pendingLaunchProcessIDs.remove(processID)
            }
        } catch {
            pendingLaunchProcessIDs.remove(processID)
            launchChaseTasks[processID]?.cancel()
            launchChaseTasks[processID] = nil
            if let client {
                _ = await evaluateConnectivity(using: service, client: client, trigger: "launch.failure")
            }
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
        if remoteDesktopLoggingEnabled {
            RemoteClientDesktopLogger.write(
                "power.local_ssh.started",
                [
                    "action": action,
                    "host": powerConfig.sshHost,
                    "user": powerConfig.sshUser,
                    "ssh_identity": identityStatus,
                ]
            )
        }
        do {
            message = try await LocalSSHPowerManager.run(action: action, config: powerConfig)
            if remoteDesktopLoggingEnabled {
                RemoteClientDesktopLogger.write("power.local_ssh", ["action": action, "host": powerConfig.sshHost, "user": powerConfig.sshUser, "status": "accepted", "ssh_identity": identityStatus, "message": message])
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
            await applyReadiness(from: latestStatus, using: service)
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
            rememberPairedDeviceID(response.id)
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
            rememberPairedDeviceID(response.id)
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

    func refreshDevices() async {
        guard let service else { return }
        do {
            applyDevices(try await service.devices())
            message = "등록 디바이스 \(devices.count)개를 불러왔습니다."
        } catch {
            message = error.localizedDescription
        }
    }
}

private extension String {
    var nilIfBlank: String? {
        let trimmed = trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }
}
