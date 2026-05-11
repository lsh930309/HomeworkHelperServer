package dev.homeworkhelper.remote

data class RemoteStatus(
    val apiVersion: String,
    val processCount: Int,
    val shortcutCount: Int,
    val activeSessionCount: Int,
    val dashboardSummary: Boolean,
    val beholderIncidents: Boolean,
    val powerControl: Boolean,
    val authRequired: Boolean,
    val pairing: Boolean,
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

data class RemoteCapabilities(
    val apiVersion: String,
    val processLaunch: Boolean,
    val shortcutOpen: Boolean,
    val dashboardSummary: Boolean,
    val beholderIncidents: Boolean,
    val powerControl: Boolean,
    val authRequired: Boolean,
    val pairing: Boolean,
)

data class RemoteProcess(
    val id: String,
    val name: String,
    val preferredLaunchType: String,
    val monitoringPath: String,
    val launchPath: String,
)

data class RemoteShortcut(
    val id: String,
    val name: String,
    val url: String,
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
    val revokedAt: String,
)
