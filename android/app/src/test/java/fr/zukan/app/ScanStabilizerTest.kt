package fr.zukan.app

import fr.zukan.app.data.OcrLineIn
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

    @Test
    fun glareHidingTheNumberDoesNotBreakTheRun() {
        // Reverse holo: the number line comes and goes, the rest of the text changes.
        val clear = listOf("Artikodin PV 120", "Rafale glacée 60", "I JTG FR 032/159")
        val glare = listOf("Artik", "glac 60")
        val stabilizer = ScanStabilizer(framesNeeded = 3)
        assertEquals(listOf(false, false, false, true), stabilizer.run(clear, glare, clear, clear))
    }

    @Test
    fun anotherNumberIsAnotherCard() {
        val articuno = listOf("Artikodin PV 120", "I JTG FR 032/159")
        val drifloon = listOf("Baudrive PV 70", "F 063/189")
        val stabilizer = ScanStabilizer(framesNeeded = 2)
        assertEquals(listOf(false, true, false, true), stabilizer.run(articuno, articuno, drifloon, drifloon))
    }

    @Test
    fun waitsAWhileForTheNumber() {
        val nameOnly = listOf("Surfer", "Supporter", "Draw cards until you have 5")
        val stabilizer = ScanStabilizer(framesNeeded = 2)
        val waited = List(ScanStabilizer.NUMBER_WAIT) { false }
        assertEquals(listOf(false) + waited + true, stabilizer.run(*Array(ScanStabilizer.NUMBER_WAIT + 2) { nameOnly }))
    }

    @Test
    fun numberLineTakenFromARecentFrame() {
        val now = listOf(OcrLineIn("Surfer", 0f, 0f))
        val earlier = listOf(OcrLineIn("Surfer", 0f, 0f), OcrLineIn("SSP EN 187/191", 0f, 0.95f))
        val sent = ScanStabilizer.withNumberLine(now, listOf(earlier, now))
        assertEquals(listOf("Surfer", "SSP EN 187/191"), sent.map { it.text })
        // Already there: unchanged.
        assertEquals(earlier, ScanStabilizer.withNumberLine(earlier, listOf(now)))
    }
}
