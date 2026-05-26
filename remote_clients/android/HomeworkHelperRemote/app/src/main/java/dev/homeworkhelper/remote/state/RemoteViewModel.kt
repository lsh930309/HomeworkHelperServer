package dev.homeworkhelper.remote.state

import android.content.Context
import android.os.Build
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
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

data class AutomationUiState(
    val tailscale: TailscaleBindingState = TailscaleBindingState(),
    val tailscaleAutomation: TailscaleAutomationPreferences = TailscaleAutomationPreferences(),
    val ssh: SshPowerPreferences = SshPowerPreferences(),
    val smartThings: SmartThingsPreferences = SmartThingsPreferences(),
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
    val automation: AutomationUiState = AutomationUiState(),
) {
    val canRefresh: Boolean
        get() = baseUrl.isNotBlank() && !isRefreshing

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
    private val tailscaleBinding = TailscaleBinding(appContext)
    private val sshKeyStore = AndroidSSHKeyStore(automationPreferences)
    private val sshPowerManager = AndroidSSHPowerManager(automationPreferences)
    private var autoSshAttemptSignature: String? = null

    private val _uiState = MutableStateFlow(
        RemoteUiState(
            baseUrl = preferences.baseUrl,
            deviceName = preferences.deviceName.ifBlank { defaultDeviceName() },
            hasToken = tokenStore.loadToken() != null,
            processes = preferences.cachedProcesses(),
            lastSyncMillis = preferences.lastSyncMillis,
            showDiagnostics = preferences.showDiagnostics,
            userMessage = "Remote Agent URL과 페어링 코드가 있으면 바로 연결할 수 있습니다.",
            automation = AutomationUiState(
                tailscale = tailscaleBinding.inspect(),
                tailscaleAutomation = automationPreferences.loadTailscaleAutomation(),
                ssh = automationPreferences.loadSsh(),
                smartThings = automationPreferences.loadSmartThings(),
            ),
        )
    )
    val uiState: StateFlow<RemoteUiState> = _uiState.asStateFlow()

    init {
        if (_uiState.value.baseUrl.isNotBlank()) {
            refresh()
        }
    }

    fun onAppForeground() {
        updateAutomation { it.copy(tailscale = tailscaleBinding.inspect()) }
        if (_uiState.value.automation.tailscaleAutomation.connectOnAppForeground) {
            requestTailscaleConnect("앱 실행")
        }
    }

    fun onAppBackground() {
        if (_uiState.value.automation.tailscaleAutomation.disconnectOnAppBackground) {
            requestTailscaleDisconnect("앱 종료")
        }
    }

    fun updateBaseUrl(value: String) {
        preferences.baseUrl = value
        _uiState.update { it.copy(baseUrl = value, userMessage = null) }
        fillDefaultSshHost(value)
    }

    fun updateDeviceName(value: String) {
        preferences.deviceName = value
        _uiState.update { it.copy(deviceName = value, userMessage = null) }
    }

    fun updateShowDiagnostics(value: Boolean) {
        preferences.showDiagnostics = value
        _uiState.update { it.copy(showDiagnostics = value) }
    }

    fun updateTailscaleConnectOnForeground(value: Boolean) {
        automationPreferences.tailscaleConnectOnAppForeground = value
        updateAutomation { it.copy(tailscaleAutomation = automationPreferences.loadTailscaleAutomation()) }
        _uiState.update { it.copy(userMessage = if (value) "앱 실행 시 Tailscale CONNECT_VPN 자동화를 시도합니다." else "앱 실행 시 Tailscale 자동 연결을 껐습니다.") }
    }

    fun updateTailscaleDisconnectOnBackground(value: Boolean) {
        automationPreferences.tailscaleDisconnectOnAppBackground = value
        updateAutomation { it.copy(tailscaleAutomation = automationPreferences.loadTailscaleAutomation()) }
        _uiState.update { it.copy(userMessage = if (value) "앱 종료 시 Tailscale DISCONNECT_VPN 자동화를 시도합니다." else "앱 종료 시 Tailscale 자동 비활성화를 껐습니다.") }
    }

    fun updateSshHost(value: String) {
        automationPreferences.sshHost = value
        updateAutomation { it.copy(ssh = automationPreferences.loadSsh()) }
    }

    fun updateSshUser(value: String) {
        automationPreferences.sshUser = value
        updateAutomation { it.copy(ssh = automationPreferences.loadSsh()) }
    }

    fun updateSshPort(value: String) {
        val port = value.toIntOrNull() ?: return
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
                            automation = it.automation.copy(ssh = automationPreferences.loadSsh(), tailscale = tailscaleBinding.inspect()),
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
            runCatching { repository(tokenOverride = null).confirmPairing(code.trim(), deviceName) }
                .onSuccess { response ->
                    preferences.deviceName = response.name.ifBlank { deviceName }
                    tokenStore.saveToken(response.token)
                    _uiState.update {
                        it.copy(
                            isPairing = false,
                            deviceName = response.name.ifBlank { deviceName },
                            hasToken = true,
                            userMessage = "이 Android 기기를 페어링했습니다.",
                        )
                    }
                    refreshDevices(updateMessage = false)
                    refresh()
                }
                .onFailure { error ->
                    _uiState.update { it.copy(isPairing = false) }
                    applyFailure(error)
                }
        }
    }

    fun refreshToken() {
        if (tokenStore.loadToken().isNullOrBlank()) {
            _uiState.update { it.copy(userMessage = "갱신할 로컬 토큰이 없습니다. 먼저 페어링하세요.") }
            return
        }
        viewModelScope.launch {
            _uiState.update { it.copy(isDevicesBusy = true, userMessage = null) }
            runCatching { repository().refreshToken() }
                .onSuccess { response ->
                    tokenStore.saveToken(response.token)
                    _uiState.update {
                        it.copy(
                            isDevicesBusy = false,
                            hasToken = true,
                            userMessage = "'${response.name}' 디바이스 토큰을 갱신했습니다.",
                        )
                    }
                    refreshDevices(updateMessage = false)
                }
                .onFailure { error ->
                    _uiState.update { it.copy(isDevicesBusy = false) }
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
        updateAutomation { it.copy(tailscale = tailscaleBinding.requestVpnConnect()) }
        _uiState.update { it.copy(userMessage = "$trigger Tailscale CONNECT_VPN 자동화를 요청했습니다. 최초 권한/로그인은 Tailscale 앱에서 승인해야 할 수 있습니다.") }
    }

    fun requestTailscaleDisconnect(trigger: String = "수동") {
        updateAutomation { it.copy(tailscale = tailscaleBinding.requestVpnDisconnect()) }
        _uiState.update { it.copy(userMessage = "$trigger Tailscale DISCONNECT_VPN 자동화를 요청했습니다.") }
    }

    fun openTailscaleApp() {
        val opened = tailscaleBinding.openTailscaleApp()
        _uiState.update { it.copy(userMessage = if (opened) "Tailscale 앱을 열었습니다." else "Tailscale 앱을 찾지 못했습니다.") }
    }

    fun openTailscaleInstallPage() {
        tailscaleBinding.openInstallPage()
        _uiState.update { it.copy(userMessage = "Tailscale 설치 페이지를 열었습니다.") }
    }

    fun ensureTailscaleAndProbe() {
        if (_uiState.value.baseUrl.isBlank()) {
            _uiState.update { it.copy(userMessage = "Remote Agent URL을 먼저 입력하세요.") }
            return
        }
        viewModelScope.launch {
            updateAutomation { it.copy(isTailscaleBusy = true, tailscale = tailscaleBinding.inspect()) }
            runCatching { repository().ensureTailscale() }
                .onSuccess { result ->
                    val acceptedUrl = result.suggestedBaseUrls.firstOrNull { candidate -> repository().probe(candidate) }
                    if (acceptedUrl != null) {
                        preferences.baseUrl = acceptedUrl
                    }
                    updateAutomation {
                        it.copy(
                            isTailscaleBusy = false,
                            tailscale = tailscaleBinding.inspect().copy(suggestedBaseUrls = result.suggestedBaseUrls, message = result.message ?: it.tailscale.message),
                        )
                    }
                    _uiState.update {
                        it.copy(
                            baseUrl = acceptedUrl ?: it.baseUrl,
                            userMessage = acceptedUrl?.let { url -> "Tailscale URL을 확인하고 저장했습니다: $url" }
                                ?: (result.message ?: "Tailscale 후보 URL을 확인했습니다."),
                        )
                    }
                }
                .onFailure { error ->
                    updateAutomation { it.copy(isTailscaleBusy = false) }
                    _uiState.update { it.copy(userMessage = error.message ?: "Tailscale 확인 실패") }
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
            updateAutomation { it.copy(isSshBusy = true) }
            val result = sshPowerManager.health(automationPreferences.loadSsh(), privateKey)
            updateAutomation { it.copy(isSshBusy = false, ssh = automationPreferences.loadSsh()) }
            _uiState.update { it.copy(userMessage = result.message) }
        }
    }

    private fun maybeAutoCompleteSshAutomation(trigger: String) {
        val baseUrl = _uiState.value.baseUrl.trim()
        val ssh = automationPreferences.loadSsh()
        if (baseUrl.isBlank() || tokenStore.loadToken().isNullOrBlank()) return
        if (ssh.host.isBlank() || ssh.user.isBlank() || ssh.healthOk || _uiState.value.automation.isSshBusy) return
        val signature = listOf(baseUrl, ssh.host, ssh.user, ssh.port.toString(), ssh.publicKey.take(48)).joinToString("|")
        if (autoSshAttemptSignature == signature) return
        autoSshAttemptSignature = signature
        viewModelScope.launch {
            completeSshAutomation(trigger)
        }
    }

    private suspend fun completeSshAutomation(trigger: String) {
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

    fun clearLocalToken() {
        tokenStore.clearToken()
        _uiState.update {
            it.copy(
                hasToken = false,
                availability = RemoteAvailability.AuthRejected,
                userMessage = "로컬 토큰을 삭제했습니다. 호스트에서 기기를 revoke하려면 기기 탭을 확인하세요.",
            )
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
        return RemoteRepository(_uiState.value.baseUrl.trim(), tokenOverride)
    }

    private fun applyPowerDefaults(powerReadiness: RemotePowerReadiness?) {
        if (automationPreferences.sshUser.isBlank()) {
            powerReadiness?.setup?.user?.takeIf { it.isNotBlank() }?.let { automationPreferences.sshUser = it }
        }
        if (automationPreferences.sshHost.isBlank()) {
            fillDefaultSshHost(_uiState.value.baseUrl)
        }
    }

    private fun fillDefaultSshHost(baseUrl: String) {
        if (automationPreferences.sshHost.isNotBlank()) return
        val host = runCatching { URI(baseUrl.trim()).host }.getOrNull().orEmpty()
        if (host.isNotBlank()) {
            automationPreferences.sshHost = host
            updateAutomation { it.copy(ssh = automationPreferences.loadSsh()) }
        }
    }

    private fun updateAutomation(transform: (AutomationUiState) -> AutomationUiState) {
        _uiState.update { state -> state.copy(automation = transform(state.automation)) }
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
