import Foundation

struct RemoteAPIClient {
    var baseURL: URL
    var bearerToken: String?
    var session: URLSession = RemoteAPIClient.defaultSession()

    static func defaultSession(requestTimeout: TimeInterval = 5, resourceTimeout: TimeInterval = 8) -> URLSession {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = requestTimeout
        configuration.timeoutIntervalForResource = resourceTimeout
        configuration.waitsForConnectivity = false
        return URLSession(configuration: configuration, delegate: nil, delegateQueue: OperationQueue())
    }

    private func endpoint(_ path: String) -> URL {
        baseURL.appendingPathComponent(path)
    }

    private func pathSegment(_ value: String) -> String {
        var allowed = CharacterSet.urlPathAllowed
        allowed.remove(charactersIn: "/?")
        return value.addingPercentEncoding(withAllowedCharacters: allowed) ?? value
    }

    func status() async throws -> RemoteStatus {
        try await get("remote/status")
    }

    func capabilities() async throws -> RemoteCapabilitiesResponse {
        try await get("remote/capabilities")
    }

    func readiness() async throws -> RemoteReadiness {
        try await get("remote/readiness")
    }

    func processes() async throws -> [RemoteProcess] {
        try await get("remote/processes")
    }


    func activeMobileSessions() async throws -> [RemoteMobileSession] {
        let response: RemoteMobileSessionsResponse = try await get("remote/mobile-sessions/active")
        return response.sessions
    }

    func startMobileSession(gameLinkID: String, source: String = "manual") async throws -> RemoteMobileSession {
        let payload = [
            "game_link_id": gameLinkID,
            "source": source,
        ]
        let body = try JSONEncoder().encode(payload)
        return try await post("remote/mobile-sessions/start", body: body)
    }

    func endMobileSession(sessionID: String) async throws -> RemoteMobileSession {
        let payload = ["session_id": sessionID]
        let body = try JSONEncoder().encode(payload)
        return try await post("remote/mobile-sessions/end", body: body)
    }

    func shortcuts() async throws -> [RemoteShortcut] {
        try await get("remote/shortcuts")
    }

    func dashboardSummary() async throws -> RemoteDashboardSummary {
        try await get("remote/dashboard/summary")
    }

    func gameLinks() async throws -> [RemoteGameLink] {
        let response: RemoteGameLinksResponse = try await get("remote/game-links")
        return response.links
    }

    func createGameLink(processID: String, androidPackageName: String, syncStrategy: String = "manual") async throws -> RemoteGameLink {
        let payload = [
            "pc_process_id": processID,
            "android_package_name": androidPackageName,
            "sync_strategy": syncStrategy,
        ]
        let body = try JSONEncoder().encode(payload)
        return try await post("remote/game-links", body: body)
    }

    func beholderIncidents() async throws -> [RemoteBeholderIncident] {
        let response: RemoteBeholderIncidentsResponse = try await get("remote/beholder/incidents")
        return response.incidents
    }

    func launchProcess(id: String, mode: String? = nil) async throws -> RemoteCommandResult {
        var body = Data("{}".utf8)
        if let mode {
            body = try JSONEncoder().encode(["mode": mode])
        }
        return try await post("remote/processes/\(pathSegment(id))/launch", body: body)
    }

    func stopProcess(id: String) async throws -> RemoteCommandResult {
        try await post("remote/processes/\(pathSegment(id))/stop", body: Data("{}".utf8))
    }

    func openShortcut(id: String) async throws -> RemoteCommandResult {
        try await post("remote/shortcuts/\(id)/open", body: Data("{}".utf8))
    }

    func powerSetup() async throws -> RemotePowerSetupResponse {
        try await get("remote/power/setup")
    }

    func registerPowerSSHKey(publicKey: String, label: String) async throws -> RemoteSSHKeyRegistrationResponse {
        let payload = [
            "public_key": publicKey,
            "label": label,
        ]
        let body = try JSONEncoder().encode(payload)
        return try await post("remote/power/ssh-key", body: body)
    }

    func confirmPairing(code: String, deviceName: String) async throws -> PairingConfirmResponse {
        let payload = [
            "code": code,
            "device_name": deviceName,
            "platform": "macos",
        ]
        let body = try JSONEncoder().encode(payload)
        return try await post("remote/pair/confirm", body: body)
    }

    func refreshToken() async throws -> PairingConfirmResponse {
        try await post("remote/tokens/refresh", body: Data("{}".utf8))
    }

    func ensureServerTailscale() async throws -> RemoteTailscaleEnsureResponse {
        try await post("remote/tailscale/ensure", body: Data("{}".utf8))
    }

    func remoteLoggingConfig() async throws -> RemoteLoggingConfigResponse {
        try await get("remote/logging/config")
    }

    func saveRemoteLoggingConfig(enabled: Bool) async throws -> RemoteLoggingConfigResponse {
        let body = try JSONEncoder().encode(["enabled": enabled])
        return try await put("remote/logging/config", body: body)
    }

    func devices() async throws -> [RemoteDevice] {
        let response: RemoteDevicesResponse = try await get("remote/devices")
        return response.devices
    }

    func revokeDevice(id: String) async throws -> RevokeDeviceResponse {
        try await delete("remote/devices/\(id)")
    }

    func purgeRevokedDevices() async throws -> PurgeDevicesResponse {
        try await delete("remote/devices/revoked")
    }

    private func get<T: Decodable>(_ path: String) async throws -> T {
        let (data, response) = try await session.data(for: request(path: path, method: "GET"))
        try validate(response: response, data: data)
        return try JSONDecoder().decode(T.self, from: data)
    }

    private func post<T: Decodable>(_ path: String, body: Data) async throws -> T {
        var request = request(path: path, method: "POST")
        request.httpBody = body
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let (data, response) = try await session.data(for: request)
        try validate(response: response, data: data)
        return try JSONDecoder().decode(T.self, from: data)
    }

    private func put<T: Decodable>(_ path: String, body: Data) async throws -> T {
        var request = request(path: path, method: "PUT")
        request.httpBody = body
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let (data, response) = try await session.data(for: request)
        try validate(response: response, data: data)
        return try JSONDecoder().decode(T.self, from: data)
    }

    private func delete<T: Decodable>(_ path: String) async throws -> T {
        let (data, response) = try await session.data(for: request(path: path, method: "DELETE"))
        try validate(response: response, data: data)
        return try JSONDecoder().decode(T.self, from: data)
    }

    private func request(path: String, method: String) -> URLRequest {
        var request = URLRequest(url: endpoint(path))
        request.httpMethod = method
        if let bearerToken, !bearerToken.isEmpty {
            request.setValue("Bearer \(bearerToken)", forHTTPHeaderField: "Authorization")
        }
        return request
    }

    private func validate(response: URLResponse, data: Data) throws {
        guard let http = response as? HTTPURLResponse else { return }
        guard (200..<300).contains(http.statusCode) else {
            let message = String(data: data, encoding: .utf8) ?? "HTTP \(http.statusCode)"
            let path = http.url?.path ?? "unknown endpoint"
            throw RemoteAPIError.http(status: http.statusCode, message: "\(path): \(message)")
        }
    }
}

enum RemoteAPIError: LocalizedError {
    case invalidURL
    case http(status: Int, message: String)

    var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "Remote Agent URL이 올바르지 않습니다."
        case let .http(status, message):
            return "HTTP \(status): \(message)"
        }
    }
}
