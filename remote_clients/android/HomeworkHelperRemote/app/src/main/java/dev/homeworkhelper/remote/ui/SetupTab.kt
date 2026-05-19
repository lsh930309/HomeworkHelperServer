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
import androidx.compose.ui.unit.dp
import dev.homeworkhelper.remote.state.RemoteUiState

@Composable
fun SetupTab(
    state: RemoteUiState,
    onBaseUrlChange: (String) -> Unit,
    onDeviceNameChange: (String) -> Unit,
    onPair: (String) -> Unit,
    onClearToken: () -> Unit,
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
                "실제 절전/재시작/종료 명령은 Android direct adapter 준비 후 별도 단계에서 활성화됩니다.",
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
