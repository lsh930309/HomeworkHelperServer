package dev.homeworkhelper.remote.platform

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Uri
import android.os.Build

private const val TAILSCALE_PACKAGE = "com.tailscale.ipn"
private const val TAILSCALE_RECEIVER_CLASS = "com.tailscale.ipn.IPNReceiver"
private const val TAILSCALE_CONNECT_VPN = "com.tailscale.ipn.CONNECT_VPN"
private const val TAILSCALE_DISCONNECT_VPN = "com.tailscale.ipn.DISCONNECT_VPN"

data class TailscaleBindingState(
    val installed: Boolean = false,
    val vpnActive: Boolean = false,
    val suggestedBaseUrls: List<String> = emptyList(),
    val message: String = "Tailscale 상태를 아직 확인하지 않았습니다.",
    val lastAutomationAction: String = "",
    val broadcastTarget: String = "",
    val automationAttempt: Int = 0,
    val automationAttemptLimit: Int = 0,
    val pollingTimedOut: Boolean = false,
)

class TailscaleBinding(private val context: Context) {
    fun inspect(
        lastAutomationAction: String = "",
        broadcastTarget: String = "",
        automationAttempt: Int = 0,
        automationAttemptLimit: Int = 0,
        pollingTimedOut: Boolean = false,
    ): TailscaleBindingState {
        val installed = isInstalled()
        val vpnActive = isVpnActive()
        return TailscaleBindingState(
            installed = installed,
            vpnActive = vpnActive,
            message = when {
                installed && vpnActive -> "Tailscale 앱과 VPN 연결을 감지했습니다."
                installed -> "Tailscale 앱은 설치되어 있지만 VPN 활성 네트워크가 보이지 않습니다. 자동 연결 또는 앱 열기를 시도할 수 있습니다."
                else -> "Tailscale 앱이 설치되어 있지 않습니다. Play Store에서 먼저 설치하세요."
            },
            lastAutomationAction = lastAutomationAction,
            broadcastTarget = broadcastTarget,
            automationAttempt = automationAttempt,
            automationAttemptLimit = automationAttemptLimit,
            pollingTimedOut = pollingTimedOut,
        )
    }

    fun openTailscaleApp(): Boolean {
        val intent = context.packageManager.getLaunchIntentForPackage(TAILSCALE_PACKAGE) ?: return false
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        context.startActivity(intent)
        return true
    }

    fun openInstallPage() {
        val intent = Intent(Intent.ACTION_VIEW, Uri.parse("market://details?id=$TAILSCALE_PACKAGE"))
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        runCatching { context.startActivity(intent) }
            .onFailure {
                context.startActivity(
                    Intent(Intent.ACTION_VIEW, Uri.parse("https://play.google.com/store/apps/details?id=$TAILSCALE_PACKAGE"))
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                )
            }
    }

    fun requestVpnConnect(
        automationAttempt: Int = 1,
        automationAttemptLimit: Int = 1,
        includePackageFallback: Boolean = false,
    ): TailscaleBindingState {
        return sendVpnBroadcast(
            TAILSCALE_CONNECT_VPN,
            "CONNECT_VPN",
            automationAttempt,
            automationAttemptLimit,
            includePackageFallback,
        )
    }

    fun requestVpnDisconnect(): TailscaleBindingState {
        return sendVpnBroadcast(
            TAILSCALE_DISCONNECT_VPN,
            "DISCONNECT_VPN",
            automationAttempt = 1,
            automationAttemptLimit = 1,
            includePackageFallback = false,
        )
    }

    private fun sendVpnBroadcast(
        action: String,
        label: String,
        automationAttempt: Int,
        automationAttemptLimit: Int,
        includePackageFallback: Boolean,
    ): TailscaleBindingState {
        if (!isInstalled()) {
            return inspect("$label 실패: Tailscale 미설치")
        }
        val sentTargets = mutableListOf<String>()
        val errors = mutableListOf<String>()
        fun send(labelForTarget: String, intent: Intent): Boolean {
            return runCatching {
                context.sendBroadcast(intent)
                sentTargets += labelForTarget
            }.isSuccess.also { success ->
                if (!success) errors += labelForTarget
            }
        }
        val componentTarget = "$TAILSCALE_PACKAGE/$TAILSCALE_RECEIVER_CLASS"
        val componentSent = send(
            "component:$TAILSCALE_RECEIVER_CLASS",
            Intent(action).setComponent(ComponentName(TAILSCALE_PACKAGE, TAILSCALE_RECEIVER_CLASS)),
        )
        if (!componentSent || includePackageFallback) {
            send("package:$TAILSCALE_PACKAGE", Intent(action).setPackage(TAILSCALE_PACKAGE))
        }
        val broadcastTarget = sentTargets.joinToString(", ").ifBlank { componentTarget }
        val actionSummary = buildString {
            append("$label broadcast 전송됨")
            append(" [target=$broadcastTarget")
            if (automationAttemptLimit > 1) append(", attempt=$automationAttempt/$automationAttemptLimit")
            if (errors.isNotEmpty()) append(", failed=${errors.joinToString()}")
            append("]")
        }
        val inspected = inspect(
            lastAutomationAction = actionSummary,
            broadcastTarget = broadcastTarget,
            automationAttempt = automationAttempt,
            automationAttemptLimit = automationAttemptLimit,
        )
        return inspected.copy(
            message = if (inspected.vpnActive) {
                "Tailscale $label 요청 후 VPN 활성 네트워크를 감지했습니다."
            } else {
                "Tailscale $label 요청을 보냈습니다. target=$broadcastTarget; Android VPN 활성화까지 상태를 추적합니다."
            },
        )
    }

    private fun isInstalled(): Boolean {
        return runCatching {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                context.packageManager.getPackageInfo(TAILSCALE_PACKAGE, PackageManager.PackageInfoFlags.of(0))
            } else {
                @Suppress("DEPRECATION")
                context.packageManager.getPackageInfo(TAILSCALE_PACKAGE, 0)
            }
        }.isSuccess
    }

    private fun isVpnActive(): Boolean {
        val connectivity = context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
        return connectivity.allNetworks.any { network ->
            connectivity.getNetworkCapabilities(network)?.hasTransport(NetworkCapabilities.TRANSPORT_VPN) == true
        }
    }
}
