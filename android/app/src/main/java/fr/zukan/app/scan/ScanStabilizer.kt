package fr.zukan.app.scan

import fr.zukan.app.data.OcrLineIn

/**
 * Decides when the camera sees one card steadily enough to ask the server.
 *
 * Text read from successive frames is compared as sets of normalized words; a frame is
 * "stable" once [framesNeeded] frames in a row are similar. The same card is not sent
 * twice until something clearly different has been seen.
 *
 * Glare on holo and reverse holo cards changes much of the text from frame to frame: a
 * frame also counts as the same card when it shares the collector number ("022/132") with
 * any of the last [WINDOW] frames, and a frame where glare hid that number neither counts
 * nor breaks the run. A steady card whose number was not read yet waits a few frames
 * ([NUMBER_WAIT]) for a frame that has it, the most telling line.
 */
class ScanStabilizer(
    private val framesNeeded: Int = 3,
    private val similar: Double = 0.6,
    private val minWords: Int = 2,
) {
    private val window = ArrayDeque<Set<String>>()
    private var streak = 0
    private var waited = 0
    private var lastSent: Set<String> = emptySet()

    /** Returns true when this frame should be identified. */
    fun offer(lines: List<String>): Boolean {
        val words = words(lines)
        if (words.size < minWords) {
            streak = 0
            waited = 0
            window.clear()
            return false
        }
        val numbers = numbers(words)
        val seen = window.flatMapTo(HashSet(), ::numbers)
        // Another collector number: another card, older frames no longer count.
        val otherCard = numbers.isNotEmpty() && seen.isNotEmpty() && numbers.none { it in seen }
        if (otherCard) window.clear()
        val previous = window.lastOrNull()
        val sameCard = previous != null && (jaccard(words, previous) >= similar || numbers.any { it in seen })
        streak = when {
            sameCard -> streak + 1
            // Glare hid the number of the card seen so far: this frame neither counts nor
            // breaks the run.
            numbers.isEmpty() && seen.isNotEmpty() -> streak
            else -> 1
        }
        window.addLast(words)
        while (window.size > WINDOW) window.removeFirst()
        if (streak < framesNeeded) return false
        if (lastSent.isNotEmpty() && (jaccard(words, lastSent) >= similar || sameNumber(words, lastSent))) return false
        if (window.none(::hasNumber) && waited < NUMBER_WAIT) {
            waited++
            return false
        }
        waited = 0
        lastSent = words
        return true
    }

    /** Forget the last card, e.g. when the user wants to scan the same card again. */
    fun reset() {
        lastSent = emptySet()
        streak = 0
        waited = 0
        window.clear()
    }

    companion object {
        /** Frames compared with the current one. */
        const val WINDOW = 4
        /** Steady frames waited for the collector number before sending without it (games
         * that print none, Yu-Gi-Oh! or Sorcery, only wait this long). */
        const val NUMBER_WAIT = 3

        private val cjk = Regex("""[\p{IsHan}\p{IsHiragana}\p{IsKatakana}\p{IsHangul}]""")

        /** Normalized words; unspaced Japanese, Korean and Chinese text is cut into pairs
         * of characters, so one misread glyph does not change the whole line. */
        fun words(lines: List<String>): Set<String> = lines
            .flatMap { it.lowercase().split(Regex("""[^\p{L}\p{N}/]+""")) }
            .flatMap { if (it.length > 2 && cjk.containsMatchIn(it)) it.windowed(2) else listOf(it) }
            .filter { it.length >= 2 }
            .toSet()

        private val number = Regex("""\d{1,3}/\d{2,3}""")
        private val numberInLine = Regex("""\d{1,3}\s*/\s*\d{2,3}""")

        fun hasNumber(words: Set<String>): Boolean = words.any { number.matches(it) }

        private fun numbers(words: Set<String>): List<String> = words.filter { number.matches(it) }

        fun sameNumber(a: Set<String>, b: Set<String>): Boolean =
            a.any { number.matches(it) && it in b }

        fun jaccard(a: Set<String>, b: Set<String>): Double {
            if (a.isEmpty() || b.isEmpty()) return 0.0
            return a.intersect(b).size.toDouble() / a.union(b).size
        }

        /** [lines], plus the collector number lines of the latest of [recent] frames that
         * read one, when [lines] has none (glare hid it in this frame). */
        fun withNumberLine(lines: List<OcrLineIn>, recent: List<List<OcrLineIn>>): List<OcrLineIn> {
            if (lines.any { numberInLine.containsMatchIn(it.text) }) return lines
            val found = recent.asReversed()
                .firstNotNullOfOrNull { frame -> frame.filter { numberInLine.containsMatchIn(it.text) }.ifEmpty { null } }
                ?: return lines
            return lines + found
        }
    }
}
