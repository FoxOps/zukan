package fr.zukan.app.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import fr.zukan.app.ZukanApp
import fr.zukan.app.R
import fr.zukan.app.data.AdjustIn
import fr.zukan.app.data.CandidateOut
import fr.zukan.app.data.CardRef
import fr.zukan.app.data.CardSummaryOut
import fr.zukan.app.data.HintsOut
import fr.zukan.app.data.IdentifyIn
import fr.zukan.app.data.IdentifyOut
import fr.zukan.app.data.ItemOut
import fr.zukan.app.data.OcrLineIn
import fr.zukan.app.data.PrintingOut
import fr.zukan.app.data.runCatchingCancellable
import fr.zukan.app.data.userMessage
import fr.zukan.app.scan.GlareMeter
import fr.zukan.app.scan.ScanPicture
import fr.zukan.app.scan.ScanStabilizer
import fr.zukan.app.scan.toJpegBase64
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.drop
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

enum class Phase { SCANNING, IDENTIFYING, RESULT, NOT_FOUND, ERROR }

/** Where a card is shown: the scanner's result, or a card opened by hand over any tab. */
enum class Panel { SCAN, DETAILS }

/** Text in view this long without a card sent: "Scan now" is offered. */
private const val STUCK_MS = 4000L

/** Games with set symbols the server compares (old Magic cards print no set code). */
private val SYMBOL_GAMES = setOf("mtg")

/** An Asian reading this recent is what "Scan now" sends. */
private const val ASIAN_FRESH_MS = 2000L

data class Undoable(val transactionId: Int, val text: String)

/** A stock change: lists of owned cards update [item] in place when they show it, else
 * reload ([item] null: undo, or unknown). */
data class StockChange(val version: Int = 0, val item: ItemOut? = null)

/** An owned copy opened from the collection: what the panel starts on. */
data class Variant(val language: String, val finish: String, val condition: String)

data class ScanState(
    val phase: Phase = Phase.SCANNING,
    val result: IdentifyOut? = null,
    val candidate: Int = 0,
    val printing: Int = 0,
    val busy: Boolean = false,
    val message: String? = null,
    // Why identification failed (phase ERROR): network, server...
    val error: String? = null,
    val undo: Undoable? = null,
    // Every stock change, so lists of owned cards follow.
    val stock: StockChange = StockChange(),
    // A copy opened from the collection: its language, finish and condition come first.
    val language: String? = null,
    val finish: String? = null,
    val condition: String? = null,
    // Finish of the last copies added (the next card of a batch is often the same).
    val lastFinish: String? = null,
    // Experimental guess from how light moves on the card ("holo", "reverse").
    val finishGuess: String? = null,
    // Cards not found in a row (hints about light and holo cards).
    val failures: Int = 0,
    // Text in view for a while and nothing sent (glare on holo cards): "Scan now" shown.
    val stuck: Boolean = false,
) {
    val current: CandidateOut? get() = result?.candidates?.getOrNull(candidate)
}

/** A card opened from the collection or search: loading, failed, or shown in [card]. */
data class DetailsState(
    val cardId: Int,
    val printingId: Int? = null,
    val variant: Variant? = null,
    val card: ScanState? = null,
    val error: String? = null,
) {
    val loading get() = card == null && error == null
}

/** Scan flow: steady OCR text -> identify -> pick printing/variant -> add or remove; and the
 * same panel for cards opened by hand ([details]). */
class ScanViewModel(application: Application) : AndroidViewModel(application) {
    private val app = application as ZukanApp
    private val stabilizer = ScanStabilizer()
    // Readings of Asian models in automatic mode come every 3rd frame: 2 in a row suffice.
    private val asianStabilizer = ScanStabilizer(framesNeeded = 2)
    /** Set while the experimental finish guess is on (fed by the camera analysis thread). */
    @Volatile
    var glare: GlareMeter? = null
    private val _state = MutableStateFlow(ScanState())
    val state: StateFlow<ScanState> = _state.asStateFlow()
    private val _details = MutableStateFlow<DetailsState?>(null)
    val details: StateFlow<DetailsState?> = _details.asStateFlow()
    var game: String? = null
    // Back to the camera after adding copies (setting "after adding").
    var autoNext = false

