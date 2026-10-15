package fr.zukan.app.auth

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.core.net.toUri
import fr.zukan.app.BuildConfig
import fr.zukan.app.R
import fr.zukan.app.data.ProviderOut
import java.net.HttpURLConnection
import java.net.URL
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException
import kotlinx.coroutines.suspendCancellableCoroutine
import net.openid.appauth.AppAuthConfiguration
import net.openid.appauth.AuthorizationException
import net.openid.appauth.AuthorizationRequest
import net.openid.appauth.AuthorizationResponse
import net.openid.appauth.AuthorizationService
import net.openid.appauth.AuthorizationServiceConfiguration
import net.openid.appauth.ResponseTypeValues
import net.openid.appauth.connectivity.ConnectionBuilder

/** fr.zukan.app:/oauth2redirect, or fr.zukan.app.dev:/oauth2redirect for dev builds. */
const val REDIRECT_URI = "${BuildConfig.REDIRECT_SCHEME}:/oauth2redirect"

/** What the server needs to log in with an identity provider's ID token. */
data class SsoResult(val idToken: String, val nonce: String, val accessToken: String?)

/**
 * OpenID Connect login with AppAuth: authorization code + PKCE in a browser tab, as a
 * public client (`mobile_client_id`). The app never sees a client secret.
 */
class SsoLogin(private val context: Context) {
    // AppAuth only allows HTTPS by default; home identity providers may be plain HTTP.
    private val connections = ConnectionBuilder { uri: Uri ->
        (URL(uri.toString()).openConnection() as HttpURLConnection).apply {
            connectTimeout = 15_000
            readTimeout = 15_000
            instanceFollowRedirects = false
        }
    }
    private val service = AuthorizationService(
        context,
        AppAuthConfiguration.Builder().setConnectionBuilder(connections).build(),
    )

    suspend fun authorizationIntent(provider: ProviderOut): Pair<Intent, AuthorizationRequest> {
        val clientId = provider.mobileClientId ?: error(context.getString(R.string.error_sso_no_client, provider.displayName))
        val configuration = suspendCancellableCoroutine { cont ->
            AuthorizationServiceConfiguration.fetchFromIssuer(provider.issuer.toUri(), { config, error ->
                if (config != null) cont.resume(config) else cont.resumeWithException(error ?: IllegalStateException(context.getString(R.string.error_sso_discovery)))
            }, connections)
        }
        val request = AuthorizationRequest.Builder(
            configuration,
            clientId,
            ResponseTypeValues.CODE,
            REDIRECT_URI.toUri(),
        ).setScopes(provider.scopes).build()
        return service.getAuthorizationRequestIntent(request) to request
    }

    /** Exchange the authorization code returned to the app for the ID token. */
    suspend fun complete(data: Intent?): SsoResult {
        val response = data?.let { AuthorizationResponse.fromIntent(it) }
        if (response == null) {
            val error = data?.let { AuthorizationException.fromIntent(it) }
            throw IllegalStateException(error?.errorDescription ?: error?.error ?: context.getString(R.string.error_sso_cancelled))
        }
        val tokens = suspendCancellableCoroutine { cont ->
            service.performTokenRequest(response.createTokenExchangeRequest()) { token, error ->
                if (token != null) cont.resume(token) else cont.resumeWithException(error ?: IllegalStateException(context.getString(R.string.error_sso_token)))
            }
        }
        val idToken = tokens.idToken ?: error(context.getString(R.string.error_sso_no_id_token))
        val nonce = response.request.nonce ?: error(context.getString(R.string.error_sso_no_nonce))
        return SsoResult(idToken, nonce, tokens.accessToken)
    }

    fun dispose() = service.dispose()
}
