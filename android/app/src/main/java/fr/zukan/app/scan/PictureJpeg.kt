package fr.zukan.app.scan

import android.graphics.Bitmap
import android.util.Base64
import java.io.ByteArrayOutputStream

/** The picture as a base64 JPEG, as the identify request carries it. */
fun ScanPicture.toJpegBase64(quality: Int = 80): String {
    val colors = IntArray(pixels.size) { i ->
        val v = pixels[i].toInt() and 0xFF
        (0xFF shl 24) or (v shl 16) or (v shl 8) or v
    }
    val bitmap = Bitmap.createBitmap(colors, width, height, Bitmap.Config.ARGB_8888)
    val out = ByteArrayOutputStream()
    bitmap.compress(Bitmap.CompressFormat.JPEG, quality, out)
    bitmap.recycle()
    return Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP)
}
