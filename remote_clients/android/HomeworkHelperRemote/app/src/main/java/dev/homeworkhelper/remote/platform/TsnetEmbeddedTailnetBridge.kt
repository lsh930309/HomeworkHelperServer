package dev.homeworkhelper.remote.platform

import android.content.Context
import android.provider.Settings
import dev.homeworkhelper.remote.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.io.File
import java.io.IOException
import java.io.InputStream
import java.io.OutputStream
import java.lang.reflect.InvocationTargetException
import java.lang.reflect.Method
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.Socket
import java.net.SocketAddress
import java.net.SocketException
import java.net.SocketTimeoutException
import java.net.URL
import java.util.Locale
import kotlin.math.min

private const val TSNET_STATUS_TIMEOUT_MILLIS = 2_000L
private const val TSNET_CONNECT_TIMEOUT_MILLIS = 15_000L
private const val TSNET_MAX_READ_BYTES = 64 * 1024
private const val TSNET_BRIDGE_FACTORY_CLASS = "dev.homeworkhelper.remote.nativebridge.tailnetbridge.Tailnetbridge"
private const val TSNET_BRIDGE_CLASS = "dev.homeworkhelper.remote.nativebridge.tailnetbridge.Bridge"

class TsnetEmbeddedTailnetBridge(context: Context) : EmbeddedTailnetBridge {
    private val appContext = context.applicationContext
    private val nativeBridge: Result<NativeTsnetBridge> by lazy { loadNativeBridge() }

    override suspend fun inspect(): RemoteNetworkState = withContext(Dispatchers.IO) {
        nativeBridge.fold(
            onSuccess = { bridge ->
                runCatching {
                    bridge.decodeState(bridge.statusJson(TSNET_STATUS_TIMEOUT_MILLIS), "내장 tailnet 상태 확인")
                }.getOrElse {
                    unavailableState(it, "내장 tailnet 상태 확인", bridgeAvailable = true)
                }
            },
            onFailure = { unavailableState(it) },
        )
    }

    override suspend fun ensureConnected(reason: String): RemoteNetworkState = withContext(Dispatchers.IO) {
        nativeBridge.fold(
            onSuccess = { bridge ->
                runCatching {
                    bridge.decodeState(bridge.ensureConnectedJson(TSNET_CONNECT_TIMEOUT_MILLIS), reason)
                }.getOrElse {
                    unavailableState(it, reason, bridgeAvailable = true)
                }
            },
            onFailure = { unavailableState(it, reason) },
        )
    }

    override suspend fun disconnect(): RemoteNetworkState = withContext(Dispatchers.IO) {
        nativeBridge.fold(
            onSuccess = { bridge ->
                runCatching {
                    bridge.stop()
                    RemoteNetworkState(
                        mode = RemoteNetworkMode.EmbeddedTailnet,
                        status = RemoteNetworkStatus.Disabled,
                        engine = "tsnet",
                        message = "앱 내장 tailnet 노드를 중지했습니다.",
                        lastAction = "내장 tailnet 중지",
                        bridgeAvailable = true,
                    )
                }.getOrElse {
                    unavailableState(it, "내장 tailnet 중지", bridgeAvailable = true)
                }
            },
            onFailure = { unavailableState(it, "내장 tailnet 중지") },
        )
    }

    override suspend fun request(
        url: URL,
        method: String,
        headers: Map<String, String>,
        body: String?,
        connectTimeoutMillis: Int,
        readTimeoutMillis: Int,
    ): RemoteHttpResponse = withContext(Dispatchers.IO) {
        val bridge = nativeBridge.getOrElse { throw RemoteNetworkUnavailableException(unavailableMessage(it)) }
        val response = JSONObject(
            bridge.requestJson(
                method = method,
                rawUrl = url.toString(),
                headersJson = JSONObject(headers).toString(),
                body = body.orEmpty(),
                connectTimeoutMillis = connectTimeoutMillis.toLong(),
                readTimeoutMillis = readTimeoutMillis.toLong(),
            ),
        )
        RemoteHttpResponse(
            code = response.optInt("code", 0),
            body = response.optString("body", ""),
        )
    }

    override fun openSocket(
        host: String,
        port: Int,
        timeoutMillis: Int,
        localAddress: InetAddress?,
        localPort: Int,
    ): Socket {
        if (localAddress != null || localPort != 0) {
            throw RemoteNetworkUnavailableException("내장 tailnet socket은 local bind를 지원하지 않습니다.")
        }
        val bridge = nativeBridge.getOrElse { throw RemoteNetworkUnavailableException(unavailableMessage(it)) }
        val connId = bridge.openTcp(host, port.toLong(), timeoutMillis.toLong())
        return TsnetSocket(bridge, connId, InetSocketAddress(host, port))
    }

    private fun loadNativeBridge(): Result<NativeTsnetBridge> {
        return runCatching {
            NativeTsnetBridge.create(
                stateDir = File(appContext.filesDir, "tailnetbridge").absolutePath,
                hostname = configuredHostname(appContext),
                controlUrl = BuildConfig.EMBEDDED_TAILNET_CONTROL_URL.trim(),
            )
        }
    }
}

