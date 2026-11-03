package fr.zukan.app.scan

import java.nio.ByteBuffer
import kotlin.math.roundToInt

/**
 * A grayscale picture around the text of a card, sent with its text so the server can
 * compare the set symbol (right of the type line, past the text) with set icons: old
 * Magic cards print no set code.
 *
 * [box] is where the picture lies in the frame of the lines' boxes (fractions of the
 * text area): left, top, right, bottom, past 0..1 for the margin around the text.
 */
class ScanPicture(val width: Int, val height: Int, val pixels: ByteArray, val box: List<Float>) {
    companion object {
        // Margin around the text, as a share of its size: the symbol and the card edge.
        const val MARGIN_X = 0.25f
        const val MARGIN_Y = 0.06f
        // Largest picture sent (pixels), enough for a symbol a few dozen pixels wide.
        const val MAX_WIDTH = 640
        const val MAX_HEIGHT = 900

        /**
         * The upright picture around [text] (left, top, right, bottom in upright pixels).
         * [luma] is the Y plane ([width] x [height], [rowStride] bytes a row) and
         * [rotation] the degrees that turn it upright, as for [GlareMeter.offer].
         */
        fun crop(
            luma: ByteBuffer,
            width: Int,
            height: Int,
            rowStride: Int,
            rotation: Int,
            text: IntArray,
        ): ScanPicture? {
            val (textLeft, textTop, textRight, textBottom) = text.toList()
            val textWidth = (textRight - textLeft).toFloat()
            val textHeight = (textBottom - textTop).toFloat()
            if (textWidth < 1 || textHeight < 1) return null
            val quarter = rotation % 180 != 0
            val uprightWidth = if (quarter) height else width
            val uprightHeight = if (quarter) width else height
            val left = (textLeft - textWidth * MARGIN_X).roundToInt().coerceIn(0, uprightWidth)
            val right = (textRight + textWidth * MARGIN_X).roundToInt().coerceIn(0, uprightWidth)
            val top = (textTop - textHeight * MARGIN_Y).roundToInt().coerceIn(0, uprightHeight)
            val bottom = (textBottom + textHeight * MARGIN_Y).roundToInt().coerceIn(0, uprightHeight)
            if (right - left < 8 || bottom - top < 8) return null
            val scale = minOf(1f, MAX_WIDTH.toFloat() / (right - left), MAX_HEIGHT.toFloat() / (bottom - top))
            val outWidth = ((right - left) * scale).roundToInt().coerceAtLeast(1)
            val outHeight = ((bottom - top) * scale).roundToInt().coerceAtLeast(1)
            val pixels = ByteArray(outWidth * outHeight)
            for (oy in 0 until outHeight) {
                val uy = (top + (oy + 0.5f) / scale).toInt().coerceIn(0, uprightHeight - 1)
                for (ox in 0 until outWidth) {
                    val ux = (left + (ox + 0.5f) / scale).toInt().coerceIn(0, uprightWidth - 1)
                    // Upright point back to the sensor's picture.
                    val (x, y) = when (rotation) {
                        90 -> uy to (height - 1 - ux)
                        180 -> (width - 1 - ux) to (height - 1 - uy)
                        270 -> (width - 1 - uy) to ux
                        else -> ux to uy
                    }
                    pixels[oy * outWidth + ox] = luma.get(y * rowStride + x)
                }
            }
            val box = listOf(
                (left - textLeft) / textWidth,
                (top - textTop) / textHeight,
                (right - textLeft) / textWidth,
                (bottom - textTop) / textHeight,
            )
            return ScanPicture(outWidth, outHeight, pixels, box)
        }
    }
}
