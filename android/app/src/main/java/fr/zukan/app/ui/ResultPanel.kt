package fr.zukan.app.ui

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
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.sizeIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.OpenInNew
import androidx.compose.material3.Icon
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
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import coil3.ImageLoader
import coil3.compose.AsyncImage
import fr.zukan.app.R
import fr.zukan.app.data.GameOut
import fr.zukan.app.data.PrintingOut
import fr.zukan.app.data.Settings
import java.util.Locale

/** A finish code of [finishes] matching the light's guess ("holo": holo or foil). */
fun guessedFinish(guess: String?, finishes: List<String>): String? = when (guess) {
    "holo" -> listOf("holo", "foil").firstOrNull { it in finishes }
    "reverse" -> "reverse".takeIf { it in finishes }
    else -> null
}

private val LANG_PARAM = Regex("""([?&])lang=[^&]*&?""")

/** A card picture link of the API in [lang]: `lang=` set or replaced. */
fun withImageLanguage(link: String, lang: String): String {
    if (!link.contains("/image")) return link
    val base = link.replace(LANG_PARAM) { it.groupValues[1] }.trimEnd('?', '&')
    return base + (if (base.contains('?')) "&" else "?") + "lang=$lang"
}

fun languageName(code: String): String =
    Locale.forLanguageTag(code).getDisplayName(Locale.getDefault()).ifEmpty { code }

/** Only web pages are opened from links the server sends (no intents, files...). */
fun isWebLink(url: String): Boolean = url.startsWith("https://") || url.startsWith("http://")

/**
 * The identified card: what was read, the card and its price, the copies owned, then
 * the printing, variant and quantity to add or remove.
 */
@Composable
fun ResultPanel(
    state: ScanState,
    games: List<GameOut>,
    settings: Settings,
    // The user's price sources, main one first.
    priceSources: List<String>,
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
    // Defaults: the copy opened from the collection, else detected language, else
    // preferred, else the printing's first language.
    val defaultLanguage = listOfNotNull(state.language, result.detected.lang, settings.language).firstOrNull { it in languages } ?: languages.first()
    // The copy's finish, else the light's guess (experimental), else the finish of the last
    // copies added, else the first.
    val guessed = guessedFinish(state.finishGuess, finishes)
    val defaultFinish = listOfNotNull(state.finish, guessed, state.lastFinish).firstOrNull { it in finishes } ?: finishes.firstOrNull() ?: ""

    var finish by remember(printing.id) { mutableStateOf(defaultFinish) }
    var condition by remember(printing.id) { mutableStateOf(settings.condition) }
    var language by remember(printing.id) { mutableStateOf(defaultLanguage) }
    var quantity by remember(printing.id) { mutableIntStateOf(1) }
    var pickPrinting by remember { mutableStateOf(false) }
    val finishName = { code: String -> game?.finishes?.firstOrNull { it.code == code }?.name ?: code }
    val uriHandler = LocalUriHandler.current
    // Named as printed in its set ("ビードル (Aspicot)"); servers before 0.6 only name the card.
    val name = printing.name.ifEmpty { candidate.card.name }
    val translation = if (printing.name.isNotEmpty()) printing.translation else candidate.card.translation
    // The finish chips also choose the price shown; card-wide prices need every printing.
    // Servers before 0.7 send every market: only the user's are shown.
    val sources = shownSources(game, priceSources)
    val mainSource = sources.firstOrNull()
    val stats = priceStats(candidate.printings, printing, finish, complete = candidate.printings.size >= candidate.printingCount, mainSource = mainSource)

    Column(modifier.verticalScroll(rememberScrollState()).padding(horizontal = 24.dp).padding(bottom = 24.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        DetectedRow(result.detected.name, result.detected.lang, result.detected.setCode, result.detected.collectorNumber)
        if (result.candidates.size > 1) {
            Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                result.candidates.forEachIndexed { index, c ->
                    PillChip(shownName(c.card.name, c.card.translation).text, index == state.candidate, { onCandidate(index) })
                }
            }
        }
        Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            CardPicture(
                // In the language chosen below (the server falls back to another one).
                printing.image?.let { withImageLanguage(it, language) },
                imageUrl,
                imageLoader,
                Modifier.width(120.dp),
                back = printing.backImage,
                landscape = printing.orientation == "landscape",
                contentDescription = name,
            )
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(shownName(name, translation), style = MaterialTheme.typography.titleLarge, fontWeight = FontWeight.SemiBold)
                printing.names[language]?.takeIf { it != name && it != translation }?.let {
                    Text(it, style = MaterialTheme.typography.bodyMedium)
                }
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    ColorSymbols(game, candidate.card.colors, imageUrl, imageLoader)
                    RarityBadge(game, printing.rarity, printing.rarityCode, imageUrl, imageLoader, lang = printing.set.lang)
                }
                val sourceName = { id: String -> game?.priceSources?.firstOrNull { it.id == id }?.name ?: id }
                val shownPrices = printing.prices
                    .filter { game == null || it.source in sources }
                    .sortedBy { sources.indexOf(it.source).let { i -> if (i < 0) Int.MAX_VALUE else i } }
                shownPrices.groupBy { it.source }.entries.forEachIndexed { index, (source, prices) ->
                    // The main market in full, the others on one line each.
                    if (index == 0) {
                        if (shownPrices.map { it.source }.distinct().size > 1) {
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
                printing.links.filter { isWebLink(it.url) && (game == null || it.source in sources) }.forEach { link ->
                    TextButton(onClick = { uriHandler.openUri(link.url) }, contentPadding = androidx.compose.foundation.layout.PaddingValues(0.dp)) {
                        Text(link.name)
                        Icon(Icons.AutoMirrored.Filled.OpenInNew, null, Modifier.padding(start = 4.dp).size(16.dp))
                    }
                }
            }
        }
        PriceStatsGrid(stats, finishName)
        OwnedSummary(game, printing)

        // Printing: tap to choose among all printings of the card.
        Row(
            Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp))
                .background(MaterialTheme.colorScheme.background)
                .border(1.dp, MaterialTheme.colorScheme.outline, RoundedCornerShape(16.dp))
                .clickable(enabled = candidate.printings.size > 1, role = Role.Button) { pickPrinting = true }
                .heightIn(min = 56.dp)
                .padding(horizontal = 16.dp, vertical = 8.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
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
                ZIcon(R.drawable.ic_chevron, stringResource(R.string.choose_printing))
            }
        }

        if (finishes.isNotEmpty()) {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                SectionLabel(stringResource(R.string.finish))
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    finishes.forEach { f -> PillChip(finishName(f), f == finish, { finish = f }) }
                }
                if (guessed != null && finish == guessed && state.finish == null) {
                    Text(
                        stringResource(R.string.finish_guessed),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                }
            }
        }
        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            SectionLabel("${stringResource(R.string.condition)} · ${CONDITION_NAMES[condition] ?: condition}")
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                CONDITIONS.forEach { c -> ConditionChoice(c, selected = c == condition) { condition = c } }
            }
        }
        if (languages.size > 1) {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                SectionLabel(stringResource(R.string.language))
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    languages.forEach { l -> PillChip(languageName(l), l == language, { language = l }, leading = { LangFlag(l, size = 20) }) }
                }
            }
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(stringResource(R.string.copies), style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
            QuantityStepper(quantity, onMinus = { if (quantity > 1) quantity-- }, onPlus = { if (quantity < 99) quantity++ })
        }
        GoldButton(
            stringResource(R.string.add_to_collection),
            { onAdjust(finish, condition, language, quantity) },
            enabled = !state.busy && finish.isNotEmpty(),
        )
        OutlinedButton(
            onClick = { onAdjust(finish, condition, language, -quantity) },
            enabled = !state.busy && printing.owned.isNotEmpty(),
            shape = FieldShape,
            modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp),
        ) { Text(stringResource(R.string.remove_from_collection), style = MaterialTheme.typography.titleMedium) }
        TextButton(onClick = onClose, modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp)) {
            ZIcon(R.drawable.ic_scan, null, Modifier.padding(end = 8.dp))
            Text(stringResource(R.string.scan_next), style = MaterialTheme.typography.titleMedium)
        }
    }

    if (pickPrinting) {
        PrintingPicker(
            printings = candidate.printings,
            total = candidate.printingCount,
            selectedId = printing.id,
            mainSource = mainSource,
            search = { q -> searchPrintings(candidate.card.id, q) },
            imageUrl = imageUrl,
            imageLoader = imageLoader,
            onPick = { onPrinting(it); pickPrinting = false },
            onDismiss = { pickPrinting = false },
            game = game,
        )
    }
}

