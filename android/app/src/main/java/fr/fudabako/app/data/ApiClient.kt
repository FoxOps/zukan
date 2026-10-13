package fr.fudabako.app.data

import kotlinx.coroutines.runBlocking
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
import java.util.concurrent.TimeUnit

private val NO_REFRESH = listOf("/api/auth/login", "/api/auth/refresh", "/exchange")

val json = Json {
    // Send default values too (e.g. `source = "scan"`); the server has its own defaults.
    encodeDefaults = true
    ignoreUnknownKeys = true
    explicitNulls = false
}

/**
 * HTTP access to one Fudabako server: bearer token on every request and a single
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

    private val refreshApi: FudabakoApi = retrofit(plain)

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

    val api: FudabakoApi = retrofit(http)

    fun imageUrl(path: String?): String? = path?.let { baseUrl + it.removePrefix("/") }

    private fun retrofit(client: OkHttpClient): FudabakoApi = Retrofit.Builder()
        .baseUrl(baseUrl)
        .client(client)
        .addConverterFactory(json.asConverterFactory("application/json".toMediaType()))
        .build()
        .create(FudabakoApi::class.java)

    private fun Request.withToken(token: String) = newBuilder().header("Authorization", "Bearer $token").build()
}

/** Human-readable message from a failed call (FastAPI puts it in `detail`). */
fun Throwable.userMessage(): String {
    if (this is HttpException) {
        val body = response()?.errorBody()?.string().orEmpty()
        val detail = runCatching { json.parseToJsonElement(body).jsonObject["detail"] }.getOrNull()
        return when (detail) {
            is JsonPrimitive -> detail.content
            is JsonArray -> detail.joinToString { runCatching { it.jsonObject["msg"]!!.jsonPrimitive.content }.getOrDefault("") }
            else -> "Server error ${code()}"
        }
    }
    return when (this) {
        is java.net.UnknownHostException -> "Server not found"
        is java.net.ConnectException -> "Cannot reach the server"
        is java.net.SocketTimeoutException -> "The server did not answer"
        is javax.net.ssl.SSLException -> "Secure connection failed (certificate?)"
        else -> message ?: toString()
    }
}
