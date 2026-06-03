package dev.homeworkhelper.remote.state

import android.content.Context
import android.os.Build
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import dev.homeworkhelper.remote.BuildConfig
import dev.homeworkhelper.remote.data.RemoteApiException
import dev.homeworkhelper.remote.data.RemoteAvailability
import dev.homeworkhelper.remote.data.RemoteDevice
import dev.homeworkhelper.remote.data.RemotePowerReadiness
import dev.homeworkhelper.remote.data.RemoteProcess
import dev.homeworkhelper.remote.data.RemoteRepository
import dev.homeworkhelper.remote.data.SMARTTHINGS_DEFAULT_WAKE_LABEL
import dev.homeworkhelper.remote.data.SmartThingsClient
import dev.homeworkhelper.remote.data.SmartThingsDeviceCandidate
import dev.homeworkhelper.remote.data.selectSmartThingsWakeDevice
import dev.homeworkhelper.remote.platform.AndroidSSHKeyStore
import dev.homeworkhelper.remote.platform.AndroidSSHPowerManager
import dev.homeworkhelper.remote.platform.AndroidTokenStore
import dev.homeworkhelper.remote.platform.AutomationPreferences
import dev.homeworkhelper.remote.platform.PowerAction
import dev.homeworkhelper.remote.platform.RemoteNetworkControllers
import dev.homeworkhelper.remote.platform.RemoteNetworkSocketFactory
import dev.homeworkhelper.remote.platform.RemoteNetworkState
import dev.homeworkhelper.remote.platform.RemoteNetworkStatus
import dev.homeworkhelper.remote.platform.RemotePreferences
import dev.homeworkhelper.remote.platform.SmartThingsPreferences
import dev.homeworkhelper.remote.platform.SshPowerPreferences
import dev.homeworkhelper.remote.platform.TailscaleAutomationPreferences
import dev.homeworkhelper.remote.platform.TailscaleBinding
import dev.homeworkhelper.remote.platform.TailscaleBindingState
import dev.homeworkhelper.remote.platform.TokenStore
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.net.URI
import java.text.DateFormat
import java.util.Date

private const val TAILSCALE_CONNECT_TIMEOUT_MILLIS = 15_000L
private const val TAILSCALE_CONNECT_POLL_MILLIS = 1_000L
private const val TAILSCALE_CONNECT_MAX_ATTEMPTS = 3
private const val TAILSCALE_CONNECT_RETRY_DELAY_MILLIS = 1_500L
private const val TAILSCALE_FOREGROUND_CONNECT_DELAY_MILLIS = 1_000L
private const val REMOTE_AGENT_SCHEME = "http"
private const val REMOTE_AGENT_PORT = 8000
private val URL_SCHEME_PATTERN = Regex("^[A-Za-z][A-Za-z0-9+.-]*://")
private val IPV4_PATTERN = Regex("""^\d{1,3}(?:\.\d{1,3}){3}$""")

internal data class RemoteBaseUrlPolicy(
    val allowed: Boolean,
    val message: String,
)

internal fun normalizeRemoteBaseUrl(value: String): String {
    val trimmed = value.trim().trimEnd('/')
    if (trimmed.isBlank()) return ""
    val withScheme = if (URL_SCHEME_PATTERN.containsMatchIn(trimmed)) trimmed else "$REMOTE_AGENT_SCHEME://$trimmed"
    val uri = runCatching { URI(withScheme) }.getOrNull() ?: return withScheme
    val host = uri.host?.trim().orEmpty()
    if (host.isBlank()) return withScheme
    val scheme = uri.scheme.ifBlank { REMOTE_AGENT_SCHEME }
    val port = uri.port
    val displayHost = if (host.contains(":") && !host.startsWith("[")) "[$host]" else host
    val path = uri.rawPath?.takeIf { it.isNotBlank() && it != "/" }.orEmpty()
    val query = uri.rawQuery?.takeIf { it.isNotBlank() }?.let { "?$it" }.orEmpty()
    val authority = if (port > 0) {
        "$displayHost:$port"
    } else if (scheme.lowercase() == "https") {
        displayHost
    } else {
        "$displayHost:$REMOTE_AGENT_PORT"
    }
    return "$scheme://$authority$path$query"
}

internal fun remoteHostInputFromBaseUrl(baseUrl: String): String {
    return normalizeRemoteBaseUrl(baseUrl)
}

internal fun validateRemoteBaseUrlPolicy(baseUrl: String): RemoteBaseUrlPolicy {
    val normalized = normalizeRemoteBaseUrl(baseUrl)
    if (normalized.isBlank()) return RemoteBaseUrlPolicy(true, "")
    val uri = runCatching { URI(normalized) }.getOrNull()
        ?: return RemoteBaseUrlPolicy(false, "Remote Agent URL 형식이 올바르지 않습니다.")
    val scheme = uri.scheme?.lowercase().orEmpty()
    val host = uri.host?.trim().orEmpty()
    if (scheme == "https") {
        return RemoteBaseUrlPolicy(true, "Public HTTPS 직접접속 URL입니다.")
    }
    if (scheme == "http" && isPrivateRemoteHost(host)) {
        return RemoteBaseUrlPolicy(true, "Private HTTP 경로입니다. LAN, loopback, Tailscale 같은 사설망에서만 사용하세요.")
    }
    if (scheme == "http") {
        return RemoteBaseUrlPolicy(false, "Public HTTP는 허용하지 않습니다. 외부 접속은 라우터/프록시에서 HTTPS로 종료한 URL을 사용하세요.")
    }
    return RemoteBaseUrlPolicy(false, "Remote Agent URL은 http 또는 https만 지원합니다.")
}

private fun isPrivateRemoteHost(host: String): Boolean {
    val normalized = host.trim().trim('[', ']').lowercase()
    if (normalized in setOf("localhost", "testclient")) return true
    if (normalized.endsWith(".local")) return true
    if (normalized.contains(":") && (
            normalized == "::1" ||
                normalized.startsWith("fe80:") ||
                normalized.startsWith("fc") ||
                normalized.startsWith("fd")
            )
    ) {
        return true
    }
    if (!IPV4_PATTERN.matches(normalized)) return false
    val octets = normalized.split(".").mapNotNull { it.toIntOrNull() }
    if (octets.size != 4 || octets.any { it !in 0..255 }) return false
    val first = octets[0]
    val second = octets[1]
    return first == 10 ||
        first == 127 ||
        first == 192 && second == 168 ||
        first == 172 && second in 16..31 ||
        first == 169 && second == 254 ||
        first == 100 && second in 64..127
}

