package dev.homeworkhelper.remote.platform

import android.content.Context
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.net.HttpURLConnection
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.Socket
import java.net.SocketAddress
import java.net.URL
import javax.net.SocketFactory

enum class RemoteNetworkMode(val wireName: String, val label: String) {
    SystemRoute("system", "Android system route"),
}

enum class RemoteNetworkStatus(val label: String, val ready: Boolean) {
    Disabled("disabled", false),
    NeedsAuth("needs auth", false),
    Connecting("connecting", false),
    Connected("connected", true),
    Degraded("degraded", true),
    Unavailable("unavailable", false),
}

data class RemoteNetworkState(
    val mode: RemoteNetworkMode = RemoteNetworkMode.SystemRoute,
    val status: RemoteNetworkStatus = RemoteNetworkStatus.Connected,
    val engine: String = "system",
    val message: String = "Android system network route를 사용합니다.",
    val lastAction: String = "",
) {
    val ready: Boolean
        get() = status.ready
}

data class RemoteHttpResponse(
    val code: Int,
    val body: String,
)

interface RemoteHttpTransport {
    suspend fun request(
        url: URL,
        method: String,
        headers: Map<String, String>,
        body: String?,
        connectTimeoutMillis: Int,
        readTimeoutMillis: Int,
    ): RemoteHttpResponse
}

class RemoteNetworkUnavailableException(message: String) : IOException(message)

interface RemoteNetworkController : RemoteHttpTransport {
    val mode: RemoteNetworkMode
    val initialState: RemoteNetworkState
    suspend fun inspect(): RemoteNetworkState
    suspend fun ensureConnected(reason: String): RemoteNetworkState
    suspend fun disconnect(): RemoteNetworkState
    fun openSocket(
        host: String,
        port: Int,
        timeoutMillis: Int = 0,
        localAddress: InetAddress? = null,
        localPort: Int = 0,
    ): Socket
}

class SystemRemoteNetworkController : RemoteNetworkController {
    override val mode: RemoteNetworkMode = RemoteNetworkMode.SystemRoute
    override val initialState: RemoteNetworkState = RemoteNetworkState(
        mode = mode,
        status = RemoteNetworkStatus.Connected,
        engine = "system",
        message = "Android system network route를 사용합니다.",
    )

    override suspend fun inspect(): RemoteNetworkState = initialState

    override suspend fun ensureConnected(reason: String): RemoteNetworkState {
        return initialState.copy(lastAction = "$reason system route 확인")
    }

    override suspend fun disconnect(): RemoteNetworkState {
        return initialState.copy(lastAction = "system route는 앱에서 끄지 않습니다.")
    }

    override suspend fun request(
        url: URL,
        method: String,
        headers: Map<String, String>,
        body: String?,
        connectTimeoutMillis: Int,
        readTimeoutMillis: Int,
    ): RemoteHttpResponse {
        val connection = url.openConnection() as HttpURLConnection
        try {
            connection.requestMethod = method
            connection.connectTimeout = connectTimeoutMillis
            connection.readTimeout = readTimeoutMillis
            headers.forEach { (key, value) -> connection.setRequestProperty(key, value) }
            if (body != null) {
                connection.doOutput = true
                connection.outputStream.use { stream -> stream.write(body.toByteArray(Charsets.UTF_8)) }
            }
            val code = connection.responseCode
            return RemoteHttpResponse(code, readBody(connection, code))
        } finally {
            connection.disconnect()
        }
    }

    override fun openSocket(
        host: String,
        port: Int,
        timeoutMillis: Int,
        localAddress: InetAddress?,
        localPort: Int,
    ): Socket {
        return Socket().apply {
            if (localAddress != null) bind(InetSocketAddress(localAddress, localPort))
            connect(InetSocketAddress(host, port), timeoutMillis)
        }
    }
}

private fun readBody(connection: HttpURLConnection, code: Int): String {
    val stream = if (code in 200..299) connection.inputStream else connection.errorStream
    return stream?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
}

object RemoteNetworkControllers {
    @Suppress("UNUSED_PARAMETER")
    fun create(context: Context): RemoteNetworkController {
        return SystemRemoteNetworkController()
    }
}

class RemoteNetworkSocketFactory(private val controller: RemoteNetworkController) : SocketFactory() {
    override fun createSocket(): Socket {
        return RemoteNetworkSocket(controller)
    }

    override fun createSocket(host: String, port: Int): Socket {
        return controller.openSocket(host, port)
    }

    override fun createSocket(address: InetAddress, port: Int): Socket {
        return controller.openSocket(address.remoteHost(), port)
    }

    override fun createSocket(host: String, port: Int, localAddress: InetAddress, localPort: Int): Socket {
        return controller.openSocket(host, port, localAddress = localAddress, localPort = localPort)
    }

    override fun createSocket(address: InetAddress, port: Int, localAddress: InetAddress, localPort: Int): Socket {
        return controller.openSocket(address.remoteHost(), port, localAddress = localAddress, localPort = localPort)
    }

    private fun InetAddress.remoteHost(): String = hostAddress ?: hostName
}

private class RemoteNetworkSocket(private val controller: RemoteNetworkController) : Socket() {
    private var delegate: Socket? = null
    private var pendingBind: SocketAddress? = null
    private var pendingSoTimeout: Int = 0
    private var closed: Boolean = false

    override fun connect(endpoint: SocketAddress?) {
        connect(endpoint, 0)
    }

    override fun connect(endpoint: SocketAddress?, timeout: Int) {
        if (closed) throw RemoteNetworkUnavailableException("socket이 이미 닫혔습니다.")
        val inetEndpoint = endpoint as? InetSocketAddress
            ?: throw RemoteNetworkUnavailableException("지원하지 않는 socket endpoint입니다: $endpoint")
        val bindEndpoint = pendingBind as? InetSocketAddress
        delegate = controller.openSocket(
            inetEndpoint.hostString,
            inetEndpoint.port,
            timeout,
            bindEndpoint?.address,
            bindEndpoint?.port ?: 0,
        ).also { socket ->
            if (pendingSoTimeout > 0) socket.soTimeout = pendingSoTimeout
        }
    }

    override fun bind(bindpoint: SocketAddress?) {
        if (closed) throw RemoteNetworkUnavailableException("socket이 이미 닫혔습니다.")
        pendingBind = bindpoint
    }

    override fun getInputStream(): InputStream {
        return active().getInputStream()
    }

    override fun getOutputStream(): OutputStream {
        return active().getOutputStream()
    }

    override fun close() {
        closed = true
        delegate?.close()
    }

    override fun isConnected(): Boolean {
        return delegate?.isConnected == true
    }

    override fun isClosed(): Boolean {
        return closed || delegate?.isClosed == true
    }

    override fun setSoTimeout(timeout: Int) {
        pendingSoTimeout = timeout
        delegate?.soTimeout = timeout
    }

    override fun getSoTimeout(): Int {
        return delegate?.soTimeout ?: pendingSoTimeout
    }

    override fun getInetAddress(): InetAddress? {
        return delegate?.inetAddress
    }

    override fun getLocalAddress(): InetAddress? {
        return delegate?.localAddress
    }

    override fun getPort(): Int {
        return delegate?.port ?: 0
    }

    override fun getLocalPort(): Int {
        return delegate?.localPort ?: 0
    }

    private fun active(): Socket {
        return delegate ?: throw RemoteNetworkUnavailableException("socket이 아직 연결되지 않았습니다.")
    }
}
