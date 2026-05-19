package dev.homeworkhelper.remote

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.platform.LocalContext
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
    RemoteTheme {
        RemoteAppShell(
            state = state,
            onBaseUrlChange = viewModel::updateBaseUrl,
            onDeviceNameChange = viewModel::updateDeviceName,
            onRefresh = viewModel::refresh,
            onPair = viewModel::pair,
            onLaunch = viewModel::launch,
            onClearToken = viewModel::clearLocalToken,
            onInspectTailscale = viewModel::inspectTailscale,
            onOpenTailscale = viewModel::openTailscaleApp,
            onInstallTailscale = viewModel::openTailscaleInstallPage,
            onEnsureTailscale = viewModel::ensureTailscaleAndProbe,
            onSshHostChange = viewModel::updateSshHost,
            onSshUserChange = viewModel::updateSshUser,
            onSshPortChange = viewModel::updateSshPort,
            onRegisterSshKey = viewModel::createAndRegisterSshKey,
            onVerifySsh = viewModel::verifySshHealth,
            onDiscoverSmartThings = viewModel::discoverSmartThingsDevices,
            onSelectSmartThingsDevice = viewModel::selectSmartThingsDevice,
            onManualSmartThingsDeviceChange = viewModel::updateManualSmartThingsDevice,
            onPowerAction = viewModel::executePowerAction,
        )
    }
}
