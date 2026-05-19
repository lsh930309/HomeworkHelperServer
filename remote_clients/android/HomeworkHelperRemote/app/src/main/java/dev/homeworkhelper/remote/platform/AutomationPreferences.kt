package dev.homeworkhelper.remote.platform

import android.content.Context

data class SshPowerPreferences(
    val host: String = "",
    val user: String = "",
    val port: Int = 22,
    val publicKey: String = "",
    val trustedFingerprint: String = "",
    val healthOk: Boolean = false,
)

data class SmartThingsPreferences(
    val hasPat: Boolean = false,
    val deviceId: String = "",
    val deviceLabel: String = "",
    val locationId: String = "",
    val lastVerifiedMillis: Long = 0L,
)

class AutomationPreferences(context: Context) {
    private val preferences = context.getSharedPreferences("homeworkhelper.remote.automation", Context.MODE_PRIVATE)
    private val secureStore = SecureStringStore(
        context,
        "homeworkhelper.remote.automation.secure",
        "homeworkhelper_remote_automation_key",
    )

    var sshHost: String
        get() = preferences.getString(KEY_SSH_HOST, "").orEmpty()
        set(value) = preferences.edit().putString(KEY_SSH_HOST, value.trim()).apply()

    var sshUser: String
        get() = preferences.getString(KEY_SSH_USER, "").orEmpty()
        set(value) = preferences.edit().putString(KEY_SSH_USER, value.trim()).apply()

    var sshPort: Int
        get() = preferences.getInt(KEY_SSH_PORT, 22).coerceIn(1, 65535)
        set(value) = preferences.edit().putInt(KEY_SSH_PORT, value.coerceIn(1, 65535)).apply()

    var sshPublicKey: String
        get() = preferences.getString(KEY_SSH_PUBLIC_KEY, "").orEmpty()
        set(value) = preferences.edit().putString(KEY_SSH_PUBLIC_KEY, value.trim()).apply()

    var sshTrustedFingerprint: String
        get() = preferences.getString(KEY_SSH_FINGERPRINT, "").orEmpty()
        set(value) = preferences.edit().putString(KEY_SSH_FINGERPRINT, value.trim()).apply()

    var sshHealthOk: Boolean
        get() = preferences.getBoolean(KEY_SSH_HEALTH_OK, false)
        set(value) = preferences.edit().putBoolean(KEY_SSH_HEALTH_OK, value).apply()

    var smartThingsDeviceId: String
        get() = preferences.getString(KEY_ST_DEVICE_ID, "").orEmpty()
        set(value) = preferences.edit().putString(KEY_ST_DEVICE_ID, value.trim()).apply()

    var smartThingsDeviceLabel: String
        get() = preferences.getString(KEY_ST_DEVICE_LABEL, "").orEmpty()
        set(value) = preferences.edit().putString(KEY_ST_DEVICE_LABEL, value.trim()).apply()

    var smartThingsLocationId: String
        get() = preferences.getString(KEY_ST_LOCATION_ID, "").orEmpty()
        set(value) = preferences.edit().putString(KEY_ST_LOCATION_ID, value.trim()).apply()

    var smartThingsLastVerifiedMillis: Long
        get() = preferences.getLong(KEY_ST_LAST_VERIFIED, 0L)
        set(value) = preferences.edit().putLong(KEY_ST_LAST_VERIFIED, value).apply()

    fun loadSsh(): SshPowerPreferences = SshPowerPreferences(
        host = sshHost,
        user = sshUser,
        port = sshPort,
        publicKey = sshPublicKey,
        trustedFingerprint = sshTrustedFingerprint,
        healthOk = sshHealthOk,
    )

    fun loadSmartThings(): SmartThingsPreferences = SmartThingsPreferences(
        hasPat = loadSmartThingsPat() != null,
        deviceId = smartThingsDeviceId,
        deviceLabel = smartThingsDeviceLabel,
        locationId = smartThingsLocationId,
        lastVerifiedMillis = smartThingsLastVerifiedMillis,
    )

    fun saveSmartThingsPat(value: String) {
        secureStore.save(KEY_ST_PAT, value.trim())
    }

    fun loadSmartThingsPat(): String? = secureStore.load(KEY_ST_PAT)?.takeIf { it.isNotBlank() }

    fun clearSmartThingsPat() {
        secureStore.clear(KEY_ST_PAT)
    }

    fun savePrivateKey(pem: String) {
        secureStore.save(KEY_SSH_PRIVATE_KEY, pem)
    }

    fun loadPrivateKey(): String? = secureStore.load(KEY_SSH_PRIVATE_KEY)?.takeIf { it.isNotBlank() }

    fun clearPrivateKey() {
        secureStore.clear(KEY_SSH_PRIVATE_KEY)
    }

    companion object {
        private const val KEY_SSH_HOST = "ssh.host"
        private const val KEY_SSH_USER = "ssh.user"
        private const val KEY_SSH_PORT = "ssh.port"
        private const val KEY_SSH_PUBLIC_KEY = "ssh.public_key"
        private const val KEY_SSH_FINGERPRINT = "ssh.trusted_fingerprint"
        private const val KEY_SSH_HEALTH_OK = "ssh.health_ok"
        private const val KEY_SSH_PRIVATE_KEY = "ssh.private_key"
        private const val KEY_ST_PAT = "smartthings.pat"
        private const val KEY_ST_DEVICE_ID = "smartthings.device_id"
        private const val KEY_ST_DEVICE_LABEL = "smartthings.device_label"
        private const val KEY_ST_LOCATION_ID = "smartthings.location_id"
        private const val KEY_ST_LAST_VERIFIED = "smartthings.last_verified_millis"
    }
}
