package dev.homeworkhelper.remote.data

import org.json.JSONArray
import org.json.JSONObject

enum class RemoteAvailability {
    Unknown,
    Online,
    OfflineExpected,
    AgentUnavailable,
    AuthRejected,
    Waking,
    GoingOffline,
    Restarting,
}

data class RemoteStatus(
    val stateRevision: String?,
    val processCount: Int,
    val processLaunch: Boolean,
    val authRequired: Boolean,
    val serverTime: Double?,
)

data class RemoteReadiness(
    val remoteConnectivity: RemoteReadinessSection?,
    val serverModeReadiness: RemoteReadinessSection?,
    val powerReadiness: RemoteReadinessSection?,
    val tailscaleReadiness: RemoteReadinessSection?,
)

data class RemoteReadinessSection(
    val state: String?,
    val color: String?,
    val message: String?,
    val supportedActions: List<String> = emptyList(),
)

data class RemoteProgress(
    val kind: String,
    val percentage: Double,
    val displayText: String?,
    val remainingSeconds: Int?,
    val resourceIconUrl: String?,
    val resourceIconUrls: Map<String, String>,
) {
    val preferredResourceIconUrl: String?
        get() = resourceIconUrls["32"] ?: resourceIconUrls["64"] ?: resourceIconUrl ?: resourceIconUrls.values.firstOrNull()
}

data class RemoteProcess(
    val id: String,
    val name: String,
    val statusText: String?,
    val progress: RemoteProgress?,
    val iconUrl: String?,
    val iconUrls: Map<String, String>,
    val isRunning: Boolean,
    val playedToday: Boolean,
) {
    val safeStatusText: String
        get() = statusText?.takeIf { it.isNotBlank() } ?: if (isRunning) "실행 중" else "대기"

    val preferredIconUrl: String?
        get() = iconUrls["128"] ?: iconUrls["64"] ?: iconUrl ?: iconUrls.values.firstOrNull()

    companion object {
        fun listFromJson(raw: String, baseUrl: String? = null): List<RemoteProcess> {
            val array = JSONArray(raw)
            return List(array.length()) { index -> fromJson(array.getJSONObject(index)) }
                .map { process -> if (baseUrl.isNullOrBlank()) process else process.resolveAssetUrls(baseUrl) }
        }

        private fun fromJson(json: JSONObject): RemoteProcess {
            val name = json.optString("name", "Unnamed")
            val id = json.optString("id").takeIf { it.isNotBlank() } ?: name
            return RemoteProcess(
                id = id,
                name = name,
                statusText = json.optStringOrNull("status_text"),
                progress = json.optJSONObject("progress")?.let(::progressFromJson),
                iconUrl = json.optStringOrNull("icon_url"),
                iconUrls = json.optJSONObject("icon_urls")?.toStringMap().orEmpty(),
                isRunning = json.optBoolean("is_running", false),
                playedToday = json.optBoolean("played_today", false),
            )
        }

        private fun progressFromJson(json: JSONObject): RemoteProgress {
            return RemoteProgress(
                kind = json.optString("kind", "unknown"),
                percentage = json.optDouble("percentage", 0.0).coerceIn(0.0, 100.0),
                displayText = json.optStringOrNull("display_text"),
                remainingSeconds = json.optIntOrNull("remaining_seconds"),
                resourceIconUrl = json.optStringOrNull("resource_icon_url"),
                resourceIconUrls = json.optJSONObject("resource_icon_urls")?.toStringMap().orEmpty(),
            )
        }
    }
}

data class RemoteCommandResult(
    val accepted: Boolean,
    val status: String,
    val message: String,
)

data class RemotePowerStatus(
    val configured: Boolean,
    val state: String?,
    val status: String?,
    val targetHost: String?,
    val supportedActions: List<String>,
    val message: String?,
)

data class RemotePowerSetup(
    val message: String?,
    val hostPlatform: String?,
    val user: String?,
    val effectiveAuthorizedKeysPath: String?,
    val sshServiceMessage: String?,
)

data class RemoteTailscaleEnsure(
    val ready: Boolean,
    val method: String?,
    val message: String?,
    val suggestedBaseUrls: List<String>,
)

data class RemotePowerReadiness(
    val status: RemotePowerStatus?,
    val setup: RemotePowerSetup?,
    val readiness: RemoteReadinessSection?,
) {
    val isConfigured: Boolean
        get() = status?.configured == true

    val summary: String
        get() = readiness?.message
            ?: status?.message
            ?: setup?.message
            ?: "전원 준비 상태를 아직 확인하지 못했습니다."
}

data class PairingConfirmResponse(
    val id: String,
    val name: String,
    val token: String,
)

data class RemoteHomeSnapshot(
    val status: RemoteStatus,
    val readiness: RemoteReadiness?,
    val powerReadiness: RemotePowerReadiness,
    val processes: List<RemoteProcess>,
    val rawProcessesJson: String,
)

fun JSONObject.optStringOrNull(name: String): String? {
    if (!has(name) || isNull(name)) return null
    return optString(name).takeIf { it.isNotBlank() }
}

