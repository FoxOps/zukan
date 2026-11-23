package fr.zukan.app

import android.app.Application
import android.content.Context
import coil3.disk.DiskCache
import coil3.disk.directory
import coil3.memory.MemoryCache
import fr.zukan.app.data.ApiClient
import fr.zukan.app.data.AppLanguage
import fr.zukan.app.data.SessionStore
import kotlinx.coroutines.flow.MutableStateFlow

/** Application-wide objects: stored settings/tokens and the client of the current server. */
class ZukanApp : Application() {
    lateinit var store: SessionStore
        private set
    val client = MutableStateFlow<ApiClient?>(null)
    /** Set from OkHttp threads when the refresh token is no longer accepted. */
    val sessionExpired = MutableStateFlow(false)

    /** Card pictures in memory and on disk, kept when the server or account changes (the
     * image loader is rebuilt then). Lists ask for small pictures, so these go far. */
    val imageMemory: MemoryCache by lazy { MemoryCache.Builder().maxSizePercent(this, 0.15).build() }
    val imageDisk: DiskCache by lazy {
        DiskCache.Builder().directory(cacheDir.resolve("images")).maxSizeBytes(IMAGE_DISK_BYTES).build()
    }

    override fun attachBaseContext(base: Context) = super.attachBaseContext(AppLanguage.wrap(base))

    override fun onCreate() {
        super.onCreate()
        store = SessionStore(this)
    }

    /** The current session ([SessionStore.generation]): what is shown for one account or
     * server (scanner result, lists, undo) goes when it changes. */
    val session = MutableStateFlow(0L)

    /** The client of [baseUrl]. Another server ends the current session first: its tokens
     * never go to the new server, and the old server's calls are cancelled. */
    suspend fun connect(baseUrl: String): ApiClient {
        val current = client.value
        if (current != null && current.baseUrl == baseUrl && current.generation == store.generation) return current
        if (current != null && current.baseUrl != baseUrl) store.invalidate()
        return replaceClient(baseUrl)
    }

    /** Logout, expiry or disconnection: the session's tokens go and its calls stop; the same
     * server gets a fresh client (none without [baseUrl]). */
    suspend fun endSession(baseUrl: String? = client.value?.baseUrl) {
        store.invalidate()
        if (baseUrl == null) {
            client.value?.close()
            client.value = null
            session.value = store.generation
        } else {
            replaceClient(baseUrl)
        }
    }

    private fun replaceClient(baseUrl: String): ApiClient {
        val old = client.value
        val generation = store.generation
        val fresh = ApiClient(baseUrl, store, generation = generation) {
            if (store.generation == generation) sessionExpired.value = true
        }
        client.value = fresh
        session.value = generation
        old?.close()
        return fresh
    }

    private companion object {
        const val IMAGE_DISK_BYTES = 100L * 1024 * 1024
    }
}
