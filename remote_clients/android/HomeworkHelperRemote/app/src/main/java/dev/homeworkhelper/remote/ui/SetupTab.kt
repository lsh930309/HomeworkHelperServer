package dev.homeworkhelper.remote.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import dev.homeworkhelper.remote.data.SMARTTHINGS_DEFAULT_WAKE_LABEL
import dev.homeworkhelper.remote.data.SmartThingsDeviceCandidate
import dev.homeworkhelper.remote.state.RemoteUiState

@Composable
fun SetupTab(
    state: RemoteUiState,
    onBaseUrlChange: (String) -> Unit,
    onDeviceNameChange: (String) -> Unit,
    onPair: (String) -> Unit,
    onClearToken: () -> Unit,
    onInspectTailscale: () -> Unit,
    onOpenTailscale: () -> Unit,
    onInstallTailscale: () -> Unit,
    onEnsureTailscale: () -> Unit,
    onSshHostChange: (String) -> Unit,
    onSshUserChange: (String) -> Unit,
    onSshPortChange: (String) -> Unit,
    onRegisterSshKey: () -> Unit,
    onVerifySsh: () -> Unit,
    onDiscoverSmartThings: (String?) -> Unit,
    onSelectSmartThingsDevice: (SmartThingsDeviceCandidate) -> Unit,
    onManualSmartThingsDeviceChange: (String) -> Unit,
    modifier: Modifier = Modifier,
) {
    var showDiagnostics by remember { mutableStateOf(true) }
    Surface(modifier = modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = 16.dp, vertical = 16.dp)
                .padding(bottom = 92.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Text("설정", style = MaterialTheme.typography.headlineMedium, fontWeight = FontWeight.Bold)
            ConnectionCard(
                state = state,
                onBaseUrlChange = onBaseUrlChange,
                onDeviceNameChange = onDeviceNameChange,
                onPair = onPair,
                onClearToken = onClearToken,
            )
            AutomationCard(
                state = state,
                onInspectTailscale = onInspectTailscale,
                onOpenTailscale = onOpenTailscale,
                onInstallTailscale = onInstallTailscale,
                onEnsureTailscale = onEnsureTailscale,
                onSshHostChange = onSshHostChange,
                onSshUserChange = onSshUserChange,
                onSshPortChange = onSshPortChange,
                onRegisterSshKey = onRegisterSshKey,
                onVerifySsh = onVerifySsh,
                onDiscoverSmartThings = onDiscoverSmartThings,
                onSelectSmartThingsDevice = onSelectSmartThingsDevice,
                onManualSmartThingsDeviceChange = onManualSmartThingsDeviceChange,
            )
            DisplayPreferencesCard(showDiagnostics = showDiagnostics, onShowDiagnosticsChange = { showDiagnostics = it })
            PowerStatusSection(state)
            if (showDiagnostics) DiagnosticsSection(state)
            FakeSmokeSection()
        }
    }
}

