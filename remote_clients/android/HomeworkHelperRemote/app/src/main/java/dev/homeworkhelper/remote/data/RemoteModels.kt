package dev.homeworkhelper.remote.data

import org.json.JSONArray
import org.json.JSONObject
import kotlin.math.floor

private const val SERVER_TRACKED_SOURCE = "server_tracked"
private const val TIMESTAMP_DERIVED_SOURCE = "timestamp_derived"

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
    val processStop: Boolean,
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
    val schemaVersion: Int,
    val source: String,
    val kind: String,
    val percentage: Double,
    val displayText: String?,
    val status: String?,
    val remainingSeconds: Int?,
    val readyAt: Double?,
    val projectionStrategy: String?,
    val projectionUnit: String?,
    val projectionBaseValue: Double?,
    val projectionMaxValue: Double?,
    val projectionBaseTimestamp: Double?,
    val projectionRecoverySecondsPerUnit: Int?,
    val projectionFullRecoverySeconds: Int?,
    val projectionCycleSeconds: Int?,
    val provider: String?,
    val key: String?,
    val label: String?,
    val resourceIconUrl: String?,
    val resourceIconUrls: Map<String, String>,
) {
    val preferredResourceIconUrl: String?
        get() = resourceIconUrls["32"] ?: resourceIconUrls["64"] ?: resourceIconUrl ?: resourceIconUrls.values.firstOrNull()

    val sourceLabel: String
        get() = when (source) {
            SERVER_TRACKED_SOURCE -> "서버 추적"
            TIMESTAMP_DERIVED_SOURCE -> "로컬 예측"
            else -> source.ifBlank { "진행률" }
        }

    fun projectedPercentage(nowSeconds: Double = System.currentTimeMillis() / 1000.0): Double {
        val projected = when (projectionStrategy) {
            "cycle_elapsed" -> {
                val base = projectionBaseTimestamp
                val cycle = projectionCycleSeconds
                if (base != null && cycle != null && cycle > 0) {
                    ((nowSeconds - base) / cycle.toDouble()) * 100.0
                } else {
                    percentage
                }
            }
            "linear_recovery" -> {
                val base = projectionBaseValue
                val max = projectionMaxValue
                val timestamp = projectionBaseTimestamp
                val secondsPerUnit = projectionRecoverySecondsPerUnit
                if (base != null && max != null && max > 0.0 && timestamp != null && secondsPerUnit != null && secondsPerUnit > 0) {
                    val recovered = floor((nowSeconds - timestamp).coerceAtLeast(0.0) / secondsPerUnit.toDouble())
                    ((base + recovered).coerceIn(0.0, max) / max) * 100.0
                } else {
                    percentage
                }
            }
            "linear_percent_fill" -> {
                val base = projectionBaseValue
                val timestamp = projectionBaseTimestamp
                val fullSeconds = projectionFullRecoverySeconds
                if (base != null && timestamp != null && fullSeconds != null && fullSeconds > 0) {
                    val elapsedPercent = ((nowSeconds - timestamp).coerceAtLeast(0.0) / fullSeconds.toDouble()) * 100.0
                    base + elapsedPercent
                } else {
                    percentage
                }
            }
            else -> percentage
        }
        return projected.coerceIn(0.0, 100.0)
    }

    fun projectedDisplayText(nowSeconds: Double = System.currentTimeMillis() / 1000.0): String {
        val percent = projectedPercentage(nowSeconds)
        if (projectionStrategy == "linear_recovery" && projectionUnit == "count") {
            val base = projectionBaseValue
            val max = projectionMaxValue
            val timestamp = projectionBaseTimestamp
            val secondsPerUnit = projectionRecoverySecondsPerUnit
            if (base != null && max != null && timestamp != null && secondsPerUnit != null && secondsPerUnit > 0) {
                val recovered = floor((nowSeconds - timestamp).coerceAtLeast(0.0) / secondsPerUnit.toDouble())
                val value = (base + recovered).coerceIn(0.0, max).toInt()
                return "$value/${max.toInt()}"
            }
        }
        if (projectionStrategy == "linear_percent_fill") {
            return "${String.format(java.util.Locale.US, "%.1f", percent)}%"
        }
        return displayText ?: "${percent.toInt()}%"
    }
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
            val projection = json.optJSONObject("projection")
            return RemoteProgress(
                schemaVersion = json.optInt("schema_version", 1),
                source = json.optString("source", "unknown"),
                kind = json.optString("kind", "unknown"),
                percentage = json.optDouble("percentage", 0.0).coerceIn(0.0, 100.0),
                displayText = json.optStringOrNull("display_text"),
                status = json.optStringOrNull("status"),
                remainingSeconds = json.optIntOrNull("remaining_seconds"),
                readyAt = json.optDoubleOrNull("ready_at"),
                projectionStrategy = projection?.optStringOrNull("strategy"),
                projectionUnit = projection?.optStringOrNull("unit"),
                projectionBaseValue = projection?.optDoubleOrNull("base_value"),
                projectionMaxValue = projection?.optDoubleOrNull("max_value"),
                projectionBaseTimestamp = projection?.optDoubleOrNull("base_timestamp"),
                projectionRecoverySecondsPerUnit = projection?.optIntOrNull("recovery_seconds_per_unit"),
                projectionFullRecoverySeconds = projection?.optIntOrNull("full_recovery_seconds"),
                projectionCycleSeconds = projection?.optIntOrNull("cycle_seconds"),
                provider = json.optStringOrNull("provider"),
                key = json.optStringOrNull("key"),
                label = json.optStringOrNull("label"),
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
    val commandId: String? = null,
    val acceptedAt: Double? = null,
    val refreshAfterMs: Int? = null,
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

data class RemoteDevice(
    val id: String,
    val name: String,
    val platform: String,
    val role: String,
    val tailnetIp: String,
    val pairingStatus: String,
    val connectivityState: String,
    val healthMessage: String?,
    val canRevoke: Boolean,
    val revokedAt: Double?,
)

data class RemoteDeviceRevokeResponse(
    val revoked: Boolean,
    val deviceId: String,
)

data class PurgeDevicesResponse(
    val removed: Int,
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

fun JSONObject.optDoubleOrNull(name: String): Double? {
    if (!has(name) || isNull(name)) return null
    return optDouble(name)
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
        processStop = capabilities?.optBoolean("process_stop", false) ?: false,
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
        commandId = optStringOrNull("command_id"),
        acceptedAt = optDoubleOrNull("accepted_at"),
        refreshAfterMs = optIntOrNull("refresh_after_ms"),
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

fun JSONObject.toRemoteDevices(): List<RemoteDevice> {
    val array = optJSONArray("devices") ?: JSONArray()
    return List(array.length()) { index -> array.getJSONObject(index).toRemoteDevice() }
}

fun JSONObject.toRemoteDevice(): RemoteDevice {
    return RemoteDevice(
        id = optString("id"),
        name = optString("name", optString("id", "Unknown device")),
        platform = optString("platform", "unknown"),
        role = optString("role", "client"),
        tailnetIp = optString("tailnet_ip", ""),
        pairingStatus = optString("pairing_status", if (isNull("revoked_at")) "paired" else "revoked"),
        connectivityState = optString("connectivity_state", "unknown"),
        healthMessage = optStringOrNull("health_message"),
        canRevoke = optBoolean("can_revoke", false),
        revokedAt = optDoubleOrNull("revoked_at"),
    )
}

fun JSONObject.toRemoteDeviceRevokeResponse(): RemoteDeviceRevokeResponse {
    return RemoteDeviceRevokeResponse(
        revoked = optBoolean("revoked", false),
        deviceId = optString("device_id"),
    )
}

fun JSONObject.toPurgeDevicesResponse(): PurgeDevicesResponse {
    return PurgeDevicesResponse(removed = optInt("removed", 0))
}
