package fr.zukan.app.ui

import android.app.Application
import android.content.Intent
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.SavedStateHandle
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
import fr.zukan.app.data.runCatchingCancellable
import fr.zukan.app.data.userMessage
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.SharingStarted
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.first
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
    // False: never picked, the app follows the phone's language.
    val languageChosen: Boolean = true,
    // Optional modules the user has on (server setting).
    val modules: List<String> = emptyList(),
    val error: String? = null,
) {
    val loggedIn get() = username != null

    /** Games offered by search and the scanner. */
    val catalog: List<GameOut> get() = catalogGames?.let { shown -> games.filter { it.id in shown } } ?: games
}

class SessionViewModel(application: Application, private val saved: SavedStateHandle) : AndroidViewModel(application) {
    private val app = application as ZukanApp
    private val sso = SsoLogin(application)
    private val _state = MutableStateFlow(SessionState())
    val state: StateFlow<SessionState> = _state.asStateFlow()
    val settings: StateFlow<Settings> = app.store.settings.stateIn(viewModelScope, SharingStarted.Eagerly, Settings())

    init {
        viewModelScope.launch {
            val stored = app.store.load()
            _state.update { it.copy(serverUrl = stored.serverUrl) }
            if (stored.serverUrl.isNotEmpty()) {
                val client = app.connect(stored.serverUrl)
                // Independent: asked together, so a slow server costs one wait, not two.
                coroutineScope {
                    val providers = async { runCatchingCancellable { client.api.providers() } }
                    val health = async { runCatchingCancellable { client.api.health() } }
                    providers.await().onSuccess { p -> _state.update { it.copy(providers = p) } }
                    health.await().onSuccess { h -> _state.update { it.copy(serverVersion = h.version) } }
                }
                if (app.store.tokensFor(client.generation) != null) loadAccount(client)
            }
            _state.update { it.copy(loading = false) }
        }
        viewModelScope.launch {
            app.sessionExpired.collect { expired ->
                if (expired) {
                    app.sessionExpired.value = false
                    // A new session: what the scanner and lists showed for the account goes.
                    app.endSession()
                    _state.update { it.copy(username = null, error = app.getString(R.string.error_session_expired)) }
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

    /** The browser login of [provider]; the provider and server are kept with the activity's
     * saved state, so the answer still completes after Android stopped the app meanwhile. */
    suspend fun ssoIntent(provider: ProviderOut): Intent? {
        if (_state.value.busy) return null
        _state.update { it.copy(busy = true, error = null) }
        return try {
            sso.authorizationIntent(provider).first.also {
                saved[SSO_PROVIDER] = provider.name
                saved[SSO_SERVER] = _state.value.serverUrl
            }
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            _state.update { it.copy(error = e.userMessage(app)) }
            null
        } finally {
            _state.update { it.copy(busy = false) }
        }
    }

    fun ssoResult(data: Intent?) = work {
        val name = saved.get<String>(SSO_PROVIDER)
        val server = saved.get<String>(SSO_SERVER)
        saved.remove<String>(SSO_PROVIDER)
        saved.remove<String>(SSO_SERVER)
        // After the app was stopped: its server and login options load again first.
        val loaded = _state.first { !it.loading }
        val provider = loaded.providers?.providers?.firstOrNull { it.name == name }
        // Started for another server (changed meanwhile): not for this one.
        if (provider == null || server != loaded.serverUrl) error(app.getString(R.string.error_no_login))
        val result = sso.complete(data)
        val client = requireClient()
        signIn(client, client.api.exchange(provider.name, OidcExchangeIn(result.idToken, result.nonce, result.accessToken)))
    }

    fun logout() = work {
        val refresh = app.store.tokens?.refresh
        // The session ends here first: nothing still running can bring it back.
        app.endSession()
        _state.update { it.copy(username = null) }
        if (refresh != null) runCatchingCancellable { app.client.value?.api?.logout(RefreshIn(refresh)) }
    }

    fun disconnect() = work {
        app.endSession(baseUrl = null)
        app.store.update { it.copy(serverUrl = "") }
        _state.update { SessionState(loading = false) }
    }

    fun updateSettings(transform: (Settings) -> Settings) {
        viewModelScope.launch { app.store.update(transform) }
    }

    private suspend fun signIn(client: ApiClient, tokens: TokenOut) {
        // Server changed or session ended while logging in: this login is for nothing shown.
        if (app.client.value !== client) return
        // Each login is a session of its own (nothing of the previous account stays shown).
        app.endSession()
        val fresh = app.client.value ?: return
        if (!app.store.replaceIf(fresh.generation, null, Tokens(tokens.accessToken, tokens.refreshToken))) return
        loadAccount(fresh)
    }

    private suspend fun loadAccount(client: ApiClient) {
        runCatchingCancellable {
            val me = client.api.me()
            val games = client.api.games()
            if (app.client.value !== client) return@runCatchingCancellable
            _state.update { it.copy(username = me.username, games = games, error = null).withMe(me) }
        }.onFailure { e -> _state.update { it.copy(username = null, error = e.userMessage(app)) } }
    }

    private fun SessionState.withMe(me: MeOut) =
        copy(priceSources = me.shownPriceSources, catalogGames = me.catalogGames, serverLanguage = me.language, languageChosen = me.languageChosen, modules = me.modules)

    /** Settings changed on the web meanwhile (back to the app). */
    fun refreshAccount() {
        val client = app.client.value ?: return
        if (!_state.value.loggedIn) return
        viewModelScope.launch {
            runCatchingCancellable { client.api.me() }.onSuccess { me -> if (app.client.value === client) _state.update { it.withMe(me) } }
        }
    }

    /** Saves the interface language on the account (the web UI follows). */
    fun setServerLanguage(lang: String) = work {
        val me = requireClient().api.updateMe(SettingsIn(language = lang))
        _state.update { it.withMe(me) }
    }

    /** Follow the phone's language again: the server takes it from Accept-Language (else
     * English) for card names and pictures; the web keeps following its browser's. */
    fun followPhoneLanguage() = work {
        val me = requireClient().api.updateMe(SettingsIn(languageChosen = false))
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
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                _state.update { it.copy(error = e.userMessage(app)) }
            } finally {
                _state.update { it.copy(busy = false) }
            }
        }
    }

    override fun onCleared() = sso.dispose()

    private companion object {
        const val SSO_PROVIDER = "sso_provider"
        const val SSO_SERVER = "sso_server"
    }
}
