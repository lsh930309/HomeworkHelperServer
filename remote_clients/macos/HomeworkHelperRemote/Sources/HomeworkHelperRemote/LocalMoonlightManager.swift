import Foundation
import AppKit
import ApplicationServices

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

struct LocalMoonlightPublicIPCache: Codable, Equatable {
    let ip: String
    let source: String
    let collectedAt: TimeInterval
    let matchedPeerHostName: String

    var collectedDate: Date {
        Date(timeIntervalSince1970: collectedAt)
    }
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

    var publicStreamAddresses: [String] {
        [manualAddress, remoteAddress]
            .compactMap(Self.normalizedHost)
            .filter(Self.isLikelyPublicIPv4)
    }

    func matchesHostNameHint(_ hint: String) -> Bool {
        guard let normalized = Self.normalizedHost(hint) else { return false }
        let canonical = Self.canonicalHostToken(normalized)
        let hostnameMatch = Self.normalizedHost(hostname).map(Self.canonicalHostToken) == canonical
        let stemMatch = Self.normalizedDNSStem(hostname).map(Self.canonicalHostToken) == canonical
        return hostnameMatch || stemMatch
    }

    func matchesAnyAddress(_ values: [String]) -> Bool {
        let normalizedValues = Set(values.compactMap(Self.normalizedHost))
        let candidates = [hostname, localAddress, manualAddress, remoteAddress, ipv6Address].compactMap(Self.normalizedHost)
        return candidates.contains { normalizedValues.contains($0) }
    }

    func matchesPublicIP(_ values: [String]) -> Bool {
        let normalizedValues = Set(values.compactMap(Self.normalizedHost).filter(Self.isLikelyPublicIPv4))
        guard !normalizedValues.isEmpty else { return false }
        return publicStreamAddresses.contains { normalizedValues.contains($0) }
    }

    private func labeledAddress(_ label: String, _ address: String, _ port: Int) -> String? {
        let trimmed = address.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return nil }
        return "\(label): \(trimmed)\(port > 0 ? ":\(port)" : "")"
    }

    private static func normalizedHost(_ value: String?) -> String? {
        let trimmed = (value ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .trimmingCharacters(in: CharacterSet(charactersIn: "[]"))
            .lowercased()
        return trimmed.isEmpty ? nil : trimmed
    }

    private static func normalizedDNSStem(_ value: String?) -> String? {
        normalizedHost(value)?.split(separator: ".").first.map(String.init)
    }

    private static func canonicalHostToken(_ value: String) -> String {
        value.replacingOccurrences(of: "_", with: "-")
    }

    private static func isLikelyPublicIPv4(_ value: String) -> Bool {
        let parts = value.split(separator: ".").compactMap { Int($0) }
        guard parts.count == 4, parts.allSatisfy({ (0...255).contains($0) }) else { return false }
        if parts[0] == 10 || parts[0] == 127 || parts[0] == 0 { return false }
        if parts[0] == 172 && (16...31).contains(parts[1]) { return false }
        if parts[0] == 192 && parts[1] == 168 { return false }
        if parts[0] == 169 && parts[1] == 254 { return false }
        if parts[0] == 100 && (64...127).contains(parts[1]) { return false }
        if parts[0] >= 224 { return false }
        return true
    }

}

enum LocalMoonlightReadiness: String, Equatable {
    case missingApp
    case missingConfig
    case noHosts
    case needsTailscaleRegistration
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
        case .needsTailscaleRegistration:
            return "Tailscale 등록 필요"
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
    let publicIPCache: LocalMoonlightPublicIPCache?
    let stalePublicIPWarning: String

    init(
        installation: LocalMoonlightAppInstallation?,
        preferencesPath: String,
        preferencesReadable: Bool,
        hosts: [LocalMoonlightHostCandidate],
        selectedHostUUID: String,
        targetHost: LocalMoonlightHostCandidate?,
        readiness: LocalMoonlightReadiness,
        message: String,
        publicIPCache: LocalMoonlightPublicIPCache? = nil,
        stalePublicIPWarning: String = ""
    ) {
        self.installation = installation
        self.preferencesPath = preferencesPath
        self.preferencesReadable = preferencesReadable
        self.hosts = hosts
        self.selectedHostUUID = selectedHostUUID
        self.targetHost = targetHost
        self.readiness = readiness
        self.message = message
        self.publicIPCache = publicIPCache
        self.stalePublicIPWarning = stalePublicIPWarning
    }

