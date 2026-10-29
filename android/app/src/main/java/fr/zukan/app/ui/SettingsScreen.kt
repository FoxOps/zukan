package fr.zukan.app.ui

import androidx.annotation.StringRes
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import fr.zukan.app.BuildConfig
import fr.zukan.app.R
import fr.zukan.app.data.OcrScript
import fr.zukan.app.data.Settings
import java.net.URI

/** Bottom sheets opened from the settings rows. */
private enum class SettingsSheet { SCRIPT, AFTER_ADD, DEFAULTS, SOURCES, MAIN_SOURCE, APP }

@Composable
fun SettingsScreen(
    session: SessionViewModel,
    state: SessionState,
    settings: Settings,
    updates: UpdateViewModel,
    updateState: UpdateState,
) {
    var sheet by rememberSaveable { mutableStateOf<SettingsSheet?>(null) }
    val languages = state.games.flatMap { it.languages }.distinct()
    val sources = state.games.flatMap { it.priceSources }.distinctBy { it.id }
    val shownSources = sources.filter { it.id in state.priceSources }
    val mainSource = sources.firstOrNull { it.id == state.priceSources.firstOrNull() }
    val defaultLanguage = settings.language?.let { languageName(it) } ?: stringResource(R.string.printing_language)

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 24.dp).padding(bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        ScreenHeader(stringResource(R.string.settings), stringResource(R.string.settings_subtitle))
        ProfileCard(state.username.orEmpty(), state.serverUrl, Modifier.padding(top = 12.dp)) { sheet = SettingsSheet.APP }

        SectionLabel(stringResource(R.string.group_scan), Modifier.padding(top = 16.dp))
        SettingsGroup {
            SettingsRow(R.drawable.ic_scan, stringResource(R.string.text_recognition), stringResource(settings.script.label), { sheet = SettingsSheet.SCRIPT }, divider = true)
            SettingsRow(
                R.drawable.ic_plus,
                stringResource(R.string.after_add),
                stringResource(if (settings.autoNext) R.string.after_add_next else R.string.after_add_stay),
                { sheet = SettingsSheet.AFTER_ADD },
                divider = true,
            )
            SettingsRow(R.drawable.ic_card, stringResource(R.string.default_values), "${settings.condition} · $defaultLanguage", { sheet = SettingsSheet.DEFAULTS })
        }

        if (sources.size > 1) {
            SectionLabel(stringResource(R.string.group_prices), Modifier.padding(top = 16.dp))
            SettingsGroup {
                SettingsRow(
                    R.drawable.ic_globe,
                    stringResource(R.string.price_sources),
                    shownSources.joinToString(", ") { it.name },
                    { sheet = SettingsSheet.SOURCES },
                    divider = state.priceSources.size > 1,
                )
                if (state.priceSources.size > 1) {
                    SettingsRow(
                        R.drawable.ic_spark,
                        stringResource(R.string.price_source),
                        mainSource?.let { "${it.name} · ${it.currency}" },
                        { sheet = SettingsSheet.MAIN_SOURCE },
                    )
                }
            }
        }

        SectionLabel(stringResource(R.string.group_app), Modifier.padding(top = 16.dp))
        SettingsGroup {
            SettingsRow(R.drawable.ic_settings, stringResource(R.string.app_and_connection), stringResource(R.string.app_and_connection_value), { sheet = SettingsSheet.APP })
        }
        Text(
            stringResource(R.string.app_footer, BuildConfig.VERSION_NAME),
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth().padding(top = 12.dp),
        )
    }

    val close = { sheet = null }
    when (sheet) {
        SettingsSheet.SCRIPT -> ZukanSheet(stringResource(R.string.text_recognition), close, subtitle = stringResource(R.string.text_recognition_help)) {
            Column {
                OcrScript.entries.forEach { script ->
                    ChoiceRow(stringResource(script.label), settings.script == script, { session.updateSettings { it.copy(script = script) } })
                }
            }
        }
        SettingsSheet.AFTER_ADD -> ZukanSheet(stringResource(R.string.after_add), close) {
            Column {
                ChoiceRow(stringResource(R.string.after_add_stay), !settings.autoNext, { session.updateSettings { it.copy(autoNext = false) } })
                ChoiceRow(stringResource(R.string.after_add_next), settings.autoNext, { session.updateSettings { it.copy(autoNext = true) } })
            }
        }
        SettingsSheet.DEFAULTS -> ZukanSheet(stringResource(R.string.default_values), close, subtitle = stringResource(R.string.default_values_help)) {
            SheetSection(stringResource(R.string.default_condition)) {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    CONDITIONS.forEach { c -> PillChip(c, settings.condition == c, { session.updateSettings { it.copy(condition = c) } }) }
                }
                Text("${settings.condition} · ${CONDITION_NAMES[settings.condition]}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            SheetSection(stringResource(R.string.default_language)) {
                Column {
                    ChoiceRow(stringResource(R.string.printing_language), settings.language == null, { session.updateSettings { it.copy(language = null) } })
                    languages.forEach { l ->
                        ChoiceRow(
                            "${languageFlag(l) ?: ""} ${languageName(l)}".trim(),
                            settings.language == l,
                            { session.updateSettings { it.copy(language = l) } },
                        )
                    }
                }
            }
        }
        SettingsSheet.SOURCES -> ZukanSheet(stringResource(R.string.price_sources), close, subtitle = stringResource(R.string.price_sources_help)) {
            Column {
                sources.forEach { s ->
                    val on = s.id in state.priceSources
                    ChoiceRow(
                        s.name,
                        on,
                        { session.togglePriceSource(s.id) },
                        // One source at least stays shown.
                        enabled = !(on && state.priceSources.size == 1),
                        role = Role.Checkbox,
                        subtitle = s.currency,
                    )
                }
            }
        }
        SettingsSheet.MAIN_SOURCE -> ZukanSheet(stringResource(R.string.price_source), close, subtitle = stringResource(R.string.price_source_help)) {
            Column {
                shownSources.forEach { s ->
                    ChoiceRow(s.name, state.priceSources.first() == s.id, { session.setMainPriceSource(s.id) }, subtitle = s.currency)
                }
            }
        }
        SettingsSheet.APP -> ZukanSheet(stringResource(R.string.app_and_connection), close) {
            AppSheet(session, state, updates, updateState)
        }
        null -> Unit
    }
}

