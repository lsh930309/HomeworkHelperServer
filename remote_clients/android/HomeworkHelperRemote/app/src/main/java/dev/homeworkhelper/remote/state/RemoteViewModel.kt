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
import dev.homeworkhelper.remote.platform.AndroidTokenStore
import dev.homeworkhelper.remote.platform.AutomationPreferences
import dev.homeworkhelper.remote.platform.PowerAction
import dev.homeworkhelper.remote.platform.RemoteNetworkControllers
import dev.homeworkhelper.remote.platform.RemoteNetworkState
import dev.homeworkhelper.remote.platform.RemoteNetworkStatus
import dev.homeworkhelper.remote.platform.RemotePreferences
import dev.homeworkhelper.remote.platform.SmartThingsPreferences
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

private const val PUBLIC_REMOTE_AGENT_SCHEME = "https"
private const val PUBLIC_IP_DNS_SUFFIX = "sslip.io"
private val IPV4_PATTERN = Regex("""^\d{1,3}(?:\.\d{1,3}){3}$""")
private val SSLIP_DASH_IPV4_PATTERN = Regex("""^(\d{1,3})-(\d{1,3})-(\d{1,3})-(\d{1,3})\.sslip\.io$""", RegexOption.IGNORE_CASE)

internal data class RemoteBaseUrlPolicy(
    val allowed: Boolean,
    val message: String,
)

internal fun normalizeRemoteBaseUrl(value: String): String {
    val trimmed = value.trim().trimEnd('/')
    if (trimmed.isBlank()) return ""
    val publicIp = publicIpv4FromUserInput(trimmed) ?: publicIpv4FromSslipUrl(trimmed) ?: return ""
    return "$PUBLIC_REMOTE_AGENT_SCHEME://${publicIp.replace(".", "-")}.$PUBLIC_IP_DNS_SUFFIX"
}

internal fun remoteHostInputFromBaseUrl(baseUrl: String): String {
    return publicIpv4FromSslipUrl(baseUrl) ?: publicIpv4FromUserInput(baseUrl) ?: ""
}

internal fun validateRemoteBaseUrlPolicy(baseUrl: String): RemoteBaseUrlPolicy {
    val normalized = normalizeRemoteBaseUrl(baseUrl)
    if (normalized.isBlank()) {
        return RemoteBaseUrlPolicy(false, "공유기 WAN 공인 IPv4만 입력하세요. URL, 포트, LAN/사설망 주소는 사용할 수 없습니다.")
    }
    return RemoteBaseUrlPolicy(true, "공개 HTTPS 직접접속: 공유기 공인 IP만 저장하고 URL은 앱 내부에서 생성합니다.")
}

private fun publicIpv4FromUserInput(value: String): String? {
    val trimmed = value.trim()
    if (!IPV4_PATTERN.matches(trimmed)) return null
    return trimmed.takeIf(::isPublicIpv4Host)
}

private fun publicIpv4FromSslipUrl(value: String): String? {
    val host = runCatching { URI(value.trim()).host?.trim().orEmpty() }.getOrDefault("")
    val match = SSLIP_DASH_IPV4_PATTERN.matchEntire(host) ?: return null
    val dotted = match.groupValues.drop(1).joinToString(".")
    return dotted.takeIf(::isPublicIpv4Host)
}

private fun isPublicIpv4Host(host: String): Boolean {
    val normalized = host.trim()
    if (!IPV4_PATTERN.matches(normalized)) return false
    val octets = normalized.split(".").mapNotNull { it.toIntOrNull() }
    if (octets.size != 4 || octets.any { it !in 0..255 }) return false
    val first = octets[0]
    val second = octets[1]
    val third = octets[2]
    if (first == 0 || first >= 224) return false
    if (first == 10 || first == 127) return false
    if (first == 172 && second in 16..31) return false
    if (first == 192 && second == 168) return false
    if (first == 169 && second == 254) return false
    if (first == 100 && second in 64..127) return false
    if (first == 192 && second == 0 && third == 2) return false
    if (first == 198 && second in 18..19) return false
    if (first == 198 && second == 51 && third == 100) return false
    if (first == 203 && second == 0 && third == 113) return false
    return true
}

data class AutomationUiState(
    val remoteNetwork: RemoteNetworkState = RemoteNetworkState(),
    val smartThings: SmartThingsPreferences = SmartThingsPreferences(),
    val isRemoteNetworkBusy: Boolean = false,
    val smartThingsCandidates: List<SmartThingsDeviceCandidate> = emptyList(),
    val isSmartThingsBusy: Boolean = false,
    val powerActionInFlight: PowerAction? = null,
) {
    val wakeReady: Boolean
        get() = smartThings.hasPat && smartThings.deviceId.isNotBlank()
}

