package fr.zukan.app.data

import java.io.File
import java.io.IOException
import java.security.MessageDigest
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.ensureActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import okhttp3.OkHttpClient
import okhttp3.Request

/** Latest Android release, from the server (`GET /api/app/android`, itself from GitHub). */
@Serializable
data class AndroidReleaseOut(
    val version: String,
    // APK download on GitHub.
    val url: String,
    val size: Long = 0,
    @SerialName("published_at") val publishedAt: String = "",
    val sha256: String? = null,
    @SerialName("notes_url") val notesUrl: String = "",
)

object Versions {
    /** Compares "X.Y.Z" versions (a suffix such as "-dev.abc1234" is ignored): negative when a < b. */
    fun compare(a: String, b: String): Int {
        val left = parts(a)
        val right = parts(b)
        for (i in 0 until maxOf(left.size, right.size)) {
            val diff = left.getOrElse(i) { 0 }.compareTo(right.getOrElse(i) { 0 })
            if (diff != 0) return diff
        }
        return 0
    }

    private fun parts(version: String) =
        version.trim().removePrefix("v").substringBefore('-').split('.').map { it.toIntOrNull() ?: 0 }
}

/** When an update is offered: newer than the installed app and, for the automatic check
 * (at most once a day), not a version the user chose to skip. */
object UpdatePolicy {
    const val CHECK_EVERY_MS = 24 * 3600 * 1000L

    fun shouldCheck(lastCheck: Long, now: Long): Boolean = now - lastCheck >= CHECK_EVERY_MS || now < lastCheck

    fun offer(release: AndroidReleaseOut, installed: String, skipped: String?, manual: Boolean): Boolean =
        Versions.compare(release.version, installed) > 0 && (manual || release.version != skipped)
}

class ChecksumException : IOException("Downloaded APK checksum mismatch")

/** A release this app does not download: not HTTPS, or an odd version. */
class InvalidReleaseException : IOException("Invalid release")

/** More bytes than announced (or than any app needs): the download stops. */
class TooLargeException : IOException("Download larger than expected")

/** Not enough room in the app cache for the APK. */
class NoSpaceException : IOException("Not enough free space")

/**
 * Downloads an APK into [dir] (app cache, shared with the installer through a FileProvider).
 * Its own HTTP client: the server's bearer token must never reach GitHub. Never more than the
 * release's size (else [maxBytes]); a cancelled download stops at once and leaves no file.
 */
class ApkDownloader(
    private val dir: File,
    private val http: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(60, TimeUnit.SECONDS)
        .build(),
    private val maxBytes: Long = MAX_APK_BYTES,
    // Tests use plain HTTP.
    private val httpsOnly: Boolean = true,
) {
    suspend fun download(release: AndroidReleaseOut, onProgress: (Float) -> Unit): File = withContext(Dispatchers.IO) {
        if (!VERSION.matches(release.version) || (httpsOnly && !release.url.startsWith("https://"))) throw InvalidReleaseException()
        val limit = if (release.size > 0) minOf(release.size, maxBytes) else maxBytes
        dir.mkdirs()
        // One update at a time: older downloads go.
        dir.listFiles()?.forEach { it.delete() }
        if (dir.usableSpace in 0 until limit + SPACE_MARGIN) throw NoSpaceException()
        val part = File.createTempFile("zukan-", ".part", dir)
        val call = http.newCall(Request.Builder().url(release.url).build())
        try {
            coroutineScope {
                // A read waiting for bytes does not see cancellation: the call is cancelled.
                val watcher = launch {
                    try {
                        awaitCancellation()
                    } finally {
                        call.cancel()
                    }
                }
                try {
                    call.execute().use { response ->
                        if (!response.isSuccessful) throw IOException("HTTP ${response.code}")
                        val body = response.body
                        if (body.contentLength() > limit) throw TooLargeException()
                        val total = body.contentLength().takeIf { it > 0 } ?: release.size
                        val digest = MessageDigest.getInstance("SHA-256")
                        body.byteStream().use { input ->
                            part.outputStream().use { output ->
                                val buffer = ByteArray(64 * 1024)
                                var done = 0L
                                var shown = -1
                                while (true) {
                                    ensureActive()
                                    val read = input.read(buffer)
                                    if (read < 0) break
                                    done += read
                                    if (done > limit) throw TooLargeException()
                                    output.write(buffer, 0, read)
                                    digest.update(buffer, 0, read)
                                    // Each percent once, not every buffer.
                                    val percent = if (total > 0) (done * 100 / total).toInt().coerceIn(0, 100) else -1
                                    if (percent > shown) {
                                        shown = percent
                                        onProgress(percent / 100f)
                                    }
                                }
                            }
                        }
                        val hex = digest.digest().joinToString("") { "%02x".format(it) }
                        if (release.sha256 != null && !hex.equals(release.sha256, ignoreCase = true)) throw ChecksumException()
                    }
                } finally {
                    watcher.cancel()
                }
            }
            val file = File(dir, "zukan-${release.version}.apk")
            if (!part.renameTo(file)) throw IOException("Could not save the update")
            file
        } catch (e: Throwable) {
            call.cancel()
            part.delete()
            throw e
        }
    }

    companion object {
        const val MAX_APK_BYTES = 150L * 1024 * 1024
        private const val SPACE_MARGIN = 16L * 1024 * 1024
        private val VERSION = Regex("""^\d{1,4}\.\d{1,4}\.\d{1,4}$""")
    }
}
