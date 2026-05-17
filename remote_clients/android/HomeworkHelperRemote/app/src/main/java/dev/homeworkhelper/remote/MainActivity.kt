package dev.homeworkhelper.remote

import android.app.Activity
import android.os.Bundle
import android.view.Window
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.SideEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalView
import androidx.core.view.WindowCompat
import dev.homeworkhelper.remote.ui.RemoteApp

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            val darkTheme = isSystemInDarkTheme()
            val colorScheme = if (darkTheme) {
                darkColorScheme(
                    primary = Color(0xFFD8C4FF),
                    secondary = Color(0xFFCBBEEA),
                    tertiary = Color(0xFFF0B8C8),
                    background = Color(0xFF141218),
                    surface = Color(0xFF1D1B20),
                    surfaceVariant = Color(0xFF49454F),
                    primaryContainer = Color(0xFF4F378B),
                    errorContainer = Color(0xFF8C1D18),
                )
            } else {
                lightColorScheme(
                    primary = Color(0xFF6750A4),
                    secondary = Color(0xFF625B71),
                    tertiary = Color(0xFF7D5260),
                    background = Color(0xFFFFF7FF),
                    surface = Color(0xFFFFFBFE),
                    surfaceVariant = Color(0xFFE7E0EC),
                    primaryContainer = Color(0xFFEADDFF),
                    errorContainer = Color(0xFFF9DEDC),
                )
            }
            val view = LocalView.current
            SideEffect {
                val window = (view.context as? Activity)?.window
                if (window != null) {
                    applySystemBarColors(
                        window = window,
                        statusBarColor = colorScheme.background.toArgb(),
                        navigationBarColor = colorScheme.surface.toArgb(),
                    )
                    WindowCompat.getInsetsController(window, view).isAppearanceLightStatusBars = !darkTheme
                    WindowCompat.getInsetsController(window, view).isAppearanceLightNavigationBars = !darkTheme
                }
            }
            MaterialTheme(colorScheme = colorScheme) {
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

@Suppress("DEPRECATION")
private fun applySystemBarColors(window: Window, statusBarColor: Int, navigationBarColor: Int) {
    window.statusBarColor = statusBarColor
    window.navigationBarColor = navigationBarColor
}
