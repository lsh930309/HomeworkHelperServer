import Foundation

struct RemoteStatus: Decodable {
    struct Counts: Decodable {
        let processes: Int
        let shortcuts: Int
        let activeSessions: Int

        enum CodingKeys: String, CodingKey {
            case processes
            case shortcuts
            case activeSessions = "active_sessions"
        }
    }

    struct Capabilities: Decodable {
        let processLaunch: Bool
        let shortcutOpen: Bool
        let dashboardSummary: Bool
        let beholderIncidents: Bool
        let gameLinks: Bool
        let mobileSessions: Bool
        let powerConfig: Bool
        let powerControl: Bool
        let beholder: Bool
        let authRequired: Bool
        let pairing: Bool

        enum CodingKeys: String, CodingKey {
            case processLaunch = "process_launch"
            case shortcutOpen = "shortcut_open"
            case dashboardSummary = "dashboard_summary"
            case beholderIncidents = "beholder_incidents"
            case gameLinks = "game_links"
            case mobileSessions = "mobile_sessions"
            case powerConfig = "power_config"
            case powerControl = "power_control"
            case authRequired = "auth_required"
            case beholder
            case pairing
        }
    }

    struct Power: Decodable {
        let configured: Bool
        let status: String?
        let supportedActions: [String]
        let targetHost: String?

        enum CodingKeys: String, CodingKey {
            case configured
            case status
            case supportedActions = "supported_actions"
            case targetHost = "target_host"
        }
    }

    let app: String
    let remoteAPIVersion: String
    let serverTime: Double
    let counts: Counts
    let capabilities: Capabilities
    let power: Power?
    let readiness: RemoteReadiness?

    var supportedPowerActions: Set<String> {
        Set(power?.supportedActions ?? [])
    }

    enum CodingKeys: String, CodingKey {
        case app
        case remoteAPIVersion = "remote_api_version"
        case serverTime = "server_time"
        case counts
        case capabilities
        case power
        case readiness
    }
}

struct RemoteReadiness: Decodable {
    struct Section: Decodable {
        let state: String
        let color: String
        let message: String
        let activeIncidents: Int?
        let authRequired: Bool?
        let supportedActions: [String]?
        let suggestedBaseURLs: [String]?
        let details: TailscaleDetails?

        enum CodingKeys: String, CodingKey {
            case state
            case color
            case message
            case activeIncidents = "active_incidents"
            case authRequired = "auth_required"
            case supportedActions = "supported_actions"
            case suggestedBaseURLs = "suggested_base_urls"
            case details
        }
    }

    struct TailscaleDetails: Decodable {
        let installed: Bool
        let running: Bool
        let backendState: String
        let selfIPs: [String]
        let selfHostname: String
        let message: String

        enum CodingKeys: String, CodingKey {
            case installed
            case running
            case backendState = "backend_state"
            case selfIPs = "self_ips"
            case selfHostname = "self_hostname"
            case message
        }
    }

    let beholderHealth: Section
    let remoteConnectivity: Section
    let serverModeReadiness: Section
    let powerReadiness: Section
    let tailscaleReadiness: Section

    enum CodingKeys: String, CodingKey {
        case beholderHealth = "beholder_health"
        case remoteConnectivity = "remote_connectivity"
        case serverModeReadiness = "server_mode_readiness"
        case powerReadiness = "power_readiness"
        case tailscaleReadiness = "tailscale_readiness"
    }
}

struct RemotePowerConfigPayload: Codable {
    var smartthingsDeviceID: String = ""
    var smartthingsCLIPath: String = ""
    var sshHost: String = ""
    var sshPort: Int = 22
    var sshUser: String = ""
    var sshKeyPath: String = ""
    var statusTimeoutSeconds: Double = 4.0

    enum CodingKeys: String, CodingKey {
        case smartthingsDeviceID = "smartthings_device_id"
        case smartthingsCLIPath = "smartthings_cli_path"
        case sshHost = "ssh_host"
        case sshPort = "ssh_port"
        case sshUser = "ssh_user"
        case sshKeyPath = "ssh_key_path"
        case statusTimeoutSeconds = "status_timeout_seconds"
    }
}


struct RemotePowerSetupResponse: Decodable {
    struct SSHService: Decodable {
        let available: Bool
        let running: Bool
        let startType: String
        let message: String

        enum CodingKeys: String, CodingKey {
            case available
            case running
            case startType = "start_type"
            case message
        }
    }

