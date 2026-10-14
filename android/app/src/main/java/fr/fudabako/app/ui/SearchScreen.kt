package fr.fudabako.app.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.FilterList
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.FilterChip
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
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
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.core.graphics.toColorInt
import coil3.ImageLoader
import coil3.compose.AsyncImage
import fr.fudabako.app.R
import fr.fudabako.app.data.CardSummaryOut
import fr.fudabako.app.data.FudabakoApi
import fr.fudabako.app.data.GameOut
import fr.fudabako.app.data.SetOut
import fr.fudabako.app.data.userMessage
import kotlinx.coroutines.delay

private const val PAGE_SIZE = 30

/**
 * Find a card when it cannot be scanned (damaged, foil glare, unusual layout): name in
 * any language (accents and case ignored) or "set number" codes, with optional game,
 * set, color and printed language filters.
 */
@Composable
fun SearchScreen(
    api: FudabakoApi?,
    defaultGame: String?,
    games: List<GameOut>,
    imageUrl: (String?) -> String?,
    imageLoader: ImageLoader,
    onPick: (CardSummaryOut) -> Unit,
) {
    var query by rememberSaveable { mutableStateOf("") }
    var game by rememberSaveable { mutableStateOf(defaultGame) }
    var set by remember { mutableStateOf<SetOut?>(null) }
    var colors by rememberSaveable { mutableStateOf(listOf<String>()) }
    var lang by rememberSaveable { mutableStateOf<String?>(null) }
    var showFilters by rememberSaveable { mutableStateOf(false) }
    var page by remember { mutableIntStateOf(1) }
    var results by remember { mutableStateOf<List<CardSummaryOut>>(emptyList()) }
    var total by remember { mutableIntStateOf(0) }
    var error by remember { mutableStateOf<String?>(null) }
    val context = LocalContext.current
    val gameInfo = games.firstOrNull { it.id == game }
    val filtered = set != null || colors.isNotEmpty() || lang != null

    LaunchedEffect(query, game, set, colors, lang) { page = 1 }
    LaunchedEffect(query, game, set, colors, lang, page) {
        if (api == null || (query.trim().length < 2 && !filtered)) {
            results = emptyList()
            total = 0
            return@LaunchedEffect
        }
        if (page == 1) delay(300) // typing debounce
        runCatching {
            api.searchCards(query.trim().ifEmpty { null }, game, set?.id, colors.ifEmpty { null }, lang, page, PAGE_SIZE)
        }.onSuccess {
            results = if (page == 1) it.items else results + it.items
            total = it.total
            error = null
        }.onFailure { error = it.userMessage(context) }
    }

    Column(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = query,
                onValueChange = { query = it },
                label = { Text(stringResource(R.string.search_hint)) },
                singleLine = true,
                modifier = Modifier.weight(1f),
            )
            IconButton(onClick = { showFilters = !showFilters }) {
                Icon(Icons.Default.FilterList, stringResource(R.string.filters), tint = if (filtered) MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
        Row(Modifier.horizontalScroll(rememberScrollState()), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            FilterChip(selected = game == null, onClick = { game = null; set = null; colors = emptyList() }, label = { Text(stringResource(R.string.any_game)) })
            games.forEach { g ->
                FilterChip(selected = game == g.id, onClick = { game = g.id; set = null; colors = emptyList() }, label = { Text(g.name) })
            }
        }
        if (showFilters) {
            Filters(api, gameInfo, games, set, { set = it }, colors, { colors = it }, lang, { lang = it })
        }
        error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(results, key = { it.id }) { card ->
                Row(
                    Modifier.fillMaxWidth().clickable { onPick(card) }.padding(4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    AsyncImage(
                        model = imageUrl(card.image),
                        contentDescription = null,
                        imageLoader = imageLoader,
                        modifier = Modifier.width(48.dp).aspectRatio(63f / 88f),
                    )
                    Column(Modifier.weight(1f)) {
                        Text(card.name, style = MaterialTheme.typography.titleMedium)
                        Text(
                            pluralStringResource(
                                R.plurals.printing_count,
                                card.printingCount,
                                games.firstOrNull { it.id == card.gameId }?.name ?: card.gameId,
                                card.printingCount,
                            ),
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                    card.priceMin?.let { Text(stringResource(R.string.price_value, it), style = MaterialTheme.typography.bodySmall) }
                }
            }
            if (results.size < total) {
                item {
                    TextButton(onClick = { page++ }, modifier = Modifier.fillMaxWidth()) {
                        Text(stringResource(R.string.load_more, total - results.size))
                    }
                }
            }
        }
    }
}

@Composable
private fun Filters(
    api: FudabakoApi?,
    game: GameOut?,
    games: List<GameOut>,
    set: SetOut?,
    onSet: (SetOut?) -> Unit,
    colors: List<String>,
    onColors: (List<String>) -> Unit,
    lang: String?,
    onLang: (String?) -> Unit,
) {
    var pickSet by remember { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        if (game != null) {
            OutlinedButton(onClick = { pickSet = true }) {
                Text(set?.let { "${it.code} · ${it.name}" } ?: stringResource(R.string.any_set), maxLines = 1)
            }
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                game.colors.forEach { c ->
                    val selected = c.code in colors
                    FilterChip(
                        selected = selected,
                        onClick = { onColors(if (selected) colors - c.code else colors + c.code) },
                        label = { Text(c.name) },
                        leadingIcon = { Text("●", color = runCatching { Color(c.hex.toColorInt()) }.getOrDefault(Color.Gray)) },
                    )
                }
            }
        }
        val languages = (game?.let { listOf(it) } ?: games).flatMap { it.languages }.distinct()
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            FilterChip(selected = lang == null, onClick = { onLang(null) }, label = { Text(stringResource(R.string.any_language)) })
            languages.forEach { l ->
                FilterChip(selected = lang == l, onClick = { onLang(l) }, label = { LangFlag(l, size = 18) })
            }
        }
    }
    if (pickSet && game != null) {
        SetPicker(api, game.id, onPick = { onSet(it); pickSet = false }, onDismiss = { pickSet = false })
    }
}

/** Sets of a game, newest first, filtered by name or code. */
@Composable
private fun SetPicker(api: FudabakoApi?, game: String, onPick: (SetOut?) -> Unit, onDismiss: () -> Unit) {
    var sets by remember { mutableStateOf<List<SetOut>>(emptyList()) }
    var filter by remember { mutableStateOf("") }
    LaunchedEffect(game) { sets = runCatching { api?.sets(game) }.getOrNull().orEmpty() }
    val shown = sets.filter { filter.isBlank() || it.name.contains(filter, true) || it.code.contains(filter, true) }
    AlertDialog(
        onDismissRequest = onDismiss,
        confirmButton = { TextButton(onClick = { onPick(null) }) { Text(stringResource(R.string.any_set)) } },
        title = {
            OutlinedTextField(value = filter, onValueChange = { filter = it }, label = { Text(stringResource(R.string.filter_sets)) }, singleLine = true)
        },
        text = {
            LazyColumn(Modifier.heightIn(max = 420.dp)) {
                items(shown, key = { it.id }) { s ->
                    Row(
                        Modifier.fillMaxWidth().clickable { onPick(s) }.padding(vertical = 8.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text(s.code, style = MaterialTheme.typography.labelLarge, modifier = Modifier.width(56.dp))
                        Text(s.name, Modifier.weight(1f), maxLines = 2)
                        s.lang?.let { LangFlag(it, size = 14) }
                    }
                }
            }
        },
    )
}
