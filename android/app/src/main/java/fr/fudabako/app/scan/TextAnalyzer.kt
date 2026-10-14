package fr.fudabako.app.scan

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
import fr.fudabako.app.data.OcrLineIn
import fr.fudabako.app.data.OcrScript

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
 * [onAsianFrame], with its own steadiness check.
 */
class TextAnalyzer(
    private val script: OcrScript,
    private val onFrame: (List<OcrLineIn>) -> Boolean,
    private val onIdentify: (List<OcrLineIn>) -> Unit,
    private val onAsianFrame: (List<OcrLineIn>) -> Boolean = { false },
) : ImageAnalysis.Analyzer {
    @Volatile
    var paused = false

    private val main = recognizer(script)
    private val others: Map<OcrScript, TextRecognizer> by lazy {
        ASIAN.associateWith(::recognizer)
    }
    private var frames = 0
    private var asian = OcrScript.JAPANESE

    @OptIn(ExperimentalGetImage::class)
    override fun analyze(proxy: ImageProxy) {
        val image = proxy.image
        if (paused || image == null) {
            proxy.close()
            return
        }
        // Runs on the analysis thread: ML Kit tasks are awaited, so the frame stays open
        // until every model has read it.
        try {
            val input = InputImage.fromMediaImage(image, proxy.imageInfo.rotationDegrees)
            val lines = toLines(Tasks.await(main.process(input)))
            if (!onFrame(lines)) {
                if (script == OcrScript.AUTO && ++frames % ASIAN_EVERY == 0) readAsian(input)
                return
            }
            if (script != OcrScript.AUTO) {
                onIdentify(lines)
                return
            }
            val readings = others.mapValues { (_, model) -> toLines(Tasks.await(model.process(input))) }
            val best = ScriptPicker.pick(readings.mapValues { (_, l) -> l.map { it.text } } + (OcrScript.LATIN to lines.map { it.text }))
            onIdentify(readings[best] ?: lines)
        } catch (e: Exception) {
            // A failed recognition only loses this frame.
            Log.w(TAG, "Text recognition failed", e)
        } finally {
            proxy.close()
        }
    }

    /** One Asian model reads the frame; a steady reading is identified. */
    private fun readAsian(input: InputImage) {
        val lines = toLines(Tasks.await(others.getValue(asian).process(input)))
        val found = ScriptPicker.pick(mapOf(asian to lines.map { it.text }))
        if (found != asian) {
            // Not this script: try the next model on the next round.
            asian = ASIAN[(ASIAN.indexOf(asian) + 1) % ASIAN.size]
            return
        }
        if (onAsianFrame(lines)) onIdentify(lines)
    }

    fun close() {
        main.close()
        if (script == OcrScript.AUTO) others.values.forEach { it.close() }
    }

    companion object {
        private const val TAG = "TextAnalyzer"
        const val ASIAN_EVERY = 3
        private val ASIAN = listOf(OcrScript.JAPANESE, OcrScript.KOREAN, OcrScript.CHINESE)

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
