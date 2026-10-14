package fr.fudabako.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.OpenInNew
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.Remove
import androidx.compose.material3.Button
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
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import coil3.ImageLoader
import coil3.compose.AsyncImage
import fr.fudabako.app.R
import fr.fudabako.app.data.GameOut
import fr.fudabako.app.data.PrintingOut
import fr.fudabako.app.data.Settings
import java.util.Locale

fun languageName(code: String): String =
    Locale.forLanguageTag(code).getDisplayName(Locale.getDefault()).ifEmpty { code }

/** Only web pages are opened from links the server sends (no intents, files...). */
fun isWebLink(url: String): Boolean = url.startsWith("https://") || url.startsWith("http://")

/** Prices of the user's price source (the server lists it first). */
fun mainPrices(printing: PrintingOut) = printing.prices.filter { it.source == printing.prices.firstOrNull()?.source }

/**
 * The identified card: what was read, the card and its price, the copies owned, then
 * the printing, variant and quantity to add or remove.
 */
@Composable
fun ResultPanel(
    state: ScanState,
    games: List<GameOut>,
    settings: Settings,
    imageUrl: (String?) -> String?,
    imageLoader: ImageLoader,
    onCandidate: (Int) -> Unit,
    onPrinting: (PrintingOut) -> Unit,
    searchPrintings: suspend (cardId: Int, query: String) -> List<PrintingOut>,
    onAdjust: (finish: String, condition: String, language: String, delta: Int) -> Unit,
    onClose: () -> Unit,
    modifier: Modifier = Modifier,
) {
    val result = state.result ?: return
    val candidate = state.current ?: return
    val printing = candidate.printings.getOrNull(state.printing) ?: return
    val game = games.firstOrNull { it.id == candidate.card.gameId }
    val finishes = printing.finishes.ifEmpty { game?.finishes?.map { it.code } ?: emptyList() }
    // Languages the printing exists in (all of the game's when the catalog does not say).
    val languages = printing.languages.ifEmpty { game?.languages ?: listOf("en") }
    // Defaults: detected language, else preferred, else the printing's first language.
    val defaultLanguage = listOfNotNull(result.detected.lang, settings.language).firstOrNull { it in languages } ?: languages.first()

    var finish by remember(printing.id) { mutableStateOf(finishes.firstOrNull() ?: "") }
    var condition by remember(printing.id) { mutableStateOf(settings.condition) }
    var language by remember(printing.id) { mutableStateOf(defaultLanguage) }
    var quantity by remember(printing.id) { mutableIntStateOf(1) }
    var pickPrinting by remember { mutableStateOf(false) }
    val finishName = { code: String -> game?.finishes?.firstOrNull { it.code == code }?.name ?: code }
    val uriHandler = LocalUriHandler.current

    Column(modifier.verticalScroll(rememberScrollState()).padding(horizontal = 16.dp).padding(bottom = 16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        DetectedRow(result.detected.name, result.detected.lang, result.detected.setCode, result.detected.collectorNumber)
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
                printing.names[language]?.takeIf { it != candidate.card.name }?.let {
                    Text(it, style = MaterialTheme.typography.bodyMedium)
                }
                printing.rarity?.let { Text(it.replaceFirstChar(Char::uppercase), style = MaterialTheme.typography.bodySmall) }
                val sourceName = { id: String -> game?.priceSources?.firstOrNull { it.id == id }?.name ?: id }
                printing.prices.groupBy { it.source }.entries.forEachIndexed { index, (source, prices) ->
                    // The user's market in full, the others on one line each.
                    if (index == 0) {
                        if (printing.prices.map { it.source }.distinct().size > 1) {
                            Text(sourceName(source), style = MaterialTheme.typography.labelSmall)
                        }
                        prices.forEach { price ->
                            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                                FinishBadge(game, price.finish)
                                Text(money(price.trend, price.currency), style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.SemiBold)
                                price.low?.let { Text(stringResource(R.string.price_from, money(it, price.currency)), style = MaterialTheme.typography.bodySmall) }
                            }
                        }
                    } else {
                        Text(
                            "${sourceName(source)}: " + prices.joinToString(" · ") { money(it.trend, it.currency) },
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                    }
                }
                printing.links.filter { isWebLink(it.url) }.forEach { link ->
                    TextButton(onClick = { uriHandler.openUri(link.url) }, contentPadding = androidx.compose.foundation.layout.PaddingValues(0.dp)) {
                        Text(link.name)
                        Icon(Icons.AutoMirrored.Filled.OpenInNew, null, Modifier.padding(start = 4.dp).size(16.dp))
                    }
                }
            }
        }
        OwnedSummary(game, printing)

        // Printing: tap to choose among all printings of the card.
        Row(
            Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp))
                .border(1.dp, MaterialTheme.colorScheme.outlineVariant, RoundedCornerShape(8.dp))
                .clickable(enabled = candidate.printings.size > 1) { pickPrinting = true }
                .padding(horizontal = 12.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Column(Modifier.weight(1f)) {
                Text(printing.set.name, style = MaterialTheme.typography.bodyLarge, maxLines = 1)
                Text(
                    listOfNotNull(printing.set.code, printing.collectorNumber).joinToString(" · "),
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            printing.set.lang?.let { LangFlag(it) }
            if (candidate.printingCount > 1) {
                Text(stringResource(R.string.printing_position, state.printing + 1, maxOf(candidate.printingCount, candidate.printings.size)), style = MaterialTheme.typography.bodySmall)
                Icon(Icons.Default.ArrowDropDown, stringResource(R.string.choose_printing))
            }
        }

        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            finishes.forEach { f -> FilterChip(selected = f == finish, onClick = { finish = f }, label = { Text(finishName(f)) }) }
        }
        Text("${stringResource(R.string.condition)}: ${condition}", style = MaterialTheme.typography.labelLarge)
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            CONDITIONS.forEach { c -> ConditionChoice(c, selected = c == condition) { condition = c } }
        }
        if (languages.size > 1) {
            Text("${stringResource(R.string.language)}: ${languageName(language)}", style = MaterialTheme.typography.labelLarge)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                languages.forEach { l -> FilterChip(selected = l == language, onClick = { language = l }, label = { LangFlag(l, size = 20) }) }
            }
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

    if (pickPrinting) {
        PrintingPicker(
            printings = candidate.printings,
            total = candidate.printingCount,
            selectedId = printing.id,
            search = { q -> searchPrintings(candidate.card.id, q) },
            imageUrl = imageUrl,
            imageLoader = imageLoader,
            onPick = { onPrinting(it); pickPrinting = false },
            onDismiss = { pickPrinting = false },
        )
    }
}

