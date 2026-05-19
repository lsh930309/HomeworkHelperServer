package dev.homeworkhelper.remote.platform

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

interface TokenStore {
    fun loadToken(): String?
    fun saveToken(token: String)
    fun clearToken()
}

class AndroidTokenStore(context: Context) : TokenStore {
    private val preferences = context.getSharedPreferences("homeworkhelper.remote.token", Context.MODE_PRIVATE)

    override fun loadToken(): String? {
        val encoded = preferences.getString(KEY_TOKEN, null) ?: return null
        return runCatching {
            val payload = Base64.decode(encoded, Base64.NO_WRAP)
            val iv = payload.copyOfRange(0, GCM_IV_LENGTH)
            val ciphertext = payload.copyOfRange(GCM_IV_LENGTH, payload.size)
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.DECRYPT_MODE, secretKey(), GCMParameterSpec(GCM_TAG_LENGTH, iv))
            String(cipher.doFinal(ciphertext), Charsets.UTF_8)
        }.getOrElse {
            clearToken()
            null
        }
    }

    override fun saveToken(token: String) {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, secretKey())
        val ciphertext = cipher.doFinal(token.toByteArray(Charsets.UTF_8))
        val payload = cipher.iv + ciphertext
        preferences.edit().putString(KEY_TOKEN, Base64.encodeToString(payload, Base64.NO_WRAP)).apply()
    }

    override fun clearToken() {
        preferences.edit().remove(KEY_TOKEN).apply()
    }

    private fun secretKey(): SecretKey {
        val keyStore = KeyStore.getInstance(ANDROID_KEYSTORE).apply { load(null) }
        (keyStore.getKey(KEY_ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, ANDROID_KEYSTORE)
        val spec = KeyGenParameterSpec.Builder(
            KEY_ALIAS,
            KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
        )
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setRandomizedEncryptionRequired(true)
            .build()
        generator.init(spec)
        return generator.generateKey()
    }

    companion object {
        private const val ANDROID_KEYSTORE = "AndroidKeyStore"
        private const val KEY_ALIAS = "homeworkhelper_remote_token_key"
        private const val KEY_TOKEN = "encrypted_bearer_token"
        private const val TRANSFORMATION = "AES/GCM/NoPadding"
        private const val GCM_IV_LENGTH = 12
        private const val GCM_TAG_LENGTH = 128
    }
}