/** This version | Cheapest version, Most expensive version | Lowest offer. */
@Composable
private fun PriceStatsGrid(stats: PriceStats, finishName: (String) -> String) {
    if (stats.thisVersion == null && stats.cheapest == null) return
    val label = { o: Offer -> "${o.printing.set.name} · ${finishName(o.price.finish)}" }
    val cells = listOfNotNull(
        stats.thisVersion?.let {
            Triple(stringResource(R.string.this_version), money(it.price.trend, it.price.currency),
                listOfNotNull(finishName(it.price.finish), it.price.low?.let { low -> stringResource(R.string.price_from, money(low, it.price.currency)) }).joinToString(" · "))
        },
        stats.cheapest?.let { Triple(stringResource(R.string.cheapest_version), money(it.price.trend, it.price.currency), label(it)) },
        stats.dearest?.let { Triple(stringResource(R.string.most_expensive_version), money(it.price.trend, it.price.currency), label(it)) },
        stats.lowestOffer?.let { Triple(stringResource(R.string.lowest_offer), money(it.price.low, it.price.currency), label(it)) },
    )
    Column(
        Modifier.fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(MaterialTheme.colorScheme.surfaceVariant),
    ) {
        cells.chunked(2).forEachIndexed { row, pair ->
            Row(Modifier.fillMaxWidth()) {
                pair.forEachIndexed { column, (title, value, desc) ->
                    val highlight = row == 0 && column == 0 && stats.thisVersion != null
                    Column(
                        Modifier.weight(1f)
                            .then(if (highlight) Modifier.background(MaterialTheme.colorScheme.primaryContainer) else Modifier)
                            .padding(horizontal = 10.dp, vertical = 6.dp),
                    ) {
                        Text(title, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                        Text(value, style = MaterialTheme.typography.titleMedium, fontWeight = FontWeight.SemiBold)
                        Text(desc, style = MaterialTheme.typography.bodySmall, maxLines = 2)
                    }
                }
                if (pair.size == 1) Spacer(Modifier.weight(1f))
            }
        }
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
        Modifier.sizeIn(minWidth = 48.dp, minHeight = 48.dp).clip(RoundedCornerShape(12.dp))
            .background(if (selected) color else color.copy(alpha = 0.45f))
            .then(if (selected) Modifier.border(2.dp, MaterialTheme.colorScheme.onSurface, RoundedCornerShape(12.dp)) else Modifier)
            .clickable(role = Role.RadioButton, onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 8.dp),
        contentAlignment = Alignment.Center,
    ) { Text(code, color = conditionTextColor(code), fontWeight = FontWeight.Bold) }
}
