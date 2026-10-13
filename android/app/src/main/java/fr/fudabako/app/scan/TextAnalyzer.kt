package fr.fudabako.app.scan

import android.graphics.Rect
import androidx.annotation.OptIn
import androidx.camera.core.ExperimentalGetImage
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import com.google.mlkit.vision.common.InputImage
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
        OcrScript.LATIN -> TextRecognizerOptions.DEFAULT_OPTIONS
        OcrScript.JAPANESE -> JapaneseTextRecognizerOptions.Builder().build()
        OcrScript.CHINESE -> ChineseTextRecognizerOptions.Builder().build()
        OcrScript.KOREAN -> KoreanTextRecognizerOptions.Builder().build()
    },
)

/**
 * Runs on-device text recognition on camera frames (one at a time, newest frame wins)
 * and reports lines with boxes relative to the text area, which approximates the card.
 */
class TextAnalyzer(
    private val recognizer: TextRecognizer,
    private val onLines: (List<OcrLineIn>) -> Unit,
) : ImageAnalysis.Analyzer {
    @Volatile
    var paused = false

    @OptIn(ExperimentalGetImage::class)
    override fun analyze(proxy: ImageProxy) {
        val image = proxy.image
        if (paused || image == null) {
            proxy.close()
            return
        }
        val input = InputImage.fromMediaImage(image, proxy.imageInfo.rotationDegrees)
        recognizer.process(input)
            .addOnSuccessListener { text ->
                val lines = text.textBlocks.flatMap { it.lines }.mapNotNull { line ->
                    line.boundingBox?.let { box -> line.text to box }
                }
                onLines(relativeToText(lines))
            }
            .addOnCompleteListener { proxy.close() }
    }

    companion object {
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