@Composable
private fun ConnectionCard(
    state: RemoteUiState,
    onBaseUrlChange: (String) -> Unit,
    onDeviceNameChange: (String) -> Unit,
    onPair: (String) -> Unit,
    onClearToken: () -> Unit,
) {
    var pairingCode by remember { mutableStateOf("") }
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text("연결 설정", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
            OutlinedTextField(
                value = state.baseUrl,
                onValueChange = onBaseUrlChange,
                label = { Text("Remote Agent URL") },
                placeholder = { Text("http://192.168.0.10:8000") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                value = state.deviceName,
                onValueChange = onDeviceNameChange,
                label = { Text("기기 이름") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                value = pairingCode,
                onValueChange = { pairingCode = it.filter(Char::isDigit).take(6) },
                label = { Text("6자리 페어링 코드") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
                modifier = Modifier.fillMaxWidth(),
            )
            Button(
                onClick = { onPair(pairingCode) },
                enabled = !state.isPairing,
                modifier = Modifier.fillMaxWidth(),
            ) {
                Text(if (state.isPairing) "페어링 중..." else "페어링")
            }
            if (state.hasToken) {
                TextButton(onClick = onClearToken, modifier = Modifier.fillMaxWidth()) {
                    Text("로컬 토큰 삭제")
                }
            }
        }
    }
}

@Composable
private fun AutomationCard(
    state: RemoteUiState,
    onInspectTailscale: () -> Unit,
    onOpenTailscale: () -> Unit,
    onInstallTailscale: () -> Unit,
    onEnsureTailscale: () -> Unit,
    onSshHostChange: (String) -> Unit,
    onSshUserChange: (String) -> Unit,
    onSshPortChange: (String) -> Unit,
    onRegisterSshKey: () -> Unit,
    onVerifySsh: () -> Unit,
    onDiscoverSmartThings: (String?) -> Unit,
    onSelectSmartThingsDevice: (SmartThingsDeviceCandidate) -> Unit,
    onManualSmartThingsDeviceChange: (String) -> Unit,
) {
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
            Text("자동화 설정", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
            TailscaleSection(state, onInspectTailscale, onOpenTailscale, onInstallTailscale, onEnsureTailscale)
            SshSection(state, onSshHostChange, onSshUserChange, onSshPortChange, onRegisterSshKey, onVerifySsh)
            SmartThingsSection(state, onDiscoverSmartThings, onSelectSmartThingsDevice, onManualSmartThingsDeviceChange)
        }
    }
}

@Composable
private fun TailscaleSection(
    state: RemoteUiState,
    onInspectTailscale: () -> Unit,
    onOpenTailscale: () -> Unit,
    onInstallTailscale: () -> Unit,
    onEnsureTailscale: () -> Unit,
) {
    val tailscale = state.automation.tailscale
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("Tailscale 바인딩", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
        Text("설치: ${if (tailscale.installed) "감지됨" else "없음"} · VPN: ${if (tailscale.vpnActive) "활성" else "미감지"}")
        Text(tailscale.message, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        if (tailscale.suggestedBaseUrls.isNotEmpty()) {
            Text("후보 URL: ${tailscale.suggestedBaseUrls.joinToString()}", style = MaterialTheme.typography.bodySmall)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            TextButton(onClick = onInspectTailscale) { Text("상태 확인") }
            TextButton(onClick = onOpenTailscale) { Text("앱 열기") }
            TextButton(onClick = onInstallTailscale) { Text("설치") }
        }
        Button(onClick = onEnsureTailscale, enabled = !state.automation.isTailscaleBusy, modifier = Modifier.fillMaxWidth()) {
            Text(if (state.automation.isTailscaleBusy) "확인 중..." else "Host Tailscale URL 확인")
        }
    }
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
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("OpenSSH 전원 제어", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
        OutlinedTextField(value = ssh.host, onValueChange = onSshHostChange, label = { Text("SSH host") }, singleLine = true, modifier = Modifier.fillMaxWidth())
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            OutlinedTextField(value = ssh.user, onValueChange = onSshUserChange, label = { Text("User") }, singleLine = true, modifier = Modifier.weight(1f))
            OutlinedTextField(value = ssh.port.toString(), onValueChange = onSshPortChange, label = { Text("Port") }, singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), modifier = Modifier.weight(0.55f))
        }
        Text("Key: ${if (ssh.publicKey.isNotBlank()) "생성됨" else "없음"} · Health: ${if (ssh.healthOk) "OK" else "미확인"}")
        if (ssh.trustedFingerprint.isNotBlank()) Text("Fingerprint: ${ssh.trustedFingerprint}", style = MaterialTheme.typography.bodySmall)
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Button(onClick = onRegisterSshKey, enabled = !state.automation.isSshBusy, modifier = Modifier.weight(1f)) { Text("SSH 자동 설정") }
            Button(onClick = onVerifySsh, enabled = !state.automation.isSshBusy, modifier = Modifier.weight(1f)) { Text("Health 재확인") }
        }
        Text(
            "페어링 또는 온라인 복구 후 key 등록과 SSH health는 자동으로 시도됩니다.",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun SmartThingsSection(
    state: RemoteUiState,
    onDiscoverSmartThings: (String?) -> Unit,
    onSelectSmartThingsDevice: (SmartThingsDeviceCandidate) -> Unit,
    onManualSmartThingsDeviceChange: (String) -> Unit,
) {
    var patInput by remember { mutableStateOf("") }
    val smartThings = state.automation.smartThings
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Text("SmartThings Wake", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
        Text("자동 선택 target label: $SMARTTHINGS_DEFAULT_WAKE_LABEL")
        OutlinedTextField(
            value = patInput,
            onValueChange = { patInput = it.trim() },
            label = { Text("SmartThings PAT") },
            placeholder = { Text(if (smartThings.hasPat) "저장됨 - 비워 두면 기존 PAT 사용" else "PAT 입력") },
            singleLine = true,
            visualTransformation = PasswordVisualTransformation(),
            modifier = Modifier.fillMaxWidth(),
        )
        Button(
            onClick = { onDiscoverSmartThings(patInput.takeIf { it.isNotBlank() }) },
            enabled = !state.automation.isSmartThingsBusy,
            modifier = Modifier.fillMaxWidth(),
        ) { Text(if (state.automation.isSmartThingsBusy) "조회 중..." else "디바이스 자동 조회/선택") }
        Text("선택: ${smartThings.deviceLabel.ifBlank { "없음" }} ${smartThings.deviceId.takeIf { it.isNotBlank() }?.let { "($it)" }.orEmpty()}")
        OutlinedTextField(
            value = smartThings.deviceId,
            onValueChange = onManualSmartThingsDeviceChange,
            label = { Text("deviceId 수동 입력 fallback") },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        if (state.automation.smartThingsCandidates.isNotEmpty()) {
            Text("후보 디바이스", style = MaterialTheme.typography.labelLarge)
            state.automation.smartThingsCandidates.forEach { candidate ->
                TextButton(onClick = { onSelectSmartThingsDevice(candidate) }, modifier = Modifier.fillMaxWidth()) {
                    Text("${candidate.label} · ${candidate.deviceId}")
                }
            }
        }
    }
}

@Composable
private fun DisplayPreferencesCard(
    showDiagnostics: Boolean,
    onShowDiagnosticsChange: (Boolean) -> Unit,
) {
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("표시 설정", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
            Text("테마는 시스템 다크 모드를 자동 추적합니다.", style = MaterialTheme.typography.bodyMedium)
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("진단 섹션 표시", style = MaterialTheme.typography.bodyMedium)
                Switch(checked = showDiagnostics, onCheckedChange = onShowDiagnosticsChange)
            }
            Text(
                if (showDiagnostics) "진단 정보가 아래에 표시됩니다." else "진단 정보는 이번 세션에서 접어 둡니다.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun PowerStatusSection(state: RemoteUiState) {
    val power = state.powerReadiness
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("전원 준비 상태", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
            Text(power?.summary ?: "Remote Agent 연결 후 전원 readiness를 확인합니다.")
            Text("Host: ${power?.status?.targetHost?.takeIf { it.isNotBlank() } ?: "미설정"}")
            Text("Status: ${power?.status?.status ?: power?.readiness?.state ?: "unknown"}")
            Text("SSH: ${power?.setup?.sshServiceMessage ?: "확인 전"}")
            power?.setup?.effectiveAuthorizedKeysPath?.let { Text("Authorized keys: $it", style = MaterialTheme.typography.bodySmall) }
            Text(
                "Wake는 SmartThings REST API, 절전/재시작/종료는 Android OpenSSH adapter가 직접 수행합니다.",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun DiagnosticsSection(state: RemoteUiState) {
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("진단", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
            Text("Availability: ${state.availability}")
            Text("Base URL: ${state.baseUrl.ifBlank { "미설정" }}")
            Text("Token: ${if (state.hasToken) "저장됨" else "없음"}")
            Text("Games: ${state.processes.size}")
            Text("Last sync: ${state.lastSyncLabel}")
            Text("SSH ready: ${state.automation.sshReady}")
            Text("SmartThings ready: ${state.automation.wakeReady}")
        }
    }
}

@Composable
private fun FakeSmokeSection() {
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Fake Remote Agent smoke", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
            Text("개발 중에는 fake Remote Agent와 adb reverse로 Home/Setup UI, PNG icon 전송, launch 계약을 먼저 검증합니다.")
            Text("실제 HomeworkHelper host pairing과 게임 실행은 별도 실기기 검증 단계에서 확인합니다.")
        }
    }
}
