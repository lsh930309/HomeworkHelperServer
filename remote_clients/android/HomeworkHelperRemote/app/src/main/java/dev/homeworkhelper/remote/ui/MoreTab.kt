package dev.homeworkhelper.remote.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import dev.homeworkhelper.remote.state.RemoteUiState

@Composable
fun MoreTab(
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
            Text("더보기", style = MaterialTheme.typography.headlineMedium)
            DiagnosticsCard(state)
            FakeSmokeCard()
        }
    }
}

@Composable
private fun DiagnosticsCard(state: RemoteUiState) {
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("진단", style = MaterialTheme.typography.titleLarge)
            Text("Availability: ${state.availability}")
            Text("Base URL: ${state.baseUrl.ifBlank { "미설정" }}")
            Text("Token: ${if (state.hasToken) "저장됨" else "없음"}")
            Text("Games: ${state.processes.size}")
            Text("Last sync: ${state.lastSyncLabel}")
        }
    }
}

@Composable
private fun FakeSmokeCard() {
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(18.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Fake Remote Agent smoke", style = MaterialTheme.typography.titleLarge)
            Text("개발 중에는 fake Remote Agent와 adb reverse로 Home/Power/Setup UI 계약을 먼저 검증합니다.")
            Text("실제 HomeworkHelper host pairing과 게임 실행은 별도 실기기 검증 단계에서 확인합니다.")
        }
    }
}
