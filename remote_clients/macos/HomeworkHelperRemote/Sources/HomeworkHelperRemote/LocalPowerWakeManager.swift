import Foundation

enum LocalPowerWakeManager {
    private struct ProcessResult {
        let status: Int32
        let stdout: String
        let stderr: String
    }

    private struct SmartThingsJSONDevice: Decodable {
        let deviceId: String?
        let id: String?
        let name: String?
        let label: String?
    }

    static func smartThingsCLICandidates() -> [String] {
        let paths = [
            "/opt/homebrew/bin/smartthings",
            "/usr/local/bin/smartthings",
            NSString(string: "~/.npm-global/bin/smartthings").expandingTildeInPath
        ]
        return paths.filter { FileManager.default.isExecutableFile(atPath: $0) }
    }

    static func isLocalSmartThingsCLIPath(_ path: String) -> Bool {
        let expanded = NSString(string: path.trimmingCharacters(in: .whitespacesAndNewlines)).expandingTildeInPath
        guard !expanded.isEmpty else { return false }
        if smartThingsCLICandidates().contains(expanded) { return true }
        return FileManager.default.isExecutableFile(atPath: expanded)
    }

    static func probeDevices(cliPath: String? = nil) async -> RemoteSmartThingsDevicesResponse {
        let selected = (cliPath ?? "").trimmingCharacters(in: .whitespacesAndNewlines)
        let cli = selected.isEmpty ? smartThingsCLICandidates().first ?? "" : NSString(string: selected).expandingTildeInPath
        guard !cli.isEmpty else {
            return RemoteSmartThingsDevicesResponse(
                available: false,
                devices: [],
                deviceCandidates: [],
                message: "Mac에서 SmartThings CLI를 찾지 못했습니다.",
                cliPath: nil
            )
        }
        do {
            let result = try await runForResult(executable: cli, arguments: ["devices"])
            let lines = result.stdout.split(separator: "\n").map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
            let candidates = parseSmartThingsDevices(lines)
            return RemoteSmartThingsDevicesResponse(
                available: result.status == 0,
                devices: lines,
                deviceCandidates: result.status == 0 ? candidates : [],
                message: result.status == 0 ? "Mac SmartThings device 목록 조회 완료" : (result.stderr.isEmpty ? "Mac SmartThings 로그인/권한 확인 필요" : result.stderr),
                cliPath: cli
            )
        } catch {
            return RemoteSmartThingsDevicesResponse(
                available: false,
                devices: [],
                deviceCandidates: [],
                message: "Mac SmartThings CLI 실행 실패: \(error.localizedDescription)",
                cliPath: cli
            )
        }
    }

    static func wake(config: RemotePowerConfigPayload) async throws -> String {
        let cli = config.smartthingsCLIPath.trimmingCharacters(in: .whitespacesAndNewlines)
        let deviceID = config.smartthingsDeviceID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cli.isEmpty, !deviceID.isEmpty else {
            throw NSError(domain: "LocalPowerWakeManager", code: 1, userInfo: [NSLocalizedDescriptionKey: "Mac에 저장된 SmartThings CLI/device id가 없어 로컬 wake를 보낼 수 없습니다."])
        }
        let result = try await runForResult(executable: NSString(string: cli).expandingTildeInPath, arguments: ["devices:commands", deviceID, "switch:on"])
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
            if line.isEmpty || lowered.hasPrefix("id ") || line.contains("----") { return nil }
            let parts = line.split(whereSeparator: { $0 == " " || $0 == "\t" }).map(String.init)
            guard let id = parts.first, id.count >= 8, !["id", "name", "label"].contains(id.lowercased()) else { return nil }
            let name = parts.dropFirst().joined(separator: " ")
            return RemoteSmartThingsDeviceCandidate(id: id, name: name.isEmpty ? id : name, raw: line)
        }
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
