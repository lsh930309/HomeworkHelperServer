package dev.homeworkhelper.remote.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import dev.homeworkhelper.remote.data.RemoteAvailability
import dev.homeworkhelper.remote.data.RemoteProcess
import dev.homeworkhelper.remote.state.RemoteUiState

@Composable
fun RemoteHomeScreen(
    state: RemoteUiState,
    onBaseUrlChange: (String) -> Unit,
    onDeviceNameChange: (String) -> Unit,
    onRefresh: () -> Unit,
    onPair: (String) -> Unit,
    onLaunch: (RemoteProcess) -> Unit,
    onClearToken: () -> Unit,
) {
    Scaffold { padding ->
        Surface(modifier = Modifier.fillMaxSize()) {
            Column(
                modifier = Modifier
                    .padding(padding)
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(20.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                HeaderCard(state = state, onRefresh = onRefresh)
                if (state.userMessage != null || state.availability != RemoteAvailability.Online) {
                    StatusBanner(state)
                }
                GameList(
                    state = state,
                    onLaunch = onLaunch,
                )
                ConnectionCard(
                    state = state,
                    onBaseUrlChange = onBaseUrlChange,
                    onDeviceNameChange = onDeviceNameChange,
                    onPair = onPair,
                    onClearToken = onClearToken,
                )
            }
        }
    }
}

@Composable
private fun HeaderCard(state: RemoteUiState, onRefresh: () -> Unit) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column {
                    Text("HomeworkHelper Remote", style = MaterialTheme.typography.headlineSmall)
                    Text("Home / Games", style = MaterialTheme.typography.titleMedium)
                }
                StatusChip(state.availability)
            }
            Text(
                text = "마지막 동기화: ${state.lastSyncLabel}",
                style = MaterialTheme.typography.bodyMedium,
            )
            Button(
                onClick = onRefresh,
                enabled = state.canRefresh,
                modifier = Modifier.fillMaxWidth(),
            ) {
                if (state.isRefreshing) {
                    CircularProgressIndicator(modifier = Modifier.size(18.dp), strokeWidth = 2.dp)
                    Spacer(modifier = Modifier.size(8.dp))
                }
                Text("새로고침")
            }
        }
    }
}

@Composable
private fun StatusChip(availability: RemoteAvailability) {
    val (label, color) = when (availability) {
        RemoteAvailability.Online -> "online" to Color(0xFF1B8A3A)
        RemoteAvailability.OfflineExpected -> "offline" to Color(0xFF8A5A00)
        RemoteAvailability.AgentUnavailable -> "agent unavailable" to Color(0xFFB3261E)
        RemoteAvailability.AuthRejected -> "auth rejected" to Color(0xFFB3261E)
        RemoteAvailability.Unknown -> "unknown" to Color(0xFF666666)
    }
    Text(
        text = label,
        color = Color.White,
        style = MaterialTheme.typography.labelMedium,
        modifier = Modifier
            .clip(RoundedCornerShape(999.dp))
            .background(color)
            .padding(horizontal = 10.dp, vertical = 6.dp),
    )
}

@Composable
private fun StatusBanner(state: RemoteUiState) {
    val container = when (state.availability) {
        RemoteAvailability.Online -> MaterialTheme.colorScheme.primaryContainer
        RemoteAvailability.AuthRejected -> MaterialTheme.colorScheme.errorContainer
        RemoteAvailability.AgentUnavailable -> MaterialTheme.colorScheme.errorContainer
        RemoteAvailability.OfflineExpected -> MaterialTheme.colorScheme.tertiaryContainer
        RemoteAvailability.Unknown -> MaterialTheme.colorScheme.surfaceVariant
    }
    Card(colors = CardDefaults.cardColors(containerColor = container)) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            Text(statusTitle(state.availability), fontWeight = FontWeight.Bold)
            state.userMessage?.let { Text(it, style = MaterialTheme.typography.bodyMedium) }
            state.hostMessage?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
        }
    }
}

private fun statusTitle(availability: RemoteAvailability): String {
    return when (availability) {
        RemoteAvailability.Online -> "연결됨"
        RemoteAvailability.OfflineExpected -> "호스트 오프라인"
        RemoteAvailability.AgentUnavailable -> "Remote Agent 확인 필요"
        RemoteAvailability.AuthRejected -> "페어링 복구 필요"
        RemoteAvailability.Unknown -> "연결 설정 필요"
    }
}

@Composable
private fun GameList(
    state: RemoteUiState,
    onLaunch: (RemoteProcess) -> Unit,
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text("등록된 게임", style = MaterialTheme.typography.titleLarge)
            if (state.processes.isEmpty()) {
                EmptyGameList(state)
            } else {
                state.processes.forEach { process ->
                    GameCard(state = state, process = process, onLaunch = onLaunch)
                }
            }
        }
    }
}

@Composable
private fun EmptyGameList(state: RemoteUiState) {
    val text = if (state.hasToken) {
        "호스트에 등록된 게임이 없거나 아직 동기화되지 않았습니다."
    } else {
        "페어링 후 호스트에 등록된 게임 목록이 여기에 표시됩니다."
    }
    Text(text, style = MaterialTheme.typography.bodyMedium)
}

@Composable
private fun GameCard(
    state: RemoteUiState,
    process: RemoteProcess,
    onLaunch: (RemoteProcess) -> Unit,
) {
    val launchEnabled = state.availability == RemoteAvailability.Online &&
        state.processLaunchEnabled &&
        state.launchInFlightId == null &&
        !state.isRefreshing &&
        !process.isRunning
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant),
    ) {
        Column(
            modifier = Modifier.padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Row(
                horizontalArrangement = Arrangement.spacedBy(12.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                GameIcon(process)
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = process.name,
                        style = MaterialTheme.typography.titleMedium,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Text(process.safeStatusText, style = MaterialTheme.typography.bodyMedium)
                }
                Button(
                    onClick = { onLaunch(process) },
                    enabled = launchEnabled,
                ) {
                    Text(if (state.launchInFlightId == process.id) "실행 중..." else "실행")
                }
            }
            process.progress?.let { progress ->
                LinearProgressIndicator(
                    progress = { (progress.percentage / 100.0).toFloat().coerceIn(0f, 1f) },
                    modifier = Modifier.fillMaxWidth(),
                )
                Text(
                    text = progress.displayText ?: "${progress.percentage.toInt()}%",
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (process.isRunning) SmallBadge("실행중")
                if (process.playedToday) SmallBadge("오늘 실행")
                if (state.availability != RemoteAvailability.Online) SmallBadge("stale")
            }
        }
    }
}

@Composable
private fun GameIcon(process: RemoteProcess) {
    Box(
        modifier = Modifier
            .size(48.dp)
            .clip(RoundedCornerShape(14.dp))
            .background(MaterialTheme.colorScheme.primaryContainer),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = process.name.take(1).ifBlank { "G" },
            style = MaterialTheme.typography.titleLarge,
            color = MaterialTheme.colorScheme.onPrimaryContainer,
            fontWeight = FontWeight.Bold,
        )
    }
}

@Composable
private fun SmallBadge(label: String) {
    Text(
        text = label,
        style = MaterialTheme.typography.labelSmall,
        modifier = Modifier
            .clip(RoundedCornerShape(999.dp))
            .background(MaterialTheme.colorScheme.secondaryContainer)
            .padding(horizontal = 8.dp, vertical = 4.dp),
    )
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
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text("연결 설정", style = MaterialTheme.typography.titleLarge)
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
            Text(
                "전원 제어와 Android-PC 링크는 다음 단계에서 별도 direct adapter가 준비된 뒤 활성화합니다.",
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}
