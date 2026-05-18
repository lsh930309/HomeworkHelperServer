package dev.homeworkhelper.remote.ui

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.isSystemInDarkTheme
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
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AssistChip
import androidx.compose.material3.Button
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.net.HttpURLConnection
import java.net.URL
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import dev.homeworkhelper.remote.ReadinessSection
import dev.homeworkhelper.remote.RemoteAppState
import dev.homeworkhelper.remote.RemoteAppViewModel
import dev.homeworkhelper.remote.RemoteBeholderIncident
import dev.homeworkhelper.remote.RemoteDevice
import dev.homeworkhelper.remote.RemoteGameLink
import dev.homeworkhelper.remote.RemoteMobileSession
import dev.homeworkhelper.remote.RemotePowerConfigPayload
import dev.homeworkhelper.remote.RemoteProcess
import dev.homeworkhelper.remote.RemoteShortcut
import dev.homeworkhelper.remote.RemoteTab
import dev.homeworkhelper.remote.formatDuration

@Composable
fun RemoteApp(viewModel: RemoteAppViewModel) {
    val state = viewModel.state
    val darkTheme = isSystemInDarkTheme()
    val listState = rememberLazyListState()
    LaunchedEffect(darkTheme) {
        viewModel.updateSystemDarkMode(darkTheme)
    }
    LaunchedEffect(state.selectedTab) {
        listState.scrollToItem(0)
    }
    Scaffold(
        bottomBar = {
            NavigationBar {
                RemoteTab.entries.forEach { tab ->
                    NavigationBarItem(
                        selected = state.selectedTab == tab,
                        onClick = { viewModel.updateSelectedTab(tab) },
                        icon = { Text(tab.symbol) },
                        label = { Text(tab.label) },
                    )
                }
            }
        },
    ) { padding ->
        LazyColumn(
            state = listState,
            modifier = Modifier
                .fillMaxSize()
                .background(MaterialTheme.colorScheme.background)
                .padding(padding)
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            item { HeaderCard(state, viewModel) }
            if (state.offline || state.authRejected || state.partialErrors.isNotEmpty()) {
                item { DiagnosticBanner(state) }
            }
            if (state.snapshotIsStale) {
                item { StaleSnapshotBanner(state) }
            }
            when (state.selectedTab) {
                RemoteTab.DASHBOARD -> {
                    item { ConnectionCard(state, viewModel) }
                    item { ReadinessCard(state, viewModel) }
                    item { PowerQuickActionsCard(state, viewModel) }
                    if (state.showPlaySummary) {
                        state.dashboardSummary?.let { summary -> item { DashboardSummaryCard(state) } }
                    }
                    item { BeholderCard(state.beholderIncidents) }
                }
                RemoteTab.LIBRARY -> {
                    item { LibrarySummaryCard(state, viewModel) }
                    if (state.processes.isEmpty()) {
                        item { EmptyCard("게임", "새로고침 후 PC 게임 목록이 여기에 표시됩니다.") }
                    } else {
                        items(state.processes, key = { it.id }) { process -> ProcessCard(process, viewModel) }
                    }
                    if (state.shortcuts.isEmpty()) {
                        item { EmptyCard("웹 숏컷", "등록된 웹 숏컷이 없습니다.") }
                    } else {
                        item { SectionTitle("웹 숏컷") }
                        items(state.shortcuts, key = { it.id }) { shortcut -> ShortcutCard(shortcut, viewModel) }
                    }
                }
                RemoteTab.LINKS -> {
                    if (state.gameLinks.isEmpty()) {
                        item { EmptyCard("연결된 앱 없음", "PC process ID와 Android package name을 연결하면 모바일 플레이 세션을 기록할 수 있습니다.") }
                    } else {
                        item { SectionTitle("연결된 앱") }
                        items(state.gameLinks, key = { it.id }) { link -> GameLinkCard(link, viewModel) }
                    }
                    item { UsageStatsCard(state, viewModel) }
                    item { AndroidPcLinkForm(state, viewModel) }
                }
                RemoteTab.SETTINGS -> {
                    item { SettingsCard(state, viewModel) }
                    item { PowerSettingsCard(state, viewModel) }
                    item { LoggingCard(state, viewModel) }
                    if (state.devices.isNotEmpty()) {
                        item { SectionTitle("등록 디바이스") }
                        items(state.devices, key = { it.id }) { device -> DeviceCard(device, viewModel) }
                    }
                }
            }
        }
    }
}

