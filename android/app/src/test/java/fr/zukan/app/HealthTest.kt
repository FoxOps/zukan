package fr.zukan.app

import fr.zukan.app.data.ApiClient
import fr.zukan.app.data.HealthOut
import fr.zukan.app.data.TokenStore
import fr.zukan.app.data.Tokens
import kotlinx.coroutines.test.runTest
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test

/** `/api/health` as servers before 0.20.0 and since (with `maintenance`) answer it. */
class HealthTest {
    private val server = MockWebServer()
    private val store = object : TokenStore {
        override var tokens: Tokens? = null
        override suspend fun saveTokens(value: Tokens?) {
            tokens = value
        }
    }

    @Before
    fun start() = server.start()

    @After
    fun stop() = server.close()

    private suspend fun health(body: String): HealthOut {
        server.enqueue(MockResponse.Builder().addHeader("Content-Type", "application/json").body(body).build())
        return ApiClient(server.url("/").toString(), store) {}.api.health()
    }

    @Test
    fun serverBefore020() = runTest {
        val health = health("""{"status":"ok","version":"0.19.0"}""")
        assertEquals("0.19.0", health.version)
        assertNull(health.maintenance)
    }

    @Test
    fun noMaintenance() = runTest {
        assertEquals("0.20.1", health("""{"status":"ok","version":"0.20.1","maintenance":null}""").version)
    }

    @Test
    fun maintenance() = runTest {
        val health = health("""{"status":"ok","version":"0.20.1","maintenance":{"since":"2026-10-29T10:00:00Z","game_id":"mtg"}}""")
        assertEquals("0.20.1", health.version)
        assertEquals("mtg", health.maintenance?.gameId)
    }
}
