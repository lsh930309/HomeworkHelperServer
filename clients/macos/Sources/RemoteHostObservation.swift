import Foundation

// Live evidence is owned here. API authentication and app readiness never determine
// whether the PC or its independently running Apollo service is reachable.
struct RemoteHostIdentity: Equatable {
    let baseURL: String
    let moonlightHostUUID: String
    let token: String
    let sshHost: String
    let sshUser: String
    let sshKeyPath: String
    let sshPort: Int
}

enum RemotePCObservation: Equatable { case unknown, reachable, unreachable, unavailable }
enum RemoteApolloObservation: Equatable { case unknown, ready, unavailable, identityMismatch, notConfigured }
enum RemoteAppObservation: Equatable { case unknown, ready, waiting, authRejected, notPaired }

struct RemoteHostObservationSnapshot: Equatable {
    var pc: RemotePCObservation = .unknown
    var apollo: RemoteApolloObservation = .unknown
    var app: RemoteAppObservation = .unknown
    var sshPowerReady = false
    var observedAt: Date?

    var canStream: Bool { apollo == .ready }
    var shouldWake: Bool { pc == .unreachable && apollo != .ready && app != .ready }
    var appReady: Bool { app == .ready }

    func label(availability: RemoteHostAvailabilityState = .unknown, isPaired: Bool = true, isSyncing: Bool = false) -> String {
        if !isPaired { return "페어링 해제됨" }
        if isSyncing && app == .ready { return "동기화 중" }
        switch availability {
        case .goingOffline, .waking, .restarting, .reconnecting, .authRejected:
            return availability.label
        default:
            break
        }
        if pc == .unreachable && apollo != .ready && app != .ready {
            return "호스트 응답 없음"
        }
        if pc == .reachable || apollo == .ready || app == .ready {
            if app == .ready { return "페어링됨" }
            if app == .authRejected { return "인증 확인 필요" }
            if apollo != .ready { return "스트리밍 대기" }
            return "호스트 대기"
        }
        if pc == .unavailable { return "Tailscale 오류" }
        return availability == .agentUnavailable ? availability.label : "상태 확인 중"
    }
}

struct RemoteHostObservationRequest: Equatable {
    let identity: RemoteHostIdentity
    let sequence: UInt64
}

struct RemoteHostObservationStore {
    private(set) var identity: RemoteHostIdentity?
    private(set) var snapshot = RemoteHostObservationSnapshot()
    private var sequence: UInt64 = 0

    mutating func reset(to identity: RemoteHostIdentity) {
        guard self.identity != identity else { return }
        self.identity = identity
        sequence &+= 1
        snapshot = RemoteHostObservationSnapshot()
    }

    mutating func begin(for identity: RemoteHostIdentity) -> RemoteHostObservationRequest {
        reset(to: identity)
        sequence &+= 1
        return RemoteHostObservationRequest(identity: identity, sequence: sequence)
    }

    mutating func accept(_ snapshot: RemoteHostObservationSnapshot, for request: RemoteHostObservationRequest) -> Bool {
        guard request.identity == identity, request.sequence == sequence else { return false }
        self.snapshot = snapshot
        return true
    }

    static func pollDelaySeconds(screenVisible: Bool, userBaseIntervalSeconds: Int = 5) -> UInt64 {
        screenVisible ? UInt64(min(60, max(1, userBaseIntervalSeconds))) : 15
    }
}

enum RemoteApolloProbe {
    static func endpoint(host: String, target: LocalMoonlightHostCandidate) -> URL? {
        let configuredPort: Int
        if target.manualAddress.caseInsensitiveCompare(host) == .orderedSame { configuredPort = target.manualPort }
        else if target.localAddress.caseInsensitiveCompare(host) == .orderedSame { configuredPort = target.localPort }
        else if target.remoteAddress.caseInsensitiveCompare(host) == .orderedSame { configuredPort = target.remotePort }
        else if target.ipv6Address.caseInsensitiveCompare(host) == .orderedSame { configuredPort = target.ipv6Port }
        else { configuredPort = 0 }
        var components = URLComponents()
        components.scheme = "http"
        components.host = host
        components.port = configuredPort > 0 ? configuredPort : 47989
        components.path = "/serverinfo"
        return components.url
    }

    static func observe(host: String, target: LocalMoonlightHostCandidate?) async -> RemoteApolloObservation {
        guard let target, !target.uuid.isEmpty, let url = endpoint(host: host, target: target) else { return .notConfigured }
        var request = URLRequest(url: url)
        request.timeoutInterval = 3
        request.cachePolicy = .reloadIgnoringLocalAndRemoteCacheData
        do {
            let (data, response) = try await URLSession.shared.data(for: request)
            guard let response = response as? HTTPURLResponse, response.statusCode == 200 else { return .unavailable }
            return decodeServerInfo(data, expectedUUID: target.uuid)
        } catch { return .unavailable }
    }

    static func decodeServerInfo(_ data: Data, expectedUUID: String) -> RemoteApolloObservation {
        let reader = ServerInfoReader()
        let parser = XMLParser(data: data)
        parser.delegate = reader
        guard parser.parse(), reader.statusCode == "200", !reader.uniqueID.isEmpty else { return .unavailable }
        return reader.uniqueID.caseInsensitiveCompare(expectedUUID) == .orderedSame ? .ready : .identityMismatch
    }

    private final class ServerInfoReader: NSObject, XMLParserDelegate {
        var statusCode = ""
        var uniqueID = ""
        private var element = ""
        func parser(_ parser: XMLParser, didStartElement elementName: String, namespaceURI: String?, qualifiedName: String?, attributes attributeDict: [String: String] = [:]) {
            element = elementName.lowercased()
            if element == "root" { statusCode = attributeDict["status_code"] ?? "" }
        }
        func parser(_ parser: XMLParser, foundCharacters string: String) {
            if element == "uniqueid" { uniqueID += string }
        }
        func parser(_ parser: XMLParser, didEndElement elementName: String, namespaceURI: String?, qualifiedName: String?) {
            if elementName.lowercased() == "uniqueid" { uniqueID = uniqueID.trimmingCharacters(in: .whitespacesAndNewlines) }
            element = ""
        }
    }
}
