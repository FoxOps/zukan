package fr.fudabako.app.scan

/**
 * Decides when the camera sees one card steadily enough to ask the server.
 *
 * Text read from successive frames is compared as sets of normalized words; a frame is
 * "stable" once [framesNeeded] frames in a row are similar. The same card is not sent
 * twice until something clearly different has been seen.
 */
class ScanStabilizer(
    private val framesNeeded: Int = 3,
    private val similar: Double = 0.6,
    private val minWords: Int = 2,
) {
    private var previous: Set<String> = emptySet()
    private var streak = 0
    private var lastSent: Set<String> = emptySet()

    /** Returns true when this frame should be identified. */
    fun offer(lines: List<String>): Boolean {
        val words = words(lines)
        if (words.size < minWords) {
            streak = 0
            previous = emptySet()
            return false
        }
        streak = if (jaccard(words, previous) >= similar) streak + 1 else 1
        previous = words
        if (streak < framesNeeded) return false
        if (lastSent.isNotEmpty() && jaccard(words, lastSent) >= similar) return false
        lastSent = words
        return true
    }

    /** Forget the last card, e.g. when the user wants to scan the same card again. */
    fun reset() {
        lastSent = emptySet()
        streak = 0
        previous = emptySet()
    }

    companion object {
        private val cjk = Regex("""[\p{IsHan}\p{IsHiragana}\p{IsKatakana}\p{IsHangul}]""")

        /** Normalized words; unspaced Japanese, Korean and Chinese text is cut into pairs
         * of characters, so one misread glyph does not change the whole line. */
        fun words(lines: List<String>): Set<String> = lines
            .flatMap { it.lowercase().split(Regex("""[^\p{L}\p{N}/]+""")) }
            .flatMap { if (it.length > 2 && cjk.containsMatchIn(it)) it.windowed(2) else listOf(it) }
            .filter { it.length >= 2 }
            .toSet()

        fun jaccard(a: Set<String>, b: Set<String>): Double {
            if (a.isEmpty() || b.isEmpty()) return 0.0
            return a.intersect(b).size.toDouble() / a.union(b).size
        }
    }
}
