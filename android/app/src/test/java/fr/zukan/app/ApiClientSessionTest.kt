package fr.zukan.app

import fr.zukan.app.data.ApiClient
import fr.zukan.app.data.TokenSessions
import fr.zukan.app.data.Tokens
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.test.runTest
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** Tokens never cross sessions (logout, another account, another server). */
class ApiClientSessionTest {
    private val server = MockWebServer()
    private val alice = Tokens("alice-access", "alice-refresh")
    private val bob = Tokens("bob-access", "bob-refresh")
    private val store = TokenSessions(alice)
    private var expired = false

    @Before
    fun start() = server.start()

    @After
    fun stop() = server.close()

    private fun client() = ApiClient(server.url("/").toString(), store) { expired = true }

    private fun json(body: String, code: Int = 200, delayMs: Long = 0) =
        MockResponse.Builder().code(code).addHeader("Content-Type", "application/json").body(body)
            .headersDelay(delayMs, TimeUnit.MILLISECONDS).build()

    private suspend fun switchToBob() {
        store.invalidate()
        store.replaceIf(store.generation, null, bob)
    }

    @Test
    fun oldClientNeverSendsTheNextSessionsToken() = runTest {
        val old = client()
        switchToBob()
        server.enqueue(json("""{"detail":"Not authenticated"}""", 401))

        assertTrue(runCatching { old.api.me() }.isFailure)

        assertNull(server.takeRequest().headers["Authorization"])
        // No refresh either: the old session has no tokens left.
        assertEquals(1, server.requestCount)
        assertEquals(bob, store.tokens)
    }

    @Test
    fun refreshAnsweredAfterTheSessionEndedChangesNothing() = runTest {
        server.enqueue(json("""{"detail":"expired"}""", 401))
        server.enqueue(json("""{"access_token":"late-access","refresh_token":"late-refresh","expires_in":900}""", delayMs = 500))
        val call = async(Dispatchers.IO) { runCatching { client().api.me() } }
        server.takeRequest()
        assertEquals("/api/auth/refresh", server.takeRequest().url.encodedPath)
        // Logged out and in as another account while the refresh is under way.
        switchToBob()

        assertTrue(call.await().isFailure)
        assertEquals(bob, store.tokens)
        assertEquals(2, server.requestCount)
        assertFalse(expired)
    }

    @Test
    fun refusedRefreshEndsOnlyItsOwnSession() = runTest {
        server.enqueue(json("""{"detail":"expired"}""", 401))
        server.enqueue(json("""{"detail":"Invalid refresh token"}""", 401, delayMs = 500))
        val call = async(Dispatchers.IO) { runCatching { client().api.me() } }
        server.takeRequest()
        server.takeRequest()
        switchToBob()

        call.await()
        assertEquals(bob, store.tokens)
        assertFalse(expired)
    }

    @Test
    fun serverErrorDuringRefreshKeepsTheSession() = runTest {
        server.enqueue(json("""{"detail":"expired"}""", 401))
        server.enqueue(json("""{"detail":"Service unavailable"}""", 503))

        assertTrue(runCatching { client().api.me() }.isFailure)

        assertEquals(alice, store.tokens)
        assertFalse(expired)
    }

    @Test
    fun unreachableRefreshKeepsTheSession() = runTest {
        server.enqueue(json("""{"detail":"expired"}""", 401))
        val api = client()
        val call = async(Dispatchers.IO) { runCatching { api.api.me() } }
        server.takeRequest()
        // The refresh finds no server.
        server.close()

        assertTrue(call.await().isFailure)
        assertEquals(alice, store.tokens)
        assertFalse(expired)
    }

    @Test
    fun closedClientSendsNoToken() = runTest {
        val api = client().also { it.close() }
        server.enqueue(json("""{"id":1,"username":"alice","role":"user","email":null}"""))

        runCatching { api.api.me() }

        if (server.requestCount > 0) assertNull(server.takeRequest().headers["Authorization"])
        assertEquals(alice, store.tokens)
    }
}
