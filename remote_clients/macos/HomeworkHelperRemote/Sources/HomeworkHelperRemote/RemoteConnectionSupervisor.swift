import Foundation
import SwiftUI

enum RemoteHostAvailabilityState: String, Equatable {
    case unknown
    case online
    case goingOffline
    case offlineExpected
    case waking
    case restarting
    case reconnecting
    case agentUnavailable
    case authRejected

    var connectionState: String {
        switch self {
        case .online:
            return "online"
        case .offlineExpected:
            return "offline"
        default:
            return rawValue
        }
    }

    var label: String {
        switch self {
        case .unknown: return "상태 확인 중"
        case .online: return "페어링됨"
        case .goingOffline: return "종료 대기 중"
        case .offlineExpected: return "호스트 꺼짐"
        case .waking: return "부팅 대기 중"
        case .restarting: return "재시동 대기 중"
        case .reconnecting: return "재연결 중"
        case .agentUnavailable: return "서버 응답 없음"
        case .authRejected: return "인증 확인 필요"
        }
    }

    var color: Color {
        switch self {
        case .online:
            return .green
        case .goingOffline, .restarting, .agentUnavailable:
            return .orange
        case .offlineExpected:
            return .secondary
        case .waking, .reconnecting:
            return .blue
        case .authRejected:
            return .red
        case .unknown:
            return .secondary
        }
    }
}

enum RemoteConnectionFailureKind: Equatable {
    case authRejected
    case timedOut
    case cannotConnect
    case dnsFailed
    case networkLost
    case otherConnectivity
    case nonConnectivity

    var isConnectivity: Bool {
        switch self {
        case .timedOut, .cannotConnect, .dnsFailed, .networkLost, .otherConnectivity:
            return true
        case .authRejected, .nonConnectivity:
            return false
        }
    }
}

enum RemoteTailscaleReachabilitySignal: Equatable {
    case reachable(String)
    case unreachable(String)
    case unavailable(String)
    case skipped(String)
}

enum RemoteConnectionEvent: Equatable {
    case powerIntentAccepted(action: String)
    case tailscaleReachability(result: RemoteTailscaleReachabilitySignal)
    case httpStatusSucceeded(powerHint: String?, stateRevision: String?)
    case httpStatusFailed(kind: RemoteConnectionFailureKind)
    case httpAgentUnavailable(kind: RemoteConnectionFailureKind, detail: String)
    case scheduleExhausted
    case clientResumed
}

struct RemoteConnectionDecision: Equatable {
    var availabilityState: RemoteHostAvailabilityState?
    var reconnectSchedule: [UInt64]?
    var message: String?
    var shouldLoadCache: Bool
    var shouldRefreshLocalProgress: Bool
    var shouldForcePayloadSync: Bool
    var shouldClearPairingRecovery: Bool
    var shouldProbeImmediately: Bool

    static let none = RemoteConnectionDecision(
        availabilityState: nil,
        reconnectSchedule: nil,
        message: nil,
        shouldLoadCache: false,
        shouldRefreshLocalProgress: false,
        shouldForcePayloadSync: false,
        shouldClearPairingRecovery: false,
        shouldProbeImmediately: false
    )
}

enum RemoteConnectionSupervisor {
    static let expectedOfflineProbeSchedule = Array(repeating: UInt64(2), count: 5)
    static let connectionLossReconnectSchedule = Array(repeating: UInt64(1), count: 5)
        + Array(repeating: UInt64(2), count: 5)
        + Array(repeating: UInt64(5), count: 4)
    static let wakeReconnectSchedule = Array(repeating: UInt64(1), count: 15)
        + Array(repeating: UInt64(2), count: 15)
        + Array(repeating: UInt64(5), count: 24)
    static let restartReconnectSchedule = [UInt64(5)] + wakeReconnectSchedule

