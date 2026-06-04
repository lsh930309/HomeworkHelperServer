import Foundation

struct LocalTailscalePeer: Identifiable, Equatable {
    let hostname: String
    let dnsName: String
    let ips: [String]
    let online: Bool
    let os: String
    let currentEndpointHost: String?
    let directEndpointHosts: [String]
    let relay: String?
    let peerRelay: String?

    var id: String {
        let dns = dnsName.trimmingCharacters(in: CharacterSet(charactersIn: ".")).lowercased()
        if !dns.isEmpty { return dns }
        let host = hostname.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if !host.isEmpty { return host }
        if let ip = primaryIPv4 { return ip }
        return ips.joined(separator: ",")
    }
    var primaryIPv4: String? { ips.first { $0.contains(".") } }
    var dnsStem: String {
        dnsName.trimmingCharacters(in: CharacterSet(charactersIn: "."))
            .split(separator: ".")
            .first
            .map(String.init) ?? ""
    }
    var publicEndpointHosts: [String] {
        directEndpointHosts.filter(Self.isLikelyPublicIPv4)
    }
    var suggestedBaseURL: String? {
        guard let ip = primaryIPv4 else { return nil }
        return "http://\(ip):8000"
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

struct LocalTailscaleSnapshot: Equatable {
    let installed: Bool
    let running: Bool
    let backendState: String
    let selfIPs: [String]
    let selfHostname: String
    let peers: [LocalTailscalePeer]
    let message: String

    var foundationState: String {
        if !installed { return "missing" }
        if running && !selfIPs.isEmpty { return "ready" }
        let normalized = backendState.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let lowered = message.lowercased()
        if lowered.contains("system extension") || lowered.contains("network extension") || lowered.contains("vpn") || lowered.contains("approval") || lowered.contains("승인") {
            return "needs_system_approval"
        }
        if ["needslogin", "needs_login", "nostate"].contains(normalized) || lowered.contains("not logged") || lowered.contains("login") || lowered.contains("로그인") {
            return "needs_login"
        }
        if ["stopped", "down"].contains(normalized) || lowered.contains("tailscale down") || lowered.contains("stopped") {
            return "stopped_or_down"
        }
        if normalized == "running" && selfIPs.isEmpty { return "running_without_ip" }
        if lowered.contains("not running") || lowered.contains("failed to start") || lowered.contains("gui failed to start") || lowered.contains("tailscaled") || lowered.contains("daemon") || lowered.contains("backend") {
            return "app_launch_needed"
        }
        return "installed"
    }

    var suggestedBaseURLs: [String] {
        peers.compactMap { peer in
            let name = "\(peer.hostname) \(peer.dnsName)".lowercased()
            guard name.contains("windows") || name.contains("desktop") || peer.os.lowercased().contains("windows") else { return nil }
            return peer.suggestedBaseURL
        }
    }
}

struct LocalTailscalePingResult: Equatable {
    enum Outcome: Equatable {
        case reachable
        case unreachable
        case unavailable
    }

    let host: String
    let outcome: Outcome
    let message: String
    let executablePath: String?
    let exitStatus: Int32?
    let stdout: String
    let stderr: String
    let timedOut: Bool

    var attempted: Bool { outcome != .unavailable }
    var reachable: Bool { outcome == .reachable }
    var directForStreaming: Bool {
        guard reachable, !timedOut else { return false }
        let lines = [stdout, stderr, message]
            .joined(separator: "\n")
            .split(whereSeparator: \.isNewline)
            .map { String($0).trimmingCharacters(in: .whitespacesAndNewlines).lowercased() }
            .filter { !$0.isEmpty }
        guard let lastPathLine = lines.last(where: { $0.contains("pong") && $0.contains(" via ") }) else {
            return false
        }
        if lastPathLine.contains("derp(") || lastPathLine.contains("peer-relay(") || lastPathLine.contains("relay ") {
            return false
        }
        return !lines.contains { $0.contains("direct connection not established") }
    }
    var streamingRouteSummary: String {
        let combined = [stdout, stderr, message]
            .joined(separator: "\n")
            .split(whereSeparator: \.isNewline)
            .map { String($0).trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
        return combined.last(where: { $0.localizedCaseInsensitiveContains(" via ") }) ?? message
    }

    init(
        host: String,
        outcome: Outcome,
        message: String,
        executablePath: String? = nil,
        exitStatus: Int32? = nil,
        stdout: String = "",
        stderr: String = "",
        timedOut: Bool = false
    ) {
        self.host = host
        self.outcome = outcome
        self.message = message
        self.executablePath = executablePath
        self.exitStatus = exitStatus
        self.stdout = stdout
        self.stderr = stderr
        self.timedOut = timedOut
    }
}

enum TailscaleDiscovery {
    private enum TailscaleCommand: Equatable {
        case direct(path: String)
        case zshLoginShell

        var displayPath: String {
            switch self {
            case .direct(let path):
                return path
            case .zshLoginShell:
                return "/bin/zsh -lic tailscale"
            }
        }

        var isShellBridge: Bool {
            switch self {
            case .direct:
                return false
            case .zshLoginShell:
                return true
            }
        }

        func invocation(arguments: [String]) -> (executable: String, arguments: [String]) {
            switch self {
            case .direct(let path):
                return (path, arguments)
            case .zshLoginShell:
                let command = (["tailscale"] + arguments).enumerated().map { index, value in
                    index == 0 ? value : Self.shellQuote(value)
                }.joined(separator: " ")
                return ("/bin/zsh", ["-lic", command])
            }
        }

        func environment(base: [String: String]) -> [String: String]? {
            var environment = base
            environment["TAILSCALE_BE_CLI"] = "1"
            guard isShellBridge else { return environment }
            environment["TERM"] = environment["TERM"] ?? "dumb"
            environment["POWERLEVEL9K_DISABLE_GITSTATUS"] = "true"
            environment["ZSH_DISABLE_COMPFIX"] = "true"
            environment["DISABLE_AUTO_UPDATE"] = "true"
            return environment
        }

        private static func shellQuote(_ value: String) -> String {
            "'\(value.replacingOccurrences(of: "'", with: "'\\''"))'"
        }
    }

    private struct ProcessResult {
        let status: Int32
        let stdout: String
        let stderr: String
        let timedOut: Bool
    }

    static func status() async -> LocalTailscaleSnapshot {
        let commands = tailscaleCommands()
        guard !commands.isEmpty else {
            return LocalTailscaleSnapshot(installed: false, running: false, backendState: "missing", selfIPs: [], selfHostname: "", peers: [], message: "tailscale CLI를 찾지 못했습니다. Base URL을 수동 입력하세요.")
        }

        var lastError = ""
        for command in commands {
            do {
                let data = try await run(command: command, arguments: ["status", "--json"])
                let payload = try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]
                let selfNode = payload["Self"] as? [String: Any] ?? [:]
                let backendState = payload["BackendState"] as? String ?? "unknown"
                let peersDict = payload["Peer"] as? [String: Any] ?? [:]
                let peers = peersDict.values.compactMap { value -> LocalTailscalePeer? in
                    guard let item = value as? [String: Any] else { return nil }
                    let ips = item["TailscaleIPs"] as? [String] ?? []
                    let currentEndpointHost = endpointHost(from: item["CurAddr"] as? String)
                    let directEndpointHosts = uniqueEndpointHosts(
                        ([currentEndpointHost].compactMap { $0 }) +
                            ((item["Addrs"] as? [String] ?? []).compactMap(endpointHost(from:)))
                    )
                    return LocalTailscalePeer(
                        hostname: item["HostName"] as? String ?? "",
                        dnsName: item["DNSName"] as? String ?? "",
                        ips: ips,
                        online: item["Online"] as? Bool ?? false,
                        os: item["OS"] as? String ?? "",
                        currentEndpointHost: currentEndpointHost,
                        directEndpointHosts: directEndpointHosts,
                        relay: item["Relay"] as? String,
                        peerRelay: item["PeerRelay"] as? String
                    )
                }
                let selfIPs = selfNode["TailscaleIPs"] as? [String] ?? []
                let running = backendState.lowercased() == "running" && !selfIPs.isEmpty
                let message = messageForFoundationState(
                    installed: true,
                    running: running,
                    backendState: backendState,
                    selfIPs: selfIPs,
                    fallback: running ? "tailscale 네트워크 사용 가능" : "tailscale 상태: \(backendState)"
                )
                return LocalTailscaleSnapshot(installed: true, running: running, backendState: backendState, selfIPs: selfIPs, selfHostname: selfNode["HostName"] as? String ?? "", peers: peers, message: message)
            } catch {
                lastError = "\(command.displayPath): \(error.localizedDescription)"
            }
        }
        return LocalTailscaleSnapshot(installed: hasKnownTailscaleInstall(), running: false, backendState: "error", selfIPs: [], selfHostname: "", peers: [], message: lastError.isEmpty ? "tailscale status 실패" : lastError)
    }

    static func ping(host: String, timeoutSeconds: Int = 2) async -> LocalTailscalePingResult {
        let trimmedHost = host.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedHost.isEmpty else {
            return LocalTailscalePingResult(host: host, outcome: .unavailable, message: "ping할 호스트가 비어 있습니다.")
        }
        let commands = tailscaleCommands()
        guard !commands.isEmpty else {
            return LocalTailscalePingResult(host: trimmedHost, outcome: .unavailable, message: "tailscale CLI를 찾지 못해 HTTP 상태 확인으로 fallback합니다.")
        }
        var lastUnavailable: LocalTailscalePingResult?
        for command in commands {
            let result = await ping(host: trimmedHost, timeoutSeconds: timeoutSeconds, command: command)
            switch result.outcome {
            case .reachable, .unreachable:
                return result
            case .unavailable:
                lastUnavailable = result
            }
        }
        return lastUnavailable ?? LocalTailscalePingResult(host: trimmedHost, outcome: .unavailable, message: "tailscale CLI를 실행할 수 없습니다.")
    }

    private static func ping(host trimmedHost: String, timeoutSeconds: Int, command: TailscaleCommand) async -> LocalTailscalePingResult {
        do {
            let result = try await runForResult(
                command: command,
                arguments: ["ping", "--timeout=\(max(1, timeoutSeconds))s", trimmedHost],
                hardTimeoutSeconds: max(4, min(8, timeoutSeconds * 3))
            )
            let combined = [result.stdout, result.stderr].joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
            if result.timedOut {
                return LocalTailscalePingResult(
                    host: trimmedHost,
                    outcome: .unreachable,
                    message: combined.isEmpty ? "tailscale ping hard deadline 초과" : combined,
                    executablePath: command.displayPath,
                    exitStatus: result.status,
                    stdout: result.stdout,
                    stderr: result.stderr,
                    timedOut: true
                )
            }
            let lowered = combined.lowercased()
            let noReplySignals = noReplySignalCount(in: lowered)
            if (combined.isEmpty && result.status != 0)
                || isRuntimeUnavailableMessage(lowered)
                || (command.isShellBridge && result.status != 0 && noReplySignals == 0) {
                return LocalTailscalePingResult(
                    host: trimmedHost,
                    outcome: .unavailable,
                    message: combined.isEmpty ? "tailscale ping을 실행할 수 없습니다." : combined,
                    executablePath: command.displayPath,
                    exitStatus: result.status,
                    stdout: result.stdout,
                    stderr: result.stderr
                )
            }
            if result.status == 0 {
                return LocalTailscalePingResult(
                    host: trimmedHost,
                    outcome: .reachable,
                    message: combined.isEmpty ? "tailscale ping 성공" : combined,
                    executablePath: command.displayPath,
                    exitStatus: result.status,
                    stdout: result.stdout,
                    stderr: result.stderr
                )
            }
            if noReplySignals >= 2 {
                return LocalTailscalePingResult(
                    host: trimmedHost,
                    outcome: .unreachable,
                    message: combined.isEmpty ? "tailscale ping no-reply signal limit 도달" : combined,
                    executablePath: command.displayPath,
                    exitStatus: result.status,
                    stdout: result.stdout,
                    stderr: result.stderr
                )
            }
            return LocalTailscalePingResult(
                host: trimmedHost,
                outcome: .unreachable,
                message: combined.isEmpty ? "tailscale ping 응답이 없습니다." : combined,
                executablePath: command.displayPath,
                exitStatus: result.status,
                stdout: result.stdout,
                stderr: result.stderr
            )
        } catch {
            return LocalTailscalePingResult(host: trimmedHost, outcome: .unavailable, message: error.localizedDescription, executablePath: command.displayPath)
        }
    }


    static func ensureReady() async -> LocalTailscaleSnapshot {
        await activateNetwork()
    }

    static func activateNetwork() async -> LocalTailscaleSnapshot {
        let before = await status()
        if before.running && !before.selfIPs.isEmpty { return before }

        if !before.installed {
            let installed = await installTailscale()
            if !installed {
                return LocalTailscaleSnapshot(installed: false, running: false, backendState: "install_failed", selfIPs: [], selfHostname: "", peers: [], message: "tailscale 자동 설치에 실패했습니다. 공식 다운로드 페이지에서 수동 설치가 필요합니다.")
            }
        }

        _ = await launchTailscale()
        let up = await runTailscaleControl(arguments: ["up", "--accept-routes"], hardTimeoutSeconds: 90)
        try? await Task.sleep(for: .seconds(2))
        let after = await status()
        if after.running && !after.selfIPs.isEmpty { return after }
        let detail = up.message.trimmingCharacters(in: .whitespacesAndNewlines)
        let fallback = detail.isEmpty
            ? messageForFoundationState(installed: after.installed, running: after.running, backendState: after.backendState, selfIPs: after.selfIPs, fallback: "tailscale 설치/실행 후에도 로그인 또는 System Extension 승인이 필요합니다. Tailscale 앱에서 승인을 완료한 뒤 다시 시도하세요.")
            : detail
        return LocalTailscaleSnapshot(installed: after.installed, running: after.running, backendState: after.backendState, selfIPs: after.selfIPs, selfHostname: after.selfHostname, peers: after.peers, message: fallback)
    }

    static func deactivateNetwork() async -> LocalTailscaleSnapshot {
        let before = await status()
        guard before.installed else {
            return LocalTailscaleSnapshot(installed: false, running: false, backendState: "missing", selfIPs: [], selfHostname: "", peers: [], message: "Tailscale이 설치되어 있지 않아 비활성화할 네트워크가 없습니다.")
        }
        let down = await runTailscaleControl(arguments: ["down"], hardTimeoutSeconds: 45)
        try? await Task.sleep(for: .seconds(1))
        let after = await status()
        if down.ok {
            return LocalTailscaleSnapshot(installed: after.installed, running: after.running, backendState: after.backendState, selfIPs: after.selfIPs, selfHostname: after.selfHostname, peers: after.peers, message: "Tailscale 네트워크를 비활성화했습니다. 다시 연결하려면 Tailscale 활성화를 실행하세요.")
        }
        let detail = down.message.trimmingCharacters(in: .whitespacesAndNewlines)
        return LocalTailscaleSnapshot(installed: after.installed, running: after.running, backendState: after.backendState, selfIPs: after.selfIPs, selfHostname: after.selfHostname, peers: after.peers, message: detail.isEmpty ? after.message : detail)
    }

    private static func installTailscale() async -> Bool {
        if let brew = firstExecutable(["/opt/homebrew/bin/brew", "/usr/local/bin/brew"]) {
            if (try? await run(executable: brew, arguments: ["install", "--cask", "tailscale"])) != nil {
                return true
            }
        }
        guard let pkg = await downloadLatestStablePackage() else { return false }
        let command = "/usr/sbin/installer -pkg \"\(pkg.path)\" -target /"
        let script = "do shell script \"\(escapeAppleScript(command))\" with administrator privileges"
        return (try? await run(executable: "/usr/bin/osascript", arguments: ["-e", script])) != nil
    }

    private static func launchTailscale() async -> Bool {
        if (try? await run(executable: "/usr/bin/open", arguments: ["-a", "Tailscale"])) != nil {
            return true
        }
        return false
    }

    private static func runTailscaleControl(arguments: [String], hardTimeoutSeconds: Int) async -> (ok: Bool, message: String) {
        var lastMessage = ""
        for command in tailscaleCommands() {
            do {
                let result = try await runForResult(command: command, arguments: arguments, hardTimeoutSeconds: hardTimeoutSeconds)
                let combined = [result.stdout, result.stderr].joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
                if result.status == 0 {
                    return (true, combined)
                }
                if !combined.isEmpty {
                    lastMessage = "\(command.displayPath): \(combined)"
                }
            } catch {
                lastMessage = "\(command.displayPath): \(error.localizedDescription)"
            }
        }
        return (false, lastMessage)
    }

    private static func messageForFoundationState(installed: Bool, running: Bool, backendState: String, selfIPs: [String], fallback: String) -> String {
        if !installed { return "Tailscale이 설치되어 있지 않습니다. 자동 설치를 실행하세요." }
        if running && !selfIPs.isEmpty { return "tailscale 네트워크 사용 가능" }
        let normalized = backendState.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        if ["needslogin", "needs_login", "nostate"].contains(normalized) {
            return "Tailscale 실행은 확인됐지만 tailnet 로그인/계정 생성이 필요합니다. Tailscale 앱에서 로그인 후 다시 시도하세요."
        }
        if ["stopped", "down"].contains(normalized) {
            return "Tailscale이 설치되어 있지만 네트워크가 down 상태입니다. Tailscale 활성화를 실행하세요."
        }
        if normalized == "running" && selfIPs.isEmpty {
            return "Tailscale 상태는 Running이지만 self IP가 없습니다. 로그인/네트워크 상태를 확인하세요."
        }
        return fallback
    }

    private static func downloadLatestStablePackage() async -> URL? {
        do {
            let listingURL = URL(string: "https://pkgs.tailscale.com/stable/?v=latest")!
            let (data, _) = try await URLSession.shared.data(from: listingURL)
            let listing = String(data: data, encoding: .utf8) ?? ""
            guard let match = listing.range(of: #"Tailscale-[0-9.]+-macos\.pkg"#, options: .regularExpression) else { return nil }
            let filename = String(listing[match])
            let packageURL = URL(string: "https://pkgs.tailscale.com/stable/\(filename)")!
            let (packageData, _) = try await URLSession.shared.data(from: packageURL)
            let target = FileManager.default.temporaryDirectory.appendingPathComponent(filename)
            try packageData.write(to: target, options: .atomic)
            return target
        } catch {
            return nil
        }
    }

    private static func firstExecutable(_ paths: [String]) -> String? {
        paths.first { FileManager.default.isExecutableFile(atPath: $0) }
    }

    private static func endpointHost(from value: String?) -> String? {
        let trimmed = value?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        guard !trimmed.isEmpty else { return nil }
        if trimmed.hasPrefix("[") {
            guard let end = trimmed.firstIndex(of: "]") else { return nil }
            return String(trimmed[trimmed.index(after: trimmed.startIndex)..<end])
        }
        let parts = trimmed.split(separator: ":", omittingEmptySubsequences: false)
        if parts.count == 2 { return String(parts[0]) }
        return trimmed
    }

    private static func uniqueEndpointHosts(_ values: [String]) -> [String] {
        var seen = Set<String>()
        return values.compactMap { value in
            let normalized = value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
            guard !normalized.isEmpty, !seen.contains(normalized) else { return nil }
            seen.insert(normalized)
            return normalized
        }
    }

    private static func escapeAppleScript(_ value: String) -> String {
        value.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"")
    }

    private static func tailscaleCommands() -> [TailscaleCommand] {
        var commands: [TailscaleCommand] = []
        var seen = Set<String>()

        func appendDirect(_ path: String) {
            guard !seen.contains(path), FileManager.default.isExecutableFile(atPath: path) else { return }
            seen.insert(path)
            commands.append(.direct(path: path))
        }

        // Packaged apps do not inherit the user's interactive zsh aliases. Prefer
        // real executable paths, including the Tailscale.app bundled CLI entry,
        // before the login-shell bridge so connectivity logs stay shell-noise-free.
        for path in [
            "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
            "/usr/local/bin/tailscale",
            "/opt/homebrew/bin/tailscale"
        ] {
            appendDirect(path)
        }
        if FileManager.default.isExecutableFile(atPath: "/bin/zsh") {
            commands.append(.zshLoginShell)
        }
        return commands
    }

    private static func hasKnownTailscaleInstall() -> Bool {
        [
            "/opt/homebrew/bin/tailscale",
            "/usr/local/bin/tailscale",
            "/Applications/Tailscale.app/Contents/MacOS/Tailscale"
        ]
            .contains { FileManager.default.isExecutableFile(atPath: $0) }
    }

    private static func noReplySignalCount(in output: String) -> Int {
        var count = 0
        for marker in ["no reply", "timed out"] {
            var searchStart = output.startIndex
            while let range = output.range(of: marker, range: searchStart..<output.endIndex) {
                count += 1
                searchStart = range.upperBound
            }
        }
        return count
    }

    private static func isRuntimeUnavailableMessage(_ output: String) -> Bool {
        output.contains("gui failed to start")
            || output.contains("failed to start")
            || output.contains("clierror")
            || output.contains("couldn’t be completed")
            || output.contains("couldn't be completed")
            || output.contains("not running")
            || output.contains("not logged")
            || output.contains("tailscaled")
            || output.contains("daemon")
            || output.contains("backend")
    }

    private static func run(command: TailscaleCommand, arguments: [String]) async throws -> Data {
        try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: .utility).async {
                let process = Process()
                let pipe = Pipe()
                let invocation = command.invocation(arguments: arguments)
                process.executableURL = URL(fileURLWithPath: invocation.executable)
                process.arguments = invocation.arguments
                process.environment = command.environment(base: ProcessInfo.processInfo.environment)
                process.standardOutput = pipe
                process.standardError = FileHandle.nullDevice
                var outputData = Data()
                let outputGroup = DispatchGroup()
                outputGroup.enter()
                DispatchQueue.global(qos: .utility).async {
                    outputData = pipe.fileHandleForReading.readDataToEndOfFile()
                    outputGroup.leave()
                }
                do {
                    try process.run()
                    process.waitUntilExit()
                    outputGroup.wait()
                    if process.terminationStatus == 0 {
                        continuation.resume(returning: outputData)
                    } else {
                        continuation.resume(throwing: NSError(domain: "TailscaleDiscovery", code: Int(process.terminationStatus), userInfo: [NSLocalizedDescriptionKey: "tailscale status 실패 (\(command.displayPath))"]))
                    }
                } catch {
                    continuation.resume(throwing: error)
                }
            }
        }
    }

