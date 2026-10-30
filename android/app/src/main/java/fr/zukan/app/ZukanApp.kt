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

    fun connect(baseUrl: String): ApiClient {
        val current = client.value
        if (current != null && current.baseUrl == baseUrl) return current
        return ApiClient(baseUrl, store) { sessionExpired.value = true }.also { client.value = it }
    }

    private companion object {
        const val IMAGE_DISK_BYTES = 100L * 1024 * 1024
    }
}