private class NativeTsnetBridge private constructor(private val bridge: Any) {
    private val bridgeClass: Class<*> = Class.forName(TSNET_BRIDGE_CLASS)
    private val configureMethod: Method = bridgeClass.getMethod("configure", String::class.java, String::class.java, String::class.java)
    private val ensureConnectedJsonMethod: Method = bridgeClass.getMethod("ensureConnectedJson", java.lang.Long.TYPE)
    private val statusJsonMethod: Method = bridgeClass.getMethod("statusJson", java.lang.Long.TYPE)
    private val requestJsonMethod: Method = bridgeClass.getMethod(
        "requestJson",
        String::class.java,
        String::class.java,
        String::class.java,
        String::class.java,
        java.lang.Long.TYPE,
        java.lang.Long.TYPE,
    )
    private val openTcpMethod: Method = bridgeClass.getMethod("openTcp", String::class.java, java.lang.Long.TYPE, java.lang.Long.TYPE)
    private val readMethod: Method = bridgeClass.getMethod("read", java.lang.Long.TYPE, java.lang.Long.TYPE, java.lang.Long.TYPE)
    private val writeMethod: Method = bridgeClass.getMethod("write", java.lang.Long.TYPE, ByteArray::class.java)
    private val closeConnMethod: Method = bridgeClass.getMethod("closeConn", java.lang.Long.TYPE)
    private val stopMethod: Method = bridgeClass.getMethod("stop")

    fun configure(stateDir: String, hostname: String, controlUrl: String) {
        invoke(configureMethod, stateDir, hostname, controlUrl)
    }

    fun ensureConnectedJson(timeoutMillis: Long): String {
        return invoke(ensureConnectedJsonMethod, timeoutMillis) as String
    }

    fun statusJson(timeoutMillis: Long): String {
        return invoke(statusJsonMethod, timeoutMillis) as String
    }

    fun requestJson(
        method: String,
        rawUrl: String,
        headersJson: String,
        body: String,
        connectTimeoutMillis: Long,
        readTimeoutMillis: Long,
    ): String {
        return invoke(requestJsonMethod, method, rawUrl, headersJson, body, connectTimeoutMillis, readTimeoutMillis) as String
    }

    fun openTcp(host: String, port: Long, timeoutMillis: Long): Long {
        return invoke(openTcpMethod, host, port, timeoutMillis) as Long
    }

    fun read(connId: Long, maxBytes: Long, timeoutMillis: Long): ByteArray {
        return invoke(readMethod, connId, maxBytes, timeoutMillis) as ByteArray
    }

    fun write(connId: Long, data: ByteArray): Long {
        return invoke(writeMethod, connId, data) as Long
    }

    fun closeConn(connId: Long) {
        invoke(closeConnMethod, connId)
    }

    fun stop() {
        invoke(stopMethod)
    }

    fun decodeState(raw: String, lastAction: String): RemoteNetworkState {
        val json = JSONObject(raw)
        val backend = json.optString("backend_state", "")
        val selfIps = json.optJSONArray("self_ips")
        val ipText = if (selfIps != null && selfIps.length() > 0) {
            (0 until selfIps.length()).joinToString(",") { index -> selfIps.optString(index) }
        } else {
            ""
        }
        val engine = buildString {
            append("tsnet")
            if (backend.isNotBlank()) append(" / ").append(backend)
            if (ipText.isNotBlank()) append(" / ").append(ipText)
        }
        return RemoteNetworkState(
            mode = RemoteNetworkMode.EmbeddedTailnet,
            status = json.optString("status").toRemoteNetworkStatus(),
            engine = engine,
            message = json.optString("message", "tsnet 상태를 확인했습니다."),
            lastAction = lastAction,
            authUrl = json.optString("auth_url", ""),
            bridgeAvailable = true,
        )
    }

    private fun invoke(method: Method, vararg args: Any?): Any? {
        return try {
            method.invoke(bridge, *args)
        } catch (error: InvocationTargetException) {
            throw error.targetException.asIOException()
        } catch (error: ReflectiveOperationException) {
            throw IOException("native tailnet bridge 호출 실패: ${error.message}", error)
        } catch (error: LinkageError) {
            throw IOException("native tailnet bridge link 실패: ${error.message}", error)
        }
    }

    companion object {
        fun create(stateDir: String, hostname: String, controlUrl: String): NativeTsnetBridge {
            val factoryClass = Class.forName(TSNET_BRIDGE_FACTORY_CLASS)
            val bridge = factoryClass.getMethod("newBridge").invoke(null)
                ?: throw IOException("native tailnet bridge factory returned null")
            return NativeTsnetBridge(bridge).also {
                it.configure(stateDir, hostname, controlUrl)
            }
        }
    }
}