    // Work of the current session (account and server): cancelled when it ends, so nothing
    // of the previous account (result, owned copies, undo) shows up afterwards.
    private var sessionJob = SupervisorJob(viewModelScope.coroutineContext[Job])
    private val sessionScope get() = CoroutineScope(viewModelScope.coroutineContext + sessionJob)

    private var identifyJob: Job? = null
    private var detailsJob: Job? = null

    init {
        viewModelScope.launch { app.session.drop(1).collect { reset() } }
    }

    val scanning get() = _state.value.phase == Phase.SCANNING

    /** Games whose old cards print no set code: a picture goes with the text so the server
     * can compare the set symbol (any game: the card may be one). */
    val wantsPicture get() = game == null || game in SYMBOL_GAMES

    // Each identify request; an answer to an older one (or after leaving) is dropped.
    @Volatile
    private var request = 0

    // Each card opened by hand; an answer for an older one is dropped.
    private var detailsRequest = 0

    /** Called from the camera analysis thread for every frame: true when the card is
     * steady and new, so the frame is read for identification. */
    // Lines of the last frames: a frame sent without the collector number line (glare)
    // gets it from a recent frame of the same card.
    private val recent = ArrayDeque<List<OcrLineIn>>()

    // When text came into view without a card being sent since (0: nothing in view).
    private var readingSince = 0L

    @Synchronized
    fun onFrame(lines: List<OcrLineIn>): Boolean {
        if (!scanning) return false
        remember(lines)
        val now = android.os.SystemClock.elapsedRealtime()
        if (lines.size < 2) {
            readingSince = 0L
        } else if (readingSince == 0L) {
            readingSince = now
        }
        val stuck = readingSince != 0L && now - readingSince >= STUCK_MS
        if (stuck != _state.value.stuck) _state.update { it.copy(stuck = stuck) }
        return stabilizer.offer(lines.map { it.text })
    }

    /** "Scan now": the latest frame with text is identified without waiting for a steady
     * reading (glare on a holo card can keep the reading from settling). */
    fun scanNow() {
        val lines = synchronized(this) {
            // An Asian model that just found its script read the card better than the
            // Latin one (whose reading would lose the card's language).
            val now = android.os.SystemClock.elapsedRealtime()
            recentAsian?.takeIf { now - recentAsianAt <= ASIAN_FRESH_MS } ?: recent.lastOrNull { it.size >= 2 }
        } ?: return
        identify(lines)
    }

    // The last reading of an Asian model that found its script (automatic mode).
    private var recentAsian: List<OcrLineIn>? = null
    private var recentAsianAt = 0L

    @Synchronized
    fun onAsianFrame(lines: List<OcrLineIn>): Boolean {
        if (!scanning) return false
        if (lines.size >= 2) {
            recentAsian = lines
            recentAsianAt = android.os.SystemClock.elapsedRealtime()
        }
        return asianStabilizer.offer(lines.map { it.text })
    }

    private fun remember(lines: List<OcrLineIn>) {
        recent.addLast(lines)
        while (recent.size > ScanStabilizer.WINDOW) recent.removeFirst()
    }

    fun identify(lines: List<OcrLineIn>, picture: ScanPicture? = null) {
        val client = app.client.value ?: return
        val id = synchronized(this) {
            // One card at a time: "Scan now" and a steady frame arriving together would
            // send it twice, and the later answer (or failure) replace the shown one.
            if (_state.value.phase == Phase.IDENTIFYING) return
            readingSince = 0L
            ++request
        }
        val sent = synchronized(this) { ScanStabilizer.withNumberLine(lines, recent.toList()) }
        val guess = glare?.guess()
        glare?.reset()
        _state.update { it.copy(phase = Phase.IDENTIFYING, message = null, error = null, stuck = false) }
        identifyJob = sessionScope.launch {
            runCatchingCancellable {
                val image = picture?.let { withContext(Dispatchers.Default) { runCatching { it.toJpegBase64() }.getOrNull() } }
                client.api.identify(IdentifyIn(game, sent, image, picture?.box?.takeIf { image != null }))
            }
                .onSuccess { answer ->
                    // A card the server returns without printings cannot be shown.
                    val result = answer.copy(candidates = answer.candidates.filter { it.printings.isNotEmpty() })
                    _state.update {
                        if (!current(id, it)) return@update it
                        it.copy(
                            phase = if (result.candidates.isEmpty()) Phase.NOT_FOUND else Phase.RESULT,
                            result = result,
                            candidate = 0,
                            printing = 0,
                            language = null,
                            finish = null,
                            condition = null,
                            finishGuess = guess,
                            failures = if (result.candidates.isEmpty()) it.failures + 1 else 0,
                            // Missing from the server catalog: fetched from its source.
                            message = if (result.fetched) app.getString(R.string.card_fetched) else it.message,
                        )
                    }
                }
                // Shown on the camera until "Try again" (no scanning against a server that fails).
                .onFailure { e ->
                    _state.update { if (current(id, it)) it.copy(phase = Phase.ERROR, error = e.userMessage(app)) else it }
                }
        }
    }