data class RemoteUiState(
    val baseUrl: String = "",
    val routerPublicIpInput: String = "",
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
    val baseUrlAllowed: Boolean = false,
    val automation: AutomationUiState = AutomationUiState(),
) {
    val canRefresh: Boolean
        get() = baseUrl.isNotBlank() && baseUrlAllowed && !isRefreshing

    val hostDelegatedPowerReady: Boolean
        get() = listOf(PowerAction.Sleep, PowerAction.Restart, PowerAction.Shutdown).all(::supportsHostPowerAction)

    fun supportsHostPowerAction(action: PowerAction): Boolean {
        if (action == PowerAction.Wake) return automation.wakeReady
        return powerReadiness?.status?.supportedActions?.contains(action.wireName) == true
    }

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
    private val smartThingsPatSeeded = automationPreferences.seedSmartThingsPatFromBuildConfig()
    private val storedBaseUrlAtLaunch = preferences.baseUrl
    private val defaultRemoteBaseUrl = normalizeRemoteBaseUrl(BuildConfig.DEFAULT_REMOTE_BASE_URL)
    private val initialBaseUrl = normalizeRemoteBaseUrl(storedBaseUrlAtLaunch).ifBlank { defaultRemoteBaseUrl }
    private val defaultRemoteBaseUrlApplied = storedBaseUrlAtLaunch.isBlank() && initialBaseUrl.isNotBlank()

    init {
        if (initialBaseUrl != storedBaseUrlAtLaunch) {
            preferences.baseUrl = initialBaseUrl
        }
    }

    private val initialPolicy = validateRemoteBaseUrlPolicy(initialBaseUrl)
    private val _uiState = MutableStateFlow(
        RemoteUiState(
            baseUrl = initialBaseUrl,
            routerPublicIpInput = remoteHostInputFromBaseUrl(initialBaseUrl),
            deviceName = preferences.deviceName.ifBlank { defaultDeviceName() },
            hasToken = tokenStore.loadToken() != null,
            processes = preferences.cachedProcesses(),
            lastSyncMillis = preferences.lastSyncMillis,
            showDiagnostics = preferences.showDiagnostics,
            userMessage = initialUserMessage(),
            baseUrlSecurityMessage = if (initialBaseUrl.isBlank()) "공유기 WAN 공인 IPv4를 입력하세요." else initialPolicy.message,
            baseUrlAllowed = initialBaseUrl.isNotBlank() && initialPolicy.allowed,
            automation = AutomationUiState(
                remoteNetwork = remoteNetworkController.initialState,
                smartThings = automationPreferences.loadSmartThings(),
            ),
        )
    )
    val uiState: StateFlow<RemoteUiState> = _uiState.asStateFlow()

    fun onAppForeground() {
        viewModelScope.launch {
            val state = remoteNetworkController.inspect()
            updateAutomation { it.copy(remoteNetwork = state) }
        }
        if (_uiState.value.baseUrl.isNotBlank()) {
            refresh()
        }
    }

    fun onAppBackground() {
        // Public HTTPS direct mode has no client-side network lifecycle side effects.
    }

    fun updateBaseUrl(value: String) {
        val sanitizedInput = value.filter { it.isDigit() || it == '.' }.take(15)
        val normalized = normalizeRemoteBaseUrl(sanitizedInput)
        val policy = if (normalized.isBlank()) validateRemoteBaseUrlPolicy(sanitizedInput) else validateRemoteBaseUrlPolicy(normalized)
        if (normalized.isNotBlank()) {
            preferences.baseUrl = normalized
        }
        _uiState.update {
            it.copy(
                routerPublicIpInput = sanitizedInput,
                baseUrl = normalized,
                baseUrlSecurityMessage = policy.message,
                baseUrlAllowed = normalized.isNotBlank() && policy.allowed,
                userMessage = if (normalized.isNotBlank() && policy.allowed) null else policy.message,
            )
        }
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
                    userMessage = "공유기 WAN 공인 IPv4를 먼저 입력하세요.",
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
            runCatching {
                val repo = repository()
                val accessStatus = runCatching { repo.remoteAccessStatus() }.getOrNull()
                val snapshot = repo.fetchHomeSnapshot()
                accessStatus to snapshot
            }
                .onSuccess { (accessStatus, snapshot) ->
                    val now = System.currentTimeMillis()
                    preferences.cachedProcessesJson = snapshot.rawProcessesJson
                    preferences.lastSyncMillis = now
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
                        )
                    }
                }
                .onFailure { error -> applyFailure(error) }
        }
    }

    fun pair(code: String) {
        val baseUrl = _uiState.value.baseUrl.trim()
        val deviceName = _uiState.value.deviceName.trim().ifBlank { defaultDeviceName() }
        if (baseUrl.isBlank() || code.trim().length != 6) {
            _uiState.update { it.copy(userMessage = "공유기 공인 IP와 6자리 페어링 코드를 입력하세요.") }
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
                            userMessage = "페어링 성공: $pairedName 등록 완료. 공개 HTTPS 상태를 자동 확인합니다.",
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

    fun repairEnvironment() {
        val baseUrl = _uiState.value.baseUrl.trim()
        if (baseUrl.isBlank()) {
            _uiState.update { it.copy(userMessage = "공유기 WAN 공인 IPv4를 먼저 입력하세요.") }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(setupRepairInFlight = true, userMessage = "공개 HTTPS 환경 점검을 시작합니다.") }
            if (!ensureRemoteNetwork("공개 HTTPS 환경 점검")) {
                _uiState.update { it.copy(setupRepairInFlight = false) }
                return@launch
            }
            runCatching {
                val repo = repository()
                val accessStatus = runCatching { repo.remoteAccessStatus() }.getOrNull()
                accessStatus to repo.fetchHomeSnapshot()
            }
                .onSuccess { (accessStatus, snapshot) ->
                    val now = System.currentTimeMillis()
                    preferences.cachedProcessesJson = snapshot.rawProcessesJson
                    preferences.lastSyncMillis = now
                    _uiState.update {
                        it.copy(
                            setupRepairInFlight = false,
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
                            userMessage = accessStatus?.message
                                ?: "공개 HTTPS 연결과 Host 위임 전원 상태를 확인했습니다.",
                        )
                    }
                    refreshDevices(updateMessage = false)
                }
                .onFailure { error ->
                    _uiState.update { it.copy(setupRepairInFlight = false, userMessage = error.message ?: "Remote Agent 상태 조회 실패") }
                }
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
            PowerAction.Sleep, PowerAction.Restart, PowerAction.Shutdown -> executeHostDelegatedPower(action)
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

    private fun executeHostDelegatedPower(action: PowerAction) {
        if (!_uiState.value.supportsHostPowerAction(action)) {
            _uiState.update { it.copy(userMessage = "Host HTTPS 위임 전원 상태 확인 후 ${action.label} 명령을 사용할 수 있습니다.") }
            return
        }
        viewModelScope.launch {
            if (!ensureRemoteNetwork("${action.label} HTTPS 전원 명령")) return@launch
            updateAutomation { it.copy(powerActionInFlight = action) }
            runCatching { repository().executePowerAction(action.wireName) }
                .onSuccess { result ->
                    updateAutomation { it.copy(powerActionInFlight = null) }
                    _uiState.update {
                        it.copy(
                            availability = if (result.accepted) {
                                if (action == PowerAction.Restart) RemoteAvailability.Restarting else RemoteAvailability.GoingOffline
                            } else {
                                it.availability
                            },
                            userMessage = result.message,
                        )
                    }
                }
                .onFailure { error ->
                    updateAutomation { it.copy(powerActionInFlight = null) }
                    applyFailure(error)
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
            message = "$reason 공개 HTTPS 연결을 확인합니다.",
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
            is RemoteApiException.AgentUnavailable -> "호스트는 있을 수 있지만 공개 HTTPS Remote Agent에 연결할 수 없습니다."
            is RemoteApiException.HttpFailure -> "Remote Agent 오류: HTTP ${error.code}"
            else -> error.message ?: "Remote Agent에 연결하지 못했습니다."
        }
    }

    private fun initialUserMessage(): String {
        return when {
            smartThingsPatSeeded && defaultRemoteBaseUrlApplied -> "로컬 SmartThings debug token과 빌드 기본 공유기 공인 IP 설정을 적용했습니다."
            smartThingsPatSeeded -> "로컬 SmartThings debug token을 앱 보안 저장소에 보관했습니다."
            defaultRemoteBaseUrlApplied -> "빌드 기본 공유기 공인 IP를 적용했습니다. 페어링 코드만 입력하면 됩니다."
            else -> "공유기 WAN 공인 IP와 페어링 코드가 있으면 바로 연결할 수 있습니다."
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
