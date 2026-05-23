import Foundation
import AppKit

struct LocalMoonlightAppInstallation: Equatable {
    let appPath: String
    let executablePath: String
    let bundleIdentifier: String
    let version: String
}

struct LocalMoonlightAppEntry: Equatable {
    let name: String
    let id: Int
    let hidden: Bool
}

struct LocalMoonlightHostCandidate: Identifiable, Equatable {
    let uuid: String
    let hostname: String
    let localAddress: String
    let localPort: Int
    let manualAddress: String
    let manualPort: Int
    let remoteAddress: String
    let remotePort: Int
    let ipv6Address: String
    let ipv6Port: Int
    let apps: [LocalMoonlightAppEntry]

    var id: String {
        if !uuid.isEmpty { return uuid }
        return [hostname, localAddress, manualAddress, remoteAddress, ipv6Address].joined(separator: "|")
    }

    var hasDesktopApp: Bool {
        apps.contains { $0.name.caseInsensitiveCompare("Desktop") == .orderedSame }
    }

    var desktopAppID: Int? {
        apps.first { $0.name.caseInsensitiveCompare("Desktop") == .orderedSame }?.id
    }

    var displayTitle: String {
        if !hostname.isEmpty { return hostname }
        if !uuid.isEmpty { return uuid }
        if !manualAddress.isEmpty { return manualAddress }
        if !localAddress.isEmpty { return localAddress }
        if !remoteAddress.isEmpty { return remoteAddress }
        if !ipv6Address.isEmpty { return ipv6Address }
        return "Unknown Moonlight Host"
    }

    var addressSummary: String {
        let addresses = [
            labeledAddress("local", localAddress, localPort),
            labeledAddress("manual", manualAddress, manualPort),
            labeledAddress("remote", remoteAddress, remotePort),
            labeledAddress("ipv6", ipv6Address, ipv6Port)
        ]
            .compactMap { $0 }
        return addresses.isEmpty ? "주소 없음" : addresses.joined(separator: " · ")
    }

    var appSummary: String {
        if apps.isEmpty { return "앱 목록 없음" }
        if hasDesktopApp {
            return desktopAppID.map { "Desktop 감지 (#\($0))" } ?? "Desktop 감지"
        }
        return "Desktop 없음 · \(apps.map(\.name).prefix(3).joined(separator: ", "))"
    }

    var targetHostArgument: String {
        if !uuid.isEmpty { return uuid }
        if !hostname.isEmpty { return hostname }
        if !manualAddress.isEmpty { return manualAddress }
        if !localAddress.isEmpty { return localAddress }
        return remoteAddress
    }

    private func labeledAddress(_ label: String, _ address: String, _ port: Int) -> String? {
        let trimmed = address.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        return "\(label): \(trimmed)\(port > 0 ? ":\(port)" : "")"
    }
}

enum LocalMoonlightReadiness: String, Equatable {
    case missingApp
    case missingConfig
    case noHosts
    case ambiguous
    case ready

    var label: String {
        switch self {
        case .missingApp:
            return "Moonlight 없음"
        case .missingConfig:
            return "설정 없음"
        case .noHosts:
            return "Host 없음"
        case .ambiguous:
            return "Host 선택 필요"
        case .ready:
            return "준비됨"
        }
    }
}

struct LocalMoonlightSnapshot: Equatable {
    let installation: LocalMoonlightAppInstallation?
    let preferencesPath: String
    let preferencesReadable: Bool
    let hosts: [LocalMoonlightHostCandidate]
    let selectedHostUUID: String
    let targetHost: LocalMoonlightHostCandidate?
    let readiness: LocalMoonlightReadiness
    let message: String

    var installed: Bool { installation != nil }
    var usableHosts: [LocalMoonlightHostCandidate] {
        hosts.filter { !$0.targetHostArgument.isEmpty && $0.hasDesktopApp }
    }
}

