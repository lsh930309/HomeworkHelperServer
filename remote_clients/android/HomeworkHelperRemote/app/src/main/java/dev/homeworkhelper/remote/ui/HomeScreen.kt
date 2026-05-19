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
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import dev.homeworkhelper.remote.data.RemoteAvailability
import dev.homeworkhelper.remote.data.RemoteProcess
import dev.homeworkhelper.remote.state.RemoteUiState

@Composable
fun HomeTab(
    state: RemoteUiState,
    onRefresh: () -> Unit,
    onLaunch: (RemoteProcess) -> Unit,
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
            HomeHeroCard(state = state, onRefresh = onRefresh)
            if (state.userMessage != null || state.availability != RemoteAvailability.Online) {
                StatusBanner(state)
            }
            GameList(state = state, onLaunch = onLaunch)
            PowerQuickRow(state = state)
        }
    }
}

@Composable
private fun HomeHeroCard(state: RemoteUiState, onRefresh: () -> Unit) {
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(20.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text("HomeworkHelper Remote", style = MaterialTheme.typography.headlineSmall)
                    Text("게임 상태와 빠른 실행", style = MaterialTheme.typography.titleMedium)
                }
                StatusChip(state.availability)
            }
            Text("마지막 동기화: ${state.lastSyncLabel}", style = MaterialTheme.typography.bodyMedium)
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
fun StatusChip(availability: RemoteAvailability) {
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
fun StatusBanner(state: RemoteUiState) {
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
    Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
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

@Composable
private fun EmptyGameList(state: RemoteUiState) {
    val text = if (state.hasToken) {
        "호스트에 등록된 게임이 없거나 아직 동기화되지 않았습니다."
    } else {
        "설정 탭에서 페어링하면 호스트에 등록된 게임 목록이 여기에 표시됩니다."
    }
    Card(modifier = Modifier.fillMaxWidth()) {
        Text(text, modifier = Modifier.padding(18.dp), style = MaterialTheme.typography.bodyMedium)
    }
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
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(16.dp),
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
            .size(52.dp)
            .clip(RoundedCornerShape(16.dp))
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
fun SmallBadge(label: String) {
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
private fun PowerQuickRow(state: RemoteUiState) {
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Text("원격 전원 관리", style = MaterialTheme.typography.titleMedium)
            Text(
                state.powerReadiness?.summary ?: "전원 준비 상태는 연결 후 표시됩니다.",
                style = MaterialTheme.typography.bodyMedium,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                DisabledPowerButton("깨우기", Modifier.weight(1f))
                DisabledPowerButton("절전", Modifier.weight(1f))
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                DisabledPowerButton("재시작", Modifier.weight(1f))
                DisabledPowerButton("종료", Modifier.weight(1f))
            }
            Text(
                "Android 전원 제어는 direct adapter 준비 후 활성화됩니다.",
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
fun DisabledPowerButton(label: String, modifier: Modifier = Modifier) {
    OutlinedButton(onClick = {}, enabled = false, modifier = modifier.height(48.dp)) {
        Text(label)
    }
}