data class AutomationUiState(
    val remoteNetwork: RemoteNetworkState = RemoteNetworkState(),
    val tailscale: TailscaleBindingState = TailscaleBindingState(),
    val tailscaleAutomation: TailscaleAutomationPreferences = TailscaleAutomationPreferences(),
    val ssh: SshPowerPreferences = SshPowerPreferences(),
    val smartThings: SmartThingsPreferences = SmartThingsPreferences(),
    val isRemoteNetworkBusy: Boolean = false,
    val smartThingsCandidates: List<SmartThingsDeviceCandidate> = emptyList(),
    val isTailscaleBusy: Boolean = false,
    val isSshBusy: Boolean = false,
    val isSmartThingsBusy: Boolean = false,
    val powerActionInFlight: PowerAction? = null,
) {
    val sshReady: Boolean
        get() = ssh.publicKey.isNotBlank() && ssh.healthOk && ssh.host.isNotBlank() && ssh.user.isNotBlank()

    val wakeReady: Boolean
        get() = smartThings.hasPat && smartThings.deviceId.isNotBlank()
}

data class RemoteUiState(
    val baseUrl: String = "",
    val deviceName: String = "",
    val hasToken: Boolean = false,
    val availability: RemoteAvailability = RemoteAvailability.Unknown,
    val isRefreshing: Boolean = false,
    val isPairing: Boolean = false,
    val launchInFlightId: String? = null,
    val stopInFlightId: String? = null,
    val processes: List<RemoteProcess> = emptyList(),
    val devices: List<RemoteDevice> = emptyList(),
    val isDevicesBusy: Boolean = false,
    val hostMessage: String? = null,
    val userMessage: String? = null,
    val lastSyncMillis: Long = 0L,
    val lastStateRevision: String? = null,
    val processLaunchEnabled: Boolean = false,
    val processStopEnabled: Boolean = false,
    val showDiagnostics: Boolean = false,
    val powerReadiness: RemotePowerReadiness? = null,
    val setupRepairInFlight: Boolean = false,
    val baseUrlSecurityMessage: String = "",
    val baseUrlAllowed: Boolean = true,
    val automation: AutomationUiState = AutomationUiState(),
) {
    val canRefresh: Boolean
        get() = baseUrl.isNotBlank() && baseUrlAllowed && !isRefreshing

    val lastSyncLabel: String
        get() = if (lastSyncMillis <= 0L) {
            "아직 동기화되지 않음"
        } else {
            DateFormat.getTimeInstance(DateFormat.SHORT).format(Date(lastSyncMillis))
        }
}

