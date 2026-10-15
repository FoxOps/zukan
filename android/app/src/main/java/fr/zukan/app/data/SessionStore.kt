package fr.zukan.app.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map

private val Context.dataStore: DataStore<Preferences> by preferencesDataStore("zukan")

/** Text recognition model to run: Latin also reads EU languages; the others add a script.
 * AUTO reads with Latin, then tries every script on the frame sent to the server. */
enum class OcrScript { AUTO, LATIN, JAPANESE, CHINESE, KOREAN }

data class Settings(
    val serverUrl: String = "",
    val game: String? = null,
    val condition: String = "NM",
    val language: String? = null,
    val script: OcrScript = OcrScript.AUTO,
    // After adding copies: go back to the camera for the next card.
    val autoNext: Boolean = false,
)

data class Tokens(val access: String, val refresh: String)

/** Where the API client reads and stores tokens. */
interface TokenStore {
    val tokens: Tokens?
    suspend fun saveTokens(value: Tokens?)
}

/** Server URL, tokens and scan preferences, stored with DataStore. */
class SessionStore(private val context: Context) : TokenStore {
    private object Keys {
        val server = stringPreferencesKey("server_url")
        val access = stringPreferencesKey("access_token")
        val refresh = stringPreferencesKey("refresh_token")
        val game = stringPreferencesKey("game")
        val condition = stringPreferencesKey("condition")
        val language = stringPreferencesKey("language")
        // New key in 0.3: everyone starts on AUTO (the old "script" was LATIN for most).
        val script = stringPreferencesKey("ocr_script")
        val autoNext = booleanPreferencesKey("auto_next")
    }

    // Read by OkHttp threads on every request; kept in memory to avoid blocking reads.
    @Volatile
    override var tokens: Tokens? = null
        private set

    val settings: Flow<Settings> = context.dataStore.data.map { p ->
        Settings(
            serverUrl = p[Keys.server] ?: "",
            game = p[Keys.game],
            condition = p[Keys.condition] ?: "NM",
            language = p[Keys.language],
            script = p[Keys.script]?.let { runCatching { OcrScript.valueOf(it) }.getOrNull() } ?: OcrScript.AUTO,
            autoNext = p[Keys.autoNext] ?: false,
        )
    }

    suspend fun load(): Settings {
        val prefs = context.dataStore.data.first()
        val access = prefs[Keys.access]
        val refresh = prefs[Keys.refresh]
        tokens = if (access != null && refresh != null) Tokens(access, refresh) else null
        return settings.first()
    }

    override suspend fun saveTokens(value: Tokens?) {
        tokens = value
        context.dataStore.edit { p ->
            if (value == null) {
                p.remove(Keys.access)
                p.remove(Keys.refresh)
            } else {
                p[Keys.access] = value.access
                p[Keys.refresh] = value.refresh
            }
        }
    }

    suspend fun update(transform: (Settings) -> Settings) {
        val current = settings.first()
        val next = transform(current)
        context.dataStore.edit { p ->
            p[Keys.server] = next.serverUrl
            if (next.game == null) p.remove(Keys.game) else p[Keys.game] = next.game
            p[Keys.condition] = next.condition
            if (next.language == null) p.remove(Keys.language) else p[Keys.language] = next.language
            p[Keys.script] = next.script.name
            p[Keys.autoNext] = next.autoNext
        }
    }
}
