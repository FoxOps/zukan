package fr.zukan.app.ui

import android.app.Application
import android.content.Intent
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import fr.zukan.app.ZukanApp
import fr.zukan.app.R
import fr.zukan.app.auth.SsoLogin
import fr.zukan.app.data.ApiClient
import fr.zukan.app.data.GameOut
import fr.zukan.app.data.LoginIn
import fr.zukan.app.data.MeOut
import fr.zukan.app.data.OidcExchangeIn
import fr.zukan.app.data.ProviderOut
import fr.zukan.app.data.ProvidersOut
import fr.zukan.app.data.RefreshIn
import fr.zukan.app.data.SettingsIn
import fr.zukan.app.data.ServerUrl
import fr.zukan.app.data.Settings
import fr.zukan.app.data.TokenOut
import fr.zukan.app.data.Tokens
import fr.zukan.app.data.userMessage
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.stateIn
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive

data class SessionState(
    val loading: Boolean = true,
    val busy: Boolean = false,
    val serverUrl: String = "",
    val providers: ProvidersOut? = null,
    val username: String? = null,
    val games: List<GameOut> = emptyList(),
    val serverVersion: String? = null,
    // Markets whose prices are shown, main one first (server setting, shared with the web UI).
    val priceSources: List<String> = listOf("cardmarket"),
    // Games shown in search and the scanner, null for all (server setting, shared with the web UI).
    val catalogGames: List<String>? = null,
    // The account's interface language (server setting, shared with the web UI).
    val serverLanguage: String? = null,
    val error: String? = null,
) {
    val loggedIn get() = username != null

    /** Games offered by search and the scanner. */
    val catalog: List<GameOut> get() = catalogGames?.let { shown -> games.filter { it.id in shown } } ?: games
}

class SessionViewModel(application: Application) : AndroidViewModel(application) {
    private val app = application as ZukanApp
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
                runCatching { client.api.health() }.onSuccess { h -> _state.update { it.copy(serverVersion = h.version) } }
                if (app.store.tokens != null) loadAccount(client)
            }
            _state.update { it.copy(loading = false) }
        }
        viewModelScope.launch {
            app.sessionExpired.collect { expired ->
                if (expired) {
                    _state.update { it.copy(username = null, error = app.getString(R.string.error_session_expired)) }
                    app.sessionExpired.value = false
                }
            }
        }
    }

    fun clearError() = _state.update { it.copy(error = null) }

    /** Check the server and load its login options. */
    fun connect(input: String) = work {
        // A proxy may redirect http to https: use the final address so later POSTs stay POSTs.
        val url = app.connect(ServerUrl.normalize(input)).redirectedBaseUrl()
        val client = app.connect(url)
        val health = client.api.health()
        val providers = client.api.providers()
        app.store.update { it.copy(serverUrl = url) }
        _state.update { it.copy(serverUrl = url, providers = providers, serverVersion = health.version) }
    }

    fun login(username: String, password: String) = work {
        val client = requireClient()
        signIn(client, client.api.login(LoginIn(username.trim(), password)))
    }

    suspend fun ssoIntent(provider: ProviderOut): Intent? = try {
        pendingProvider = provider
        sso.authorizationIntent(provider).first
    } catch (e: Exception) {
        _state.update { it.copy(error = e.userMessage(app)) }
        null
    }

    fun ssoResult(data: Intent?) = work {
        val provider = pendingProvider ?: error(app.getString(R.string.error_no_login))
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
            _state.update { it.copy(username = me.username, games = games, error = null).withMe(me) }
        }.onFailure { e -> _state.update { it.copy(username = null, error = e.userMessage(app)) } }
    }

    private fun SessionState.withMe(me: MeOut) =
        copy(priceSources = me.shownPriceSources, catalogGames = me.catalogGames, serverLanguage = me.language)

    /** Settings changed on the web meanwhile (back to the app). */
    fun refreshAccount() {
        val client = app.client.value ?: return
        if (!_state.value.loggedIn) return
        viewModelScope.launch {
            runCatching { client.api.me() }.onSuccess { me -> _state.update { it.withMe(me) } }
        }
    }

    /** Saves the interface language on the account (the web UI follows). */
    fun setServerLanguage(lang: String) = work {
        val me = requireClient().api.updateMe(SettingsIn(language = lang))
        _state.update { it.withMe(me) }
    }

    /** Games shown in search and the scanner; null: every game. */
    fun setCatalogGames(games: List<String>?) = work {
        val value = games?.let { list -> JsonArray(list.map(::JsonPrimitive)) } ?: JsonNull
        val me = requireClient().api.updateMeJson(JsonObject(mapOf("catalog_games" to value)))
        _state.update { it.withMe(me) }
    }

    /** Makes [source] the main price source. */
    fun setMainPriceSource(source: String) = work {
        val me = requireClient().api.updateMe(SettingsIn(priceSource = source))
        _state.update { it.withMe(me) }
    }

    /** Shows or hides the prices of [source] (one source at least stays shown). */
    fun togglePriceSource(source: String) = work {
        val current = _state.value.priceSources
        val next = if (source in current) current - source else current + source
        if (next.isEmpty()) return@work
        val me = requireClient().api.updateMe(SettingsIn(priceSources = next))
        _state.update { it.withMe(me) }
    }

    private fun requireClient(): ApiClient = app.client.value ?: error(app.getString(R.string.error_not_connected))

    private fun work(block: suspend () -> Unit) {
        viewModelScope.launch {
            _state.update { it.copy(busy = true, error = null) }
            try {
                block()
            } catch (e: Exception) {
                _state.update { it.copy(error = e.userMessage(app)) }
            } finally {
                _state.update { it.copy(busy = false) }
            }
        }
    }

    override fun onCleared() = sso.dispose()
}