    struct Firewall: Decodable {
        let available: Bool
        let enabled: Bool
        let message: String
    }

    let hostPlatform: String
    let user: String
    let authorizedKeysPath: String
    let authorizedKeysExists: Bool
    let sshService: SSHService
    let firewall: Firewall
    let smartthingsCLICandidates: [String]
    let smartthingsReady: Bool
    let message: String

    enum CodingKeys: String, CodingKey {
        case hostPlatform = "host_platform"
        case user
        case authorizedKeysPath = "authorized_keys_path"
        case authorizedKeysExists = "authorized_keys_exists"
        case sshService = "ssh_service"
        case firewall
        case smartthingsCLICandidates = "smartthings_cli_candidates"
        case smartthingsReady = "smartthings_ready"
        case message
    }
}

struct RemoteSSHKeyRegistrationResponse: Decodable {
    let registered: Bool
    let alreadyPresent: Bool
    let authorizedKeysPath: String
    let message: String

    enum CodingKeys: String, CodingKey {
        case registered
        case alreadyPresent = "already_present"
        case authorizedKeysPath = "authorized_keys_path"
        case message
    }
}

struct RemoteSmartThingsDeviceCandidate: Decodable, Identifiable {
    let id: String
    let name: String
    let raw: String
}

struct RemoteSmartThingsDevicesResponse: Decodable {
    let available: Bool
    let devices: [String]
    let deviceCandidates: [RemoteSmartThingsDeviceCandidate]
    let message: String
    let cliPath: String?

    enum CodingKeys: String, CodingKey {
        case available
        case devices
        case deviceCandidates = "device_candidates"
        case message
        case cliPath = "cli_path"
    }
}

extension RemotePowerConfigPayload {
    var hasAnyPowerSetting: Bool {
        !smartthingsDeviceID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        || !smartthingsCLIPath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        || !sshHost.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        || !sshUser.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        || !sshKeyPath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    func hostSafeForRemoteSave() -> RemotePowerConfigPayload {
        var copy = self
        if LocalPowerWakeManager.isLocalSmartThingsCLIPath(copy.smartthingsCLIPath) {
            copy.smartthingsCLIPath = ""
        }
        if copy.sshKeyPath.trimmingCharacters(in: .whitespacesAndNewlines).hasPrefix("/") ||
            copy.sshKeyPath.trimmingCharacters(in: .whitespacesAndNewlines).hasPrefix("~") {
            copy.sshKeyPath = ""
        }
        return copy
    }

    func preservingLocalWake(from local: RemotePowerConfigPayload) -> RemotePowerConfigPayload {
        var copy = self
        if copy.smartthingsCLIPath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
           LocalPowerWakeManager.isLocalSmartThingsCLIPath(local.smartthingsCLIPath) {
            copy.smartthingsCLIPath = local.smartthingsCLIPath
        }
        if copy.smartthingsDeviceID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            copy.smartthingsDeviceID = local.smartthingsDeviceID
        }
        if copy.sshHost.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            copy.sshHost = local.sshHost
        }
        if copy.sshUser.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            copy.sshUser = local.sshUser
        }
        if copy.sshKeyPath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            copy.sshKeyPath = local.sshKeyPath
        }
        return copy
    }

    var localWakeConfigured: Bool {
        !smartthingsDeviceID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        && !smartthingsCLIPath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var localSSHConfigured: Bool {
        !sshHost.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        && !sshUser.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        && !sshKeyPath.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        && sshPort > 0
    }
}

struct RemotePowerConfigResponse: Decodable {
    struct Readiness: Decodable {
        let wakeConfigured: Bool
        let sshConfigured: Bool
        let supportedActions: [String]

        enum CodingKeys: String, CodingKey {
            case wakeConfigured = "wake_configured"
            case sshConfigured = "ssh_configured"
            case supportedActions = "supported_actions"
        }
    }

    let configPath: String
    let configExists: Bool
    let config: RemotePowerConfigPayload
    let readiness: Readiness

    enum CodingKeys: String, CodingKey {
        case configPath = "config_path"
        case configExists = "config_exists"
        case config
        case readiness
    }
}

struct RemoteProcess: Decodable, Identifiable {
    let processID: String?
    let name: String
    let monitoringPath: String?
    let launchPath: String?
    let preferredLaunchType: String?
    let lastPlayedTimestamp: Double?
    let staminaCurrent: Int?
    let staminaMax: Int?

    var id: String { processID ?? name }