@Composable
private fun HeaderCard(state: RemoteAppState, viewModel: RemoteAppViewModel) {
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Box(
                    modifier = Modifier
                        .size(42.dp)
                        .background(MaterialTheme.colorScheme.primaryContainer, CircleShape),
                    contentAlignment = Alignment.Center,
                ) { Text("HH", color = MaterialTheme.colorScheme.onPrimaryContainer) }
                Column(Modifier.weight(1f)) {
                    Text("HomeworkHelper Remote", style = MaterialTheme.typography.titleLarge)
                    Text("Tailscale-first Android client", style = MaterialTheme.typography.bodySmall)
                }
                StatusDot(headerStatusColor(state))
            }
            Text(state.message, style = MaterialTheme.typography.bodyMedium)
            Text(
                "${headerStatusLabel(state)} · 시스템 ${state.systemThemeLabel} 모드 추적 중" +
                    if (state.lastSyncedAtMillis > 0L) " · 마지막 동기화 ${formatClock(state.lastSyncedAtMillis)}" else "",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { viewModel.refresh() }, enabled = !state.isLoading) { Text("새로고침") }
                OutlinedButton(onClick = { viewModel.openTailscale() }) { Text(if (state.tailscaleInstalled) "Tailscale 열기" else "Tailscale 설치") }
                OutlinedButton(onClick = { viewModel.ensureServerTailscale() }, enabled = state.tokenPresent) { Text("Host Tailscale") }
            }
        }
    }
}

@Composable
private fun DiagnosticBanner(state: RemoteAppState) {
    val text = when {
        state.baseUrlError.isNotBlank() -> state.baseUrlError
        state.authRejected -> "인증이 거부되었습니다. 토큰 갱신 또는 pairing code로 복구하세요."
        state.offline && looksLikeLoopbackUrl(state.baseUrl) -> "현재 URL은 ADB reverse/로컬 테스트용입니다. 실사용은 Tailscale 추천 URL을 적용하거나 adb reverse를 다시 연결하세요."
        state.offline -> "Remote Agent에 닿지 않습니다. Tailscale 연결, URL, 서버 실행 상태를 확인하세요."
        else -> "일부 API가 실패했습니다: ${state.partialErrors.take(2).joinToString(" / ")}"
    }
    Surface(color = MaterialTheme.colorScheme.errorContainer, modifier = Modifier.fillMaxWidth()) {
        Text(text, modifier = Modifier.padding(12.dp), color = MaterialTheme.colorScheme.onErrorContainer)
    }
}

