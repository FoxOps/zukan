package fr.zukan.app.scan

import android.graphics.Rect
import android.util.Log
import androidx.annotation.OptIn
import androidx.camera.core.ExperimentalGetImage
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import com.google.android.gms.tasks.Tasks
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.Text
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.TextRecognizer
import com.google.mlkit.vision.text.chinese.ChineseTextRecognizerOptions
import com.google.mlkit.vision.text.japanese.JapaneseTextRecognizerOptions
import com.google.mlkit.vision.text.korean.KoreanTextRecognizerOptions
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import fr.zukan.app.data.OcrLineIn
import fr.zukan.app.data.OcrScript
import java.util.concurrent.TimeUnit

fun recognizer(script: OcrScript): TextRecognizer = TextRecognition.getClient(
    when (script) {
        // Each non-Latin model also reads Latin text.
        OcrScript.AUTO, OcrScript.LATIN -> TextRecognizerOptions.DEFAULT_OPTIONS
        OcrScript.JAPANESE -> JapaneseTextRecognizerOptions.Builder().build()
        OcrScript.CHINESE -> ChineseTextRecognizerOptions.Builder().build()
        OcrScript.KOREAN -> KoreanTextRecognizerOptions.Builder().build()
    },
)

/**
 * Runs on-device text recognition on camera frames (one at a time, newest frame wins)
 * and reports lines with boxes relative to the text area, which approximates the card.
 *
 * Every frame is read with the chosen model and offered to [onFrame], which tells
 * whether the card is steady enough to identify. In [OcrScript.AUTO] mode the Latin
 * model reads the frames; the frame to identify is then read by every Asian model too
 * and the best fitting reading ([ScriptPicker]) goes to [onIdentify].
 *
 * The Latin model reads little but noise on Japanese, Korean or Chinese cards, so it may
 * never find them steady: in AUTO mode every [ASIAN_EVERY]th frame is also read by one
 * Asian model (the last one that found its script, else each in turn) and offered to
 * [onAsianFrame], with its own steadiness check. Once a model has found its script it
 * reads every frame until it stops finding it ([ASIAN_STREAK] misses), and the Japanese
 * model reading only Han characters ([KANJI_ONLY_FRAMES] in a row) hands over to the
 * Chinese one. A card taken away ([EMPTY_FRAMES] without text) starts over with Japanese.
 *
 * Landscape cards held upright put their text sideways: when the reading runs sideways
 * or stays weak, the frame is also read turned by a quarter ([CardTurn]) and the best
 * turn is kept for the next frames.
 *
 * At most one frame every [MIN_FRAME_MS] is read (about 6 a second): enough to find a
 * card steady, without keeping the processor busy.
 */