    static func decide(
        event: RemoteConnectionEvent,
        currentState: RemoteHostAvailabilityState,
        reconnectScheduleIsEmpty: Bool
    ) -> RemoteConnectionDecision {
        switch event {
        case .powerIntentAccepted(let action):
            return powerIntentDecision(action: action)
        case .tailscaleReachability(let result):
            return tailscaleDecision(result: result, currentState: currentState, reconnectScheduleIsEmpty: reconnectScheduleIsEmpty)
        case .httpStatusSucceeded(let powerHint, _):
            return statusSuccessDecision(powerHint: powerHint, currentState: currentState)
        case .httpStatusFailed(let kind):
            return httpFailureDecision(kind: kind, currentState: currentState, reconnectScheduleIsEmpty: reconnectScheduleIsEmpty)
        case .httpAgentUnavailable(let kind, let detail):
            return httpAgentUnavailableDecision(kind: kind, detail: detail, currentState: currentState, reconnectScheduleIsEmpty: reconnectScheduleIsEmpty)
        case .scheduleExhausted:
            return scheduleExhaustedDecision(currentState: currentState)
        case .clientResumed:
            return RemoteConnectionDecision(
                availabilityState: nil,
                reconnectSchedule: nil,
                message: nil,
                shouldLoadCache: false,
                shouldRefreshLocalProgress: true,
                shouldForcePayloadSync: false,
                shouldClearPairingRecovery: false,
                shouldProbeImmediately: true
            )
        }
    }

    private static func powerIntentDecision(action: String) -> RemoteConnectionDecision {
        switch action {
        case "wake":
            return stateDecision(.waking, schedule: wakeReconnectSchedule, message: nil, clearPairing: true)
        case "restart":
            return stateDecision(.restarting, schedule: restartReconnectSchedule, message: nil, clearPairing: true)
        case "sleep", "shutdown":
            return stateDecision(.goingOffline, schedule: expectedOfflineProbeSchedule, message: nil, clearPairing: true)
        default:
            return RemoteConnectionDecision(
                availabilityState: nil,
                reconnectSchedule: [],
                message: nil,
                shouldLoadCache: false,
                shouldRefreshLocalProgress: false,
                shouldForcePayloadSync: false,
                shouldClearPairingRecovery: false,
                shouldProbeImmediately: false
            )
        }
    }

    private static func tailscaleDecision(
        result: RemoteTailscaleReachabilitySignal,
        currentState: RemoteHostAvailabilityState,
        reconnectScheduleIsEmpty: Bool
    ) -> RemoteConnectionDecision {
        switch result {
        case .reachable, .unavailable, .skipped:
            return .none
        case .unreachable(let detail):
            if currentState == .waking || currentState == .restarting {
                if reconnectScheduleIsEmpty {
                    return disconnectedDecision(
                        state: .offlineExpected,
                        schedule: [],
                        message: "호스트가 아직 응답하지 않습니다. 저장된 토큰과 캐시 데이터는 보존합니다."
                    )
                }
                return disconnectedDecision(
                    state: currentState,
                    schedule: nil,
                    message: "호스트 응답을 기다리는 중입니다. 저장된 토큰은 보존합니다."
                )
            }
            let suffix = detail.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "" : " (\(detail))"
            return disconnectedDecision(
                state: .offlineExpected,
                schedule: [],
                message: "호스트 Tailscale ping 응답이 없습니다. 호스트가 최대 절전/종료 상태이거나 Tailscale이 비활성화된 것으로 판단했습니다." + suffix
            )
        }
    }

