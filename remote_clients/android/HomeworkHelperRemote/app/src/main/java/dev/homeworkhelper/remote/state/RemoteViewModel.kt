package dev.homeworkhelper.remote.state

import android.content.Context
import android.os.Build
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewModelScope
import dev.homeworkhelper.remote.data.RemoteApiException
import dev.homeworkhelper.remote.data.RemoteAvailability
import dev.homeworkhelper.remote.data.RemoteProcess
import dev.homeworkhelper.remote.data.RemoteRepository
import dev.homeworkhelper.remote.platform.AndroidTokenStore
import dev.homeworkhelper.remote.platform.RemotePreferences
import dev.homeworkhelper.remote.platform.TokenStore
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import java.text.DateFormat
import java.util.Date

data class RemoteUiState(
    val baseUrl: String = "",
    val deviceName: String = "",
    val hasToken: Boolean = false,
    val availability: RemoteAvailability = RemoteAvailability.Unknown,
    val isRefreshing: Boolean = false,
    val isPairing: Boolean = false,
    val launchInFlightId: String? = null,
    val processes: List<RemoteProcess> = emptyList(),
    val hostMessage: String? = null,
    val userMessage: String? = null,
    val lastSyncMillis: Long = 0L,
    val processLaunchEnabled: Boolean = false,
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
) : ViewModel() {
    private val _uiState = MutableStateFlow(
        RemoteUiState(
            baseUrl = preferences.baseUrl,
            deviceName = preferences.deviceName.ifBlank { defaultDeviceName() },
            hasToken = tokenStore.loadToken() != null,
            processes = preferences.cachedProcesses(),
            lastSyncMillis = preferences.lastSyncMillis,
            userMessage = "Remote Agent URL과 페어링 코드가 있으면 바로 연결할 수 있습니다.",
        )
    )
    val uiState: StateFlow<RemoteUiState> = _uiState.asStateFlow()

    init {
        if (_uiState.value.baseUrl.isNotBlank()) {
            refresh()
        }
    }

    fun updateBaseUrl(value: String) {
        preferences.baseUrl = value
        _uiState.update { it.copy(baseUrl = value, userMessage = null) }
    }

    fun updateDeviceName(value: String) {
        preferences.deviceName = value
        _uiState.update { it.copy(deviceName = value, userMessage = null) }
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
            _uiState.update { it.copy(isRefreshing = true, userMessage = null) }
            runCatching { repository().fetchHomeSnapshot() }
                .onSuccess { snapshot ->
                    val now = System.currentTimeMillis()
                    preferences.cachedProcessesJson = snapshot.rawProcessesJson
                    preferences.lastSyncMillis = now
                    _uiState.update {
                        it.copy(
                            availability = RemoteAvailability.Online,
                            isRefreshing = false,
                            processes = snapshot.processes,
                            hostMessage = snapshot.readiness?.message,
                            userMessage = successMessage ?: "게임 목록을 동기화했습니다.",
                            lastSyncMillis = now,
                            hasToken = tokenStore.loadToken() != null,
                            processLaunchEnabled = snapshot.status.processLaunch,
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
                    refresh()
                }
                .onFailure { error ->
                    _uiState.update { it.copy(isPairing = false) }
                    applyFailure(error)
                }
        }
    }

    fun launch(process: RemoteProcess) {
        if (process.isRunning) {
            _uiState.update { it.copy(userMessage = "이미 실행 중인 게임입니다.") }
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
                    if (result.accepted) refreshWithMessage(result.message)
                }
                .onFailure { error ->
                    _uiState.update { it.copy(launchInFlightId = null) }
                    applyFailure(error)
                }
        }
    }

    fun clearLocalToken() {
        tokenStore.clearToken()
        _uiState.update {
            it.copy(
                hasToken = false,
                availability = RemoteAvailability.AuthRejected,
                userMessage = "로컬 토큰을 삭제했습니다. 호스트에서 기기를 revoke하려면 별도 기기 관리가 필요합니다.",
            )
        }
    }

    private fun repository(tokenOverride: String? = tokenStore.loadToken()): RemoteRepository {
        return RemoteRepository(_uiState.value.baseUrl.trim(), tokenOverride)
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
            )
        }
    }

    private fun failureMessage(error: Throwable): String {
        return when (error) {
            is RemoteApiException.AuthRejected -> "저장된 토큰이 거부되었습니다. 캐시는 보존했으니 페어링을 복구하세요."
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
