package dev.homeworkhelper.remote.data

class RemoteRepository(
    private val baseUrl: String,
    private val token: String?,
) {
    private val api = RemoteApiClient(baseUrl, token)

    suspend fun fetchHomeSnapshot(): RemoteHomeSnapshot {
        val status = api.status()
        val readiness = runCatching { api.readiness() }.getOrNull()
        val rawProcesses = api.processesRaw()
        return RemoteHomeSnapshot(
            status = status,
            readiness = readiness,
            processes = RemoteProcess.listFromJson(rawProcesses),
            rawProcessesJson = rawProcesses,
        )
    }

    suspend fun launchProcess(id: String): RemoteCommandResult {
        return api.launchProcess(id)
    }

    suspend fun confirmPairing(code: String, deviceName: String): PairingConfirmResponse {
        return api.confirmPairing(code, deviceName)
    }
}
