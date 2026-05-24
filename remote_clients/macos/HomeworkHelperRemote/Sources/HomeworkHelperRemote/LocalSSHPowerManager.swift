import Foundation

enum LocalSSHPowerManager {
    static let acceptedMarker = "__HH_REMOTE_POWER_ACCEPTED__"
    static let healthMarker = "__HH_SSH_HEALTH_OK__"
    private static let connectionClosingActions: Set<String> = ["sleep", "restart", "shutdown"]

    private struct ProcessResult {
        let status: Int32
        let stdout: String
        let stderr: String
    }

    struct HealthResult: Equatable {
        enum Outcome: Equatable {
            case reachable
            case unreachable
            case unavailable
        }

        let host: String
        let outcome: Outcome
        let message: String
        let executablePath: String
        let exitStatus: Int32?
        let authenticated: Bool
        let stdout: String
        let stderr: String
    }

    struct PublicIPResult: Equatable {
        let host: String
        let ip: String?
        let message: String
        let executablePath: String
        let exitStatus: Int32?
        let stdout: String
        let stderr: String

        var succeeded: Bool { ip != nil }
    }

    static func command(for action: String) throws -> String {
        switch action {
        case "shutdown":
            return "cmd /C shutdown /s /t 1 && echo \(acceptedMarker)"
        case "restart":
            return "cmd /C shutdown /r /t 1 && echo \(acceptedMarker)"
        case "sleep":
            return "cmd /C echo \(acceptedMarker) && rundll32.exe powrprof.dll,SetSuspendState 0,0,0"
        default:
            throw NSError(domain: "LocalSSHPowerManager", code: 1, userInfo: [NSLocalizedDescriptionKey: "지원하지 않는 SSH 전원 명령입니다: \(action)"])
        }
    }

    static func run(action: String, config: RemotePowerConfigPayload) async throws -> String {
        let command = try command(for: action)
        var extraArgs: [String] = []
        if connectionClosingActions.contains(action) {
            extraArgs = ["-o", "ServerAliveInterval=2", "-o", "ServerAliveCountMax=2"]
        }

        let host = config.sshHost.trimmingCharacters(in: .whitespacesAndNewlines)
        let user = config.sshUser.trimmingCharacters(in: .whitespacesAndNewlines)
        let keyPath = NSString(string: config.normalizedLocalSSHKeyPath()).expandingTildeInPath
        guard !host.isEmpty, !user.isEmpty, !keyPath.isEmpty else {
            throw NSError(domain: "LocalSSHPowerManager", code: 2, userInfo: [NSLocalizedDescriptionKey: "Mac에 저장된 SSH host/user/key path가 없어 SSH 전원 명령을 보낼 수 없습니다."])
        }

        var args = [
            "-i", keyPath,
            "-p", String(config.sshPort),
            "-o", "ConnectTimeout=5",
            "-o", "BatchMode=yes",
            "-o", "IdentitiesOnly=yes",
            "-o", "StrictHostKeyChecking=no",
        ]
        args.append(contentsOf: extraArgs)
        args.append("\(user)@\(host)")
        args.append(command)

        let result = try await runForResult(executable: "/usr/bin/ssh", arguments: args)
        let combined = [result.stdout, result.stderr].joined(separator: "\n")
        guard combined.contains(Self.acceptedMarker) else {
            let detail = result.stderr.isEmpty ? result.stdout : result.stderr
            throw NSError(domain: "LocalSSHPowerManager", code: Int(result.status), userInfo: [NSLocalizedDescriptionKey: detail.isEmpty ? "SSH 전원 명령 수락 신호를 확인하지 못했습니다." : detail])
        }
        return "Mac에서 OpenSSH로 \(action) 명령 수락 신호를 확인했습니다."
    }

    static func health(config: RemotePowerConfigPayload, timeoutSeconds: Int = 3) async -> HealthResult {
        let host = config.sshHost.trimmingCharacters(in: .whitespacesAndNewlines)
        let user = config.sshUser.trimmingCharacters(in: .whitespacesAndNewlines)
        let keyPath = NSString(string: config.normalizedLocalSSHKeyPath()).expandingTildeInPath
        guard !host.isEmpty, !user.isEmpty, !keyPath.isEmpty, config.sshPort > 0 else {
            return HealthResult(host: host, outcome: .unavailable, message: "SSH health를 확인할 host/user/key path가 비어 있습니다.", executablePath: "/usr/bin/ssh", exitStatus: nil, authenticated: false, stdout: "", stderr: "")
        }

        let args = [
            "-i", keyPath,
            "-p", String(config.sshPort),
            "-o", "ConnectTimeout=\(max(1, timeoutSeconds))",
            "-o", "BatchMode=yes",
            "-o", "IdentitiesOnly=yes",
            "-o", "StrictHostKeyChecking=no",
            "\(user)@\(host)",
            "echo \(healthMarker)",
        ]

        do {
            let result = try await runForResult(executable: "/usr/bin/ssh", arguments: args)
            let combined = [result.stdout, result.stderr].joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
            let lowered = combined.lowercased()
            if result.status == 0 && combined.contains(healthMarker) {
                return HealthResult(host: host, outcome: .reachable, message: combined.isEmpty ? "SSH health 성공" : combined, executablePath: "/usr/bin/ssh", exitStatus: result.status, authenticated: true, stdout: result.stdout, stderr: result.stderr)
            }
            if lowered.contains("connection refused") || lowered.contains("permission denied") {
                return HealthResult(host: host, outcome: .reachable, message: combined.isEmpty ? "SSH host는 응답했지만 인증/서비스가 거부되었습니다." : combined, executablePath: "/usr/bin/ssh", exitStatus: result.status, authenticated: false, stdout: result.stdout, stderr: result.stderr)
            }
            if lowered.contains("timed out")
                || lowered.contains("operation timed out")
                || lowered.contains("no route to host")
                || lowered.contains("host is down")
                || lowered.contains("network is unreachable")
                || lowered.contains("could not resolve hostname") {
                return HealthResult(host: host, outcome: .unreachable, message: combined.isEmpty ? "SSH health 응답이 없습니다." : combined, executablePath: "/usr/bin/ssh", exitStatus: result.status, authenticated: false, stdout: result.stdout, stderr: result.stderr)
            }
            return HealthResult(host: host, outcome: .unavailable, message: combined.isEmpty ? "SSH health를 판독할 수 없습니다." : combined, executablePath: "/usr/bin/ssh", exitStatus: result.status, authenticated: false, stdout: result.stdout, stderr: result.stderr)
        } catch {
            return HealthResult(host: host, outcome: .unavailable, message: error.localizedDescription, executablePath: "/usr/bin/ssh", exitStatus: nil, authenticated: false, stdout: "", stderr: "")
        }
    }

