package dev.homeworkhelper.remote

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.io.Closeable

enum class RemoteTab(val label: String, val symbol: String) {
    DASHBOARD("홈", "◆"),
    LIBRARY("게임", "◈"),
    LINKS("연결", "◎"),
    SETTINGS("설정", "◇"),
}

data class RemoteAppState(
    val baseUrl: String,
    val token: String,
    val deviceName: String,
    val pairingCode: String = "",
    val selectedTab: RemoteTab = RemoteTab.DASHBOARD,
    val isLoading: Boolean = false,
    val message: String = "Remote Agent에 연결하세요.",
    val offline: Boolean = false,
    val authRejected: Boolean = false,
    val status: RemoteStatus? = null,
    val capabilities: RemoteCapabilities? = null,
    val readiness: RemoteReadiness? = null,
    val loggingConfig: RemoteLoggingConfigResponse? = null,
    val dashboardSummary: RemoteDashboardSummary? = null,
    val beholderIncidents: List<RemoteBeholderIncident> = emptyList(),
    val gameLinks: List<RemoteGameLink> = emptyList(),
    val mobileSessions: List<RemoteMobileSession> = emptyList(),
    val powerConfig: RemotePowerConfigPayload = RemotePowerConfigPayload(),
    val powerConfigResponse: RemotePowerConfigResponse? = null,
    val powerSetup: RemotePowerSetupResponse? = null,
    val processes: List<RemoteProcess> = emptyList(),
    val shortcuts: List<RemoteShortcut> = emptyList(),
    val devices: List<RemoteDevice> = emptyList(),
    val androidPackageName: String = "",
    val gameLinkProcessId: String = "",
    val gameLinkPackageName: String = "",
    val usageAccessGranted: Boolean = false,
    val recentUsage: AndroidUsageSnapshot? = null,
    val tailscaleInstalled: Boolean = false,
    val showPlaySummary: Boolean = true,
    val refreshIntervalSeconds: Int = 5,
    val progressMode: String = "remaining",
    val smartThingsProbe: RemoteSmartThingsDevicesResponse? = null,
    val sshPublicKey: String = "",
    val partialErrors: List<String> = emptyList(),
    val iconCacheRevision: Int = 0,
) {
    val tokenPresent: Boolean get() = token.isNotBlank()
}

data class UsageSyncResult(
    val usage: AndroidUsageSnapshot?,
    val matchedLink: RemoteGameLink?,
    val started: RemoteMobileSession?,
    val ended: List<RemoteMobileSession>,
)