private class TsnetSocket(
    private val bridge: NativeTsnetBridge,
    private val connId: Long,
    private val remoteAddress: InetSocketAddress,
) : Socket() {
    @Volatile private var closed = false
    @Volatile private var soTimeoutMillis = 0
    private val input = TsnetInputStream(this)
    private val output = TsnetOutputStream(this)

    override fun getInputStream(): InputStream {
        ensureOpen()
        return input
    }

    override fun getOutputStream(): OutputStream {
        ensureOpen()
        return output
    }

    override fun close() {
        if (closed) return
        closed = true
        bridge.closeConn(connId)
    }

    override fun isConnected(): Boolean = !closed

    override fun isClosed(): Boolean = closed

    override fun setSoTimeout(timeout: Int) {
        soTimeoutMillis = timeout.coerceAtLeast(0)
    }

    override fun getSoTimeout(): Int = soTimeoutMillis

    override fun getInetAddress(): InetAddress? = runCatching { InetAddress.getByName(remoteAddress.hostString) }.getOrNull()

    override fun getRemoteSocketAddress(): SocketAddress = remoteAddress

    override fun getPort(): Int = remoteAddress.port

    internal fun read(maxBytes: Int): ByteArray {
        ensureOpen()
        return try {
            bridge.read(connId, min(maxBytes, TSNET_MAX_READ_BYTES).toLong(), soTimeoutMillis.toLong())
        } catch (error: IOException) {
            if (error.message?.contains("i/o timeout", ignoreCase = true) == true) {
                throw SocketTimeoutException(error.message)
            }
            throw error
        }
    }

    internal fun write(bytes: ByteArray) {
        ensureOpen()
        bridge.write(connId, bytes)
    }

    private fun ensureOpen() {
        if (closed) throw SocketException("socket is closed")
    }
}

private class TsnetInputStream(private val socket: TsnetSocket) : InputStream() {
    private val oneByte = ByteArray(1)

    override fun read(): Int {
        val count = read(oneByte, 0, 1)
        return if (count < 0) -1 else oneByte[0].toInt() and 0xff
    }

    override fun read(buffer: ByteArray, offset: Int, length: Int): Int {
        if (offset < 0 || length < 0 || length > buffer.size - offset) {
            throw IndexOutOfBoundsException()
        }
        if (length == 0) return 0
        val bytes = socket.read(length)
        if (bytes.isEmpty()) return -1
        bytes.copyInto(buffer, offset)
        return bytes.size
    }
}

private class TsnetOutputStream(private val socket: TsnetSocket) : OutputStream() {
    override fun write(value: Int) {
        socket.write(byteArrayOf(value.toByte()))
    }

    override fun write(buffer: ByteArray, offset: Int, length: Int) {
        if (offset < 0 || length < 0 || length > buffer.size - offset) {
            throw IndexOutOfBoundsException()
        }
        if (length == 0) return
        socket.write(buffer.copyOfRange(offset, offset + length))
    }
}

private fun Throwable.asIOException(): IOException {
    if (this is IOException) return this
    return IOException(message ?: javaClass.simpleName, this)
}

private fun String.toRemoteNetworkStatus(): RemoteNetworkStatus {
    return when (lowercase(Locale.US)) {
        "disabled" -> RemoteNetworkStatus.Disabled
        "needs_auth" -> RemoteNetworkStatus.NeedsAuth
        "connecting" -> RemoteNetworkStatus.Connecting
        "connected" -> RemoteNetworkStatus.Connected
        "degraded" -> RemoteNetworkStatus.Degraded
        else -> RemoteNetworkStatus.Unavailable
    }
}

private fun unavailableState(
    error: Throwable,
    lastAction: String = "",
    bridgeAvailable: Boolean = false,
): RemoteNetworkState {
    return RemoteNetworkState(
        mode = RemoteNetworkMode.EmbeddedTailnet,
        status = RemoteNetworkStatus.Unavailable,
        engine = "tsnet",
        message = unavailableMessage(error),
        lastAction = lastAction,
        bridgeAvailable = bridgeAvailable,
    )
}

private fun unavailableMessage(error: Throwable): String {
    val detail = error.message?.takeIf { it.isNotBlank() } ?: error.javaClass.simpleName
    if (detail.lowercase(Locale.US).contains("netlinkrib: permission denied")) {
        return "Android 권한 제한으로 내장 tailnet 초기화가 거부되었습니다: $detail"
    }
    return "내장 tailnet AAR가 포함되지 않았거나 초기화에 실패했습니다: $detail"
}

private fun configuredHostname(context: Context): String {
    val configured = BuildConfig.EMBEDDED_TAILNET_HOSTNAME.trim()
    if (configured.isNotBlank()) return sanitizeHostname(configured)
    val androidId = Settings.Secure.getString(context.contentResolver, Settings.Secure.ANDROID_ID).orEmpty()
    val suffix = androidId.takeLast(6).ifBlank { "device" }
    return sanitizeHostname("homeworkhelper-android-$suffix")
}

private fun sanitizeHostname(value: String): String {
    val sanitized = value
        .lowercase(Locale.US)
        .replace(Regex("[^a-z0-9-]"), "-")
        .trim('-')
    return sanitized.ifBlank { "homeworkhelper-android" }
}
