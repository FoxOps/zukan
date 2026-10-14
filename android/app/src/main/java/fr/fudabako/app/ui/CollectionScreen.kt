package fr.fudabako.app.ui

import androidx.annotation.StringRes
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Sort
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Remove
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import coil3.ImageLoader
import coil3.compose.AsyncImage
import fr.fudabako.app.R
import fr.fudabako.app.data.FudabakoApi
import fr.fudabako.app.data.GameOut
import fr.fudabako.app.data.ItemOut
import fr.fudabako.app.data.ValueOut
import fr.fudabako.app.data.userMessage
import kotlinx.coroutines.delay

private const val PAGE_SIZE = 50

/** Sort orders of `GET /api/collection`, same as the web UI. */
enum class CollectionSort(val api: String, @StringRes val label: Int) {
    NAME("name", R.string.sort_name),
    SET("set", R.string.sort_set),
    UPDATED("updated", R.string.sort_updated),
    QUANTITY("quantity", R.string.sort_quantity),
    PRICE_ASC("price_asc", R.string.sort_price_asc),
    PRICE_DESC("price_desc", R.string.sort_price_desc),
}

/** The user's cards: value, filters like the web UI, quick +1 / -1, tap for details. */
@Composable
fun CollectionScreen(
    api: FudabakoApi?,
    games: List<GameOut>,
    stockVersion: Int,
    imageUrl: (String?) -> String?,
    imageLoader: ImageLoader,
    onAdjust: (ItemOut, Int) -> Unit,
    onOpen: (ItemOut) -> Unit,
) {
    var query by rememberSaveable { mutableStateOf("") }
    var game by rememberSaveable { mutableStateOf<String?>(null) }
    var condition by rememberSaveable { mutableStateOf<String?>(null) }
    var language by rememberSaveable { mutableStateOf<String?>(null) }
    var sort by rememberSaveable { mutableStateOf(CollectionSort.NAME) }
    // Rows loaded so far, in pages; every reload fetches them all in one request, so a
    // stock change refreshes quantities everywhere in the list.
    var pages by remember { mutableIntStateOf(1) }
    var items by remember { mutableStateOf<List<ItemOut>>(emptyList()) }
    var total by remember { mutableIntStateOf(0) }
    var value by remember { mutableStateOf<ValueOut?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    val context = LocalContext.current

    LaunchedEffect(query, game, condition, language, sort) { pages = 1 }
    LaunchedEffect(query, game, condition, language, sort, pages, stockVersion) {
        if (api == null) return@LaunchedEffect
        if (query.isNotEmpty()) delay(300) // typing debounce
        runCatching {
            api.collection(game, query.trim().ifEmpty { null }, null, condition, language, sort.api, 1, (PAGE_SIZE * pages).coerceAtMost(500))
        }.onSuccess {
            items = it.items
            total = it.total
            error = null
        }.onFailure { error = it.userMessage(context) }
        value = runCatching { api.collectionValue() }.getOrNull() ?: value
    }

    Column(Modifier.fillMaxSize().padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        value?.let { v ->
            val shown = game?.let { g -> v.games.firstOrNull { it.gameId == g } }
            Text(
                pluralStringResource(
                    R.plurals.collection_value,
                    shown?.quantity ?: v.quantity,
                    // Per currency: markets in different currencies are never added up.
                    shown?.let { money(it.total, it.currency) } ?: moneyByCurrency(v.games.map { it.total to it.currency }),
                    shown?.quantity ?: v.quantity,
                ),
                style = MaterialTheme.typography.titleMedium,
                modifier = Modifier.padding(top = 12.dp),
            )
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = query,
                onValueChange = { query = it },
                label = { Text(stringResource(R.string.search_collection)) },
                singleLine = true,
                modifier = Modifier.weight(1f),
            )
            SortMenu(sort) { sort = it }
        }
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            FilterChip(selected = game == null, onClick = { game = null }, label = { Text(stringResource(R.string.any_game)) })
            games.forEach { g -> FilterChip(selected = game == g.id, onClick = { game = g.id }, label = { Text(g.name) }) }
        }
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
            CONDITIONS.forEach { c -> ConditionChoice(c, selected = condition == c) { condition = if (condition == c) null else c } }
            val languages = (games.firstOrNull { it.id == game }?.let { listOf(it) } ?: games).flatMap { it.languages }.distinct()
            languages.forEach { l ->
                FilterChip(selected = language == l, onClick = { language = if (language == l) null else l }, label = { LangFlag(l, size = 18) })
            }
        }
        error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        if (items.isEmpty() && error == null) {
            Text(stringResource(R.string.collection_empty), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
        LazyColumn(verticalArrangement = Arrangement.spacedBy(2.dp)) {
            items(items, key = { it.id }) { item ->
                ItemRow(item, games.firstOrNull { it.id == item.gameId }, imageUrl, imageLoader, onAdjust, onOpen)
                HorizontalDivider()
            }
            if (items.size < total) {
                item {
                    TextButton(onClick = { pages++ }, modifier = Modifier.fillMaxWidth(), enabled = items.size < 500) {
                        Text(stringResource(R.string.load_more, total - items.size))
                    }
                }
            }
        }
    }
}

@Composable
private fun ItemRow(
    item: ItemOut,
    game: GameOut?,
    imageUrl: (String?) -> String?,
    imageLoader: ImageLoader,
    onAdjust: (ItemOut, Int) -> Unit,
    onOpen: (ItemOut) -> Unit,
) {
    Row(
        Modifier.fillMaxWidth().clickable { onOpen(item) }.padding(vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        AsyncImage(model = imageUrl(item.image), contentDescription = null, imageLoader = imageLoader, modifier = Modifier.width(44.dp).aspectRatio(63f / 88f))
        Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(3.dp)) {
            Text(shownName(item.name, item.translation), style = MaterialTheme.typography.titleSmall, maxLines = 1)
            Text(
                listOfNotNull(item.set?.code, item.collectorNumber, item.set?.name).joinToString(" · "),
                style = MaterialTheme.typography.bodySmall,
                maxLines = 1,
            )
            FlowRow(horizontalArrangement = Arrangement.spacedBy(4.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                FinishBadge(game, item.finish)
                ConditionBadge(item.condition)
                LangFlag(item.language)
            }
        }
        Column(horizontalAlignment = Alignment.End) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = { onAdjust(item, -1) }) { Icon(Icons.Default.Remove, stringResource(R.string.less)) }
                Text("${item.quantity}", fontWeight = FontWeight.SemiBold)
                IconButton(onClick = { onAdjust(item, 1) }) { Icon(Icons.Default.Add, stringResource(R.string.more)) }
            }
            item.unitPrice?.let { Text(money(it, item.currency), style = MaterialTheme.typography.bodySmall) }
        }
    }
}

@Composable
private fun SortMenu(sort: CollectionSort, onSort: (CollectionSort) -> Unit) {
    var open by remember { mutableStateOf(false) }
    Box {
        IconButton(onClick = { open = true }) { Icon(Icons.AutoMirrored.Filled.Sort, stringResource(R.string.sort)) }
        DropdownMenu(expanded = open, onDismissRequest = { open = false }) {
            CollectionSort.entries.forEach { option ->
                DropdownMenuItem(
                    text = { Text(stringResource(option.label), fontWeight = if (option == sort) FontWeight.Bold else null) },
                    onClick = {
                        onSort(option)
                        open = false
                    },
                )
            }
        }
    }
}
