package dev.homeworkhelper.remote

import android.app.AppOpsManager
import android.app.usage.UsageEvents
import android.app.usage.UsageStatsManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Process
import android.provider.Settings
import android.widget.Toast

private const val TAILSCALE_PACKAGE = "com.tailscale.ipn"

data class AndroidUsageSnapshot(
    val packageName: String,
    val className: String,
    val timestampMillis: Long,
)

class AndroidIntegration(private val context: Context) {
    fun launchPackage(packageName: String): Boolean {
        val normalized = packageName.trim()
        if (normalized.isBlank()) {
            toast("Android package name을 입력하세요.")
            return false
        }
        val launchIntent = context.packageManager.getLaunchIntentForPackage(normalized)
        if (launchIntent == null) {
            toast("실행 가능한 패키지를 찾지 못했습니다: $normalized")
            return false
        }
        launchIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(launchIntent)
        return true
    }

    fun isPackageLaunchable(packageName: String): Boolean =
        context.packageManager.getLaunchIntentForPackage(packageName.trim()) != null

    fun isTailscaleInstalled(): Boolean = isPackageLaunchable(TAILSCALE_PACKAGE)

    fun openTailscaleOrStore(): Boolean {
        if (launchPackage(TAILSCALE_PACKAGE)) return true
        return openUrl("market://details?id=$TAILSCALE_PACKAGE") ||
            openUrl("https://play.google.com/store/apps/details?id=$TAILSCALE_PACKAGE")
    }

    fun openUrl(url: String): Boolean {
        return runCatching {
            context.startActivity(
                Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            )
            true
        }.getOrElse {
            toast("열 수 없습니다: $url")
            false
        }
    }

    fun hasUsageAccess(): Boolean {
        val appOps = context.getSystemService(Context.APP_OPS_SERVICE) as AppOpsManager
        val mode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            appOps.unsafeCheckOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), context.packageName)
        } else {
            @Suppress("DEPRECATION")
            appOps.checkOpNoThrow(AppOpsManager.OPSTR_GET_USAGE_STATS, Process.myUid(), context.packageName)
        }
        return mode == AppOpsManager.MODE_ALLOWED
    }

    fun openUsageAccessSettings() {
        context.startActivity(Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }

    fun recentForegroundApp(lookbackMillis: Long = DEFAULT_USAGE_LOOKBACK_MILLIS): AndroidUsageSnapshot? {
        if (!hasUsageAccess()) return null
        val usageStats = context.getSystemService(Context.USAGE_STATS_SERVICE) as UsageStatsManager
        val endTime = System.currentTimeMillis()
        val events = usageStats.queryEvents(endTime - lookbackMillis, endTime)
        val event = UsageEvents.Event()
        var latest: AndroidUsageSnapshot? = null
        while (events.hasNextEvent()) {
            events.getNextEvent(event)
            if (event.eventType == UsageEvents.Event.MOVE_TO_FOREGROUND || event.eventType == UsageEvents.Event.ACTIVITY_RESUMED) {
                latest = AndroidUsageSnapshot(
                    packageName = event.packageName.orEmpty(),
                    className = event.className.orEmpty(),
                    timestampMillis = event.timeStamp,
                )
            }
        }
        return latest
    }

    private fun toast(message: String) {
        Toast.makeText(context, message, Toast.LENGTH_SHORT).show()
    }

    companion object {
        private const val DEFAULT_USAGE_LOOKBACK_MILLIS = 6L * 60L * 60L * 1000L
    }
}
