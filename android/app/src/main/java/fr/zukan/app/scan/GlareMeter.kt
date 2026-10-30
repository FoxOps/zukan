package fr.zukan.app.scan

import java.nio.ByteBuffer

/**
 * Experimental (opt-in setting): guesses a holo or reverse holo finish from how light
 * moves on the card while it is held in the frame.
 *
 * Every card is glossy, but foil throws bright highlights that come and go as the card or
 * phone moves. Per frame, the share of near-white pixels is measured in the art window
 * and in the rest of the card (border, text area). Holo cards have foil in the art window,
 * reverse holo cards everywhere but there: the part whose highlights vary most over the
 * last frames tells which. Weak or even variation: no guess.
 *
 * Only the brightness plane is read, on a coarse grid: a few thousand pixels a frame.
 */
class GlareMeter {
    private val art = ArrayDeque<Double>()
    private val rest = ArrayDeque<Double>()

    @Synchronized
    fun reset() {
        art.clear()
        rest.clear()
    }

    /** The share of highlights in the art window and in the rest of the card, one frame. */
    @Synchronized
    fun offer(artBright: Double, restBright: Double) {
        art.addLast(artBright)
        rest.addLast(restBright)
        while (art.size > FRAMES) art.removeFirst()
        while (rest.size > FRAMES) rest.removeFirst()
    }

    /** One camera frame: [luma] is the Y plane ([width] x [height], [rowStride] bytes a
     * row), [rotation] the degrees that turn it upright. The card is taken where the
     * scanner's card frame is: centered, card shaped, most of the picture. */
    fun offer(luma: ByteBuffer, width: Int, height: Int, rowStride: Int, rotation: Int) {
        val quarter = rotation % 180 != 0
        val uprightWidth = if (quarter) height else width
        val uprightHeight = if (quarter) width else height
        val cardHeight = minOf(uprightHeight * 0.8, uprightWidth * 0.8 / CARD_RATIO)
        val cardWidth = cardHeight * CARD_RATIO
        val left = (uprightWidth - cardWidth) / 2
        val top = (uprightHeight - cardHeight) / 2
        var artCount = 0
        var artBright = 0
        var restCount = 0
        var restBright = 0
        for (row in 0 until GRID) {
            for (col in 0 until GRID) {
                val fx = (col + 0.5) / GRID
                val fy = (row + 0.5) / GRID
                val ux = (left + fx * cardWidth).toInt()
                val uy = (top + fy * cardHeight).toInt()
                // Upright point back to the sensor's picture.
                val (x, y) = when (rotation) {
                    90 -> uy to (height - 1 - ux)
                    180 -> (width - 1 - ux) to (height - 1 - uy)
                    270 -> (width - 1 - uy) to ux
                    else -> ux to uy
                }
                if (x !in 0 until width || y !in 0 until height) continue
                val bright = (luma.get(y * rowStride + x).toInt() and 0xFF) >= BRIGHT
                if (inArt(fx, fy)) {
                    artCount++
                    if (bright) artBright++
                } else {
                    restCount++
                    if (bright) restBright++
                }
            }
        }
        if (artCount > 0 && restCount > 0) offer(artBright.toDouble() / artCount, restBright.toDouble() / restCount)
    }

    /** "holo", "reverse" or null (not enough frames, or nothing telling). */
    @Synchronized
    fun guess(): String? = guess(art.toList(), rest.toList())

    companion object {
        private const val CARD_RATIO = 63.0 / 88.0
        private const val GRID = 48
        private const val BRIGHT = 235
        const val FRAMES = 8
        private const val MIN_FRAMES = 4
        // Highlights varying by less than this share of the area: an ordinary glossy card.
        private const val MIN_SWING = 0.02
        // One part varying this many times more than the other.
        private const val DOMINANT = 2.0

        /** The art window of most cards: under the name, above the text box. */
        fun inArt(fx: Double, fy: Double): Boolean = fx in 0.08..0.92 && fy in 0.10..0.52

        fun guess(art: List<Double>, rest: List<Double>): String? {
            if (art.size < MIN_FRAMES || rest.size < MIN_FRAMES) return null
            val artSwing = art.max() - art.min()
            val restSwing = rest.max() - rest.min()
            return when {
                maxOf(artSwing, restSwing) < MIN_SWING -> null
                artSwing >= restSwing * DOMINANT -> "holo"
                restSwing >= artSwing * DOMINANT -> "reverse"
                else -> null
            }
        }
    }
}