@Composable
private fun StaleSnapshotBanner(state: RemoteAppState) {
    Surface(color = MaterialTheme.colorScheme.tertiaryContainer, modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text("마지막 성공 데이터 표시 중", color = MaterialTheme.colorScheme.onTertiaryContainer)
            Text(
                state.snapshotStaleReason,
                color = MaterialTheme.colorScheme.onTertiaryContainer,
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

@Composable
private fun ConnectionCard(state: RemoteAppState, viewModel: RemoteAppViewModel) {
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("연결과 페어링", style = MaterialTheme.typography.titleMedium)
            OutlinedTextField(
                value = state.baseUrl,
                onValueChange = viewModel::updateBaseUrl,
                label = { Text("Remote Agent URL") },
                isError = state.baseUrlError.isNotBlank(),
                supportingText = if (state.baseUrlError.isNotBlank()) {
                    { Text(state.baseUrlError) }
                } else {
                    { Text("Tailscale IP 또는 Remote Agent 주소를 입력하세요.") }
                },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedTextField(
                    value = state.deviceName,
                    onValueChange = viewModel::updateDeviceName,
                    label = { Text("Device name") },
                    singleLine = true,
                    modifier = Modifier.weight(1f),
                )
                OutlinedTextField(
                    value = state.token,
                    onValueChange = viewModel::updateToken,
                    label = { Text("Bearer token") },
                    visualTransformation = PasswordVisualTransformation(),
                    singleLine = true,
                    modifier = Modifier.weight(1f),
                )
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { viewModel.saveConnection() }) { Text("저장") }
                OutlinedButton(onClick = { viewModel.clearLocalToken() }) { Text("토큰 삭제") }
                OutlinedButton(onClick = { viewModel.refreshToken() }, enabled = state.tokenPresent) { Text("토큰 갱신") }
            }
            OutlinedTextField(
                value = state.pairingCode,
                onValueChange = viewModel::updatePairingCode,
                label = { Text("Pairing code") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            Button(onClick = { viewModel.confirmPairing() }, enabled = state.pairingCode.length == 6) { Text("페어링 완료") }
        }
    }
}

@Composable
private fun ReadinessCard(state: RemoteAppState, viewModel: RemoteAppViewModel) {
    val readiness = state.readiness
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("상태 한눈에 보기", style = MaterialTheme.typography.titleMedium)
            if (readiness == null) {
                Text("새로고침하면 readiness, Tailscale, 인증, 전원 상태가 카드로 표시됩니다.")
            } else {
                ReadinessRow("Tailscale", readiness.tailscaleReadiness)
                readiness.tailscaleReadiness.suggestedBaseUrls.firstOrNull()?.let { suggested ->
                    AssistChip(onClick = { viewModel.applySuggestedBaseUrl(suggested) }, label = { Text("추천 URL 적용: $suggested") })
                }
                ReadinessRow("Remote 인증", readiness.remoteConnectivity)
                ReadinessRow("서버 모드", readiness.serverModeReadiness)
                ReadinessRow("전원", readiness.powerReadiness)
                ReadinessRow("Beholder", readiness.beholderHealth)
            }
            state.status?.let { current ->
                Text("API ${current.apiVersion} · 게임 ${current.processCount}개 / 숏컷 ${current.shortcutCount}개 / PC 활성 세션 ${current.activeSessionCount}개")
                Text("Android-PC 연결: ${if (current.gameLinks) "${state.gameLinks.size}개" else "미지원"} · 활성 모바일 세션: ${if (current.mobileSessions) "${state.mobileSessions.size}개" else "미지원"}")
            }
        }
    }
}

@Composable
private fun ReadinessRow(title: String, section: ReadinessSection) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        StatusDot(section.color)
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge)
            Text(section.message, style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
private fun PowerQuickActionsCard(state: RemoteAppState, viewModel: RemoteAppViewModel) {
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("전원 빠른 실행", style = MaterialTheme.typography.titleMedium)
            val power = state.status?.power
            if (power == null || power.configured.not()) {
                Text("클라이언트 직접 전원 경로(SmartThings/OpenSSH)가 준비되지 않아 전원 버튼을 비활성화했습니다.")
            } else {
                Text("전원 상태: ${power.status} · 지원 명령: ${if (power.supportedActions.isEmpty()) "전체" else power.supportedActions.joinToString(", ")}")
                Text("Android 직접 SmartThings/OpenSSH 실행 경로가 구현되기 전까지 버튼은 비활성화됩니다.", style = MaterialTheme.typography.bodySmall)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (power == null || power.configured.not()) {
                    OutlinedButton(onClick = { viewModel.updateSelectedTab(RemoteTab.SETTINGS) }) { Text("전원 설정 열기") }
                } else {
                    Button(onClick = { viewModel.powerCommand("wake") }, enabled = viewModel.isPowerActionEnabled("wake")) { Text("켜기") }
                    Button(onClick = { viewModel.powerCommand("sleep") }, enabled = viewModel.isPowerActionEnabled("sleep")) { Text("절전") }
                    Button(onClick = { viewModel.powerCommand("restart") }, enabled = viewModel.isPowerActionEnabled("restart")) { Text("재시작") }
                    Button(onClick = { viewModel.powerCommand("shutdown") }, enabled = viewModel.isPowerActionEnabled("shutdown")) { Text("끄기") }
                }
            }
        }
    }
}