    static func publicIP(config: RemotePowerConfigPayload, timeoutSeconds: Int = 8) async -> PublicIPResult {
        let host = config.sshHost.trimmingCharacters(in: .whitespacesAndNewlines)
        let user = config.sshUser.trimmingCharacters(in: .whitespacesAndNewlines)
        let keyPath = NSString(string: config.normalizedLocalSSHKeyPath()).expandingTildeInPath
        guard !host.isEmpty, !user.isEmpty, !keyPath.isEmpty, config.sshPort > 0 else {
            return PublicIPResult(host: host, ip: nil, message: "SSH 공인 IP를 확인할 host/user/key path가 비어 있습니다.", executablePath: "/usr/bin/ssh", exitStatus: nil, stdout: "", stderr: "")
        }

        let remoteCommand = """
        powershell -NoProfile -NonInteractive -Command "& { try { (Invoke-RestMethod -UseBasicParsing -Uri 'https://api.ipify.org?format=text' -TimeoutSec \(max(1, timeoutSeconds))).Trim() } catch { 'PUBLIC_IP_ERROR:' + $_.Exception.Message } }"
        """
        let args = [
            "-i", keyPath,
            "-p", String(config.sshPort),
            "-o", "ConnectTimeout=\(max(1, timeoutSeconds))",
            "-o", "BatchMode=yes",
            "-o", "IdentitiesOnly=yes",
            "-o", "StrictHostKeyChecking=no",
            "\(user)@\(host)",
            remoteCommand
        ]

        do {
            let result = try await runForResult(executable: "/usr/bin/ssh", arguments: args)
            let combined = [result.stdout, result.stderr].joined(separator: "\n").trimmingCharacters(in: .whitespacesAndNewlines)
            if let ip = firstIPv4(in: combined), isLikelyPublicIPv4(ip), result.status == 0 {
                return PublicIPResult(host: host, ip: ip, message: "SSH로 호스트 공인 IP를 확인했습니다.", executablePath: "/usr/bin/ssh", exitStatus: result.status, stdout: result.stdout, stderr: result.stderr)
            }
            return PublicIPResult(host: host, ip: nil, message: combined.isEmpty ? "SSH 공인 IP 응답을 판독할 수 없습니다." : combined, executablePath: "/usr/bin/ssh", exitStatus: result.status, stdout: result.stdout, stderr: result.stderr)
        } catch {
            return PublicIPResult(host: host, ip: nil, message: error.localizedDescription, executablePath: "/usr/bin/ssh", exitStatus: nil, stdout: "", stderr: "")
        }
    }

    private static func firstIPv4(in value: String) -> String? {
        let pattern = #"(?<!\d)(\d{1,3}(?:\.\d{1,3}){3})(?!\d)"#
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return nil }
        let range = NSRange(value.startIndex..<value.endIndex, in: value)
        return regex.matches(in: value, range: range).compactMap { match in
            Range(match.range(at: 1), in: value).map { String(value[$0]) }
        }.first
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

    private static func runForResult(executable: String, arguments: [String]) async throws -> ProcessResult {
        try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: .utility).async {
                let process = Process()
                process.executableURL = URL(fileURLWithPath: executable)
                process.arguments = arguments
                let output = Pipe()
                let error = Pipe()
                process.standardOutput = output
                process.standardError = error
                do {
                    try process.run()
                    process.waitUntilExit()
                    let stdout = String(data: output.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
                    let stderr = String(data: error.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
                    continuation.resume(returning: ProcessResult(status: process.terminationStatus, stdout: stdout.trimmingCharacters(in: .whitespacesAndNewlines), stderr: stderr.trimmingCharacters(in: .whitespacesAndNewlines)))
                } catch {
                    continuation.resume(throwing: error)
                }
            }
        }
    }
}
