package fr.zukan.app.scan

import kotlin.math.abs

/**
 * Landscape cards (Sorcery sites, some Pokémon and MTG cards) held in a portrait frame put
 * their text sideways, which text recognition reads badly. Decides when to read a frame
 * turned by a quarter, and which turn reads best.
 */
object CardTurn {
    /** Extra rotations tried, in degrees, besides the current one. */
    val TURNS = listOf(0, 90, 270)

    // A sideways reading: most lines tilted beyond this many degrees.
    private const val SIDEWAYS = 50f
    // Fewer letters than this: nothing usable was read.
    private const val FEW_LETTERS = 12
    // Weak frames in a row before other turns are tried anyway.
    const val WEAK_FRAMES = 6

    /** Lines with their angle (degrees) as text recognition returns them. */
    data class Read(val text: String, val angle: Float)

    /** Most lines (weighted by length) are tilted: the text runs sideways in the frame. */
    fun sideways(lines: List<Read>): Boolean {
        val weighted = lines.filter { it.text.length >= 3 }
        if (weighted.isEmpty()) return false
        val tilted = weighted.filter { abs(it.angle) > SIDEWAYS }.sumOf { it.text.length }
        return tilted * 2 > weighted.sumOf { it.text.length }
    }

    /** Letters on upright lines: how well a reading went. */
    fun score(lines: List<Read>): Int =
        lines.filter { abs(it.angle) <= SIDEWAYS }.sumOf { line -> line.text.count { it.isLetter() } }

    fun weak(lines: List<Read>): Boolean = score(lines) < FEW_LETTERS

    /** The turn whose reading scored best; the current one keeps ties. */
    fun best(current: Int, scores: Map<Int, Int>): Int {
        val top = scores.maxByOrNull { it.value } ?: return current
        return if (top.value > (scores[current] ?: 0)) top.key else current
    }
}
