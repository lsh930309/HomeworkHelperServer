package dev.homeworkhelper.remote.platform

import android.util.Base64
import java.io.ByteArrayOutputStream
import java.io.DataOutputStream
import java.math.BigInteger
import java.security.KeyPairGenerator
import java.security.interfaces.RSAPrivateKey
import java.security.interfaces.RSAPublicKey

class AndroidSSHKeyStore(private val preferences: AutomationPreferences) {
    fun ensureKeyPair(): SshKeyPair {
        val existingPrivateKey = preferences.loadPrivateKey()
        val existingPublicKey = preferences.sshPublicKey
        if (!existingPrivateKey.isNullOrBlank() && existingPublicKey.isNotBlank()) {
            return SshKeyPair(existingPrivateKey, existingPublicKey)
        }
        val generator = KeyPairGenerator.getInstance("RSA")
        generator.initialize(3072)
        val keyPair = generator.generateKeyPair()
        val privateKey = keyPair.private as RSAPrivateKey
        val publicKey = keyPair.public as RSAPublicKey
        val privatePem = privateKey.toPkcs8Pem()
        val publicLine = publicKey.toAuthorizedKeyLine()
        preferences.savePrivateKey(privatePem)
        preferences.sshPublicKey = publicLine
        preferences.sshHealthOk = false
        return SshKeyPair(privatePem, publicLine)
    }

    fun loadPrivateKey(): String? = preferences.loadPrivateKey()
}

data class SshKeyPair(
    val privateKeyPem: String,
    val publicKeyLine: String,
)

private fun RSAPrivateKey.toPkcs8Pem(): String {
    val encoded = Base64.encodeToString(encoded, Base64.NO_WRAP)
        .chunked(64)
        .joinToString("\n")
    return "-----BEGIN PRIVATE KEY-----\n$encoded\n-----END PRIVATE KEY-----"
}

private fun RSAPublicKey.toAuthorizedKeyLine(): String {
    val blob = ByteArrayOutputStream().use { output ->
        DataOutputStream(output).use { data ->
            data.writeSshString("ssh-rsa".toByteArray(Charsets.US_ASCII))
            data.writeSshString(publicExponent.toMpint())
            data.writeSshString(modulus.toMpint())
        }
        output.toByteArray()
    }
    val encoded = Base64.encodeToString(blob, Base64.NO_WRAP)
    return "ssh-rsa $encoded homeworkhelper-android"
}

private fun DataOutputStream.writeSshString(bytes: ByteArray) {
    writeInt(bytes.size)
    write(bytes)
}

private fun BigInteger.toMpint(): ByteArray = toByteArray()
