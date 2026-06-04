package dev.homeworkhelper.remote.platform

import android.content.Context
import dev.homeworkhelper.remote.BuildConfig

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

    var smartThingsDeviceId: String
        get() = preferences.getString(KEY_ST_DEVICE_ID, "").orEmpty().ifBlank { BuildConfig.SMARTTHINGS_DEFAULT_DEVICE_ID }
        set(value) = preferences.edit().putString(KEY_ST_DEVICE_ID, value.trim()).apply()

    var smartThingsDeviceLabel: String
        get() = preferences.getString(KEY_ST_DEVICE_LABEL, "").orEmpty().ifBlank { BuildConfig.SMARTTHINGS_DEFAULT_DEVICE_LABEL }
        set(value) = preferences.edit().putString(KEY_ST_DEVICE_LABEL, value.trim()).apply()

    var smartThingsLocationId: String
        get() = preferences.getString(KEY_ST_LOCATION_ID, "").orEmpty().ifBlank { BuildConfig.SMARTTHINGS_DEFAULT_LOCATION_ID }
        set(value) = preferences.edit().putString(KEY_ST_LOCATION_ID, value.trim()).apply()

    var smartThingsLastVerifiedMillis: Long
        get() = preferences.getLong(KEY_ST_LAST_VERIFIED, 0L)
        set(value) = preferences.edit().putLong(KEY_ST_LAST_VERIFIED, value).apply()

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

    fun seedSmartThingsPatFromBuildConfig(): Boolean {
        val debugPat = BuildConfig.SMARTTHINGS_DEBUG_PAT.takeIf { it.isNotBlank() } ?: return false
        if (secureStore.contains(KEY_ST_PAT)) return false
        secureStore.save(KEY_ST_PAT, debugPat)
        return true
    }

    fun loadSmartThingsPat(): String? = secureStore.load(KEY_ST_PAT)?.takeIf { it.isNotBlank() }
        ?: BuildConfig.SMARTTHINGS_DEBUG_PAT.takeIf { it.isNotBlank() }

    fun clearSmartThingsPat() {
        secureStore.clear(KEY_ST_PAT)
    }

    companion object {
        private const val KEY_ST_PAT = "smartthings.pat"
        private const val KEY_ST_DEVICE_ID = "smartthings.device_id"
        private const val KEY_ST_DEVICE_LABEL = "smartthings.device_label"
        private const val KEY_ST_LOCATION_ID = "smartthings.location_id"
        private const val KEY_ST_LAST_VERIFIED = "smartthings.last_verified_millis"
    }
}
