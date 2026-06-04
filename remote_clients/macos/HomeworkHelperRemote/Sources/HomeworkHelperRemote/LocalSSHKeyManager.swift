import Foundation

struct LocalSSHKeyPair: Equatable {
    let privateKeyPath: String
    let publicKeyPath: String
    let publicKey: String
    let created: Bool
}

enum LocalSSHKeyManager {
    static let defaultPrivateKeyPath = "~/.ssh/homeworkhelper_remote_ed25519"

    static func ensureKeyPair(privateKeyPath: String = defaultPrivateKeyPath) async throws -> LocalSSHKeyPair {
        let privatePath = expandTilde(privateKeyPath)
        let publicPath = privatePath + ".pub"
        let fm = FileManager.default
        if fm.fileExists(atPath: privatePath), fm.fileExists(atPath: publicPath) {
            return LocalSSHKeyPair(privateKeyPath: privatePath, publicKeyPath: publicPath, publicKey: try String(contentsOfFile: publicPath, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines), created: false)
        }
        try fm.createDirectory(atPath: (privatePath as NSString).deletingLastPathComponent, withIntermediateDirectories: true)
        try await runSSHKeygen(privatePath: privatePath)
        return LocalSSHKeyPair(privateKeyPath: privatePath, publicKeyPath: publicPath, publicKey: try String(contentsOfFile: publicPath, encoding: .utf8).trimmingCharacters(in: .whitespacesAndNewlines), created: true)
    }

    private static func expandTilde(_ path: String) -> String {
        NSString(string: path).expandingTildeInPath
    }

    private static func runSSHKeygen(privatePath: String) async throws {
        try await withCheckedThrowingContinuation { continuation in
            DispatchQueue.global(qos: .utility).async {
                let process = Process()
                process.executableURL = URL(fileURLWithPath: "/usr/bin/ssh-keygen")
                process.arguments = ["-t", "ed25519", "-f", privatePath, "-N", "", "-C", "HomeworkHelper Remote"]
                process.standardOutput = FileHandle.nullDevice
                process.standardError = FileHandle.nullDevice
                do {
                    try process.run()
                    process.waitUntilExit()
                    if process.terminationStatus == 0 {
                        continuation.resume()
                    } else {
                        continuation.resume(throwing: NSError(domain: "LocalSSHKeyManager", code: Int(process.terminationStatus), userInfo: [NSLocalizedDescriptionKey: "ssh-keygen 실행 실패"]))
                    }
                } catch {
                    continuation.resume(throwing: error)
                }
            }
        }
    }
}
