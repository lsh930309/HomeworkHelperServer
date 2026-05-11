package dev.homeworkhelper.remote

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                RemoteApp()
            }
        }
    }
}

@Composable
fun RemoteApp() {
    val context = LocalContext.current
    val preferences = remember { RemotePreferences(context) }
    val tokenStore = remember { AndroidTokenStore(context) }
    val androidIntegration = remember { AndroidIntegration(context) }
    val initialToken = remember {
        val encryptedToken = tokenStore.token()
        if (encryptedToken.isNotBlank()) {
            encryptedToken
        } else {
            preferences.legacyToken().also { legacyToken ->
                if (legacyToken.isNotBlank()) {
                    tokenStore.saveToken(legacyToken)
                    preferences.clearLegacyToken()
                }
            }
        }
    }
    var baseUrl by remember { mutableStateOf(preferences.baseUrl()) }
    var token by remember { mutableStateOf(initialToken) }
    var deviceName by remember { mutableStateOf(preferences.deviceName()) }
    var pairingCode by remember { mutableStateOf("") }
    var androidPackageName by remember { mutableStateOf("") }
    var gameLinkProcessId by remember { mutableStateOf("") }
    var gameLinkPackageName by remember { mutableStateOf("") }
    var usageAccessGranted by remember { mutableStateOf(androidIntegration.hasUsageAccess()) }
    var recentUsage by remember { mutableStateOf<AndroidUsageSnapshot?>(null) }
    var status by remember { mutableStateOf<RemoteStatus?>(null) }
    var dashboardSummary by remember { mutableStateOf<RemoteDashboardSummary?>(null) }
    var beholderIncidents by remember { mutableStateOf(emptyList<RemoteBeholderIncident>()) }
    var gameLinks by remember { mutableStateOf(emptyList<RemoteGameLink>()) }
    var processes by remember { mutableStateOf(emptyList<RemoteProcess>()) }
    var shortcuts by remember { mutableStateOf(emptyList<RemoteShortcut>()) }
    var devices by remember { mutableStateOf(emptyList<RemoteDevice>()) }
    var message by remember { mutableStateOf("Remote Agent에 연결하세요.") }
    val scope = rememberCoroutineScope()

    fun client() = RemoteApiClient(baseUrl, token)

    fun savePreferences(nextMessage: String = "설정을 저장했습니다.") {
        preferences.save(baseUrl, deviceName)
        tokenStore.saveToken(token)
        preferences.clearLegacyToken()
        message = nextMessage
    }

    fun refresh(includeDevices: Boolean = token.isNotBlank()) {
        scope.launch {
            runCatching {
                withContext(Dispatchers.IO) {
                    val api = client()
                    val nextStatus = api.status()
                    val nextSummary = api.dashboardSummary()
                    val nextIncidents = api.beholderIncidents()
                    val nextGameLinks = api.gameLinks()
                    val nextProcesses = api.processes()
                    val nextShortcuts = api.shortcuts()
                    val nextDevices = if (includeDevices) api.devices() else emptyList()
                    RemoteSnapshot(nextStatus, nextSummary, nextIncidents, nextGameLinks, nextProcesses, nextShortcuts, nextDevices)
                }
            }.onSuccess { (nextStatus, nextSummary, nextIncidents, nextGameLinks, nextProcesses, nextShortcuts, nextDevices) ->
                status = nextStatus
                dashboardSummary = nextSummary
                beholderIncidents = nextIncidents
                gameLinks = nextGameLinks
                processes = nextProcesses
                shortcuts = nextShortcuts
                devices = nextDevices
                usageAccessGranted = androidIntegration.hasUsageAccess()
                savePreferences("동기화 완료: 게임 ${nextProcesses.size}개, 연결 ${nextGameLinks.size}개, 숏컷 ${nextShortcuts.size}개")
            }.onFailure {
                message = it.message ?: "연결 실패"
            }
        }
    }

    fun command(block: RemoteApiClient.() -> RemoteCommandResult) {
        scope.launch {
            runCatching { withContext(Dispatchers.IO) { client().block() } }
                .onSuccess { message = it.message }
                .onFailure { message = it.message ?: "명령 실패" }
        }
    }

    fun isPowerActionEnabled(action: String): Boolean = status?.isPowerActionEnabled(action) == true

    fun powerCommand(action: String) {
        if (!isPowerActionEnabled(action)) {
            message = "전원 제어 adapter가 설정되지 않았거나 지원하지 않는 명령입니다."
            return
        }
        command { power(action) }
    }

    fun confirmPairing() {
        scope.launch {
            runCatching {
                withContext(Dispatchers.IO) { client().confirmPairing(pairingCode, deviceName) }
            }.onSuccess { paired ->
                token = paired.token
                pairingCode = ""
                savePreferences("${paired.deviceName} 페어링 완료")
                refresh(includeDevices = true)
            }.onFailure {
                message = it.message ?: "페어링 실패"
            }
        }
    }

    fun revokeDevice(device: RemoteDevice) {
        scope.launch {
            runCatching { withContext(Dispatchers.IO) { client().revokeDevice(device.id) } }
                .onSuccess {
                    message = "${device.deviceName} 토큰을 폐기했습니다."
                    refresh(includeDevices = true)
                }
                .onFailure { message = it.message ?: "토큰 폐기 실패" }
        }
    }

    fun createGameLink() {
        val processId = gameLinkProcessId.trim()
        val packageName = gameLinkPackageName.trim()
        if (processId.isBlank() || packageName.isBlank()) {
            message = "PC process ID와 Android package name을 입력하세요."
            return
        }
        scope.launch {
            runCatching { withContext(Dispatchers.IO) { client().createGameLink(processId, packageName) } }
                .onSuccess { link ->
                    message = "${link.pcDisplayName.ifBlank { link.pcProcessId }}와 ${link.androidPackageName} 연결을 저장했습니다."
                    gameLinkPackageName = ""
                    refresh(includeDevices = token.isNotBlank())
                }
                .onFailure { message = it.message ?: "Android-PC 연결 저장 실패" }
        }
    }

    fun refreshToken() {
        scope.launch {
            runCatching { withContext(Dispatchers.IO) { client().refreshToken() } }
                .onSuccess { refreshed ->
                    token = refreshed.token
                    savePreferences("${refreshed.deviceName} 토큰을 갱신했습니다.")
                    refresh(includeDevices = true)
                }
                .onFailure { message = it.message ?: "토큰 갱신 실패" }
        }
    }

    Scaffold { padding ->
        LazyColumn(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("HomeworkHelper Remote", style = MaterialTheme.typography.headlineSmall)
                    OutlinedTextField(
                        value = baseUrl,
                        onValueChange = { baseUrl = it },
                        label = { Text("Remote Agent URL") },
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = token,
                        onValueChange = { token = it },
                        label = { Text("Bearer token") },
                        visualTransformation = PasswordVisualTransformation(),
                        modifier = Modifier.fillMaxWidth(),
                    )
                    OutlinedTextField(
                        value = deviceName,
                        onValueChange = { deviceName = it },
                        label = { Text("Device name") },
                        modifier = Modifier.fillMaxWidth(),
                    )
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(onClick = { savePreferences() }) { Text("저장") }
                        Button(onClick = {
                            token = ""
                            tokenStore.clearToken()
                            preferences.clearLegacyToken()
                            message = "로컬 토큰을 삭제했습니다."
                        }) { Text("토큰 삭제") }
                        Button(onClick = { refreshToken() }, enabled = token.isNotBlank()) { Text("토큰 갱신") }
                        Button(onClick = { refresh() }) { Text("새로고침") }
                    }
                    Text(message, style = MaterialTheme.typography.bodyMedium)
                }
            }
            item {
                Card(modifier = Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("페어링", style = MaterialTheme.typography.titleMedium)
                        Text("PC에서 /remote/pair/start로 발급한 6자리 코드를 입력합니다.")
                        OutlinedTextField(
                            value = pairingCode,
                            onValueChange = { pairingCode = it.filter(Char::isDigit).take(6) },
                            label = { Text("Pairing code") },
                            modifier = Modifier.fillMaxWidth(),
                        )
                        Button(onClick = { confirmPairing() }, enabled = pairingCode.length == 6) { Text("페어링 완료") }
                    }
                }
            }
            status?.let { current ->
                item {
                    Card(modifier = Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            Text("Remote Agent", style = MaterialTheme.typography.titleMedium)
                            Text("API ${current.apiVersion}")
                            Text("게임 ${current.processCount}개 / 숏컷 ${current.shortcutCount}개 / 활성 세션 ${current.activeSessionCount}개")
                            Text("대시보드 요약: ${if (current.dashboardSummary) "사용 가능" else "미지원"}")
                            Text("Beholder 알림: ${if (current.beholderIncidents) "${beholderIncidents.size}건" else "미지원"}")
                            Text("Android-PC 연결: ${if (current.gameLinks) "${gameLinks.size}개" else "미지원"}")
                            Text("전원 제어: ${if (current.powerControl) "설정됨" else "미설정"}")
                            current.power?.let { power ->
                                Text("전원 상태: ${power.status}")
                                Text("지원 명령: ${if (power.supportedActions.isEmpty()) "없음" else power.supportedActions.joinToString(", ")}")
                                if (power.targetHost.isNotBlank()) Text("대상: ${power.targetHost}")
                            }
                            Text("인증 필요: ${if (current.authRequired) "예" else "아니오"}")
                            Text("페어링 API: ${if (current.pairing) "사용 가능" else "미지원"}")
                        }
                    }
                }
                item {
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        if (!current.powerControl || current.power?.configured != true) {
                            Text("Remote Agent의 전원 제어 adapter가 설정되지 않아 전원 버튼을 비활성화했습니다.")
                        }
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Button(onClick = { powerCommand("wake") }, enabled = isPowerActionEnabled("wake")) { Text("켜기") }
                            Button(onClick = { powerCommand("sleep") }, enabled = isPowerActionEnabled("sleep")) { Text("절전") }
                            Button(onClick = { powerCommand("restart") }, enabled = isPowerActionEnabled("restart")) { Text("재시작") }
                            Button(onClick = { powerCommand("shutdown") }, enabled = isPowerActionEnabled("shutdown")) { Text("끄기") }
                        }
                    }
                }
            }
            item {
                Card(modifier = Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text("Android 로컬 실행", style = MaterialTheme.typography.titleMedium)
                        Text("PC 게임과 연결할 Android 패키지를 수동으로 입력해 Intent 실행을 검증합니다.")
                        OutlinedTextField(
                            value = androidPackageName,
                            onValueChange = { androidPackageName = it },
                            label = { Text("Android package name") },
                            modifier = Modifier.fillMaxWidth(),
                        )
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Button(onClick = {
                                val ok = androidIntegration.launchPackage(androidPackageName)
                                message = if (ok) "$androidPackageName 실행 요청" else "Android 패키지 실행 실패"
                            }) { Text("앱 실행") }
                            Button(onClick = { androidIntegration.openUsageAccessSettings() }) { Text("Usage 권한") }
                            Button(onClick = {
                                usageAccessGranted = androidIntegration.hasUsageAccess()
                                recentUsage = androidIntegration.recentForegroundApp()
                                message = recentUsage?.let { "최근 전면 앱: ${it.packageName}" } ?: "Usage Access 권한이 없거나 최근 전면 앱을 찾지 못했습니다."
                            }) { Text("최근 앱") }
                        }
                        Text("Usage Access: ${if (usageAccessGranted) "허용됨" else "미허용"}")
                        recentUsage?.let { usage ->
                            Text("최근 전면 앱: ${usage.packageName}")
                            if (usage.className.isNotBlank()) Text(usage.className)
                        }
                    }
                }
            }
            dashboardSummary?.let { summary ->
                item {
                    Card(modifier = Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            Text("플레이 요약", style = MaterialTheme.typography.titleMedium)
                            Text("${summary.rangeStart} ~ ${summary.rangeEnd}")
                            Text("총 플레이 ${formatDuration(summary.totalSeconds)} / 일평균 ${formatDuration(summary.dailyAverageSeconds)}")
                            Text("세션 ${summary.sessionCount}개 / 플레이 일수 ${summary.playedDays}일")
                            if (summary.topGameName.isNotBlank()) {
                                Text("Top: ${summary.topGameName} · ${formatDuration(summary.topGameSeconds)}")
                            }
                        }
                    }
                }
            }
            if (beholderIncidents.isNotEmpty()) {
                item {
                    Card(modifier = Modifier.fillMaxWidth()) {
                        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            Text("Beholder 알림", style = MaterialTheme.typography.titleMedium)
                            beholderIncidents.take(3).forEach { incident ->
                                Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                                    Text(incident.userTitle)
                                    Text("위험도 ${incident.riskScore} · ${incident.severity}")
                                    if (incident.userSummary.isNotBlank()) Text(incident.userSummary)
                                    if (incident.riskLabels.isNotEmpty()) Text(incident.riskLabels.joinToString(", "))
                                }
                            }
                        }
                    }
                }
            }

            if (gameLinks.isNotEmpty()) {
                item { Text("Android-PC 연결", style = MaterialTheme.typography.titleMedium) }
                items(gameLinks, key = { it.id }) { link ->
                    Card(modifier = Modifier.fillMaxWidth()) {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(12.dp),
                            horizontalArrangement = Arrangement.SpaceBetween,
                        ) {
                            Column(Modifier.weight(1f)) {
                                Text(link.pcDisplayName.ifBlank { link.pcProcessId })
                                Text(link.androidPackageName)
                                Text("sync: ${link.syncStrategy}")
                                if (link.platformAccountHint.isNotBlank()) Text(link.platformAccountHint)
                            }
                            Button(onClick = {
                                val ok = androidIntegration.launchPackage(link.androidPackageName)
                                message = if (ok) "${link.androidPackageName} 실행 요청" else "Android 연결 앱 실행 실패"
                            }) { Text("Android 실행") }
                        }
                    }
                }
            }
            item { Text("게임", style = MaterialTheme.typography.titleMedium) }
            items(processes, key = { it.id }) { process ->
                Card(modifier = Modifier.fillMaxWidth()) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(12.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Column(Modifier.weight(1f)) {
                            Text(process.name)
                            Text("PC 실행: ${process.preferredLaunchType}")
                            if (process.launchPath.isNotBlank()) Text(process.launchPath)
                        }
                        Button(onClick = { command { launchProcess(process.id) } }) { Text("PC 실행") }
                    }
                }
            }
            item { Text("웹 숏컷", style = MaterialTheme.typography.titleMedium) }
            items(shortcuts, key = { it.id }) { shortcut ->
                Card(modifier = Modifier.fillMaxWidth()) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(12.dp),
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Column(Modifier.weight(1f)) {
                            Text(shortcut.name)
                            Text(shortcut.url)
                        }
                        Button(onClick = { command { openShortcut(shortcut.id) } }) { Text("열기") }
                    }
                }
            }
            if (devices.isNotEmpty()) {
                item { Text("등록 디바이스", style = MaterialTheme.typography.titleMedium) }
                items(devices, key = { it.id }) { device ->
                    Card(modifier = Modifier.fillMaxWidth()) {
                        Row(
                            modifier = Modifier
                                .fillMaxWidth()
                                .padding(12.dp),
                            horizontalArrangement = Arrangement.SpaceBetween,
                        ) {
                            Column(Modifier.weight(1f)) {
                                Text(device.deviceName)
                                Text(device.platform)
                                if (device.tokenRefreshedAt.isNotBlank()) Text("refreshed: ${device.tokenRefreshedAt}")
                                if (device.revokedAt.isNotBlank()) Text("revoked: ${device.revokedAt}")
                            }
                            Button(onClick = { revokeDevice(device) }, enabled = device.revokedAt.isBlank()) { Text("폐기") }
                        }
                    }
                }
            }
        }
    }
}

private data class RemoteSnapshot(
    val status: RemoteStatus,
    val dashboardSummary: RemoteDashboardSummary,
    val beholderIncidents: List<RemoteBeholderIncident>,
    val gameLinks: List<RemoteGameLink>,
    val processes: List<RemoteProcess>,
    val shortcuts: List<RemoteShortcut>,
    val devices: List<RemoteDevice>,
)

private fun formatDuration(seconds: Double): String {
    val minutes = (seconds / 60).toInt()
    if (minutes < 60) return "${minutes}분"
    val hours = minutes / 60
    val remainder = minutes % 60
    return if (remainder == 0) "${hours}시간" else "${hours}시간 ${remainder}분"
}
