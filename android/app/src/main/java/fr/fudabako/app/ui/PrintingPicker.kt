package fr.fudabako.app.ui

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
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
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
import fr.fudabako.app.R
import fr.fudabako.app.data.PrintingOut

/** True when `query` appears in the set name, code or collector number (case-insensitive). */
fun printingMatches(printing: PrintingOut, query: String): Boolean {
    val q = query.trim()
    if (q.isEmpty()) return true
    return listOfNotNull(printing.set.name, printing.set.code, printing.collectorNumber, "${printing.set.code} ${printing.collectorNumber}")
        .any { it.contains(q, ignoreCase = true) }
}

/** All printings of a card, filterable by set name, code or number. */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PrintingPicker(
    printings: List<PrintingOut>,
    selected: Int,
    imageUrl: (String?) -> String?,
    imageLoader: ImageLoader,
    onPick: (Int) -> Unit,
    onDismiss: () -> Unit,
) {
    var query by remember { mutableStateOf("") }
    val shown = printings.withIndex().filter { printingMatches(it.value, query) }
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)) {
        Column(Modifier.padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(stringResource(R.string.choose_printing), style = MaterialTheme.typography.titleMedium)
            if (printings.size > 6) {
                OutlinedTextField(
                    value = query,
                    onValueChange = { query = it },
                    label = { Text(stringResource(R.string.filter_printings)) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
            }
            LazyColumn(Modifier.fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                itemsIndexed(shown, key = { _, item -> item.value.id }) { _, (index, printing) ->
                    Row(
                        Modifier.fillMaxWidth()
                            .background(if (index == selected) MaterialTheme.colorScheme.secondaryContainer else MaterialTheme.colorScheme.surface)
                            .clickable { onPick(index) }
                            .padding(6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        AsyncImage(
                            model = imageUrl(printing.image),
                            contentDescription = null,
                            imageLoader = imageLoader,
                            modifier = Modifier.width(40.dp).aspectRatio(63f / 88f),
                        )
                        Column(Modifier.weight(1f)) {
                            Text(printing.set.name, style = MaterialTheme.typography.bodyLarge, maxLines = 1)
                            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
                                Text(
                                    listOfNotNull(printing.set.code, printing.collectorNumber, printing.set.releaseDate?.take(4)).joinToString(" · "),
                                    style = MaterialTheme.typography.bodySmall,
                                )
                                printing.languages.take(4).forEach { LangFlag(it, size = 12) }
                            }
                        }
                        Column(horizontalAlignment = Alignment.End) {
                            printing.prices.minByOrNull { it.trend.toDoubleOrNull() ?: Double.MAX_VALUE }?.let {
                                Text(stringResource(R.string.price_value, it.trend), style = MaterialTheme.typography.bodySmall)
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
