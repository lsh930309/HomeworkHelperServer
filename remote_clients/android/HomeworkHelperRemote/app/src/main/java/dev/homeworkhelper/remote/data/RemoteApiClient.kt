package dev.homeworkhelper.remote.data

import android.net.Uri
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.IOException
import java.net.ConnectException
import java.net.HttpURLConnection
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

    suspend fun confirmPairing(code: String, deviceName: String): PairingConfirmResponse {
        val payload = JSONObject()
            .put("code", code)
            .put("device_name", deviceName)
            .put("platform", "android")
            .toString()
        return JSONObject(request("remote/pair/confirm", method = "POST", body = payload))
            .toPairingConfirmResponse()
    }

    private suspend fun request(
        path: String,
        method: String = "GET",
        body: String? = null,
    ): String = withContext(Dispatchers.IO) {
        val url = endpoint(path)
        val connection = (URL(url).openConnection() as HttpURLConnection).apply {
            requestMethod = method
            connectTimeout = 5_000
            readTimeout = 8_000
            setRequestProperty("Accept", "application/json")
            if (!bearerToken.isNullOrBlank()) {
                setRequestProperty("Authorization", "Bearer $bearerToken")
            }
            if (body != null) {
                doOutput = true
                setRequestProperty("Content-Type", "application/json; charset=utf-8")
            }
        }
        try {
            if (body != null) {
                connection.outputStream.use { stream -> stream.write(body.toByteArray(Charsets.UTF_8)) }
            }
            val code = connection.responseCode
            val responseText = readBody(connection, code)
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
        } finally {
            connection.disconnect()
        }
    }

    private fun endpoint(path: String): String {
        val trimmedBase = baseUrl.trim().trimEnd('/')
        val trimmedPath = path.trimStart('/')
        return "$trimmedBase/$trimmedPath"
    }

    private fun readBody(connection: HttpURLConnection, code: Int): String {
        val stream = if (code in 200..299) connection.inputStream else connection.errorStream
        return stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
    }
}
