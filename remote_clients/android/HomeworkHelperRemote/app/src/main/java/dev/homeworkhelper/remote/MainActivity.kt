package dev.homeworkhelper.remote

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { HomeworkHelperRemoteRebuildScaffold() }
    }
}

@Composable
private fun HomeworkHelperRemoteRebuildScaffold() {
    MaterialTheme {
        Surface(modifier = Modifier.fillMaxSize()) {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(20.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                Card(modifier = Modifier.fillMaxWidth()) {
                    Column(
                        modifier = Modifier.padding(18.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Text("HomeworkHelper Remote", style = MaterialTheme.typography.headlineSmall)
                        Text("Android rebuild scaffold", style = MaterialTheme.typography.titleMedium)
                        Text(
                            "새 Android 클라이언트는 macOS popover처럼 등록된 게임 현황과 빠른 실행을 메인 화면으로 재구축합니다.",
                            style = MaterialTheme.typography.bodyMedium,
                        )
                    }
                }
                Card(modifier = Modifier.fillMaxWidth()) {
                    Column(
                        modifier = Modifier.padding(18.dp),
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Text("Implementation source of truth", style = MaterialTheme.typography.titleMedium)
                        Text("docs/remote/macos-client-architecture.md")
                        Text("docs/remote/android-client-design.md")
                        Text("REMOTE_CONNECTION_SUPERVISOR.md")
                    }
                }
            }
        }
    }
}