    enum CodingKeys: String, CodingKey {
        case processID = "id"
        case name
        case monitoringPath = "monitoring_path"
        case launchPath = "launch_path"
        case preferredLaunchType = "preferred_launch_type"
        case lastPlayedTimestamp = "last_played_timestamp"
        case staminaCurrent = "stamina_current"
        case staminaMax = "stamina_max"
    }
}

struct RemoteShortcut: Decodable, Identifiable {
    let id: String
    let name: String
    let url: String
    let refreshTime: String?
    let lastResetTimestamp: Double?

    enum CodingKeys: String, CodingKey {
        case id
        case name
        case url
        case refreshTime = "refresh_time_str"
        case lastResetTimestamp = "last_reset_timestamp"
    }
}

struct RemoteCommandResult: Decodable {
    let accepted: Bool
    let command: String
    let targetID: String?
    let targetName: String?
    let target: String?
    let status: String
    let message: String

    enum CodingKeys: String, CodingKey {
        case accepted
        case command
        case targetID = "target_id"
        case targetName = "target_name"
        case target
        case status
        case message
    }
}

struct RemoteOnboardingBundle: Decodable {
    let readiness: RemoteReadiness?
    let powerConfig: RemotePowerConfigResponse?
    let powerSetup: RemotePowerSetupResponse?
    let message: String?

    enum CodingKeys: String, CodingKey {
        case readiness
        case powerConfig = "power_config"
        case powerSetup = "power_setup"
        case message
    }
}

struct PairingConfirmResponse: Decodable {
    let id: String
    let name: String
    let platform: String?
    let token: String
    let onboarding: RemoteOnboardingBundle?
}

struct RemoteDevice: Decodable, Identifiable {
    let id: String
    let name: String
    let platform: String?
    let createdAt: Double?
    let lastSeenAt: Double?
    let tokenRefreshedAt: Double?
    let revokedAt: Double?

    enum CodingKeys: String, CodingKey {
        case id
        case name
        case platform
        case createdAt = "created_at"
        case lastSeenAt = "last_seen_at"
        case tokenRefreshedAt = "token_refreshed_at"
        case revokedAt = "revoked_at"
    }
}

struct RemoteDevicesResponse: Decodable {
    let devices: [RemoteDevice]
}

struct RemoteTailscalePeer: Decodable, Identifiable {
    let hostname: String
    let dnsName: String
    let ips: [String]
    let online: Bool
    let os: String
    let primaryIPv4: String?

    var id: String { "\(hostname)-\(primaryIPv4 ?? dnsName)" }

    enum CodingKeys: String, CodingKey {
        case hostname
        case dnsName = "dns_name"
        case ips
        case online
        case os
        case primaryIPv4 = "primary_ipv4"
    }
}

struct RemoteTailscaleSnapshot: Decodable {
    let installed: Bool
    let running: Bool
    let backendState: String
    let selfIPs: [String]
    let selfHostname: String
    let peers: [RemoteTailscalePeer]
    let message: String

    enum CodingKeys: String, CodingKey {
        case installed
        case running
        case backendState = "backend_state"
        case selfIPs = "self_ips"
        case selfHostname = "self_hostname"
        case peers
        case message
    }
}

struct RemoteTailscaleEnsureResponse: Decodable {
    let ready: Bool
    let installAttempted: Bool
    let launchAttempted: Bool
    let method: String
    let message: String
    let before: RemoteTailscaleSnapshot
    let after: RemoteTailscaleSnapshot

    enum CodingKeys: String, CodingKey {
        case ready
        case installAttempted = "install_attempted"
        case launchAttempted = "launch_attempted"
        case method
        case message
        case before
        case after
    }
}

struct RemoteCapabilitiesResponse: Decodable {
    let remoteAPIVersion: String
    let capabilities: RemoteStatus.Capabilities
    let power: RemoteStatus.Power?

    enum CodingKeys: String, CodingKey {
        case remoteAPIVersion = "remote_api_version"
        case capabilities
        case power
    }
}

struct RemoteGameLink: Decodable, Identifiable {
    let id: String
    let pcProcessID: String
    let pcDisplayName: String?
    let androidPackageName: String
    let androidLaunchIntentURI: String?
    let androidStoreURL: String?
    let platformAccountHint: String?
    let hoyolabGameID: String?
    let syncStrategy: String
    let createdAt: Double
    let updatedAt: Double

