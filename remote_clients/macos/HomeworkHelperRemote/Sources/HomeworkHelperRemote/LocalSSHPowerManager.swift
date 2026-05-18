import Foundation

enum LocalSSHPowerManager {
    static let acceptedMarker = "__HH_REMOTE_POWER_ACCEPTED__"

    private struct ProcessResult {
        let status: Int32
        let stdout: String
        let stderr: String
    }

    static func command(for action: String) throws -> String {
        switch action {
        case "shutdown":
            return "cmd /C shutdown /s /t 0 && echo \(acceptedMarker)"
        case "restart":
            return "cmd /C shutdown /r /t 0 && echo \(acceptedMarker)"
        case "sleep":
            return "cmd /C start \"\" rundll32.exe powrprof.dll,SetSuspendState 0,0,0 && echo \(acceptedMarker)"
        default:
            throw NSError(domain: "LocalSSHPowerManager", code: 1, userInfo: [NSLocalizedDescriptionKey: "지원하지 않는 SSH 전원 명령입니다: \(action)"])
        }
    }

    static func run(action: String, config: RemotePowerConfigPayload) async throws -> String {
        let command = try command(for: action)
        var extraArgs: [String] = []
        if action == "sleep" {
            extraArgs = ["-o", "ServerAliveInterval=2", "-o", "ServerAliveCountMax=2"]
        }

        let host = config.sshHost.trimmingCharacters(in: .whitespacesAndNewlines)
        let user = config.sshUser.trimmingCharacters(in: .whitespacesAndNewlines)
        let keyPath = NSString(string: config.sshKeyPath.trimmingCharacters(in: .whitespacesAndNewlines)).expandingTildeInPath
        guard !host.isEmpty, !user.isEmpty, !keyPath.isEmpty else {
            throw NSError(domain: "LocalSSHPowerManager", code: 2, userInfo: [NSLocalizedDescriptionKey: "Mac에 저장된 SSH host/user/key path가 없어 SSH 전원 명령을 보낼 수 없습니다."])
        }

        var args = [
            "-i", keyPath,
            "-p", String(config.sshPort),
            "-o", "ConnectTimeout=5",
            "-o", "BatchMode=yes",
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
