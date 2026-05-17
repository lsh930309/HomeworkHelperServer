package dev.homeworkhelper.remote

data class RemoteStatus(
    val apiVersion: String,
    val processCount: Int,
    val shortcutCount: Int,
    val activeSessionCount: Int,
    val dashboardSummary: Boolean,
    val beholderIncidents: Boolean,
    val gameLinks: Boolean,
    val mobileSessions: Boolean,
    val powerConfig: Boolean,
    val powerControl: Boolean,
    val authRequired: Boolean,
    val pairing: Boolean,
    val tailscaleDiscovery: Boolean = false,
    val readiness: Boolean = false,
    val localStoreHealth: Boolean = false,
    val power: RemotePowerStatus?,
) {
    fun isPowerActionEnabled(action: String): Boolean {
        val currentPower = power ?: return false
        if (!powerControl || !currentPower.configured) return false
        return currentPower.supportedActions.isEmpty() || currentPower.supportedActions.contains(action)
    }
}

data class RemotePowerStatus(
    val configured: Boolean,
    val status: String,
    val supportedActions: Set<String>,
    val targetHost: String,
)

data class RemoteReadiness(
    val beholderHealth: ReadinessSection = ReadinessSection(),
    val remoteConnectivity: ReadinessSection = ReadinessSection(),
    val serverModeReadiness: ReadinessSection = ReadinessSection(),
    val powerReadiness: ReadinessSection = ReadinessSection(),
    val tailscaleReadiness: ReadinessSection = ReadinessSection(),
)

data class ReadinessSection(
    val state: String = "unknown",
    val color: String = "gray",
    val message: String = "상태 미확인",
    val activeIncidents: Int = 0,
    val authRequired: Boolean = false,
    val supportedActions: List<String> = emptyList(),
    val suggestedBaseUrls: List<String> = emptyList(),
    val tailscaleDetails: TailscaleDetails? = null,
)

data class TailscaleDetails(
    val installed: Boolean = false,
    val running: Boolean = false,
    val backendState: String = "unknown",
    val selfIps: List<String> = emptyList(),
    val selfHostname: String = "",
    val message: String = "",
)

data class RemotePowerConfigPayload(
    val smartthingsDeviceId: String = "",
    val smartthingsCliPath: String = "",
    val sshHost: String = "",
    val sshPort: Int = 22,
    val sshUser: String = "",
    val sshKeyPath: String = "",
    val statusTimeoutSeconds: Double = 4.0,
)

data class RemotePowerConfigResponse(
    val configPath: String,
    val configExists: Boolean,
    val config: RemotePowerConfigPayload,
    val wakeConfigured: Boolean,
    val sshConfigured: Boolean,
    val supportedActions: Set<String>,
)

data class RemotePowerSetupResponse(
    val hostPlatform: String = "",
    val user: String = "",
    val authorizedKeysPath: String = "",
    val authorizedKeysExists: Boolean = false,
    val sshServiceRunning: Boolean = false,
    val firewallEnabled: Boolean = false,
    val smartthingsCliCandidates: List<String> = emptyList(),
    val smartthingsReady: Boolean = false,
    val message: String = "",
)

data class RemoteSmartThingsDeviceCandidate(
    val id: String,
    val name: String,
    val raw: String,
)

data class RemoteSmartThingsDevicesResponse(
    val available: Boolean = false,
    val devices: List<String> = emptyList(),
    val deviceCandidates: List<RemoteSmartThingsDeviceCandidate> = emptyList(),
    val message: String = "",
    val cliPath: String = "",
)

data class RemoteTailscaleEnsureResponse(
    val ready: Boolean = false,
    val method: String = "",
    val message: String = "",
    val installAttempted: Boolean = false,
    val launchAttempted: Boolean = false,
)

data class RemoteLoggingConfigResponse(
    val enabled: Boolean = false,
    val path: String = "",
)

data class RemoteCapabilities(
    val apiVersion: String,
    val processLaunch: Boolean,
    val shortcutOpen: Boolean,
    val dashboardSummary: Boolean,
    val beholderIncidents: Boolean,
    val gameLinks: Boolean,
    val mobileSessions: Boolean,
    val powerConfig: Boolean,
    val powerControl: Boolean,
    val authRequired: Boolean,
    val pairing: Boolean,
    val tailscaleDiscovery: Boolean = false,
    val readiness: Boolean = false,
    val localStoreHealth: Boolean = false,
)

data class RemoteProcess(
    val id: String,
    val name: String,
    val preferredLaunchType: String,
    val monitoringPath: String,
    val launchPath: String,
    val iconUrl: String = "",
    val isRunning: Boolean = false,
    val playedToday: Boolean = false,
    val statusText: String = "",
    val progress: RemoteProcessProgress? = null,
)

data class RemoteProcessProgress(
    val kind: String,
    val percentage: Double,
    val displayText: String,
    val staminaCurrent: Int = 0,
    val staminaMax: Int = 0,
    val resourceIconUrl: String = "",
    val remainingSeconds: Int = 0,
)

data class RemoteShortcut(
    val id: String,
    val name: String,
    val url: String,
)

data class RemoteGameLink(
    val id: String,
    val pcProcessId: String,
    val pcDisplayName: String,
    val androidPackageName: String,
    val androidLaunchIntentUri: String,
    val androidStoreUrl: String,
    val platformAccountHint: String,
    val hoyolabGameId: String,
    val syncStrategy: String,
)

data class RemoteMobileSession(
    val id: String,
    val gameLinkId: String,
    val pcProcessId: String,
    val pcDisplayName: String,
    val androidPackageName: String,
    val source: String,
    val status: String,
    val startedAt: Double,
    val endedAt: Double,
    val durationSeconds: Double,
)

data class RemoteDashboardSummary(
    val rangeStart: String,
    val rangeEnd: String,
    val totalSeconds: Double,
    val dailyAverageSeconds: Double,
    val playedDays: Int,
    val sessionCount: Int,
    val topGameName: String,
    val topGameSeconds: Double,
    val mobileTotalSeconds: Double,
    val mobileActiveSeconds: Double,
    val mobileSessionCount: Int,
    val mobileActiveSessionCount: Int,
    val mobileTopGameName: String,
    val mobileTopAndroidPackageName: String,
    val mobileTopGameSeconds: Double,
)

data class RemoteBeholderIncident(
    val id: Int,
    val severity: String,
    val status: String,
    val userTitle: String,
    val userSummary: String,
    val riskScore: Int,
    val riskLabels: List<String>,
)

data class RemoteCommandResult(
    val accepted: Boolean,
    val command: String,
    val status: String,
    val message: String,
)

data class PairingResult(
    val id: String,
    val deviceName: String,
    val platform: String,
    val token: String,
)

data class RemoteDevice(
    val id: String,
    val deviceName: String,
    val platform: String,
    val tokenRefreshedAt: String,
    val revokedAt: String,
)

data class PurgeDevicesResponse(
    val removed: Int,
)
