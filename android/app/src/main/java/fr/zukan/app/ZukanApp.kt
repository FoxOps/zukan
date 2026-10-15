package fr.zukan.app

import android.app.Application
import fr.zukan.app.data.ApiClient
import fr.zukan.app.data.SessionStore
import kotlinx.coroutines.flow.MutableStateFlow

/** Application-wide objects: stored settings/tokens and the client of the current server. */
class ZukanApp : Application() {
    lateinit var store: SessionStore
        private set
    val client = MutableStateFlow<ApiClient?>(null)
    /** Set from OkHttp threads when the refresh token is no longer accepted. */
    val sessionExpired = MutableStateFlow(false)

    override fun onCreate() {
        super.onCreate()
        store = SessionStore(this)
    }

    fun connect(baseUrl: String): ApiClient {
        val current = client.value
        if (current != null && current.baseUrl == baseUrl) return current
        return ApiClient(baseUrl, store) { sessionExpired.value = true }.also { client.value = it }
    }
}
