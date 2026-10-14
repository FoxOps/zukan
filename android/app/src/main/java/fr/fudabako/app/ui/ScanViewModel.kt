package fr.fudabako.app.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import fr.fudabako.app.FudabakoApp
import fr.fudabako.app.R
import fr.fudabako.app.data.AdjustIn
import fr.fudabako.app.data.CandidateOut
import fr.fudabako.app.data.CardRef
import fr.fudabako.app.data.CardSummaryOut
import fr.fudabako.app.data.HintsOut
import fr.fudabako.app.data.IdentifyIn
import fr.fudabako.app.data.IdentifyOut
import fr.fudabako.app.data.OcrLineIn
import fr.fudabako.app.data.userMessage
import fr.fudabako.app.scan.ScanStabilizer
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

enum class Phase { SCANNING, IDENTIFYING, RESULT, NOT_FOUND }

data class Undoable(val transactionId: Int, val text: String)

data class ScanState(
    val phase: Phase = Phase.SCANNING,
    val result: IdentifyOut? = null,
    val candidate: Int = 0,
    val printing: Int = 0,
    val busy: Boolean = false,
    val message: String? = null,
    val undo: Undoable? = null,
    // Bumped after every stock change, so lists of owned cards reload.
    val stockVersion: Int = 0,
) {
    val current: CandidateOut? get() = result?.candidates?.getOrNull(candidate)
}

/** Scan flow: steady OCR text -> identify -> pick printing/variant -> add or remove. */
class ScanViewModel(application: Application) : AndroidViewModel(application) {
    private val app = application as FudabakoApp
    private val stabilizer = ScanStabilizer()
    private val _state = MutableStateFlow(ScanState())
    val state: StateFlow<ScanState> = _state.asStateFlow()
    var game: String? = null
    // Back to the camera after adding copies (setting "after adding").
    var autoNext = false

    val scanning get() = _state.value.phase == Phase.SCANNING

    /** Called from the camera analysis thread for every frame: true when the card is
     * steady and new, so the frame is read for identification. */
    @Synchronized
    fun onFrame(lines: List<OcrLineIn>): Boolean = scanning && stabilizer.offer(lines.map { it.text })

    fun identify(lines: List<OcrLineIn>) {
        val client = app.client.value ?: return
        _state.update { it.copy(phase = Phase.IDENTIFYING, message = null) }
        viewModelScope.launch {
            runCatching { client.api.identify(IdentifyIn(game, lines)) }
                .onSuccess { result ->
                    _state.update {
                        it.copy(
                            phase = if (result.candidates.isEmpty()) Phase.NOT_FOUND else Phase.RESULT,
                            result = result,
                            candidate = 0,
                            printing = 0,
                        )
                    }
                }
                .onFailure { e -> _state.update { it.copy(phase = Phase.SCANNING, message = e.userMessage(app)) } }
        }
    }

    /** Show a card picked by hand (search or collection screen) in the result panel,
     * `printingId` first when given. */
    fun showCard(summary: CardSummaryOut) = showCard(summary.id)

    fun showCard(cardId: Int, printingId: Int? = null) {
        val client = app.client.value ?: return
        viewModelScope.launch {
            runCatching { client.api.card(cardId) }
                .onSuccess { card ->
                    val printings = card.printings.sortedBy { if (it.id == printingId) 0 else 1 }
                    val candidate = CandidateOut(1.0, "manual", CardRef(card.id, card.gameId, card.name, card.colors), printings)
                    _state.update {
                        ScanState(
                            phase = Phase.RESULT,
                            result = IdentifyOut(card.gameId, HintsOut(), listOf(candidate)),
                            undo = it.undo,
                            stockVersion = it.stockVersion,
                        )
                    }
                }
                .onFailure { e -> _state.update { it.copy(message = e.userMessage(app)) } }
        }
    }

    fun selectCandidate(index: Int) = _state.update { it.copy(candidate = index, printing = 0) }

    fun selectPrinting(index: Int) = _state.update { it.copy(printing = index) }

    fun adjust(finish: String, condition: String, language: String, delta: Int) {
        val state = _state.value
        val candidate = state.current ?: return
        val printing = candidate.printings.getOrNull(state.printing) ?: return
        change(AdjustIn(printing.id, finish, condition, language, delta), fromPanel = true)
    }

    /** Quick +1 / -1 from the collection list. */
    fun adjustItem(printingId: Int, finish: String, condition: String, language: String, delta: Int) =
        change(AdjustIn(printingId, finish, condition, language, delta, source = "web"), fromPanel = false)

    private fun change(body: AdjustIn, fromPanel: Boolean) {
        val client = app.client.value ?: return
        val state = _state.value
        val delta = body.delta
        _state.update { it.copy(busy = true) }
        viewModelScope.launch {
            try {
                val out = client.api.adjust(body)
                val text = if (delta > 0) {
                    app.getString(R.string.added, delta, out.item.name, out.item.quantity)
                } else {
                    app.getString(R.string.removed, -delta, out.item.name, out.item.quantity)
                }
                _state.update { it.copy(busy = false, undo = Undoable(out.transactionId, text), stockVersion = it.stockVersion + 1) }
                if (!fromPanel) return@launch
                if (autoNext && delta > 0 && state.result?.candidates?.firstOrNull()?.match != "manual") {
                    resume()
                } else {
                    refreshCurrent()
                }
            } catch (e: Exception) {
                _state.update { it.copy(busy = false, message = e.userMessage(app)) }
            }
        }
    }

    fun undo() {
        val client = app.client.value ?: return
        val undo = _state.value.undo ?: return
        _state.update { it.copy(undo = null) }
        viewModelScope.launch {
            runCatching { client.api.undo(undo.transactionId) }
                .onSuccess { item ->
                    _state.update {
                        it.copy(message = app.getString(R.string.undone, item.name, item.quantity), stockVersion = it.stockVersion + 1)
                    }
                    refreshCurrent()
                }
                .onFailure { e -> _state.update { it.copy(message = e.userMessage(app)) } }
        }
    }

    /** Reload owned copies of the card shown in the panel. */
    private suspend fun refreshCurrent() {
        val client = app.client.value ?: return
        val candidate = _state.value.current ?: return
        val fresh = runCatching { client.api.card(candidate.card.id) }.getOrNull() ?: return
        val byId = fresh.printings.associateBy { it.id }
        _state.update { s ->
            val candidates = s.result?.candidates?.map { c ->
                if (c.card.id == candidate.card.id) c.copy(printings = c.printings.map { byId[it.id] ?: it }) else c
            }
            s.copy(result = s.result?.copy(candidates = candidates ?: s.result.candidates))
        }
    }

    /** Back to the camera. The same card is not identified again until it changes. */
    fun resume(forgetCard: Boolean = false) {
        if (forgetCard) stabilizer.reset()
        _state.update { it.copy(phase = Phase.SCANNING, result = null) }
    }

    fun consumeMessage() = _state.update { it.copy(message = null) }

    fun consumeUndo() = _state.update { it.copy(undo = null) }
}
