package dev.homeworkhelper.remote.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import dev.homeworkhelper.remote.data.RemoteDevice
import dev.homeworkhelper.remote.data.SMARTTHINGS_DEFAULT_WAKE_LABEL
import dev.homeworkhelper.remote.data.SmartThingsDeviceCandidate
import dev.homeworkhelper.remote.platform.PowerAction
import dev.homeworkhelper.remote.state.RemoteUiState

private enum class SetupSection(val label: String, val icon: String) {
    Connection("연결", "🔗"),
    Power("전원", "⚡"),
    Devices("기기", "▣"),
    App("앱", "⚙"),
}

@Composable
fun SetupTab(
    state: RemoteUiState,
    onBaseUrlChange: (String) -> Unit,
    onDeviceNameChange: (String) -> Unit,
    onPair: (String) -> Unit,
    onRefreshDevices: () -> Unit,
    onRevokeDevice: (RemoteDevice) -> Unit,
    onPurgeRevokedDevices: () -> Unit,
    onShowDiagnosticsChange: (Boolean) -> Unit,
    onInspectRemoteNetwork: () -> Unit,
    onEnsureRemoteNetwork: () -> Unit,
    onRepairEnvironment: () -> Unit,
    onSaveSmartThingsPat: (String) -> Unit,
    onDiscoverSmartThings: (String?) -> Unit,
    onSelectSmartThingsDevice: (SmartThingsDeviceCandidate) -> Unit,
    onManualSmartThingsDeviceChange: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    var section by rememberSaveable { mutableStateOf(SetupSection.Connection) }
    Surface(modifier = modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
        Column(modifier = Modifier.fillMaxSize()) {
            Column(modifier = Modifier.padding(horizontal = 16.dp, vertical = 14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text("설정", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
                Text("공유기 공인 IP 기반 공개 HTTPS 연결, SmartThings Wake, Host 위임 전원을 관리합니다.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            TabRow(selectedTabIndex = SetupSection.entries.indexOf(section)) {
                SetupSection.entries.forEach { item ->
                    Tab(
                        selected = section == item,
                        onClick = { section = item },
                        text = { Text("${item.icon} ${item.label}", maxLines = 1, overflow = TextOverflow.Ellipsis) },
                    )
                }
            }
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(horizontal = 16.dp, vertical = 16.dp)
                    .padding(bottom = 92.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                when (section) {
                    SetupSection.Connection -> ConnectionSection(
                        state = state,
                        onBaseUrlChange = onBaseUrlChange,
                        onDeviceNameChange = onDeviceNameChange,
                        onPair = onPair,
                        onInspectRemoteNetwork = onInspectRemoteNetwork,
                        onEnsureRemoteNetwork = onEnsureRemoteNetwork,
                        onRepairEnvironment = onRepairEnvironment,
                    )
                    SetupSection.Power -> PowerSection(
                        state = state,
                        onSaveSmartThingsPat = onSaveSmartThingsPat,
                        onDiscoverSmartThings = onDiscoverSmartThings,
                        onSelectSmartThingsDevice = onSelectSmartThingsDevice,
                        onManualSmartThingsDeviceChange = onManualSmartThingsDeviceChange,
                    )
                    SetupSection.Devices -> DevicesSection(
                        state = state,
                        onRefreshDevices = onRefreshDevices,
                        onRevokeDevice = onRevokeDevice,
                        onPurgeRevokedDevices = onPurgeRevokedDevices,
                    )
                    SetupSection.App -> AppSection(
                        state = state,
                        onShowDiagnosticsChange = onShowDiagnosticsChange,
                    )
                }
            }
        }
    }
}

@Composable
private fun ConnectionSection(
    state: RemoteUiState,
    onBaseUrlChange: (String) -> Unit,
    onDeviceNameChange: (String) -> Unit,
    onPair: (String) -> Unit,
    onInspectRemoteNetwork: () -> Unit,
    onEnsureRemoteNetwork: () -> Unit,
    onRepairEnvironment: () -> Unit,
) {
    var pairingCode by remember { mutableStateOf("") }
    LaunchedEffect(state.hasToken) {
        if (state.hasToken) pairingCode = ""
    }
    SettingsCard(title = "연결/페어링", subtitle = "공유기 WAN 공인 IPv4만 입력합니다. HTTPS URL은 앱 내부에서 자동 생성됩니다.") {
        OutlinedTextField(
            value = state.routerPublicIpInput,
            onValueChange = onBaseUrlChange,
            label = { Text("공유기 공인 IP") },
            placeholder = { Text("예: 211.216.28.65") },
            singleLine = true,
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
            modifier = Modifier.fillMaxWidth(),
        )
        if (state.baseUrlSecurityMessage.isNotBlank()) {
            Text(
                state.baseUrlSecurityMessage,
                style = MaterialTheme.typography.bodySmall,
                color = if (state.baseUrlAllowed) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.error,
            )
        }
        OutlinedTextField(value = state.deviceName, onValueChange = onDeviceNameChange, label = { Text("기기 이름") }, singleLine = true, modifier = Modifier.fillMaxWidth())
        InfoRow("페어링", if (state.hasToken) "완료" else "필요")
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(value = pairingCode, onValueChange = { pairingCode = it.filter(Char::isDigit).take(6) }, label = { Text("6자리 페어링 코드") }, singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword), modifier = Modifier.weight(1f))
            Button(onClick = { onPair(pairingCode) }, enabled = !state.isPairing && state.baseUrlAllowed) { Text(if (state.isPairing) "페어링 중" else "페어링") }
        }
        Text("페어링 토큰은 명시적 기기 revoke 전까지 유지됩니다. 네트워크 오류나 앱 재시작만으로 갱신/삭제하지 않습니다.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        ConnectionDoctorSection(state)
        Button(
            onClick = onRepairEnvironment,
            enabled = state.baseUrl.isNotBlank() && !state.setupRepairInFlight,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text(if (state.setupRepairInFlight) "점검 중" else "공개 HTTPS 상태 점검")
        }
        Text("수동 포트포워딩은 TCP 443 → Windows Host 38443만 필요합니다. Remote Agent 8000은 외부에 직접 열지 않습니다.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
    RemoteNetworkFoundationSection(state, onInspectRemoteNetwork, onEnsureRemoteNetwork)
}

@Composable
private fun RemoteNetworkFoundationSection(
    state: RemoteUiState,
    onInspectRemoteNetwork: () -> Unit,
    onEnsureRemoteNetwork: () -> Unit,
) {
    val remoteNetwork = state.automation.remoteNetwork
    SettingsCard(title = "원격 연결 경로", subtitle = "HomeworkHelper HTTP 호출은 Android system route로 공개 HTTPS에 접속합니다.") {
        InfoRow("Mode", remoteNetwork.mode.label)
        InfoRow("State", remoteNetwork.status.label)
        InfoRow("Engine", remoteNetwork.engine)
        Text(remoteNetwork.message, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        if (remoteNetwork.lastAction.isNotBlank()) {
            Text("최근 확인: ${remoteNetwork.lastAction}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = onEnsureRemoteNetwork, enabled = !state.automation.isRemoteNetworkBusy, modifier = Modifier.weight(1f)) {
                Text(if (state.automation.isRemoteNetworkBusy) "연결 확인 중" else "연결 확인")
            }
            OutlinedButton(onClick = onInspectRemoteNetwork, enabled = !state.automation.isRemoteNetworkBusy, modifier = Modifier.weight(1f)) {
                Text("상태")
            }
        }
        Text("공유기 공인 IP만 저장하고, DNS/TLS/Bearer/Remote Agent 검사는 내부 URL로 자동 수행합니다.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun ConnectionDoctorSection(state: RemoteUiState) {
    val verdict = when {
        !state.baseUrlAllowed -> "차단: ${state.baseUrlSecurityMessage}"
        state.hasToken && state.availability.name == "Online" -> "정상: HTTPS/DNS/Bearer/Remote Agent 응답 확인"
        state.hasToken -> "점검: DNS → TLS 인증서 → Bearer 인증 → /remote/status 순서로 확인"
        else -> "페어링 전: Host App에서 6자리 코드를 발급한 뒤 Bearer token을 등록"
    }
    SettingsCard(title = "Connection Doctor", subtitle = "공개 HTTPS 직접접속의 실패 지점을 단계별로 분리합니다.") {
        InfoRow("공인 IP", state.routerPublicIpInput.ifBlank { "입력 대기" })
        InfoRow("정책", state.baseUrlSecurityMessage.ifBlank { "공개망은 HTTPS만 허용" })
        InfoRow("진단", verdict)
        Text("수동 포트포워딩 기본값은 TCP 443 → Windows Host 38443입니다. Remote Agent 8000 포트는 외부에 직접 열지 않습니다.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun PowerSection(
    state: RemoteUiState,
    onSaveSmartThingsPat: (String) -> Unit,
    onDiscoverSmartThings: (String?) -> Unit,
    onSelectSmartThingsDevice: (SmartThingsDeviceCandidate) -> Unit,
    onManualSmartThingsDeviceChange: (String) -> Unit,
) {
    PowerStatusSection(state)
    SmartThingsSection(state, onSaveSmartThingsPat, onDiscoverSmartThings, onSelectSmartThingsDevice, onManualSmartThingsDeviceChange)
}

@Composable
private fun SmartThingsSection(
    state: RemoteUiState,
    onSaveSmartThingsPat: (String) -> Unit,
    onDiscoverSmartThings: (String?) -> Unit,
    onSelectSmartThingsDevice: (SmartThingsDeviceCandidate) -> Unit,
    onManualSmartThingsDeviceChange: (String) -> Unit,
) {
    var patInput by remember { mutableStateOf("") }
    val smartThings = state.automation.smartThings
    SettingsCard(title = "SmartThings Wake", subtitle = "Wake는 공유기 WoL 전달 미지원 때문에 SmartThings REST API와 PC 켜기 deviceId를 사용합니다.") {
        Text("대상 deviceId는 target일 뿐이며, Cloud 명령 전송에는 PAT/OAuth 인증이 반드시 필요합니다.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text("디바이스 자동 조회/선택 target label: $SMARTTHINGS_DEFAULT_WAKE_LABEL", style = MaterialTheme.typography.bodySmall)
        OutlinedTextField(value = patInput, onValueChange = { patInput = it.trim() }, label = { Text("SmartThings PAT 또는 로컬 debug token") }, placeholder = { Text(if (smartThings.hasPat) "저장됨 - 비워 두면 기존 PAT 사용" else "PAT 입력") }, singleLine = true, visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth())
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = { onSaveSmartThingsPat(patInput) }, enabled = patInput.isNotBlank(), modifier = Modifier.weight(1f)) { Text("PAT 저장") }
            Button(onClick = { onDiscoverSmartThings(patInput.takeIf { it.isNotBlank() }) }, enabled = !state.automation.isSmartThingsBusy, modifier = Modifier.weight(1f)) { Text(if (state.automation.isSmartThingsBusy) "조회 중" else "자동 조회") }
        }
        InfoRow("선택", "${smartThings.deviceLabel.ifBlank { "없음" }} ${smartThings.deviceId.takeIf { it.isNotBlank() }?.let { "($it)" }.orEmpty()}")
        OutlinedTextField(value = smartThings.deviceId, onValueChange = onManualSmartThingsDeviceChange, label = { Text("Wake target deviceId 수동 입력 fallback") }, singleLine = true, modifier = Modifier.fillMaxWidth())
        if (state.automation.smartThingsCandidates.isNotEmpty()) {
            Text("후보 디바이스", style = MaterialTheme.typography.labelLarge)
            state.automation.smartThingsCandidates.forEach { candidate ->
                TextButton(onClick = { onSelectSmartThingsDevice(candidate) }, modifier = Modifier.fillMaxWidth()) { Text("${candidate.label} · ${candidate.deviceId}") }
            }
        }
    }
}

@Composable
private fun PowerStatusSection(state: RemoteUiState) {
    val power = state.powerReadiness
    SettingsCard(title = "전원 준비 상태", subtitle = power?.summary ?: "Remote Agent 연결 후 전원 readiness를 확인합니다.") {
        InfoRow("Wake", if (state.automation.wakeReady) "SmartThings 준비됨" else "SmartThings PAT/deviceId 필요")
        InfoRow("Host 위임", if (state.hostDelegatedPowerReady) "절전/재시작/종료 준비됨" else "Host action 상태 확인 전")
        InfoRow("Status", power?.status?.status ?: power?.readiness?.state ?: "unknown")
        InfoRow("Actions", power?.status?.supportedActions?.joinToString().orEmpty().ifBlank { "없음" })
        Text("Wake는 기존 SmartThings 경로를 유지하고, 절전/재시작/종료는 인증된 공개 HTTPS Remote Agent가 호스트에서 수행합니다.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun DevicesSection(
    state: RemoteUiState,
    onRefreshDevices: () -> Unit,
    onRevokeDevice: (RemoteDevice) -> Unit,
    onPurgeRevokedDevices: () -> Unit,
) {
    SettingsCard(title = "기기 관리", subtitle = "페어링된 리모트 기기를 표시합니다.") {
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = onRefreshDevices, enabled = state.hasToken && !state.isDevicesBusy, modifier = Modifier.weight(1f)) { Text(if (state.isDevicesBusy) "조회 중" else "기기 새로고침") }
            OutlinedButton(onClick = onPurgeRevokedDevices, enabled = state.hasToken && !state.isDevicesBusy, modifier = Modifier.weight(1f)) { Text("폐기 정리") }
        }
        if (state.devices.isEmpty()) {
            Text("아직 불러온 기기 목록이 없습니다.", style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        } else {
            state.devices.forEach { device -> DeviceRow(device = device, busy = state.isDevicesBusy, onRevokeDevice = onRevokeDevice) }
        }
    }
}

@Composable
private fun DeviceRow(device: RemoteDevice, busy: Boolean, onRevokeDevice: (RemoteDevice) -> Unit) {
    var pendingRevoke by remember(device.id) { mutableStateOf(false) }
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Row(modifier = Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(device.name, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text("${device.platform} · ${device.role} · ${device.pairingStatus}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                Text(device.healthMessage ?: device.connectivityState, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
            OutlinedButton(onClick = { pendingRevoke = true }, enabled = device.canRevoke && !busy) { Text("Revoke") }
        }
    }
    if (pendingRevoke) {
        AlertDialog(
            onDismissRequest = { pendingRevoke = false },
            title = { Text("${device.name} revoke") },
            text = { Text("호스트에서 이 기기의 Remote token을 폐기합니다. 해당 기기는 다시 페어링해야 합니다.") },
            confirmButton = { Button(onClick = { pendingRevoke = false; onRevokeDevice(device) }, colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error)) { Text("Revoke") } },
            dismissButton = { TextButton(onClick = { pendingRevoke = false }) { Text("취소") } },
        )
    }
}

@Composable
private fun AppSection(
    state: RemoteUiState,
    onShowDiagnosticsChange: (Boolean) -> Unit,
) {
    SettingsCard(title = "앱 동작", subtitle = "진단 표시와 공개 HTTPS 직접 연결 상태를 관리합니다.") {
        ToggleRow("진단 섹션 표시", state.showDiagnostics, onShowDiagnosticsChange)
        Text("앱 lifecycle에서 외부 네트워크 상태를 변경하지 않습니다. 모든 Remote Agent 호출은 공유기 공인 IP에서 파생한 공개 HTTPS 경로를 사용합니다.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
    if (state.showDiagnostics) DiagnosticsSection(state)
    FakeSmokeSection()
}

@Composable
private fun DiagnosticsSection(state: RemoteUiState) {
    SettingsCard(title = "진단", subtitle = "현재 Android 클라이언트 상태") {
        InfoRow("Availability", state.availability.toString())
        InfoRow("공유기 공인 IP", state.routerPublicIpInput.ifBlank { "미설정" })
        InfoRow("Token", if (state.hasToken) "저장됨" else "없음")
        InfoRow("Games", state.processes.size.toString())
        InfoRow("Devices", state.devices.size.toString())
        InfoRow("Last sync", state.lastSyncLabel)
        InfoRow("State revision", state.lastStateRevision ?: "unknown")
        InfoRow("SmartThings ready", state.automation.wakeReady.toString())
        InfoRow("Host power ready", state.hostDelegatedPowerReady.toString())
        InfoRow("Remote network mode", state.automation.remoteNetwork.mode.wireName)
        InfoRow("Remote network state", state.automation.remoteNetwork.status.label)
        InfoRow("Public HTTPS", state.baseUrl.startsWith("https://").toString())
        InfoRow("Connection policy", state.baseUrlSecurityMessage.ifBlank { "미설정" })
    }
}

@Composable
private fun FakeSmokeSection() {
    SettingsCard(title = "Fake Remote Agent smoke", subtitle = "개발 검증 루프") {
        Text("fake Remote Agent와 adb reverse로 Home/Setup UI, PNG icon, launch/stop, token/device 계약을 먼저 검증합니다.")
        Text("실제 HomeworkHelper host pairing과 게임 실행은 별도 실기기 검증 단계에서 확인합니다.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun SettingsCard(title: String, subtitle: String? = null, content: @Composable ColumnScope.() -> Unit) {
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(title, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
            subtitle?.takeIf { it.isNotBlank() }?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
            content()
        }
    }
}

@Composable
private fun InfoRow(label: String, value: String) {
    Row(modifier = Modifier.fillMaxWidth(), verticalAlignment = Alignment.Top, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(label, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.weight(0.42f))
        Text(value, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
    }
}

@Composable
private fun ToggleRow(label: String, checked: Boolean, onCheckedChange: (Boolean) -> Unit, enabled: Boolean = true) {
    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
        Text(label, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
        Spacer(modifier = Modifier.padding(4.dp))
        Switch(checked = checked, onCheckedChange = onCheckedChange, enabled = enabled)
    }
}
