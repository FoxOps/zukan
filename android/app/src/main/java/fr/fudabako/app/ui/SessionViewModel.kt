package fr.fudabako.app.ui

import android.app.Application
import android.content.Intent
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import fr.fudabako.app.FudabakoApp
import fr.fudabako.app.auth.SsoLogin
import fr.fudabako.app.data.ApiClient
import fr.fudabako.app.data.GameOut
import fr.fudabako.app.data.LoginIn
import fr.fudabako.app.data.OidcExchangeIn
import fr.fudabako.app.data.ProviderOut
import fr.fudabako.app.data.ProvidersOut
import fr.fudabako.app.data.RefreshIn
import fr.fudabako.app.data.ServerUrl
import fr.fudabako.app.data.Settings
import fr.fudabako.app.data.TokenOut
import fr.fudabako.app.data.Tokens
import fr.fudabako.app.data.userMessage
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class SessionState(
    val loading: Boolean = true,
    val busy: Boolean = false,
    val serverUrl: String = "",
    val providers: ProvidersOut? = null,
    val username: String? = null,
    val games: List<GameOut> = emptyList(),
    val error: String? = null,
) {
    val loggedIn get() = username != null
}

class SessionViewModel(application: Application) : AndroidViewModel(application) {
    private val app = application as FudabakoApp
    private val sso = SsoLogin(application)
    private val _state = MutableStateFlow(SessionState())
    val state: StateFlow<SessionState> = _state.asStateFlow()
    val settings: StateFlow<Settings> = app.store.settings.stateIn(viewModelScope, SharingStarted.Eagerly, Settings())
    private var pendingProvider: ProviderOut? = null

    init {
        viewModelScope.launch {
            val saved = app.store.load()
            _state.update { it.copy(serverUrl = saved.serverUrl) }
            if (saved.serverUrl.isNotEmpty()) {
                val client = app.connect(saved.serverUrl)
                runCatching { client.api.providers() }.onSuccess { p -> _state.update { it.copy(providers = p) } }
                if (app.store.tokens != null) loadAccount(client)
            }
            _state.update { it.copy(loading = false) }
        }
        viewModelScope.launch {
            app.sessionExpired.collect { expired ->
                if (expired) {
                    _state.update { it.copy(username = null, error = "Session expired, please log in again") }
                    app.sessionExpired.value = false
                }
            }
        }
    }

    fun clearError() = _state.update { it.copy(error = null) }

    /** Check the server and load its login options. */
    fun connect(input: String) = work {
        val url = ServerUrl.normalize(input)
        val client = app.connect(url)
        client.api.health()
        val providers = client.api.providers()
        app.store.update { it.copy(serverUrl = url) }
        _state.update { it.copy(serverUrl = url, providers = providers) }
    }

    fun login(username: String, password: String) = work {
        val client = requireClient()
        signIn(client, client.api.login(LoginIn(username.trim(), password)))
    }

    suspend fun ssoIntent(provider: ProviderOut): Intent? = try {
        pendingProvider = provider
        sso.authorizationIntent(provider).first
    } catch (e: Exception) {
        _state.update { it.copy(error = e.userMessage()) }
        null
    }

    fun ssoResult(data: Intent?) = work {
        val provider = pendingProvider ?: error("No login in progress")
        val result = sso.complete(data)
        val client = requireClient()
        signIn(client, client.api.exchange(provider.name, OidcExchangeIn(result.idToken, result.nonce, result.accessToken)))
    }

    fun logout() = work {
        val client = app.client.value
        val refresh = app.store.tokens?.refresh
        if (client != null && refresh != null) runCatching { client.api.logout(RefreshIn(refresh)) }
        app.store.saveTokens(null)
        _state.update { it.copy(username = null) }
    }

    fun disconnect() = work {
        app.store.saveTokens(null)
        app.store.update { it.copy(serverUrl = "") }
        _state.update { SessionState(loading = false) }
    }

    fun updateSettings(transform: (Settings) -> Settings) {
        viewModelScope.launch { app.store.update(transform) }
    }

    private suspend fun signIn(client: ApiClient, tokens: TokenOut) {
        app.store.saveTokens(Tokens(tokens.accessToken, tokens.refreshToken))
        loadAccount(client)
    }

    private suspend fun loadAccount(client: ApiClient) {
        runCatching {
            val me = client.api.me()
            val games = client.api.games()
            _state.update { it.copy(username = me.username, games = games, error = null) }
        }.onFailure { e -> _state.update { it.copy(username = null, error = e.userMessage()) } }
    }

    private fun requireClient(): ApiClient = app.client.value ?: error("Connect to a server first")

    private fun work(block: suspend () -> Unit) {
        viewModelScope.launch {
            _state.update { it.copy(busy = true, error = null) }
            try {
                block()
            } catch (e: Exception) {
                _state.update { it.copy(error = e.userMessage()) }
            } finally {
                _state.update { it.copy(busy = false) }
            }
        }
    }

    override fun onCleared() = sso.dispose()
}
