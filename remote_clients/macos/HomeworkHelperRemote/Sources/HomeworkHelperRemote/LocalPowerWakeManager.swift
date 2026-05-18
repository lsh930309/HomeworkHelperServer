import Foundation

enum LocalPowerWakeManager {
    private static let preferredWakeDeviceName = "PC 켜기"
    private static let smartThingsCommandNames = ["smartthings", "smartthings.exe"]
    private static let smartThingsCLIPathOverrideKey = "HH_REMOTE_SMARTTHINGS_CLI_PATHS"

    private struct ProcessResult {
        let status: Int32
        let stdout: String
        let stderr: String
    }

    private struct CLIResolution {
        let path: String?
        let installAttempted: Bool
        let installSucceeded: Bool
        let message: String
    }

    private struct SmartThingsJSONDevice: Decodable {
        let deviceId: String?
        let id: String?
        let name: String?
        let label: String?
    }

    static func smartThingsCLICandidates() -> [String] {
        smartThingsCLIPathCandidates().filter { FileManager.default.isExecutableFile(atPath: $0) }
    }

    static func resolveSmartThingsCLIPath(_ path: String? = nil) -> String? {
        let selected = (path ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if selected.isEmpty || isBareSmartThingsCommand(selected) {
            return smartThingsCLICandidates().first
        }
        let expanded = NSString(string: selected).expandingTildeInPath
        return FileManager.default.isExecutableFile(atPath: expanded) ? expanded : nil
    }

    static func preferredWakeDevice(from candidates: [RemoteSmartThingsDeviceCandidate]) -> RemoteSmartThingsDeviceCandidate? {
        if let exact = candidates.first(where: { normalizeDeviceName($0.name) == normalizeDeviceName(preferredWakeDeviceName) }) {
            return exact
        }
        if candidates.count == 1 { return candidates[0] }
        return nil
    }

    private static func smartThingsCLIPathCandidates() -> [String] {
        let defaults = [
            "/opt/homebrew/bin/smartthings",
            "/usr/local/bin/smartthings",
            NSString(string: "~/.npm-global/bin/smartthings").expandingTildeInPath
        ]
        let overrides = (ProcessInfo.processInfo.environment[smartThingsCLIPathOverrideKey] ?? "")
            .split(separator: ":")
            .map { NSString(string: String($0)).expandingTildeInPath }
        var seen = Set<String>()
        return (overrides + defaults).filter { path in
            guard !path.isEmpty, !seen.contains(path) else { return false }
            seen.insert(path)
            return true
        }
    }

    static func isLocalSmartThingsCLIPath(_ path: String) -> Bool {
        let trimmed = path.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return false }
        if isBareSmartThingsCommand(trimmed) { return true }
        if trimmed.hasPrefix("/") || trimmed.hasPrefix("~") { return true }
        let expanded = NSString(string: trimmed).expandingTildeInPath
        if smartThingsCLICandidates().contains(expanded) { return true }
        return FileManager.default.isExecutableFile(atPath: expanded)
    }

    static func probeDevices(cliPath: String? = nil) async -> RemoteSmartThingsDevicesResponse {
        let resolution = await ensureSmartThingsCLIPath(cliPath, installIfMissing: true)
        guard let cli = resolution.path else {
            return RemoteSmartThingsDevicesResponse(
                available: false,
                devices: [],
                deviceCandidates: [],
                message: resolution.message,
                cliPath: nil,
                installAttempted: resolution.installAttempted,
                installSucceeded: resolution.installSucceeded
            )
        }
        do {
            let result = try await runForResult(executable: cli, arguments: ["devices"])
            let lines = result.stdout.split(separator: "\n").map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
            let candidates = parseSmartThingsDevices(lines)
            let statusMessage = result.status == 0 ? "Mac SmartThings device 목록 조회 완료" : (result.stderr.isEmpty ? "Mac SmartThings 로그인/권한 확인 필요" : result.stderr)
            let message = [resolution.message, statusMessage].filter { !$0.isEmpty }.joined(separator: " ")
            return RemoteSmartThingsDevicesResponse(
                available: result.status == 0,
                devices: lines,
                deviceCandidates: result.status == 0 ? candidates : [],
                message: message,
                cliPath: cli,
                installAttempted: resolution.installAttempted,
                installSucceeded: resolution.installSucceeded
            )
        } catch {
            return RemoteSmartThingsDevicesResponse(
                available: false,
                devices: [],
                deviceCandidates: [],
                message: "Mac SmartThings CLI 실행 실패: \(error.localizedDescription)",
                cliPath: cli,
                installAttempted: resolution.installAttempted,
                installSucceeded: resolution.installSucceeded
            )
        }
    }

    static func wake(config: RemotePowerConfigPayload) async throws -> String {
        let resolution = await ensureSmartThingsCLIPath(config.smartthingsCLIPath, installIfMissing: true)
        let deviceID = config.smartthingsDeviceID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard let cli = resolution.path, !deviceID.isEmpty else {
            throw NSError(domain: "LocalPowerWakeManager", code: 1, userInfo: [NSLocalizedDescriptionKey: "Mac에 저장된 SmartThings CLI/device id가 없어 로컬 wake를 보낼 수 없습니다."])
        }
        let result = try await runForResult(executable: cli, arguments: ["devices:commands", deviceID, "switch:on"])
        guard result.status == 0 else {
            throw NSError(domain: "LocalPowerWakeManager", code: Int(result.status), userInfo: [NSLocalizedDescriptionKey: result.stderr.isEmpty ? "SmartThings wake 명령 실패" : result.stderr])
        }
        return "호스트 서버가 꺼진 상태에서 Mac의 SmartThings CLI로 wake 신호를 보냈습니다."
    }

