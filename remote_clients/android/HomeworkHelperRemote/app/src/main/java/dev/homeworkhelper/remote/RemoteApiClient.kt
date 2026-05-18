package dev.homeworkhelper.remote

import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder

class RemoteApiClient(
    private val baseUrl: String,
    private val bearerToken: String,
) {
    fun status(): RemoteStatus {
        val json = JSONObject(get("remote/status"))
        val counts = json.optJSONObject("counts") ?: JSONObject()
        val capabilities = json.optJSONObject("capabilities") ?: JSONObject()
        val power = json.optJSONObject("power")
        return RemoteStatus(
            apiVersion = json.optString("remote_api_version"),
            processCount = counts.optInt("processes"),
            shortcutCount = counts.optInt("shortcuts"),
            activeSessionCount = counts.optInt("active_sessions"),
            dashboardSummary = capabilities.optBoolean("dashboard_summary"),
            beholderIncidents = capabilities.optBoolean("beholder_incidents"),
            gameLinks = capabilities.optBoolean("game_links"),
            mobileSessions = capabilities.optBoolean("mobile_sessions"),
            powerConfig = capabilities.optBoolean("power_config"),
            powerControl = capabilities.optBoolean("power_control"),
            authRequired = capabilities.optBoolean("auth_required"),
            pairing = capabilities.optBoolean("pairing"),
            tailscaleDiscovery = capabilities.optBoolean("tailscale_discovery"),
            readiness = capabilities.optBoolean("readiness"),
            localStoreHealth = capabilities.optBoolean("local_store_health"),
            power = power?.toRemotePowerStatus(),
        )
    }

    fun capabilities(): RemoteCapabilities {
        val json = JSONObject(get("remote/capabilities"))
        val capabilities = json.optJSONObject("capabilities") ?: JSONObject()
        return RemoteCapabilities(
            apiVersion = json.optString("remote_api_version"),
            processLaunch = capabilities.optBoolean("process_launch"),
            shortcutOpen = capabilities.optBoolean("shortcut_open"),
            dashboardSummary = capabilities.optBoolean("dashboard_summary"),
            beholderIncidents = capabilities.optBoolean("beholder_incidents"),
            gameLinks = capabilities.optBoolean("game_links"),
            mobileSessions = capabilities.optBoolean("mobile_sessions"),
            powerConfig = capabilities.optBoolean("power_config"),
            powerControl = capabilities.optBoolean("power_control"),
            authRequired = capabilities.optBoolean("auth_required"),
            pairing = capabilities.optBoolean("pairing"),
            tailscaleDiscovery = capabilities.optBoolean("tailscale_discovery"),
            readiness = capabilities.optBoolean("readiness"),
            localStoreHealth = capabilities.optBoolean("local_store_health"),
        )
    }

    fun readiness(): RemoteReadiness = JSONObject(get("remote/readiness")).toRemoteReadiness()

    fun remoteLoggingConfig(): RemoteLoggingConfigResponse = JSONObject(get("remote/logging/config")).toRemoteLoggingConfig()

    fun saveRemoteLoggingConfig(enabled: Boolean, path: String = ""): RemoteLoggingConfigResponse {
        val body = JSONObject().put("enabled", enabled)
        if (path.isNotBlank()) body.put("path", path)
        return JSONObject(put("remote/logging/config", body.toString())).toRemoteLoggingConfig()
    }

    fun ensureServerTailscale(): RemoteTailscaleEnsureResponse =
        JSONObject(post("remote/tailscale/ensure", "{}")).toRemoteTailscaleEnsureResponse()

    fun powerSetup(): RemotePowerSetupResponse = JSONObject(get("remote/power/setup")).toRemotePowerSetupResponse()

    fun registerPowerSshKey(publicKey: String, label: String = "HomeworkHelper Android Remote"): RemoteSSHKeyRegistrationResponse {
        val body = JSONObject()
            .put("public_key", publicKey)
            .put("label", label)
            .toString()
        return JSONObject(post("remote/power/ssh-key", body)).toRemoteSSHKeyRegistrationResponse()
    }

    fun smartThingsDevices(cliPath: String = ""): RemoteSmartThingsDevicesResponse {
        val body = JSONObject().put("cli_path", cliPath.ifBlank { JSONObject.NULL }).toString()
        return JSONObject(post("remote/power/smartthings/devices", body)).toRemoteSmartThingsDevicesResponse()
    }

    fun beholderIncidents(): List<RemoteBeholderIncident> {
        val json = JSONObject(get("remote/beholder/incidents"))
        return json.optJSONArray("incidents")?.mapObjects { item ->
            RemoteBeholderIncident(
                id = item.optInt("id"),
                severity = item.optString("severity"),
                status = item.optString("status"),
                userTitle = item.optString("user_title"),
                userSummary = item.optString("user_summary"),
                riskScore = item.optInt("risk_score"),
                riskLabels = item.optJSONArray("risk_labels")?.toStringList().orEmpty(),
            )
        }.orEmpty()
    }

    fun dashboardSummary(): RemoteDashboardSummary {
        val json = JSONObject(get("remote/dashboard/summary"))
        val range = json.optJSONObject("range") ?: JSONObject()
        val metrics = json.optJSONObject("metrics") ?: JSONObject()
        val topGame = metrics.optJSONObject("top_game")
        val mobileMetrics = json.optJSONObject("mobile_metrics")
        val mobileTopGame = mobileMetrics?.optJSONObject("top_game")
        return RemoteDashboardSummary(
            rangeStart = range.optString("start"),
            rangeEnd = range.optString("end"),
            totalSeconds = metrics.optDouble("total_seconds"),
            dailyAverageSeconds = metrics.optDouble("daily_average_seconds"),
            playedDays = metrics.optInt("played_days"),
            sessionCount = metrics.optInt("session_count"),
            topGameName = topGame?.optString("display_name").orEmpty(),
            topGameSeconds = topGame?.optDouble("total_seconds") ?: 0.0,
            mobileTotalSeconds = mobileMetrics?.optDouble("total_seconds") ?: 0.0,
            mobileActiveSeconds = mobileMetrics?.optDouble("active_seconds") ?: 0.0,
            mobileSessionCount = mobileMetrics?.optInt("session_count") ?: 0,
            mobileActiveSessionCount = mobileMetrics?.optInt("active_session_count") ?: 0,
            mobileTopGameName = mobileTopGame?.optString("display_name").orEmpty(),
            mobileTopAndroidPackageName = mobileTopGame?.optString("android_package_name").orEmpty(),
            mobileTopGameSeconds = mobileTopGame?.optDouble("total_seconds") ?: 0.0,
        )
    }

    fun gameLinks(): List<RemoteGameLink> {
        val json = JSONObject(get("remote/game-links"))
        return json.optJSONArray("links")?.mapObjects { item -> item.toGameLink() }.orEmpty()
    }

    fun createGameLink(processId: String, androidPackageName: String, syncStrategy: String = "manual"): RemoteGameLink {
        val body = JSONObject()
            .put("pc_process_id", processId)
            .put("android_package_name", androidPackageName)
            .put("sync_strategy", syncStrategy)
            .toString()
        return JSONObject(post("remote/game-links", body)).toGameLink()
    }

    fun activeMobileSessions(): List<RemoteMobileSession> {
        val json = JSONObject(get("remote/mobile-sessions/active"))
        return json.optJSONArray("sessions")?.mapObjects { item -> item.toMobileSession() }.orEmpty()
    }

    fun powerConfig(): RemotePowerConfigResponse = JSONObject(get("remote/power/config")).toPowerConfigResponse()

    fun savePowerConfig(config: RemotePowerConfigPayload): RemotePowerConfigResponse {
        val body = JSONObject()
            .put("smartthings_device_id", config.smartthingsDeviceId)
            .put("smartthings_cli_path", config.smartthingsCliPath)
            .put("ssh_host", config.sshHost)
            .put("ssh_port", config.sshPort)
            .put("ssh_user", config.sshUser)
            .put("ssh_key_path", config.sshKeyPath)
            .put("status_timeout_seconds", config.statusTimeoutSeconds)
            .toString()
        return JSONObject(put("remote/power/config", body)).toPowerConfigResponse()
    }

    fun startMobileSession(gameLinkId: String, source: String = "manual", startedAtSeconds: Double? = null): RemoteMobileSession {
        val body = JSONObject()
            .put("game_link_id", gameLinkId)
            .put("source", source)
        if (startedAtSeconds != null) {
            body.put("started_at", startedAtSeconds)
        }
        return JSONObject(post("remote/mobile-sessions/start", body.toString())).toMobileSession()
    }

    fun endMobileSession(sessionId: String): RemoteMobileSession {
        val body = JSONObject().put("session_id", sessionId).toString()
        return JSONObject(post("remote/mobile-sessions/end", body)).toMobileSession()
    }

    fun processes(): List<RemoteProcess> = JSONArray(get("remote/processes")).mapObjects { item -> item.toRemoteProcess() }

    fun shortcuts(): List<RemoteShortcut> = JSONArray(get("remote/shortcuts")).mapObjects { item ->
        RemoteShortcut(
            id = item.optString("id"),
            name = item.optString("name"),
            url = item.optString("url"),
        )
    }

    fun launchProcess(id: String): RemoteCommandResult = command(post("remote/processes/${pathSegment(id)}/launch", "{}"))

    fun openShortcut(id: String): RemoteCommandResult = command(post("remote/shortcuts/${pathSegment(id)}/open", "{}"))

    fun confirmPairing(code: String, deviceName: String): PairingResult {
        val body = JSONObject()
            .put("code", code)
            .put("device_name", deviceName)
            .put("platform", "android")
            .toString()
        val json = JSONObject(post("remote/pair/confirm", body))
        return json.toPairingResult()
    }

    fun refreshToken(): PairingResult = JSONObject(post("remote/tokens/refresh", "{}")).toPairingResult()

    fun devices(): List<RemoteDevice> {
        val json = JSONObject(get("remote/devices"))
        return json.optJSONArray("devices")?.mapObjects { item -> item.toRemoteDevice() }.orEmpty()
    }

    fun revokeDevice(id: String): RevokeDeviceResponse {
        val json = JSONObject(delete("remote/devices/${pathSegment(id)}"))
        return RevokeDeviceResponse(
            revoked = json.optBoolean("revoked"),
            deviceId = json.optString("device_id"),
        )
    }

    fun purgeRevokedDevices(): PurgeDevicesResponse =
        PurgeDevicesResponse(removed = JSONObject(delete("remote/devices/revoked")).optInt("removed"))

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

    private fun put(path: String, body: String): String = request(path, "PUT", body)

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

    private fun pathSegment(value: String): String =
        URLEncoder.encode(value, Charsets.UTF_8.name()).replace("+", "%20")
}

