package fr.zukan.app

import fr.zukan.app.scan.ScanStabilizer
import org.junit.Assert.assertEquals
import org.junit.Test

class ScanStabilizerTest {
    private val elves = listOf("Elfes de Llanowar", "Créature : elfe et druide", "168/269 C", "DOM • FR")
    private val delver = listOf("Delver of Secrets", "Creature — Human Wizard", "51/264")

    private fun ScanStabilizer.run(vararg frames: List<String>) = frames.map { offer(it) }

    @Test
    fun sendsOnceAfterSteadyFrames() {
        val stabilizer = ScanStabilizer(framesNeeded = 3)
        assertEquals(listOf(false, false, true, false, false), stabilizer.run(elves, elves, elves, elves, elves))
    }

    @Test
    fun noisyFramesStillCountAsTheSameCard() {
        val noisy = listOf("Elfes de Llanowar", "Creature elfe et druide", "168/269 C")
        val stabilizer = ScanStabilizer(framesNeeded = 3)
        assertEquals(listOf(false, false, true), stabilizer.run(elves, noisy, elves))
    }

    @Test
    fun nextCardIsSentAndSameCardNeedsReset() {
        val stabilizer = ScanStabilizer(framesNeeded = 2)
        assertEquals(listOf(false, true, false, true), stabilizer.run(elves, elves, delver, delver))
        assertEquals(listOf(false, true), stabilizer.run(elves, elves))
        assertEquals(listOf(false, false), stabilizer.run(elves, elves)) // already sent
        stabilizer.reset()
        assertEquals(listOf(false, true), stabilizer.run(elves, elves))
    }

    @Test
    fun ignoresFramesWithoutText() {
        val stabilizer = ScanStabilizer(framesNeeded = 2)
        assertEquals(listOf(false, false, false), stabilizer.run(emptyList(), listOf("a"), emptyList()))
    }

    @Test
    fun asianLinesSurviveOneMisreadGlyph() {
        // Unspaced text: one wrong glyph changed the whole line when it was one word.
        val read = listOf("たねトロピウスHP110", "リーフドレイン 20", "SV1a 001/073")
        val misread = listOf("たねトロピワスHP110", "リーフドレイン 20", "SV1a 001/073")
        assertEquals(true, ScanStabilizer.jaccard(ScanStabilizer.words(read), ScanStabilizer.words(misread)) >= 0.6)
        val stabilizer = ScanStabilizer(framesNeeded = 3)
        assertEquals(listOf(false, false, true), stabilizer.run(read, misread, read))
    }

    @Test
    fun glareKeepsTheSameCardWhenTheNumberStays() {
        val clear = listOf("Mega Camerupt ex", "HP 330", "Volcanic Burst 230", "I MEG EN 022/132")
        val glare = listOf("Mega Cam", "Volc", "022/132")
        val stabilizer = ScanStabilizer(framesNeeded = 3)
        assertEquals(listOf(false, false, true, false), stabilizer.run(clear, glare, clear, glare))
    }
}