    /** The answer to request [id] is still awaited: the newest request, not left since. */
    private fun current(id: Int, state: ScanState) = id == request && state.phase == Phase.IDENTIFYING

    /** Show a card picked by hand (search or collection screen) over the current tab,
     * `printingId` first when given, else the printing the catalog shows. */
    fun openCard(summary: CardSummaryOut) = openCard(summary.id, summary.printingId)

    /** An owned copy of the collection: its printing and variant come first. */
    fun openItem(item: ItemOut) = openCard(item.cardId, item.printingId, Variant(item.language, item.finish, item.condition))

    fun openCard(cardId: Int, printingId: Int? = null, variant: Variant? = null) {
        val client = app.client.value ?: return
        detailsJob?.cancel()
        val id = ++detailsRequest
        _details.value = DetailsState(cardId, printingId, variant)
        detailsJob = sessionScope.launch {
            runCatchingCancellable { client.api.card(cardId) }
                .onSuccess { card ->
                    val first = printingId ?: card.defaultPrintingId
                    val printings = card.printings.sortedBy { if (it.id == first) 0 else 1 }
                    val ref = CardRef(card.id, card.gameId, card.name, card.colors, card.translation)
                    val candidate = CandidateOut(1.0, "manual", ref, printings, printings.size)
                    val shown = ScanState(
                        phase = Phase.RESULT,
                        result = IdentifyOut(card.gameId, HintsOut(), listOf(candidate)),
                        language = variant?.language,
                        finish = variant?.finish,
                        condition = variant?.condition,
                        lastFinish = _state.value.lastFinish,
                    )
                    if (id == detailsRequest) _details.update { it?.copy(card = shown, error = null) }
                }
                .onFailure { e -> if (id == detailsRequest) _details.update { it?.copy(error = e.userMessage(app)) } }
        }
    }

    fun retryDetails() {
        val d = _details.value ?: return
        openCard(d.cardId, d.printingId, d.variant)
    }

    fun closeDetails() {
        detailsJob?.cancel()
        detailsRequest++
        _details.value = null
    }

    private fun panel(panel: Panel): ScanState? = if (panel == Panel.SCAN) _state.value else _details.value?.card

    private fun updatePanel(panel: Panel, transform: (ScanState) -> ScanState) {
        if (panel == Panel.SCAN) {
            _state.update(transform)
        } else {
            _details.update { d -> d?.card?.let { d.copy(card = transform(it)) } ?: d }
        }
    }

    fun selectCandidate(panel: Panel, index: Int) = updatePanel(panel) { it.copy(candidate = index, printing = 0) }

    /** Show `printing`; one found by a search is added to the candidate's printings. */
    fun selectPrinting(panel: Panel, printing: PrintingOut) = updatePanel(panel) { s ->
        val result = s.result ?: return@updatePanel s
        val candidate = s.current ?: return@updatePanel s
        val index = candidate.printings.indexOfFirst { it.id == printing.id }
        if (index >= 0) return@updatePanel s.copy(printing = index)
        val grown = candidate.copy(printings = candidate.printings + printing)
        val candidates = result.candidates.toMutableList().also { it[s.candidate] = grown }
        s.copy(result = result.copy(candidates = candidates), printing = grown.printings.lastIndex)
    }

    /** Printings of a card beyond those a scan loaded (set name, code, number, year). */
    suspend fun searchPrintings(cardId: Int, query: String): List<PrintingOut> =
        app.client.value?.api?.printings(cardId, query) ?: emptyList()