    var installed: Bool { installation != nil }
    var usableHosts: [LocalMoonlightHostCandidate] {
        hosts.filter { !$0.targetHostArgument.isEmpty && $0.hasDesktopApp }
    }
}

struct LocalMoonlightCommandResult: Equatable {
    let action: String
    let executablePath: String
    let arguments: [String]
    let exitStatus: Int32?
    let stdout: String
    let stderr: String
    let timedOut: Bool

    var succeeded: Bool {
        exitStatus == 0 && !timedOut
    }

    var outputSummary: String {
        let combined = [stdout, stderr]
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .joined(separator: "\n")
        if !combined.isEmpty { return combined }
        if timedOut { return "\(action) 시간 초과" }
        if let exitStatus { return "\(action) 종료 코드 \(exitStatus)" }
        return "\(action) 실행 결과 없음"
    }
}

struct LocalMoonlightSessionSnapshot: Equatable {
    let runningApplicationCount: Int
    let hasVisibleWindow: Bool
    let accessibilityTrusted: Bool
    let desktopStreamProcessCount: Int

    var isRunning: Bool { runningApplicationCount > 0 }
    var isVisible: Bool { isRunning && hasVisibleWindow }
    var hasDesktopStreamSession: Bool { desktopStreamProcessCount > 0 }
    var isDesktopStreamVisible: Bool { hasDesktopStreamSession && hasVisibleWindow }
    var hasDesktopSession: Bool { hasDesktopStreamSession || isVisible }
}

enum LocalMoonlightManager {
    private static let bundleIdentifier = "com.moonlight-stream.Moonlight"
    private static let appPathOverrideKey = "HH_REMOTE_MOONLIGHT_APP_PATHS"
    private static let preferencesPathOverrideKey = "HH_REMOTE_MOONLIGHT_PREFS_PATH"
    private static let ignoreRunningAppsKey = "HH_REMOTE_MOONLIGHT_IGNORE_RUNNING_APPS"

