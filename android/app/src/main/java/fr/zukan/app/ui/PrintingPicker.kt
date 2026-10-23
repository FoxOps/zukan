package fr.zukan.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import coil3.ImageLoader
import coil3.compose.AsyncImage
import fr.zukan.app.R
import fr.zukan.app.data.GameOut
import fr.zukan.app.data.PrintingOut
import kotlinx.coroutines.delay

/** True when `query` appears in the set name, code or collector number (case-insensitive). */
fun printingMatches(printing: PrintingOut, query: String): Boolean {
    val q = query.trim()
    if (q.isEmpty()) return true
    return listOfNotNull(printing.set.name, printing.set.code, printing.collectorNumber, "${printing.set.code} ${printing.collectorNumber}")
        .any { it.contains(q, ignoreCase = true) }
}

/**
 * Printings of a card, filterable by set name, code or number. A scan loads the 30 most
 * likely of `total`: the others are searched on the server while typing.
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PrintingPicker(
    printings: List<PrintingOut>,
    total: Int,
    selectedId: Int?,
    // Price shown for each printing: this market's (null: the first one listed).
    mainSource: String?,
    search: suspend (String) -> List<PrintingOut>,
    imageUrl: (String?) -> String?,
    imageLoader: ImageLoader,
    onPick: (PrintingOut) -> Unit,
    onDismiss: () -> Unit,
    // For rarity pictograms.
    game: GameOut? = null,
) {
    var query by remember { mutableStateOf("") }
    var remote by remember { mutableStateOf<List<PrintingOut>>(emptyList()) }
    val partial = total > printings.size
    LaunchedEffect(query) {
        val q = query.trim()
        if (!partial || q.length < 2) {
            remote = emptyList()
            return@LaunchedEffect
        }
        delay(300) // typing: wait for a pause
        remote = runCatching { search(q) }.getOrDefault(emptyList())
    }
    val local = printings.filter { printingMatches(it, query) }
    val known = local.map { it.id }.toSet()
    val shown = local + remote.filter { it.id !in known }
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(Modifier.padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(stringResource(R.string.choose_printing), style = MaterialTheme.typography.titleMedium)
            if (partial) {
                Text(stringResource(R.string.printings_partial, printings.size, total), style = MaterialTheme.typography.bodySmall)
            }
            if (total > 6) {
                OutlinedTextField(
                    value = query,
                    onValueChange = { query = it },
                    label = { Text(stringResource(R.string.filter_printings)) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
            LazyColumn(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                items(shown, key = { it.id }) { printing ->
                    Row(
                        Modifier.fillMaxWidth()
                            .background(if (printing.id == selectedId) MaterialTheme.colorScheme.secondaryContainer else MaterialTheme.colorScheme.surface)
                            .clickable { onPick(printing) }
                            .padding(6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        CardPicture(printing.image, imageUrl, imageLoader, Modifier.width(40.dp), landscape = printing.orientation == "landscape")
                        Column(Modifier.weight(1f)) {
                            Text(printing.set.name, style = MaterialTheme.typography.bodyLarge, maxLines = 1)
                            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                                Text(
                                    listOfNotNull(printing.set.code, printing.collectorNumber, printing.set.releaseDate?.take(4)).joinToString(" · "),
                                    style = MaterialTheme.typography.bodySmall,
                                )
                                printing.languages.take(4).forEach { LangFlag(it, size = 12) }
                            }
                            RarityBadge(game, printing.rarity, printing.rarityCode, imageUrl, imageLoader, lang = printing.set.lang)
                        }
                        Column(horizontalAlignment = Alignment.End) {
                            mainPrices(printing, mainSource).minByOrNull { it.trend.toDoubleOrNull() ?: Double.MAX_VALUE }?.let {
                                Text(money(it.trend, it.currency), style = MaterialTheme.typography.bodySmall)
                            }
                            val owned = printing.owned.sumOf { it.quantity }
                            if (owned > 0) {
                                Text(
                                    stringResource(R.string.owned_quantity, owned),
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.primary,
                                    fontWeight = FontWeight.SemiBold,
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}