    private static func run(executable: String, arguments: [String]) async throws -> Data {
        try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: .utility).async {
                let process = Process()
                let pipe = Pipe()
                process.executableURL = URL(fileURLWithPath: executable)
                process.arguments = arguments
                process.standardOutput = pipe
                process.standardError = FileHandle.nullDevice
                var outputData = Data()
                let outputGroup = DispatchGroup()
                outputGroup.enter()
                DispatchQueue.global(qos: .utility).async {
                    outputData = pipe.fileHandleForReading.readDataToEndOfFile()
                    outputGroup.leave()
                }
                do {
                    try process.run()
                    process.waitUntilExit()
                    outputGroup.wait()
                    if process.terminationStatus == 0 {
                        continuation.resume(returning: outputData)
                    } else {
                        continuation.resume(throwing: NSError(domain: "TailscaleDiscovery", code: Int(process.terminationStatus), userInfo: [NSLocalizedDescriptionKey: "\(executable) 실행 실패"]))
                    }
                } catch {
                    continuation.resume(throwing: error)
                }
            }
        }
    }

    private static func runForResult(command: TailscaleCommand, arguments: [String], hardTimeoutSeconds: Int? = nil) async throws -> ProcessResult {
        try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: .utility).async {
                let process = Process()
                let output = Pipe()
                let error = Pipe()
                let invocation = command.invocation(arguments: arguments)
                process.executableURL = URL(fileURLWithPath: invocation.executable)
                process.arguments = invocation.arguments
                process.environment = command.environment(base: ProcessInfo.processInfo.environment)
                process.standardOutput = output
                process.standardError = error
                var stdoutData = Data()
                var stderrData = Data()
                let outputGroup = DispatchGroup()
                outputGroup.enter()
                DispatchQueue.global(qos: .utility).async {
                    stdoutData = output.fileHandleForReading.readDataToEndOfFile()
                    outputGroup.leave()
                }
                outputGroup.enter()
                DispatchQueue.global(qos: .utility).async {
                    stderrData = error.fileHandleForReading.readDataToEndOfFile()
                    outputGroup.leave()
                }
                do {
                    try process.run()
                    let timeoutLock = NSLock()
                    var didTimeOut = false
                    if let hardTimeoutSeconds {
                        DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + .seconds(max(1, hardTimeoutSeconds))) {
                            guard process.isRunning else { return }
                            timeoutLock.lock()
                            didTimeOut = true
                            timeoutLock.unlock()
                            process.terminate()
                        }
                    }
                    process.waitUntilExit()
                    outputGroup.wait()
                    let stdout = String(data: stdoutData, encoding: .utf8) ?? ""
                    let stderr = String(data: stderrData, encoding: .utf8) ?? ""
                    timeoutLock.lock()
                    let timedOut = didTimeOut
                    timeoutLock.unlock()
                    continuation.resume(returning: ProcessResult(status: process.terminationStatus, stdout: stdout, stderr: stderr, timedOut: timedOut))
                } catch {
                    continuation.resume(throwing: error)
                }
            }
        }
    }
}