class TextAnalyzer(
    private val script: OcrScript,
    private val onFrame: (List<OcrLineIn>) -> Boolean,
    private val onIdentify: (List<OcrLineIn>, ScanPicture?) -> Unit,
    private val onAsianFrame: (List<OcrLineIn>) -> Boolean = { false },
    // Experimental finish guess, when on: fed with every frame read.
    private val glare: () -> GlareMeter? = { null },
    // Whether a picture around the text goes with it (games with set symbols to compare).
    private val wantPicture: () -> Boolean = { false },
) : ImageAnalysis.Analyzer {
    @Volatile
    var paused = false

    private val main = recognizer(script)
    // Asian models, each loaded the first time it is needed (each holds its own model).
    private val others = mutableMapOf<OcrScript, TextRecognizer>()

    private fun other(script: OcrScript): TextRecognizer = synchronized(others) { others.getOrPut(script) { recognizer(script) } }
    private var frames = 0
    private var asian = OcrScript.JAPANESE
    // Frames the current Asian model still reads one after the other.
    private var asianStreak = 0
    // Frames in a row the Japanese model read Han characters without kana.
    private var kanjiOnlyFrames = 0
    // Frames in a row without any text: the card was taken away.
    private var emptyFrames = 0
    // Quarter turns added to the camera's rotation (landscape cards), and weak frames.
    private var turn = 0
    private var weakFrames = 0
    private var lastFrame = 0L

    @OptIn(ExperimentalGetImage::class)
    override fun analyze(proxy: ImageProxy) {
        val image = proxy.image
        val now = android.os.SystemClock.elapsedRealtime()
        if (paused || image == null || now - lastFrame < MIN_FRAME_MS) {
            proxy.close()
            return
        }
        lastFrame = now
        // Runs on the analysis thread: ML Kit tasks are awaited, so the frame stays open
        // until every model has read it.
        try {
            val rotation = proxy.imageInfo.rotationDegrees
            var input = InputImage.fromMediaImage(image, (rotation + turn) % 360)
            var text = await(main.process(input))
            if (shouldTurn(text)) {
                // Read the frame at every turn and keep the best one.
                val readings = CardTurn.TURNS.associateWith { extra ->
                    if (extra == turn) {
                        input to text
                    } else {
                        val turned = InputImage.fromMediaImage(image, (rotation + extra) % 360)
                        turned to await(main.process(turned))
                    }
                }
                val best = CardTurn.best(turn, readings.mapValues { (_, r) -> CardTurn.score(reads(r.second)) })
                if (best != turn) Log.d(TAG, "Reading frames turned by $best°")
                turn = best
                input = readings.getValue(best).first
                text = readings.getValue(best).second
                weakFrames = 0
            }
            val lines = toLines(text)
            if (lines.isEmpty()) {
                // No card in view for a while: the next one starts with the Japanese model
                // (a Chinese card scanned before must not make it read the next one).
                if (++emptyFrames >= EMPTY_FRAMES) forgetScript()
            } else {
                emptyFrames = 0
            }
            glare()?.let { meter ->
                val plane = proxy.planes[0]
                meter.offer(plane.buffer, proxy.width, proxy.height, plane.rowStride, rotation)
            }
            // An Asian set code read by the Latin model ("SV6a", "M6a"): the Asian models
            // read the next frames.
            if (script == OcrScript.AUTO && lines.any { ASIAN_CODE.containsMatchIn(it.text) }) asianStreak = ASIAN_STREAK
            if (!onFrame(lines)) {
                if (script == OcrScript.AUTO && (asianStreak > 0 || ++frames % ASIAN_EVERY == 0)) readAsian(input)
                return
            }
            val total = (rotation + turn) % 360
            if (script != OcrScript.AUTO) {
                onIdentify(lines, picture(proxy, total, text))
                return
            }
            // This frame passed the stabilizer: an Asian model failing must not lose it (the
            // card would count as sent and never be asked for).
            val readings = try {
                ASIAN.associateWith { await(other(it).process(input)) }
            } catch (e: Exception) {
                Log.w(TAG, "Asian text recognition failed, sending the Latin reading", e)
                emptyMap()
            }
            val best = ScriptPicker.pick(readings.mapValues { (_, t) -> toLines(t).map { it.text } } + (OcrScript.LATIN to lines.map { it.text }))
            val chosen = readings[best] ?: text
            onIdentify(if (chosen === text) lines else toLines(chosen), picture(proxy, total, chosen))
        } catch (e: Exception) {
            // A failed recognition only loses this frame.
            Log.w(TAG, "Text recognition failed", e)
        } finally {
            proxy.close()
        }
    }

    /** Sideways text, or a weak reading for a while: worth reading other turns. */
    private fun shouldTurn(text: Text): Boolean {
        val read = reads(text)
        if (CardTurn.sideways(read)) return true
        // Nothing read at all: no card in view, nothing to turn.
        if (!CardTurn.weak(read) || read.isEmpty()) {
            weakFrames = 0
            return false
        }
        return ++weakFrames >= CardTurn.WEAK_FRAMES
    }

    /** One Asian model reads the frame; a steady reading is identified. */
    private fun readAsian(input: InputImage) {
        val lines = toLines(await(other(asian).process(input)))
        val texts = lines.map { it.text }
        val found = ScriptPicker.pick(mapOf(asian to texts))
        // Han characters without kana: Chinese more likely than kanji-only Japanese, when
        // it lasts (one blurred frame often loses the kana).
        val kanjiOnly = asian == OcrScript.JAPANESE && found == OcrScript.JAPANESE && !ScriptPicker.hasKana(texts)
        kanjiOnlyFrames = if (kanjiOnly) kanjiOnlyFrames + 1 else 0
        if (found != asian || kanjiOnlyFrames >= KANJI_ONLY_FRAMES) {
            // Not this script: try the next model (from Japanese reading Han: Chinese).
            asian = if (kanjiOnly) OcrScript.CHINESE else ASIAN[(ASIAN.indexOf(asian) + 1) % ASIAN.size]
            asianStreak = (asianStreak - 1).coerceAtLeast(0)
            kanjiOnlyFrames = 0
            return
        }
        if (kanjiOnly) return
        asianStreak = ASIAN_STREAK
        if (onAsianFrame(lines)) onIdentify(lines, null)
    }

    private fun forgetScript() {
        asian = OcrScript.JAPANESE
        asianStreak = 0
        kanjiOnlyFrames = 0
    }

    /** The picture around the text of [text] (read at [rotation]), when wanted. */
    private fun picture(proxy: ImageProxy, rotation: Int, text: Text): ScanPicture? {
        if (!wantPicture()) return null
        val boxes = text.textBlocks.flatMap { it.lines }.mapNotNull { it.boundingBox }
        if (boxes.isEmpty()) return null
        val bounds = intArrayOf(boxes.minOf { it.left }, boxes.minOf { it.top }, boxes.maxOf { it.right }, boxes.maxOf { it.bottom })
        val plane = proxy.planes[0]
        // Only lose the picture on failure, never the text.
        return runCatching {
            ScanPicture.crop(plane.buffer, proxy.width, proxy.height, plane.rowStride, rotation, bounds)
        }.onFailure { Log.w(TAG, "No picture of the card", it) }.getOrNull()
    }

    /** A recognition result; a model that hangs (seen on old phones) loses the frame
     * instead of blocking every later one. */
    private fun <T> await(task: com.google.android.gms.tasks.Task<T>): T = Tasks.await(task, AWAIT_SECONDS, TimeUnit.SECONDS)

    fun close() {
        main.close()
        synchronized(others) {
            others.values.forEach { it.close() }
            others.clear()
        }
    }

    companion object {
        private const val TAG = "TextAnalyzer"
        const val ASIAN_EVERY = 3
        const val ASIAN_STREAK = 3
        const val MIN_FRAME_MS = 160L
        const val KANJI_ONLY_FRAMES = 2
        const val EMPTY_FRAMES = 6
        const val AWAIT_SECONDS = 10L
        // Japanese-style set codes ("SV6a", "M6a", "S12a", "CSV9C") before a number.
        private val ASIAN_CODE = Regex("""\b(?:SV|S|SM|M|CS|CSV)\d{1,2}[a-zA-Z]{1,2}\s*\d{1,3}\s*/""")
        private val ASIAN = listOf(OcrScript.JAPANESE, OcrScript.KOREAN, OcrScript.CHINESE)

        private fun reads(text: Text): List<CardTurn.Read> =
            text.textBlocks.flatMap { it.lines }.map { CardTurn.Read(it.text, it.angle) }

        private fun toLines(text: Text): List<OcrLineIn> = relativeToText(
            text.textBlocks.flatMap { it.lines }.mapNotNull { line -> line.boundingBox?.let { box -> line.text to box } },
        )

        fun relativeToText(lines: List<Pair<String, Rect>>): List<OcrLineIn> {
            if (lines.isEmpty()) return emptyList()
            val left = lines.minOf { it.second.left }
            val top = lines.minOf { it.second.top }
            val width = (lines.maxOf { it.second.right } - left).coerceAtLeast(1).toFloat()
            val height = (lines.maxOf { it.second.bottom } - top).coerceAtLeast(1).toFloat()
            return lines.map { (text, box) ->
                OcrLineIn(
                    text = text,
                    left = ((box.left - left) / width).coerceIn(0f, 1f),
                    top = ((box.top - top) / height).coerceIn(0f, 1f),
                    width = (box.width() / width).coerceIn(0f, 1f),
                    height = (box.height() / height).coerceIn(0f, 1f),
                )
            }
        }
    }
}
