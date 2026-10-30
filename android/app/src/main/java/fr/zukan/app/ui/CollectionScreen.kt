package fr.zukan.app.ui

import android.content.Context
import android.content.Intent
import android.widget.Toast
import androidx.annotation.StringRes
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
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.GridItemSpan
import androidx.compose.foundation.lazy.grid.LazyGridScope
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.content.FileProvider
import coil3.ImageLoader
import fr.zukan.app.R
import fr.zukan.app.data.GameOut
import fr.zukan.app.data.ItemOut
import fr.zukan.app.data.PriceSourceOut
import fr.zukan.app.data.SetOut
import fr.zukan.app.data.Settings
import fr.zukan.app.data.ValueOut
import fr.zukan.app.data.ZukanApi
import fr.zukan.app.data.userMessage
import java.io.File
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

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

/** Filters of the collection, as the web UI's. Set, finish and colors need a game. */
data class CollectionFilter(
    val game: String? = null,
    val set: SetOut? = null,
    val finish: String? = null,
    val colors: List<String> = emptyList(),
    // Exactly these colors, instead of at least one of them.
    val exactColors: Boolean = false,
    val language: String? = null,
    val condition: String? = null,
    val sort: CollectionSort = CollectionSort.NAME,
) {
    val narrowed get() = set != null || finish != null || colors.isNotEmpty() || language != null || condition != null || sort != CollectionSort.NAME

    /** Another game: what only applies to the previous one goes. */
    fun withGame(id: String?) = if (id == game) this else copy(game = id, set = null, finish = null, colors = emptyList())
}

/** The user's cards: value, filters like the web UI, list or picture grid, quick +1 / -1,
 * tap for details, CSV export. */