    fun adjust(panel: Panel, finish: String, condition: String, language: String, delta: Int) {
        val state = panel(panel) ?: return
        val candidate = state.current ?: return
        val printing = candidate.printings.getOrNull(state.printing) ?: return
        change(AdjustIn(printing.id, finish, condition, language, delta), panel)
    }

    /** Quick +1 / -1 from the collection list. */
    fun adjustItem(item: ItemOut, delta: Int) =
        change(AdjustIn(item.printingId, item.finish, item.condition, item.language, delta, source = "web"), panel = null)

    private fun change(body: AdjustIn, panel: Panel?) {
        val client = app.client.value ?: return
        val delta = body.delta
        val manual = panel?.let(::panel)?.result?.candidates?.firstOrNull()?.match == "manual"
        panel?.let { updatePanel(it) { s -> s.copy(busy = true) } }
        sessionScope.launch {
            try {
                val out = client.api.adjust(body)
                val text = if (delta > 0) {
                    app.getString(R.string.added, delta, out.item.name, out.item.quantity)
                } else {
                    app.getString(R.string.removed, -delta, out.item.name, out.item.quantity)
                }
                _state.update {
                    it.copy(
                        undo = Undoable(out.transactionId, text),
                        stock = StockChange(it.stock.version + 1, out.item),
                        lastFinish = if (panel != null && delta > 0) body.finish else it.lastFinish,
                    )
                }
                if (panel == null) return@launch
                updatePanel(panel) { it.copy(busy = false) }
                if (panel == Panel.SCAN && autoNext && delta > 0 && !manual) {
                    resume()
                } else {
                    refreshCurrent(panel)
                }
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                panel?.let { updatePanel(it) { s -> s.copy(busy = false) } }
                _state.update { it.copy(message = e.userMessage(app)) }
            }
        }
    }

    fun undo() {
        val client = app.client.value ?: return
        val undo = _state.value.undo ?: return
        _state.update { it.copy(undo = null) }
        sessionScope.launch {
            runCatchingCancellable { client.api.undo(undo.transactionId) }
                .onSuccess { item ->
                    _state.update {
                        it.copy(message = app.getString(R.string.undone, item.name, item.quantity), stock = StockChange(it.stock.version + 1, item))
                    }
                    Panel.entries.forEach { refreshCurrent(it) }
                }
                .onFailure { e -> _state.update { it.copy(message = e.userMessage(app)) } }
        }
    }

    /** Reload owned copies of the card shown in [panel]. */
    private suspend fun refreshCurrent(panel: Panel) {
        val client = app.client.value ?: return
        val candidate = panel(panel)?.current ?: return
        val fresh = runCatchingCancellable { client.api.card(candidate.card.id) }.getOrNull() ?: return
        val byId = fresh.printings.associateBy { it.id }
        updatePanel(panel) { s ->
            val candidates = s.result?.candidates?.map { c ->
                if (c.card.id == candidate.card.id) c.copy(printings = c.printings.map { byId[it.id] ?: it }) else c
            }
            s.copy(result = s.result?.copy(candidates = candidates ?: s.result.candidates))
        }
    }

    /** Back to the camera. The same card is not identified again until it changes. */
    fun resume(forgetCard: Boolean = false) {
        synchronized(this) {
            readingSince = 0L
            request++ // an identify still running is no longer awaited
        }
        identifyJob?.cancel()
        identifyJob = null
        if (forgetCard) {
            synchronized(this) {
                stabilizer.reset()
                asianStabilizer.reset()
                recent.clear()
                recentAsian = null
            }
        }
        glare?.reset()
        _state.update { it.copy(phase = Phase.SCANNING, result = null, error = null, language = null, finish = null, condition = null, finishGuess = null) }
    }

    /** Another account or server: its work stops and nothing it showed stays. */
    private fun reset() {
        sessionJob.cancel()
        sessionJob = SupervisorJob(viewModelScope.coroutineContext[Job])
        identifyJob = null
        detailsJob = null
        synchronized(this) {
            request++
            detailsRequest++
            readingSince = 0L
            stabilizer.reset()
            asianStabilizer.reset()
            recent.clear()
            recentAsian = null
        }
        glare?.reset()
        _state.value = ScanState()
        _details.value = null
    }

    fun consumeMessage() = _state.update { it.copy(message = null) }

    fun consumeUndo() = _state.update { it.copy(undo = null) }
}
