import Foundation

enum RemotePayloadSyncScope: Equatable {
    case revisionAware
    case forceProcesses
    case forceFull

    func merged(with other: RemotePayloadSyncScope) -> RemotePayloadSyncScope {
        if self == .forceFull || other == .forceFull { return .forceFull }
        if self == .forceProcesses || other == .forceProcesses { return .forceProcesses }
        return .revisionAware
    }
}

enum RemoteSmartPollController {
    static let launchChaseFallbackDelaysNanoseconds: [UInt64] = [
        0,
        750_000_000,
        1_500_000_000,
        3_000_000_000,
    ]

    static func launchChaseDelaysNanoseconds(refreshAfterMilliseconds: Int?) -> [UInt64] {
        var delays = launchChaseFallbackDelaysNanoseconds
        guard let refreshAfterMilliseconds, refreshAfterMilliseconds > 0 else { return delays }
        let clampedMilliseconds = min(5_000, max(250, refreshAfterMilliseconds))
        delays[1] = UInt64(clampedMilliseconds) * 1_000_000
        return delays
    }
}