    private static func statusSuccessDecision(powerHint: String?, currentState: RemoteHostAvailabilityState) -> RemoteConnectionDecision {
        let normalized = powerHint?.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() ?? ""
        let isOfflineHint = ["off", "offline", "asleep", "sleeping"].contains(normalized)
        if currentState == .goingOffline && !isOfflineHint {
            return RemoteConnectionDecision(
                availabilityState: .goingOffline,
                reconnectSchedule: nil,
                message: nil,
                shouldLoadCache: false,
                shouldRefreshLocalProgress: false,
                shouldForcePayloadSync: false,
                shouldClearPairingRecovery: false,
                shouldProbeImmediately: false
            )
        }
        let state: RemoteHostAvailabilityState = isOfflineHint ? .offlineExpected : .online
        return RemoteConnectionDecision(
            availabilityState: state,
            reconnectSchedule: [],
            message: nil,
            shouldLoadCache: false,
            shouldRefreshLocalProgress: false,
            shouldForcePayloadSync: currentState != .online,
            shouldClearPairingRecovery: true,
            shouldProbeImmediately: false
        )
    }

    private static func httpFailureDecision(
        kind: RemoteConnectionFailureKind,
        currentState: RemoteHostAvailabilityState,
        reconnectScheduleIsEmpty: Bool
    ) -> RemoteConnectionDecision {
        if kind == .authRejected {
            return disconnectedDecision(
                state: .authRejected,
                schedule: [],
                message: "저장된 토큰이 호스트에서 거부되었습니다. 로컬 토큰은 보존됩니다. 호스트 원격 설정에서 해당 디바이스가 폐기됐는지 확인하세요."
            )
        }
        guard kind.isConnectivity else { return .none }

        switch currentState {
        case .goingOffline:
            return disconnectedDecision(
                state: .offlineExpected,
                schedule: [],
                message: "호스트가 절전/종료 상태로 전환된 것으로 판단했습니다. 저장된 토큰과 캐시 데이터는 보존합니다."
            )
        case .waking, .restarting:
            if reconnectScheduleIsEmpty {
                return disconnectedDecision(
                    state: .offlineExpected,
                    schedule: [],
                    message: "호스트가 아직 응답하지 않습니다. 저장된 토큰과 캐시 데이터는 보존합니다."
                )
            }
            return disconnectedDecision(
                state: currentState,
                schedule: nil,
                message: "호스트 응답을 기다리는 중입니다. 저장된 토큰은 보존합니다."
            )
        case .offlineExpected:
            return disconnectedDecision(
                state: .offlineExpected,
                schedule: [],
                message: "호스트가 계속 응답하지 않습니다. 저장된 토큰과 캐시 데이터는 보존하고 standalone 표시를 유지합니다."
            )
        case .reconnecting:
            if reconnectScheduleIsEmpty {
                return disconnectedDecision(
                    state: .agentUnavailable,
                    schedule: [],
                    message: "짧은 재연결 확인 후에도 Remote Agent가 응답하지 않아 서버 응답 없음 상태로 전환했습니다. 저장된 토큰과 캐시 데이터는 보존합니다."
                )
            }
            return disconnectedDecision(
                state: .reconnecting,
                schedule: nil,
                message: "호스트 연결이 끊겼습니다. 저장된 토큰으로 자동 재연결을 시도합니다."
            )
        case .agentUnavailable:
            return disconnectedDecision(
                state: .agentUnavailable,
                schedule: [],
                message: "Remote Agent가 계속 응답하지 않습니다. 호스트 앱 서버 모드와 방화벽/포트 설정을 확인하세요."
            )
        default:
            return disconnectedDecision(
                state: .reconnecting,
                schedule: reconnectScheduleIsEmpty ? connectionLossReconnectSchedule : nil,
                message: "호스트 연결이 끊겼습니다. 저장된 토큰으로 자동 재연결을 시도합니다."
            )
        }
    }

