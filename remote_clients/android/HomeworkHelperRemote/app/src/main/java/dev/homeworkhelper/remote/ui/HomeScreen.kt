package dev.homeworkhelper.remote.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
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
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import coil3.compose.AsyncImage
import coil3.request.ImageRequest
import coil3.request.crossfade
import dev.homeworkhelper.remote.data.RemoteAvailability
import dev.homeworkhelper.remote.data.RemoteProcess
import dev.homeworkhelper.remote.data.RemoteProgress
import dev.homeworkhelper.remote.platform.PowerAction
import dev.homeworkhelper.remote.state.RemoteUiState

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeTab(
    state: RemoteUiState,
    onRefresh: () -> Unit,
    onLaunch: (RemoteProcess) -> Unit,
    onStopProcess: (RemoteProcess) -> Unit,
    onPowerAction: (PowerAction) -> Unit,
    modifier: Modifier = Modifier,
) {
    Surface(modifier = modifier.fillMaxSize(), color = MaterialTheme.colorScheme.background) {
        PullToRefreshBox(
            isRefreshing = state.isRefreshing,
            onRefresh = onRefresh,
            modifier = Modifier.fillMaxSize(),
        ) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(horizontal = 16.dp, vertical = 16.dp)
                    .padding(bottom = 92.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                HomeHeroCard(state = state)
                GameList(state = state, onLaunch = onLaunch, onStopProcess = onStopProcess)
                PowerQuickSection(state = state, onPowerAction = onPowerAction)
            }
        }
    }
}

