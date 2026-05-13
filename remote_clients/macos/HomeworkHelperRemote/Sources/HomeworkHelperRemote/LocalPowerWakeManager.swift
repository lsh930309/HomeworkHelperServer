import Foundation

enum LocalPowerWakeManager {
    static func wake(config: RemotePowerConfigPayload) async throws -> String {
        let cli = config.smartthingsCLIPath.trimmingCharacters(in: .whitespacesAndNewlines)
        let deviceID = config.smartthingsDeviceID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !cli.isEmpty, !deviceID.isEmpty else {
            throw NSError(domain: "LocalPowerWakeManager", code: 1, userInfo: [NSLocalizedDescriptionKey: "Mac에 저장된 SmartThings CLI/device id가 없어 로컬 wake를 보낼 수 없습니다."])
        }
        try await run(executable: NSString(string: cli).expandingTildeInPath, arguments: ["devices:commands", deviceID, "switch:on"])
        return "호스트 서버가 꺼진 상태에서 Mac의 SmartThings CLI로 wake 신호를 보냈습니다."
    }

    private static func run(executable: String, arguments: [String]) async throws {
        try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: .utility).async {
                let process = Process()
                process.executableURL = URL(fileURLWithPath: executable)
                process.arguments = arguments
                process.standardOutput = FileHandle.nullDevice
                process.standardError = FileHandle.nullDevice
                do {
                    try process.run()
                    process.waitUntilExit()
                    if process.terminationStatus == 0 {
                        continuation.resume()
                    } else {
                        continuation.resume(throwing: NSError(domain: "LocalPowerWakeManager", code: Int(process.terminationStatus), userInfo: [NSLocalizedDescriptionKey: "SmartThings wake 명령 실패"]))
                    }
                } catch {
                    continuation.resume(throwing: error)
                }
            }
        }
    }
}
