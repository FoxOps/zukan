package fr.zukan.app.ui

import androidx.annotation.StringRes
import androidx.compose.foundation.Image
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
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
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
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
import coil3.ImageLoader
import fr.zukan.app.R
import fr.zukan.app.data.GameOut
import fr.zukan.app.data.ItemOut
import fr.zukan.app.data.PriceSourceOut
import fr.zukan.app.data.ValueOut
import fr.zukan.app.data.ZukanApi
import fr.zukan.app.data.userMessage
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
    api: ZukanApi?,
    games: List<GameOut>,
    mainSource: PriceSourceOut?,
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
    var showFilters by rememberSaveable { mutableStateOf(false) }
    var showSort by rememberSaveable { mutableStateOf(false) }
    // Rows loaded so far, in pages; every reload fetches them all in one request, so a
    // stock change refreshes quantities everywhere in the list.
    var pages by remember { mutableIntStateOf(1) }
    var retry by remember { mutableIntStateOf(0) }
    var items by remember { mutableStateOf<List<ItemOut>>(emptyList()) }
    var total by remember { mutableIntStateOf(0) }
    var loaded by remember { mutableStateOf(false) }
    var value by remember { mutableStateOf<ValueOut?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    val context = LocalContext.current

    LaunchedEffect(query, game, condition, language, sort) { pages = 1 }
    LaunchedEffect(query, game, condition, language, sort, pages, stockVersion, retry) {
        if (api == null) return@LaunchedEffect
        if (query.isNotEmpty()) delay(300) // typing debounce
        runCatching {
            api.collection(game, query.trim().ifEmpty { null }, null, condition, language, sort.api, 1, (PAGE_SIZE * pages).coerceAtMost(500))
        }.onSuccess {
            items = it.items
            total = it.total
            error = null
        }.onFailure { error = it.userMessage(context) }
        loaded = true
        value = runCatching { api.collectionValue() }.getOrNull() ?: value
    }

    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(start = 24.dp, end = 24.dp, bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item { ScreenHeader(stringResource(R.string.collection_title), stringResource(R.string.collection_subtitle)) }
        item { ValueCard(value, game, mainSource, Modifier.padding(top = 12.dp)) }
        item {
            Row(Modifier.padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.CenterVertically) {
                PillSearchField(query, { query = it }, stringResource(R.string.search_collection), Modifier.weight(1f))
                FilterButton(condition != null || language != null || sort != CollectionSort.NAME) { showFilters = true }
            }
        }
        item { GameChips(games, game, { game = it }, { showFilters = true }) }
        item {
            Row(Modifier.fillMaxWidth().padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(
                    games.firstOrNull { it.id == game }?.name ?: stringResource(R.string.all_cards),
                    style = MaterialTheme.typography.titleMedium,
                    fontSize = 20.sp,
                    modifier = Modifier.weight(1f),
                )
                val sortLabel = stringResource(R.string.sort)
                Row(
                    Modifier.heightIn(min = 48.dp).clickable(role = Role.Button, onClickLabel = sortLabel) { showSort = true }.padding(horizontal = 4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(6.dp),
                ) {
                    Text(stringResource(sort.label), style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    ZIcon(R.drawable.ic_list, null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
        when {
            error != null -> item {
                MessageCard(stringResource(R.string.error_title), error, action = {
                    OutlinedButton(onClick = { retry++ }) { Text(stringResource(R.string.try_again)) }
                })
            }
            !loaded -> item { Box(Modifier.fillMaxWidth().padding(32.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() } }
            items.isEmpty() -> item {
                MessageCard(
                    stringResource(R.string.collection_empty),
                    stringResource(R.string.collection_empty_help),
                    picture = { Image(painterResource(R.drawable.zukan_mascot), null, Modifier.size(72.dp)) },
                )
            }
        }
        items(items, key = { it.id }) { item ->
            ItemCard(item, games.firstOrNull { it.id == item.gameId }, imageUrl, imageLoader, onAdjust, onOpen)
        }
        if (items.size < total) {
            item {
                TextButton(onClick = { pages++ }, modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp), enabled = items.size < 500) {
                    Text(stringResource(R.string.load_more, total - items.size))
                }
            }
        }
    }

    if (showFilters) {
        CollectionFilters(
            games, game, language, condition, sort,
            onApply = { g, l, c, s ->
                game = g; language = l; condition = c; sort = s
                showFilters = false
            },
            onDismiss = { showFilters = false },
        )
    }
    if (showSort) {
        ZukanSheet(stringResource(R.string.sort), onDismiss = { showSort = false }) {
            Column {
                CollectionSort.entries.forEach { option ->
                    ChoiceRow(stringResource(option.label), option == sort, {
                        sort = option
                        showSort = false
                    })
                }
            }
        }
    }
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
            CardPicture(item.image, imageUrl, imageLoader, Modifier.width(52.dp), landscape = item.orientation == "landscape", contentDescription = name.text)
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
                    val finish = game?.finishes?.firstOrNull { it.code == item.finish }?.name ?: item.finish
                    Text(
                        "${item.language.uppercase()} · $finish",
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

/** Game, language, condition and sort, applied together. */
@Composable
private fun CollectionFilters(
    games: List<GameOut>,
    game: String?,
    language: String?,
    condition: String?,
    sort: CollectionSort,
    onApply: (String?, String?, String?, CollectionSort) -> Unit,
    onDismiss: () -> Unit,
) {
    var draftGame by remember { mutableStateOf(game) }
    var draftLanguage by remember { mutableStateOf(language) }
    var draftCondition by remember { mutableStateOf(condition) }
    var draftSort by remember { mutableStateOf(sort) }
    var pickLanguage by remember { mutableStateOf(false) }
    var pickSort by remember { mutableStateOf(false) }
    ZukanSheet(
        stringResource(R.string.filter_collection),
        onDismiss,
        subtitle = stringResource(R.string.filter_collection_help),
        footer = {
            FilterFooter(
                onReset = {
                    draftGame = null; draftLanguage = null; draftCondition = null; draftSort = CollectionSort.NAME
                },
                onApply = { onApply(draftGame, draftLanguage, draftCondition, draftSort) },
            )
        },
    ) {
        SheetSection(stringResource(R.string.game)) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                PillChip(stringResource(R.string.all), draftGame == null, { draftGame = null })
                games.forEach { g -> PillChip(g.name, draftGame == g.id, { draftGame = g.id }) }
            }
        }
        SheetSection(stringResource(R.string.language)) {
            PickerRow(draftLanguage?.let { languageName(it) } ?: stringResource(R.string.any_language), { pickLanguage = !pickLanguage }, R.drawable.ic_globe, pickLanguage)
            if (pickLanguage) {
                val languages = (games.firstOrNull { it.id == draftGame }?.let { listOf(it) } ?: games).flatMap { it.languages }.distinct()
                Column {
                    ChoiceRow(stringResource(R.string.any_language), draftLanguage == null, { draftLanguage = null; pickLanguage = false })
                    languages.forEach { l ->
                        ChoiceRow("${languageFlag(l) ?: ""} ${languageName(l)}".trim(), draftLanguage == l, { draftLanguage = l; pickLanguage = false })
                    }
                }
            }
        }
        SheetSection(stringResource(R.string.card_condition)) {
            FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                CONDITIONS.forEach { c ->
                    PillChip(c, draftCondition == c, { draftCondition = if (draftCondition == c) null else c })
                }
            }
            Text(
                draftCondition?.let { "$it · ${CONDITION_NAMES[it]}" } ?: stringResource(R.string.any_condition),
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        SheetSection(stringResource(R.string.sort)) {
            PickerRow(stringResource(draftSort.label), { pickSort = !pickSort }, expanded = pickSort)
            if (pickSort) {
                Column {
                    CollectionSort.entries.forEach { option ->
                        ChoiceRow(stringResource(option.label), option == draftSort, { draftSort = option; pickSort = false })
                    }
                }
            }
        }
    }
}