class RemoteViewModel(
    context: Context,
    private val preferences: RemotePreferences = RemotePreferences(context.applicationContext),
    private val tokenStore: TokenStore = AndroidTokenStore(context.applicationContext),
    private val automationPreferences: AutomationPreferences = AutomationPreferences(context.applicationContext),
) : ViewModel() {
    private val appContext = context.applicationContext
    private val remoteNetworkController = RemoteNetworkControllers.create(appContext)
    private val tailscaleBinding = TailscaleBinding(appContext)
    private val sshKeyStore = AndroidSSHKeyStore(automationPreferences)
    private val sshPowerManager = AndroidSSHPowerManager(
        automationPreferences,
        RemoteNetworkSocketFactory(remoteNetworkController),
    )
    private val smartThingsPatSeeded = automationPreferences.seedSmartThingsPatFromBuildConfig()
    private var autoSshAttemptSignature: String? = null
    private var tailscaleConnectSequence: Int = 0
    private val storedBaseUrlAtLaunch = preferences.baseUrl
    private val defaultRemoteBaseUrl = normalizeRemoteBaseUrl(BuildConfig.DEFAULT_REMOTE_BASE_URL)
    private val initialBaseUrl = normalizeRemoteBaseUrl(storedBaseUrlAtLaunch.ifBlank { defaultRemoteBaseUrl })
    private val defaultRemoteBaseUrlApplied = storedBaseUrlAtLaunch.isBlank() && initialBaseUrl.isNotBlank()

    init {
        if (initialBaseUrl != storedBaseUrlAtLaunch) {
            preferences.baseUrl = initialBaseUrl
        }
    }

    private val _uiState = MutableStateFlow(
        RemoteUiState(
            baseUrl = initialBaseUrl,
            deviceName = preferences.deviceName.ifBlank { defaultDeviceName() },
            hasToken = tokenStore.loadToken() != null,
            processes = preferences.cachedProcesses(),
            lastSyncMillis = preferences.lastSyncMillis,
            showDiagnostics = preferences.showDiagnostics,
            userMessage = initialUserMessage(),
            baseUrlSecurityMessage = validateRemoteBaseUrlPolicy(initialBaseUrl).message,
            baseUrlAllowed = validateRemoteBaseUrlPolicy(initialBaseUrl).allowed,
            automation = AutomationUiState(
                remoteNetwork = remoteNetworkController.initialState,
                tailscale = tailscaleBinding.inspect(),
                tailscaleAutomation = automationPreferences.loadTailscaleAutomation(),
                ssh = automationPreferences.loadSsh(),
                smartThings = automationPreferences.loadSmartThings(),
            ),
        )
    )
    val uiState: StateFlow<RemoteUiState> = _uiState.asStateFlow()

    fun onAppForeground() {
        updateAutomation { it.copy(tailscale = tailscaleBinding.inspect()) }
        viewModelScope.launch {
            val state = remoteNetworkController.inspect()
            updateAutomation { it.copy(remoteNetwork = state) }
        }
        if (_uiState.value.automation.tailscaleAutomation.connectOnAppForeground) {
            requestTailscaleConnect(
                "앱 실행",
                refreshWhenReady = true,
                initialDelayMillis = TAILSCALE_FOREGROUND_CONNECT_DELAY_MILLIS,
            )
        } else if (_uiState.value.baseUrl.isNotBlank()) {
            refresh()
        }
    }

    fun onAppBackground() {
        val tailscaleAutomation = _uiState.value.automation.tailscaleAutomation
        if (tailscaleAutomation.sleepSafeMode) {
            return
        }
        if (tailscaleAutomation.disconnectOnAppBackground) {
            requestTailscaleDisconnect("앱 종료")
        }
    }

    fun updateBaseUrl(value: String) {
        val normalized = normalizeRemoteBaseUrl(value)
        val policy = validateRemoteBaseUrlPolicy(normalized)
        preferences.baseUrl = normalized
        _uiState.update {
            it.copy(
                baseUrl = normalized,
                baseUrlSecurityMessage = policy.message,
                baseUrlAllowed = policy.allowed,
                userMessage = if (policy.allowed) null else policy.message,
            )
        }
        repairSshDefaults(reason = "URL 변경")
    }

    fun updateDeviceName(value: String) {
        preferences.deviceName = value
        _uiState.update { it.copy(deviceName = value, userMessage = null) }
    }

    fun updateShowDiagnostics(value: Boolean) {
        preferences.showDiagnostics = value
        _uiState.update { it.copy(showDiagnostics = value) }
    }

    fun inspectRemoteNetwork() {
        viewModelScope.launch {
            val state = remoteNetworkController.inspect()
            updateAutomation { it.copy(remoteNetwork = state) }
            _uiState.update { it.copy(userMessage = state.message) }
        }
    }

    fun ensureRemoteNetworkFromUi() {
        viewModelScope.launch {
            val ready = ensureRemoteNetwork("수동 확인")
            if (ready) {
                _uiState.update { it.copy(userMessage = _uiState.value.automation.remoteNetwork.message) }
            }
        }
    }

    fun updateTailscaleConnectOnForeground(value: Boolean) {
        automationPreferences.tailscaleConnectOnAppForeground = value
        updateAutomation { it.copy(tailscaleAutomation = automationPreferences.loadTailscaleAutomation()) }
        _uiState.update { it.copy(userMessage = if (value) "앱 실행 시 Tailscale CONNECT_VPN 자동화를 시도합니다." else "앱 실행 시 Tailscale 자동 연결을 껐습니다.") }
    }

    fun updateTailscaleDisconnectOnBackground(value: Boolean) {
        automationPreferences.tailscaleDisconnectOnAppBackground = value
        updateAutomation { it.copy(tailscaleAutomation = automationPreferences.loadTailscaleAutomation()) }
        val sleepSafeMode = automationPreferences.tailscaleSleepSafeMode
        val message = when {
            value && sleepSafeMode -> "앱 종료 시 Tailscale OFF 요청을 저장했지만 Sleep-safe가 켜져 있어 실제 종료 시에는 실행하지 않습니다."
            value -> "앱 종료 시 Tailscale DISCONNECT_VPN 자동화를 시도합니다. sleep/wake 후 자동 ON이 실패할 수 있습니다."
            else -> "앱 종료 시 Tailscale 자동 비활성화를 껐습니다."
        }
        _uiState.update { it.copy(userMessage = message) }
    }

    fun updateTailscaleSleepSafeMode(value: Boolean) {
        automationPreferences.tailscaleSleepSafeMode = value
        updateAutomation { it.copy(tailscaleAutomation = automationPreferences.loadTailscaleAutomation()) }
        _uiState.update {
            it.copy(
                userMessage = if (value) {
                    "Sleep-safe가 켜졌습니다. 앱 종료 시 Tailscale OFF 요청을 보내지 않아 sleep/wake 연결 유지성을 우선합니다."
                } else {
                    "Sleep-safe를 껐습니다. 앱 종료 OFF가 켜져 있으면 sleep/wake 후 Tailscale broadcast 자동 ON이 실패할 수 있습니다."
                },
            )
        }
    }

    fun updateSshHost(value: String) {
        if (automationPreferences.sshHost != value.trim()) resetSshHealthTrust()
        automationPreferences.sshHost = value
        updateAutomation { it.copy(ssh = automationPreferences.loadSsh()) }
    }

    fun updateSshUser(value: String) {
        if (automationPreferences.sshUser != value.trim()) resetSshHealthTrust(resetFingerprint = false)
        automationPreferences.sshUser = value
        updateAutomation { it.copy(ssh = automationPreferences.loadSsh()) }
    }

    fun updateSshPort(value: String) {
        val port = value.toIntOrNull() ?: return
        if (automationPreferences.sshPort != port) resetSshHealthTrust()
        automationPreferences.sshPort = port
        updateAutomation { it.copy(ssh = automationPreferences.loadSsh()) }
    }

    fun updateManualSmartThingsDevice(value: String) {
        automationPreferences.smartThingsDeviceId = value
        if (value.isBlank()) {
            automationPreferences.smartThingsDeviceLabel = ""
            automationPreferences.smartThingsLocationId = ""
            automationPreferences.smartThingsLastVerifiedMillis = 0L
        }
        updateAutomation { it.copy(smartThings = automationPreferences.loadSmartThings()) }
        _uiState.update { it.copy(userMessage = "SmartThings deviceId를 수동 저장했습니다.") }
    }

    fun saveSmartThingsPat(value: String) {
        val token = value.trim()
        if (token.isBlank()) {
            _uiState.update { it.copy(userMessage = "SmartThings PAT를 입력하세요. deviceId만으로는 Cloud 명령을 보낼 수 없습니다.") }
            return
        }
        automationPreferences.saveSmartThingsPat(token)
        updateAutomation { it.copy(smartThings = automationPreferences.loadSmartThings()) }
        _uiState.update { it.copy(userMessage = "SmartThings PAT를 저장했습니다. 저장된 deviceId로 Wake를 실행할 수 있습니다.") }
    }

    fun refresh() {
        refreshWithMessage()
    }

    private fun refreshWithMessage(successMessage: String? = null) {
        val baseUrl = _uiState.value.baseUrl.trim()
        if (baseUrl.isBlank()) {
            _uiState.update {
                it.copy(
                    availability = RemoteAvailability.Unknown,
                    userMessage = "Remote Agent URL을 먼저 입력하세요.",
                )
            }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(isRefreshing = true, userMessage = successMessage) }
            if (!ensureRemoteNetwork("게임 목록 동기화")) {
                _uiState.update { it.copy(isRefreshing = false) }
                return@launch
            }
            runCatching { repository().fetchHomeSnapshot() }
                .onSuccess { snapshot ->
                    val now = System.currentTimeMillis()
                    preferences.cachedProcessesJson = snapshot.rawProcessesJson
                    preferences.lastSyncMillis = now
                    applyPowerDefaults(snapshot.powerReadiness)
                    _uiState.update {
                        it.copy(
                            availability = RemoteAvailability.Online,
                            isRefreshing = false,
                            processes = snapshot.processes,
                            hostMessage = snapshot.readiness?.remoteConnectivity?.message
                                ?: snapshot.readiness?.serverModeReadiness?.message,
                            userMessage = successMessage ?: "게임 목록을 동기화했습니다.",
                            lastSyncMillis = now,
                            lastStateRevision = snapshot.status.stateRevision,
                            hasToken = tokenStore.loadToken() != null,
                            processLaunchEnabled = snapshot.status.processLaunch,
                            processStopEnabled = snapshot.status.processStop,
                            powerReadiness = snapshot.powerReadiness,
                            automation = it.automation.copy(
                                ssh = automationPreferences.loadSsh(),
                                tailscale = inspectTailscalePreservingDiagnostics(it.automation.tailscale),
                            ),
                        )
                    }
                    maybeAutoCompleteSshAutomation("온라인 동기화 후")
                }
                .onFailure { error -> applyFailure(error) }
        }
    }

    fun pair(code: String) {
        val baseUrl = _uiState.value.baseUrl.trim()
        val deviceName = _uiState.value.deviceName.trim().ifBlank { defaultDeviceName() }
        if (baseUrl.isBlank() || code.trim().length != 6) {
            _uiState.update { it.copy(userMessage = "Remote Agent URL과 6자리 페어링 코드를 입력하세요.") }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(isPairing = true, userMessage = null) }
            if (!ensureRemoteNetwork("페어링")) {
                _uiState.update { it.copy(isPairing = false) }
                return@launch
            }
            runCatching { repository(tokenOverride = null).confirmPairing(code.trim(), deviceName) }
                .onSuccess { response ->
                    preferences.deviceName = response.name.ifBlank { deviceName }
                    tokenStore.saveToken(response.token)
                    val pairedName = response.name.ifBlank { deviceName }
                    _uiState.update {
                        it.copy(
                            isPairing = false,
                            deviceName = pairedName,
                            hasToken = true,
                            userMessage = "페어링 성공: $pairedName 등록 완료. 게임 목록을 동기화합니다.",
                        )
                    }
                    refreshDevices(updateMessage = false)
                    refreshWithMessage("페어링 성공: $pairedName 등록 완료. 게임 목록을 동기화했습니다.")
                }
                .onFailure { error ->
                    _uiState.update { it.copy(isPairing = false) }
                    applyFailure(error)
                }
        }
    }

    fun refreshDevices(updateMessage: Boolean = true) {
        if (tokenStore.loadToken().isNullOrBlank()) {
            if (updateMessage) _uiState.update { it.copy(userMessage = "기기 목록을 보려면 먼저 페어링하세요.") }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(isDevicesBusy = true) }
            if (!ensureRemoteNetwork("기기 목록 조회")) {
                _uiState.update { it.copy(isDevicesBusy = false) }
                return@launch
            }
            runCatching { repository().devices() }
                .onSuccess { devices ->
                    _uiState.update {
                        it.copy(
                            devices = devices,
                            isDevicesBusy = false,
                            userMessage = if (updateMessage) "등록 기기 ${devices.size}개를 불러왔습니다." else it.userMessage,
                        )
                    }
                }
                .onFailure { error ->
                    _uiState.update { it.copy(isDevicesBusy = false, userMessage = error.message ?: "기기 목록 조회 실패") }
                }
        }
    }

    fun revokeDevice(device: RemoteDevice) {
        if (!device.canRevoke) {
            _uiState.update { it.copy(userMessage = "이 기기는 Android에서 revoke할 수 없습니다.") }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(isDevicesBusy = true, userMessage = null) }
            if (!ensureRemoteNetwork("기기 revoke")) {
                _uiState.update { it.copy(isDevicesBusy = false) }
                return@launch
            }
            runCatching { repository().revokeDevice(device.id) }
                .onSuccess { response ->
                    _uiState.update { it.copy(isDevicesBusy = false, userMessage = if (response.revoked) "'${device.name}' 기기를 revoke했습니다." else "기기 revoke 결과를 확인할 수 없습니다.") }
                    refreshDevices(updateMessage = false)
                }
                .onFailure { error ->
                    _uiState.update { it.copy(isDevicesBusy = false, userMessage = error.message ?: "기기 revoke 실패") }
                }
        }
    }

    fun purgeRevokedDevices() {
        viewModelScope.launch {
            _uiState.update { it.copy(isDevicesBusy = true, userMessage = null) }
            if (!ensureRemoteNetwork("폐기 기기 정리")) {
                _uiState.update { it.copy(isDevicesBusy = false) }
                return@launch
            }
            runCatching { repository().purgeRevokedDevices() }
                .onSuccess { response ->
                    _uiState.update { it.copy(isDevicesBusy = false, userMessage = "폐기된 기기 ${response.removed}개를 정리했습니다.") }
                    refreshDevices(updateMessage = false)
                }
                .onFailure { error ->
                    _uiState.update { it.copy(isDevicesBusy = false, userMessage = error.message ?: "폐기 기기 정리 실패") }
                }
        }
    }

    fun launch(process: RemoteProcess) {
        if (process.isRunning) {
            _uiState.update { it.copy(userMessage = "이미 실행 중인 게임입니다. 중단 버튼을 사용하세요.") }
            return
        }
        if (_uiState.value.availability != RemoteAvailability.Online) {
            _uiState.update { it.copy(userMessage = "호스트가 online일 때만 실행할 수 있습니다.") }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(launchInFlightId = process.id, userMessage = null) }
            if (!ensureRemoteNetwork("게임 실행")) {
                _uiState.update { it.copy(launchInFlightId = null) }
                return@launch
            }
            runCatching { repository().launchProcess(process.id) }
                .onSuccess { result ->
                    _uiState.update {
                        it.copy(
                            launchInFlightId = null,
                            userMessage = if (result.accepted) result.message else "실행 요청이 거부되었습니다: ${result.message}",
                        )
                    }
                    if (result.accepted) startCommandChase(result.refreshAfterMs, result.message)
                }
                .onFailure { error ->
                    _uiState.update { it.copy(launchInFlightId = null) }
                    applyFailure(error)
                }
        }
    }

    fun stop(process: RemoteProcess) {
        if (!process.isRunning) {
            _uiState.update { it.copy(userMessage = "현재 실행 중인 게임이 아닙니다.") }
            return
        }
        if (_uiState.value.availability != RemoteAvailability.Online) {
            _uiState.update { it.copy(userMessage = "호스트가 online일 때만 게임 중단을 요청할 수 있습니다.") }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(stopInFlightId = process.id, userMessage = null) }
            if (!ensureRemoteNetwork("게임 중단")) {
                _uiState.update { it.copy(stopInFlightId = null) }
                return@launch
            }
            runCatching { repository().stopProcess(process.id) }
                .onSuccess { result ->
                    _uiState.update {
                        it.copy(
                            stopInFlightId = null,
                            userMessage = if (result.accepted) result.message else "중단 요청이 거부되었습니다: ${result.message}",
                        )
                    }
                    if (result.accepted) startCommandChase(result.refreshAfterMs, result.message)
                }
                .onFailure { error ->
                    _uiState.update { it.copy(stopInFlightId = null) }
                    applyFailure(error)
                }
        }
    }

    private fun startCommandChase(refreshAfterMs: Int?, message: String) {
        viewModelScope.launch {
            val delays = listOf((refreshAfterMs ?: 750).coerceIn(250, 3000), 1_250, 2_000)
            delays.forEach { delayMs ->
                delay(delayMs.toLong())
                refreshWithMessage(message)
            }
        }
    }

    fun inspectTailscale() {
        updateAutomation { it.copy(tailscale = tailscaleBinding.inspect()) }
        _uiState.update { it.copy(userMessage = it.automation.tailscale.message) }
    }

    fun requestTailscaleConnect(trigger: String = "수동") {
        requestTailscaleConnect(trigger, refreshWhenReady = false, initialDelayMillis = 0L)
    }

    fun requestTailscaleDisconnect(trigger: String = "수동") {
        tailscaleConnectSequence += 1
        updateAutomation { it.copy(isTailscaleBusy = false, tailscale = tailscaleBinding.requestVpnDisconnect()) }
        val warning = if (trigger == "수동") {
            " sleep/wake 후 Tailscale 앱이 standby 상태가 되면 자동 ON broadcast를 받지 못할 수 있습니다."
        } else {
            ""
        }
        _uiState.update { it.copy(userMessage = "$trigger Tailscale DISCONNECT_VPN 자동화를 요청했습니다.$warning") }
    }

    fun openTailscaleApp() {
        val opened = tailscaleBinding.openTailscaleApp()
        _uiState.update { it.copy(userMessage = if (opened) "Tailscale 앱을 열었습니다." else "Tailscale 앱을 찾지 못했습니다.") }
    }

    fun openTailscaleInstallPage() {
        tailscaleBinding.openInstallPage()
        _uiState.update { it.copy(userMessage = "Tailscale 설치 페이지를 열었습니다.") }
    }

    fun openTailscaleAppSettings() {
        val opened = tailscaleBinding.openTailscaleAppSettings()
        _uiState.update { it.copy(userMessage = if (opened) "Tailscale 앱 설정을 열었습니다. 배터리 제한 없음/절전 예외를 권장합니다." else "Tailscale 앱 설정을 열지 못했습니다.") }
    }

    fun openVpnSettings() {
        val opened = tailscaleBinding.openVpnSettings()
        _uiState.update { it.copy(userMessage = if (opened) "Android VPN 설정을 열었습니다. 필요하면 Always-on VPN을 Tailscale로 설정하세요." else "Android VPN 설정을 열지 못했습니다.") }
    }

    fun checkClientTailscaleAndRefresh() {
        requestTailscaleConnect("클라이언트 확인", refreshWhenReady = true, initialDelayMillis = 0L)
    }

    private fun requestTailscaleConnect(trigger: String, refreshWhenReady: Boolean, initialDelayMillis: Long) {
        val sequence = ++tailscaleConnectSequence
        val inspected = tailscaleBinding.inspect()
        updateAutomation { it.copy(isTailscaleBusy = inspected.installed && !inspected.vpnActive, tailscale = inspected) }
        if (!inspected.installed) {
            _uiState.update { it.copy(userMessage = inspected.message) }
            return
        }
        if (inspected.vpnActive) {
            updateAutomation { it.copy(isTailscaleBusy = false, tailscale = inspected) }
            if (refreshWhenReady && _uiState.value.baseUrl.trim().isNotBlank()) {
                refreshWithMessage("Tailscale이 이미 활성 상태라 게임 목록을 동기화했습니다.")
            } else {
                _uiState.update { it.copy(userMessage = "Android-local Tailscale VPN이 이미 활성 상태입니다.") }
            }
            return
        }
        val delayMessage = if (initialDelayMillis > 0L) " ${initialDelayMillis / 1000.0}초 후" else ""
        _uiState.update { it.copy(userMessage = "$trigger Tailscale CONNECT_VPN 자동화를$delayMessage 시작합니다.") }
        viewModelScope.launch {
            if (initialDelayMillis > 0L) {
                delay(initialDelayMillis)
                if (sequence != tailscaleConnectSequence) return@launch
            }
            var finalState = inspected
            for (attemptNumber in 1..TAILSCALE_CONNECT_MAX_ATTEMPTS) {
                if (sequence != tailscaleConnectSequence) return@launch
                val initial = tailscaleBinding.requestVpnConnect(
                    automationAttempt = attemptNumber,
                    automationAttemptLimit = TAILSCALE_CONNECT_MAX_ATTEMPTS,
                    includePackageFallback = attemptNumber > 1,
                )
                updateAutomation {
                    it.copy(
                        isTailscaleBusy = initial.installed && !initial.vpnActive,
                        tailscale = initial,
                    )
                }
                if (!initial.installed) {
                    _uiState.update { it.copy(userMessage = initial.message) }
                    return@launch
                }
                _uiState.update {
                    it.copy(
                        userMessage = "$trigger Tailscale CONNECT_VPN 요청 ${attemptNumber}/${TAILSCALE_CONNECT_MAX_ATTEMPTS}: ${initial.broadcastTarget}",
                    )
                }
                finalState = waitForTailscaleActive(initial)
                if (sequence != tailscaleConnectSequence) return@launch
                updateAutomation { it.copy(tailscale = finalState) }
                if (finalState.vpnActive) break
                if (attemptNumber < TAILSCALE_CONNECT_MAX_ATTEMPTS) {
                    delay(TAILSCALE_CONNECT_RETRY_DELAY_MILLIS)
                }
            }
            updateAutomation { it.copy(isTailscaleBusy = false, tailscale = finalState) }
            val baseUrl = _uiState.value.baseUrl.trim()
            when {
                finalState.vpnActive && refreshWhenReady && baseUrl.isNotBlank() -> {
                    refreshWithMessage("Tailscale 연결 확인 후 게임 목록을 동기화했습니다.")
                }
                finalState.vpnActive -> {
                    _uiState.update { it.copy(userMessage = "Android-local Tailscale VPN 활성화를 확인했습니다.") }
                }
                else -> {
                    _uiState.update {
                        it.copy(
                            userMessage = "${finalState.message} Sleep-safe를 켜고, Tailscale을 Always-on VPN/배터리 제한 없음으로 설정하거나 Tailscale 앱을 열어 수동 상태를 확인하세요.",
                        )
                    }
                }
            }
        }
    }

    private suspend fun waitForTailscaleActive(initial: TailscaleBindingState): TailscaleBindingState {
        var latest = tailscaleBinding.inspect(
            lastAutomationAction = initial.lastAutomationAction,
            broadcastTarget = initial.broadcastTarget,
            automationAttempt = initial.automationAttempt,
            automationAttemptLimit = initial.automationAttemptLimit,
        )
        if (!latest.installed) return latest
        if (latest.vpnActive) {
            return latest.copy(message = "Android-local Tailscale VPN 활성화를 확인했습니다.")
        }
        val deadlineMillis = System.currentTimeMillis() + TAILSCALE_CONNECT_TIMEOUT_MILLIS
        while (System.currentTimeMillis() < deadlineMillis) {
            delay(TAILSCALE_CONNECT_POLL_MILLIS)
            latest = tailscaleBinding.inspect(
                lastAutomationAction = initial.lastAutomationAction,
                broadcastTarget = initial.broadcastTarget,
                automationAttempt = initial.automationAttempt,
                automationAttemptLimit = initial.automationAttemptLimit,
            )
            updateAutomation { it.copy(tailscale = latest) }
            if (latest.vpnActive) {
                return latest.copy(message = "Android-local Tailscale VPN 활성화를 확인했습니다.")
            }
        }
        return latest.copy(
            message = "Tailscale CONNECT_VPN ${initial.automationAttempt}/${initial.automationAttemptLimit} 요청 후에도 Android VPN 활성 네트워크가 감지되지 않았습니다. target=${initial.broadcastTarget}. sleep/wake 이후 Tailscale 앱 standby 상태에서는 broadcast 자동 ON이 제한될 수 있습니다.",
            pollingTimedOut = true,
        )
    }

    fun repairEnvironment() {
        val baseUrl = _uiState.value.baseUrl.trim()
        if (baseUrl.isBlank()) {
            _uiState.update { it.copy(userMessage = "Remote Agent URL을 먼저 입력하세요.") }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(setupRepairInFlight = true, userMessage = "환경 자동 복구를 시작합니다. 전원 명령은 실행하지 않습니다.") }
            updateAutomation { it.copy(tailscale = tailscaleBinding.inspect()) }
            if (!ensureRemoteNetwork("환경 자동 복구")) {
                _uiState.update { it.copy(setupRepairInFlight = false) }
                return@launch
            }
            runCatching { repository().fetchHomeSnapshot() }
                .onSuccess { snapshot ->
                    val now = System.currentTimeMillis()
                    preferences.cachedProcessesJson = snapshot.rawProcessesJson
                    preferences.lastSyncMillis = now
                    applyPowerDefaults(snapshot.powerReadiness)
                    _uiState.update {
                        it.copy(
                            availability = RemoteAvailability.Online,
                            isRefreshing = false,
                            processes = snapshot.processes,
                            hostMessage = snapshot.readiness?.remoteConnectivity?.message
                                ?: snapshot.readiness?.serverModeReadiness?.message,
                            lastSyncMillis = now,
                            lastStateRevision = snapshot.status.stateRevision,
                            hasToken = tokenStore.loadToken() != null,
                            processLaunchEnabled = snapshot.status.processLaunch,
                            processStopEnabled = snapshot.status.processStop,
                            powerReadiness = snapshot.powerReadiness,
                            automation = it.automation.copy(
                                ssh = automationPreferences.loadSsh(),
                                tailscale = inspectTailscalePreservingDiagnostics(it.automation.tailscale),
                            ),
                        )
                    }
                }
                .onFailure { error ->
                    repairSshDefaults(reason = "환경 자동 복구")
                    _uiState.update { it.copy(userMessage = error.message ?: "Remote Agent 상태 조회 실패. 로컬 설정 복구만 적용했습니다.") }
                }

            val ssh = automationPreferences.loadSsh()
            if (tokenStore.loadToken().isNullOrBlank()) {
                _uiState.update {
                    it.copy(
                        setupRepairInFlight = false,
                        userMessage = "환경 자동 복구: SSH host/user 후보를 정리했습니다. key 등록은 페어링 토큰 복구 후 가능합니다.",
                    )
                }
                return@launch
            }
            if (sshHasKnownBadEndpoint(ssh)) {
                _uiState.update {
                    it.copy(
                        setupRepairInFlight = false,
                        userMessage = "환경 자동 복구: SSH host/user가 아직 유효하지 않습니다. Remote Agent URL과 host user를 확인하세요.",
                    )
                }
                return@launch
            }
            try {
                completeSshAutomation("환경 자동 복구")
            } finally {
                _uiState.update { it.copy(setupRepairInFlight = false) }
            }
        }
    }

    fun createAndRegisterSshKey() {
        if (_uiState.value.baseUrl.isBlank()) {
            _uiState.update { it.copy(userMessage = "Remote Agent URL을 먼저 입력하세요.") }
            return
        }
        viewModelScope.launch {
            completeSshAutomation("수동 요청")
        }
    }

    fun verifySshHealth() {
        val privateKey = sshKeyStore.loadPrivateKey()
        if (privateKey.isNullOrBlank()) {
            _uiState.update { it.copy(userMessage = "SSH key를 먼저 생성/등록하세요.") }
            return
        }
        viewModelScope.launch {
            if (!ensureRemoteNetwork("SSH health 확인")) return@launch
            updateAutomation { it.copy(isSshBusy = true) }
            val result = sshPowerManager.health(automationPreferences.loadSsh(), privateKey)
            updateAutomation { it.copy(isSshBusy = false, ssh = automationPreferences.loadSsh()) }
            _uiState.update { it.copy(userMessage = result.message) }
        }
    }

    private fun maybeAutoCompleteSshAutomation(trigger: String) {
        val baseUrl = _uiState.value.baseUrl.trim()
        repairSshDefaults(_uiState.value.powerReadiness, trigger)
        val ssh = automationPreferences.loadSsh()
        if (baseUrl.isBlank() || tokenStore.loadToken().isNullOrBlank()) return
        if (sshHasKnownBadEndpoint(ssh) || ssh.healthOk || _uiState.value.automation.isSshBusy || _uiState.value.setupRepairInFlight) return
        val signature = listOf(baseUrl, ssh.host, ssh.user, ssh.port.toString(), ssh.publicKey.take(48)).joinToString("|")
        if (autoSshAttemptSignature == signature) return
        autoSshAttemptSignature = signature
        viewModelScope.launch {
            completeSshAutomation(trigger)
        }
    }

    private suspend fun completeSshAutomation(trigger: String) {
        if (!ensureRemoteNetwork("$trigger SSH 자동화")) return
        updateAutomation { it.copy(isSshBusy = true) }
        _uiState.update { it.copy(userMessage = "$trigger SSH key 등록과 health 확인을 자동 진행합니다.") }
        val keyPair = sshKeyStore.ensureKeyPair()
        val registerResult = runCatching { repository().registerPowerSSHKey(keyPair.publicKeyLine, "Android") }
            .getOrElse { error ->
                updateAutomation { it.copy(isSshBusy = false, ssh = automationPreferences.loadSsh()) }
                _uiState.update { it.copy(userMessage = "SSH public key 자동 등록 실패: ${error.message ?: "알 수 없는 오류"}") }
                return
            }
        if (!registerResult.accepted) {
            updateAutomation { it.copy(isSshBusy = false, ssh = automationPreferences.loadSsh()) }
            _uiState.update { it.copy(userMessage = "SSH public key 자동 등록이 거부되었습니다: ${registerResult.message}") }
            return
        }
        val privateKey = sshKeyStore.loadPrivateKey() ?: keyPair.privateKeyPem
        val healthResult = sshPowerManager.health(automationPreferences.loadSsh(), privateKey)
        updateAutomation { it.copy(isSshBusy = false, ssh = automationPreferences.loadSsh()) }
        _uiState.update {
            it.copy(
                userMessage = if (healthResult.ok) {
                    "$trigger SSH key 등록과 health 확인을 자동 완료했습니다."
                } else {
                    "SSH key 등록은 완료했지만 health 확인 실패: ${healthResult.message}"
                },
            )
        }
    }

    fun discoverSmartThingsDevices(pat: String? = null) {
        val token = pat?.trim()?.takeIf { it.isNotBlank() } ?: automationPreferences.loadSmartThingsPat()
        if (token.isNullOrBlank()) {
            _uiState.update { it.copy(userMessage = "SmartThings PAT를 입력하세요.") }
            return
        }
        pat?.trim()?.takeIf { it.isNotBlank() }?.let(automationPreferences::saveSmartThingsPat)
        viewModelScope.launch {
            updateAutomation { it.copy(isSmartThingsBusy = true, smartThings = automationPreferences.loadSmartThings()) }
            runCatching { SmartThingsClient(token).listSwitchDevices() }
                .onSuccess { devices ->
                    val selection = selectSmartThingsWakeDevice(devices, SMARTTHINGS_DEFAULT_WAKE_LABEL)
                    selection.selected?.let(::persistSmartThingsDevice)
                    updateAutomation {
                        it.copy(
                            isSmartThingsBusy = false,
                            smartThings = automationPreferences.loadSmartThings(),
                            smartThingsCandidates = selection.candidates,
                        )
                    }
                    _uiState.update { it.copy(userMessage = selection.message) }
                }
                .onFailure { error ->
                    updateAutomation { it.copy(isSmartThingsBusy = false, smartThings = automationPreferences.loadSmartThings()) }
                    _uiState.update { it.copy(userMessage = error.message ?: "SmartThings 디바이스 조회 실패") }
                }
        }
    }

    fun selectSmartThingsDevice(candidate: SmartThingsDeviceCandidate) {
        persistSmartThingsDevice(candidate)
        updateAutomation { it.copy(smartThings = automationPreferences.loadSmartThings()) }
        _uiState.update { it.copy(userMessage = "SmartThings '${candidate.label}' 디바이스를 선택했습니다.") }
    }

    fun executePowerAction(action: PowerAction) {
        when (action) {
            PowerAction.Wake -> wakeWithSmartThings()
            PowerAction.Sleep, PowerAction.Restart, PowerAction.Shutdown -> executeSshPower(action)
        }
    }

    private fun wakeWithSmartThings() {
        val pat = automationPreferences.loadSmartThingsPat()
        val deviceId = automationPreferences.smartThingsDeviceId
        if (pat.isNullOrBlank() || deviceId.isBlank()) {
            val message = when {
                pat.isNullOrBlank() && deviceId.isBlank() -> "SmartThings PAT와 PC 켜기 deviceId를 먼저 설정하세요."
                pat.isNullOrBlank() -> "PC 켜기 deviceId는 설정되어 있지만 SmartThings PAT/OAuth 인증이 없어 Wake 명령을 보낼 수 없습니다."
                else -> "SmartThings PAT는 저장되어 있지만 PC 켜기 deviceId가 없습니다."
            }
            _uiState.update { it.copy(userMessage = message) }
            return
        }
        viewModelScope.launch {
            updateAutomation { it.copy(powerActionInFlight = PowerAction.Wake) }
            runCatching { SmartThingsClient(pat).wake(deviceId) }
                .onSuccess { result ->
                    updateAutomation { it.copy(powerActionInFlight = null) }
                    _uiState.update {
                        it.copy(
                            availability = if (result.accepted) RemoteAvailability.Waking else it.availability,
                            userMessage = result.message,
                        )
                    }
                    if (result.accepted) {
                        delay(4_000)
                        refreshWithMessage("Wake 후 Remote Agent 재연결을 확인했습니다.")
                    }
                }
                .onFailure { error ->
                    updateAutomation { it.copy(powerActionInFlight = null) }
                    _uiState.update { it.copy(userMessage = error.message ?: "SmartThings Wake 실패") }
                }
        }
    }

    private fun executeSshPower(action: PowerAction) {
        val privateKey = sshKeyStore.loadPrivateKey()
        if (privateKey.isNullOrBlank() || !automationPreferences.loadSsh().healthOk) {
            _uiState.update { it.copy(userMessage = "SSH health 확인이 완료되어야 ${action.label} 명령을 사용할 수 있습니다.") }
            return
        }
        viewModelScope.launch {
            if (!ensureRemoteNetwork("${action.label} SSH 명령")) return@launch
            updateAutomation { it.copy(powerActionInFlight = action) }
            val result = sshPowerManager.executePowerAction(action, automationPreferences.loadSsh(), privateKey)
            updateAutomation { it.copy(powerActionInFlight = null) }
            _uiState.update {
                it.copy(
                    availability = if (result.ok) {
                        if (action == PowerAction.Restart) RemoteAvailability.Restarting else RemoteAvailability.GoingOffline
                    } else {
                        it.availability
                    },
                    userMessage = result.message,
                )
            }
        }
    }

    private fun persistSmartThingsDevice(candidate: SmartThingsDeviceCandidate) {
        automationPreferences.smartThingsDeviceId = candidate.deviceId
        automationPreferences.smartThingsDeviceLabel = candidate.label
        automationPreferences.smartThingsLocationId = candidate.locationId.orEmpty()
        automationPreferences.smartThingsLastVerifiedMillis = System.currentTimeMillis()
    }

    private fun repository(tokenOverride: String? = tokenStore.loadToken()): RemoteRepository {
        return RemoteRepository(_uiState.value.baseUrl.trim(), tokenOverride, remoteNetworkController)
    }

    private fun applyPowerDefaults(powerReadiness: RemotePowerReadiness?) {
        repairSshDefaults(powerReadiness, "전원 readiness")
    }

    private fun repairSshDefaults(powerReadiness: RemotePowerReadiness? = _uiState.value.powerReadiness, reason: String = "자동 복구"): Boolean {
        val candidateUser = powerReadiness?.setup?.user?.trim().orEmpty()
        val candidateHost = hostFromBaseUrl(_uiState.value.baseUrl)
        var changed = false
        if (shouldReplaceSshUser(automationPreferences.sshUser, candidateUser)) {
            automationPreferences.sshUser = candidateUser
            resetSshHealthTrust(resetFingerprint = false)
            changed = true
        }
        if (shouldReplaceSshHost(automationPreferences.sshHost, candidateHost)) {
            automationPreferences.sshHost = candidateHost
            resetSshHealthTrust()
            changed = true
        }
        if (changed) {
            autoSshAttemptSignature = null
            updateAutomation { it.copy(ssh = automationPreferences.loadSsh()) }
            _uiState.update { it.copy(userMessage = "$reason: 테스트/loopback SSH 설정을 실제 host 후보로 복구했습니다.") }
        }
        return changed
    }

    private fun hostFromBaseUrl(baseUrl: String): String {
        return runCatching { URI(baseUrl.trim()).host }.getOrNull().orEmpty()
    }

    private fun shouldReplaceSshHost(current: String, candidate: String): Boolean {
        if (candidate.isBlank()) return false
        val normalized = current.trim().lowercase()
        if (normalized.isBlank()) return true
        return normalized in setOf("127.0.0.1", "localhost", "0.0.0.0", "::1") || normalized.contains("fake")
    }

    private fun shouldReplaceSshUser(current: String, candidate: String): Boolean {
        if (candidate.isBlank()) return false
        val normalized = current.trim().lowercase()
        return normalized.isBlank() || sshUserLooksSynthetic(normalized)
    }

    private fun sshHasKnownBadEndpoint(ssh: SshPowerPreferences): Boolean {
        val host = ssh.host.trim().lowercase()
        val user = ssh.user.trim().lowercase()
        return host.isBlank() ||
            user.isBlank() ||
            host in setOf("127.0.0.1", "localhost", "0.0.0.0", "::1") ||
            host.contains("fake") ||
            sshUserLooksSynthetic(user)
    }

    private fun sshUserLooksSynthetic(value: String): Boolean {
        return value == "fake" || value == "fake-user" || value == "test" || value.contains("fake")
    }

    private fun resetSshHealthTrust(resetFingerprint: Boolean = true) {
        automationPreferences.sshHealthOk = false
        if (resetFingerprint) automationPreferences.sshTrustedFingerprint = ""
    }

    private fun updateAutomation(transform: (AutomationUiState) -> AutomationUiState) {
        _uiState.update { state -> state.copy(automation = transform(state.automation)) }
    }

    private suspend fun ensureRemoteNetwork(reason: String): Boolean {
        val policy = validateRemoteBaseUrlPolicy(_uiState.value.baseUrl)
        if (!policy.allowed) {
            val blocked = _uiState.value.automation.remoteNetwork.copy(
                status = RemoteNetworkStatus.Unavailable,
                message = policy.message,
                lastAction = reason,
            )
            updateAutomation { it.copy(isRemoteNetworkBusy = false, remoteNetwork = blocked) }
            _uiState.update { it.copy(baseUrlSecurityMessage = policy.message, baseUrlAllowed = false, userMessage = policy.message) }
            return false
        }
        val connecting = _uiState.value.automation.remoteNetwork.copy(
            status = RemoteNetworkStatus.Connecting,
            message = "$reason 원격 네트워크 연결을 확인합니다.",
            lastAction = reason,
        )
        updateAutomation { it.copy(isRemoteNetworkBusy = true, remoteNetwork = connecting) }
        val state = remoteNetworkController.ensureConnected(reason)
        updateAutomation { it.copy(isRemoteNetworkBusy = false, remoteNetwork = state) }
        if (!state.ready) {
            _uiState.update { it.copy(userMessage = state.message) }
            return false
        }
        return true
    }

    private fun inspectTailscalePreservingDiagnostics(previous: TailscaleBindingState): TailscaleBindingState {
        return tailscaleBinding.inspect(
            lastAutomationAction = previous.lastAutomationAction,
            broadcastTarget = previous.broadcastTarget,
            automationAttempt = previous.automationAttempt,
            automationAttemptLimit = previous.automationAttemptLimit,
            pollingTimedOut = previous.pollingTimedOut,
        )
    }

    private fun applyFailure(error: Throwable) {
        val availability = when (error) {
            is RemoteApiException.AuthRejected -> RemoteAvailability.AuthRejected
            is RemoteApiException.OfflineExpected -> RemoteAvailability.OfflineExpected
            is RemoteApiException.AgentUnavailable -> RemoteAvailability.AgentUnavailable
            else -> RemoteAvailability.AgentUnavailable
        }
        _uiState.update {
            it.copy(
                availability = availability,
                isRefreshing = false,
                isPairing = false,
                hostMessage = null,
                userMessage = failureMessage(error),
                processes = it.processes.ifEmpty { preferences.cachedProcesses() },
                lastSyncMillis = preferences.lastSyncMillis,
                hasToken = tokenStore.loadToken() != null,
                processLaunchEnabled = false,
                processStopEnabled = false,
            )
        }
    }

    private fun failureMessage(error: Throwable): String {
        return when (error) {
            is RemoteApiException.AuthRejected -> "저장된 토큰이 거부되었습니다. 캐시는 보존했으니 페어링/토큰 복구를 진행하세요."
            is RemoteApiException.OfflineExpected -> "호스트가 꺼져 있거나 네트워크에서 보이지 않습니다. 마지막 게임 목록을 표시합니다."
            is RemoteApiException.AgentUnavailable -> "호스트는 있을 수 있지만 Remote Agent HTTP 서버에 연결할 수 없습니다."
            is RemoteApiException.HttpFailure -> "Remote Agent 오류: HTTP ${error.code}"
            else -> error.message ?: "Remote Agent에 연결하지 못했습니다."
        }
    }

    private fun initialUserMessage(): String {
        return when {
            smartThingsPatSeeded && defaultRemoteBaseUrlApplied -> "로컬 SmartThings debug token과 빌드 기본 Remote Agent URL을 적용했습니다."
            smartThingsPatSeeded -> "로컬 SmartThings debug token을 앱 보안 저장소에 보관했습니다."
            defaultRemoteBaseUrlApplied -> "빌드 기본 Remote Agent URL을 적용했습니다. 페어링 코드만 입력하면 됩니다."
            else -> "Host IP/hostname과 페어링 코드가 있으면 바로 연결할 수 있습니다."
        }
    }

    private fun defaultDeviceName(): String {
        return listOf(Build.MANUFACTURER, Build.MODEL)
            .filter { it.isNotBlank() }
            .joinToString(" ")
            .ifBlank { "Android" }
    }
}

class RemoteViewModelFactory(private val context: Context) : ViewModelProvider.Factory {
    @Suppress("UNCHECKED_CAST")
    override fun <T : ViewModel> create(modelClass: Class<T>): T {
        return RemoteViewModel(context.applicationContext) as T
    }
}
