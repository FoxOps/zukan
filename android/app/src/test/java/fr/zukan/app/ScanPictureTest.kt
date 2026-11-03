package fr.zukan.app

import fr.zukan.app.scan.ScanPicture
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test
import java.nio.ByteBuffer

class ScanPictureTest {
    /** A sensor frame (Y plane) with [value] at each pixel, rows padded to [rowStride]. */
    private fun frame(width: Int, height: Int, rowStride: Int, value: (Int, Int) -> Int): ByteBuffer {
        val bytes = ByteArray(rowStride * height)
        for (y in 0 until height) for (x in 0 until width) bytes[y * rowStride + x] = value(x, y).toByte()
        return ByteBuffer.wrap(bytes)
    }

    @Test
    fun cropIsUprightWithItsBoxInTextFractions() {
        // 40x20 sensor turned by 90°: upright 20 wide, 40 high. Bright pixel at sensor
        // (x=30, y=19), upright (19 - 19, 30) = (0, 30).
        val luma = frame(40, 20, 48) { x, y -> if (x == 30 && y == 19) 200 else 10 }
        val picture = ScanPicture.crop(luma, 40, 20, 48, 90, intArrayOf(0, 0, 20, 40))!!
        // The margin is clamped to the frame: the picture is the whole upright frame.
        assertEquals(20, picture.width)
        assertEquals(40, picture.height)
        assertEquals(listOf(0f, 0f, 1f, 1f), picture.box)
        assertEquals(200, picture.pixels[30 * 20 + 0].toInt() and 0xFF)
        assertEquals(10, picture.pixels[0].toInt() and 0xFF)
    }

    @Test
    fun marginGoesPastTheText() {
        val luma = frame(100, 100, 100) { x, _ -> x }
        val picture = ScanPicture.crop(luma, 100, 100, 100, 0, intArrayOf(20, 20, 60, 80))!!
        // 25% of 40 px each side, 6% of 60 px above and below.
        assertEquals(listOf(-0.25f, -0.0666f, 1.25f, 1.0666f), picture.box.map { (it * 10000).toInt() / 10000f })
        assertArrayEquals(byteArrayOf(10, 11, 12), picture.pixels.copyOfRange(0, 3))
    }
}
