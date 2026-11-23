package fr.zukan.app.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.MutablePreferences
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.longPreferencesKey
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
    // Experimental: guess holo / reverse holo from how light moves on the card.
    val glareFinish: Boolean = false,
    // Collection shown as a grid of pictures instead of a list.
    val collectionGrid: Boolean = false,
)

/** Settings in the stored preferences. */
object SettingsPrefs {
    private val server = stringPreferencesKey("server_url")
    private val game = stringPreferencesKey("game")
    private val condition = stringPreferencesKey("condition")
    private val language = stringPreferencesKey("language")
    // New key in 0.3: everyone starts on AUTO (the old "script" was LATIN for most).
    private val script = stringPreferencesKey("ocr_script")
    private val autoNext = booleanPreferencesKey("auto_next")
    private val glareFinish = booleanPreferencesKey("glare_finish")
    private val collectionGrid = booleanPreferencesKey("collection_grid")

    fun read(p: Preferences) = Settings(
        serverUrl = p[server] ?: "",
        game = p[game],
        condition = p[condition] ?: "NM",
        language = p[language],
        script = p[script]?.let { runCatching { OcrScript.valueOf(it) }.getOrNull() } ?: OcrScript.AUTO,
        autoNext = p[autoNext] ?: false,
        glareFinish = p[glareFinish] ?: false,
        collectionGrid = p[collectionGrid] ?: false,
    )

    /** Within one transaction: [transform] sees what is stored now, so two updates made at
     * the same time each keep the other's change. */
    fun update(p: MutablePreferences, transform: (Settings) -> Settings) {
        val s = transform(read(p))
        p[server] = s.serverUrl
        if (s.game == null) p.remove(game) else p[game] = s.game
        p[condition] = s.condition
        if (s.language == null) p.remove(language) else p[language] = s.language
        p[script] = s.script.name
        p[autoNext] = s.autoNext
        p[glareFinish] = s.glareFinish
        p[collectionGrid] = s.collectionGrid
    }
}

/** Server URL, tokens (encrypted) and scan preferences, stored with DataStore. */
class SessionStore(private val context: Context, private val cipher: TokenCipher = KeystoreCipher) : TokenSessions() {
    private object Keys {
        // Before 0.20: tokens in plain text, encrypted at the next start.
        val access = stringPreferencesKey("access_token")
        val refresh = stringPreferencesKey("refresh_token")
        val accessSealed = stringPreferencesKey("access_token_enc")
        val refreshSealed = stringPreferencesKey("refresh_token_enc")
        val lastUpdateCheck = longPreferencesKey("last_update_check")
        val skippedVersion = stringPreferencesKey("skipped_version")
    }

    val settings: Flow<Settings> = context.dataStore.data.map(SettingsPrefs::read)

    suspend fun load(): Settings {
        val prefs = context.dataStore.data.first()
        val access = prefs[Keys.accessSealed]?.let(cipher::decrypt)
        val refresh = prefs[Keys.refreshSealed]?.let(cipher::decrypt)
        val plainAccess = prefs[Keys.access]
        val plainRefresh = prefs[Keys.refresh]
        val tokens = when {
            access != null && refresh != null -> Tokens(access, refresh)
            plainAccess != null && plainRefresh != null -> Tokens(plainAccess, plainRefresh).also { persist(it) }
            // Undecryptable (Keystore key lost): logging in again is all it takes.
            else -> null
        }
        restore(tokens)
        return SettingsPrefs.read(prefs)
    }

    override suspend fun persist(tokens: Tokens?) {
        val access = tokens?.let { cipher.encrypt(it.access) }
        val refresh = tokens?.let { cipher.encrypt(it.refresh) }
        context.dataStore.edit { p ->
            listOf(Keys.access, Keys.refresh, Keys.accessSealed, Keys.refreshSealed).forEach { p.remove(it) }
            if (tokens == null) return@edit
            if (access != null && refresh != null) {
                p[Keys.accessSealed] = access
                p[Keys.refreshSealed] = refresh
            } else {
                // No working Keystore on this phone: kept as before 0.20 rather than lost.
                p[Keys.access] = tokens.access
                p[Keys.refresh] = tokens.refresh
            }
        }
    }

    /** Last automatic update check (epoch ms, 0: never) and the version the user skipped. */
    suspend fun updateCheck(): Pair<Long, String?> {
        val prefs = context.dataStore.data.first()
        return (prefs[Keys.lastUpdateCheck] ?: 0L) to prefs[Keys.skippedVersion]
    }

    suspend fun markUpdateChecked(now: Long) {
        context.dataStore.edit { it[Keys.lastUpdateCheck] = now }
    }

    suspend fun skipVersion(version: String) {
        context.dataStore.edit { it[Keys.skippedVersion] = version }
    }

    suspend fun update(transform: (Settings) -> Settings) {
        context.dataStore.edit { SettingsPrefs.update(it, transform) }
    }
}