fun JSONObject.optIntOrNull(name: String): Int? {
    if (!has(name) || isNull(name)) return null
    return optInt(name)
}

fun JSONObject.toStringMap(): Map<String, String> {
    return keys().asSequence().mapNotNull { key ->
        optStringOrNull(key)?.let { value -> key to value }
    }.toMap()
}

fun RemoteProcess.resolveAssetUrls(baseUrl: String): RemoteProcess {
    return copy(
        iconUrl = resolveRemoteUrl(baseUrl, iconUrl),
        iconUrls = iconUrls.mapValues { (_, value) -> resolveRemoteUrl(baseUrl, value) ?: value },
        progress = progress?.resolveAssetUrls(baseUrl),
    )
}

fun RemoteProgress.resolveAssetUrls(baseUrl: String): RemoteProgress {
    return copy(
        resourceIconUrl = resolveRemoteUrl(baseUrl, resourceIconUrl),
        resourceIconUrls = resourceIconUrls.mapValues { (_, value) -> resolveRemoteUrl(baseUrl, value) ?: value },
    )
}

fun resolveRemoteUrl(baseUrl: String, value: String?): String? {
    val raw = value?.trim()?.takeIf { it.isNotBlank() } ?: return null
    if (raw.startsWith("http://") || raw.startsWith("https://")) return raw
    val base = baseUrl.trim().trimEnd('/')
    return if (raw.startsWith('/')) "$base$raw" else "$base/$raw"
}

fun JSONObject.toRemoteStatus(): RemoteStatus {
    val counts = optJSONObject("counts")
    val capabilities = optJSONObject("capabilities")
    return RemoteStatus(
        stateRevision = optStringOrNull("state_revision"),
        processCount = counts?.optInt("processes", 0) ?: 0,
        processLaunch = capabilities?.optBoolean("process_launch", false) ?: false,
        authRequired = capabilities?.optBoolean("auth_required", false) ?: false,
        serverTime = if (has("server_time") && !isNull("server_time")) optDouble("server_time") else null,
    )
}

fun JSONObject.toRemoteReadiness(): RemoteReadiness {
    return RemoteReadiness(
        remoteConnectivity = optJSONObject("remote_connectivity")?.toRemoteReadinessSection(),
        serverModeReadiness = optJSONObject("server_mode_readiness")?.toRemoteReadinessSection(),
        powerReadiness = optJSONObject("power_readiness")?.toRemoteReadinessSection(),
        tailscaleReadiness = optJSONObject("tailscale_readiness")?.toRemoteReadinessSection(),
    )
}

fun JSONObject.toRemoteReadinessSection(): RemoteReadinessSection {
    return RemoteReadinessSection(
        state = optStringOrNull("state"),
        color = optStringOrNull("color"),
        message = optStringOrNull("message"),
        supportedActions = optJSONArray("supported_actions")?.let { array ->
            List(array.length()) { index -> array.optString(index) }.filter { it.isNotBlank() }
        }.orEmpty(),
    )
}

fun JSONObject.toRemoteCommandResult(): RemoteCommandResult {
    return RemoteCommandResult(
        accepted = optBoolean("accepted", false),
        status = optString("status", "unknown"),
        message = optString("message", "명령 결과를 확인할 수 없습니다."),
    )
}

fun JSONObject.toPairingConfirmResponse(): PairingConfirmResponse {
    return PairingConfirmResponse(
        id = optString("id"),
        name = optString("name"),
        token = optString("token"),
    )
}

fun JSONObject.toRemotePowerStatus(): RemotePowerStatus {
    return RemotePowerStatus(
        configured = optBoolean("configured", false),
        state = optStringOrNull("state"),
        status = optStringOrNull("status"),
        targetHost = optStringOrNull("target_host"),
        supportedActions = optJSONArray("supported_actions")?.let { array ->
            List(array.length()) { index -> array.optString(index) }.filter { it.isNotBlank() }
        }.orEmpty(),
        message = optStringOrNull("message"),
    )
}

fun JSONObject.toRemoteTailscaleEnsure(): RemoteTailscaleEnsure {
    return RemoteTailscaleEnsure(
        ready = optBoolean("ready", false),
        method = optStringOrNull("method"),
        message = optStringOrNull("message"),
        suggestedBaseUrls = optJSONArray("suggested_base_urls")?.let { array ->
            List(array.length()) { index -> array.optString(index) }.filter { it.isNotBlank() }
        } ?: optJSONObject("after")?.optJSONArray("suggested_base_urls")?.let { array ->
            List(array.length()) { index -> array.optString(index) }.filter { it.isNotBlank() }
        }.orEmpty(),
    )
}

fun JSONObject.toRemotePowerSetup(): RemotePowerSetup {
    val sshService = optJSONObject("ssh_service")
    return RemotePowerSetup(
        message = optStringOrNull("message"),
        hostPlatform = optStringOrNull("host_platform"),
        user = optStringOrNull("user"),
        effectiveAuthorizedKeysPath = optStringOrNull("effective_authorized_keys_path")
            ?: optStringOrNull("authorized_keys_path"),
        sshServiceMessage = sshService?.optStringOrNull("message"),
    )
}
