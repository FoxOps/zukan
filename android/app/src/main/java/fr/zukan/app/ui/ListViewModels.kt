package fr.zukan.app.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import fr.zukan.app.R
import fr.zukan.app.ZukanApp
import fr.zukan.app.data.CardSummaryOut
import fr.zukan.app.data.ItemOut
import fr.zukan.app.data.SetOut
import fr.zukan.app.data.ValueOut
import fr.zukan.app.data.ZukanApi
import fr.zukan.app.data.runCatchingCancellable
import fr.zukan.app.data.userMessage
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.launch

private const val COLLECTION_PAGE_SIZE = 50
private const val SEARCH_PAGE_SIZE = 30
private const val TYPING_MS = 300L

/** What the collection list shows: typed text and filters. */
data class CollectionQuery(val text: String = "", val filter: CollectionFilter = CollectionFilter())

/** The collection tab's rows, value and query, kept while other tabs are open. */
class CollectionViewModel(application: Application) : AndroidViewModel(application) {
    private val app = application as ZukanApp
    private val _query = MutableStateFlow(CollectionQuery())
    val query: StateFlow<CollectionQuery> = _query.asStateFlow()
    private val _value = MutableStateFlow<ValueOut?>(null)
    val value: StateFlow<ValueOut?> = _value.asStateFlow()
    val pager = ListPager<CollectionQuery, ItemOut>(viewModelScope, CollectionQuery(), { it.id }, { it.userMessage(app) }) { q, page ->
        val out = api().collection(
            game = q.filter.game,
            query = q.text.trim().ifEmpty { null },
            setId = q.filter.set?.id,
            colors = q.filter.colors.ifEmpty { null },
            colorMode = if (q.filter.exactColors) "exact" else "include",
            finish = q.filter.finish,
            condition = q.filter.condition,
            language = q.filter.language,
            sort = q.filter.sort.api,
            page = page,
            pageSize = COLLECTION_PAGE_SIZE,
        )
        out.items to out.total
    }
    private var started = false
    private var seenStock = 0
    private var valueJob: Job? = null

    init {
        viewModelScope.launch {
            app.session.drop(1).collect {
                started = false
                seenStock = 0
                valueJob?.cancel()
                _value.value = null
                _query.value = CollectionQuery()
                pager.clear(CollectionQuery())
            }
        }
    }

    private fun api(): ZukanApi = app.client.value?.api ?: error(app.getString(R.string.error_not_connected))

    /** The first time the tab is shown in a session. */
    fun start() {
        if (started) return
        started = true
        refresh()
    }

    /** Rows from page 1 and the value again (back to the app: changed on the web maybe). */
    fun refresh() {
        pager.load(_query.value)
        loadValue()
    }

    fun setText(text: String) {
        if (text == _query.value.text) return
        _query.value = _query.value.copy(text = text)
        pager.load(_query.value, debounceMs = if (text.isEmpty()) 0 else TYPING_MS)
    }

    fun setFilter(filter: CollectionFilter) {
        if (filter == _query.value.filter) return
        _query.value = _query.value.copy(filter = filter)
        pager.load(_query.value)
    }

    /** A stock change (here, in the scanner or by an undo): the row follows in place when
     * the order cannot change; otherwise, or for a card not shown yet, the list reloads. */
    fun onStock(change: StockChange) {
        if (change.version <= seenStock) return
        seenStock = change.version
        val item = change.item
        val rows = pager.state.value
        val stableOrder = _query.value.filter.sort == CollectionSort.NAME || _query.value.filter.sort == CollectionSort.SET
        if (item != null && stableOrder && rows.loaded && rows.items.any { it.id == item.id }) {
            pager.update { p ->
                if (item.quantity > 0) {
                    p.copy(items = p.items.map { if (it.id == item.id) item else it })
                } else {
                    p.copy(items = p.items.filter { it.id != item.id }, total = p.total - 1)
                }
            }
        } else if (started) {
            pager.load(_query.value)
        }
        loadValue()
    }

    private fun loadValue() {
        valueJob?.cancel()
        valueJob = viewModelScope.launch {
            runCatchingCancellable { api().collectionValue() }.onSuccess { _value.value = it }
        }
    }
}

/** What the search tab looks for. */
data class SearchQuery(
    val text: String = "",
    val game: String? = null,
    val set: SetOut? = null,
    val colors: List<String> = emptyList(),
    val lang: String? = null,
) {
    val filtered get() = set != null || colors.isNotEmpty() || lang != null
    val searching get() = text.trim().length >= 2 || filtered
}

/** The search tab's query and results, kept while other tabs are open. */
class SearchViewModel(application: Application) : AndroidViewModel(application) {
    private val app = application as ZukanApp
    private val _query = MutableStateFlow(SearchQuery())
    val query: StateFlow<SearchQuery> = _query.asStateFlow()
    val pager = ListPager<SearchQuery, CardSummaryOut>(viewModelScope, SearchQuery(), { it.id }, { it.userMessage(app) }) { q, page ->
        val api = app.client.value?.api ?: error(app.getString(R.string.error_not_connected))
        val out = api.searchCards(q.text.trim().ifEmpty { null }, q.game, q.set?.id, q.colors.ifEmpty { null }, q.lang, page, SEARCH_PAGE_SIZE)
        out.items to out.total
    }
    private var started = false

    init {
        viewModelScope.launch {
            app.session.drop(1).collect {
                started = false
                _query.value = SearchQuery()
                pager.clear(SearchQuery())
            }
        }
    }

    /** The first time in a session: the scanner's game is the first filter. */
    fun start(defaultGame: String?) {
        if (started) return
        started = true
        _query.value = SearchQuery(game = defaultGame)
        pager.clear(_query.value)
    }

    fun setText(text: String) = set(_query.value.copy(text = text), typing = true)

    fun setGame(game: String?) = set(_query.value.copy(game = game, set = null, colors = emptyList()))

    fun setFilters(game: String?, set: SetOut?, colors: List<String>, lang: String?) =
        set(SearchQuery(_query.value.text, game, set, colors, lang))

    private fun set(next: SearchQuery, typing: Boolean = false) {
        if (next == _query.value) return
        _query.value = next
        if (next.searching) pager.load(next, debounceMs = if (typing) TYPING_MS else 0) else pager.clear(next)
    }
}