enum LocalMoonlightManager {
    private static let bundleIdentifier = "com.moonlight-stream.Moonlight"
    private static let appPathOverrideKey = "HH_REMOTE_MOONLIGHT_APP_PATHS"
    private static let preferencesPathOverrideKey = "HH_REMOTE_MOONLIGHT_PREFS_PATH"

    static func snapshot(selectedHostUUID: String, baseURLHost: String?) -> LocalMoonlightSnapshot {
        let installation = resolveInstallation()
        let preferencesPath = resolvePreferencesPath()
        let selected = selectedHostUUID.trimmingCharacters(in: .whitespacesAndNewlines)

        guard installation != nil else {
            return LocalMoonlightSnapshot(
                installation: nil,
                preferencesPath: preferencesPath,
                preferencesReadable: false,
                hosts: [],
                selectedHostUUID: selected,
                targetHost: nil,
                readiness: .missingApp,
                message: "Moonlight 앱을 찾지 못했습니다. /Applications 또는 사용자 Applications에 설치되어 있는지 확인하세요."
            )
        }

        let parseResult = readHosts(from: preferencesPath)
        guard parseResult.readable else {
            return LocalMoonlightSnapshot(
                installation: installation,
                preferencesPath: preferencesPath,
                preferencesReadable: false,
                hosts: [],
                selectedHostUUID: selected,
                targetHost: nil,
                readiness: .missingConfig,
                message: parseResult.message.isEmpty ? "Moonlight 설정 파일을 읽지 못했습니다. Moonlight에서 host를 먼저 추가/pair하세요." : parseResult.message
            )
        }

        let hosts = parseResult.hosts
        let usableHosts = hosts.filter { !$0.targetHostArgument.isEmpty && $0.hasDesktopApp }
        guard !usableHosts.isEmpty else {
            return LocalMoonlightSnapshot(
                installation: installation,
                preferencesPath: preferencesPath,
                preferencesReadable: true,
                hosts: hosts,
                selectedHostUUID: selected,
                targetHost: nil,
                readiness: .noHosts,
                message: hosts.isEmpty ? "Moonlight에 저장된 host가 없습니다." : "Moonlight host는 있지만 Desktop 앱이 노출된 후보가 없습니다."
            )
        }

        if !selected.isEmpty, let host = usableHosts.first(where: { $0.uuid == selected }) {
            return readySnapshot(
                installation: installation,
                preferencesPath: preferencesPath,
                hosts: hosts,
                selectedHostUUID: selected,
                targetHost: host,
                reason: "저장된 Moonlight host 선택값을 사용합니다."
            )
        }

        let matchedByRemoteHost = usableHosts.filter { matches(baseURLHost: baseURLHost, candidate: $0) }
        if matchedByRemoteHost.count == 1, let host = matchedByRemoteHost.first {
            return readySnapshot(
                installation: installation,
                preferencesPath: preferencesPath,
                hosts: hosts,
                selectedHostUUID: selected,
                targetHost: host,
                reason: "Remote Agent Base URL host와 일치하는 Moonlight host를 찾았습니다."
            )
        }

        if usableHosts.count == 1, let host = usableHosts.first {
            return readySnapshot(
                installation: installation,
                preferencesPath: preferencesPath,
                hosts: hosts,
                selectedHostUUID: selected,
                targetHost: host,
                reason: "Desktop 앱이 있는 Moonlight host 후보가 1개입니다."
            )
        }

        return LocalMoonlightSnapshot(
            installation: installation,
            preferencesPath: preferencesPath,
            preferencesReadable: true,
            hosts: hosts,
            selectedHostUUID: selected,
            targetHost: nil,
            readiness: .ambiguous,
            message: "Desktop 앱이 있는 Moonlight host 후보가 \(usableHosts.count)개입니다. 사용할 host를 선택하세요."
        )
    }

    static func resolveInstallation() -> LocalMoonlightAppInstallation? {
        for appPath in moonlightAppPathCandidates() {
            if let installation = resolveInstallationCandidate(appPath) {
                return installation
            }
        }
        return nil
    }

