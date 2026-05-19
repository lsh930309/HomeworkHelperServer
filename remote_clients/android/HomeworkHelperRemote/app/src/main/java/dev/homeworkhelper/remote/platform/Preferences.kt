package dev.homeworkhelper.remote.platform

import android.content.Context
import dev.homeworkhelper.remote.data.RemoteProcess

class RemotePreferences(context: Context) {
    private val preferences = context.getSharedPreferences("homeworkhelper.remote.preferences", Context.MODE_PRIVATE)

    var baseUrl: String
        get() = preferences.getString(KEY_BASE_URL, "").orEmpty()
        set(value) = preferences.edit().putString(KEY_BASE_URL, value.trim()).apply()

    var deviceName: String
        get() = preferences.getString(KEY_DEVICE_NAME, "").orEmpty()
        set(value) = preferences.edit().putString(KEY_DEVICE_NAME, value.trim()).apply()

    var cachedProcessesJson: String
        get() = preferences.getString(KEY_CACHED_PROCESSES, "[]").orEmpty()
        set(value) = preferences.edit().putString(KEY_CACHED_PROCESSES, value).apply()

    var lastSyncMillis: Long
        get() = preferences.getLong(KEY_LAST_SYNC_MILLIS, 0L)
        set(value) = preferences.edit().putLong(KEY_LAST_SYNC_MILLIS, value).apply()

    fun cachedProcesses(): List<RemoteProcess> {
        return runCatching { RemoteProcess.listFromJson(cachedProcessesJson) }.getOrDefault(emptyList())
    }

    companion object {
        private const val KEY_BASE_URL = "remote.base_url"
        private const val KEY_DEVICE_NAME = "remote.device_name"
        private const val KEY_CACHED_PROCESSES = "remote.cached_processes_json"
        private const val KEY_LAST_SYNC_MILLIS = "remote.last_sync_millis"
    }
}