private fun JSONObject.toRemotePowerStatus(): RemotePowerStatus = RemotePowerStatus(
    configured = optBoolean("configured"),
    status = optString("status", "unknown"),
    supportedActions = optJSONArray("supported_actions")?.toStringSet().orEmpty(),
    targetHost = optString("target_host"),
)

private fun JSONObject.toRemoteReadiness(): RemoteReadiness = RemoteReadiness(
    beholderHealth = optJSONObject("beholder_health").toReadinessSection(),
    remoteConnectivity = optJSONObject("remote_connectivity").toReadinessSection(),
    serverModeReadiness = optJSONObject("server_mode_readiness").toReadinessSection(),
    powerReadiness = optJSONObject("power_readiness").toReadinessSection(),
    tailscaleReadiness = optJSONObject("tailscale_readiness").toReadinessSection(),
)

private fun JSONObject?.toReadinessSection(): ReadinessSection {
    val json = this ?: JSONObject()
    return ReadinessSection(
        state = json.optString("state", "unknown"),
        color = json.optString("color", "gray"),
        message = json.optString("message", "상태 미확인"),
        activeIncidents = json.optInt("active_incidents"),
        authRequired = json.optBoolean("auth_required"),
        supportedActions = json.optJSONArray("supported_actions")?.toStringList().orEmpty(),
        suggestedBaseUrls = json.optJSONArray("suggested_base_urls")?.toStringList().orEmpty(),
        tailscaleDetails = json.optJSONObject("details")?.toTailscaleDetails(),
    )
}

