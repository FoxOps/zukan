package fr.zukan.app

import fr.zukan.app.data.AndroidReleaseOut
import fr.zukan.app.data.ApiClient
import fr.zukan.app.data.ApkDownloader
import fr.zukan.app.data.ChecksumException
import fr.zukan.app.data.TokenStore
import fr.zukan.app.data.Tokens
import fr.zukan.app.data.UpdatePolicy
import fr.zukan.app.data.Versions
import java.nio.file.Files
import java.security.MessageDigest
import kotlinx.coroutines.test.runTest
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import org.junit.After
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Before
import org.junit.Test

class UpdatesTest {
    private val server = MockWebServer()

    @Before
    fun start() = server.start()

    @After
    fun stop() = server.close()

    private fun release(version: String, sha256: String? = null) =
        AndroidReleaseOut(version = version, url = server.url("/zukan-$version.apk").toString(), size = 4, sha256 = sha256)

    @Test
    fun comparesVersions() {
        assertTrue(Versions.compare("0.11.0", "0.10.0") > 0)
        assertTrue(Versions.compare("0.9.0", "0.10.0") < 0)
        assertEquals(0, Versions.compare("0.11.0", "0.11.0-dev.abc1234"))
        assertTrue(Versions.compare("1.0", "0.99.9") > 0)
    }

    @Test
    fun offersNewerNotSkippedVersions() {
        assertTrue(UpdatePolicy.offer(release("0.12.0"), "0.11.0", skipped = null, manual = false))
        assertFalse(UpdatePolicy.offer(release("0.11.0"), "0.11.0", skipped = null, manual = true))
        // Skipped: not offered by the daily check, still by "Check for updates".
        assertFalse(UpdatePolicy.offer(release("0.12.0"), "0.11.0", skipped = "0.12.0", manual = false))
        assertTrue(UpdatePolicy.offer(release("0.12.0"), "0.11.0", skipped = "0.12.0", manual = true))
        assertTrue(UpdatePolicy.offer(release("0.13.0"), "0.11.0", skipped = "0.12.0", manual = false))
    }

    @Test
    fun checksAtMostOnceADay() {
        val day = UpdatePolicy.CHECK_EVERY_MS
        assertTrue(UpdatePolicy.shouldCheck(0, 10 * day))
        assertFalse(UpdatePolicy.shouldCheck(10 * day, 10 * day + day / 2))
        assertTrue(UpdatePolicy.shouldCheck(10 * day, 11 * day))
        // Clock moved back: check again.
        assertTrue(UpdatePolicy.shouldCheck(10 * day, 9 * day))
    }

    @Test
    fun readsTheServerRelease() = runTest {
        server.enqueue(
            MockResponse.Builder().addHeader("Content-Type", "application/json").body(
                """{"version":"0.12.0","url":"https://github.com/dl/zukan-0.12.0.apk","size":24000000,
                |"published_at":"2026-10-27T10:00:00Z","sha256":null,"notes_url":"https://github.com/r"}""".trimMargin(),
            ).build(),
        )
        val store = object : TokenStore {
            override var tokens: Tokens? = Tokens("access", "refresh")
            override suspend fun saveTokens(value: Tokens?) {}
        }
        val out = ApiClient(server.url("/").toString(), store) {}.api.androidRelease()
        assertEquals("0.12.0", out.version)
        assertNull(out.sha256)
        assertEquals("/api/app/android", server.takeRequest().url.encodedPath)
    }

    @Test
    fun downloadsAndChecksTheApk() = runTest {
        val content = byteArrayOf(1, 2, 3, 4)
        val sha = MessageDigest.getInstance("SHA-256").digest(content).joinToString("") { "%02x".format(it) }
        val dir = Files.createTempDirectory("updates").toFile()
        val downloader = ApkDownloader(dir)
        server.enqueue(MockResponse.Builder().body(okio.Buffer().write(content)).build())
        val progress = mutableListOf<Float>()
        val file = downloader.download(release("0.12.0", sha)) { progress.add(it) }
        assertArrayEquals(content, file.readBytes())
        assertEquals(1f, progress.last())
        // No token sent to the download host.
        assertNull(server.takeRequest().headers["Authorization"])

        server.enqueue(MockResponse.Builder().body(okio.Buffer().write(content)).build())
        try {
            downloader.download(release("0.12.1", "00".repeat(32))) {}
            fail("checksum mismatch not detected")
        } catch (_: ChecksumException) {
        }
        assertTrue(dir.listFiles().isNullOrEmpty())
        dir.deleteRecursively()
    }
}
