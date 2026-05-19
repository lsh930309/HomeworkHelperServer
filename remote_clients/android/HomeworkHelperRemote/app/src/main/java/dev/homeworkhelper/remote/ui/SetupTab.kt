package dev.homeworkhelper.remote.ui

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.ElevatedCard
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import dev.homeworkhelper.remote.state.RemoteUiState

@Composable
fun SetupTab(
    state: RemoteUiState,
    onBaseUrlChange: (String) -> Unit,
    onDeviceNameChange: (String) -> Unit,
    onPair: (String) -> Unit,
    onClearToken: () -> Unit,
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
            Text("설정", style = MaterialTheme.typography.headlineMedium)
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

@Composable
private fun ConnectionCard(
    state: RemoteUiState,
    onBaseUrlChange: (String) -> Unit,
    onDeviceNameChange: (String) -> Unit,
    onPair: (String) -> Unit,
    onClearToken: () -> Unit,
) {
    var pairingCode by remember { mutableStateOf("") }
    ElevatedCard(modifier = Modifier.fillMaxWidth()) {
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
        }
    }
}
