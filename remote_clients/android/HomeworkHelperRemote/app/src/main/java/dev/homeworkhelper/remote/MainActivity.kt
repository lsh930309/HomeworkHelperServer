package dev.homeworkhelper.remote

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalContext
import dev.homeworkhelper.remote.ui.RemoteApp

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                val context = LocalContext.current
                val viewModel = remember {
                    RemoteAppViewModel(
                        preferences = RemotePreferences(context),
                        tokenStore = AndroidTokenStore(context),
                        androidIntegration = AndroidIntegration(context),
                    )
                }
                DisposableEffect(viewModel) {
                    onDispose { viewModel.close() }
                }
                RemoteApp(viewModel)
            }
        }
    }
}