    enum CodingKeys: String, CodingKey {
        case id
        case pcProcessID = "pc_process_id"
        case pcDisplayName = "pc_display_name"
        case androidPackageName = "android_package_name"
        case androidLaunchIntentURI = "android_launch_intent_uri"
        case androidStoreURL = "android_store_url"
        case platformAccountHint = "platform_account_hint"
        case hoyolabGameID = "hoyolab_game_id"
        case syncStrategy = "sync_strategy"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }
}

struct RemoteGameLinksResponse: Decodable {
    let links: [RemoteGameLink]
    let count: Int
}

struct RemoteMobileSession: Decodable, Identifiable {
    let id: String
    let gameLinkID: String
    let pcProcessID: String
    let pcDisplayName: String?
    let androidPackageName: String
    let source: String
    let status: String
    let startedAt: Double
    let endedAt: Double?
    let durationSeconds: Double?

    enum CodingKeys: String, CodingKey {
        case id
        case gameLinkID = "game_link_id"
        case pcProcessID = "pc_process_id"
        case pcDisplayName = "pc_display_name"
        case androidPackageName = "android_package_name"
        case source
        case status
        case startedAt = "started_at"
        case endedAt = "ended_at"
        case durationSeconds = "duration_seconds"
    }
}

struct RemoteMobileSessionsResponse: Decodable {
    let sessions: [RemoteMobileSession]
    let count: Int
}

struct RemoteDashboardSummary: Decodable {
    struct Range: Decodable {
        let start: String
        let end: String
    }

    struct Game: Decodable {
        let displayName: String
        let totalSeconds: Double
        let sessionCount: Int

        enum CodingKeys: String, CodingKey {
            case displayName = "display_name"
            case totalSeconds = "total_seconds"
            case sessionCount = "session_count"
        }
    }

    struct Metrics: Decodable {
        let totalSeconds: Double
        let dailyAverageSeconds: Double
        let playedDays: Int
        let sessionCount: Int
        let topGame: Game?

        enum CodingKeys: String, CodingKey {
            case totalSeconds = "total_seconds"
            case dailyAverageSeconds = "daily_average_seconds"
            case playedDays = "played_days"
            case sessionCount = "session_count"
            case topGame = "top_game"
        }
    }

    struct MobileMetrics: Decodable {
        struct Game: Decodable {
            let displayName: String
            let androidPackageName: String
            let totalSeconds: Double
            let sessionCount: Int
            let activeSessionCount: Int

            enum CodingKeys: String, CodingKey {
                case displayName = "display_name"
                case androidPackageName = "android_package_name"
                case totalSeconds = "total_seconds"
                case sessionCount = "session_count"
                case activeSessionCount = "active_session_count"
            }
        }

        let totalSeconds: Double
        let activeSeconds: Double
        let sessionCount: Int
        let activeSessionCount: Int
        let sourceBreakdown: [String: Int]
        let topGame: Game?

        enum CodingKeys: String, CodingKey {
            case totalSeconds = "total_seconds"
            case activeSeconds = "active_seconds"
            case sessionCount = "session_count"
            case activeSessionCount = "active_session_count"
            case sourceBreakdown = "source_breakdown"
            case topGame = "top_game"
        }
    }

    let range: Range
    let metrics: Metrics
    let mobileMetrics: MobileMetrics?

    enum CodingKeys: String, CodingKey {
        case range
        case metrics
        case mobileMetrics = "mobile_metrics"
    }
}

struct RemoteBeholderIncident: Decodable, Identifiable {
    let id: Int
    let severity: String
    let status: String
    let userTitle: String
    let userSummary: String?
    let riskScore: Int
    let riskLabels: [String]
    let createdAt: Double?

    enum CodingKeys: String, CodingKey {
        case id
        case severity
        case status
        case userTitle = "user_title"
        case userSummary = "user_summary"
        case riskScore = "risk_score"
        case riskLabels = "risk_labels"
        case createdAt = "created_at"
    }
}

struct RemoteBeholderIncidentsResponse: Decodable {
    let incidents: [RemoteBeholderIncident]
    let count: Int
}

struct RevokeDeviceResponse: Decodable {
    let revoked: Bool
    let deviceID: String

    enum CodingKeys: String, CodingKey {
        case revoked
        case deviceID = "device_id"
    }
}


struct RemoteLoggingConfigResponse: Decodable {
    let enabled: Bool
    let path: String
}

struct PurgeDevicesResponse: Decodable {
    let removed: Int
}