/** What the camera read: name always, language and set when found. */
@Composable
private fun DetectedRow(name: String?, lang: String?, setCode: String?, number: String?) {
    if (name == null && lang == null && setCode == null) return
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(stringResource(R.string.detected), style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        name?.let { Text(it, style = MaterialTheme.typography.labelMedium, maxLines = 1, modifier = Modifier.weight(1f, fill = false)) }
        lang?.let { LangFlag(it, size = 14) }
        listOfNotNull(setCode, number).takeIf { it.isNotEmpty() }?.let {
            Text(it.joinToString(" "), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

@Composable
private fun OwnedSummary(game: GameOut?, printing: PrintingOut) {
    if (printing.owned.isEmpty()) {
        Text(stringResource(R.string.not_owned), style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
        return
    }
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        printing.owned.forEach {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(stringResource(R.string.owned_quantity, it.quantity), color = MaterialTheme.colorScheme.primary, fontWeight = FontWeight.SemiBold)
                FinishBadge(game, it.finish)
                ConditionBadge(it.condition)
                LangFlag(it.language)
            }
        }
    }
}

@Composable
fun ConditionChoice(code: String, selected: Boolean, onClick: () -> Unit) {
    val color = CONDITION_COLORS[code] ?: MaterialTheme.colorScheme.secondary
    Box(
        Modifier.clip(RoundedCornerShape(8.dp))
            .background(if (selected) color else color.copy(alpha = 0.45f))
            .then(if (selected) Modifier.border(2.dp, MaterialTheme.colorScheme.onSurface, RoundedCornerShape(8.dp)) else Modifier)
            .clickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 8.dp),
    ) { Text(code, color = conditionTextColor(code), fontWeight = FontWeight.Bold) }
}