@Composable
private fun DashboardSummaryCard(state: RemoteAppState) {
    val summary = state.dashboardSummary ?: return
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("플레이 요약", style = MaterialTheme.typography.titleMedium)
            Text("${summary.rangeStart} ~ ${summary.rangeEnd}")
            Text("총 플레이 ${formatDuration(summary.totalSeconds)} / 일평균 ${formatDuration(summary.dailyAverageSeconds)}")
            Text("세션 ${summary.sessionCount}개 / 플레이 일수 ${summary.playedDays}일")
            if (summary.topGameName.isNotBlank()) Text("Top: ${summary.topGameName} · ${formatDuration(summary.topGameSeconds)}")
            Text("모바일 플레이 ${formatDuration(summary.mobileTotalSeconds)} / 모바일 세션 ${summary.mobileSessionCount}개")
            if (summary.mobileActiveSessionCount > 0) Text("활성 모바일 ${summary.mobileActiveSessionCount}개 · ${formatDuration(summary.mobileActiveSeconds)}")
            if (summary.mobileTopGameName.isNotBlank()) Text("Mobile Top: ${summary.mobileTopGameName} · ${summary.mobileTopAndroidPackageName} · ${formatDuration(summary.mobileTopGameSeconds)}")
        }
    }
}

@Composable
private fun BeholderCard(incidents: List<RemoteBeholderIncident>) {
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Beholder 알림", style = MaterialTheme.typography.titleMedium)
            if (incidents.isEmpty()) {
                Text("대기 중인 incident가 없습니다.")
            } else {
                incidents.take(4).forEach { IncidentRow(it) }
            }
        }
    }
}

@Composable
private fun IncidentRow(incident: RemoteBeholderIncident) {
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.Top) {
        StatusDot(if (incident.riskScore >= 70) "red" else if (incident.riskScore >= 40) "yellow" else "green")
        Column(Modifier.weight(1f)) {
            Text(incident.userTitle.ifBlank { "Incident ${incident.id}" }, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text("위험도 ${incident.riskScore} · ${incident.severity} · ${incident.status}", style = MaterialTheme.typography.bodySmall)
            if (incident.userSummary.isNotBlank()) Text(incident.userSummary, style = MaterialTheme.typography.bodySmall)
            if (incident.riskLabels.isNotEmpty()) Text(incident.riskLabels.joinToString(", "), style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
private fun LibrarySummaryCard(state: RemoteAppState, viewModel: RemoteAppViewModel) {
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("게임 라이브러리", style = MaterialTheme.typography.titleMedium)
            Text("프로세스 ${state.processes.size}개 · 숏컷 ${state.shortcuts.size}개")
            Button(onClick = { viewModel.refresh() }) { Text("게임/숏컷 새로고침") }
        }
    }
}

@Composable
private fun ProcessCard(process: RemoteProcess, viewModel: RemoteAppViewModel) {
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Row(Modifier.padding(14.dp), horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically) {
            RemoteIcon(
                baseUrl = viewModel.state.baseUrl,
                token = viewModel.state.token,
                path = process.iconUrl,
                cacheRevision = viewModel.state.iconCacheRevision,
                fallback = if (process.playedToday) "★" else "▶",
                running = process.isRunning,
            )
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(process.name, style = MaterialTheme.typography.titleSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
                Text(process.statusText.ifBlank { "PC 실행: ${process.preferredLaunchType}" }, style = MaterialTheme.typography.bodySmall)
                process.progress?.let { progress ->
                    val value = (progress.percentage / 100.0).toFloat().coerceIn(0f, 1f)
                    LinearProgressIndicator(progress = { value }, modifier = Modifier.fillMaxWidth())
                    Text(progress.displayText.ifBlank { "progress ${progress.percentage.toInt()}%" }, style = MaterialTheme.typography.bodySmall)
                }
            }
            Button(onClick = { viewModel.launchProcess(process) }) { Text("PC 실행") }
        }
    }
}

@Composable
private fun ShortcutCard(shortcut: RemoteShortcut, viewModel: RemoteAppViewModel) {
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Row(Modifier.padding(14.dp), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(shortcut.name, style = MaterialTheme.typography.titleSmall)
                Text(shortcut.url, style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
            Button(onClick = { viewModel.openShortcut(shortcut) }) { Text("열기") }
        }
    }
}

@Composable
private fun AndroidPcLinkForm(state: RemoteAppState, viewModel: RemoteAppViewModel) {
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("새 Android-PC 연결 추가", style = MaterialTheme.typography.titleMedium)
            Text("PC process와 Android package를 연결하면 같은 대시보드에 모바일 세션이 기록됩니다.")
            OutlinedTextField(
                value = state.gameLinkProcessId,
                onValueChange = viewModel::updateGameLinkProcessId,
                label = { Text("PC process ID") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                value = state.gameLinkPackageName,
                onValueChange = viewModel::updateGameLinkPackageName,
                label = { Text("Android package name") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            Button(onClick = { viewModel.createGameLink() }) { Text("Android-PC 연결 저장") }
        }
    }
}

@Composable
private fun UsageStatsCard(state: RemoteAppState, viewModel: RemoteAppViewModel) {
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Android 로컬 실행 / UsageStats", style = MaterialTheme.typography.titleMedium)
            OutlinedTextField(
                value = state.androidPackageName,
                onValueChange = viewModel::updateAndroidPackageName,
                label = { Text("Android package name") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { viewModel.launchAndroidPackage() }) { Text("앱 실행") }
                OutlinedButton(onClick = { viewModel.openUsageAccessSettings() }) { Text("Usage 권한") }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = { viewModel.syncUsageStatsSessions() }, enabled = state.gameLinks.isNotEmpty()) { Text("Usage 동기화") }
                OutlinedButton(onClick = { viewModel.probeRecentUsage() }) { Text("최근 앱") }
            }
            Text("Usage Access: ${if (state.usageAccessGranted) "허용됨" else "미허용"}")
            state.recentUsage?.let { usage -> Text("최근 전면 앱: ${usage.packageName}") }
        }
    }
}

