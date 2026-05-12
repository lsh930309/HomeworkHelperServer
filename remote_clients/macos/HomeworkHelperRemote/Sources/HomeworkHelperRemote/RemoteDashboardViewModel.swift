import Foundation
import SwiftUI

private actor RemoteDashboardService {
    let client: RemoteAPIClient

    init(client: RemoteAPIClient) {
        self.client = client
    }

    func status() async throws -> RemoteStatus { try await client.status() }
    func dashboardSummary() async throws -> RemoteDashboardSummary { try await client.dashboardSummary() }
    func beholderIncidents() async throws -> [RemoteBeholderIncident] { try await client.beholderIncidents() }
    func gameLinks() async throws -> [RemoteGameLink] { try await client.gameLinks() }
    func activeMobileSessions() async throws -> [RemoteMobileSession] { try await client.activeMobileSessions() }
    func powerConfig() async throws -> RemotePowerConfigResponse { try await client.powerConfig() }
    func processes() async throws -> [RemoteProcess] { try await client.processes() }
    func shortcuts() async throws -> [RemoteShortcut] { try await client.shortcuts() }
    func devices() async throws -> [RemoteDevice] { try await client.devices() }
    func startMobileSession(gameLinkID: String) async throws -> RemoteMobileSession { try await client.startMobileSession(gameLinkID: gameLinkID) }
    func endMobileSession(sessionID: String) async throws -> RemoteMobileSession { try await client.endMobileSession(sessionID: sessionID) }
    func createGameLink(processID: String, androidPackageName: String) async throws -> RemoteGameLink {
        try await client.createGameLink(processID: processID, androidPackageName: androidPackageName)
    }
    func launchProcess(id: String) async throws -> RemoteCommandResult { try await client.launchProcess(id: id) }
    func openShortcut(id: String) async throws -> RemoteCommandResult { try await client.openShortcut(id: id) }
    func power(action: String) async throws -> RemoteCommandResult { try await client.power(action: action) }
    func savePowerConfig(_ config: RemotePowerConfigPayload) async throws -> RemotePowerConfigResponse { try await client.savePowerConfig(config) }
    func confirmPairing(code: String, deviceName: String) async throws -> PairingConfirmResponse {
        try await client.confirmPairing(code: code, deviceName: deviceName)
    }
    func refreshToken() async throws -> PairingConfirmResponse { try await client.refreshToken() }
    func revokeDevice(id: String) async throws -> RevokeDeviceResponse { try await client.revokeDevice(id: id) }
}

@MainActor
final class RemoteDashboardViewModel: ObservableObject {
    @Published var baseURLText = "http://127.0.0.1:8000"
    @Published var tokenText = "" {
        didSet { tokenStore.save(tokenText) }
    }
    @Published var pairingCode = ""
    @Published var deviceName = Host.current().localizedName ?? "Mac"
    @Published var gameLinkProcessID = ""
    @Published var gameLinkAndroidPackage = ""
    @Published var powerConfig = RemotePowerConfigPayload()
    @Published var powerConfigResponse: RemotePowerConfigResponse?
    @Published var status: RemoteStatus?
    @Published var dashboardSummary: RemoteDashboardSummary?
    @Published var beholderIncidents: [RemoteBeholderIncident] = []
    @Published var gameLinks: [RemoteGameLink] = []
    @Published var mobileSessions: [RemoteMobileSession] = []
    @Published var processes: [RemoteProcess] = []
    @Published var shortcuts: [RemoteShortcut] = []
    @Published var devices: [RemoteDevice] = []
    @Published var isLoading = false
    @Published var message = "Remote Agent에 연결하세요."

    private let tokenStore: any RemoteTokenStore

    init(tokenStore: any RemoteTokenStore = KeychainTokenStore()) {
        self.tokenStore = tokenStore
        tokenText = tokenStore.load()
    }

    private var client: RemoteAPIClient? {
        guard let url = URL(string: baseURLText), url.scheme != nil else { return nil }
        return RemoteAPIClient(baseURL: url, bearerToken: tokenText.isEmpty ? nil : tokenText)
    }

    private var service: RemoteDashboardService? {
        guard let client else { return nil }
        return RemoteDashboardService(client: client)
    }

    func refresh() async {
        guard let client else {
            message = "Remote Agent URL이 올바르지 않습니다."
            return
        }
        await refresh(using: RemoteDashboardService(client: client), includeDevices: !tokenText.isEmpty)
    }

    private func refresh(using service: RemoteDashboardService, includeDevices: Bool) async {
        isLoading = true
        defer { isLoading = false }
        do {
            // Keep refreshes sequential. The Remote Agent's file-backed device
            // registry updates token last-seen metadata during auth checks, so
            // parallel authenticated requests can race on that registry file.
            status = try await service.status()
            dashboardSummary = try await service.dashboardSummary()
            beholderIncidents = try await service.beholderIncidents()
            gameLinks = try await service.gameLinks()
            mobileSessions = try await service.activeMobileSessions()
            powerConfigResponse = try await service.powerConfig()
            powerConfig = powerConfigResponse?.config ?? RemotePowerConfigPayload()
            processes = try await service.processes()
            shortcuts = try await service.shortcuts()
            if includeDevices {
                devices = try await service.devices()
            }
            message = "동기화 완료: 게임 \(processes.count)개, 연결 \(gameLinks.count)개, 모바일 세션 \(mobileSessions.count)개, 숏컷 \(shortcuts.count)개"
        } catch {
            message = error.localizedDescription
        }
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
        } catch {
            message = error.localizedDescription
        }
    }

    func open(_ shortcut: RemoteShortcut) async {
        guard let service else { return }
        do {
            let result = try await service.openShortcut(id: shortcut.id)
            message = result.message
        } catch {
            message = error.localizedDescription
        }
    }

    func isPowerActionEnabled(_ action: String) -> Bool {
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
        guard let client else { return }
        do {
            let service = RemoteDashboardService(client: client)
            let result = try await service.power(action: action)
            message = result.message
            await refresh()
        } catch {
            message = error.localizedDescription
        }
    }

    func savePowerConfig() async {
        guard let service else { return }
        do {
            let response = try await service.savePowerConfig(powerConfig)
            powerConfigResponse = response
            powerConfig = response.config
            status = try await service.status()
            let supportedActions = response.readiness.supportedActions.joined(separator: ", ")
            message = "전원 설정을 저장했습니다. 지원 명령: \(supportedActions)"
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
            message = "'\(response.name)' 디바이스 페어링 완료. 토큰을 Keychain에 저장했습니다."
            await refresh(using: RemoteDashboardService(client: RemoteAPIClient(baseURL: client.baseURL, bearerToken: response.token)), includeDevices: true)
        } catch {
            message = error.localizedDescription
        }
    }

    func refreshToken() async {
        guard let service else { return }
        do {
            let response = try await service.refreshToken()
            tokenText = response.token
            message = "'\(response.name)' 디바이스 토큰을 갱신하고 Keychain에 저장했습니다."
            await refreshDevices()
        } catch {
            message = error.localizedDescription
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
