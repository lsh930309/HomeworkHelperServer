package dev.homeworkhelper.remote

data class RemoteSnapshot(
    val status: RemoteStatus,
    val capabilities: RemoteCapabilities?,
    val readiness: RemoteReadiness?,
    val loggingConfig: RemoteLoggingConfigResponse?,
    val dashboardSummary: RemoteDashboardSummary?,
    val beholderIncidents: List<RemoteBeholderIncident>,
    val gameLinks: List<RemoteGameLink>,
    val mobileSessions: List<RemoteMobileSession>,
    val powerConfig: RemotePowerConfigResponse?,
    val powerSetup: RemotePowerSetupResponse?,
    val processes: List<RemoteProcess>,
    val shortcuts: List<RemoteShortcut>,
    val devices: List<RemoteDevice>,
    val partialErrors: List<String>,
)

class RemoteRepository {
    fun fetchSnapshot(baseUrl: String, token: String, includeDevices: Boolean): RemoteSnapshot {
        val api = client(baseUrl, token)
        val errors = mutableListOf<String>()
        val status = api.status()
        return RemoteSnapshot(
            status = status,
            capabilities = optional(errors, "capabilities") { api.capabilities() },
            readiness = optional(errors, "readiness") { api.readiness() },
            loggingConfig = optional(errors, "logging") { api.remoteLoggingConfig() },
            dashboardSummary = optional(errors, "dashboard") { api.dashboardSummary() },
            beholderIncidents = optional(errors, "beholder") { api.beholderIncidents() }.orEmpty(),
            gameLinks = optional(errors, "game-links") { api.gameLinks() }.orEmpty(),
            mobileSessions = optional(errors, "mobile-sessions") { api.activeMobileSessions() }.orEmpty(),
            powerConfig = optional(errors, "power-config") { api.powerConfig() },
            powerSetup = optional(errors, "power-setup") { api.powerSetup() },
            processes = optional(errors, "processes") { api.processes() }.orEmpty(),
            shortcuts = optional(errors, "shortcuts") { api.shortcuts() }.orEmpty(),
            devices = if (includeDevices) optional(errors, "devices") { api.devices() }.orEmpty() else emptyList(),
            partialErrors = errors,
        )
    }

    fun confirmPairing(baseUrl: String, token: String, code: String, deviceName: String): PairingResult =
        client(baseUrl, token).confirmPairing(code, deviceName)

    fun refreshToken(baseUrl: String, token: String): PairingResult = client(baseUrl, token).refreshToken()

    fun revokeDevice(baseUrl: String, token: String, id: String): RevokeDeviceResponse = client(baseUrl, token).revokeDevice(id)

    fun purgeRevokedDevices(baseUrl: String, token: String): PurgeDevicesResponse = client(baseUrl, token).purgeRevokedDevices()

    fun launchProcess(baseUrl: String, token: String, id: String): RemoteCommandResult = client(baseUrl, token).launchProcess(id)

    fun openShortcut(baseUrl: String, token: String, id: String): RemoteCommandResult = client(baseUrl, token).openShortcut(id)

    fun power(baseUrl: String, token: String, action: String): RemoteCommandResult = client(baseUrl, token).power(action)

    fun savePowerConfig(baseUrl: String, token: String, config: RemotePowerConfigPayload): RemotePowerConfigResponse =
        client(baseUrl, token).savePowerConfig(config)

    fun createGameLink(baseUrl: String, token: String, processId: String, packageName: String): RemoteGameLink =
        client(baseUrl, token).createGameLink(processId, packageName)

    fun startMobileSession(
        baseUrl: String,
        token: String,
        linkId: String,
        source: String = "manual",
        startedAtSeconds: Double? = null,
    ): RemoteMobileSession = client(baseUrl, token).startMobileSession(linkId, source, startedAtSeconds)

    fun endMobileSession(baseUrl: String, token: String, sessionId: String): RemoteMobileSession =
        client(baseUrl, token).endMobileSession(sessionId)

    fun ensureServerTailscale(baseUrl: String, token: String): RemoteTailscaleEnsureResponse =
        client(baseUrl, token).ensureServerTailscale()

    fun saveRemoteLogging(baseUrl: String, token: String, enabled: Boolean, path: String = ""): RemoteLoggingConfigResponse =
        client(baseUrl, token).saveRemoteLoggingConfig(enabled, path)

    fun smartThingsDevices(baseUrl: String, token: String, cliPath: String = ""): RemoteSmartThingsDevicesResponse =
        client(baseUrl, token).smartThingsDevices(cliPath)

    fun registerPowerSshKey(baseUrl: String, token: String, publicKey: String, label: String): RemoteSSHKeyRegistrationResponse =
        client(baseUrl, token).registerPowerSshKey(publicKey, label)

    private fun client(baseUrl: String, token: String) = RemoteApiClient(baseUrl, token)

    private inline fun <T> optional(errors: MutableList<String>, label: String, block: () -> T): T? =
        runCatching(block).onFailure { errors.add("$label: ${it.message ?: it::class.java.simpleName}") }.getOrNull()
}
