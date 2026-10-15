package fr.zukan.app.ui

import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import fr.zukan.app.BuildConfig
import fr.zukan.app.R
import fr.zukan.app.data.OcrScript
import fr.zukan.app.data.Settings

@Composable
fun SettingsScreen(session: SessionViewModel, state: SessionState, settings: Settings) {
    val languages = state.games.flatMap { it.languages }.distinct()
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text(stringResource(R.string.settings), style = MaterialTheme.typography.headlineSmall)
        Text(stringResource(R.string.signed_in_as, state.username.orEmpty(), state.serverUrl), style = MaterialTheme.typography.bodyMedium)

        Section(stringResource(R.string.text_recognition)) {
            Text(stringResource(R.string.text_recognition_help), style = MaterialTheme.typography.bodySmall)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                OcrScript.entries.forEach { script ->
                    FilterChip(
                        selected = settings.script == script,
                        onClick = { session.updateSettings { it.copy(script = script) } },
                        label = { Text(stringResource(script.label)) },
                    )
                }
            }
        }
        val sources = state.games.flatMap { it.priceSources }.distinctBy { it.id }
        if (sources.size > 1) {
            Section(stringResource(R.string.price_sources)) {
                Text(stringResource(R.string.price_sources_help), style = MaterialTheme.typography.bodySmall)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    sources.forEach { s ->
                        val on = s.id in state.priceSources
                        FilterChip(
                            selected = on,
                            // One source at least stays shown.
                            enabled = !(on && state.priceSources.size == 1),
                            onClick = { session.togglePriceSource(s.id) },
                            label = { Text("${s.name} (${s.currency})") },
                        )
                    }
                }
                if (state.priceSources.size > 1) {
                    Text(stringResource(R.string.price_source), style = MaterialTheme.typography.labelLarge)
                    Text(stringResource(R.string.price_source_help), style = MaterialTheme.typography.bodySmall)
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        sources.filter { it.id in state.priceSources }.forEach { s ->
                            FilterChip(
                                selected = state.priceSources.first() == s.id,
                                onClick = { session.setMainPriceSource(s.id) },
                                label = { Text(s.name) },
                            )
                        }
                    }
                }
            }
        }
        Section(stringResource(R.string.after_add)) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                FilterChip(selected = !settings.autoNext, onClick = { session.updateSettings { it.copy(autoNext = false) } }, label = { Text(stringResource(R.string.after_add_stay)) })
                FilterChip(selected = settings.autoNext, onClick = { session.updateSettings { it.copy(autoNext = true) } }, label = { Text(stringResource(R.string.after_add_next)) })
            }
        }
        Section(stringResource(R.string.default_condition)) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                CONDITIONS.forEach { c ->
                    ConditionChoice(c, selected = settings.condition == c) { session.updateSettings { it.copy(condition = c) } }
                }
            }
        }
        Section(stringResource(R.string.default_language)) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                FilterChip(selected = settings.language == null, onClick = { session.updateSettings { it.copy(language = null) } }, label = { Text(stringResource(R.string.printing_language)) })
                languages.forEach { l ->
                    FilterChip(
                        selected = settings.language == l,
                        onClick = { session.updateSettings { it.copy(language = l) } },
                        label = { Text("${languageFlag(l) ?: ""} ${languageName(l)}".trim()) },
                    )
                }
            }
        }
        HorizontalDivider()
        OutlinedButton(onClick = session::logout) { Text(stringResource(R.string.log_out)) }
        OutlinedButton(onClick = session::disconnect) { Text(stringResource(R.string.change_server)) }
        Text(
            stringResource(R.string.app_version, BuildConfig.VERSION_NAME, state.serverVersion ?: "?"),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

private val OcrScript.label
    @StringRes get() = when (this) {
        OcrScript.AUTO -> R.string.script_auto
        OcrScript.LATIN -> R.string.script_latin
        OcrScript.JAPANESE -> R.string.script_japanese
        OcrScript.CHINESE -> R.string.script_chinese
        OcrScript.KOREAN -> R.string.script_korean
    }

@Composable
private fun Section(title: String, content: @Composable () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(title, style = MaterialTheme.typography.titleMedium)
        content()
    }
}
