package fr.zukan.app.ui

import androidx.activity.compose.BackHandler
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
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.foundation.selection.triStateToggleable
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.stateDescription
import androidx.compose.ui.state.ToggleableState
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import fr.zukan.app.R
import fr.zukan.app.data.ShoppingItemIn
import fr.zukan.app.data.ShoppingItemOut
import fr.zukan.app.data.ShoppingListOut
import fr.zukan.app.data.ZukanApi
import fr.zukan.app.data.runCatchingCancellable
import fr.zukan.app.data.userMessage
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

/** Shopping lists sent from the web (a deck's missing cards): tick copies while buying.
 * Lists are deleted only here, never on their own, even complete. Ticking a card marks it
 * bought on the list; it does not change the collection. */
@Composable
fun ShoppingScreen(api: ZukanApi?) {
    var openId by rememberSaveable { mutableStateOf<Int?>(null) }
    BackHandler(enabled = openId != null) { openId = null }
    val id = openId
    if (id == null) ShoppingLists(api) { openId = it } else ShoppingListDetail(api, id) { openId = null }
}

@Composable
private fun ShoppingLists(api: ZukanApi?, onOpen: (Int) -> Unit) {
    var lists by remember { mutableStateOf<List<ShoppingListOut>?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var reload by remember { mutableIntStateOf(0) }
    val context = LocalContext.current
    // Lists sent from the web meanwhile.
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) { reload++ }
    LaunchedEffect(api, reload) {
        if (api == null) return@LaunchedEffect
        runCatching { api.shoppingLists() }
            .onSuccess { lists = it; error = null }
            .onFailure { error = it.userMessage(context) }
    }
    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(start = 24.dp, end = 24.dp, bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        item { ScreenHeader(stringResource(R.string.shopping_title), stringResource(R.string.shopping_subtitle)) }
        val shown = lists
        when {
            error != null -> item {
                MessageCard(stringResource(R.string.error_title), error, action = {
                    OutlinedButton(onClick = { reload++ }) { Text(stringResource(R.string.try_again)) }
                })
            }
            shown == null -> item {
                Box(Modifier.fillMaxWidth().padding(32.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
            }
            shown.isEmpty() -> item {
                MessageCard(stringResource(R.string.shopping_empty), stringResource(R.string.shopping_empty_help))
            }
            else -> items(shown, key = { it.id }) { list -> ShoppingListRow(list) { onOpen(list.id) } }
        }
    }
}

@Composable
private fun ShoppingListRow(list: ShoppingListOut, onClick: () -> Unit) {
    Surface(shape = CardShape, color = MaterialTheme.colorScheme.surfaceContainerLow, modifier = Modifier.fillMaxWidth().clickable(onClick = onClick)) {
        Row(Modifier.padding(horizontal = 20.dp, vertical = 16.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(list.name, style = MaterialTheme.typography.titleMedium)
                Text(
                    stringResource(R.string.shopping_progress, list.bought, list.copies) + " · " + list.createdAt.take(10),
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
            }
            if (list.complete) {
                Text(stringResource(R.string.shopping_complete), style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.primary)
            }
            ZIcon(R.drawable.ic_chevron, null)
        }
    }
}

@Composable
private fun ShoppingListDetail(api: ZukanApi?, id: Int, onBack: () -> Unit) {
    var list by remember { mutableStateOf<ShoppingListOut?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var reload by remember { mutableIntStateOf(0) }
    var deleting by remember { mutableStateOf(false) }
    val context = LocalContext.current
    val scope = rememberCoroutineScope()
    LaunchedEffect(api, id, reload) {
        if (api == null) return@LaunchedEffect
        runCatching { api.shoppingList(id) }
            .onSuccess { list = it; error = null }
            .onFailure { error = it.userMessage(context) }
    }

    // Per item: the count last asked for, the count the server last confirmed, and one
    // write at a time (taps 1 then 2 must not reach the server as 2 then 1).
    val wanted = remember { mutableMapOf<Int, Int>() }
    val confirmed = remember { mutableMapOf<Int, Int>() }
    val writes = remember { mutableMapOf<Int, Mutex>() }

    fun setBought(item: ShoppingItemOut, count: Int) {
        val current = list ?: return
        confirmed.getOrPut(item.id) { current.items.firstOrNull { it.id == item.id }?.boughtCount ?: item.boughtCount }
        wanted[item.id] = count
        // Shown at once; the server's answer (or this item's last saved count) follows.
        list = current.withBought(item.id, count)
        scope.launch {
            writes.getOrPut(item.id) { Mutex() }.withLock {
                // A newer tap of this item came meanwhile: only that one is sent.
                if (wanted[item.id] != count) return@withLock
                runCatchingCancellable { api!!.updateShoppingItem(id, item.id, ShoppingItemIn(count, bought = count >= item.quantity)) }
                    .onSuccess { answer ->
                        val saved = answer.items.firstOrNull { it.id == item.id }?.boughtCount ?: count
                        confirmed[item.id] = saved
                        if (wanted[item.id] == count) list = list?.withItemOf(answer, item.id)
                    }
                    .onFailure {
                        if (wanted[item.id] == count) {
                            wanted.remove(item.id)
                            list = list?.withBought(item.id, confirmed[item.id] ?: item.boughtCount)
                        }
                        error = it.userMessage(context)
                    }
            }
        }
    }

    LazyColumn(
        Modifier.fillMaxSize(),
        contentPadding = PaddingValues(start = 24.dp, end = 24.dp, bottom = 24.dp),
        verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        item {
            Row(Modifier.padding(top = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                TextButton(onClick = onBack) { Text("← " + stringResource(R.string.shopping_title)) }
                Box(Modifier.weight(1f))
                if (list != null) {
                    IconButton(onClick = { deleting = true }) { ZIcon(R.drawable.ic_delete, stringResource(R.string.shopping_delete)) }
                }
            }
        }
        val shown = list
        item {
            ScreenHeader(
                shown?.name ?: "",
                shown?.let { stringResource(R.string.shopping_progress, it.bought, it.copies) },
                mascot = false,
            )
        }
        error?.let { message ->
            item {
                MessageCard(stringResource(R.string.error_title), message, action = {
                    OutlinedButton(onClick = { reload++ }) { Text(stringResource(R.string.try_again)) }
                })
            }
        }
        if (shown == null && error == null) {
            item { Box(Modifier.fillMaxWidth().padding(32.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() } }
        }
        if (shown != null) items(shown.items, key = { it.id }) { item -> ShoppingItemRow(item) { setBought(item, it) } }
    }

    if (deleting) {
        AlertDialog(
            onDismissRequest = { deleting = false },
            title = { Text(stringResource(R.string.shopping_delete_title)) },
            text = { Text(stringResource(R.string.shopping_delete_text, list?.name ?: "")) },
            confirmButton = {
                TextButton(onClick = {
                    deleting = false
                    scope.launch {
                        runCatching { api!!.deleteShoppingList(id) }
                            .onSuccess { onBack() }
                            .onFailure { error = it.userMessage(context) }
                    }
                }) { Text(stringResource(R.string.shopping_delete)) }
            },
            dismissButton = { TextButton(onClick = { deleting = false }) { Text(stringResource(R.string.cancel)) } },
        )
    }
}

/** One box per copy ("[x][ ][ ] 3 Card Name"): a box ticks the copies up to it, or unticks
 * from it; the row ticks all copies, or none once all are bought. Above [MAX_BOXES] copies,
 * a − count + stepper instead of a box per copy. */
@Composable
private fun ShoppingItemRow(item: ShoppingItemOut, onBought: (Int) -> Unit) {
    val count = item.boughtCount
    val done = if (item.bought) TextDecoration.LineThrough else null
    val faded = if (item.bought) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.onSurface
    val progress = stringResource(R.string.shopping_item_state, count, item.quantity)
    Row(
        Modifier.fillMaxWidth().heightIn(min = 56.dp)
            .triStateToggleable(
                state = when {
                    item.bought -> ToggleableState.On
                    count > 0 -> ToggleableState.Indeterminate
                    else -> ToggleableState.Off
                },
                role = Role.Checkbox,
            ) { onBought(if (item.bought) 0 else item.quantity) }
            .semantics { stateDescription = progress },
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        if (item.quantity <= MAX_BOXES) {
            // 48 dp each: neighbouring boxes never share a touch target.
            FlowRow(Modifier.width(BOX_SIZE * minOf(item.quantity, BOXES_PER_ROW)), maxItemsInEachRow = BOXES_PER_ROW) {
                repeat(item.quantity) { copy ->
                    val label = stringResource(R.string.shopping_copy, item.name, copy + 1, item.quantity)
                    Checkbox(
                        checked = copy < count,
                        onCheckedChange = { onBought(if (copy < count) copy else copy + 1) },
                        modifier = Modifier.size(BOX_SIZE).semantics { contentDescription = label },
                    )
                }
            }
        } else {
            QuantityStepper(
                count,
                onMinus = { if (count > 0) onBought(count - 1) },
                onPlus = { if (count < item.quantity) onBought(count + 1) },
            )
        }
        Text("${item.quantity}", style = MaterialTheme.typography.titleMedium, color = faded, modifier = Modifier.width(28.dp))
        Column(Modifier.weight(1f)) {
            Text(item.name, style = MaterialTheme.typography.bodyLarge, color = faded, textDecoration = done)
            item.translation?.let { Text(it, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant, textDecoration = done) }
        }
        val printing = listOfNotNull(item.setCode, item.collectorNumber).joinToString(" ")
        if (printing.isNotEmpty()) {
            Text(printing, style = MaterialTheme.typography.bodySmall, fontFamily = FontFamily.Monospace, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
}

// Copy boxes: a row of the list holds this many before wrapping; more copies than
// MAX_BOXES get a stepper (a deck line may ask for up to 250).
private const val BOXES_PER_ROW = 4
private const val MAX_BOXES = 8
private val BOX_SIZE = 48.dp
