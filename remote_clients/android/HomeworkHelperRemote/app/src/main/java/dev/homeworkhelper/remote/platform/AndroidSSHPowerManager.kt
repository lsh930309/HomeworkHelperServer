package dev.homeworkhelper.remote.platform

import android.util.Base64
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import net.schmizz.sshj.DefaultConfig
import net.schmizz.sshj.SSHClient
import net.schmizz.sshj.common.IOUtils
import net.schmizz.sshj.transport.verification.HostKeyVerifier
import java.security.MessageDigest
import java.security.PublicKey
import java.util.concurrent.TimeUnit

private const val SSH_HEALTH_MARKER = "__HH_SSH_HEALTH_OK__"
private const val SSH_ACCEPTED_MARKER = "__HH_REMOTE_POWER_ACCEPTED__"

class AndroidSSHPowerManager(private val preferences: AutomationPreferences) {
    suspend fun health(config: SshPowerPreferences, privateKeyPem: String): SshCommandResult {
        return runCommand(config, privateKeyPem, "cmd /C echo $SSH_HEALTH_MARKER", SSH_HEALTH_MARKER, persistHealth = true)
    }

    suspend fun executePowerAction(action: PowerAction, config: SshPowerPreferences, privateKeyPem: String): SshCommandResult {
        return runCommand(config, privateKeyPem, powerCommand(action), SSH_ACCEPTED_MARKER, persistHealth = false)
    }

    private suspend fun runCommand(
        config: SshPowerPreferences,
        privateKeyPem: String,
        command: String,
        requiredMarker: String,
        persistHealth: Boolean,
    ): SshCommandResult = withContext(Dispatchers.IO) {
        if (config.host.isBlank() || config.user.isBlank()) {
            return@withContext SshCommandResult(false, "SSH host/user 설정이 필요합니다.")
        }
        var observedFingerprint: String? = null
        val client = SSHClient(androidCompatibleSshConfig())
        try {
            client.addHostKeyVerifier(object : HostKeyVerifier {
                override fun verify(hostname: String, port: Int, key: PublicKey): Boolean {
                    val fingerprint = key.sha256Fingerprint()
                    observedFingerprint = fingerprint
                    return config.trustedFingerprint.isBlank() || config.trustedFingerprint == fingerprint
                }

                override fun findExistingAlgorithms(hostname: String, port: Int): MutableList<String> {
                    return mutableListOf()
                }
            })
            client.connect(config.host, config.port)
            val publicKey = config.publicKey.takeIf { it.isNotBlank() }
            val keyProvider = client.loadKeys(privateKeyPem, publicKey, null)
            client.authPublickey(config.user, keyProvider)
            val session = client.startSession()
            try {
                val sshCommand = session.exec(command)
                sshCommand.join(8, TimeUnit.SECONDS)
                val stdout = IOUtils.readFully(sshCommand.inputStream).toString()
                val stderr = IOUtils.readFully(sshCommand.errorStream).toString()
                val exitStatus = sshCommand.exitStatus ?: -1
                val markerOk = stdout.contains(requiredMarker) || stderr.contains(requiredMarker)
                if (!markerOk) {
                    return@withContext SshCommandResult(false, "SSH 명령 marker를 확인하지 못했습니다. exit=$exitStatus stderr=${stderr.take(160)}")
                }
                observedFingerprint?.let { fingerprint ->
                    if (preferences.sshTrustedFingerprint.isBlank()) preferences.sshTrustedFingerprint = fingerprint
                }
                if (persistHealth) preferences.sshHealthOk = true
                SshCommandResult(true, "SSH 인증/명령 marker 확인 완료", observedFingerprint, stdout, stderr, exitStatus)
            } finally {
                session.close()
            }
        } catch (exception: Exception) {
            if (persistHealth) preferences.sshHealthOk = false
            SshCommandResult(false, exception.message ?: "SSH 명령 실행 실패", observedFingerprint)
        } finally {
            runCatching { client.disconnect() }
        }
    }


    private fun androidCompatibleSshConfig(): DefaultConfig {
        return DefaultConfig().apply {
            setKeyExchangeFactories(
                keyExchangeFactories.filterNot { factory ->
                    factory.name.contains("curve25519", ignoreCase = true)
                },
            )
        }
    }

    private fun powerCommand(action: PowerAction): String {
        return when (action) {
            PowerAction.Wake -> error("Wake는 SmartThings REST API로 처리합니다.")
            PowerAction.Sleep -> "cmd /C echo $SSH_ACCEPTED_MARKER && rundll32.exe powrprof.dll,SetSuspendState 0,0,0"
            PowerAction.Restart -> "cmd /C echo $SSH_ACCEPTED_MARKER && shutdown /r /t 0"
            PowerAction.Shutdown -> "cmd /C echo $SSH_ACCEPTED_MARKER && shutdown /s /t 0"
        }
    }
}

enum class PowerAction(val wireName: String, val label: String) {
    Wake("wake", "깨우기"),
    Sleep("sleep", "절전"),
    Restart("restart", "재시작"),
    Shutdown("shutdown", "종료"),
}

data class SshCommandResult(
    val ok: Boolean,
    val message: String,
    val fingerprint: String? = null,
    val stdout: String = "",
    val stderr: String = "",
    val exitStatus: Int = -1,
)

private fun PublicKey.sha256Fingerprint(): String {
    val digest = MessageDigest.getInstance("SHA-256").digest(encoded)
    return "SHA256:" + Base64.encodeToString(digest, Base64.NO_WRAP).trimEnd('=')
}
