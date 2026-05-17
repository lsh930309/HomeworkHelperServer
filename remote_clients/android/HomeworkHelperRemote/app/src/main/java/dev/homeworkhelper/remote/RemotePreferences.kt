package dev.homeworkhelper.remote

import android.content.Context

class RemotePreferences(context: Context) {
    private val prefs = context.getSharedPreferences("homeworkhelper_remote", Context.MODE_PRIVATE)

    fun baseUrl(): String = prefs.getString(KEY_BASE_URL, DEFAULT_BASE_URL) ?: DEFAULT_BASE_URL

    fun legacyToken(): String = prefs.getString(KEY_LEGACY_TOKEN, "") ?: ""

    fun deviceName(): String = prefs.getString(KEY_DEVICE_NAME, DEFAULT_DEVICE_NAME) ?: DEFAULT_DEVICE_NAME

    fun refreshIntervalSeconds(): Int = prefs.getInt(KEY_REFRESH_INTERVAL_SECONDS, 5).coerceIn(1, 60)

    fun showPlaySummary(): Boolean = prefs.getBoolean(KEY_SHOW_PLAY_SUMMARY, true)

    fun progressMode(): String = prefs.getString(KEY_PROGRESS_MODE, "remaining") ?: "remaining"

    fun saveConnection(baseUrl: String, deviceName: String) {
        prefs.edit()
            .putString(KEY_BASE_URL, baseUrl)
            .putString(KEY_DEVICE_NAME, deviceName)
            .apply()
    }

    fun save(baseUrl: String, deviceName: String) = saveConnection(baseUrl, deviceName)

    fun saveUiSettings(refreshIntervalSeconds: Int, showPlaySummary: Boolean, progressMode: String) {
        prefs.edit()
            .putInt(KEY_REFRESH_INTERVAL_SECONDS, refreshIntervalSeconds.coerceIn(1, 60))
            .putBoolean(KEY_SHOW_PLAY_SUMMARY, showPlaySummary)
            .putString(KEY_PROGRESS_MODE, progressMode)
            .apply()
    }

    fun clearLegacyToken() {
        prefs.edit().remove(KEY_LEGACY_TOKEN).apply()
    }

    companion object {
        private const val KEY_BASE_URL = "base_url"
        private const val KEY_LEGACY_TOKEN = "bearer_token"
        private const val KEY_DEVICE_NAME = "device_name"
        private const val KEY_REFRESH_INTERVAL_SECONDS = "refresh_interval_seconds"
        private const val KEY_SHOW_PLAY_SUMMARY = "show_play_summary"
        private const val KEY_PROGRESS_MODE = "progress_mode"
        private const val DEFAULT_BASE_URL = "http://100.x.y.z:8000"
        private const val DEFAULT_DEVICE_NAME = "Android Remote"
    }
}
