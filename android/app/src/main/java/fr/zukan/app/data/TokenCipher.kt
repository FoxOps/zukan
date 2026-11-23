package fr.zukan.app.data

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Log
import java.security.KeyStore
import java.util.Base64
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Encrypts stored tokens; null when it cannot (the caller decides what to do). */
interface TokenCipher {
    fun encrypt(plain: String): String?
    fun decrypt(stored: String): String?
}

/**
 * AES-GCM with a key kept in the Android Keystore: copied app data alone does not give the
 * tokens. No user authentication is asked (tokens are refreshed in the background), so
 * nothing changes for the user. A lost key (rare: device reset of the Keystore) only means
 * logging in again.
 */
object KeystoreCipher : TokenCipher {
    private const val TAG = "KeystoreCipher"
    private const val STORE = "AndroidKeyStore"
    private const val ALIAS = "zukan_tokens"
    private const val TRANSFORMATION = "AES/GCM/NoPadding"
    private const val TAG_BITS = 128

    private fun key(): SecretKey {
        val store = KeyStore.getInstance(STORE).apply { load(null) }
        (store.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, STORE)
        generator.init(
            KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build(),
        )
        return generator.generateKey()
    }

    override fun encrypt(plain: String): String? = runCatching {
        val cipher = Cipher.getInstance(TRANSFORMATION).apply { init(Cipher.ENCRYPT_MODE, key()) }
        val sealed = cipher.doFinal(plain.toByteArray())
        val encoder = Base64.getEncoder()
        encoder.encodeToString(cipher.iv) + ":" + encoder.encodeToString(sealed)
    }.onFailure { Log.w(TAG, "Token encryption failed", it) }.getOrNull()

    override fun decrypt(stored: String): String? = runCatching {
        val (iv, sealed) = stored.split(':', limit = 2).map { Base64.getDecoder().decode(it) }
        val cipher = Cipher.getInstance(TRANSFORMATION).apply { init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(TAG_BITS, iv)) }
        String(cipher.doFinal(sealed))
    }.onFailure { Log.w(TAG, "Token decryption failed", it) }.getOrNull()
}
