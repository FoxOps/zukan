package fr.zukan.app.ui

import fr.zukan.app.data.runCatchingCancellable
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** Rows of one query ([key]), as far as [page] (0: none loaded yet), kept together so an
 * answer for another query or page never mixes in. */
data class Paged<K, T>(
    val key: K,
    val items: List<T> = emptyList(),
    val total: Int = 0,
    val page: Int = 0,
    val loading: Boolean = false,
    val error: String? = null,
) {
    val loaded get() = page > 0
    val more get() = loaded && items.size < total

    /** Page [number] of [forKey] answered: page 1 replaces the rows, the next page adds its
     * new rows; anything else (another query, a page already loaded) changes nothing. */
    fun withPage(forKey: K, number: Int, rows: List<T>, count: Int, id: (T) -> Any): Paged<K, T> {
        if (forKey != key) return this
        return when (number) {
            1 -> copy(items = rows, total = count, page = 1, loading = false, error = null)
            page + 1 -> {
                val known = items.mapTo(HashSet(), id)
                copy(items = items + rows.filter { id(it) !in known }, total = count, page = number, loading = false, error = null)
            }
            else -> this
        }
    }

    /** Page [number] of [forKey] failed: the rows stay, the same page is asked again next. */
    fun withError(forKey: K, number: Int, message: String): Paged<K, T> =
        if (forKey != key || number != page + 1) this else copy(loading = false, error = message)
}

/** Loads [Paged] rows: a new query cancels the work for the previous one. */
class ListPager<K, T>(
    private val scope: CoroutineScope,
    initial: K,
    private val id: (T) -> Any,
    private val message: (Throwable) -> String,
    private val fetch: suspend (key: K, page: Int) -> Pair<List<T>, Int>,
) {
    private val _state = MutableStateFlow(Paged<K, T>(initial))
    val state: StateFlow<Paged<K, T>> = _state.asStateFlow()
    private var job: Job? = null

    /** Rows of [key] from page 1 (after [debounceMs] of typing). Rows of the same query stay
     * shown while they reload. */
    fun load(key: K, debounceMs: Long = 0) {
        job?.cancel()
        _state.update { if (it.key == key) it.copy(loading = true, error = null, page = 0) else Paged(key, loading = true) }
        job = scope.launch {
            if (debounceMs > 0) delay(debounceMs)
            page(key, 1)
        }
    }

    /** The next page of the current query (the failed one again after an error). */
    fun more() {
        val current = _state.value
        if (current.loading || !current.more) return
        _state.update { it.copy(loading = true, error = null) }
        job = scope.launch { page(current.key, current.page + 1) }
    }

    /** Page 1 again, or the failed page. */
    fun retry() {
        val current = _state.value
        if (current.loaded) {
            if (current.error != null) {
                _state.update { it.copy(error = null) }
                more()
            }
        } else {
            load(current.key)
        }
    }

    fun update(transform: (Paged<K, T>) -> Paged<K, T>) = _state.update(transform)

    /** Empty, as for a new session. */
    fun clear(key: K) {
        job?.cancel()
        _state.value = Paged(key)
    }

    private suspend fun page(key: K, number: Int) {
        runCatchingCancellable { fetch(key, number) }
            .onSuccess { (rows, count) -> _state.update { it.withPage(key, number, rows, count, id) } }
            .onFailure { e -> _state.update { it.withError(key, number, message(e)) } }
    }
}
