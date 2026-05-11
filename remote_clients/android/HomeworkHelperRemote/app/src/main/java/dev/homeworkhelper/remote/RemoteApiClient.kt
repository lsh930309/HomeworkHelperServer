package dev.homeworkhelper.remote

import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

class RemoteApiClient(
    private val baseUrl: String,
    private val bearerToken: String,
) {
    fun status(): RemoteStatus {
        val json = JSONObject(get("remote/status"))
        val counts = json.getJSONObject("counts")
        val capabilities = json.getJSONObject("capabilities")
        val power = json.optJSONObject("power")
        return RemoteStatus(
            apiVersion = json.optString("remote_api_version"),
            processCount = counts.optInt("processes"),
            shortcutCount = counts.optInt("shortcuts"),
            activeSessionCount = counts.optInt("active_sessions"),
            dashboardSummary = capabilities.optBoolean("dashboard_summary"),
            beholderIncidents = capabilities.optBoolean("beholder_incidents"),
            gameLinks = capabilities.optBoolean("game_links"),
            powerControl = capabilities.optBoolean("power_control"),
            authRequired = capabilities.optBoolean("auth_required"),
            pairing = capabilities.optBoolean("pairing"),
            power = power?.let {
                RemotePowerStatus(
                    configured = it.optBoolean("configured"),
                    status = it.optString("status", "unknown"),
                    supportedActions = it.optJSONArray("supported_actions")?.toStringSet().orEmpty(),
                    targetHost = it.optString("target_host"),
                )
            },
        )
    }

    fun capabilities(): RemoteCapabilities {
        val json = JSONObject(get("remote/capabilities"))
        val capabilities = json.getJSONObject("capabilities")
        return RemoteCapabilities(
            apiVersion = json.optString("remote_api_version"),
            processLaunch = capabilities.optBoolean("process_launch"),
            shortcutOpen = capabilities.optBoolean("shortcut_open"),
            dashboardSummary = capabilities.optBoolean("dashboard_summary"),
            beholderIncidents = capabilities.optBoolean("beholder_incidents"),
            gameLinks = capabilities.optBoolean("game_links"),
            powerControl = capabilities.optBoolean("power_control"),
            authRequired = capabilities.optBoolean("auth_required"),
            pairing = capabilities.optBoolean("pairing"),
        )
    }

    fun beholderIncidents(): List<RemoteBeholderIncident> {
        val json = JSONObject(get("remote/beholder/incidents"))
        return json.getJSONArray("incidents").mapObjects { item ->
            RemoteBeholderIncident(
                id = item.optInt("id"),
                severity = item.optString("severity"),
                status = item.optString("status"),
                userTitle = item.optString("user_title"),
                userSummary = item.optString("user_summary"),
                riskScore = item.optInt("risk_score"),
                riskLabels = item.optJSONArray("risk_labels")?.toStringList().orEmpty(),
            )
        }
    }

    fun dashboardSummary(): RemoteDashboardSummary {
        val json = JSONObject(get("remote/dashboard/summary"))
        val range = json.getJSONObject("range")
        val metrics = json.getJSONObject("metrics")
        val topGame = metrics.optJSONObject("top_game")
        return RemoteDashboardSummary(
            rangeStart = range.optString("start"),
            rangeEnd = range.optString("end"),
            totalSeconds = metrics.optDouble("total_seconds"),
            dailyAverageSeconds = metrics.optDouble("daily_average_seconds"),
            playedDays = metrics.optInt("played_days"),
            sessionCount = metrics.optInt("session_count"),
            topGameName = topGame?.optString("display_name").orEmpty(),
            topGameSeconds = topGame?.optDouble("total_seconds") ?: 0.0,
        )
    }

    fun gameLinks(): List<RemoteGameLink> {
        val json = JSONObject(get("remote/game-links"))
        return json.getJSONArray("links").mapObjects { item ->
            RemoteGameLink(
                id = item.optString("id"),
                pcProcessId = item.optString("pc_process_id"),
                pcDisplayName = item.optString("pc_display_name"),
                androidPackageName = item.optString("android_package_name"),
                androidLaunchIntentUri = item.optString("android_launch_intent_uri"),
                androidStoreUrl = item.optString("android_store_url"),
                platformAccountHint = item.optString("platform_account_hint"),
                hoyolabGameId = item.optString("hoyolab_game_id"),
                syncStrategy = item.optString("sync_strategy", "manual"),
            )
        }
    }

    fun createGameLink(processId: String, androidPackageName: String, syncStrategy: String = "manual"): RemoteGameLink {
        val body = JSONObject()
            .put("pc_process_id", processId)
            .put("android_package_name", androidPackageName)
            .put("sync_strategy", syncStrategy)
            .toString()
        val item = JSONObject(post("remote/game-links", body))
        return RemoteGameLink(
            id = item.optString("id"),
            pcProcessId = item.optString("pc_process_id"),
            pcDisplayName = item.optString("pc_display_name"),
            androidPackageName = item.optString("android_package_name"),
            androidLaunchIntentUri = item.optString("android_launch_intent_uri"),
            androidStoreUrl = item.optString("android_store_url"),
            platformAccountHint = item.optString("platform_account_hint"),
            hoyolabGameId = item.optString("hoyolab_game_id"),
            syncStrategy = item.optString("sync_strategy", "manual"),
        )
    }

    fun processes(): List<RemoteProcess> = JSONArray(get("remote/processes")).mapObjects { item ->
        RemoteProcess(
            id = item.optString("id"),
            name = item.optString("name"),
            preferredLaunchType = item.optString("preferred_launch_type", "shortcut"),
            monitoringPath = item.optString("monitoring_path"),
            launchPath = item.optString("launch_path"),
        )
    }

    fun shortcuts(): List<RemoteShortcut> = JSONArray(get("remote/shortcuts")).mapObjects { item ->
        RemoteShortcut(
            id = item.optString("id"),
            name = item.optString("name"),
            url = item.optString("url"),
        )
    }

    fun launchProcess(id: String): RemoteCommandResult = command(post("remote/processes/$id/launch", "{}"))

    fun openShortcut(id: String): RemoteCommandResult = command(post("remote/shortcuts/$id/open", "{}"))

    fun power(action: String): RemoteCommandResult = command(post("remote/power/$action", "{}"))

    fun confirmPairing(code: String, deviceName: String): PairingResult {
        val body = JSONObject()
            .put("code", code)
            .put("device_name", deviceName)
            .put("platform", "android")
            .toString()
        val json = JSONObject(post("remote/pair/confirm", body))
        return PairingResult(
            id = json.optString("id"),
            deviceName = json.optString("name", json.optString("device_name")),
            platform = json.optString("platform"),
            token = json.optString("token"),
        )
    }

    fun refreshToken(): PairingResult {
        val json = JSONObject(post("remote/tokens/refresh", "{}"))
        return PairingResult(
            id = json.optString("id"),
            deviceName = json.optString("name", json.optString("device_name")),
            platform = json.optString("platform"),
            token = json.optString("token"),
        )
    }

    fun devices(): List<RemoteDevice> {
        val json = JSONObject(get("remote/devices"))
        return json.getJSONArray("devices").mapObjects { item ->
            RemoteDevice(
                id = item.optString("id"),
                deviceName = item.optString("name", item.optString("device_name")),
                platform = item.optString("platform"),
                tokenRefreshedAt = item.optString("token_refreshed_at"),
                revokedAt = item.optString("revoked_at"),
            )
        }
    }

    fun revokeDevice(id: String): Boolean = JSONObject(delete("remote/devices/$id")).optBoolean("revoked")

    private fun command(body: String): RemoteCommandResult {
        val json = JSONObject(body)
        return RemoteCommandResult(
            accepted = json.optBoolean("accepted"),
            command = json.optString("command"),
            status = json.optString("status"),
            message = json.optString("message"),
        )
    }

    private fun get(path: String): String = request(path, "GET", null)

    private fun post(path: String, body: String): String = request(path, "POST", body)

    private fun delete(path: String): String = request(path, "DELETE", null)

    private fun request(path: String, method: String, body: String?): String {
        val normalized = baseUrl.trimEnd('/') + "/" + path.trimStart('/')
        val connection = (URL(normalized).openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 5_000
            readTimeout = 10_000
            setRequestProperty("Accept", "application/json")
            if (bearerToken.isNotBlank()) {
                setRequestProperty("Authorization", "Bearer $bearerToken")
            }
            if (body != null) {
                doOutput = true
                setRequestProperty("Content-Type", "application/json")
                outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            }
        }
        val responseCode = connection.responseCode
        val stream = if (responseCode in 200..299) connection.inputStream else connection.errorStream
        val text = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
        connection.disconnect()
        if (responseCode !in 200..299) {
            error("HTTP $responseCode: $text")
        }
        return text
    }
}

private fun <T> JSONArray.mapObjects(transform: (JSONObject) -> T): List<T> = buildList {
    for (index in 0 until length()) {
        add(transform(getJSONObject(index)))
    }
}


private fun JSONArray.toStringSet(): Set<String> = buildSet {
    for (index in 0 until length()) {
        optString(index).takeIf { it.isNotBlank() }?.let { add(it) }
    }
}

private fun JSONArray.toStringList(): List<String> = buildList {
    for (index in 0 until length()) {
        optString(index).takeIf { it.isNotBlank() }?.let { add(it) }
    }
}