/** Versions, updates, server and session. */
@Composable
private fun AppSheet(session: SessionViewModel, state: SessionState, updates: UpdateViewModel, updateState: UpdateState) {
    SheetSection(stringResource(R.string.versions)) {
        InfoLine(stringResource(R.string.app_name_label), BuildConfig.VERSION_NAME)
        InfoLine(stringResource(R.string.server_version), state.serverVersion ?: stringResource(R.string.unknown))
        if (updates.supported) {
            OutlinedButton(
                onClick = updates::checkNow,
                enabled = updateState !is UpdateState.Checking,
                modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
            ) {
                ZIcon(R.drawable.ic_refresh, null, Modifier.padding(end = 8.dp))
                Text(stringResource(R.string.update_check))
            }
            val status = when (updateState) {
                UpdateState.Checking -> stringResource(R.string.update_checking)
                UpdateState.UpToDate -> stringResource(R.string.update_up_to_date)
                is UpdateState.Failed -> if (updateState.release == null) updateState.message else null
                else -> null
            }
            status?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant) }
        } else {
            Text(stringResource(R.string.update_dev_build), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
    SheetSection(stringResource(R.string.connection)) {
        InfoLine(stringResource(R.string.user), state.username.orEmpty())
        InfoLine(stringResource(R.string.server_address), state.serverUrl)
        OutlinedButton(onClick = session::disconnect, modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp)) {
            ZIcon(R.drawable.ic_server, null, Modifier.padding(end = 8.dp))
            Text(stringResource(R.string.change_server))
        }
        OutlinedButton(onClick = session::logout, modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp)) {
            ZIcon(R.drawable.ic_logout, null, Modifier.padding(end = 8.dp))
            Text(stringResource(R.string.log_out))
        }
    }
}

@Composable
private fun InfoLine(label: String, value: String) {
    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
        Text(label, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.weight(1f))
        Text(value, style = MaterialTheme.typography.bodyMedium, textAlign = TextAlign.End)
    }
}

/** Initial, user name and server host; opens the app and connection sheet. */
@Composable
private fun ProfileCard(username: String, serverUrl: String, modifier: Modifier = Modifier, onClick: () -> Unit) {
    val host = runCatching { URI(serverUrl).host }.getOrNull() ?: serverUrl
    Surface(onClick = onClick, shape = CardShape, color = MaterialTheme.colorScheme.surfaceContainerLow, modifier = modifier.fillMaxWidth()) {
        Row(Modifier.padding(16.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.dp)) {
            Box(Modifier.size(48.dp).clip(CircleShape).background(MaterialTheme.colorScheme.outlineVariant), contentAlignment = Alignment.Center) {
                Text(username.take(1).uppercase(), style = MaterialTheme.typography.headlineSmall)
            }
            Column(Modifier.weight(1f)) {
                Text(username, style = MaterialTheme.typography.titleMedium, maxLines = 1)
                Text(host, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
            }
            ZIcon(R.drawable.ic_chevron, null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
        }
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
