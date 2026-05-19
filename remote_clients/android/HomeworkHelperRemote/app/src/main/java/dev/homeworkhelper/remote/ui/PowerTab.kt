package dev.homeworkhelper.remote.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Card
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.ui.Modifier
import androidx.compose.runtime.Composable
import androidx.compose.ui.unit.dp
import dev.homeworkhelper.remote.state.RemoteUiState

@Composable
fun PowerTab(
    state: RemoteUiState,
    modifier: Modifier = Modifier,
) {
    Surface(modifier = modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Text("전원", style = MaterialTheme.typography.headlineMedium)
            PowerStatusCard(state)
            PowerActionsCard()
        }
    }
}

@Composable
private fun PowerStatusCard(state: RemoteUiState) {
    val power = state.powerReadiness
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text("전원 준비 상태", style = MaterialTheme.typography.titleLarge)
            Text(power?.summary ?: "Remote Agent 연결 후 전원 readiness를 확인합니다.")
            Text("Host: ${power?.status?.targetHost?.takeIf { it.isNotBlank() } ?: "미설정"}")
            Text("Status: ${power?.status?.status ?: power?.readiness?.state ?: "unknown"}")
            Text("SSH: ${power?.setup?.sshServiceMessage ?: "확인 전"}")
            power?.setup?.effectiveAuthorizedKeysPath?.let { Text("Authorized keys: $it") }
        }
    }
}

@Composable
private fun PowerActionsCard() {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Text("원격 전원 버튼", style = MaterialTheme.typography.titleLarge)
            Text(
                "Android 전원 제어는 direct adapter 준비 후 활성화됩니다. 현재 단계에서는 readiness만 표시하고 실제 명령은 실행하지 않습니다.",
                style = MaterialTheme.typography.bodyMedium,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                DisabledPowerButton("깨우기", Modifier.weight(1f).height(52.dp))
                DisabledPowerButton("절전", Modifier.weight(1f).height(52.dp))
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                DisabledPowerButton("재시작", Modifier.weight(1f).height(52.dp))
                DisabledPowerButton("종료", Modifier.weight(1f).height(52.dp))
            }
        }
    }
}
