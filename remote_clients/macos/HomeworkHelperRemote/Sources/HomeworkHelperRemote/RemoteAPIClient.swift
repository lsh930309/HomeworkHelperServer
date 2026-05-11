import Foundation

struct RemoteAPIClient {
    var baseURL: URL
    var bearerToken: String?
    var session: URLSession = .shared

    private func endpoint(_ path: String) -> URL {
        baseURL.appendingPathComponent(path)
    }

    func status() async throws -> RemoteStatus {
        try await get("remote/status")
    }

    func capabilities() async throws -> RemoteCapabilitiesResponse {
        try await get("remote/capabilities")
    }

    func processes() async throws -> [RemoteProcess] {
        try await get("remote/processes")
    }

    func shortcuts() async throws -> [RemoteShortcut] {
        try await get("remote/shortcuts")
    }

    func dashboardSummary() async throws -> RemoteDashboardSummary {
        try await get("remote/dashboard/summary")
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
        return try await post("remote/processes/\(id)/launch", body: body)
    }

    func openShortcut(id: String) async throws -> RemoteCommandResult {
        try await post("remote/shortcuts/\(id)/open", body: Data("{}".utf8))
    }

    func power(action: String) async throws -> RemoteCommandResult {
        try await post("remote/power/\(action)", body: Data("{}".utf8))
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

    func devices() async throws -> [RemoteDevice] {
        let response: RemoteDevicesResponse = try await get("remote/devices")
        return response.devices
    }

    func revokeDevice(id: String) async throws -> RevokeDeviceResponse {
        try await delete("remote/devices/\(id)")
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
            throw RemoteAPIError.http(status: http.statusCode, message: message)
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
