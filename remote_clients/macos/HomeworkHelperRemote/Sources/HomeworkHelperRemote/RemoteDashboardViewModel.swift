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
    func powerConfig() async throws -> RemotePowerConfigResponse { try await client.powerConfig() }
    func powerSetup() async throws -> RemotePowerSetupResponse { try await client.powerSetup() }
    func registerPowerSSHKey(publicKey: String, label: String) async throws -> RemoteSSHKeyRegistrationResponse { try await client.registerPowerSSHKey(publicKey: publicKey, label: label) }
    func smartThingsDevices(cliPath: String?) async throws -> RemoteSmartThingsDevicesResponse { try await client.smartThingsDevices(cliPath: cliPath) }
    func processes() async throws -> [RemoteProcess] { try await client.processes() }
    func devices() async throws -> [RemoteDevice] { try await client.devices() }
    func startMobileSession(gameLinkID: String) async throws -> RemoteMobileSession { try await client.startMobileSession(gameLinkID: gameLinkID) }
    func endMobileSession(sessionID: String) async throws -> RemoteMobileSession { try await client.endMobileSession(sessionID: sessionID) }
    func createGameLink(processID: String, androidPackageName: String) async throws -> RemoteGameLink {
        try await client.createGameLink(processID: processID, androidPackageName: androidPackageName)
    }
    func launchProcess(id: String) async throws -> RemoteCommandResult { try await client.launchProcess(id: id) }
    func power(action: String) async throws -> RemoteCommandResult { try await client.power(action: action) }
    func savePowerConfig(_ config: RemotePowerConfigPayload) async throws -> RemotePowerConfigResponse { try await client.savePowerConfig(config) }
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
    private static let defaults = UserDefaults.standard
    private static let baseURLKey = "remote.baseURL"
    private static let deviceNameKey = "remote.deviceName"
    private static let powerConfigKey = "remote.powerConfig"
    private static let desktopLoggingEnabledKey = "remote.desktopLoggingEnabled"

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

    static func loadPowerConfig() -> RemotePowerConfigPayload {
        guard let data = defaults.data(forKey: powerConfigKey),
              let config = try? JSONDecoder().decode(RemotePowerConfigPayload.self, from: data) else {
            return RemotePowerConfigPayload()
        }
        return config
    }

    static func savePowerConfig(_ config: RemotePowerConfigPayload) {
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
        didSet { tokenStore.save(tokenText) }
    }
    @Published var pairingCode = ""
    @Published var deviceName = RemoteClientPreferences.loadDeviceName() {
        didSet { RemoteClientPreferences.saveDeviceName(deviceName) }
    }
    @Published var gameLinkProcessID = ""
    @Published var gameLinkAndroidPackage = ""
    @Published var powerConfig = RemoteClientPreferences.loadPowerConfig() {
        didSet { RemoteClientPreferences.savePowerConfig(powerConfig) }
    }
    @Published var powerConfigResponse: RemotePowerConfigResponse?
    @Published var powerSetup: RemotePowerSetupResponse?
    @Published var localSSHKey: LocalSSHKeyPair?
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
    @Published var status: RemoteStatus?
    @Published var dashboardSummary: RemoteDashboardSummary?
    @Published var beholderIncidents: [RemoteBeholderIncident] = []
    @Published var gameLinks: [RemoteGameLink] = []
    @Published var mobileSessions: [RemoteMobileSession] = []
    @Published var processes: [RemoteProcess] = RemoteClientCache.loadProcesses()
    @Published var devices: [RemoteDevice] = []
    @Published var launchAtLoginEnabled = RemoteLoginItemManager.isEnabled
    @Published var isLoading = false
    @Published var message = "Remote Agent에 연결하세요."


    var setupChecklist: [(String, String, Bool)] {
        [
            ("1. Mac Tailscale", localTailscale?.running == true ? "준비됨: \(localTailscale?.selfIPs.joined(separator: ", ") ?? "")" : "Tailscale 찾기/자동 실행 필요", localTailscale?.running == true),
            ("2. Windows 서버", hostConnectionState == "offline" ? "호스트 서버가 꺼져 있거나 Remote Agent에 연결할 수 없습니다." : (readiness?.serverModeReadiness.color == "green" ? readiness?.serverModeReadiness.message ?? "준비됨" : "Windows 앱의 설정 > 원격 설정에서 서버 모드와 페어링 코드를 확인"), hostConnectionState != "offline" && readiness?.serverModeReadiness.color == "green"),
            ("3. 페어링", pairingRecoveryMessage.isEmpty ? (tokenText.isEmpty ? "페어링 코드를 입력해 이 Mac을 등록" : "Keychain 토큰 저장됨") : pairingRecoveryMessage, !tokenText.isEmpty && !pairingRecoveryMessage.contains("재페어링")),
            ("4. 전원 관리", powerConfigResponse?.readiness.supportedActions.isEmpty == false ? "지원 명령: \(powerConfigResponse?.readiness.supportedActions.joined(separator: ", ") ?? "")" : "SmartThings/SSH 설정 저장 필요", powerConfigResponse?.readiness.supportedActions.isEmpty == false),
            ("5. 서버 Tailscale", serverTailscaleEnsure?.ready == true || readiness?.tailscaleReadiness.color == "green" ? "서버 Tailscale 준비됨" : "페어링 후 서버 Tailscale 확인/복구 실행", serverTailscaleEnsure?.ready == true || readiness?.tailscaleReadiness.color == "green")
        ]
    }

    var isPaired: Bool { !tokenText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }

    private let tokenStore: any RemoteTokenStore
    private var mirrorTask: Task<Void, Never>?

    init(tokenStore: any RemoteTokenStore = KeychainTokenStore()) {
        self.tokenStore = tokenStore
        tokenText = tokenStore.load()
    }

    deinit {
        mirrorTask?.cancel()
    }

    private var client: RemoteAPIClient? {
        guard let url = URL(string: baseURLText), url.scheme != nil else { return nil }
        return RemoteAPIClient(baseURL: url, bearerToken: tokenText.isEmpty ? nil : tokenText)
    }

    private var service: RemoteDashboardService? {
        guard let client else { return nil }
        return RemoteDashboardService(client: client)
    }

    private func applyHostPowerConfig(_ config: RemotePowerConfigPayload) {
        powerConfig = config.preservingLocalWake(from: powerConfig)
    }

    private func fillDefaultSSHFields() {
        if powerConfig.sshUser.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
           let hostUser = powerSetup?.user.trimmingCharacters(in: .whitespacesAndNewlines),
           !hostUser.isEmpty {
            powerConfig.sshUser = hostUser
        }
        if powerConfig.sshKeyPath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            powerConfig.sshKeyPath = LocalSSHKeyManager.defaultPrivateKeyPath
        }
    }

    private var baseURLNeedsTailnetSuggestion: Bool {
        let trimmed = baseURLText.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty || trimmed.contains("127.0.0.1") || trimmed.contains("localhost")
    }

    func bootstrap() async {
        startMirroring()
        setupProgress = "저장된 연결 정보와 Tailscale 후보를 확인 중..."
        let snapshot = await TailscaleDiscovery.status()
        localTailscale = snapshot
        if baseURLNeedsTailnetSuggestion, let url = snapshot.suggestedBaseURLs.first {
            baseURLText = url
            setupProgress = "저장된 Base URL이 없어서 Windows Desktop 후보를 적용했습니다: \(url)"
        }
        if let logging = try? await service?.remoteLoggingConfig() {
            if logging.enabled {
                remoteDesktopLoggingEnabled = true
                RemoteClientPreferences.saveDesktopLoggingEnabled(true)
            }
            remoteDesktopLoggingPath = logging.path
        }
        if isPaired {
            await recoverPairing(silent: true)
        }
        await refresh()
        if pairingRecoveryMessage.contains("재페어링") {
            setupProgress = "Windows 앱의 [설정 > 원격 설정]에서 새 페어링 코드를 발급해 입력하세요."
        } else if status != nil {
            setupProgress = isPaired ? "저장된 Keychain 토큰으로 자동 연결했습니다." : "서버를 찾았습니다. Windows 원격 설정에서 페어링 코드를 발급해 입력하세요."
        } else if snapshot.running {
            setupProgress = "Tailscale은 준비됐지만 Windows Remote Agent에 연결하지 못했습니다. Windows 앱의 서버 모드와 방화벽을 확인하세요."
        } else {
            setupProgress = "Tailscale 또는 Windows Remote Agent가 아직 준비되지 않았습니다. 자동 설정 점검을 실행하세요."
        }
    }

    func startMirroring() {
        guard mirrorTask == nil else { return }
        mirrorTask = Task { [weak self] in
            while !Task.isCancelled {
                let seconds: UInt64 = await MainActor.run { NSApp.isActive ? 15 : 60 }
                try? await Task.sleep(nanoseconds: seconds * 1_000_000_000)
                guard !Task.isCancelled else { break }
                await self?.mirrorRemoteState()
            }
        }
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

    func cachedIconURL(for process: RemoteProcess) -> URL? {
        RemoteClientCache.cachedIconURL(for: process)
    }

    func cachedResourceIconURL(for process: RemoteProcess) -> URL? {
        RemoteClientCache.cachedResourceIconURL(for: process)
    }

    func remoteIconURL(for process: RemoteProcess) -> URL? {
        guard let client else { return nil }
        return RemoteClientCache.remoteIconURL(for: process, baseURL: client.baseURL)
    }

    func remoteResourceIconURL(for process: RemoteProcess) -> URL? {
        guard let client else { return nil }
        return RemoteClientCache.remoteResourceIconURL(for: process, baseURL: client.baseURL)
    }

    private func connectionGuidance(for error: Error) -> String {
        let raw = error.localizedDescription
        if raw.contains("HTTP 401") || raw.contains("HTTP 403") {
            return "페어링 토큰이 없거나 만료되었습니다. Windows 앱의 [설정 > 원격 설정]에서 새 페어링 코드를 발급하세요. (\(raw))"
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
        do {
            let refreshed = try await service?.refreshToken()
            if let refreshed {
                tokenText = refreshed.token
                pairingRecoveryMessage = "토큰 갱신 완료: \(refreshed.name)"
                setupProgress = "저장된 페어링을 확인하고 Keychain 토큰을 갱신했습니다."
                devices = (try? await service?.devices()) ?? devices
            }
        } catch {
            let guidance = connectionGuidance(for: error)
            if guidance.contains("페어링 토큰") || guidance.contains("HTTP 401") || guidance.contains("HTTP 403") {
                tokenText = ""
                devices = []
                pairingRecoveryMessage = "저장된 토큰이 만료/폐기되었습니다. 재페어링이 필요합니다."
                setupProgress = "Windows 앱의 [설정 > 원격 설정]에서 새 페어링 코드를 발급해 입력하세요."
            } else {
                pairingRecoveryMessage = guidance
                setupProgress = guidance
            }
            if !silent {
                message = setupProgress
            }
        }
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
        setupProgress = "1/4 Mac Tailscale 확인 중..."
        let local = await TailscaleDiscovery.ensureReady()
        localTailscale = local
        if let url = local.suggestedBaseURLs.first, baseURLText.contains("127.0.0.1") || baseURLText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            baseURLText = url
        }

        guard let client else {
            setupProgress = "Base URL이 올바르지 않습니다."
            message = setupProgress
            return
        }
        let service = RemoteDashboardService(client: client)
        do {
            setupProgress = "2/4 Windows Remote Agent 상태 확인 중..."
            status = try await service.status()
            hostConnectionState = "online"
            if let statusReadiness = status?.readiness {
                readiness = statusReadiness
            } else {
                readiness = try? await service.readiness()
            }
            powerConfigResponse = try? await service.powerConfig()
            powerSetup = try? await service.powerSetup()
            if let config = powerConfigResponse?.config, config.hasAnyPowerSetting { applyHostPowerConfig(config) }
            fillDefaultSSHFields()

            if isPaired {
                setupProgress = "3/4 페어링 토큰 복구와 등록 디바이스 확인 중..."
                await recoverPairing(silent: true)
                devices = (try? await service.devices()) ?? devices
                serverTailscaleEnsure = try? await service.ensureServerTailscale()
                status = try await service.status()
                readiness = status?.readiness
            } else {
                setupProgress = "3/4 페어링 대기: Windows 앱의 설정 > 원격 설정에서 코드를 발급해 입력하세요."
            }

            setupProgress = isPaired ? "4/4 자동 설정 점검 완료. 전원 설정이 비어 있으면 아래 값을 저장하세요." : "페어링 코드를 입력하면 자동 설정을 계속할 수 있습니다."
            message = setupProgress
        } catch {
            let guidance = connectionGuidance(for: error)
            setupProgress = guidance
            message = guidance
        }
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
            status = try await service.status()
            readiness = status?.readiness
            message = serverTailscaleEnsure?.message ?? "서버 Tailscale 확인 완료"
        } catch {
            message = connectionGuidance(for: error)
        }
    }

    func applySuggestedPowerHost() {
        if let host = URL(string: baseURLText)?.host {
            powerConfig.sshHost = host
            message = "Base URL에서 SSH host를 채웠습니다. 사용자, 키 경로, SmartThings 값은 실제 전원 제어 환경에 맞게 입력하세요."
        } else {
            message = "Base URL에서 SSH host를 추출하지 못했습니다."
        }
    }

    func refresh() async {
        guard let client else {
            message = "Remote Agent URL이 올바르지 않습니다."
            return
        }
        await refresh(using: RemoteDashboardService(client: client), includeDevices: !tokenText.isEmpty)
    }

    private func mirrorRemoteState() async {
        guard let client else { return }
        let service = RemoteDashboardService(client: client)
        do {
            status = try await service.status()
            hostConnectionState = "online"
            if let statusReadiness = status?.readiness {
                readiness = statusReadiness
            } else {
                readiness = try? await service.readiness()
            }
            processes = try await service.processes()
            RemoteClientCache.saveProcesses(processes)
            await RemoteClientCache.cacheIcons(for: processes, baseURL: client.baseURL)
        } catch {
            if processes.isEmpty {
                processes = RemoteClientCache.loadProcesses()
            }
            hostConnectionState = "offline"
            message = connectionGuidance(for: error)
        }
    }

    private func refresh(using service: RemoteDashboardService, includeDevices: Bool) async {
        isLoading = true
        defer { isLoading = false }
        do {
            // Keep refreshes sequential. The Remote Agent's file-backed device
            // registry updates token last-seen metadata during auth checks, so
            // parallel authenticated requests can race on that registry file.
            status = try await service.status()
            hostConnectionState = "online"
            if let statusReadiness = status?.readiness {
                readiness = statusReadiness
            } else {
                readiness = try? await service.readiness()
            }
            dashboardSummary = try await service.dashboardSummary()
            beholderIncidents = try await service.beholderIncidents()
            gameLinks = try await service.gameLinks()
            mobileSessions = try await service.activeMobileSessions()
            powerConfigResponse = try await service.powerConfig()
            powerSetup = try? await service.powerSetup()
            if let config = powerConfigResponse?.config, config.hasAnyPowerSetting { applyHostPowerConfig(config) }
            fillDefaultSSHFields()
            processes = try await service.processes()
            RemoteClientCache.saveProcesses(processes)
            if let client {
                await RemoteClientCache.cacheIcons(for: processes, baseURL: client.baseURL)
            }
            if includeDevices {
                devices = try await service.devices()
            }
            message = "동기화 완료: 게임 \(processes.count)개, 연결 \(gameLinks.count)개, 모바일 세션 \(mobileSessions.count)개"
        } catch {
            let guidance = connectionGuidance(for: error)
            if guidance.contains("연결하지 못했습니다") { hostConnectionState = "offline" }
            if processes.isEmpty {
                processes = RemoteClientCache.loadProcesses()
            }
            message = guidance
            setupProgress = guidance
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
        guard let service else { return }
        do {
            let result = try await service.launchProcess(id: process.id)
            message = result.message
            await refresh()
        } catch {
            message = error.localizedDescription
        }
    }

    func isPowerActionEnabled(_ action: String) -> Bool {
        if action == "wake", powerConfig.localWakeConfigured { return true }
        if ["shutdown", "sleep", "restart"].contains(action), powerConfig.localSSHConfigured { return true }
        guard let status else { return false }
        guard status.capabilities.powerControl, status.power?.configured == true else { return false }
        let supported = status.supportedPowerActions
        return supported.isEmpty || supported.contains(action)
    }

    func power(_ action: String) async {
        guard isPowerActionEnabled(action) else {
            message = "전원 제어 adapter가 설정되지 않았거나 지원하지 않는 명령입니다."
            return
        }
        if remoteDesktopLoggingEnabled {
            RemoteClientDesktopLogger.write("power.click", ["action": action])
        }
        if action == "wake", powerConfig.localWakeConfigured {
            await localWake()
            return
        }
        if ["shutdown", "sleep", "restart"].contains(action), powerConfig.localSSHConfigured {
            await localSSH(action)
            return
        }
        guard let client else { return }
        do {
            let service = RemoteDashboardService(client: client)
            let result = try await service.power(action: action)
            message = result.message
            await refresh()
        } catch {
            if action == "wake" {
                await localWake()
            } else {
                message = error.localizedDescription
            }
        }
    }

    func localWake() async {
        do {
            message = try await LocalPowerWakeManager.wake(config: powerConfig)
            if remoteDesktopLoggingEnabled { RemoteClientDesktopLogger.write("power.local_wake", ["device_id": powerConfig.smartthingsDeviceID]) }
        } catch {
            message = error.localizedDescription
        }
    }

    func localSSH(_ action: String) async {
        do {
            message = try await LocalSSHPowerManager.run(action: action, config: powerConfig)
            if remoteDesktopLoggingEnabled {
                RemoteClientDesktopLogger.write("power.local_ssh", ["action": action, "host": powerConfig.sshHost, "user": powerConfig.sshUser, "status": "accepted"])
            }
        } catch {
            message = error.localizedDescription
            if remoteDesktopLoggingEnabled {
                RemoteClientDesktopLogger.write("power.local_ssh", ["action": action, "host": powerConfig.sshHost, "user": powerConfig.sshUser, "status": "failed", "message": error.localizedDescription])
            }
        }
    }


    func refreshPowerSetup() async {
        guard let service else { return }
        do {
            powerSetup = try await service.powerSetup()
            if powerConfig.smartthingsCLIPath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                if let local = LocalPowerWakeManager.smartThingsCLICandidates().first {
                    powerConfig.smartthingsCLIPath = local
                } else if let first = powerSetup?.smartthingsCLICandidates.first {
                    powerConfig.smartthingsCLIPath = first
                }
            }
            fillDefaultSSHFields()
            message = powerSetup?.message ?? "전원 준비 상태 확인 완료"
        } catch {
            message = connectionGuidance(for: error)
        }
    }

    func generateAndSendSSHKey() async {
        guard let service else {
            message = "Remote Agent URL이 올바르지 않습니다."
            return
        }
        guard isPaired else {
            message = "SSH key 등록은 페어링 후 사용할 수 있습니다."
            return
        }
        isLoading = true
        defer { isLoading = false }
        do {
            let key = try await LocalSSHKeyManager.ensureKeyPair(privateKeyPath: powerConfig.sshKeyPath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? LocalSSHKeyManager.defaultPrivateKeyPath : powerConfig.sshKeyPath)
            localSSHKey = key
            powerConfig.sshKeyPath = key.privateKeyPath
            let result = try await service.registerPowerSSHKey(publicKey: key.publicKey, label: deviceName)
            powerSetup = try? await service.powerSetup()
            message = result.message
        } catch {
            message = connectionGuidance(for: error)
        }
    }

    func probeSmartThingsDevices() async {
        guard let service else { return }
        do {
            let cliPath = powerConfig.smartthingsCLIPath.trimmingCharacters(in: .whitespacesAndNewlines)
            let result: RemoteSmartThingsDevicesResponse
            if LocalPowerWakeManager.isLocalSmartThingsCLIPath(cliPath) {
                result = await LocalPowerWakeManager.probeDevices(cliPath: cliPath)
                if remoteDesktopLoggingEnabled {
                    RemoteClientDesktopLogger.write(
                        "power.smartthings.local_devices",
                        ["available": String(result.available), "cli_path": result.cliPath ?? "", "candidates": String(result.deviceCandidates.count), "message": result.message]
                    )
                }
            } else {
                result = try await service.smartThingsDevices(cliPath: cliPath.isEmpty ? nil : cliPath)
            }
            smartThingsDevices = result.devices
            smartThingsDeviceCandidates = result.deviceCandidates
            if let cliPath = result.cliPath, powerConfig.smartthingsCLIPath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                powerConfig.smartthingsCLIPath = cliPath
            }
            message = result.message
        } catch {
            message = connectionGuidance(for: error)
        }
    }

    func applySmartThingsDevice(_ candidate: RemoteSmartThingsDeviceCandidate) {
        powerConfig.smartthingsDeviceID = candidate.id
        message = "SmartThings device id 후보를 적용했습니다. 전원 설정 저장을 누르세요: \(candidate.name)"
    }


    private func completePairingOnboarding(using service: RemoteDashboardService) async {
        setupProgress = "PIN 확인 완료: Tailscale, SSH key, SmartThings 전원 설정을 자동 점검합니다."
        serverTailscaleEnsure = try? await service.ensureServerTailscale()
        powerSetup = try? await service.powerSetup()
        if powerConfig.smartthingsCLIPath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            if let local = LocalPowerWakeManager.smartThingsCLICandidates().first {
                powerConfig.smartthingsCLIPath = local
            } else if let first = powerSetup?.smartthingsCLICandidates.first {
                powerConfig.smartthingsCLIPath = first
            }
        }
        if powerConfig.sshHost.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, let host = URL(string: baseURLText)?.host {
            powerConfig.sshHost = host
        }
        fillDefaultSSHFields()

        do {
            let key = try await LocalSSHKeyManager.ensureKeyPair(privateKeyPath: powerConfig.sshKeyPath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? LocalSSHKeyManager.defaultPrivateKeyPath : powerConfig.sshKeyPath)
            localSSHKey = key
            powerConfig.sshKeyPath = key.privateKeyPath
            _ = try await service.registerPowerSSHKey(publicKey: key.publicKey, label: deviceName)
        } catch {
            setupProgress = "SSH key 자동 등록은 실패했습니다. Windows 원격 설정 또는 mac 전원 설정에서 다시 시도하세요: \(error.localizedDescription)"
        }

        let smartThingsCLIPath = powerConfig.smartthingsCLIPath.trimmingCharacters(in: .whitespacesAndNewlines)
        if smartThingsCLIPath.isEmpty == false {
            let result: RemoteSmartThingsDevicesResponse?
            if LocalPowerWakeManager.isLocalSmartThingsCLIPath(smartThingsCLIPath) {
                result = await LocalPowerWakeManager.probeDevices(cliPath: smartThingsCLIPath)
                if let result, remoteDesktopLoggingEnabled {
                    RemoteClientDesktopLogger.write(
                        "power.smartthings.local_devices",
                        ["available": String(result.available), "cli_path": result.cliPath ?? "", "candidates": String(result.deviceCandidates.count), "message": result.message]
                    )
                }
            } else {
                result = try? await service.smartThingsDevices(cliPath: smartThingsCLIPath)
            }
            if let result {
                smartThingsDevices = result.devices
                smartThingsDeviceCandidates = result.deviceCandidates
                if result.deviceCandidates.count == 1 {
                    powerConfig.smartthingsDeviceID = result.deviceCandidates[0].id
                }
            }
        }

        let hostPowerConfig = powerConfig.hostSafeForRemoteSave()
        if hostPowerConfig.sshHost.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false || hostPowerConfig.smartthingsDeviceID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty == false {
            if let saved = try? await service.savePowerConfig(hostPowerConfig) {
                powerConfigResponse = saved
            }
        }
        status = try? await service.status()
        readiness = status?.readiness ?? readiness
        hostConnectionState = status == nil ? hostConnectionState : "online"
        setupProgress = smartThingsDeviceCandidates.count > 1
            ? "PIN 설정 대부분 완료. SmartThings 후보가 여러 개라 wake 대상만 선택 후 저장하세요."
            : "PIN 1회 입력으로 가능한 원격 연결 설정을 자동 완료했습니다."
    }

    func savePowerConfig() async {
        guard let service else { return }
        do {
            let response = try await service.savePowerConfig(powerConfig.hostSafeForRemoteSave())
            powerConfigResponse = response
            status = try await service.status()
            readiness = status?.readiness
            let supportedActions = response.readiness.supportedActions.joined(separator: ", ")
            message = "전원 설정을 저장했습니다. Mac 로컬 SmartThings CLI는 클라이언트에만 보존합니다. 지원 명령: \(supportedActions)"
        } catch {
            message = error.localizedDescription
        }
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
            pairingRecoveryMessage = "페어링 완료: \(response.name)"
            readiness = response.onboarding?.readiness ?? readiness
            powerSetup = response.onboarding?.powerSetup ?? powerSetup
            powerConfigResponse = response.onboarding?.powerConfig ?? powerConfigResponse
            if let config = powerConfigResponse?.config, config.hasAnyPowerSetting { applyHostPowerConfig(config) }
            fillDefaultSSHFields()
            let pairedService = RemoteDashboardService(client: RemoteAPIClient(baseURL: client.baseURL, bearerToken: response.token))
            await completePairingOnboarding(using: pairedService)
            message = "'\(response.name)' 디바이스 페어링 및 자동 설정을 완료했습니다."
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
            pairingRecoveryMessage = "토큰 갱신 완료: \(response.name)"
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
