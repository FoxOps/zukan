package fr.zukan.app

import androidx.datastore.preferences.core.mutablePreferencesOf
import fr.zukan.app.data.OcrScript
import fr.zukan.app.data.SettingsPrefs
import org.junit.Assert.assertEquals
import org.junit.Test

class SettingsPrefsTest {
    @Test
    fun eachUpdateKeepsTheOthersChanges() {
        val prefs = mutablePreferencesOf()
        // Two updates run one after the other inside DataStore's transactions: the second
        // sees the first one's change instead of an old snapshot.
        SettingsPrefs.update(prefs) { it.copy(script = OcrScript.JAPANESE) }
        SettingsPrefs.update(prefs) { it.copy(condition = "PL") }

        val stored = SettingsPrefs.read(prefs)
        assertEquals(OcrScript.JAPANESE, stored.script)
        assertEquals("PL", stored.condition)
    }

    @Test
    fun nullsRemoveTheirKey() {
        val prefs = mutablePreferencesOf()
        SettingsPrefs.update(prefs) { it.copy(game = "mtg", language = "fr") }
        SettingsPrefs.update(prefs) { it.copy(game = null) }
        val stored = SettingsPrefs.read(prefs)
        assertEquals(null, stored.game)
        assertEquals("fr", stored.language)
    }
}
