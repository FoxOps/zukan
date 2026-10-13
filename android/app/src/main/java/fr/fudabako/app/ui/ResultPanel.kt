package fr.fudabako.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ChevronLeft
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.Remove
import androidx.compose.material3.Button
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import coil3.ImageLoader
import coil3.compose.AsyncImage
import fr.fudabako.app.R
import fr.fudabako.app.data.GameOut
import fr.fudabako.app.data.Settings
import java.util.Locale

val CONDITIONS = listOf("MT", "NM", "EX", "GD", "LP", "PL", "PO")

fun languageName(code: String): String =
    Locale.forLanguageTag(code).getDisplayName(Locale.getDefault()).ifEmpty { code }

/** The identified card: printings to swipe through, variant to pick, add or remove. */
@Composable
fun ResultPanel(
    state: ScanState,
    games: List<GameOut>,
    settings: Settings,
    imageUrl: (String?) -> String?,
    imageLoader: ImageLoader,
    onCandidate: (Int) -> Unit,
    onPrinting: (Int) -> Unit,
    onAdjust: (finish: String, condition: String, language: String, delta: Int) -> Unit,
    onClose: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val result = state.result ?: return
    val candidate = state.current ?: return
    val printing = candidate.printings.getOrNull(state.printing) ?: return
    val game = games.firstOrNull { it.id == candidate.card.gameId }
    val finishes = printing.finishes.ifEmpty { game?.finishes?.map { it.code } ?: emptyList() }
    val languages = game?.languages ?: printing.languages
    // Defaults: detected language, else preferred, else the printing's first language.
    val defaultLanguage = listOfNotNull(result.detected.lang, settings.language, printing.languages.firstOrNull())
        .firstOrNull { it in languages } ?: "en"

    var finish by remember(printing.id) { mutableStateOf(finishes.firstOrNull() ?: "") }
    var condition by remember(printing.id) { mutableStateOf(settings.condition) }
    var language by remember(printing.id) { mutableStateOf(defaultLanguage) }
    var quantity by remember(printing.id) { mutableIntStateOf(1) }
    val finishName = { code: String -> game?.finishes?.firstOrNull { it.code == code }?.name ?: code }

    Column(modifier.verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        if (result.candidates.size > 1) {
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                result.candidates.forEachIndexed { index, c ->
                    FilterChip(selected = index == state.candidate, onClick = { onCandidate(index) }, label = { Text(c.card.name, maxLines = 1) })
                }
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Box(Modifier.width(120.dp).aspectRatio(63f / 88f).clip(RoundedCornerShape(6.dp))) {
                if (printing.image == null) {
                    Box(Modifier.matchParentSize().background(MaterialTheme.colorScheme.surfaceVariant), contentAlignment = Alignment.Center) {
                        Text(stringResource(R.string.no_picture), style = MaterialTheme.typography.bodySmall)
                    }
                } else {
                    AsyncImage(model = imageUrl(printing.image), contentDescription = candidate.card.name, imageLoader = imageLoader)
                }
            }
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(candidate.card.name, style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
                printing.names.filterValues { it != candidate.card.name }.entries.firstOrNull { it.key == language }?.let {
                    Text(it.value, style = MaterialTheme.typography.bodyMedium)
                }
                Text("${printing.set.name} · ${printing.set.code} ${printing.collectorNumber ?: ""}", style = MaterialTheme.typography.bodySmall)
                printing.rarity?.let { Text(it.replaceFirstChar(Char::uppercase), style = MaterialTheme.typography.bodySmall) }
                printing.prices.forEach { Text(stringResource(R.string.price, finishName(it.finish), it.trend), style = MaterialTheme.typography.bodyMedium) }
                printing.owned.forEach {
                    Text(
                        stringResource(R.string.owned, it.quantity, finishName(it.finish), it.condition, it.language),
                        color = MaterialTheme.colorScheme.primary,
                        style = MaterialTheme.typography.bodySmall,
                    )
                }
            }
        }
        if (candidate.printings.size > 1) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = { onPrinting(state.printing - 1) }, enabled = state.printing > 0) { Icon(Icons.Default.ChevronLeft, stringResource(R.string.previous_printing)) }
                Text(stringResource(R.string.printing_position, state.printing + 1, candidate.printings.size), Modifier.weight(1f))
                IconButton(onClick = { onPrinting(state.printing + 1) }, enabled = state.printing < candidate.printings.size - 1) {
                    Icon(Icons.Default.ChevronRight, stringResource(R.string.next_printing))
                }
            }
        }
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            finishes.forEach { f -> FilterChip(selected = f == finish, onClick = { finish = f }, label = { Text(finishName(f)) }) }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            Picker(stringResource(R.string.condition), condition, CONDITIONS, { it }) { condition = it }
            Picker(stringResource(R.string.language), language, languages, ::languageName) { language = it }
        }
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            IconButton(onClick = { if (quantity > 1) quantity-- }) { Icon(Icons.Default.Remove, stringResource(R.string.less)) }
            Text("$quantity", style = MaterialTheme.typography.titleLarge)
            IconButton(onClick = { if (quantity < 99) quantity++ }) { Icon(Icons.Default.Add, stringResource(R.string.more)) }
            Spacer(Modifier.weight(1f))
            OutlinedButton(onClick = { onAdjust(finish, condition, language, -quantity) }, enabled = !state.busy) { Text(stringResource(R.string.remove)) }
            Button(onClick = { onAdjust(finish, condition, language, quantity) }, enabled = !state.busy && finish.isNotEmpty()) { Text(stringResource(R.string.add)) }
        }
        TextButton(onClick = onClose, modifier = Modifier.align(Alignment.End)) { Text(stringResource(R.string.scan_next)) }
    }
}

@Composable
private fun Picker(label: String, value: String, options: List<String>, display: (String) -> String, onPick: (String) -> Unit) {
    var open by remember { mutableStateOf(false) }
    Box {
        OutlinedButton(onClick = { open = true }) { Text(stringResource(R.string.picker_value, label, display(value)), maxLines = 1) }
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            options.forEach { option ->
                DropdownMenuItem(text = { Text(display(option)) }, onClick = {
                    onPick(option)
                    open = false
                })
            }
        }
    }
}
