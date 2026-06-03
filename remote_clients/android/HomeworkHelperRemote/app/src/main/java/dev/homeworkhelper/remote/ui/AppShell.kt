package dev.homeworkhelper.remote.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import dev.homeworkhelper.remote.data.RemoteAvailability
import dev.homeworkhelper.remote.data.RemoteDevice
import dev.homeworkhelper.remote.data.RemoteProcess
import dev.homeworkhelper.remote.data.SmartThingsDeviceCandidate
import dev.homeworkhelper.remote.platform.PowerAction
import dev.homeworkhelper.remote.state.RemoteUiState

enum class RemoteTab(val label: String, val icon: String) {
    Home("홈", "🎮"),
    Setup("설정", "⚙"),
}

@Composable
fun RemoteAppShell(
    state: RemoteUiState,
    onBaseUrlChange: (String) -> Unit,
    onDeviceNameChange: (String) -> Unit,
    onRefresh: () -> Unit,
    onPair: (String) -> Unit,
    onLaunch: (RemoteProcess) -> Unit,
    onStopProcess: (RemoteProcess) -> Unit,
    onRefreshDevices: () -> Unit,
    onRevokeDevice: (RemoteDevice) -> Unit,
    onPurgeRevokedDevices: () -> Unit,
    onShowDiagnosticsChange: (Boolean) -> Unit,
    onInspectRemoteNetwork: () -> Unit,
    onEnsureRemoteNetwork: () -> Unit,
    onInspectTailscale: () -> Unit,
    onOpenTailscale: () -> Unit,
    onInstallTailscale: () -> Unit,
    onOpenTailscaleSettings: () -> Unit,
    onOpenVpnSettings: () -> Unit,
    onCheckClientTailscale: () -> Unit,
    onTailscaleConnect: () -> Unit,
    onTailscaleDisconnect: () -> Unit,
    onTailscaleConnectOnForegroundChange: (Boolean) -> Unit,
    onTailscaleDisconnectOnBackgroundChange: (Boolean) -> Unit,
    onTailscaleSleepSafeModeChange: (Boolean) -> Unit,
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
    onPowerAction: (PowerAction) -> Unit,
) {
    var selectedTab by rememberSaveable { mutableStateOf(RemoteTab.Home) }

    Scaffold(
        bottomBar = {
            NavigationBar {
                RemoteTab.entries.forEach { tab ->
                    NavigationBarItem(
                        selected = selectedTab == tab,
                        onClick = { selectedTab = tab },
                        icon = { Text(tab.icon) },
                        label = { Text(tab.label) },
                    )
                }
            }
        },
    ) { padding ->
        Box(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding),
        ) {
            when (selectedTab) {
                RemoteTab.Home -> HomeTab(
                    state = state,
                    onRefresh = onRefresh,
                    onLaunch = onLaunch,
                    onStopProcess = onStopProcess,
                    onPowerAction = onPowerAction,
                    modifier = Modifier.fillMaxSize(),
                )

                RemoteTab.Setup -> SetupTab(
                    state = state,
                    onBaseUrlChange = onBaseUrlChange,
                    onDeviceNameChange = onDeviceNameChange,
                    onPair = onPair,
                    onRefreshDevices = onRefreshDevices,
                    onRevokeDevice = onRevokeDevice,
                    onPurgeRevokedDevices = onPurgeRevokedDevices,
                    onShowDiagnosticsChange = onShowDiagnosticsChange,
                    onInspectRemoteNetwork = onInspectRemoteNetwork,
                    onEnsureRemoteNetwork = onEnsureRemoteNetwork,
                    onInspectTailscale = onInspectTailscale,
                    onOpenTailscale = onOpenTailscale,
                    onInstallTailscale = onInstallTailscale,
                    onOpenTailscaleSettings = onOpenTailscaleSettings,
                    onOpenVpnSettings = onOpenVpnSettings,
                    onCheckClientTailscale = onCheckClientTailscale,
                    onTailscaleConnect = onTailscaleConnect,
                    onTailscaleDisconnect = onTailscaleDisconnect,
                    onTailscaleConnectOnForegroundChange = onTailscaleConnectOnForegroundChange,
                    onTailscaleDisconnectOnBackgroundChange = onTailscaleDisconnectOnBackgroundChange,
                    onTailscaleSleepSafeModeChange = onTailscaleSleepSafeModeChange,
                    onRepairEnvironment = onRepairEnvironment,
                    onSshHostChange = onSshHostChange,
                    onSshUserChange = onSshUserChange,
                    onSshPortChange = onSshPortChange,
                    onRegisterSshKey = onRegisterSshKey,
                    onVerifySsh = onVerifySsh,
                    onSaveSmartThingsPat = onSaveSmartThingsPat,
                    onDiscoverSmartThings = onDiscoverSmartThings,
                    onSelectSmartThingsDevice = onSelectSmartThingsDevice,
                    onManualSmartThingsDeviceChange = onManualSmartThingsDeviceChange,
                    modifier = Modifier.fillMaxSize(),
                )
            }
            FloatingStatusMessage(
                state = state,
                modifier = Modifier
                    .align(Alignment.BottomCenter)
                    .padding(horizontal = 16.dp, vertical = 12.dp),
            )
        }
    }
}

@Composable
private fun FloatingStatusMessage(state: RemoteUiState, modifier: Modifier = Modifier) {
    val message = state.userMessage
        ?: state.hostMessage
        ?: if (state.availability == RemoteAvailability.Online) "연결됨" else null
        ?: return
    val (label, container, content) = when (state.availability) {
        RemoteAvailability.Online -> Triple("연결됨", Color(0xFF133F22), Color.White)
        RemoteAvailability.OfflineExpected -> Triple("오프라인", MaterialTheme.colorScheme.tertiaryContainer, MaterialTheme.colorScheme.onTertiaryContainer)
        RemoteAvailability.AgentUnavailable -> Triple("Agent", MaterialTheme.colorScheme.errorContainer, MaterialTheme.colorScheme.onErrorContainer)
        RemoteAvailability.AuthRejected -> Triple("인증", MaterialTheme.colorScheme.errorContainer, MaterialTheme.colorScheme.onErrorContainer)
        RemoteAvailability.Waking -> Triple("Wake", MaterialTheme.colorScheme.primaryContainer, MaterialTheme.colorScheme.onPrimaryContainer)
        RemoteAvailability.GoingOffline -> Triple("전원", MaterialTheme.colorScheme.tertiaryContainer, MaterialTheme.colorScheme.onTertiaryContainer)
        RemoteAvailability.Restarting -> Triple("재시작", MaterialTheme.colorScheme.primaryContainer, MaterialTheme.colorScheme.onPrimaryContainer)
        RemoteAvailability.Unknown -> Triple("설정", MaterialTheme.colorScheme.surfaceVariant, MaterialTheme.colorScheme.onSurfaceVariant)
    }
    Surface(
        modifier = modifier
            .fillMaxWidth()
            .shadow(10.dp, RoundedCornerShape(18.dp)),
        shape = RoundedCornerShape(18.dp),
        color = container,
        contentColor = content,
        tonalElevation = 6.dp,
    ) {
        Text(
            text = "[$label] $message",
            modifier = Modifier
                .background(container)
                .padding(horizontal = 14.dp, vertical = 10.dp),
            style = MaterialTheme.typography.bodyMedium,
            fontWeight = FontWeight.Medium,
        )
    }
}
