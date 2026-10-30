package fr.zukan.app.data

import android.app.Activity
import android.app.LocaleManager
import android.content.Context
import android.content.res.Configuration
import android.content.res.Resources
import android.os.Build
import android.os.LocaleList
import androidx.core.content.edit
import java.util.Locale

/**
 * The app's interface language: the phone's, or one chosen in the settings (English,
 * French, German, Spanish, as the web interface). Android 13+ keeps the choice itself (also
 * shown in the system's per-app language settings); older versions read it from local
 * preferences when the screen is created.
 *
 * Signed in, the account's `language` is always used (shared with the web UI), never the
 * phone's.
 */
object AppLanguage {
    val SUPPORTED = listOf("en", "fr", "de", "es")
    private const val PREFS = "app_language"
    private const val TAG = "tag"

    private fun prefs(context: Context) = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    /** The language chosen in the app, null when it follows the phone. */
    fun chosen(context: Context): String? =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            context.getSystemService(LocaleManager::class.java).applicationLocales.takeIf { !it.isEmpty }?.get(0)?.language
        } else {
            prefs(context).getString(TAG, null)
        }

    /** The phone's language when the app has it, else English. */
    fun device(): String =
        Resources.getSystem().configuration.locales[0].language.takeIf { it in SUPPORTED } ?: "en"

    /** The language the interface is shown in. */
    fun effective(context: Context): String = chosen(context)?.takeIf { it in SUPPORTED } ?: device()

    /** Show the interface in [lang] (null: the phone's); the screen is created again. */
    fun choose(activity: Activity, lang: String?) {
        if (lang == chosen(activity)) return
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            activity.getSystemService(LocaleManager::class.java).applicationLocales =
                if (lang == null) LocaleList.getEmptyLocaleList() else LocaleList.forLanguageTags(lang)
        } else {
            prefs(activity).edit(commit = true) { putString(TAG, lang) }
            activity.recreate()
        }
    }

    /** Before Android 13: [base] with the chosen language, for activities and the app. */
    fun wrap(base: Context): Context {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) return base
        val lang = prefs(base).getString(TAG, null) ?: return base
        val config = Configuration(base.resources.configuration)
        config.setLocale(Locale.forLanguageTag(lang))
        return base.createConfigurationContext(config)
    }
}
