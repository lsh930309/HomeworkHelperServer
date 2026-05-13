import Foundation

struct LocalTailscalePeer: Identifiable, Equatable {
    let id = UUID()
    let hostname: String
    let dnsName: String
    let ips: [String]
    let online: Bool
    let os: String

    var primaryIPv4: String? { ips.first { $0.contains(".") } }
    var suggestedBaseURL: String? {
        guard let ip = primaryIPv4 else { return nil }
        return "http://\(ip):8000"
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

    var suggestedBaseURLs: [String] {
        peers.compactMap { peer in
            let name = "\(peer.hostname) \(peer.dnsName)".lowercased()
            guard name.contains("windows") || name.contains("desktop") || peer.os.lowercased().contains("windows") else { return nil }
            return peer.suggestedBaseURL
        }
    }
}

enum TailscaleDiscovery {
    static func status() async -> LocalTailscaleSnapshot {
        guard let executable = tailscaleExecutable() else {
            return LocalTailscaleSnapshot(installed: false, running: false, backendState: "missing", selfIPs: [], selfHostname: "", peers: [], message: "tailscale CLI를 찾지 못했습니다. Base URL을 수동 입력하세요.")
        }
        do {
            let data = try await run(executable: executable, arguments: ["status", "--json"])
            let payload = try JSONSerialization.jsonObject(with: data) as? [String: Any] ?? [:]
            let selfNode = payload["Self"] as? [String: Any] ?? [:]
            let backendState = payload["BackendState"] as? String ?? "unknown"
            let peersDict = payload["Peer"] as? [String: Any] ?? [:]
            let peers = peersDict.values.compactMap { value -> LocalTailscalePeer? in
                guard let item = value as? [String: Any] else { return nil }
                let ips = item["TailscaleIPs"] as? [String] ?? []
                return LocalTailscalePeer(
                    hostname: item["HostName"] as? String ?? "",
                    dnsName: item["DNSName"] as? String ?? "",
                    ips: ips,
                    online: item["Online"] as? Bool ?? false,
                    os: item["OS"] as? String ?? ""
                )
            }
            let selfIPs = selfNode["TailscaleIPs"] as? [String] ?? []
            let running = backendState.lowercased() == "running" && !selfIPs.isEmpty
            return LocalTailscaleSnapshot(installed: true, running: running, backendState: backendState, selfIPs: selfIPs, selfHostname: selfNode["HostName"] as? String ?? "", peers: peers, message: running ? "tailscale 네트워크 사용 가능" : "tailscale 상태: \(backendState)")
        } catch {
            return LocalTailscaleSnapshot(installed: true, running: false, backendState: "error", selfIPs: [], selfHostname: "", peers: [], message: error.localizedDescription)
        }
    }


    static func ensureReady() async -> LocalTailscaleSnapshot {
        let before = await status()
        if before.running && !before.selfIPs.isEmpty { return before }

        if !before.installed {
            let installed = await installTailscale()
            if !installed {
                return LocalTailscaleSnapshot(installed: false, running: false, backendState: "install_failed", selfIPs: [], selfHostname: "", peers: [], message: "tailscale 자동 설치에 실패했습니다. 공식 다운로드 페이지에서 수동 설치가 필요합니다.")
            }
        }

        _ = await launchTailscale()
        try? await Task.sleep(for: .seconds(2))
        let after = await status()
        if after.running && !after.selfIPs.isEmpty { return after }
        return LocalTailscaleSnapshot(installed: after.installed, running: after.running, backendState: after.backendState, selfIPs: after.selfIPs, selfHostname: after.selfHostname, peers: after.peers, message: "tailscale 설치/실행 후에도 로그인 또는 System Extension 승인이 필요합니다. Tailscale 앱에서 승인을 완료한 뒤 다시 시도하세요.")
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

    private static func escapeAppleScript(_ value: String) -> String {
        value.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"")
    }

    private static func tailscaleExecutable() -> String? {
        for path in ["/opt/homebrew/bin/tailscale", "/usr/local/bin/tailscale", "/Applications/Tailscale.app/Contents/MacOS/Tailscale"] {
            if FileManager.default.isExecutableFile(atPath: path) { return path }
        }
        return nil
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
                do {
                    try process.run()
                    process.waitUntilExit()
                    if process.terminationStatus == 0 {
                        continuation.resume(returning: pipe.fileHandleForReading.readDataToEndOfFile())
                    } else {
                        continuation.resume(throwing: NSError(domain: "TailscaleDiscovery", code: Int(process.terminationStatus), userInfo: [NSLocalizedDescriptionKey: "tailscale status 실패"]))
                    }
                } catch {
                    continuation.resume(throwing: error)
                }
            }
        }
    }
}
