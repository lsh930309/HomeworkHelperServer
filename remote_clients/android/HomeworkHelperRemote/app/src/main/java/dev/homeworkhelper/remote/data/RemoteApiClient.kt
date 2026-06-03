package dev.homeworkhelper.remote.data

import android.net.Uri
import dev.homeworkhelper.remote.platform.RemoteHttpTransport
import dev.homeworkhelper.remote.platform.SystemRemoteNetworkController
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.IOException
import java.net.ConnectException
import java.net.NoRouteToHostException
import java.net.SocketTimeoutException
import java.net.URL
import java.net.UnknownHostException

sealed class RemoteApiException(message: String, cause: Throwable? = null) : Exception(message, cause) {
    class AuthRejected : RemoteApiException("인증 토큰이 거부되었습니다.")
    class OfflineExpected(cause: Throwable) : RemoteApiException("호스트에 연결할 수 없습니다.", cause)
    class AgentUnavailable(cause: Throwable? = null) : RemoteApiException("Remote Agent HTTP 서버에 연결할 수 없습니다.", cause)
    class HttpFailure(val code: Int, body: String) : RemoteApiException("HTTP $code: $body")
    class DecodeFailure(cause: Throwable) : RemoteApiException("응답을 해석할 수 없습니다.", cause)
}

class RemoteApiClient(
    private val baseUrl: String,
    private val bearerToken: String?,
    private val httpTransport: RemoteHttpTransport = SystemRemoteNetworkController(),
) {
    suspend fun status(): RemoteStatus {
        return JSONObject(request("remote/status")).toRemoteStatus()
    }

    suspend fun readiness(): RemoteReadiness {
        return JSONObject(request("remote/readiness")).toRemoteReadiness()
    }

    suspend fun processesRaw(): String {
        return request("remote/processes")
    }

    suspend fun launchProcess(id: String): RemoteCommandResult {
        val encodedId = Uri.encode(id)
        return JSONObject(request("remote/processes/$encodedId/launch", method = "POST", body = "{}"))
            .toRemoteCommandResult()
    }

    suspend fun stopProcess(id: String): RemoteCommandResult {
        val encodedId = Uri.encode(id)
        return JSONObject(request("remote/processes/$encodedId/stop", method = "POST", body = "{}"))
            .toRemoteCommandResult()
    }

    suspend fun powerStatus(): RemotePowerStatus {
        return JSONObject(request("remote/power/status")).toRemotePowerStatus()
    }

    suspend fun powerSetup(): RemotePowerSetup {
        return JSONObject(request("remote/power/setup")).toRemotePowerSetup()
    }

    suspend fun registerPowerSSHKey(publicKey: String, label: String): RemoteCommandResult {
        val payload = JSONObject()
            .put("public_key", publicKey)
            .put("label", label)
            .toString()
        val json = JSONObject(request("remote/power/ssh-key", method = "POST", body = payload))
        val accepted = json.optBoolean("registered", false) || json.optBoolean("already_present", false)
        return RemoteCommandResult(
            accepted = accepted,
            status = if (accepted) "accepted" else "rejected",
            message = json.optStringOrNull("message") ?: if (accepted) "SSH public key를 host authorized_keys에 등록했습니다." else "SSH public key 등록이 거부되었습니다.",
        )
    }

    suspend fun confirmPairing(code: String, deviceName: String): PairingConfirmResponse {
        val payload = JSONObject()
            .put("code", code)
            .put("device_name", deviceName)
            .put("platform", "android")
            .toString()
        return JSONObject(request("remote/pair/confirm", method = "POST", body = payload))
            .toPairingConfirmResponse()
    }

    suspend fun devices(): List<RemoteDevice> {
        return JSONObject(request("remote/devices")).toRemoteDevices()
    }

    suspend fun revokeDevice(id: String): RemoteDeviceRevokeResponse {
        val encodedId = Uri.encode(id)
        return JSONObject(request("remote/devices/$encodedId", method = "DELETE"))
            .toRemoteDeviceRevokeResponse()
    }

    suspend fun purgeRevokedDevices(): PurgeDevicesResponse {
        return JSONObject(request("remote/devices/revoked", method = "DELETE"))
            .toPurgeDevicesResponse()
    }

    private suspend fun request(
        path: String,
        method: String = "GET",
        body: String? = null,
    ): String = withContext(Dispatchers.IO) {
        val url = endpoint(path)
        try {
            val headers = mutableMapOf("Accept" to "application/json")
            if (!bearerToken.isNullOrBlank()) {
                headers["Authorization"] = "Bearer $bearerToken"
            }
            if (body != null) {
                headers["Content-Type"] = "application/json; charset=utf-8"
            }
            val response = httpTransport.request(URL(url), method, headers, body, 5_000, 8_000)
            val code = response.code
            val responseText = response.body
            when {
                code in 200..299 -> responseText
                code == 401 || code == 403 -> throw RemoteApiException.AuthRejected()
                code == 404 || code == 405 -> throw RemoteApiException.AgentUnavailable()
                else -> throw RemoteApiException.HttpFailure(code, responseText)
            }
        } catch (exception: RemoteApiException) {
            throw exception
        } catch (exception: UnknownHostException) {
            throw RemoteApiException.OfflineExpected(exception)
        } catch (exception: SocketTimeoutException) {
            throw RemoteApiException.OfflineExpected(exception)
        } catch (exception: NoRouteToHostException) {
            throw RemoteApiException.OfflineExpected(exception)
        } catch (exception: ConnectException) {
            throw RemoteApiException.AgentUnavailable(exception)
        } catch (exception: IOException) {
            throw RemoteApiException.AgentUnavailable(exception)
        } catch (exception: Exception) {
            throw RemoteApiException.DecodeFailure(exception)
        }
    }

    private fun endpoint(path: String): String {
        val trimmedBase = baseUrl.trim().trimEnd('/')
        val trimmedPath = path.trimStart('/')
        return "$trimmedBase/$trimmedPath"
    }

}