    private static func parseSmartThingsDevices(_ lines: [String]) -> [RemoteSmartThingsDeviceCandidate] {
        let joined = lines.joined(separator: "\n")
        if let data = joined.data(using: .utf8),
           let jsonDevices = try? JSONDecoder().decode([SmartThingsJSONDevice].self, from: data) {
            return jsonDevices.compactMap { item in
                let id = (item.deviceId ?? item.id ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
                guard !id.isEmpty else { return nil }
                let name = (item.label ?? item.name ?? id).trimmingCharacters(in: .whitespacesAndNewlines)
                return RemoteSmartThingsDeviceCandidate(id: id, name: name.isEmpty ? id : name, raw: id)
            }
        }
        return lines.compactMap { line in
            let lowered = line.lowercased()
            if line.isEmpty || lowered.hasPrefix("id ") || lowered.contains("device id") || line.contains("----") || line.contains("──") { return nil }
            if let tableCandidate = parseSmartThingsTableRow(line) {
                return tableCandidate
            }
            let parts = line.split(whereSeparator: { $0 == " " || $0 == "\t" }).map(String.init)
            guard let id = parts.first, id.count >= 8, !["id", "name", "label"].contains(id.lowercased()) else { return nil }
            let name = parts.dropFirst().joined(separator: " ")
            return RemoteSmartThingsDeviceCandidate(id: id, name: name.isEmpty ? id : name, raw: line)
        }
    }

    private static func parseSmartThingsTableRow(_ line: String) -> RemoteSmartThingsDeviceCandidate? {
        let pattern = #"^\s*\d+\s+(.+?)\s{2,}(.+?)\s{2,}(\S+)\s+([0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12})\s*$"#
        guard let match = firstMatch(pattern: pattern, in: line), match.count == 4 else { return nil }
        let label = match[0].trimmingCharacters(in: .whitespacesAndNewlines)
        let name = match[1].trimmingCharacters(in: .whitespacesAndNewlines)
        let deviceID = match[3].trimmingCharacters(in: .whitespacesAndNewlines)
        return RemoteSmartThingsDeviceCandidate(id: deviceID, name: label.isEmpty ? name : label, raw: line)
    }

    private static func firstMatch(pattern: String, in value: String) -> [String]? {
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return nil }
        let range = NSRange(value.startIndex..<value.endIndex, in: value)
        guard let match = regex.firstMatch(in: value, range: range), match.numberOfRanges > 1 else { return nil }
        return (1..<match.numberOfRanges).compactMap { index in
            guard let range = Range(match.range(at: index), in: value) else { return nil }
            return String(value[range])
        }
    }

    private static func ensureSmartThingsCLIPath(_ path: String?, installIfMissing: Bool) async -> CLIResolution {
        if let resolved = resolveSmartThingsCLIPath(path) {
            return CLIResolution(path: resolved, installAttempted: false, installSucceeded: false, message: "")
        }
        let selected = (path ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        if !selected.isEmpty && !isBareSmartThingsCommand(selected) {
            if let fallback = resolveSmartThingsCLIPath(nil) {
                return CLIResolution(path: fallback, installAttempted: false, installSucceeded: false, message: "설정된 SmartThings CLI 대신 Mac 로컬 CLI를 사용합니다.")
            }
            if installIfMissing, await installSmartThingsCLI(), let fallback = resolveSmartThingsCLIPath(nil) {
                return CLIResolution(path: fallback, installAttempted: true, installSucceeded: true, message: "설정된 SmartThings CLI 대신 자동 설치한 Mac 로컬 CLI를 사용합니다.")
            }
            return CLIResolution(path: nil, installAttempted: false, installSucceeded: false, message: "설정된 SmartThings CLI를 실행할 수 없습니다: \(selected)")
        }
        guard installIfMissing else {
            return CLIResolution(path: nil, installAttempted: false, installSucceeded: false, message: "Mac에서 SmartThings CLI를 찾지 못했습니다.")
        }
        let installed = await installSmartThingsCLI()
        if installed, let resolved = resolveSmartThingsCLIPath(path) {
            return CLIResolution(path: resolved, installAttempted: true, installSucceeded: true, message: "SmartThings CLI 자동 설치 완료.")
        }
        return CLIResolution(path: nil, installAttempted: true, installSucceeded: false, message: "SmartThings CLI를 찾지 못했고 Homebrew 자동 설치에 실패했습니다.")
    }

    private static func installSmartThingsCLI() async -> Bool {
        guard let brew = firstExecutable(["/opt/homebrew/bin/brew", "/usr/local/bin/brew"]) else { return false }
        guard let result = try? await runForResult(executable: brew, arguments: ["install", "smartthings"]) else {
            return false
        }
        return result.status == 0 || resolveSmartThingsCLIPath() != nil
    }

    private static func firstExecutable(_ paths: [String]) -> String? {
        paths.first { FileManager.default.isExecutableFile(atPath: $0) }
    }

    private static func isBareSmartThingsCommand(_ value: String) -> Bool {
        smartThingsCommandNames.contains(value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased())
    }

    private static func normalizeDeviceName(_ value: String) -> String {
        value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
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
                    continuation.resume(returning: ProcessResult(status: process.terminationStatus, stdout: stdout, stderr: stderr.trimmingCharacters(in: .whitespacesAndNewlines)))
                } catch {
                    continuation.resume(throwing: error)
                }
            }
        }
    }
}