@Composable
private fun GameLinkCard(link: RemoteGameLink, viewModel: RemoteAppViewModel) {
    val activeSession: RemoteMobileSession? = viewModel.activeMobileSession(link)
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Row(Modifier.padding(14.dp), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
                Text(link.pcDisplayName.ifBlank { link.pcProcessId }, style = MaterialTheme.typography.titleSmall)
                Text(link.androidPackageName, style = MaterialTheme.typography.bodySmall)
                Text("동기화: ${link.syncStrategy.ifBlank { "manual" }}", style = MaterialTheme.typography.bodySmall)
                if (link.platformAccountHint.isNotBlank() && link.platformAccountHint != "null") {
                    Text(link.platformAccountHint, style = MaterialTheme.typography.bodySmall)
                }
            }
            Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Button(onClick = { viewModel.launchAndroidPackage(link.androidPackageName) }) { Text("Android 실행") }
                if (activeSession == null) {
                    OutlinedButton(onClick = { viewModel.startMobileSession(link) }) { Text("모바일 시작") }
                } else {
                    OutlinedButton(onClick = { viewModel.endMobileSession(activeSession) }) { Text("모바일 종료") }
                }
            }
        }
    }
}

@Composable
private fun SettingsCard(state: RemoteAppState, viewModel: RemoteAppViewModel) {
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("앱 설정", style = MaterialTheme.typography.titleMedium)
            Text("시스템 테마: ${state.systemThemeLabel} · 앱 색상과 상태바가 자동으로 따라갑니다.", style = MaterialTheme.typography.bodySmall)
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("플레이 요약 표시", modifier = Modifier.weight(1f))
                Switch(checked = state.showPlaySummary, onCheckedChange = viewModel::updateShowPlaySummary)
            }
            OutlinedTextField(
                value = state.refreshIntervalSeconds.toString(),
                onValueChange = viewModel::updateRefreshInterval,
                label = { Text("Refresh interval seconds") },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedTextField(
                value = state.progressMode,
                onValueChange = viewModel::updateProgressMode,
                label = { Text("Progress display mode") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { viewModel.saveUiSettings() }) { Text("표시 설정 저장") }
                OutlinedButton(onClick = { viewModel.clearIconCache() }) { Text("아이콘 캐시 새로고침") }
                OutlinedButton(onClick = { viewModel.openAppSettings() }) { Text("Android 앱 설정") }
            }
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                OutlinedButton(onClick = { viewModel.refresh(includeDevices = true) }, enabled = state.tokenPresent) { Text("디바이스 조회") }
                OutlinedButton(onClick = { viewModel.purgeRevokedDevices() }, enabled = state.tokenPresent) { Text("폐기 토큰 정리") }
            }
        }
    }
}