    private static func readySnapshot(
        installation: LocalMoonlightAppInstallation?,
        preferencesPath: String,
        hosts: [LocalMoonlightHostCandidate],
        selectedHostUUID: String,
        targetHost: LocalMoonlightHostCandidate,
        reason: String
    ) -> LocalMoonlightSnapshot {
        LocalMoonlightSnapshot(
            installation: installation,
            preferencesPath: preferencesPath,
            preferencesReadable: true,
            hosts: hosts,
            selectedHostUUID: selectedHostUUID,
            targetHost: targetHost,
            readiness: .ready,
            message: "\(reason) \(targetHost.displayTitle)의 Desktop 스트림 후보를 확인했습니다."
        )
    }

    private static func readHosts(from preferencesPath: String) -> (readable: Bool, hosts: [LocalMoonlightHostCandidate], message: String) {
        let expanded = NSString(string: preferencesPath).expandingTildeInPath
        let url = URL(fileURLWithPath: expanded)
        guard FileManager.default.isReadableFile(atPath: expanded) else {
            return (false, [], "Moonlight 설정 파일을 찾지 못했습니다: \(expanded)")
        }
        do {
            let data = try Data(contentsOf: url)
            guard let plist = try PropertyListSerialization.propertyList(from: data, options: [], format: nil) as? [String: Any] else {
                return (false, [], "Moonlight 설정 파일 형식을 해석할 수 없습니다: \(expanded)")
            }
            return (true, parseHosts(from: plist), "")
        } catch {
            return (false, [], "Moonlight 설정 파일 읽기 실패: \(error.localizedDescription)")
        }
    }

    private static func parseHosts(from plist: [String: Any]) -> [LocalMoonlightHostCandidate] {
        let hostCount = intValue(plist["hosts.size"]) ?? 0
        guard hostCount > 0 else { return [] }
        return (1...hostCount).compactMap { index in
            let prefix = "hosts.\(index)"
            let uuid = stringValue(plist["\(prefix).uuid"])
            let hostname = stringValue(plist["\(prefix).hostname"])
            let localAddress = stringValue(plist["\(prefix).localaddress"])
            let manualAddress = stringValue(plist["\(prefix).manualaddress"])
            let remoteAddress = stringValue(plist["\(prefix).remoteaddress"])
            let ipv6Address = stringValue(plist["\(prefix).ipv6address"])
            let apps = parseApps(from: plist, prefix: "\(prefix).apps")
            guard !uuid.isEmpty || !hostname.isEmpty || !localAddress.isEmpty || !manualAddress.isEmpty || !remoteAddress.isEmpty || !ipv6Address.isEmpty else {
                return nil
            }
            return LocalMoonlightHostCandidate(
                uuid: uuid,
                hostname: hostname,
                localAddress: localAddress,
                localPort: intValue(plist["\(prefix).localport"]) ?? 0,
                manualAddress: manualAddress,
                manualPort: intValue(plist["\(prefix).manualport"]) ?? 0,
                remoteAddress: remoteAddress,
                remotePort: intValue(plist["\(prefix).remoteport"]) ?? 0,
                ipv6Address: ipv6Address,
                ipv6Port: intValue(plist["\(prefix).ipv6port"]) ?? 0,
                apps: apps
            )
        }
    }

    private static func parseApps(from plist: [String: Any], prefix: String) -> [LocalMoonlightAppEntry] {
        let appCount = intValue(plist["\(prefix).size"]) ?? 0
        guard appCount > 0 else { return [] }
        return (1...appCount).compactMap { index in
            let appPrefix = "\(prefix).\(index)"
            let name = stringValue(plist["\(appPrefix).name"])
            guard !name.isEmpty else { return nil }
            return LocalMoonlightAppEntry(
                name: name,
                id: intValue(plist["\(appPrefix).id"]) ?? 0,
                hidden: boolValue(plist["\(appPrefix).hidden"]) ?? false
            )
        }
    }

