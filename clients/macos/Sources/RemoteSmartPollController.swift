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
    static let slowStatusThresholdMilliseconds: Double = 1_500
    static let launchChaseFallbackDelaysNanoseconds: [UInt64] = [
        0,
        750_000_000,
        1_500_000_000,
        3_000_000_000,
    ]

    static func shouldTreatStatusAsSlow(durationMilliseconds: Double?) -> Bool {
        guard let durationMilliseconds else { return false }
        return durationMilliseconds >= slowStatusThresholdMilliseconds
    }

    static func steadyDelaySeconds(
        availabilityState: RemoteHostAvailabilityState,
        consecutiveMirrorFailures: Int,
        userBaseIntervalSeconds: Int,
        appIsActive: Bool,
        unchangedRevisionPollCount: Int,
        slowStatusPollCount: Int
    ) -> UInt64 {
        let base = UInt64(min(60, max(1, userBaseIntervalSeconds)))

        switch availabilityState {
        case .offlineExpected, .agentUnavailable, .authRejected:
            return 60
        default:
            break
        }

        if consecutiveMirrorFailures > 0 {
            return 60
        }

        if slowStatusPollCount >= 2 {
            return min(60, max(15, base * 3))
        }

        if !appIsActive {
            return min(60, max(30, base * 6))
        }

        if unchangedRevisionPollCount >= 12 {
            return min(60, max(30, base * 6))
        }
        if unchangedRevisionPollCount >= 6 {
            return min(30, max(15, base * 3))
        }

        return base
    }

    static func launchChaseDelaysNanoseconds(refreshAfterMilliseconds: Int?) -> [UInt64] {
        var delays = launchChaseFallbackDelaysNanoseconds
        guard let refreshAfterMilliseconds, refreshAfterMilliseconds > 0 else { return delays }
        let clampedMilliseconds = min(5_000, max(250, refreshAfterMilliseconds))
        delays[1] = UInt64(clampedMilliseconds) * 1_000_000
        return delays
    }
}
