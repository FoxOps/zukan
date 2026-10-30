package fr.zukan.app.ui

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import coil3.ImageLoader
import fr.zukan.app.R
import fr.zukan.app.data.CardSummaryOut
import fr.zukan.app.data.GameOut
import fr.zukan.app.data.SetOut
import fr.zukan.app.data.ZukanApi
import fr.zukan.app.data.userMessage
import kotlinx.coroutines.delay

private const val PAGE_SIZE = 30

/**
 * Find a card when it cannot be scanned (damaged, foil glare, unusual layout): name in
 * any language (accents and case ignored) or "set number" codes, with optional game,
 * set, color and printed language filters.
 */
@Composable
fun SearchScreen(
    api: ZukanApi?,
    defaultGame: String?,
    games: List<GameOut>,
    imageUrl: (String?) -> String?,
    imageLoader: ImageLoader,
    onScan: () -> Unit,
    onPick: (CardSummaryOut) -> Unit,
) {
    var query by rememberSaveable { mutableStateOf("") }
    var game by rememberSaveable { mutableStateOf(defaultGame) }
    var set by remember { mutableStateOf<SetOut?>(null) }
    var colors by rememberSaveable { mutableStateOf(listOf<String>()) }
    var lang by rememberSaveable { mutableStateOf<String?>(null) }
    var showFilters by rememberSaveable { mutableStateOf(false) }
    var page by remember { mutableIntStateOf(1) }
    var retry by remember { mutableIntStateOf(0) }
    var results by remember { mutableStateOf<List<CardSummaryOut>>(emptyList()) }
    var total by remember { mutableIntStateOf(0) }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val context = LocalContext.current
    val filtered = set != null || colors.isNotEmpty() || lang != null
    val searching = query.trim().length >= 2 || filtered

    LaunchedEffect(query, game, set, colors, lang) { page = 1 }
    LaunchedEffect(query, game, set, colors, lang, page, retry) {
        if (api == null || !searching) {
            results = emptyList()
            total = 0
            error = null
            return@LaunchedEffect
        }
        if (page == 1) delay(300) // typing debounce
        loading = true
        runCatching {
            api.searchCards(query.trim().ifEmpty { null }, game, set?.id, colors.ifEmpty { null }, lang, page, PAGE_SIZE)
        }.onSuccess {
            results = if (page == 1) it.items else results + it.items
            total = it.total
            error = null
        }.onFailure { error = it.userMessage(context) }
        loading = false
    }

    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(start = 24.dp, end = 24.dp, bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item { ScreenHeader(stringResource(R.string.search_title), stringResource(R.string.search_subtitle)) }
        item {
            Row(Modifier.padding(top = 12.dp), horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically) {
                PillSearchField(query, { query = it }, stringResource(R.string.search_hint), Modifier.weight(1f))
                FilterButton(filtered) { showFilters = true }
            }
        }
        item {
            GameChips(games, game, { g ->
                game = g
                set = null
                colors = emptyList()
            }, { showFilters = true })
        }
        when {
            !searching -> item { SearchIntro(onScan, Modifier.padding(top = 12.dp)) }
            error != null -> item {
                MessageCard(stringResource(R.string.error_title), error, action = {
                    OutlinedButton(onClick = { retry++ }) { Text(stringResource(R.string.try_again)) }
                })
            }
            results.isEmpty() && loading -> item {
                Box(Modifier.fillMaxWidth().padding(32.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
            }
            results.isEmpty() -> item {
                MessageCard(stringResource(R.string.search_no_result), stringResource(R.string.search_no_result_help), action = {
                    OutlinedButton(onClick = onScan) { Text(stringResource(R.string.scan_a_card)) }
                })
            }
        }
        items(results, key = { it.id }) { card -> ResultCard(card, games, imageUrl, imageLoader, onPick) }
        if (results.size < total) {
            item {
                TextButton(onClick = { page++ }, modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp), enabled = !loading) {
                    Text(stringResource(R.string.load_more, total - results.size))
                }
            }
        }
    }

    if (showFilters) {
        SearchFilters(api, games, game, set, colors, lang, onApply = { g, s, c, l ->
            game = g; set = s; colors = c; lang = l
            showFilters = false
        }, onDismiss = { showFilters = false })
    }
}

/** Before typing: what the tab is for, the scanner button and two steps. */
@Composable
private fun SearchIntro(onScan: () -> Unit, modifier: Modifier = Modifier) {
    Column(modifier, verticalArrangement = Arrangement.spacedBy(20.dp)) {
        MessageCard(
            stringResource(R.string.search_intro_title),
            stringResource(R.string.search_intro_text),
            picture = { Image(painterResource(R.drawable.illus_card_search), null, Modifier.size(96.dp)) },
        )
        GoldButton(stringResource(R.string.scan_a_card), onScan)
        Column(Modifier.padding(top = 8.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            SectionLabel(stringResource(R.string.how_it_works))
            listOf(R.string.search_step_game, R.string.search_step_filters).forEachIndexed { i, step ->
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                    Box(Modifier.size(28.dp).clip(CircleShape).background(MaterialTheme.colorScheme.outlineVariant), contentAlignment = Alignment.Center) {
                        Text("${i + 1}", style = MaterialTheme.typography.labelLarge)
                    }
                    Text(stringResource(step), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
    }
}

@Composable
private fun ResultCard(card: CardSummaryOut, games: List<GameOut>, imageUrl: (String?) -> String?, imageLoader: ImageLoader, onPick: (CardSummaryOut) -> Unit) {
    val game = games.firstOrNull { it.id == card.gameId }
    val name = shownName(card.name, card.translation)
    Surface(onClick = { onPick(card) }, shape = CardShape, color = MaterialTheme.colorScheme.surfaceContainerLow, modifier = Modifier.fillMaxWidth()) {
        Row(Modifier.padding(12.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            CardPicture(card.image, imageUrl, imageLoader, Modifier.width(52.dp), landscape = card.orientation == "landscape", contentDescription = name.text)
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(name, style = MaterialTheme.typography.titleMedium, fontSize = 17.sp, maxLines = 2, overflow = TextOverflow.Ellipsis)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    ColorSymbols(game, card.colors, imageUrl, imageLoader, size = 14)
                    RarityBadge(game, card.rarity, card.rarityCode, imageUrl, imageLoader)
                }
                Text(
                    pluralStringResource(R.plurals.printing_count, card.printingCount, game?.name ?: card.gameId, card.printingCount),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            card.priceMin?.let {
                Text(
                    stringResource(R.string.price_from, money(it, card.currency)),
                    style = MaterialTheme.typography.titleMedium,
                    fontWeight = FontWeight.Bold,
                )
            }
        }
    }
}

/** Game, set, colours and printed language, applied together. */
@Composable
private fun SearchFilters(
    api: ZukanApi?,
    games: List<GameOut>,
    game: String?,
    set: SetOut?,
    colors: List<String>,
    lang: String?,
    onApply: (String?, SetOut?, List<String>, String?) -> Unit,
    onDismiss: () -> Unit,
) {
    var draftGame by remember { mutableStateOf(game) }
    var draftSet by remember { mutableStateOf(set) }
    var draftColors by remember { mutableStateOf(colors) }
    var draftLang by remember { mutableStateOf(lang) }
    var pickSet by remember { mutableStateOf(false) }
    var pickLang by remember { mutableStateOf(false) }
    val gameInfo = games.firstOrNull { it.id == draftGame }
    ZukanSheet(
        stringResource(R.string.filter_search),
        onDismiss,
        subtitle = stringResource(R.string.filter_collection_help),
        footer = {
            FilterFooter(
                onReset = {
                    draftGame = null; draftSet = null; draftColors = emptyList(); draftLang = null
                },
                onApply = { onApply(draftGame, draftSet, draftColors, draftLang) },
            )
        },
    ) {
        SheetSection(stringResource(R.string.game)) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                val choose = { g: String? ->
                    if (g != draftGame) {
                        draftGame = g
                        draftSet = null
                        draftColors = emptyList()
                    }
                }
                PillChip(stringResource(R.string.all), draftGame == null, { choose(null) })
                games.forEach { g -> PillChip(g.name, draftGame == g.id, { choose(g.id) }) }
            }
        }
        if (gameInfo != null) {
            SheetSection(stringResource(R.string.set)) {
                PickerRow(draftSet?.let { "${it.code} · ${it.name}" } ?: stringResource(R.string.any_set), { pickSet = true })
            }
            if (gameInfo.colors.isNotEmpty()) {
                SheetSection(stringResource(R.string.colors)) {
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        gameInfo.colors.forEach { c ->
                            val selected = c.code in draftColors
                            PillChip(
                                c.name,
                                selected,
                                { draftColors = if (selected) draftColors - c.code else draftColors + c.code },
                                leading = { Box(Modifier.size(12.dp).clip(CircleShape).background(colorOf(c.hex))) },
                            )
                        }
                    }
                }
            }
        }
        SheetSection(stringResource(R.string.language)) {
            PickerRow(draftLang?.let { languageName(it) } ?: stringResource(R.string.any_language), { pickLang = !pickLang }, R.drawable.ic_globe, pickLang)
            if (pickLang) {
                val languages = (gameInfo?.let { listOf(it) } ?: games).flatMap { it.languages }.distinct()
                Column {
                    ChoiceRow(stringResource(R.string.any_language), draftLang == null, { draftLang = null; pickLang = false })
                    languages.forEach { l ->
                        ChoiceRow("${languageFlag(l) ?: ""} ${languageName(l)}".trim(), draftLang == l, { draftLang = l; pickLang = false })
                    }
                }
            }
        }
    }
    if (pickSet && draftGame != null) {
        SetPicker(api, draftGame!!, onPick = { draftSet = it; pickSet = false }, onDismiss = { pickSet = false })
    }
}

/** Sets of a game, newest first, filtered by name or code. */
@Composable
fun SetPicker(api: ZukanApi?, game: String, onPick: (SetOut?) -> Unit, onDismiss: () -> Unit) {
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
