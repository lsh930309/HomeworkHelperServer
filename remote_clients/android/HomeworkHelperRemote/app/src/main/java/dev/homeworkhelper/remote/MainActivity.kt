package dev.homeworkhelper.remote

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import dev.homeworkhelper.remote.state.RemoteViewModel
import dev.homeworkhelper.remote.state.RemoteViewModelFactory
import dev.homeworkhelper.remote.ui.RemoteAppShell
import dev.homeworkhelper.remote.ui.RemoteTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { HomeworkHelperRemoteApp() }
    }
}

@Composable
private fun HomeworkHelperRemoteApp(
    viewModel: RemoteViewModel = viewModel(factory = RemoteViewModelFactory(LocalContext.current)),
) {
    val state by viewModel.uiState.collectAsStateWithLifecycle()
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner, viewModel) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_START -> viewModel.onAppForeground()
                Lifecycle.Event.ON_STOP -> viewModel.onAppBackground()
                else -> Unit
            }
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose { lifecycleOwner.lifecycle.removeObserver(observer) }
    }
    RemoteTheme {
        RemoteAppShell(
            state = state,
            onBaseUrlChange = viewModel::updateBaseUrl,
            onDeviceNameChange = viewModel::updateDeviceName,
            onRefresh = viewModel::refresh,
            onPair = viewModel::pair,
            onLaunch = viewModel::launch,
            onStopProcess = viewModel::stop,
            onRefreshDevices = { viewModel.refreshDevices() },
            onRevokeDevice = viewModel::revokeDevice,
            onPurgeRevokedDevices = viewModel::purgeRevokedDevices,
            onShowDiagnosticsChange = viewModel::updateShowDiagnostics,
            onInspectRemoteNetwork = viewModel::inspectRemoteNetwork,
            onEnsureRemoteNetwork = viewModel::ensureRemoteNetworkFromUi,
            onInspectTailscale = viewModel::inspectTailscale,
            onOpenTailscale = viewModel::openTailscaleApp,
            onInstallTailscale = viewModel::openTailscaleInstallPage,
            onOpenTailscaleSettings = viewModel::openTailscaleAppSettings,
            onOpenVpnSettings = viewModel::openVpnSettings,
            onCheckClientTailscale = viewModel::checkClientTailscaleAndRefresh,
            onTailscaleConnect = { viewModel.requestTailscaleConnect() },
            onTailscaleDisconnect = { viewModel.requestTailscaleDisconnect() },
            onTailscaleConnectOnForegroundChange = viewModel::updateTailscaleConnectOnForeground,
            onTailscaleDisconnectOnBackgroundChange = viewModel::updateTailscaleDisconnectOnBackground,
            onTailscaleSleepSafeModeChange = viewModel::updateTailscaleSleepSafeMode,
            onRepairEnvironment = viewModel::repairEnvironment,
            onSshHostChange = viewModel::updateSshHost,
            onSshUserChange = viewModel::updateSshUser,
            onSshPortChange = viewModel::updateSshPort,
            onRegisterSshKey = viewModel::createAndRegisterSshKey,
            onVerifySsh = viewModel::verifySshHealth,
            onSaveSmartThingsPat = viewModel::saveSmartThingsPat,
            onDiscoverSmartThings = viewModel::discoverSmartThingsDevices,
            onSelectSmartThingsDevice = viewModel::selectSmartThingsDevice,
            onManualSmartThingsDeviceChange = viewModel::updateManualSmartThingsDevice,
            onPowerAction = viewModel::executePowerAction,
        )
    }
}
