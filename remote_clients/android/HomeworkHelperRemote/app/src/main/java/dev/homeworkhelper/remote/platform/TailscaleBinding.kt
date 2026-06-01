package dev.homeworkhelper.remote.platform

import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.Uri
import android.os.Build

private const val TAILSCALE_PACKAGE = "com.tailscale.ipn"
private const val TAILSCALE_CONNECT_VPN = "com.tailscale.ipn.CONNECT_VPN"
private const val TAILSCALE_DISCONNECT_VPN = "com.tailscale.ipn.DISCONNECT_VPN"

data class TailscaleBindingState(
    val installed: Boolean = false,
    val vpnActive: Boolean = false,
    val suggestedBaseUrls: List<String> = emptyList(),
    val message: String = "Tailscale 상태를 아직 확인하지 않았습니다.",
    val lastAutomationAction: String = "",
)

class TailscaleBinding(private val context: Context) {
    fun inspect(lastAutomationAction: String = ""): TailscaleBindingState {
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

    fun requestVpnConnect(): TailscaleBindingState {
        return sendVpnBroadcast(TAILSCALE_CONNECT_VPN, "CONNECT_VPN")
    }

    fun requestVpnDisconnect(): TailscaleBindingState {
        return sendVpnBroadcast(TAILSCALE_DISCONNECT_VPN, "DISCONNECT_VPN")
    }

    private fun sendVpnBroadcast(action: String, label: String): TailscaleBindingState {
        if (!isInstalled()) {
            return inspect("$label 실패: Tailscale 미설치")
        }
        val intent = Intent(action).setPackage(TAILSCALE_PACKAGE)
        context.sendBroadcast(intent)
        val inspected = inspect("$label broadcast 전송됨")
        return inspected.copy(
            message = if (inspected.vpnActive) {
                "Tailscale $label 요청 후 VPN 활성 네트워크를 감지했습니다."
            } else {
                "Tailscale $label 요청을 보냈습니다. Android VPN 활성화까지 잠시 걸릴 수 있어 상태를 추적합니다."
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