private fun JSONObject.toTailscaleDetails(): TailscaleDetails = TailscaleDetails(
    installed = optBoolean("installed"),
    running = optBoolean("running"),
    backendState = optString("backend_state", "unknown"),
    selfIps = optJSONArray("self_ips")?.toStringList().orEmpty(),
    selfHostname = optString("self_hostname"),
    message = optString("message"),
)

private fun JSONObject.toRemoteLoggingConfig(): RemoteLoggingConfigResponse = RemoteLoggingConfigResponse(
    enabled = optBoolean("enabled"),
    path = optString("path"),
)

private fun JSONObject.toRemoteTailscaleEnsureResponse(): RemoteTailscaleEnsureResponse = RemoteTailscaleEnsureResponse(
    ready = optBoolean("ready"),
    method = optString("method"),
    message = optString("message"),
    installAttempted = optBoolean("install_attempted"),
    launchAttempted = optBoolean("launch_attempted"),
)

private fun JSONObject.toRemotePowerSetupResponse(): RemotePowerSetupResponse {
    val ssh = optJSONObject("ssh_service") ?: JSONObject()
    val firewall = optJSONObject("firewall") ?: JSONObject()
    return RemotePowerSetupResponse(
        hostPlatform = optString("host_platform"),
        user = optString("user"),
        authorizedKeysPath = optString("authorized_keys_path"),
        authorizedKeysExists = optBoolean("authorized_keys_exists"),
        sshService = RemotePowerSetupService(
            available = ssh.optBoolean("available"),
            running = ssh.optBoolean("running"),
            startType = ssh.optString("start_type"),
            message = ssh.optString("message"),
        ),
        firewall = RemotePowerSetupFirewall(
            available = firewall.optBoolean("available"),
            enabled = firewall.optBoolean("enabled"),
            message = firewall.optString("message"),
        ),
        smartthingsCliCandidates = optJSONArray("smartthings_cli_candidates")?.toStringList().orEmpty(),
        smartthingsReady = optBoolean("smartthings_ready"),
        message = optString("message"),
    )
}

