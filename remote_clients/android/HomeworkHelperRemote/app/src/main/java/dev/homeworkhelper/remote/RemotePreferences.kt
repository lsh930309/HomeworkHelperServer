package dev.homeworkhelper.remote

import android.content.Context

class RemotePreferences(context: Context) {
    private val prefs = context.getSharedPreferences("homeworkhelper_remote", Context.MODE_PRIVATE)

    fun baseUrl(): String = prefs.getString(KEY_BASE_URL, DEFAULT_BASE_URL) ?: DEFAULT_BASE_URL

    fun legacyToken(): String = prefs.getString(KEY_LEGACY_TOKEN, "") ?: ""

    fun deviceName(): String = prefs.getString(KEY_DEVICE_NAME, DEFAULT_DEVICE_NAME) ?: DEFAULT_DEVICE_NAME

    fun save(baseUrl: String, deviceName: String) {
        prefs.edit()
            .putString(KEY_BASE_URL, baseUrl)
            .putString(KEY_DEVICE_NAME, deviceName)
            .apply()
    }

    fun clearLegacyToken() {
        prefs.edit().remove(KEY_LEGACY_TOKEN).apply()
    }

    companion object {
        private const val KEY_BASE_URL = "base_url"
        private const val KEY_LEGACY_TOKEN = "bearer_token"
        private const val KEY_DEVICE_NAME = "device_name"
        private const val DEFAULT_BASE_URL = "http://10.0.2.2:8000"
        private const val DEFAULT_DEVICE_NAME = "Android Remote"
    }
}
