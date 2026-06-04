import AppKit
import Foundation

struct RemoteClientCache {
    private static let appDirectoryName = "HomeworkHelperRemote"
    private static let iconCacheVersion = "v3_pixels"
    private static let cacheDirectoryOverrideKey = "HH_REMOTE_CACHE_DIR"

    private static var cacheDirectoryOverride: String? {
        let value = ProcessInfo.processInfo.environment[cacheDirectoryOverrideKey]?.trimmingCharacters(in: .whitespacesAndNewlines)
        return value?.isEmpty == false ? value : nil
    }

    static var cacheDirectory: URL {
        if let override = cacheDirectoryOverride {
            let directory = URL(fileURLWithPath: override, isDirectory: true)
            try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            return directory
        }
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

    private static var iconDiagnosticsURL: URL {
        cacheDirectory.appendingPathComponent("icon-diagnostics.log")
    }

    static func loadProcesses() -> [RemoteProcess] {
        guard let data = try? Data(contentsOf: processSnapshotURL) else { return [] }
        let processes = (try? JSONDecoder().decode([RemoteProcess].self, from: data)) ?? []
        if cacheDirectoryOverride == nil, isSmokeOnlySnapshot(processes) {
            return []
        }
        return processes
    }

    static func saveProcesses(_ processes: [RemoteProcess]) {
        guard let data = try? JSONEncoder().encode(processes) else { return }
        try? data.write(to: processSnapshotURL, options: [.atomic])
    }

    private static func isSmokeOnlySnapshot(_ processes: [RemoteProcess]) -> Bool {
        processes.count == 1 && processes.first?.id == "smoke-game" && processes.first?.name == "Smoke Game"
    }

    static func cachedIconURL(for process: RemoteProcess, preferredSize: Int = 256) -> URL? {
        let url = iconFileURL(for: process, preferredSize: preferredSize)
        return validatedCachedURL(url, minimumPixelSize: preferredSize)
    }

    static func cachedResourceIconURL(for process: RemoteProcess, preferredSize: Int = 128) -> URL? {
        let url = resourceIconFileURL(for: process, preferredSize: preferredSize)
        return validatedCachedURL(url, minimumPixelSize: preferredSize)
    }

    static func displayIconImage(for process: RemoteProcess, preferredSize: Int = 256, displayPointSize: CGFloat) -> NSImage? {
        guard let sourceURL = cachedIconURL(for: process, preferredSize: preferredSize) else { return nil }
        let scale = displayScale()
        let pixelSize = max(1, Int(ceil(displayPointSize * scale)))
        let thumbnailURL = displayIconFileURL(for: process, preferredSize: preferredSize, pixelSize: pixelSize)
        return displayThumbnailImage(
            sourceURL: sourceURL,
            thumbnailURL: thumbnailURL,
            displayPointSize: displayPointSize,
            pixelSize: pixelSize,
            scale: scale,
            kind: "game",
            processID: process.id
        )
    }

    static func displayResourceIconImage(for process: RemoteProcess, preferredSize: Int = 128, displayPointSize: CGFloat) -> NSImage? {
        guard let sourceURL = cachedResourceIconURL(for: process, preferredSize: preferredSize) else { return nil }
        let scale = displayScale()
        let pixelSize = max(1, Int(ceil(displayPointSize * scale)))
        let thumbnailURL = displayResourceIconFileURL(for: process, preferredSize: preferredSize, pixelSize: pixelSize)
        return displayThumbnailImage(
            sourceURL: sourceURL,
            thumbnailURL: thumbnailURL,
            displayPointSize: displayPointSize,
            pixelSize: pixelSize,
            scale: scale,
            kind: "resource",
            processID: process.id
        )
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
                guard decodedPixelDimension(data) >= preferredSize else { continue }
                let destination = iconFileURL(for: process, preferredSize: preferredSize)
                try data.write(to: destination, options: [.atomic])
                logIconDiagnostic(kind: "game.download", processID: process.id, sourceURL: source.absoluteString, cachedPath: destination.path, pixelSize: decodedPixelDimension(data), displayPointSize: nil, scale: nil)
            } catch {
                continue
            }
        }
        for process in processes {
            let preferredSize = 128
            guard cachedResourceIconURL(for: process, preferredSize: preferredSize) == nil,
                  let source = remoteResourceIconURL(for: process, baseURL: baseURL, preferredSize: preferredSize) else { continue }
            do {
                let (data, response) = try await URLSession.shared.data(from: source)
                guard let http = response as? HTTPURLResponse, (200..<300).contains(http.statusCode) else { continue }
                guard (http.value(forHTTPHeaderField: "Content-Type") ?? "").contains("image/png") else { continue }
                guard decodedPixelDimension(data) >= preferredSize else { continue }
                let destination = resourceIconFileURL(for: process, preferredSize: preferredSize)
                try data.write(to: destination, options: [.atomic])
                logIconDiagnostic(kind: "resource.download", processID: process.id, sourceURL: source.absoluteString, cachedPath: destination.path, pixelSize: decodedPixelDimension(data), displayPointSize: nil, scale: nil)
            } catch {
                continue
            }
        }
    }

    static func remoteIconURL(for process: RemoteProcess, baseURL: URL, preferredSize: Int = 256) -> URL? {
        guard let raw = bestURL(from: process.iconURLs, preferredSize: preferredSize) ?? process.iconURL, !raw.isEmpty else { return nil }
        if let absolute = URL(string: raw), absolute.scheme != nil {
            return isSameOrigin(absolute, baseURL: baseURL) ? absolute : nil
        }
        guard var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false) else { return nil }
        let path = raw.hasPrefix("/") ? raw : "/\(raw)"
        let parts = path.split(separator: "?", maxSplits: 1, omittingEmptySubsequences: false)
        components.path = String(parts[0])
        components.query = parts.count > 1 ? String(parts[1]) : nil
        return components.url
    }

    static func remoteResourceIconURL(for process: RemoteProcess, baseURL: URL, preferredSize: Int = 128) -> URL? {
        guard let raw = bestURL(from: process.progress?.resourceIconURLs, preferredSize: preferredSize) ?? process.progress?.resourceIconURL, !raw.isEmpty else { return nil }
        if let absolute = URL(string: raw), absolute.scheme != nil {
            return isSameOrigin(absolute, baseURL: baseURL) ? absolute : nil
        }
        guard var components = URLComponents(url: baseURL, resolvingAgainstBaseURL: false) else { return nil }
        let path = raw.hasPrefix("/") ? raw : "/\(raw)"
        let parts = path.split(separator: "?", maxSplits: 1, omittingEmptySubsequences: false)
        components.path = String(parts[0])
        components.query = parts.count > 1 ? String(parts[1]) : nil
        return components.url
    }

    private static func isSameOrigin(_ url: URL, baseURL: URL) -> Bool {
        url.scheme?.lowercased() == baseURL.scheme?.lowercased()
            && url.host?.lowercased() == baseURL.host?.lowercased()
            && (url.port ?? defaultPort(for: url.scheme)) == (baseURL.port ?? defaultPort(for: baseURL.scheme))
    }

    private static func defaultPort(for scheme: String?) -> Int? {
        switch scheme?.lowercased() {
        case "http": return 80
        case "https": return 443
        default: return nil
        }
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

    private static func displayIconFileURL(for process: RemoteProcess, preferredSize: Int, pixelSize: Int) -> URL {
        let safeID = process.id.replacingOccurrences(of: "[^A-Za-z0-9_.-]", with: "_", options: .regularExpression)
        return iconDirectory.appendingPathComponent("\(safeID)_display_\(iconCacheVersion)_\(preferredSize)_\(pixelSize).png")
    }

    private static func displayResourceIconFileURL(for process: RemoteProcess, preferredSize: Int, pixelSize: Int) -> URL {
        let safeID = process.id.replacingOccurrences(of: "[^A-Za-z0-9_.-]", with: "_", options: .regularExpression)
        return iconDirectory.appendingPathComponent("\(safeID)_resource_display_\(iconCacheVersion)_\(preferredSize)_\(pixelSize).png")
    }

    private static func validatedCachedURL(_ url: URL, minimumPixelSize: Int) -> URL? {
        guard FileManager.default.fileExists(atPath: url.path) else { return nil }
        guard let image = NSImage(contentsOf: url), pixelDimension(image) >= minimumPixelSize else {
            try? FileManager.default.removeItem(at: url)
            return nil
        }
        return url
    }

    private static func decodedPixelDimension(_ data: Data) -> Int {
        guard let image = NSImage(data: data) else { return 0 }
        return pixelDimension(image)
    }

    private static func pixelDimension(_ image: NSImage) -> Int {
        let representationMax = image.representations.map { max($0.pixelsWide, $0.pixelsHigh) }.max() ?? 0
        let pointMax = Int(max(image.size.width, image.size.height))
        return max(representationMax, pointMax)
    }

    private static func displayScale() -> CGFloat {
        NSScreen.main?.backingScaleFactor ?? 2
    }

    private static func displayThumbnailImage(
        sourceURL: URL,
        thumbnailURL: URL,
        displayPointSize: CGFloat,
        pixelSize: Int,
        scale: CGFloat,
        kind: String,
        processID: String
    ) -> NSImage? {
        if let cached = validatedCachedURL(thumbnailURL, minimumPixelSize: pixelSize),
           let image = NSImage(contentsOf: cached) {
            image.size = NSSize(width: displayPointSize, height: displayPointSize)
            return image
        }
        guard let source = NSImage(contentsOf: sourceURL),
              let thumbnail = renderThumbnail(from: source, displayPointSize: displayPointSize, pixelSize: pixelSize),
              let data = thumbnail.tiffRepresentation,
              let bitmap = NSBitmapImageRep(data: data),
              let png = bitmap.representation(using: .png, properties: [:]) else {
            logIconDiagnostic(kind: "\(kind).display_thumbnail_failed", processID: processID, sourceURL: sourceURL.absoluteString, cachedPath: thumbnailURL.path, pixelSize: pixelSize, displayPointSize: displayPointSize, scale: scale)
            return nil
        }
        try? png.write(to: thumbnailURL, options: [.atomic])
        logIconDiagnostic(kind: "\(kind).display_thumbnail", processID: processID, sourceURL: sourceURL.absoluteString, cachedPath: thumbnailURL.path, pixelSize: pixelSize, displayPointSize: displayPointSize, scale: scale)
        return thumbnail
    }

    private static func renderThumbnail(from source: NSImage, displayPointSize: CGFloat, pixelSize: Int) -> NSImage? {
        guard pixelSize > 0, displayPointSize > 0 else { return nil }
        let pointSize = NSSize(width: displayPointSize, height: displayPointSize)
        guard let representation = NSBitmapImageRep(
            bitmapDataPlanes: nil,
            pixelsWide: pixelSize,
            pixelsHigh: pixelSize,
            bitsPerSample: 8,
            samplesPerPixel: 4,
            hasAlpha: true,
            isPlanar: false,
            colorSpaceName: .deviceRGB,
            bytesPerRow: 0,
            bitsPerPixel: 0
        ) else { return nil }
        representation.size = pointSize
        NSGraphicsContext.saveGraphicsState()
        defer { NSGraphicsContext.restoreGraphicsState() }
        guard let context = NSGraphicsContext(bitmapImageRep: representation) else { return nil }
        context.imageInterpolation = .high
        NSGraphicsContext.current = context
        source.draw(in: aspectFitRect(sourceSize: source.size, targetSize: pointSize), from: .zero, operation: .copy, fraction: 1.0)
        let image = NSImage(size: pointSize)
        image.addRepresentation(representation)
        return image
    }

    private static func aspectFitRect(sourceSize: NSSize, targetSize: NSSize) -> NSRect {
        guard sourceSize.width > 0, sourceSize.height > 0 else {
            return NSRect(origin: .zero, size: targetSize)
        }
        let scale = min(targetSize.width / sourceSize.width, targetSize.height / sourceSize.height)
        let size = NSSize(width: sourceSize.width * scale, height: sourceSize.height * scale)
        return NSRect(
            x: (targetSize.width - size.width) / 2,
            y: (targetSize.height - size.height) / 2,
            width: size.width,
            height: size.height
        )
    }

    private static func logIconDiagnostic(kind: String, processID: String, sourceURL: String, cachedPath: String, pixelSize: Int, displayPointSize: CGFloat?, scale: CGFloat?) {
        let fields: [String: String] = [
            "event": "icon.diagnostic",
            "kind": kind,
            "process_id": processID,
            "source_url": sourceURL,
            "cached_path": cachedPath,
            "pixel_size": String(pixelSize),
            "display_point_size": displayPointSize.map { String(Double($0)) } ?? "",
            "scale": scale.map { String(Double($0)) } ?? "",
            "ts": String(Date().timeIntervalSince1970),
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: fields),
              let line = String(data: data, encoding: .utf8) else { return }
        if !FileManager.default.fileExists(atPath: iconDiagnosticsURL.path) {
            FileManager.default.createFile(atPath: iconDiagnosticsURL.path, contents: nil)
        }
        guard let handle = try? FileHandle(forWritingTo: iconDiagnosticsURL) else { return }
        do {
            try handle.seekToEnd()
            try handle.write(contentsOf: Data((line + "\n").utf8))
            try handle.close()
        } catch {
            try? handle.close()
        }
    }
}