    static func snapshot(
        selectedHostUUID: String,
        baseURLHost: String?,
        hostNameHints: [String] = [],
        publicIPHints: [String] = [],
        publicIPCache: LocalMoonlightPublicIPCache? = nil
    ) -> LocalMoonlightSnapshot {
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
                reason: "저장된 Moonlight host 선택값을 사용합니다.",
                publicIPCache: publicIPCache,
                publicIPHints: publicIPHints
            )
        }

        let normalizedBaseHost = normalizedHost(baseURLHost)
        let usableBaseURLHost = normalizedBaseHost.flatMap { Self.isLoopbackHost($0) ? nil : $0 }
        let usableHostNameHints = hostNameHints.compactMap(normalizedHost)
        let usablePublicIPHints = publicIPHints.compactMap(normalizedHost).filter(isLikelyPublicIPv4)
        let hasHomeworkHelperIdentityHints = usableBaseURLHost != nil || !usableHostNameHints.isEmpty || !usablePublicIPHints.isEmpty

        if let match = uniqueMatch(usableHosts.filter { $0.matchesAnyAddress([usableBaseURLHost ?? ""]) }) {
            return readySnapshot(
                installation: installation,
                preferencesPath: preferencesPath,
                hosts: hosts,
                selectedHostUUID: selected,
                targetHost: match,
                reason: "Remote Agent Base URL host와 일치하는 Moonlight host를 찾았습니다.",
                publicIPCache: publicIPCache,
                publicIPHints: publicIPHints
            )
        }

        if let match = uniqueMatch(usableHosts.filter { host in hostNameHints.contains { host.matchesHostNameHint($0) } }) {
            return readySnapshot(
                installation: installation,
                preferencesPath: preferencesPath,
                hosts: hosts,
                selectedHostUUID: selected,
                targetHost: match,
                reason: "Tailscale/Remote device hostname과 일치하는 Moonlight host를 찾았습니다.",
                publicIPCache: publicIPCache,
                publicIPHints: publicIPHints
            )
        }

        if let match = uniqueMatch(usableHosts.filter { $0.matchesPublicIP(publicIPHints) }) {
            return readySnapshot(
                installation: installation,
                preferencesPath: preferencesPath,
                hosts: hosts,
                selectedHostUUID: selected,
                targetHost: match,
                reason: "호스트 공인 IP와 일치하는 Moonlight host를 찾았습니다.",
                publicIPCache: publicIPCache,
                publicIPHints: publicIPHints
            )
        }

        if hasHomeworkHelperIdentityHints {
            return LocalMoonlightSnapshot(
                installation: installation,
                preferencesPath: preferencesPath,
                preferencesReadable: true,
                hosts: hosts,
                selectedHostUUID: selected,
                targetHost: nil,
                readiness: .needsTailscaleRegistration,
                message: "HomeworkHelper host와 일치하는 Moonlight Desktop host를 찾지 못했습니다. 기존 설정은 수정하지 않고, Tailscale direct 경로로 새 host 등록을 준비하세요.",
                publicIPCache: publicIPCache
            )
        }

        if usableHosts.count == 1, let host = usableHosts.first {
            return readySnapshot(
                installation: installation,
                preferencesPath: preferencesPath,
                hosts: hosts,
                selectedHostUUID: selected,
                targetHost: host,
                reason: "Desktop 앱이 있는 Moonlight host 후보가 1개입니다.",
                publicIPCache: publicIPCache,
                publicIPHints: publicIPHints
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
            message: "Desktop 앱이 있는 Moonlight host 후보가 \(usableHosts.count)개입니다. 사용할 host를 선택하세요.",
            publicIPCache: publicIPCache
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

    static func resolveHomebrewExecutablePath() -> String? {
        firstExecutable(["/opt/homebrew/bin/brew", "/usr/local/bin/brew"])
    }

    static func installViaHomebrew(timeoutSeconds: Int = 240) async -> LocalMoonlightCommandResult {
        guard let brew = resolveHomebrewExecutablePath() else {
            return LocalMoonlightCommandResult(
                action: "brew install --cask moonlight",
                executablePath: "brew",
                arguments: ["install", "--cask", "moonlight"],
                exitStatus: nil,
                stdout: "",
                stderr: "Homebrew를 찾지 못했습니다. https://brew.sh/ 설치 후 다시 시도하세요.",
                timedOut: false
            )
        }
        return await runCommand(
            action: "brew install --cask moonlight",
            executablePath: brew,
            arguments: ["install", "--cask", "moonlight"],
            timeoutSeconds: timeoutSeconds
        )
    }

    static func pair(host: String, pin: String, installation: LocalMoonlightAppInstallation? = nil, timeoutSeconds: Int = 120) async -> LocalMoonlightCommandResult {
        let trimmedHost = host.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedPin = pin.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedHost.isEmpty else {
            return LocalMoonlightCommandResult(action: "moonlight pair", executablePath: "", arguments: [], exitStatus: nil, stdout: "", stderr: "Moonlight에 등록할 host가 비어 있습니다.", timedOut: false)
        }
        guard trimmedPin.count == 4, trimmedPin.allSatisfy(\.isNumber) else {
            return LocalMoonlightCommandResult(action: "moonlight pair", executablePath: "", arguments: [], exitStatus: nil, stdout: "", stderr: "Moonlight pairing PIN은 4자리 숫자여야 합니다.", timedOut: false)
        }
        guard let executable = (installation ?? resolveInstallation())?.executablePath else {
            return LocalMoonlightCommandResult(action: "moonlight pair", executablePath: "", arguments: [], exitStatus: nil, stdout: "", stderr: "Moonlight 실행 파일을 찾지 못했습니다.", timedOut: false)
        }
        return await runCommand(
            action: "moonlight pair",
            executablePath: executable,
            arguments: ["pair", trimmedHost, "--pin", trimmedPin],
            timeoutSeconds: timeoutSeconds
        )
    }

    static func listApps(host: String, installation: LocalMoonlightAppInstallation? = nil, timeoutSeconds: Int = 45) async -> LocalMoonlightCommandResult {
        let trimmedHost = host.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedHost.isEmpty else {
            return LocalMoonlightCommandResult(action: "moonlight list", executablePath: "", arguments: [], exitStatus: nil, stdout: "", stderr: "Moonlight 앱 목록을 확인할 host가 비어 있습니다.", timedOut: false)
        }
        guard let executable = (installation ?? resolveInstallation())?.executablePath else {
            return LocalMoonlightCommandResult(action: "moonlight list", executablePath: "", arguments: [], exitStatus: nil, stdout: "", stderr: "Moonlight 실행 파일을 찾지 못했습니다.", timedOut: false)
        }
        return await runCommand(
            action: "moonlight list",
            executablePath: executable,
            arguments: ["list", trimmedHost],
            timeoutSeconds: timeoutSeconds
        )
    }

    @MainActor
    static func sessionSnapshot(targetHostArgument: String? = nil) -> LocalMoonlightSessionSnapshot {
        let runningApps = runningApplications()
        return LocalMoonlightSessionSnapshot(
            runningApplicationCount: runningApps.count,
            hasVisibleWindow: hasVisibleWindow(for: runningApps),
            accessibilityTrusted: accessibilityTrusted(prompt: false),
            desktopStreamProcessCount: desktopStreamProcessCount(
                for: runningApps,
                targetHostArgument: targetHostArgument
            )
        )
    }

    static func accessibilityPermissionReady(prompt: Bool) -> Bool {
        accessibilityTrusted(prompt: prompt)
    }

    @MainActor
    static func startDesktopStream(host: String, installation: LocalMoonlightAppInstallation? = nil, appName: String = "Desktop") -> LocalMoonlightCommandResult {
        let trimmedHost = host.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedHost.isEmpty else {
            return LocalMoonlightCommandResult(action: "moonlight stream", executablePath: "", arguments: [], exitStatus: nil, stdout: "", stderr: "Moonlight Desktop stream 대상 host가 비어 있습니다.", timedOut: false)
        }
        guard let executable = (installation ?? resolveInstallation())?.executablePath else {
            return LocalMoonlightCommandResult(action: "moonlight stream", executablePath: "", arguments: [], exitStatus: nil, stdout: "", stderr: "Moonlight 실행 파일을 찾지 못했습니다.", timedOut: false)
        }
        let arguments = ["stream", trimmedHost, appName]
        let process = Process()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        process.standardOutput = FileHandle.nullDevice
        process.standardError = FileHandle.nullDevice
        do {
            try process.run()
            return LocalMoonlightCommandResult(
                action: "moonlight stream",
                executablePath: executable,
                arguments: arguments,
                exitStatus: 0,
                stdout: "Moonlight Desktop stream 시작 요청을 보냈습니다. pid=\(process.processIdentifier)",
                stderr: "",
                timedOut: false
            )
        } catch {
            return LocalMoonlightCommandResult(
                action: "moonlight stream",
                executablePath: executable,
                arguments: arguments,
                exitStatus: nil,
                stdout: "",
                stderr: error.localizedDescription,
                timedOut: false
            )
        }
    }

    static func quit(host: String, installation: LocalMoonlightAppInstallation? = nil, timeoutSeconds: Int = 12) async -> LocalMoonlightCommandResult {
        let trimmedHost = host.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedHost.isEmpty else {
            return LocalMoonlightCommandResult(action: "moonlight quit", executablePath: "", arguments: [], exitStatus: nil, stdout: "", stderr: "Moonlight quit 대상 host가 비어 있습니다.", timedOut: false)
        }
        guard let executable = (installation ?? resolveInstallation())?.executablePath else {
            return LocalMoonlightCommandResult(action: "moonlight quit", executablePath: "", arguments: [], exitStatus: nil, stdout: "", stderr: "Moonlight 실행 파일을 찾지 못했습니다.", timedOut: false)
        }
        return await runCommand(
            action: "moonlight quit",
            executablePath: executable,
            arguments: ["quit", trimmedHost],
            timeoutSeconds: timeoutSeconds
        )
    }

    @MainActor
    static func focusAndMoveToScreen(visibleFrame: CGRect?, requireAccessibility: Bool, promptForAccessibility: Bool) -> LocalMoonlightCommandResult {
        let runningApps = runningApplications()
        guard !runningApps.isEmpty else {
            return LocalMoonlightCommandResult(action: "moonlight focus", executablePath: bundleIdentifier, arguments: [], exitStatus: nil, stdout: "", stderr: "실행 중인 Moonlight 앱을 찾지 못했습니다.", timedOut: false)
        }

        if requireAccessibility && !accessibilityTrusted(prompt: promptForAccessibility) {
            return LocalMoonlightCommandResult(action: "moonlight focus", executablePath: bundleIdentifier, arguments: [], exitStatus: nil, stdout: "", stderr: "다중 디스플레이에서 Moonlight 창을 이동하려면 macOS Accessibility 권한이 필요합니다.", timedOut: false)
        }

        var moved = false
        if let visibleFrame {
            moved = runningApps.contains { moveWindows(of: $0, to: visibleFrame) }
        }
        runningApps.forEach { app in
            app.activate(options: [.activateAllWindows])
        }
        let hasWindow = hasVisibleWindow(for: runningApps)
        let moveSuffix = visibleFrame == nil ? "" : (moved ? " · 대상 디스플레이로 이동" : " · 창 이동 미확인")
        return LocalMoonlightCommandResult(
            action: "moonlight focus",
            executablePath: bundleIdentifier,
            arguments: [],
            exitStatus: hasWindow || moved ? 0 : nil,
            stdout: "Moonlight 앱을 전면화했습니다\(moveSuffix).",
            stderr: hasWindow || moved ? "" : "Moonlight 창을 아직 확인하지 못했습니다.",
            timedOut: false
        )
    }

    @MainActor
    static func terminateRunningApplications(forceAfterSeconds: Double = 1.5) async -> LocalMoonlightCommandResult {
        let apps = runningApplications()
        guard !apps.isEmpty else {
            return LocalMoonlightCommandResult(action: "moonlight terminate", executablePath: bundleIdentifier, arguments: [], exitStatus: 0, stdout: "종료할 Moonlight 앱이 없습니다.", stderr: "", timedOut: false)
        }
        apps.forEach { _ = $0.terminate() }
        let nanoseconds = UInt64(max(0.1, forceAfterSeconds) * 1_000_000_000)
        try? await Task.sleep(nanoseconds: nanoseconds)
        let survivors = runningApplications()
        survivors.forEach { _ = $0.forceTerminate() }
        let remaining = runningApplications().count
        return LocalMoonlightCommandResult(
            action: "moonlight terminate",
            executablePath: bundleIdentifier,
            arguments: [],
            exitStatus: remaining == 0 ? 0 : nil,
            stdout: remaining == 0 ? "Moonlight 앱을 종료했습니다." : "Moonlight 종료를 요청했지만 일부 프로세스가 남아 있습니다.",
            stderr: remaining == 0 ? "" : "remaining=\(remaining)",
            timedOut: false
        )
    }

    private static func uniqueMatch(_ matches: [LocalMoonlightHostCandidate]) -> LocalMoonlightHostCandidate? {
        var seen = Set<String>()
        let unique = matches.filter { host in
            guard !seen.contains(host.id) else { return false }
            seen.insert(host.id)
            return true
        }
        return unique.count == 1 ? unique[0] : nil
    }

    private static func stalePublicIPWarning(for targetHost: LocalMoonlightHostCandidate, publicIPHints: [String]) -> String {
        let publicHints = Set(publicIPHints.compactMap(normalizedHost).filter(isLikelyPublicIPv4))
        guard !publicHints.isEmpty else { return "" }
        let savedPublicAddresses = Set(targetHost.publicStreamAddresses)
        guard !savedPublicAddresses.isEmpty else { return "" }
        guard savedPublicAddresses.isDisjoint(with: publicHints) else { return "" }
        return "현재 수집한 호스트 공인 IP와 Moonlight remote/manual 주소가 다릅니다. Moonlight host 주소가 오래되었을 수 있습니다."
    }

    private static func readySnapshot(
        installation: LocalMoonlightAppInstallation?,
        preferencesPath: String,
        hosts: [LocalMoonlightHostCandidate],
        selectedHostUUID: String,
        targetHost: LocalMoonlightHostCandidate,
        reason: String,
        publicIPCache: LocalMoonlightPublicIPCache?,
        publicIPHints: [String]
    ) -> LocalMoonlightSnapshot {
        LocalMoonlightSnapshot(
            installation: installation,
            preferencesPath: preferencesPath,
            preferencesReadable: true,
            hosts: hosts,
            selectedHostUUID: selectedHostUUID,
            targetHost: targetHost,
            readiness: .ready,
            message: "\(reason) \(targetHost.displayTitle)의 Desktop 스트림 후보를 확인했습니다.",
            publicIPCache: publicIPCache,
            stalePublicIPWarning: stalePublicIPWarning(for: targetHost, publicIPHints: publicIPHints)
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

    private static func normalizedHost(_ value: String?) -> String? {
        let trimmed = (value ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .trimmingCharacters(in: CharacterSet(charactersIn: "[]"))
            .lowercased()
        return trimmed.isEmpty ? nil : trimmed
    }

    private static func isLikelyPublicIPv4(_ value: String) -> Bool {
        let parts = value.split(separator: ".").compactMap { Int($0) }
        guard parts.count == 4, parts.allSatisfy({ (0...255).contains($0) }) else { return false }
        if parts[0] == 10 || parts[0] == 127 || parts[0] == 0 { return false }
        if parts[0] == 172 && (16...31).contains(parts[1]) { return false }
        if parts[0] == 192 && parts[1] == 168 { return false }
        if parts[0] == 169 && parts[1] == 254 { return false }
        if parts[0] == 100 && (64...127).contains(parts[1]) { return false }
        if parts[0] >= 224 { return false }
        return true
    }

    private static func isLoopbackHost(_ value: String) -> Bool {
        let normalized = value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return normalized == "localhost" || normalized == "::1" || normalized.hasPrefix("127.")
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

    private static func firstExecutable(_ paths: [String]) -> String? {
        paths.first { FileManager.default.isExecutableFile(atPath: $0) }
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

    @MainActor
    private static func runningApplications() -> [NSRunningApplication] {
        if ProcessInfo.processInfo.environment[ignoreRunningAppsKey] == "1" {
            return []
        }
        return NSRunningApplication.runningApplications(withBundleIdentifier: bundleIdentifier)
            .filter { !$0.isTerminated }
    }

    @MainActor
    private static func hasVisibleWindow(for apps: [NSRunningApplication]) -> Bool {
        let pids = Set(apps.map(\.processIdentifier))
        guard !pids.isEmpty,
              let windowInfo = CGWindowListCopyWindowInfo([.optionOnScreenOnly, .excludeDesktopElements], CGWindowID(0)) as? [[String: Any]] else {
            return false
        }
        return windowInfo.contains { info in
            guard let ownerPID = info[kCGWindowOwnerPID as String] as? pid_t,
                  pids.contains(ownerPID) else {
                return false
            }
            let layer = info[kCGWindowLayer as String] as? Int ?? 0
            let alpha = info[kCGWindowAlpha as String] as? Double ?? 1.0
            return layer == 0 && alpha > 0
        }
    }

    @MainActor
    private static func desktopStreamProcessCount(for apps: [NSRunningApplication], targetHostArgument: String?) -> Int {
        apps.filter { app in
            commandLineIndicatesDesktopStream(
                processCommandLine(pid: app.processIdentifier),
                targetHostArgument: targetHostArgument
            )
        }.count
    }

    private static func commandLineIndicatesDesktopStream(_ commandLine: String, targetHostArgument: String?) -> Bool {
        let normalized = commandLine.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !normalized.isEmpty else { return false }
        guard normalized.contains("moonlight"), normalized.contains("stream"), normalized.contains("desktop") else {
            return false
        }
        let target = targetHostArgument?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased()
        guard let target, !target.isEmpty else { return true }
        return normalized.contains(target)
    }

    private static func processCommandLine(pid: pid_t) -> String {
        let process = Process()
        let output = Pipe()
        process.executableURL = URL(fileURLWithPath: "/bin/ps")
        process.arguments = ["-p", "\(pid)", "-o", "command="]
        process.standardOutput = output
        process.standardError = FileHandle.nullDevice
        do {
            try process.run()
            process.waitUntilExit()
        } catch {
            return ""
        }
        return String(data: output.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
    }

    private static func accessibilityTrusted(prompt: Bool) -> Bool {
        if prompt {
            let key = kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String
            return AXIsProcessTrustedWithOptions([key: true] as CFDictionary)
        }
        return AXIsProcessTrusted()
    }

    @MainActor
    private static func moveWindows(of app: NSRunningApplication, to visibleFrame: CGRect) -> Bool {
        let axApp = AXUIElementCreateApplication(app.processIdentifier)
        var windowsValue: CFTypeRef?
        guard AXUIElementCopyAttributeValue(axApp, kAXWindowsAttribute as CFString, &windowsValue) == .success,
              let windows = windowsValue as? [AXUIElement],
              !windows.isEmpty else {
            return false
        }

        var didMove = false
        for window in windows {
            var size = CGSize(width: min(1280, visibleFrame.width * 0.9), height: min(720, visibleFrame.height * 0.9))
            var sizeValue: CFTypeRef?
            if AXUIElementCopyAttributeValue(window, kAXSizeAttribute as CFString, &sizeValue) == .success,
               let sizeValue,
               CFGetTypeID(sizeValue) == AXValueGetTypeID() {
                let axSize = sizeValue as! AXValue
                var currentSize = CGSize.zero
                if AXValueGetValue(axSize, .cgSize, &currentSize), currentSize.width > 100, currentSize.height > 100 {
                    size = currentSize
                }
            }

            let clampedSize = CGSize(width: min(size.width, visibleFrame.width * 0.94), height: min(size.height, visibleFrame.height * 0.94))
            if clampedSize != size {
                var newSize = clampedSize
                if let axNewSize = AXValueCreate(.cgSize, &newSize) {
                    AXUIElementSetAttributeValue(window, kAXSizeAttribute as CFString, axNewSize)
                }
            }

            var target = CGPoint(
                x: visibleFrame.midX - clampedSize.width / 2,
                y: visibleFrame.midY - clampedSize.height / 2
            )
            if let axPosition = AXValueCreate(.cgPoint, &target),
               AXUIElementSetAttributeValue(window, kAXPositionAttribute as CFString, axPosition) == .success {
                didMove = true
            }
            AXUIElementPerformAction(window, kAXRaiseAction as CFString)
        }
        return didMove
    }

    private static func runCommand(action: String, executablePath: String, arguments: [String], timeoutSeconds: Int) async -> LocalMoonlightCommandResult {
        await withCheckedContinuation { continuation in
            DispatchQueue.global(qos: .utility).async {
                let process = Process()
                let output = Pipe()
                let error = Pipe()
                process.executableURL = URL(fileURLWithPath: executablePath)
                process.arguments = arguments
                process.standardOutput = output
                process.standardError = error
                do {
                    try process.run()
                    let timeoutLock = NSLock()
                    var didTimeOut = false
                    DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + .seconds(max(1, timeoutSeconds))) {
                        guard process.isRunning else { return }
                        timeoutLock.lock()
                        didTimeOut = true
                        timeoutLock.unlock()
                        process.terminate()
                    }
                    process.waitUntilExit()
                    let stdout = String(data: output.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
                    let stderr = String(data: error.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
                    timeoutLock.lock()
                    let timedOut = didTimeOut
                    timeoutLock.unlock()
                    continuation.resume(returning: LocalMoonlightCommandResult(
                        action: action,
                        executablePath: executablePath,
                        arguments: arguments,
                        exitStatus: process.terminationStatus,
                        stdout: stdout.trimmingCharacters(in: .whitespacesAndNewlines),
                        stderr: stderr.trimmingCharacters(in: .whitespacesAndNewlines),
                        timedOut: timedOut
                    ))
                } catch {
                    continuation.resume(returning: LocalMoonlightCommandResult(
                        action: action,
                        executablePath: executablePath,
                        arguments: arguments,
                        exitStatus: nil,
                        stdout: "",
                        stderr: error.localizedDescription,
                        timedOut: false
                    ))
                }
            }
        }
    }
}
