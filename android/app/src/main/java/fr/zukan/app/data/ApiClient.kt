package fr.zukan.app.data

import android.content.Context
import fr.zukan.app.R
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withContext
import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import okhttp3.Authenticator
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.Route
import retrofit2.HttpException
import retrofit2.Retrofit
import retrofit2.converter.kotlinx.serialization.asConverterFactory

private val NO_REFRESH = listOf("/api/auth/login", "/api/auth/refresh", "/exchange")

val json = Json {
    // Send default values too (e.g. `source = "scan"`); the server has its own defaults.
    encodeDefaults = true
    ignoreUnknownKeys = true
    explicitNulls = false
}

/**
 * HTTP access to one Zukan server: bearer token on every request and a single
 * refresh-token rotation when the access token expires.
 */
class ApiClient(
    val baseUrl: String,
    private val store: TokenStore,
    private val onSessionExpired: () -> Unit,
) {
    private val plain: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(30, TimeUnit.SECONDS)
        .build()

    private val refreshApi: ZukanApi = retrofit(plain)

    private val bearer = Interceptor { chain ->
        val token = store.tokens?.access
        val request = chain.request()
        chain.proceed(if (token == null) request else request.withToken(token))
    }

    private val refresher = object : Authenticator {
        override fun authenticate(route: Route?, response: Response): Request? {
            // A 401 from login/refresh endpoints means bad credentials, not an expired token.
            val path = response.request.url.encodedPath
            if (NO_REFRESH.any { path.endsWith(it) }) return null
            if (response.priorResponse != null) return null // already retried once
            synchronized(this) {
                val current = store.tokens ?: return null
                val sent = response.request.header("Authorization")?.removePrefix("Bearer ")
                // Another request refreshed meanwhile: just retry with the new token.
                if (sent != current.access) return response.request.withToken(current.access)
                val renewed = runCatching {
                    runBlocking { refreshApi.refresh(RefreshIn(current.refresh)) }
                }.getOrNull()
                if (renewed == null) {
                    runBlocking { store.saveTokens(null) }
                    onSessionExpired()
                    return null
                }
                val tokens = Tokens(renewed.accessToken, renewed.refreshToken)
                runBlocking { store.saveTokens(tokens) }
                return response.request.withToken(tokens.access)
            }
        }
    }

    /** Also used by the image loader, so card pictures carry the token too. */
    val http: OkHttpClient = plain.newBuilder()
        .addInterceptor(bearer)
        .authenticator(refresher)
        .build()

    val api: ZukanApi = retrofit(http)

    /**
     * The base URL the server really answers on: follows a proxy redirect such as
     * http → https (a redirected POST would turn into a GET, so login must not rely on it).
     * A redirect from https to http is ignored.
     */
    suspend fun redirectedBaseUrl(): String = withContext(Dispatchers.IO) {
        val request = Request.Builder().url(baseUrl + "api/health").build()
        plain.newCall(request).execute().use { response ->
            ServerUrl.redirectedBase(baseUrl, response.request.url.toString()) ?: baseUrl
        }
    }

    fun imageUrl(path: String?): String? = path?.let { baseUrl + it.removePrefix("/") }

    private fun retrofit(client: OkHttpClient): ZukanApi = Retrofit.Builder()
        .baseUrl(baseUrl)
        .client(client)
        .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
        .build()
        .create(ZukanApi::class.java)

    private fun Request.withToken(token: String) = newBuilder().header("Authorization", "Bearer $token").build()
}

/** Human-readable message from a failed call, in the app's language except for server details. */
fun Throwable.userMessage(context: Context): String {
    if (this is HttpException) return serverDetail() ?: context.getString(R.string.error_server, code())
    return when (this) {
        is java.net.UnknownHostException -> context.getString(R.string.error_unknown_host)
        is java.net.ConnectException -> context.getString(R.string.error_connect)
        is java.net.SocketTimeoutException -> context.getString(R.string.error_timeout)
        is javax.net.ssl.SSLException -> context.getString(
            when (sslKind()) {
                SslKind.HOSTNAME -> R.string.error_ssl_hostname
                SslKind.UNTRUSTED -> R.string.error_ssl_untrusted
                SslKind.PLAIN -> R.string.error_ssl_plain
                SslKind.OTHER -> R.string.error_ssl
            },
            sslDetail(),
        )
        else -> message ?: toString()
    }
}

/** The message of a failed HTTP call, as written by the server (FastAPI puts it in `detail`). */
fun Throwable.serverDetail(): String? {
    if (this !is HttpException) return null
    val body = response()?.errorBody()?.string().orEmpty()
    return when (val detail = runCatching { json.parseToJsonElement(body).jsonObject["detail"] }.getOrNull()) {
        is JsonPrimitive -> detail.content
        is JsonArray -> detail.joinToString { runCatching { it.jsonObject["msg"]!!.jsonPrimitive.content }.getOrDefault("") }
        else -> null
    }
}