@Composable
fun CollectionScreen(
    api: ZukanApi?,
    games: List<GameOut>,
    mainSource: PriceSourceOut?,
    stock: StockChange,
    settings: Settings,
    imageUrl: (String?) -> String?,
    imageLoader: ImageLoader,
    onGrid: (Boolean) -> Unit,
    onAdjust: (ItemOut, Int) -> Unit,
    onOpen: (ItemOut) -> Unit,
) {
    var query by rememberSaveable { mutableStateOf("") }
    var filter by remember { mutableStateOf(CollectionFilter()) }
    var showFilters by rememberSaveable { mutableStateOf(false) }
    var showSort by rememberSaveable { mutableStateOf(false) }
    // Pages loaded so far; "Load more" adds the next one.
    var page by remember { mutableIntStateOf(1) }
    var reload by remember { mutableIntStateOf(0) }
    var items by remember { mutableStateOf<List<ItemOut>>(emptyList()) }
    var total by remember { mutableIntStateOf(0) }
    var loaded by remember { mutableStateOf(false) }
    var loadingMore by remember { mutableStateOf(false) }
    var exporting by remember { mutableStateOf(false) }
    var value by remember { mutableStateOf<ValueOut?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    val grid = settings.collectionGrid

    suspend fun fetch(number: Int) = api!!.collection(
        game = filter.game,
        query = query.trim().ifEmpty { null },
        setId = filter.set?.id,
        colors = filter.colors.ifEmpty { null },
        colorMode = if (filter.exactColors) "exact" else "include",
        finish = filter.finish,
        condition = filter.condition,
        language = filter.language,
        sort = filter.sort.api,
        page = number,
        pageSize = PAGE_SIZE,
    )

    LaunchedEffect(query, filter, reload) {
        if (api == null) return@LaunchedEffect
        if (query.isNotEmpty()) delay(300) // typing debounce
        runCatching { fetch(1) }
            .onSuccess {
                items = it.items
                total = it.total
                page = 1
                error = null
            }
            .onFailure { error = it.userMessage(context) }
        loaded = true
    }
    // Stock changed (here, in the scanner or by an undo): the row follows in place; a card
    // not shown yet (a new copy) means the list itself changed.
    LaunchedEffect(stock.version) {
        if (api == null) return@LaunchedEffect
        val changed = stock.item
        if (stock.version > 0) {
            if (changed != null && items.any { it.id == changed.id }) {
                items = if (changed.quantity > 0) items.map { if (it.id == changed.id) changed else it } else items.filter { it.id != changed.id }
                if (changed.quantity <= 0) total--
            } else {
                reload++
            }
        }
        value = runCatching { api.collectionValue() }.getOrNull() ?: value
    }
    val loadMore = {
        if (api != null && !loadingMore) {
            loadingMore = true
            scope.launch {
                runCatching { fetch(page + 1) }.onSuccess { next ->
                    val known = items.mapTo(HashSet()) { it.id }
                    items = items + next.items.filter { it.id !in known }
                    total = next.total
                    page++
                }.onFailure { Toast.makeText(context, it.userMessage(context), Toast.LENGTH_LONG).show() }
                loadingMore = false
            }
        }
    }
    val export = {
        if (api != null && !exporting) {
            exporting = true
            scope.launch {
                runCatching { shareCsv(context, api, filter.game) }
                    .onFailure { exportFailed(context, it) }
                exporting = false
            }
        }
    }

    LazyVerticalGrid(
        columns = GridCells.Adaptive(minSize = 104.dp),
        modifier = Modifier.fillMaxSize(),
        contentPadding = PaddingValues(start = 24.dp, end = 24.dp, bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
        horizontalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        line { ScreenHeader(stringResource(R.string.collection_title), stringResource(R.string.collection_subtitle)) }
        line { ValueCard(value, filter.game, mainSource, Modifier.padding(top = 12.dp)) }
        line {
            Row(Modifier.padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically) {
                PillSearchField(query, { query = it }, stringResource(R.string.search_collection), Modifier.weight(1f))
                FilterButton(filter.narrowed) { showFilters = true }
            }
        }
        line { GameChips(games, filter.game, { filter = filter.withGame(it) }, { showFilters = true }) }
        line {
            Row(Modifier.fillMaxWidth().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(
                    games.firstOrNull { it.id == filter.game }?.name ?: stringResource(R.string.all_cards),
                    style = MaterialTheme.typography.titleMedium,
                    fontSize = 20.sp,
                    modifier = Modifier.weight(1f),
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                val sortLabel = stringResource(R.string.sort)
                Row(
                    Modifier.heightIn(min = 48.dp).clickable(role = Role.Button, onClickLabel = sortLabel) { showSort = true }.padding(horizontal = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text(stringResource(filter.sort.label), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
                }
                IconButton(onClick = { onGrid(!grid) }) {
                    ZIcon(if (grid) R.drawable.ic_list else R.drawable.ic_grid, stringResource(if (grid) R.string.view_list else R.string.view_grid), tint = MaterialTheme.colorScheme.onSurfaceVariant)
                }
                IconButton(onClick = export, enabled = !exporting && items.isNotEmpty()) {
                    if (exporting) {
                        CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
                    } else {
                        ZIcon(R.drawable.ic_share, stringResource(R.string.export_csv), tint = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
        }
        when {
            error != null -> line {
                MessageCard(stringResource(R.string.error_title), error, action = {
                    OutlinedButton(onClick = { reload++ }) { Text(stringResource(R.string.try_again)) }
                })
            }
            !loaded -> line { Box(Modifier.fillMaxWidth().padding(32.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() } }
            items.isEmpty() -> line {
                MessageCard(
                    stringResource(R.string.collection_empty),
                    stringResource(R.string.collection_empty_help),
                    picture = { Image(painterResource(R.drawable.zukan_mascot), null, Modifier.size(72.dp)) },
                )
            }
        }
        items(
            items,
            key = { it.id },
            span = { if (grid) GridItemSpan(1) else GridItemSpan(maxLineSpan) },
            contentType = { if (grid) "tile" else "row" },
        ) { item ->
            val game = games.firstOrNull { it.id == item.gameId }
            if (grid) {
                ItemTile(item, imageUrl, imageLoader, onOpen)
            } else {
                ItemCard(item, game, imageUrl, imageLoader, onAdjust, onOpen)
            }
        }
        if (items.size < total) {
            line {
                TextButton(onClick = loadMore, modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp), enabled = !loadingMore) {
                    Text(stringResource(R.string.load_more, total - items.size))
                }
            }
        }
    }

    if (showFilters) {
        CollectionFilters(
            api,
            games,
            filter,
            onApply = {
                filter = it
                showFilters = false
            },
            onDismiss = { showFilters = false },
        )
    }
    if (showSort) {
        ZukanSheet(stringResource(R.string.sort), onDismiss = { showSort = false }) {
            Column {
                CollectionSort.entries.forEach { option ->
                    ChoiceRow(stringResource(option.label), option == filter.sort, {
                        filter = filter.copy(sort = option)
                        showSort = false
                    })
                }
            }
        }
    }
}

/** A grid line of its own (headers, messages). */
private fun LazyGridScope.line(content: @Composable () -> Unit) =
    item(span = { GridItemSpan(maxLineSpan) }, contentType = "line") { content() }

/** The collection as CSV (same file as the web UI's export), handed to the app the user picks. */
private suspend fun shareCsv(context: Context, api: ZukanApi, game: String?) {
    val body = api.exportCsv(game)
    val file = withContext(Dispatchers.IO) {
        val folder = File(context.cacheDir, "exports").apply { mkdirs() }
        File(folder, "zukan-collection-${game ?: "all"}.csv").also { out ->
            body.byteStream().use { input -> out.outputStream().use { input.copyTo(it) } }
        }
    }
    val uri = FileProvider.getUriForFile(context, "${context.packageName}.updates", file)
    val send = Intent(Intent.ACTION_SEND)
        .setType("text/csv")
        .putExtra(Intent.EXTRA_STREAM, uri)
        .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
    context.startActivity(Intent.createChooser(send, context.getString(R.string.export_csv)))
}

/** Gold card: estimated value (per currency, never added up across currencies) and copies. */
@Composable
private fun ValueCard(value: ValueOut?, game: String?, mainSource: PriceSourceOut?, modifier: Modifier = Modifier) {
    val shown = game?.let { g -> value?.games?.firstOrNull { it.gameId == g } }
    val quantity = shown?.quantity ?: value?.quantity ?: 0
    val amounts = shown?.let { listOf(it.total to it.currency) } ?: value?.games?.map { it.total to it.currency }.orEmpty()
    val currencies = amounts.map { it.second }.distinct()
    Surface(
        shape = RoundedCornerShape(32.dp),
        color = MaterialTheme.colorScheme.primaryContainer,
        contentColor = MaterialTheme.colorScheme.onPrimaryContainer,
        modifier = modifier.fillMaxWidth(),
    ) {
        Row(Modifier.padding(horizontal = 20.dp, vertical = 20.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                Text(stringResource(R.string.estimated_value).uppercase(), style = MaterialTheme.typography.labelLarge)
                Text(
                    if (value == null) "—" else if (amounts.isEmpty()) money("0", mainSource?.currency) else moneyByCurrency(amounts),
                    style = MaterialTheme.typography.displaySmall,
                )
                val source = listOfNotNull(mainSource?.name, currencies.joinToString(", ").ifEmpty { mainSource?.currency }).joinToString(" · ")
                if (source.isNotEmpty()) Text(source, style = MaterialTheme.typography.bodyMedium)
            }
            Column(horizontalAlignment = Alignment.End, verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text("$quantity", style = MaterialTheme.typography.headlineLarge)
                Text(pluralStringResource(R.plurals.cards, quantity), style = MaterialTheme.typography.bodyLarge)
                ZIcon(R.drawable.ic_collection, null, Modifier.padding(top = 6.dp))
            }
        }
    }
}

@Composable
private fun ItemCard(
    item: ItemOut,
    game: GameOut?,
    imageUrl: (String?) -> String?,
    imageLoader: ImageLoader,
    onAdjust: (ItemOut, Int) -> Unit,
    onOpen: (ItemOut) -> Unit,
) {
    val name = shownName(item.name, item.translation)
    Surface(
        onClick = { onOpen(item) },
        shape = CardShape,
        color = MaterialTheme.colorScheme.surfaceContainerLow,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Row(
            Modifier.padding(12.dp),
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(12.dp),
        ) {
            CardPicture(thumbLink(item.image), imageUrl, imageLoader, Modifier.width(52.dp), landscape = item.orientation == "landscape", contentDescription = name.text)
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(
                    name,
                    style = MaterialTheme.typography.titleMedium,
                    fontSize = 17.sp,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                Text(
                    listOfNotNull(item.set?.code, item.collectorNumber, item.set?.name).joinToString(" · "),
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis,
                )
                FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(4.dp), itemVerticalAlignment = Alignment.CenterVertically) {
                    ConditionTag(item.condition)
                    // The copy's language as a flag (its name for screen readers), then the finish.
                    LangFlag(item.language, Modifier.semantics { contentDescription = languageName(item.language) })
                    val finish = game?.finishes?.firstOrNull { it.code == item.finish }?.name ?: item.finish
                    Text(
                        finish,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    ColorSymbols(game, item.colors, imageUrl, imageLoader, size = 14)
                }
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), itemVerticalAlignment = Alignment.CenterVertically) {
                    RarityBadge(game, item.rarity, item.rarityCode, imageUrl, imageLoader, lang = item.language)
                    TrendIcons(item.trends)
                }
            }
            Column(horizontalAlignment = Alignment.End, verticalArrangement = Arrangement.spacedBy(8.dp)) {
                QuantityStepper(item.quantity, onMinus = { onAdjust(item, -1) }, onPlus = { onAdjust(item, 1) })
                val price = item.unitPrice?.let { money(it, item.currency) }
                val noPrice = stringResource(R.string.no_price)
                Text(
                    price ?: "—",
                    style = MaterialTheme.typography.titleMedium,
                    fontSize = 18.sp,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.padding(end = 4.dp).semantics { if (price == null) contentDescription = noPrice },
                )
            }
        }
    }
}

/** Grid tile: the picture with the copies and the language flag on it, then the name. */
@Composable
private fun ItemTile(item: ItemOut, imageUrl: (String?) -> String?, imageLoader: ImageLoader, onOpen: (ItemOut) -> Unit) {
    val name = shownName(item.name, item.translation)
    Column(
        Modifier.clip(RoundedCornerShape(8.dp)).clickable(onClickLabel = name.text) { onOpen(item) },
        verticalArrangement = Arrangement.spacedBy(4.dp),
    ) {
        Box {
            CardPicture(thumbLink(item.image), imageUrl, imageLoader, Modifier.fillMaxWidth(), landscape = item.orientation == "landscape", contentDescription = name.text)
            Text(
                "×${item.quantity}",
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onPrimaryContainer,
                modifier = Modifier.align(Alignment.BottomStart).padding(4.dp)
                    .background(MaterialTheme.colorScheme.primaryContainer, CircleShape).padding(horizontal = 8.dp, vertical = 2.dp),
            )
            LangFlag(
                item.language,
                Modifier.align(Alignment.TopEnd).padding(4.dp)
                    .background(MaterialTheme.colorScheme.surface.copy(alpha = 0.85f), CircleShape).padding(horizontal = 4.dp)
                    .semantics { contentDescription = languageName(item.language) },
            )
        }
        Text(name, style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
        Text(
            item.unitPrice?.let { money(it, item.currency) } ?: "—",
            style = MaterialTheme.typography.labelLarge,
            fontWeight = FontWeight.Bold,
        )
    }
}

/** Game, set, finish, colors, language, condition and sort, applied together. */
@Composable
private fun CollectionFilters(
    api: ZukanApi?,
    games: List<GameOut>,
    filter: CollectionFilter,
    onApply: (CollectionFilter) -> Unit,
    onDismiss: () -> Unit,
) {
    var draft by remember { mutableStateOf(filter) }
    var pickLanguage by remember { mutableStateOf(false) }
    var pickSort by remember { mutableStateOf(false) }
    var pickSet by remember { mutableStateOf(false) }
    val gameInfo = games.firstOrNull { it.id == draft.game }
    ZukanSheet(
        stringResource(R.string.filter_collection),
        onDismiss,
        subtitle = stringResource(R.string.filter_collection_help),
        footer = {
            FilterFooter(
                onReset = { draft = CollectionFilter() },
                onApply = { onApply(draft) },
            )
        },
    ) {
        SheetSection(stringResource(R.string.game)) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                PillChip(stringResource(R.string.all), draft.game == null, { draft = draft.withGame(null) })
                games.forEach { g -> PillChip(g.name, draft.game == g.id, { draft = draft.withGame(g.id) }) }
            }
        }
        if (gameInfo != null) {
            SheetSection(stringResource(R.string.set)) {
                PickerRow(draft.set?.let { "${it.code} · ${it.name}" } ?: stringResource(R.string.any_set), { pickSet = true })
            }
            if (gameInfo.finishes.size > 1) {
                SheetSection(stringResource(R.string.finish)) {
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        gameInfo.finishes.forEach { f ->
                            PillChip(f.name, draft.finish == f.code, { draft = draft.copy(finish = if (draft.finish == f.code) null else f.code) })
                        }
                    }
                }
            }
            if (gameInfo.colors.isNotEmpty()) {
                SheetSection(stringResource(R.string.colors)) {
                    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        gameInfo.colors.forEach { c ->
                            val selected = c.code in draft.colors
                            PillChip(
                                c.name,
                                selected,
                                { draft = draft.copy(colors = if (selected) draft.colors - c.code else draft.colors + c.code) },
                                leading = { Box(Modifier.size(12.dp).clip(CircleShape).background(colorOf(c.hex))) },
                            )
                        }
                    }
                    if (draft.colors.isNotEmpty()) {
                        Column {
                            ChoiceRow(stringResource(R.string.colors_include), !draft.exactColors, { draft = draft.copy(exactColors = false) })
                            ChoiceRow(stringResource(R.string.colors_exact), draft.exactColors, { draft = draft.copy(exactColors = true) })
                        }
                    }
                }
            }
        }
        SheetSection(stringResource(R.string.language)) {
            PickerRow(draft.language?.let { "${languageFlag(it) ?: ""} ${languageName(it)}".trim() } ?: stringResource(R.string.any_language), { pickLanguage = !pickLanguage }, R.drawable.ic_globe, pickLanguage)
            if (pickLanguage) {
                val languages = (gameInfo?.let { listOf(it) } ?: games).flatMap { it.languages }.distinct()
                Column {
                    ChoiceRow(stringResource(R.string.any_language), draft.language == null, { draft = draft.copy(language = null); pickLanguage = false })
                    languages.forEach { l ->
                        ChoiceRow("${languageFlag(l) ?: ""} ${languageName(l)}".trim(), draft.language == l, { draft = draft.copy(language = l); pickLanguage = false })
                    }
                }
            }
        }
        SheetSection(stringResource(R.string.card_condition)) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                CONDITIONS.forEach { c ->
                    PillChip(c, draft.condition == c, { draft = draft.copy(condition = if (draft.condition == c) null else c) })
                }
            }
            Text(
                draft.condition?.let { "$it · ${CONDITION_NAMES[it]}" } ?: stringResource(R.string.any_condition),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        SheetSection(stringResource(R.string.sort)) {
            PickerRow(stringResource(draft.sort.label), { pickSort = !pickSort }, expanded = pickSort)
            if (pickSort) {
                Column {
                    CollectionSort.entries.forEach { option ->
                        ChoiceRow(stringResource(option.label), option == draft.sort, { draft = draft.copy(sort = option); pickSort = false })
                    }
                }
            }
        }
    }
    val pickedGame = draft.game
    if (pickSet && pickedGame != null) {
        SetPicker(api, pickedGame, onPick = { draft = draft.copy(set = it); pickSet = false }, onDismiss = { pickSet = false })
    }
}

private fun exportFailed(context: Context, error: Throwable) =
    Toast.makeText(context, context.getString(R.string.export_failed, error.userMessage(context)), Toast.LENGTH_LONG).show()