    private static func httpAgentUnavailableDecision(
        kind: RemoteConnectionFailureKind,
        detail: String,
        currentState: RemoteHostAvailabilityState,
        reconnectScheduleIsEmpty: Bool
    ) -> RemoteConnectionDecision {
        if kind == .authRejected {
            return httpFailureDecision(kind: kind, currentState: currentState, reconnectScheduleIsEmpty: reconnectScheduleIsEmpty)
        }
        guard kind.isConnectivity else { return .none }

        switch currentState {
        case .goingOffline:
            return disconnectedDecision(
                state: .offlineExpected,
                schedule: [],
                message: "호스트가 절전/종료 상태로 전환된 것으로 판단했습니다. 저장된 토큰과 캐시 데이터는 보존합니다."
            )
        case .waking, .restarting:
            if reconnectScheduleIsEmpty {
                return disconnectedDecision(
                    state: .agentUnavailable,
                    schedule: [],
                    message: "Remote Agent HTTP 첫 응답이 아직 없습니다. Tailscale이 도달하는데도 계속 지연되면 호스트 앱/API 서버가 굼뜨거나 DB 작업에 막혔는지 확인하세요."
                )
            }
            return disconnectedDecision(
                state: currentState,
                schedule: nil,
                message: "Remote Agent HTTP 응답을 기다리는 중입니다."
            )
        default:
            let suffix = detail.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? "" : " (\(detail))"
            let baseMessage: String
            if kind == .timedOut {
                baseMessage = "Remote Agent HTTP 첫 응답이 지연되고 있습니다. Tailscale은 도달했지만 호스트 앱/API 서버가 굼뜨거나 DB 작업에 막혔을 수 있습니다. 호스트에서 /api/gui/ping, /api/gui/health, /remote/status 응답 시간을 확인하세요."
            } else {
                baseMessage = "Remote Agent HTTP 상태 응답이 없습니다. Windows 앱 서버 모드와 방화벽/포트 8000을 확인하세요."
            }
            return disconnectedDecision(
                state: .agentUnavailable,
                schedule: [],
                message: baseMessage + suffix
            )
        }
    }

    private static func scheduleExhaustedDecision(currentState: RemoteHostAvailabilityState) -> RemoteConnectionDecision {
        switch currentState {
        case .goingOffline, .waking, .restarting:
            return disconnectedDecision(
                state: .offlineExpected,
                schedule: [],
                message: "호스트가 아직 응답하지 않습니다. 저장된 토큰과 캐시 데이터는 보존합니다."
            )
        case .reconnecting:
            return disconnectedDecision(
                state: .agentUnavailable,
                schedule: [],
                message: "짧은 재연결 확인 후에도 Remote Agent가 응답하지 않아 서버 응답 없음 상태로 전환했습니다. 저장된 토큰과 캐시 데이터는 보존합니다."
            )
        case .agentUnavailable, .offlineExpected, .authRejected:
            return RemoteConnectionDecision(
                availabilityState: currentState,
                reconnectSchedule: [],
                message: nil,
                shouldLoadCache: false,
                shouldRefreshLocalProgress: true,
                shouldForcePayloadSync: false,
                shouldClearPairingRecovery: false,
                shouldProbeImmediately: false
            )
        default:
            return .none
        }
    }

    private static func stateDecision(
        _ state: RemoteHostAvailabilityState,
        schedule: [UInt64]?,
        message: String?,
        clearPairing: Bool
    ) -> RemoteConnectionDecision {
        RemoteConnectionDecision(
            availabilityState: state,
            reconnectSchedule: schedule,
            message: message,
            shouldLoadCache: false,
            shouldRefreshLocalProgress: false,
            shouldForcePayloadSync: false,
            shouldClearPairingRecovery: clearPairing,
            shouldProbeImmediately: false
        )
    }

    private static func disconnectedDecision(
        state: RemoteHostAvailabilityState,
        schedule: [UInt64]?,
        message: String?
    ) -> RemoteConnectionDecision {
        RemoteConnectionDecision(
            availabilityState: state,
            reconnectSchedule: schedule,
            message: message,
            shouldLoadCache: true,
            shouldRefreshLocalProgress: true,
            shouldForcePayloadSync: false,
            shouldClearPairingRecovery: false,
            shouldProbeImmediately: false
        )
    }
}