@Composable
private fun PowerSettingsCard(state: RemoteAppState, viewModel: RemoteAppViewModel) {
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("전원 설정", style = MaterialTheme.typography.titleMedium)
            state.powerSetup?.let { setup ->
                Text("Host ${setup.hostPlatform} · SSH ${if (setup.sshService.running) "실행 중" else "확인 필요"} · SmartThings ${if (setup.smartthingsReady) "준비됨" else "미설정"}")
                if (setup.message.isNotBlank()) Text(setup.message, style = MaterialTheme.typography.bodySmall)
            }
            state.powerConfigResponse?.let { response ->
                Text("설정 파일: ${fileName(response.configPath).ifBlank { "remote_power_config.json" }}")
                if (response.configPath.isNotBlank()) {
                    Text("경로: ${response.configPath}", style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
                Text("지원 명령: ${if (response.supportedActions.isEmpty()) "없음" else response.supportedActions.joinToString(", ")}")
            }
            PowerField("SmartThings device id", state.powerConfig.smartthingsDeviceId) { viewModel.updatePowerConfig(state.powerConfig.copy(smartthingsDeviceId = it)) }
            PowerField("SmartThings CLI path", state.powerConfig.smartthingsCliPath) { viewModel.updatePowerConfig(state.powerConfig.copy(smartthingsCliPath = it)) }
            PowerField("SSH host", state.powerConfig.sshHost) { viewModel.updatePowerConfig(state.powerConfig.copy(sshHost = it)) }
            PowerField("SSH user", state.powerConfig.sshUser) { viewModel.updatePowerConfig(state.powerConfig.copy(sshUser = it)) }
            PowerField("SSH key path", state.powerConfig.sshKeyPath) { viewModel.updatePowerConfig(state.powerConfig.copy(sshKeyPath = it)) }
            OutlinedTextField(
                value = state.powerConfig.sshPort.toString(),
                onValueChange = { viewModel.updatePowerConfig(state.powerConfig.copy(sshPort = it.toIntOrNull() ?: 22)) },
                label = { Text("SSH port") },
                singleLine = true,
                modifier = Modifier.fillMaxWidth(),
            )
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Button(onClick = { viewModel.savePowerConfig() }) { Text("전원 설정 저장") }
                OutlinedButton(onClick = { viewModel.probeSmartThingsDevices() }) { Text("SmartThings 조회") }
            }
            state.smartThingsProbe?.let { probe -> Text(probe.message.ifBlank { "SmartThings candidates: ${probe.deviceCandidates.size}" }) }
            OutlinedTextField(
                value = state.sshPublicKey,
                onValueChange = viewModel::updateSshPublicKey,
                label = { Text("SSH public key") },
                modifier = Modifier.fillMaxWidth(),
            )
            OutlinedButton(onClick = { viewModel.registerPowerSshKey() }) { Text("SSH key 등록") }
            Text("저장은 remote_power_config.json만 갱신하며 전원 명령은 실행하지 않습니다.", style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
private fun LoggingCard(state: RemoteAppState, viewModel: RemoteAppViewModel) {
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("Diagnostic logging", style = MaterialTheme.typography.titleMedium)
            val enabled = state.loggingConfig?.enabled == true
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("Remote logging", modifier = Modifier.weight(1f))
                Switch(checked = enabled, onCheckedChange = { viewModel.saveRemoteLogging(it) })
            }
            Text(state.loggingConfig?.path?.ifBlank { "Remote log path 미설정" } ?: "새로고침 후 logging config가 표시됩니다.")
        }
    }
}

@Composable
private fun DeviceCard(device: RemoteDevice, viewModel: RemoteAppViewModel) {
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Row(Modifier.padding(14.dp), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(device.deviceName, style = MaterialTheme.typography.titleSmall)
                Text(device.platform)
                if (device.tokenRefreshedAt.isNotBlank()) Text("refreshed: ${device.tokenRefreshedAt}", style = MaterialTheme.typography.bodySmall)
                if (device.revokedAt.isNotBlank()) Text("revoked: ${device.revokedAt}", style = MaterialTheme.typography.bodySmall)
            }
            Button(onClick = { viewModel.revokeDevice(device) }, enabled = device.revokedAt.isBlank()) { Text("폐기") }
        }
    }
}