private fun JSONObject.toRemoteSSHKeyRegistrationResponse(): RemoteSSHKeyRegistrationResponse = RemoteSSHKeyRegistrationResponse(
    registered = optBoolean("registered"),
    alreadyPresent = optBoolean("already_present"),
    authorizedKeysPath = optString("authorized_keys_path"),
    message = optString("message"),
)

private fun JSONObject.toRemoteSmartThingsDevicesResponse(): RemoteSmartThingsDevicesResponse = RemoteSmartThingsDevicesResponse(
    available = optBoolean("available"),
    devices = optJSONArray("devices")?.toStringList().orEmpty(),
    deviceCandidates = optJSONArray("device_candidates")?.mapObjects { candidate ->
        RemoteSmartThingsDeviceCandidate(
            id = candidate.optString("id"),
            name = candidate.optString("name"),
            raw = candidate.optString("raw"),
        )
    }.orEmpty(),
    message = optString("message"),
    cliPath = optString("cli_path"),
)

private fun JSONObject.toGameLink(): RemoteGameLink = RemoteGameLink(
    id = optString("id"),
    pcProcessId = optString("pc_process_id"),
    pcDisplayName = optString("pc_display_name"),
    androidPackageName = optString("android_package_name"),
    androidLaunchIntentUri = optString("android_launch_intent_uri"),
    androidStoreUrl = optString("android_store_url"),
    platformAccountHint = optString("platform_account_hint"),
    hoyolabGameId = optString("hoyolab_game_id"),
    syncStrategy = optString("sync_strategy", "manual"),
)

