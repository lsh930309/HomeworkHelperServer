package dev.homeworkhelper.remote.ui

import androidx.compose.foundation.layout.padding
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import dev.homeworkhelper.remote.data.RemoteProcess
import dev.homeworkhelper.remote.state.RemoteUiState

enum class RemoteTab(val label: String) {
    Home("홈"),
    Power("전원"),
    Setup("설정"),
    More("더보기"),
}

@Composable
fun RemoteAppShell(
    state: RemoteUiState,
    onBaseUrlChange: (String) -> Unit,
    onDeviceNameChange: (String) -> Unit,
    onRefresh: () -> Unit,
    onPair: (String) -> Unit,
    onLaunch: (RemoteProcess) -> Unit,
    onClearToken: () -> Unit,
) {
    var selectedTab by rememberSaveable { mutableStateOf(RemoteTab.Home) }

    Scaffold(
        bottomBar = {
            NavigationBar {
                RemoteTab.entries.forEach { tab ->
                    NavigationBarItem(
                        selected = selectedTab == tab,
                        onClick = { selectedTab = tab },
                        icon = { Text(tabIcon(tab)) },
                        label = { Text(tab.label) },
                    )
                }
            }
        },
    ) { padding ->
        when (selectedTab) {
            RemoteTab.Home -> HomeTab(
                state = state,
                onRefresh = onRefresh,
                onLaunch = onLaunch,
                modifier = Modifier.padding(padding),
            )
            RemoteTab.Power -> PowerTab(
                state = state,
                modifier = Modifier.padding(padding),
            )
            RemoteTab.Setup -> SetupTab(
                state = state,
                onBaseUrlChange = onBaseUrlChange,
                onDeviceNameChange = onDeviceNameChange,
                onPair = onPair,
                onClearToken = onClearToken,
                modifier = Modifier.padding(padding),
            )
            RemoteTab.More -> MoreTab(
                state = state,
                modifier = Modifier.padding(padding),
            )
        }
    }
}

private fun tabIcon(tab: RemoteTab): String {
    return when (tab) {
        RemoteTab.Home -> "H"
        RemoteTab.Power -> "P"
        RemoteTab.Setup -> "S"
        RemoteTab.More -> "M"
    }
}