@Composable
private fun PowerField(label: String, value: String, onChange: (String) -> Unit) {
    OutlinedTextField(value = value, onValueChange = onChange, label = { Text(label) }, singleLine = true, modifier = Modifier.fillMaxWidth())
}

@Composable
private fun SectionTitle(text: String) {
    Text(text, style = MaterialTheme.typography.titleMedium)
}

@Composable
private fun EmptyCard(title: String, body: String) {
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(title, style = MaterialTheme.typography.titleMedium)
            Text(body)
        }
    }
}

@Composable
private fun RemoteIcon(baseUrl: String, token: String, path: String, cacheRevision: Int, fallback: String, running: Boolean) {
    var bitmap by remember(baseUrl, token, path, cacheRevision) { mutableStateOf<ImageBitmap?>(null) }
    LaunchedEffect(baseUrl, token, path, cacheRevision) {
        bitmap = loadRemoteBitmap(baseUrl, token, path)
    }
    Box(
        modifier = Modifier
            .size(44.dp)
            .background(if (running) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceVariant, CircleShape),
        contentAlignment = Alignment.Center,
    ) {
        val current = bitmap
        if (current != null) {
            Image(bitmap = current, contentDescription = "process icon", modifier = Modifier.size(36.dp))
        } else {
            Text(fallback)
        }
    }
}

private suspend fun loadRemoteBitmap(baseUrl: String, token: String, path: String): ImageBitmap? = withContext(Dispatchers.IO) {
    if (baseUrl.isBlank() || path.isBlank()) return@withContext null
    runCatching {
        val url = if (path.startsWith("http://") || path.startsWith("https://")) path else baseUrl.trimEnd('/') + "/" + path.trimStart('/')
        val connection = (URL(url).openConnection() as HttpURLConnection).apply {
            connectTimeout = 3_000
            readTimeout = 5_000
            setRequestProperty("Accept", "image/png,image/*")
            if (token.isNotBlank()) setRequestProperty("Authorization", "Bearer $token")
        }
        connection.inputStream.use { input -> BitmapFactory.decodeStream(input).asImageBitmap() }
    }.getOrNull()
}

@Composable
private fun StatusDot(color: String) {
    Box(
        modifier = Modifier
            .size(12.dp)
            .background(statusColor(color), CircleShape),
    )
}

private fun headerStatusColor(state: RemoteAppState): String = when {
    state.isLoading -> "yellow"
    state.authRejected -> "red"
    state.offline || state.baseUrlError.isNotBlank() -> "red"
    state.snapshotIsStale || state.partialErrors.isNotEmpty() -> "yellow"
    state.status != null -> "green"
    else -> state.readiness?.tailscaleReadiness?.color ?: "gray"
}

private fun headerStatusLabel(state: RemoteAppState): String = when {
    state.isLoading -> "동기화 중"
    state.authRejected -> "인증 확인 필요"
    state.offline || state.baseUrlError.isNotBlank() -> "연결 확인 필요"
    state.snapshotIsStale -> "마지막 스냅샷"
    state.partialErrors.isNotEmpty() -> "부분 동기화"
    state.status != null -> "동기화 정상"
    else -> "대기"
}

private fun formatClock(epochMillis: Long): String =
    SimpleDateFormat("HH:mm:ss", Locale.getDefault()).format(Date(epochMillis))

private fun fileName(path: String): String =
    path.replace('\\', '/').substringAfterLast('/')

private fun looksLikeLoopbackUrl(value: String): Boolean =
    value.contains("127.0.0.1") || value.contains("localhost", ignoreCase = true) || value.contains("10.0.2.2")

@Composable
private fun statusColor(color: String): Color = when (color) {
    "green" -> Color(0xFF2E7D32)
    "yellow" -> Color(0xFFF9A825)
    "red" -> MaterialTheme.colorScheme.error
    else -> MaterialTheme.colorScheme.outline
}
