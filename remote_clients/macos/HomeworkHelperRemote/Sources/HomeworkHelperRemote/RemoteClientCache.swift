import Foundation

struct RemoteClientCache {
    private static let appDirectoryName = "HomeworkHelperRemote"
    private static let iconCacheVersion = "v2"

    static var cacheDirectory: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first!
        let directory = base.appendingPathComponent(appDirectoryName, isDirectory: true).appendingPathComponent("cache", isDirectory: true)
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory
    }

    private static var processSnapshotURL: URL {
        cacheDirectory.appendingPathComponent("processes.json")
    }

    private static var iconDirectory: URL {
        let directory = cacheDirectory.appendingPathComponent("icons", isDirectory: true)
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return directory
    }

    static func loadProcesses() -> [RemoteProcess] {
        guard let data = try? Data(contentsOf: processSnapshotURL) else { return [] }
        return (try? JSONDecoder().decode([RemoteProcess].self, from: data)) ?? []
    }

    static func saveProcesses(_ processes: [RemoteProcess]) {
        guard let data = try? JSONEncoder().encode(processes) else { return }
        try? data.write(to: processSnapshotURL, options: [.atomic])
    }

    static func cachedIconURL(for process: RemoteProcess, preferredSize: Int = 256) -> URL? {
        let url = iconFileURL(for: process, preferredSize: preferredSize)
        return FileManager.default.fileExists(atPath: url.path) ? url : nil
    }

    static func cachedResourceIconURL(for process: RemoteProcess, preferredSize: Int = 64) -> URL? {
        let url = resourceIconFileURL(for: process, preferredSize: preferredSize)
        return FileManager.default.fileExists(atPath: url.path) ? url : nil
    }

    static func cacheIcons(for processes: [RemoteProcess], baseURL: URL) async {
        for process in processes {
            let preferredSize = 256
            guard cachedIconURL(for: process, preferredSize: preferredSize) == nil,
                  let source = remoteIconURL(for: process, baseURL: baseURL, preferredSize: preferredSize) else { continue }
            do {
                let (data, response) = try await URLSession.shared.data(from: source)
                guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else { continue }
                guard (http.value(forHTTPHeaderField: "Content-Type") ?? "").contains("image/png") else { continue }
                try data.write(to: iconFileURL(for: process, preferredSize: preferredSize), options: [.atomic])
            } catch {
                continue
            }
        }
        for process in processes {
            let preferredSize = 64
            guard cachedResourceIconURL(for: process, preferredSize: preferredSize) == nil,
                  let source = remoteResourceIconURL(for: process, baseURL: baseURL, preferredSize: preferredSize) else { continue }
            do {
                let (data, response) = try await URLSession.shared.data(from: source)
                guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else { continue }
                guard (http.value(forHTTPHeaderField: "Content-Type") ?? "").contains("image/png") else { continue }
                try data.write(to: resourceIconFileURL(for: process, preferredSize: preferredSize), options: [.atomic])
            } catch {
                continue
            }
        }
    }

    static func remoteIconURL(for process: RemoteProcess, baseURL: URL, preferredSize: Int = 256) -> URL? {
        guard let raw = bestURL(from: process.iconURLs, preferredSize: preferredSize) ?? process.iconURL, !raw.isEmpty else { return nil }
        if let absolute = URL(string: raw), absolute.scheme != nil { return absolute }
        guard var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false) else { return nil }
        let path = raw.hasPrefix("/") ? raw : "/\(raw)"
        let parts = path.split(separator: "?", maxSplits: 1, omittingEmptySubsequences: false)
        components.path = String(parts[0])
        components.query = parts.count > 1 ? String(parts[1]) : nil
        return components.url
    }

    static func remoteResourceIconURL(for process: RemoteProcess, baseURL: URL, preferredSize: Int = 64) -> URL? {
        guard let raw = bestURL(from: process.progress?.resourceIconURLs, preferredSize: preferredSize) ?? process.progress?.resourceIconURL, !raw.isEmpty else { return nil }
        if let absolute = URL(string: raw), absolute.scheme != nil { return absolute }
        guard var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false) else { return nil }
        let path = raw.hasPrefix("/") ? raw : "/\(raw)"
        let parts = path.split(separator: "?", maxSplits: 1, omittingEmptySubsequences: false)
        components.path = String(parts[0])
        components.query = parts.count > 1 ? String(parts[1]) : nil
        return components.url
    }

    private static func bestURL(from variants: [String: String]?, preferredSize: Int) -> String? {
        guard let variants, !variants.isEmpty else { return nil }
        if let exact = variants[String(preferredSize)] { return exact }
        let sizes = variants.keys.compactMap(Int.init).sorted()
        if let size = sizes.first(where: { $0 >= preferredSize }) ?? sizes.last {
            return variants[String(size)]
        }
        return nil
    }

    private static func iconFileURL(for process: RemoteProcess, preferredSize: Int) -> URL {
        let safeID = process.id.replacingOccurrences(of: "[^A-Za-z0-9_.-]", with: "_", options: .regularExpression)
        return iconDirectory.appendingPathComponent("\(safeID)_\(iconCacheVersion)_\(preferredSize).png")
    }

    private static func resourceIconFileURL(for process: RemoteProcess, preferredSize: Int) -> URL {
        let safeID = process.id.replacingOccurrences(of: "[^A-Za-z0-9_.-]", with: "_", options: .regularExpression)
        return iconDirectory.appendingPathComponent("\(safeID)_resource_\(iconCacheVersion)_\(preferredSize).png")
    }
}
