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
import dev.homeworkhelper.remote.state.RemoteUiState
import dev.homeworkhelper.remote.state.remoteHostInputFromBaseUrl

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
    onInspectTailscale: () -> Unit,
    onOpenTailscale: () -> Unit,
    onInstallTailscale: () -> Unit,
    onCheckClientTailscale: () -> Unit,
    onTailscaleConnect: () -> Unit,
    onTailscaleDisconnect: () -> Unit,
    onTailscaleConnectOnForegroundChange: (Boolean) -> Unit,
    onTailscaleDisconnectOnBackgroundChange: (Boolean) -> Unit,
    onRepairEnvironment: () -> Unit,
    onSshHostChange: (String) -> Unit,
    onSshUserChange: (String) -> Unit,
    onSshPortChange: (String) -> Unit,
    onRegisterSshKey: () -> Unit,
    onVerifySsh: () -> Unit,
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
                Text("macOS 클라이언트 구조를 Android에 맞게 나눈 연결 · 전원 · 기기 · 앱 설정입니다.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
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
                        onInspectTailscale = onInspectTailscale,
                        onOpenTailscale = onOpenTailscale,
                        onInstallTailscale = onInstallTailscale,
                        onCheckClientTailscale = onCheckClientTailscale,
                        onTailscaleConnect = onTailscaleConnect,
                        onRepairEnvironment = onRepairEnvironment,
                    )
                    SetupSection.Power -> PowerSection(
                        state = state,
                        onSshHostChange = onSshHostChange,
                        onSshUserChange = onSshUserChange,
                        onSshPortChange = onSshPortChange,
                        onRegisterSshKey = onRegisterSshKey,
                        onVerifySsh = onVerifySsh,
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
                        onTailscaleConnect = onTailscaleConnect,
                        onTailscaleDisconnect = onTailscaleDisconnect,
                        onTailscaleConnectOnForegroundChange = onTailscaleConnectOnForegroundChange,
                        onTailscaleDisconnectOnBackgroundChange = onTailscaleDisconnectOnBackgroundChange,
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
    onInspectTailscale: () -> Unit,
    onOpenTailscale: () -> Unit,
    onInstallTailscale: () -> Unit,
    onCheckClientTailscale: () -> Unit,
    onTailscaleConnect: () -> Unit,
    onRepairEnvironment: () -> Unit,
) {
    var pairingCode by remember { mutableStateOf("") }
    val hostInput = remoteHostInputFromBaseUrl(state.baseUrl)
    LaunchedEffect(state.hasToken) {
        if (state.hasToken) pairingCode = ""
    }
    SettingsCard(title = "연결/페어링", subtitle = "Remote Agent URL과 Android device token을 관리합니다.") {
        OutlinedTextField(
            value = hostInput,
            onValueChange = onBaseUrlChange,
            label = { Text("Host IP / hostname") },
            placeholder = { Text("100.x.y.z 또는 host.tailnet.ts.net") },
            prefix = { Text("http://") },
            suffix = { Text(":8000") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        if (state.baseUrl.isNotBlank()) {
            Text("Remote Agent URL: ${state.baseUrl}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        OutlinedTextField(value = state.deviceName, onValueChange = onDeviceNameChange, label = { Text("기기 이름") }, singleLine = true, modifier = Modifier.fillMaxWidth())
        InfoRow("페어링", if (state.hasToken) "완료" else "필요")
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(value = pairingCode, onValueChange = { pairingCode = it.filter(Char::isDigit).take(6) }, label = { Text("6자리 페어링 코드") }, singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword), modifier = Modifier.weight(1f))
            Button(onClick = { onPair(pairingCode) }, enabled = !state.isPairing) { Text(if (state.isPairing) "페어링 중" else "페어링") }
        }
        Text("페어링 토큰은 명시적 기기 revoke 전까지 유지됩니다. 네트워크 오류나 앱 재시작만으로 갱신/삭제하지 않습니다.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Button(
            onClick = onRepairEnvironment,
            enabled = state.baseUrl.isNotBlank() && !state.setupRepairInFlight,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Text(if (state.setupRepairInFlight) "환경 복구 중" else "환경 자동 복구")
        }
        Text("실제 페어링 상태는 보존하면서 Tailscale 감지, host SSH 후보 복구, SSH key 등록/health를 전원 명령 없이 점검합니다.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
    TailscaleFoundationSection(state, onInspectTailscale, onOpenTailscale, onInstallTailscale, onCheckClientTailscale, onTailscaleConnect)
}

@Composable
private fun TailscaleFoundationSection(
    state: RemoteUiState,
    onInspectTailscale: () -> Unit,
    onOpenTailscale: () -> Unit,
    onInstallTailscale: () -> Unit,
    onCheckClientTailscale: () -> Unit,
    onTailscaleConnect: () -> Unit,
) {
    val tailscale = state.automation.tailscale
    SettingsCard(title = "Tailscale 기반환경", subtitle = "Android 기기의 Tailscale 앱과 VPN 상태만 확인합니다.") {
        InfoRow("설치", if (tailscale.installed) "감지됨" else "없음")
        InfoRow("VPN", if (tailscale.vpnActive) "활성" else "미감지")
        Text(tailscale.message, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        if (tailscale.lastAutomationAction.isNotBlank()) {
            Text("최근 자동화: ${tailscale.lastAutomationAction}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        if (tailscale.broadcastTarget.isNotBlank()) {
            Text("Broadcast target: ${tailscale.broadcastTarget}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        if (tailscale.automationAttemptLimit > 0) {
            Text("Retry: ${tailscale.automationAttempt}/${tailscale.automationAttemptLimit} · polling timeout=${tailscale.pollingTimedOut}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        if (tailscale.suggestedBaseUrls.isNotEmpty()) {
            Text("후보 URL: ${tailscale.suggestedBaseUrls.joinToString()}", style = MaterialTheme.typography.bodySmall)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedButton(onClick = onInspectTailscale, modifier = Modifier.weight(1f)) { Text("상태") }
            OutlinedButton(onClick = onOpenTailscale, modifier = Modifier.weight(1f)) { Text("열기") }
            OutlinedButton(onClick = onInstallTailscale, modifier = Modifier.weight(1f)) { Text("설치") }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = onTailscaleConnect, enabled = tailscale.installed, modifier = Modifier.weight(1f)) { Text("VPN ON 요청") }
            Button(onClick = onCheckClientTailscale, enabled = tailscale.installed && !state.automation.isTailscaleBusy, modifier = Modifier.weight(1f)) { Text(if (state.automation.isTailscaleBusy) "확인 중" else "클라이언트 확인") }
        }
    }
}

@Composable
private fun PowerSection(
    state: RemoteUiState,
    onSshHostChange: (String) -> Unit,
    onSshUserChange: (String) -> Unit,
    onSshPortChange: (String) -> Unit,
    onRegisterSshKey: () -> Unit,
    onVerifySsh: () -> Unit,
    onSaveSmartThingsPat: (String) -> Unit,
    onDiscoverSmartThings: (String?) -> Unit,
    onSelectSmartThingsDevice: (SmartThingsDeviceCandidate) -> Unit,
    onManualSmartThingsDeviceChange: (String) -> Unit,
) {
    PowerStatusSection(state)
    SshSection(state, onSshHostChange, onSshUserChange, onSshPortChange, onRegisterSshKey, onVerifySsh)
    SmartThingsSection(state, onSaveSmartThingsPat, onDiscoverSmartThings, onSelectSmartThingsDevice, onManualSmartThingsDeviceChange)
}

@Composable
private fun SshSection(
    state: RemoteUiState,
    onSshHostChange: (String) -> Unit,
    onSshUserChange: (String) -> Unit,
    onSshPortChange: (String) -> Unit,
    onRegisterSshKey: () -> Unit,
    onVerifySsh: () -> Unit,
) {
    val ssh = state.automation.ssh
    SettingsCard(title = "OpenSSH 전원 제어", subtitle = "절전/재시작/종료는 Android 로컬 SSH adapter가 직접 수행합니다.") {
        OutlinedTextField(value = ssh.host, onValueChange = onSshHostChange, label = { Text("SSH host") }, singleLine = true, modifier = Modifier.fillMaxWidth())
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(value = ssh.user, onValueChange = onSshUserChange, label = { Text("User") }, singleLine = true, modifier = Modifier.weight(1f))
            OutlinedTextField(value = ssh.port.toString(), onValueChange = onSshPortChange, label = { Text("Port") }, singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), modifier = Modifier.weight(0.55f))
        }
        InfoRow("Key", if (ssh.publicKey.isNotBlank()) "생성됨" else "없음")
        InfoRow("Health", if (ssh.healthOk) "OK" else "미확인")
        if (ssh.trustedFingerprint.isNotBlank()) Text("Fingerprint: ${ssh.trustedFingerprint}", style = MaterialTheme.typography.bodySmall)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = onRegisterSshKey, enabled = !state.automation.isSshBusy, modifier = Modifier.weight(1f)) { Text("SSH 자동 설정") }
            Button(onClick = onVerifySsh, enabled = !state.automation.isSshBusy, modifier = Modifier.weight(1f)) { Text("Health 재확인") }
        }
        Text("페어링 또는 온라인 복구 후 key 등록과 SSH health는 자동으로 시도됩니다.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
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
    SettingsCard(title = "SmartThings Wake", subtitle = "Wake는 SmartThings REST API와 PC 켜기 deviceId를 사용합니다.") {
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
private fun DevicesSection(
    state: RemoteUiState,
    onRefreshDevices: () -> Unit,
    onRevokeDevice: (RemoteDevice) -> Unit,
    onPurgeRevokedDevices: () -> Unit,
) {
    SettingsCard(title = "기기 관리", subtitle = "페어링된 기기, host, tailnet peer를 macOS와 같은 규칙으로 표시합니다.") {
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
    onTailscaleConnect: () -> Unit,
    onTailscaleDisconnect: () -> Unit,
    onTailscaleConnectOnForegroundChange: (Boolean) -> Unit,
    onTailscaleDisconnectOnBackgroundChange: (Boolean) -> Unit,
) {
    SettingsCard(title = "앱 동작", subtitle = "진단 표시와 Android-local Tailscale lifecycle 자동화를 설정합니다.") {
        ToggleRow("진단 섹션 표시", state.showDiagnostics, onShowDiagnosticsChange)
        ToggleRow("앱 실행 시 Tailscale ON 요청", state.automation.tailscaleAutomation.connectOnAppForeground, onTailscaleConnectOnForegroundChange)
        ToggleRow("앱 종료 시 Tailscale OFF 요청", state.automation.tailscaleAutomation.disconnectOnAppBackground, onTailscaleDisconnectOnBackgroundChange)
        if (state.automation.tailscaleAutomation.connectOnAppForeground || state.automation.tailscaleAutomation.disconnectOnAppBackground) {
            Text("주의: lifecycle 자동화가 켜져 있으면 앱 전환만으로 Tailscale VPN ON/OFF 요청이 발생할 수 있습니다.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.error)
        }
        Text("Tailscale ON/OFF는 Tailscale Android 앱의 IPNReceiver component broadcast를 우선 요청하고, 자동 ON은 sleep/wake 직후 race를 줄이기 위해 retry합니다. 최초 로그인/권한 승인은 Tailscale 앱에서 직접 확인해야 할 수 있습니다.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = onTailscaleConnect, enabled = state.automation.tailscale.installed, modifier = Modifier.weight(1f)) { Text("VPN ON") }
            OutlinedButton(onClick = onTailscaleDisconnect, enabled = state.automation.tailscale.installed, modifier = Modifier.weight(1f)) { Text("VPN OFF") }
        }
    }
    if (state.showDiagnostics) DiagnosticsSection(state)
    FakeSmokeSection()
}

@Composable
private fun PowerStatusSection(state: RemoteUiState) {
    val power = state.powerReadiness
    SettingsCard(title = "전원 준비 상태", subtitle = power?.summary ?: "Remote Agent 연결 후 전원 readiness를 확인합니다.") {
        InfoRow("Host", power?.status?.targetHost?.takeIf { it.isNotBlank() } ?: "미설정")
        InfoRow("Status", power?.status?.status ?: power?.readiness?.state ?: "unknown")
        InfoRow("SSH", power?.setup?.sshServiceMessage ?: "확인 전")
        power?.setup?.effectiveAuthorizedKeysPath?.let { Text("Authorized keys: $it", style = MaterialTheme.typography.bodySmall) }
        Text("Wake는 SmartThings REST API, 절전/재시작/종료는 Android OpenSSH adapter가 직접 수행합니다.", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun DiagnosticsSection(state: RemoteUiState) {
    SettingsCard(title = "진단", subtitle = "현재 Android 클라이언트 상태") {
        InfoRow("Availability", state.availability.toString())
        InfoRow("Base URL", state.baseUrl.ifBlank { "미설정" })
        InfoRow("Token", if (state.hasToken) "저장됨" else "없음")
        InfoRow("Games", state.processes.size.toString())
        InfoRow("Devices", state.devices.size.toString())
        InfoRow("Last sync", state.lastSyncLabel)
        InfoRow("State revision", state.lastStateRevision ?: "unknown")
        InfoRow("SSH ready", state.automation.sshReady.toString())
        InfoRow("SmartThings ready", state.automation.wakeReady.toString())
        InfoRow("Tailscale VPN", state.automation.tailscale.vpnActive.toString())
        InfoRow("Tailscale target", state.automation.tailscale.broadcastTarget.ifBlank { "none" })
        InfoRow("Tailscale retry", "${state.automation.tailscale.automationAttempt}/${state.automation.tailscale.automationAttemptLimit}")
        InfoRow("Tailscale timeout", state.automation.tailscale.pollingTimedOut.toString())
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
private fun ToggleRow(label: String, checked: Boolean, onCheckedChange: (Boolean) -> Unit) {
    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
        Text(label, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
        Spacer(modifier = Modifier.padding(4.dp))
        Switch(checked = checked, onCheckedChange = onCheckedChange)
    }
}
