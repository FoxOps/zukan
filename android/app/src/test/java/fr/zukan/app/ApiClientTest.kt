package fr.zukan.app

import fr.zukan.app.data.ApiClient
import fr.zukan.app.data.TokenStore
import fr.zukan.app.data.Tokens
import fr.zukan.app.data.serverDetail
import kotlinx.coroutines.test.runTest
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

class ApiClientTest {
    private val server = MockWebServer()
    private val store = object : TokenStore {
        override var tokens: Tokens? = Tokens("old-access", "old-refresh")
        override suspend fun saveTokens(value: Tokens?) {
            tokens = value
        }
    }
    private var expired = false

    @Before
    fun start() = server.start()

    @After
    fun stop() = server.close()

    private fun client() = ApiClient(server.url("/").toString(), store) { expired = true }

    private fun json(body: String, code: Int = 200) =
        MockResponse.Builder().code(code).addHeader("Content-Type", "application/json").body(body).build()

    @Test
    fun refreshesOnceAndRetries() = runTest {
        server.enqueue(json("""{"detail":"Invalid or expired token"}""", 401))
        server.enqueue(json("""{"access_token":"new-access","refresh_token":"new-refresh","expires_in":900}"""))
        server.enqueue(json("""{"id":1,"username":"alice","role":"user","email":null}"""))

        val me = client().api.me()

        assertEquals("alice", me.username)
        assertEquals(Tokens("new-access", "new-refresh"), store.tokens)
        assertEquals("Bearer old-access", server.takeRequest().headers["Authorization"])
        val refresh = server.takeRequest()
        assertEquals("/api/auth/refresh", refresh.url.encodedPath)
        assertTrue(refresh.body!!.utf8().contains("old-refresh"))
        assertEquals("Bearer new-access", server.takeRequest().headers["Authorization"])
    }

    @Test
    fun rejectedRefreshEndsTheSession() = runTest {
        server.enqueue(json("""{"detail":"expired"}""", 401))
        server.enqueue(json("""{"detail":"Invalid refresh token"}""", 401))

        val error = runCatching { client().api.me() }.exceptionOrNull()!!

        assertNull(store.tokens)
        assertTrue(expired)
        assertEquals("expired", error.serverDetail())
    }
}
