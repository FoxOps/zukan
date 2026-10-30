package fr.zukan.app

import fr.zukan.app.scan.GlareMeter
import fr.zukan.app.ui.guessedFinish
import fr.zukan.app.ui.thumbLink
import fr.zukan.app.ui.withImageLanguage
import java.nio.ByteBuffer
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class ScanHelpersTest {
    @Test
    fun glareGuess() {
        val still = List(6) { 0.01 }
        val moving = listOf(0.0, 0.2, 0.05, 0.3, 0.0, 0.15)
        assertEquals("holo", GlareMeter.guess(moving, still))
        assertEquals("reverse", GlareMeter.guess(still, moving))
        // An ordinary glossy card, both parts alike, or too few frames: no guess.
        assertNull(GlareMeter.guess(still, still))
        assertNull(GlareMeter.guess(moving, moving))
        assertNull(GlareMeter.guess(moving.take(2), still.take(2)))
    }

    @Test
    fun glareMeterReadsTheCardArea() {
        val width = 64
        val height = 48
        val meter = GlareMeter()
        // Upright frame (rotation 0): highlights in the art window on every other frame.
        repeat(6) { frame ->
            val luma = ByteBuffer.allocate(width * height)
            if (frame % 2 == 0) {
                for (y in 0 until height) for (x in 0 until width) {
                    val cardHeight = height * 0.8
                    val cardWidth = cardHeight * 63.0 / 88.0
                    val fx = (x - (width - cardWidth) / 2) / cardWidth
                    val fy = (y - (height - cardHeight) / 2) / cardHeight
                    if (GlareMeter.inArt(fx, fy)) luma.put(y * width + x, 250.toByte())
                }
            }
            meter.offer(luma, width, height, width, 0)
        }
        assertEquals("holo", meter.guess())
        meter.reset()
        assertNull(meter.guess())
    }

    @Test
    fun finishFromGuess() {
        assertEquals("holo", guessedFinish("holo", listOf("normal", "holo", "reverse")))
        assertEquals("foil", guessedFinish("holo", listOf("nonfoil", "foil")))
        assertEquals("reverse", guessedFinish("reverse", listOf("normal", "reverse")))
        assertNull(guessedFinish("reverse", listOf("normal", "holo")))
        assertNull(guessedFinish(null, listOf("normal")))
    }

    @Test
    fun pictureLinks() {
        assertEquals("/api/printings/3/image?lang=fr", withImageLanguage("/api/printings/3/image?lang=en", "fr"))
        assertEquals("/api/printings/3/image?lang=ja", withImageLanguage("/api/printings/3/image", "ja"))
        assertEquals("/api/printings/3/image?face=front&lang=de", withImageLanguage("/api/printings/3/image?lang=en&face=front", "de"))
        assertEquals("https://example.test/x.png", withImageLanguage("https://example.test/x.png", "fr"))
        assertEquals("/api/printings/3/image?lang=fr&size=thumb", thumbLink("/api/printings/3/image?lang=fr"))
        assertEquals("/api/printings/3/image?face=back", thumbLink("/api/printings/3/image?face=back"))
        assertNull(thumbLink(null))
    }
}