    private static func matches(baseURLHost: String?, candidate: LocalMoonlightHostCandidate) -> Bool {
        guard let normalizedBaseHost = normalizedHost(baseURLHost), !normalizedBaseHost.isEmpty else { return false }
        let values = [
            candidate.hostname,
            candidate.localAddress,
            candidate.manualAddress,
            candidate.remoteAddress,
            candidate.ipv6Address
        ]
            .compactMap(normalizedHost)
        return values.contains(normalizedBaseHost)
    }

    private static func normalizedHost(_ value: String?) -> String? {
        let trimmed = (value ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .trimmingCharacters(in: CharacterSet(charactersIn: "[]"))
            .lowercased()
        return trimmed.isEmpty ? nil : trimmed
    }

    private static func resolvePreferencesPath() -> String {
        let override = ProcessInfo.processInfo.environment[preferencesPathOverrideKey]?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        if !override.isEmpty { return NSString(string: override).expandingTildeInPath }
        return NSString(string: "~/Library/Preferences/com.moonlight-stream.Moonlight.plist").expandingTildeInPath
    }

    private static func moonlightAppPathCandidates() -> [String] {
        if let override = ProcessInfo.processInfo.environment[appPathOverrideKey] {
            return override
                .split(separator: ":", omittingEmptySubsequences: true)
                .map { NSString(string: String($0)).expandingTildeInPath }
        }

        var candidates: [String] = []
        if let workspaceURL = NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundleIdentifier) {
            candidates.append(workspaceURL.path)
        }
        candidates.append("/Applications/Moonlight.app")
        candidates.append(NSString(string: "~/Applications/Moonlight.app").expandingTildeInPath)

        var seen = Set<String>()
        return candidates.filter { path in
            guard !path.isEmpty, !seen.contains(path) else { return false }
            seen.insert(path)
            return true
        }
    }

    private static func resolveInstallationCandidate(_ path: String) -> LocalMoonlightAppInstallation? {
        let expanded = NSString(string: path).expandingTildeInPath
        let url = URL(fileURLWithPath: expanded)
        guard let bundle = Bundle(url: url) else {
            return executableInstallation(path: expanded)
        }
        let executableName = bundle.object(forInfoDictionaryKey: "CFBundleExecutable") as? String ?? "Moonlight"
        let executablePath = url.appendingPathComponent("Contents/MacOS/\(executableName)").path
        guard FileManager.default.isExecutableFile(atPath: executablePath) else { return nil }
        let identifier = bundle.bundleIdentifier ?? bundleIdentifier
        let version = (bundle.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String)
            ?? (bundle.object(forInfoDictionaryKey: "CFBundleVersion") as? String)
            ?? "unknown"
        return LocalMoonlightAppInstallation(appPath: expanded, executablePath: executablePath, bundleIdentifier: identifier, version: version)
    }

    private static func executableInstallation(path: String) -> LocalMoonlightAppInstallation? {
        guard FileManager.default.isExecutableFile(atPath: path) else { return nil }
        return LocalMoonlightAppInstallation(appPath: path, executablePath: path, bundleIdentifier: bundleIdentifier, version: "unknown")
    }

    private static func stringValue(_ value: Any?) -> String {
        switch value {
        case let string as String:
            return string.trimmingCharacters(in: .whitespacesAndNewlines)
        case let number as NSNumber:
            return number.stringValue
        default:
            return ""
        }
    }

    private static func intValue(_ value: Any?) -> Int? {
        switch value {
        case let int as Int:
            return int
        case let number as NSNumber:
            return number.intValue
        case let string as String:
            return Int(string.trimmingCharacters(in: .whitespacesAndNewlines))
        default:
            return nil
        }
    }

    private static func boolValue(_ value: Any?) -> Bool? {
        switch value {
        case let bool as Bool:
            return bool
        case let number as NSNumber:
            return number.boolValue
        case let string as String:
            let lowered = string.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
            if ["true", "yes", "1"].contains(lowered) { return true }
            if ["false", "no", "0"].contains(lowered) { return false }
            return nil
        default:
            return nil
        }
    }
}
