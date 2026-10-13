package fr.fudabako.app.ui

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
import androidx.compose.ui.unit.dp
import fr.fudabako.app.data.OcrScript
import fr.fudabako.app.data.Settings

@Composable
fun SettingsScreen(session: SessionViewModel, state: SessionState, settings: Settings) {
    val languages = state.games.flatMap { it.languages }.distinct()
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Text("Settings", style = MaterialTheme.typography.headlineSmall)
        Text("Signed in as ${state.username} on ${state.serverUrl}", style = MaterialTheme.typography.bodyMedium)

        Section("Text recognition") {
            Text("Choose the script printed on the cards you scan. Each also reads Latin text.", style = MaterialTheme.typography.bodySmall)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                OcrScript.entries.forEach { script ->
                    FilterChip(
                        selected = settings.script == script,
                        onClick = { session.updateSettings { it.copy(script = script) } },
                        label = { Text(script.name.lowercase().replaceFirstChar(Char::uppercase)) },
                    )
                }
            }
        }
        Section("Default condition") {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                CONDITIONS.forEach { c ->
                    FilterChip(selected = settings.condition == c, onClick = { session.updateSettings { it.copy(condition = c) } }, label = { Text(c) })
                }
            }
        }
        Section("Default language (when the card does not say)") {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                FilterChip(selected = settings.language == null, onClick = { session.updateSettings { it.copy(language = null) } }, label = { Text("Printing's") })
                languages.forEach { l ->
                    FilterChip(selected = settings.language == l, onClick = { session.updateSettings { it.copy(language = l) } }, label = { Text(languageName(l)) })
                }
            }
        }
        HorizontalDivider()
        OutlinedButton(onClick = session::logout) { Text("Log out") }
        OutlinedButton(onClick = session::disconnect) { Text("Change server") }
    }
}

@Composable
private fun Section(title: String, content: @Composable () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(title, style = MaterialTheme.typography.titleMedium)
        content()
    }
}