@Composable
private fun HomeHeroCard(state: RemoteUiState) {
    ElevatedCard(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.elevatedCardColors(containerColor = MaterialTheme.colorScheme.surface),
    ) {
        Column(
            modifier = Modifier.padding(18.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.Top,
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text("HomeworkHelper Remote", style = MaterialTheme.typography.headlineSmall, fontWeight = FontWeight.Bold)
                    Text("게임 상태와 빠른 실행", style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                StatusChip(state.availability)
            }
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text("마지막 동기화: ${state.lastSyncLabel}", style = MaterialTheme.typography.bodyMedium)
                Text("아래로 당겨 새로고침", style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
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
        RemoteAvailability.Waking -> "waking" to Color(0xFF2563EB)
        RemoteAvailability.GoingOffline -> "powering off" to Color(0xFF8A5A00)
        RemoteAvailability.Restarting -> "restarting" to Color(0xFF2563EB)
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

private fun statusTitle(availability: RemoteAvailability): String {
    return when (availability) {
        RemoteAvailability.Online -> "연결됨"
        RemoteAvailability.OfflineExpected -> "호스트 오프라인"
        RemoteAvailability.AgentUnavailable -> "Remote Agent 확인 필요"
        RemoteAvailability.AuthRejected -> "페어링 복구 필요"
        RemoteAvailability.Waking -> "Wake 진행 중"
        RemoteAvailability.GoingOffline -> "전원 전환 중"
        RemoteAvailability.Restarting -> "재시작 중"
        RemoteAvailability.Unknown -> "연결 설정 필요"
    }
}

@Composable
private fun GameList(
    state: RemoteUiState,
    onLaunch: (RemoteProcess) -> Unit,
    onStopProcess: (RemoteProcess) -> Unit,
) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text("등록된 게임", style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.Bold)
            Text("${state.processes.size}개", style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        if (state.processes.isEmpty()) {
            EmptyGameList(state)
        } else {
            state.processes.forEach { process ->
                GameCard(state = state, process = process, onLaunch = onLaunch, onStopProcess = onStopProcess)
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
    onStopProcess: (RemoteProcess) -> Unit,
) {
    var pendingStop by remember(process.id) { mutableStateOf(false) }
    val launchEnabled = state.availability == RemoteAvailability.Online &&
        state.processLaunchEnabled &&
        state.launchInFlightId == null &&
        state.stopInFlightId == null &&
        !state.isRefreshing &&
        !process.isRunning
    val stopEnabled = state.availability == RemoteAvailability.Online &&
        state.processStopEnabled &&
        state.launchInFlightId == null &&
        state.stopInFlightId == null &&
        !state.isRefreshing &&
        process.isRunning
    ElevatedCard(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.elevatedCardColors(containerColor = MaterialTheme.colorScheme.surface),
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
                        fontWeight = FontWeight.SemiBold,
                    )
                    Text(process.safeStatusText, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                GameActionButton(
                    process = process,
                    launchPending = state.launchInFlightId == process.id,
                    stopPending = state.stopInFlightId == process.id,
                    launchEnabled = launchEnabled,
                    stopEnabled = stopEnabled,
                    onLaunch = onLaunch,
                    onStop = { pendingStop = true },
                )
            }
            process.progress?.let { progress -> ProgressLane(progress) }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                if (process.isRunning) RunningBadge()
                if (!process.isRunning && process.progress != null) ProgressBadge(process.progress)
                if (process.playedToday) SmallBadge("오늘 실행", BadgeTone.Neutral)
                if (state.availability != RemoteAvailability.Online) SmallBadge("stale", BadgeTone.Warning)
            }
        }
    }
    if (pendingStop) {
        AlertDialog(
            onDismissRequest = { pendingStop = false },
            title = { Text("${process.name} 중단") },
            text = { Text("호스트에서 실행 중인 게임 프로세스를 종료합니다. 저장되지 않은 인게임 상태가 있다면 먼저 확인하세요.") },
            confirmButton = {
                Button(
                    onClick = {
                        pendingStop = false
                        onStopProcess(process)
                    },
                    colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error),
                ) { Text("중단") }
            },
            dismissButton = { TextButton(onClick = { pendingStop = false }) { Text("취소") } },
        )
    }
}

@Composable
private fun GameActionButton(
    process: RemoteProcess,
    launchPending: Boolean,
    stopPending: Boolean,
    launchEnabled: Boolean,
    stopEnabled: Boolean,
    onLaunch: (RemoteProcess) -> Unit,
    onStop: () -> Unit,
) {
    if (process.isRunning) {
        Button(
            onClick = onStop,
            enabled = stopEnabled,
            shape = RoundedCornerShape(14.dp),
            colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error),
        ) {
            Text(if (stopPending) "중단 중..." else "■ 중단")
        }
    } else {
        Button(
            onClick = { onLaunch(process) },
            enabled = launchEnabled,
            shape = RoundedCornerShape(14.dp),
        ) {
            Text(if (launchPending) "실행 중..." else "▶ 실행")
        }
    }
}

@Composable
private fun GameIcon(process: RemoteProcess) {
    val iconUrl = process.preferredIconUrl
    var iconLoaded by remember(iconUrl) { mutableStateOf(false) }
    var iconFailed by remember(iconUrl) { mutableStateOf(false) }
    Box(
        modifier = Modifier
            .size(54.dp)
            .clip(RoundedCornerShape(16.dp))
            .background(MaterialTheme.colorScheme.primaryContainer)
            .border(1.dp, MaterialTheme.colorScheme.outlineVariant, RoundedCornerShape(16.dp)),
        contentAlignment = Alignment.Center,
    ) {
        Text(
            text = if (iconFailed) "!" else process.name.take(1).ifBlank { "G" },
            style = MaterialTheme.typography.titleLarge,
            color = (if (iconFailed) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onPrimaryContainer).copy(alpha = if (iconLoaded) 0f else 1f),
            fontWeight = FontWeight.Bold,
        )
        if (iconUrl != null) {
            AsyncImage(
                model = ImageRequest.Builder(LocalContext.current)
                    .data(iconUrl)
                    .crossfade(true)
                    .build(),
                contentDescription = "${process.name} 아이콘",
                contentScale = ContentScale.Crop,
                modifier = Modifier.fillMaxSize(),
                onSuccess = { iconLoaded = true; iconFailed = false },
                onError = { iconLoaded = false; iconFailed = true },
            )
        }
    }
}

@Composable
private fun ProgressLane(progress: RemoteProgress) {
    val nowSeconds = System.currentTimeMillis() / 1000.0
    val percentage = progress.projectedPercentage(nowSeconds)
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        ResourceIcon(progress)
        Column(modifier = Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            LinearProgressIndicator(
                progress = { (percentage / 100.0).toFloat().coerceIn(0f, 1f) },
                modifier = Modifier.fillMaxWidth().height(7.dp).clip(RoundedCornerShape(999.dp)),
                color = MaterialTheme.colorScheme.primary,
                trackColor = MaterialTheme.colorScheme.surfaceVariant,
            )
            Text(
                text = "${progress.projectedDisplayText(nowSeconds)} · ${progress.sourceLabel}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}

@Composable
private fun ResourceIcon(progress: RemoteProgress) {
    val iconUrl = progress.preferredResourceIconUrl
    var iconLoaded by remember(iconUrl) { mutableStateOf(false) }
    var iconFailed by remember(iconUrl) { mutableStateOf(false) }
    Box(
        modifier = Modifier
            .size(28.dp)
            .clip(RoundedCornerShape(9.dp))
            .background(MaterialTheme.colorScheme.secondaryContainer),
        contentAlignment = Alignment.Center,
    ) {
        if (!iconLoaded) {
            Text(if (iconFailed) "!" else "↻", style = MaterialTheme.typography.labelMedium, color = if (iconFailed) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSecondaryContainer)
        }
        if (iconUrl != null) {
            AsyncImage(
                model = ImageRequest.Builder(LocalContext.current)
                    .data(iconUrl)
                    .crossfade(true)
                    .build(),
                contentDescription = "진행도 리소스 아이콘",
                contentScale = ContentScale.Fit,
                modifier = Modifier.padding(4.dp).fillMaxSize(),
                onSuccess = { iconLoaded = true; iconFailed = false },
                onError = { iconLoaded = false; iconFailed = true },
            )
        }
    }
}

@Composable
private fun RunningBadge() {
    Text(
        text = "실행중",
        color = Color.White,
        style = MaterialTheme.typography.labelSmall,
        fontWeight = FontWeight.Bold,
        modifier = Modifier
            .clip(RoundedCornerShape(999.dp))
            .background(Brush.horizontalGradient(listOf(Color(0xFF2563EB), Color(0xFF14B8A6))))
            .width(92.dp)
            .padding(horizontal = 8.dp, vertical = 5.dp),
    )
}

@Composable
private fun ProgressBadge(progress: RemoteProgress) {
    val text = progress.projectedDisplayText()
    Text(
        text = text,
        style = MaterialTheme.typography.labelSmall,
        maxLines = 1,
        overflow = TextOverflow.Ellipsis,
        modifier = Modifier
            .clip(RoundedCornerShape(999.dp))
            .background(MaterialTheme.colorScheme.primaryContainer)
            .width(92.dp)
            .padding(horizontal = 8.dp, vertical = 5.dp),
        color = MaterialTheme.colorScheme.onPrimaryContainer,
    )
}

enum class BadgeTone { Neutral, Warning }

@Composable
fun SmallBadge(label: String, tone: BadgeTone = BadgeTone.Neutral) {
    val colors = when (tone) {
        BadgeTone.Neutral -> MaterialTheme.colorScheme.secondaryContainer to MaterialTheme.colorScheme.onSecondaryContainer
        BadgeTone.Warning -> MaterialTheme.colorScheme.tertiaryContainer to MaterialTheme.colorScheme.onTertiaryContainer
    }
    Text(
        text = label,
        style = MaterialTheme.typography.labelSmall,
        color = colors.second,
        modifier = Modifier
            .clip(RoundedCornerShape(999.dp))
            .background(colors.first)
            .padding(horizontal = 8.dp, vertical = 4.dp),
    )
}

@Composable
private fun PowerQuickSection(
    state: RemoteUiState,
    onPowerAction: (PowerAction) -> Unit,
) {
    var pendingAction by remember { mutableStateOf<PowerAction?>(null) }
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            Text("원격 전원 관리", style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
            Text(
                state.powerReadiness?.summary ?: "전원 준비 상태는 연결 후 표시됩니다.",
                style = MaterialTheme.typography.bodyMedium,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                PowerButton(
                    action = PowerAction.Wake,
                    enabled = state.automation.wakeReady && state.automation.powerActionInFlight == null,
                    inFlight = state.automation.powerActionInFlight == PowerAction.Wake,
                    modifier = Modifier.weight(1f),
                    onClick = onPowerAction,
                )
                PowerButton(
                    action = PowerAction.Sleep,
                    enabled = state.supportsHostPowerAction(PowerAction.Sleep) && state.automation.powerActionInFlight == null,
                    inFlight = state.automation.powerActionInFlight == PowerAction.Sleep,
                    modifier = Modifier.weight(1f),
                    onClick = { pendingAction = it },
                )
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                PowerButton(
                    action = PowerAction.Restart,
                    enabled = state.supportsHostPowerAction(PowerAction.Restart) && state.automation.powerActionInFlight == null,
                    inFlight = state.automation.powerActionInFlight == PowerAction.Restart,
                    modifier = Modifier.weight(1f),
                    onClick = { pendingAction = it },
                )
                PowerButton(
                    action = PowerAction.Shutdown,
                    enabled = state.supportsHostPowerAction(PowerAction.Shutdown) && state.automation.powerActionInFlight == null,
                    inFlight = state.automation.powerActionInFlight == PowerAction.Shutdown,
                    modifier = Modifier.weight(1f),
                    onClick = { pendingAction = it },
                )
            }
            Text(
                powerHint(state),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
    pendingAction?.let { action ->
        AlertDialog(
            onDismissRequest = { pendingAction = null },
            title = { Text("${action.label} 실행") },
            text = { Text("호스트 PC에 ${action.label} 명령을 전송합니다. 현재 작업을 저장했는지 확인하세요.") },
            confirmButton = {
                Button(onClick = { pendingAction = null; onPowerAction(action) }) { Text("실행") }
            },
            dismissButton = {
                TextButton(onClick = { pendingAction = null }) { Text("취소") }
            },
        )
    }
}

@Composable
private fun PowerButton(
    action: PowerAction,
    enabled: Boolean,
    inFlight: Boolean,
    modifier: Modifier = Modifier,
    onClick: (PowerAction) -> Unit,
) {
    OutlinedButton(onClick = { onClick(action) }, enabled = enabled, modifier = modifier.height(46.dp)) {
        Text(if (inFlight) "처리 중" else action.label)
    }
}

private fun powerHint(state: RemoteUiState): String {
    return when {
        !state.automation.wakeReady && !state.hostDelegatedPowerReady -> "설정 탭에서 SmartThings 인증+PC 켜기 deviceId와 Host 위임 전원 상태를 확인하세요."
        !state.automation.wakeReady -> "Wake는 SmartThings PAT/OAuth 인증과 PC 켜기 deviceId가 모두 있어야 활성화됩니다."
        !state.hostDelegatedPowerReady -> "절전/재시작/종료는 공개 HTTPS Remote Agent의 Host 위임 전원 준비 후 활성화됩니다."
        else -> "Wake는 SmartThings REST API, 나머지 전원 명령은 Host HTTPS 위임으로 실행합니다."
    }
}