class RemoteAppViewModel(
    private val preferences: RemotePreferences,
    private val tokenStore: AndroidTokenStore,
    private val androidIntegration: AndroidIntegration,
    private val repository: RemoteRepository = RemoteRepository(),
) : Closeable {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)

    var state by mutableStateOf(initialState())
        private set

    private fun initialState(): RemoteAppState {
        val encryptedToken = tokenStore.token()
        val initialToken = if (encryptedToken.isNotBlank()) {
            encryptedToken
        } else {
            preferences.legacyToken().also { legacyToken ->
                if (legacyToken.isNotBlank()) {
                    tokenStore.saveToken(legacyToken)
                    preferences.clearLegacyToken()
                }
            }
        }
        return RemoteAppState(
            baseUrl = preferences.baseUrl(),
            token = initialToken,
            deviceName = preferences.deviceName(),
            usageAccessGranted = androidIntegration.hasUsageAccess(),
            tailscaleInstalled = androidIntegration.isTailscaleInstalled(),
            showPlaySummary = preferences.showPlaySummary(),
            refreshIntervalSeconds = preferences.refreshIntervalSeconds(),
            progressMode = preferences.progressMode(),
        )
    }

    fun updateBaseUrl(value: String) { state = state.copy(baseUrl = value) }
    fun updateToken(value: String) { state = state.copy(token = value) }
    fun updateDeviceName(value: String) { state = state.copy(deviceName = value) }
    fun updatePairingCode(value: String) { state = state.copy(pairingCode = value.filter(Char::isDigit).take(6)) }
    fun updateSelectedTab(tab: RemoteTab) { state = state.copy(selectedTab = tab) }
    fun updateAndroidPackageName(value: String) { state = state.copy(androidPackageName = value) }
    fun updateGameLinkProcessId(value: String) { state = state.copy(gameLinkProcessId = value) }
    fun updateGameLinkPackageName(value: String) { state = state.copy(gameLinkPackageName = value) }
    fun updateSshPublicKey(value: String) { state = state.copy(sshPublicKey = value) }
    fun updateShowPlaySummary(value: Boolean) { state = state.copy(showPlaySummary = value) }
    fun updateRefreshInterval(value: String) {
        state = state.copy(refreshIntervalSeconds = (value.toIntOrNull() ?: state.refreshIntervalSeconds).coerceIn(1, 60))
    }
    fun updateProgressMode(value: String) { state = state.copy(progressMode = value.ifBlank { "remaining" }) }
    fun updatePowerConfig(config: RemotePowerConfigPayload) { state = state.copy(powerConfig = config) }

    fun saveConnection(nextMessage: String = "설정을 저장했습니다.") {
        persistConnection()
        state = state.copy(message = nextMessage)
    }

    fun saveUiSettings() {
        preferences.saveUiSettings(state.refreshIntervalSeconds, state.showPlaySummary, state.progressMode)
        state = state.copy(message = "표시 설정을 저장했습니다.")
    }

    fun clearLocalToken() {
        tokenStore.clearToken()
        preferences.clearLegacyToken()
        state = state.copy(token = "", authRejected = false, message = "로컬 토큰을 삭제했습니다.")
    }

    fun refresh(includeDevices: Boolean = state.tokenPresent) {
        val current = state
        if (current.baseUrl.isBlank()) {
            state = current.copy(message = "Remote Agent URL을 입력하세요.")
            return
        }
        scope.launch {
            state = state.copy(isLoading = true, offline = false, authRejected = false)
            runCatching {
                withContext(Dispatchers.IO) {
                    repository.fetchSnapshot(current.baseUrl, current.token, includeDevices)
                }
            }.onSuccess { snapshot ->
                persistConnection()
                state = state.copy(
                    isLoading = false,
                    offline = false,
                    authRejected = false,
                    status = snapshot.status,
                    capabilities = snapshot.capabilities,
                    readiness = snapshot.readiness,
                    loggingConfig = snapshot.loggingConfig,
                    dashboardSummary = snapshot.dashboardSummary,
                    beholderIncidents = snapshot.beholderIncidents,
                    gameLinks = snapshot.gameLinks,
                    mobileSessions = snapshot.mobileSessions,
                    powerConfigResponse = snapshot.powerConfig,
                    powerConfig = snapshot.powerConfig?.config ?: state.powerConfig,
                    powerSetup = snapshot.powerSetup,
                    processes = snapshot.processes,
                    shortcuts = snapshot.shortcuts,
                    devices = snapshot.devices,
                    usageAccessGranted = androidIntegration.hasUsageAccess(),
                    tailscaleInstalled = androidIntegration.isTailscaleInstalled(),
                    partialErrors = snapshot.partialErrors,
                    message = refreshMessage(snapshot),
                )
            }.onFailure { failure ->
                state = state.copy(
                    isLoading = false,
                    offline = !failure.isAuthFailure(),
                    authRejected = failure.isAuthFailure(),
                    message = failure.message ?: "연결 실패",
                )
            }
        }
    }

    private fun refreshMessage(snapshot: RemoteSnapshot): String {
        val base = "동기화 완료: 게임 ${snapshot.processes.size}개, 연결 ${snapshot.gameLinks.size}개, 모바일 세션 ${snapshot.mobileSessions.size}개, 숏컷 ${snapshot.shortcuts.size}개"
        return if (snapshot.partialErrors.isEmpty()) base else "$base · 일부 항목 확인 필요 ${snapshot.partialErrors.size}건"
    }

    fun isPowerActionEnabled(action: String): Boolean = state.status?.isPowerActionEnabled(action) == true


    fun launchProcess(process: RemoteProcess) {
        command(refreshAfter = true) { repository.launchProcess(baseUrl, token, process.id) }
    }

    fun openShortcut(shortcut: RemoteShortcut) {
        command(refreshAfter = false) { repository.openShortcut(baseUrl, token, shortcut.id) }
    }

    fun powerCommand(action: String) {
        if (!isPowerActionEnabled(action)) {
            state = state.copy(message = "전원 제어 adapter가 설정되지 않았거나 지원하지 않는 명령입니다.")
            return
        }
        command(refreshAfter = true) { repository.power(baseUrl, token, action) }
    }

    fun savePowerConfig() {
        val current = state
        scope.launch {
            state = state.copy(isLoading = true)
            runCatching {
                withContext(Dispatchers.IO) { repository.savePowerConfig(current.baseUrl, current.token, current.powerConfig) }
            }.onSuccess { response ->
                state = state.copy(
                    isLoading = false,
                    powerConfigResponse = response,
                    powerConfig = response.config,
                    message = "전원 설정을 저장했습니다. 지원 명령: ${if (response.supportedActions.isEmpty()) "없음" else response.supportedActions.joinToString(", ")}",
                )
                refresh(includeDevices = state.tokenPresent)
            }.onFailure { state = state.copy(isLoading = false, message = it.message ?: "전원 설정 저장 실패") }
        }
    }

    fun confirmPairing() {
        val current = state
        if (current.pairingCode.length != 6) {
            state = current.copy(message = "6자리 pairing code를 입력하세요.")
            return
        }
        scope.launch {
            state = state.copy(isLoading = true)
            runCatching {
                withContext(Dispatchers.IO) {
                    repository.confirmPairing(current.baseUrl, current.token, current.pairingCode, current.deviceName)
                }
            }.onSuccess { paired ->
                state = state.copy(token = paired.token, pairingCode = "", isLoading = false)
                persistConnection()
                state = state.copy(message = "${paired.deviceName} 페어링 완료")
                refresh(includeDevices = true)
            }.onFailure { state = state.copy(isLoading = false, authRejected = it.isAuthFailure(), message = it.message ?: "페어링 실패") }
        }
    }

    fun refreshToken() {
        val current = state
        scope.launch {
            state = state.copy(isLoading = true)
            runCatching { withContext(Dispatchers.IO) { repository.refreshToken(current.baseUrl, current.token) } }
                .onSuccess { refreshed ->
                    state = state.copy(token = refreshed.token, isLoading = false)
                    persistConnection()
                    state = state.copy(message = "${refreshed.deviceName} 토큰을 갱신했습니다.")
                    refresh(includeDevices = true)
                }
                .onFailure { state = state.copy(isLoading = false, authRejected = it.isAuthFailure(), message = it.message ?: "토큰 갱신 실패") }
        }
    }

    fun revokeDevice(device: RemoteDevice) {
        command(refreshAfter = true) {
            repository.revokeDevice(baseUrl, token, device.id)
            RemoteCommandResult(true, "device.revoke", "accepted", "${device.deviceName} 토큰을 폐기했습니다.")
        }
    }

    fun purgeRevokedDevices() {
        command(refreshAfter = true) {
            val result = repository.purgeRevokedDevices(baseUrl, token)
            RemoteCommandResult(true, "device.purge", "accepted", "폐기된 디바이스 ${result.removed}개를 정리했습니다.")
        }
    }

    fun activeMobileSession(link: RemoteGameLink): RemoteMobileSession? =
        state.mobileSessions.firstOrNull { it.gameLinkId == link.id && it.status == "active" }

    fun activeUsageStatsMobileSessions(): List<RemoteMobileSession> =
        state.mobileSessions.filter { it.status == "active" && it.source == "usage_stats" }

    fun startMobileSession(link: RemoteGameLink) {
        command(refreshAfter = true) {
            val session = repository.startMobileSession(baseUrl, token, link.id)
            RemoteCommandResult(true, "mobile_session.start", "accepted", "${session.pcDisplayName.ifBlank { session.pcProcessId }} 모바일 세션을 시작했습니다.")
        }
    }

    fun endMobileSession(session: RemoteMobileSession) {
        command(refreshAfter = true) {
            val ended = repository.endMobileSession(baseUrl, token, session.id)
            RemoteCommandResult(true, "mobile_session.end", "accepted", "${ended.pcDisplayName.ifBlank { ended.pcProcessId }} 모바일 세션을 종료했습니다.")
        }
    }

    fun syncUsageStatsSessions() {
        if (!androidIntegration.hasUsageAccess()) {
            state = state.copy(usageAccessGranted = false, message = "Usage Access 권한이 필요합니다.")
            androidIntegration.openUsageAccessSettings()
            return
        }
        val current = state
        scope.launch {
            state = state.copy(isLoading = true)
            runCatching {
                withContext(Dispatchers.IO) {
                    val usage = androidIntegration.recentForegroundApp()
                    val matchedLink = usage?.let { snapshot ->
                        current.gameLinks.firstOrNull { it.androidPackageName == snapshot.packageName }
                    }
                    val activeAutoSessions = current.mobileSessions.filter { it.status == "active" && it.source == "usage_stats" }
                    val ended = activeAutoSessions
                        .filter { matchedLink == null || it.gameLinkId != matchedLink.id }
                        .map { repository.endMobileSession(current.baseUrl, current.token, it.id) }
                    val started = if (matchedLink != null && current.mobileSessions.none { it.gameLinkId == matchedLink.id && it.status == "active" }) {
                        repository.startMobileSession(
                            baseUrl = current.baseUrl,
                            token = current.token,
                            linkId = matchedLink.id,
                            source = "usage_stats",
                            startedAtSeconds = usage?.timestampMillis?.div(1000.0),
                        )
                    } else {
                        null
                    }
                    UsageSyncResult(usage, matchedLink, started, ended)
                }
            }.onSuccess { result ->
                state = state.copy(
                    isLoading = false,
                    usageAccessGranted = true,
                    recentUsage = result.usage,
                    message = when {
                        result.started != null -> "${result.started.pcDisplayName.ifBlank { result.started.pcProcessId }} UsageStats 세션을 시작했습니다."
                        result.ended.isNotEmpty() -> "UsageStats 자동 세션 ${result.ended.size}개를 종료했습니다."
                        result.matchedLink != null -> "${result.matchedLink.androidPackageName} 세션이 이미 동기화되어 있습니다."
                        result.usage != null -> "최근 전면 앱 ${result.usage.packageName}에 연결된 game-link가 없습니다."
                        else -> "최근 전면 앱을 찾지 못했습니다."
                    },
                )
                refresh(includeDevices = state.tokenPresent)
            }.onFailure { state = state.copy(isLoading = false, message = it.message ?: "UsageStats 세션 동기화 실패") }
        }
    }

    fun probeRecentUsage() {
        val granted = androidIntegration.hasUsageAccess()
        val usage = if (granted) androidIntegration.recentForegroundApp() else null
        state = state.copy(
            usageAccessGranted = granted,
            recentUsage = usage,
            message = usage?.let { "최근 전면 앱: ${it.packageName}" } ?: "Usage Access 권한이 없거나 최근 전면 앱을 찾지 못했습니다.",
        )
    }

    fun createGameLink() {
        val processId = state.gameLinkProcessId.trim()
        val packageName = state.gameLinkPackageName.trim()
        if (processId.isBlank() || packageName.isBlank()) {
            state = state.copy(message = "PC process ID와 Android package name을 입력하세요.")
            return
        }
        command(refreshAfter = true) {
            val link = repository.createGameLink(baseUrl, token, processId, packageName)
            RemoteCommandResult(true, "game_link.create", "accepted", "${link.pcDisplayName.ifBlank { link.pcProcessId }}와 ${link.androidPackageName} 연결을 저장했습니다.")
        }
        state = state.copy(gameLinkPackageName = "")
    }

    fun launchAndroidPackage(packageName: String = state.androidPackageName) {
        val ok = androidIntegration.launchPackage(packageName)
        state = state.copy(message = if (ok) "$packageName 실행 요청" else "Android 패키지 실행 실패")
    }

    fun openUsageAccessSettings() = androidIntegration.openUsageAccessSettings()

    fun openAppSettings() = androidIntegration.openAppSettings()

    fun clearIconCache() {
        state = state.copy(iconCacheRevision = state.iconCacheRevision + 1, message = "아이콘 캐시를 새로고침합니다.")
    }

    fun openTailscale() {
        val ok = androidIntegration.openTailscaleOrStore()
        state = state.copy(
            tailscaleInstalled = androidIntegration.isTailscaleInstalled(),
            message = if (ok) "Tailscale 앱을 열었습니다." else "Tailscale 앱 또는 Play Store를 열 수 없습니다.",
        )
    }

    fun ensureServerTailscale() {
        command(refreshAfter = true) {
            val result = repository.ensureServerTailscale(baseUrl, token)
            RemoteCommandResult(result.ready, "tailscale.ensure", if (result.ready) "ready" else "not_ready", result.message)
        }
    }

    fun saveRemoteLogging(enabled: Boolean) {
        val current = state
        scope.launch {
            state = state.copy(isLoading = true)
            runCatching {
                withContext(Dispatchers.IO) { repository.saveRemoteLogging(current.baseUrl, current.token, enabled) }
            }.onSuccess { config ->
                state = state.copy(isLoading = false, loggingConfig = config, message = if (config.enabled) "Remote diagnostic logging을 켰습니다." else "Remote diagnostic logging을 껐습니다.")
            }.onFailure { state = state.copy(isLoading = false, message = it.message ?: "로깅 설정 실패") }
        }
    }

    fun probeSmartThingsDevices() {
        val current = state
        scope.launch {
            state = state.copy(isLoading = true)
            runCatching {
                withContext(Dispatchers.IO) { repository.smartThingsDevices(current.baseUrl, current.token, current.powerConfig.smartthingsCliPath) }
            }.onSuccess { response ->
                state = state.copy(isLoading = false, smartThingsProbe = response, message = response.message.ifBlank { "SmartThings device ${response.deviceCandidates.size}개를 확인했습니다." })
            }.onFailure { state = state.copy(isLoading = false, message = it.message ?: "SmartThings device 확인 실패") }
        }
    }

    fun registerPowerSshKey() {
        val publicKey = state.sshPublicKey.trim()
        if (publicKey.isBlank()) {
            state = state.copy(message = "등록할 SSH public key를 입력하세요.")
            return
        }
        val current = state
        scope.launch {
            state = state.copy(isLoading = true)
            runCatching {
                withContext(Dispatchers.IO) { repository.registerPowerSshKey(current.baseUrl, current.token, publicKey, current.deviceName) }
            }.onSuccess { response ->
                state = state.copy(isLoading = false, sshPublicKey = "", message = response.message.ifBlank { "SSH public key 등록 상태를 확인했습니다." })
                refresh(includeDevices = state.tokenPresent)
            }.onFailure { state = state.copy(isLoading = false, message = it.message ?: "SSH key 등록 실패") }
        }
    }

    private fun command(refreshAfter: Boolean = false, block: RemoteAppState.() -> RemoteCommandResult) {
        val current = state
        scope.launch {
            state = state.copy(isLoading = true)
            runCatching { withContext(Dispatchers.IO) { current.block() } }
                .onSuccess { result ->
                    state = state.copy(isLoading = false, message = result.message.ifBlank { result.status })
                    if (refreshAfter) refresh(includeDevices = state.tokenPresent)
                }
                .onFailure { state = state.copy(isLoading = false, authRejected = it.isAuthFailure(), offline = !it.isAuthFailure(), message = it.message ?: "명령 실패") }
        }
    }

    private fun persistConnection() {
        preferences.saveConnection(state.baseUrl, state.deviceName)
        tokenStore.saveToken(state.token)
        preferences.clearLegacyToken()
    }

    override fun close() {
        scope.cancel()
    }
}

private fun Throwable.isAuthFailure(): Boolean = message?.contains("HTTP 401") == true

fun formatDuration(seconds: Double): String {
    val minutes = (seconds / 60).toInt()
    if (minutes < 60) return "${minutes}분"
    val hours = minutes / 60
    val remainder = minutes % 60
    return if (remainder == 0) "${hours}시간" else "${hours}시간 ${remainder}분"
}
