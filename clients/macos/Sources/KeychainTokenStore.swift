import Foundation
import Security

protocol RemoteTokenStore {
    func load() -> String
    func save(_ token: String)
    func delete()
}

struct KeychainTokenStore: RemoteTokenStore {
    private let service = "dev.homeworkhelper.remote"
    private let account = "remote-api-token"

    func load() -> String {
        var query = baseQuery()
        query[kSecReturnData as String] = true
        query[kSecMatchLimit as String] = kSecMatchLimitOne

        var result: AnyObject?
        let status = SecItemCopyMatching(query as CFDictionary, &result)
        guard status == errSecSuccess, let data = result as? Data else { return "" }
        return String(data: data, encoding: .utf8) ?? ""
    }

    func save(_ token: String) {
        if token.isEmpty {
            delete()
            return
        }
        let data = Data(token.utf8)
        let attributes = [kSecValueData as String: data]
        let status = SecItemUpdate(baseQuery() as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            var query = baseQuery()
            query[kSecValueData as String] = data
            SecItemAdd(query as CFDictionary, nil)
        }
    }

    func delete() {
        SecItemDelete(baseQuery() as CFDictionary)
    }

    private func baseQuery() -> [String: Any] {
        [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account,
        ]
    }
}


final class InMemoryTokenStore: RemoteTokenStore {
    private var token: String

    init(initialToken: String = "") {
        self.token = initialToken
    }

    func load() -> String {
        token
    }

    func save(_ token: String) {
        self.token = token
    }

    func delete() {
        token = ""
    }
}
