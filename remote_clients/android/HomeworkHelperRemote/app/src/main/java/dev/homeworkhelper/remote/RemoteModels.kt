package dev.homeworkhelper.remote

data class RemoteStatus(
    val apiVersion: String,
    val processCount: Int,
    val shortcutCount: Int,
    val activeSessionCount: Int,
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
