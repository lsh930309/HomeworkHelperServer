package dev.homeworkhelper.remote.data

import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

private const val SMARTTHINGS_BASE_URL = "https://api.smartthings.com/v1"
const val SMARTTHINGS_DEFAULT_WAKE_LABEL = "PC 켜기"

data class SmartThingsDeviceCandidate(
    val deviceId: String,
    val label: String,
    val locationId: String?,
    val capabilities: List<String>,
)

data class SmartThingsAutoSelection(
    val selected: SmartThingsDeviceCandidate?,
    val candidates: List<SmartThingsDeviceCandidate>,
    val message: String,
) {
    val needsManualSelection: Boolean
        get() = selected == null && candidates.isNotEmpty()
}

class SmartThingsClient(private val pat: String) {
    suspend fun listSwitchDevices(): List<SmartThingsDeviceCandidate> = withContext(Dispatchers.IO) {
        val json = JSONObject(request("devices?capability=switch"))
        val array = json.optJSONArray("items") ?: JSONArray(json.optString("items", "[]"))
        List(array.length()) { index -> array.getJSONObject(index).toSmartThingsCandidate() }
            .filter { candidate -> candidate.deviceId.isNotBlank() }
    }

    suspend fun wake(deviceId: String): RemoteCommandResult = withContext(Dispatchers.IO) {
        val payload = JSONObject()
            .put(
                "commands",
                JSONArray().put(
                    JSONObject()
                        .put("component", "main")
                        .put("capability", "switch")
                        .put("command", "on"),
                ),
            )
            .toString()
        val response = JSONObject(request("devices/${deviceId}/commands", method = "POST", body = payload))
        val results = response.optJSONArray("results") ?: JSONArray()
        val accepted = (0 until results.length()).any { index ->
            results.optJSONObject(index)?.optString("status")?.equals("ACCEPTED", ignoreCase = true) == true
        }
        RemoteCommandResult(
            accepted = accepted,
            status = if (accepted) "accepted" else "rejected",
            message = if (accepted) "SmartThings Wake 명령을 접수했습니다." else "SmartThings Wake 명령이 거부되었습니다.",
        )
    }

    private fun request(path: String, method: String = "GET", body: String? = null): String {
        val connection = (URL("$SMARTTHINGS_BASE_URL/$path").openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 7_000
            readTimeout = 10_000
            setRequestProperty("Accept", "application/json")
            setRequestProperty("Authorization", "Bearer $pat")
            if (body != null) {
                doOutput = true
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
            }
        }
        try {
            if (body != null) connection.outputStream.use { it.write(body.toByteArray(Charsets.UTF_8)) }
            val code = connection.responseCode
            val stream = if (code in 200..299) connection.inputStream else connection.errorStream
            val text = stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
            if (code !in 200..299) throw RemoteApiException.HttpFailure(code, text)
            return text
        } finally {
            connection.disconnect()
        }
    }
}

fun selectSmartThingsWakeDevice(
    devices: List<SmartThingsDeviceCandidate>,
    targetLabel: String = SMARTTHINGS_DEFAULT_WAKE_LABEL,
): SmartThingsAutoSelection {
    val switchDevices = devices.filter { it.capabilities.isEmpty() || it.capabilities.any { capability -> capability == "switch" } }
    val exact = switchDevices.filter { it.label == targetLabel }
    if (exact.size == 1) {
        return SmartThingsAutoSelection(exact.first(), switchDevices, "'$targetLabel' 디바이스를 자동 선택했습니다.")
    }
    val normalizedTarget = targetLabel.filterNot(Char::isWhitespace)
    val normalized = switchDevices.filter { it.label.filterNot(Char::isWhitespace) == normalizedTarget }
    if (normalized.size == 1) {
        return SmartThingsAutoSelection(normalized.first(), switchDevices, "'${normalized.first().label}' 디바이스를 자동 선택했습니다.")
    }
    return SmartThingsAutoSelection(
        selected = null,
        candidates = switchDevices,
        message = if (switchDevices.isEmpty()) {
            "SmartThings에서 switch 디바이스를 찾지 못했습니다."
        } else {
            "'$targetLabel' 후보를 하나로 좁히지 못했습니다. 목록에서 선택하세요."
        },
    )
}

private fun JSONObject.toSmartThingsCandidate(): SmartThingsDeviceCandidate {
    val components = optJSONArray("components") ?: JSONArray()
    val capabilities = mutableSetOf<String>()
    for (componentIndex in 0 until components.length()) {
        val component = components.optJSONObject(componentIndex) ?: continue
        val componentCapabilities = component.optJSONArray("capabilities") ?: JSONArray()
        for (capabilityIndex in 0 until componentCapabilities.length()) {
            val capability = componentCapabilities.optJSONObject(capabilityIndex)?.optString("id")
                ?: componentCapabilities.optString(capabilityIndex)
            if (capability.isNotBlank()) capabilities.add(capability)
        }
    }
    return SmartThingsDeviceCandidate(
        deviceId = optString("deviceId"),
        label = optString("label", optString("name", "Unnamed")),
        locationId = optStringOrNull("locationId"),
        capabilities = capabilities.toList(),
    )
}