private fun JSONObject.toMobileSession(): RemoteMobileSession = RemoteMobileSession(
    id = optString("id"),
    gameLinkId = optString("game_link_id"),
    pcProcessId = optString("pc_process_id"),
    pcDisplayName = optString("pc_display_name"),
    androidPackageName = optString("android_package_name"),
    source = optString("source", "manual"),
    status = optString("status"),
    startedAt = optDouble("started_at"),
    endedAt = optDouble("ended_at"),
    durationSeconds = optDouble("duration_seconds"),
)

private fun JSONObject.toPowerConfigResponse(): RemotePowerConfigResponse {
    val config = optJSONObject("config") ?: JSONObject()
    val readiness = optJSONObject("readiness") ?: JSONObject()
    return RemotePowerConfigResponse(
        configPath = optString("config_path"),
        configExists = optBoolean("config_exists"),
        config = RemotePowerConfigPayload(
            smartthingsDeviceId = config.optString("smartthings_device_id"),
            smartthingsCliPath = config.optString("smartthings_cli_path"),
            sshHost = config.optString("ssh_host"),
            sshPort = config.optInt("ssh_port", 22),
            sshUser = config.optString("ssh_user"),
            sshKeyPath = config.optString("ssh_key_path"),
            statusTimeoutSeconds = config.optDouble("status_timeout_seconds", 4.0),
        ),
        wakeConfigured = readiness.optBoolean("wake_configured"),
        sshConfigured = readiness.optBoolean("ssh_configured"),
        supportedActions = readiness.optJSONArray("supported_actions")?.toStringSet().orEmpty(),
    )
}

private fun JSONObject.toRemoteProcess(): RemoteProcess {
    val progressJson = optJSONObject("progress")
    return RemoteProcess(
        id = optString("id"),
        name = optString("name"),
        preferredLaunchType = optString("preferred_launch_type", "shortcut"),
        monitoringPath = optString("monitoring_path"),
        launchPath = optString("launch_path"),
        lastPlayedTimestamp = optDouble("last_played_timestamp"),
        staminaCurrent = optInt("stamina_current"),
        staminaMax = optInt("stamina_max"),
        iconUrl = optString("icon_url"),
        iconUrls = optJSONObject("icon_urls")?.toStringMap().orEmpty(),
        isRunning = optBoolean("is_running"),
        playedToday = optBoolean("played_today"),
        statusText = optString("status_text"),
        progress = progressJson?.let { progress ->
            RemoteProcessProgress(
                kind = progress.optString("kind"),
                percentage = progress.optDouble("percentage"),
                displayText = progress.optString("display_text"),
                staminaCurrent = progress.optInt("stamina_current"),
                staminaMax = progress.optInt("stamina_max"),
                hoyolabGameId = progress.optString("hoyolab_game_id"),
                resourceIconUrl = progress.optString("resource_icon_url"),
                resourceIconUrls = progress.optJSONObject("resource_icon_urls")?.toStringMap().orEmpty(),
                remainingSeconds = progress.optInt("remaining_seconds"),
                readyAt = progress.optDouble("ready_at"),
            )
        },
    )
}

private fun JSONObject.toPairingResult(): PairingResult = PairingResult(
    id = optString("id"),
    deviceName = optString("name", optString("device_name")),
    platform = optString("platform"),
    token = optString("token"),
)

private fun JSONObject.toRemoteDevice(): RemoteDevice = RemoteDevice(
    id = optString("id"),
    deviceName = optString("name", optString("device_name")),
    platform = optString("platform"),
    tokenRefreshedAt = optString("token_refreshed_at"),
    revokedAt = optString("revoked_at"),
)

private fun <T> JSONArray.mapObjects(transform: (JSONObject) -> T): List<T> = buildList {
    for (index in 0 until length()) {
        optJSONObject(index)?.let { add(transform(it)) }
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

private fun JSONObject.toStringMap(): Map<String, String> = buildMap {
    val iterator = keys()
    while (iterator.hasNext()) {
        val key = iterator.next()
        optString(key).takeIf { it.isNotBlank() }?.let { put(key, it) }
    }
}
