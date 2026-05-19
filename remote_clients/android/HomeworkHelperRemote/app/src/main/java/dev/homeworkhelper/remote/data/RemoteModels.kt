package dev.homeworkhelper.remote.data

import org.json.JSONArray
import org.json.JSONObject

enum class RemoteAvailability {
    Unknown,
    Online,
    OfflineExpected,
    AgentUnavailable,
    AuthRejected,
}

data class RemoteStatus(
    val stateRevision: String?,
    val processCount: Int,
    val processLaunch: Boolean,
    val authRequired: Boolean,
    val serverTime: Double?,
)

data class RemoteReadiness(
    val message: String?,
    val color: String?,
)

data class RemoteProgress(
    val kind: String,
    val percentage: Double,
    val displayText: String?,
    val remainingSeconds: Int?,
)

data class RemoteProcess(
    val id: String,
    val name: String,
    val statusText: String?,
    val progress: RemoteProgress?,
    val iconUrl: String?,
    val isRunning: Boolean,
    val playedToday: Boolean,
) {
    val safeStatusText: String
        get() = statusText?.takeIf { it.isNotBlank() } ?: if (isRunning) "실행 중" else "대기"

    companion object {
        fun listFromJson(raw: String): List<RemoteProcess> {
            val array = JSONArray(raw)
            return List(array.length()) { index -> fromJson(array.getJSONObject(index)) }
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
            )
        }
    }
}

data class RemoteCommandResult(
    val accepted: Boolean,
    val status: String,
    val message: String,
)

data class PairingConfirmResponse(
    val id: String,
    val name: String,
    val token: String,
)

data class RemoteHomeSnapshot(
    val status: RemoteStatus,
    val readiness: RemoteReadiness?,
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
    val remote = optJSONObject("remote_connectivity")
    val server = optJSONObject("server_mode_readiness")
    val section = remote ?: server
    return RemoteReadiness(
        message = section?.optStringOrNull("message"),
        color = section?.optStringOrNull("color"),
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
