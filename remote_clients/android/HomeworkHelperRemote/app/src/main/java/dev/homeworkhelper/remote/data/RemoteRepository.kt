package dev.homeworkhelper.remote.data

class RemoteRepository(
    private val baseUrl: String,
    private val token: String?,
) {
    private val api = RemoteApiClient(baseUrl, token)

    suspend fun fetchHomeSnapshot(): RemoteHomeSnapshot {
        val status = api.status()
        val readiness = runCatching { api.readiness() }.getOrNull()
        val powerStatus = runCatching { api.powerStatus() }.getOrNull()
        val powerSetup = runCatching { api.powerSetup() }.getOrNull()
        val rawProcesses = api.processesRaw()
        return RemoteHomeSnapshot(
            status = status,
            readiness = readiness,
            powerReadiness = RemotePowerReadiness(
                status = powerStatus,
                setup = powerSetup,
                readiness = readiness?.powerReadiness,
            ),
            processes = RemoteProcess.listFromJson(rawProcesses, baseUrl),
            rawProcessesJson = rawProcesses,
        )
    }

    suspend fun launchProcess(id: String): RemoteCommandResult {
        return api.launchProcess(id)
    }

    suspend fun stopProcess(id: String): RemoteCommandResult {
        return api.stopProcess(id)
    }

    suspend fun confirmPairing(code: String, deviceName: String): PairingConfirmResponse {
        return api.confirmPairing(code, deviceName)
    }

    suspend fun devices(): List<RemoteDevice> {
        return api.devices()
    }

    suspend fun revokeDevice(id: String): RemoteDeviceRevokeResponse {
        return api.revokeDevice(id)
    }

    suspend fun purgeRevokedDevices(): PurgeDevicesResponse {
        return api.purgeRevokedDevices()
    }

    suspend fun registerPowerSSHKey(publicKey: String, label: String): RemoteCommandResult {
        return api.registerPowerSSHKey(publicKey, label)
    }

}
