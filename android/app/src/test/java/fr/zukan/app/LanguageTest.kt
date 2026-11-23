package fr.zukan.app

import fr.zukan.app.data.ApiClient
import fr.zukan.app.data.TokenSessions
import fr.zukan.app.data.Tokens
import fr.zukan.app.data.acceptLanguage
import kotlinx.coroutines.test.runTest
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Before
import org.junit.Test

/** The phone's languages sent as `Accept-Language`: the server takes the account's language
 * from them until the user picks one. */
class LanguageTest {
    private val server = MockWebServer()
    private val store = TokenSessions(null)

    @Before
    fun start() = server.start()

    @After
    fun stop() = server.close()

    @Test
    fun header() {
        assertEquals("de-DE", acceptLanguage(listOf("de-DE")))
        assertEquals("ja-JP,fr-FR;q=0.9,en-US;q=0.8", acceptLanguage(listOf("ja-JP", "fr-FR", "en-US", "fr-FR")))
        assertEquals("a,b;q=0.9,c;q=0.8,d;q=0.7,e;q=0.6", acceptLanguage(listOf("a", "b", "c", "d", "e", "f")))
        assertNull(acceptLanguage(emptyList()))
        assertNull(acceptLanguage(listOf("und", " ")))
    }

    @Test
    fun sentWithRequests() = runTest {
        server.enqueue(MockResponse.Builder().addHeader("Content-Type", "application/json").body("""{"id":1,"username":"alice","role":"user","language":"fr","language_chosen":false}""").build())
        val me = ApiClient(server.url("/").toString(), store, { listOf("fr-FR", "en-GB") }) {}.api.me()
        assertEquals("fr", me.language)
        assertEquals("fr-FR,en-GB;q=0.9", server.takeRequest().headers["Accept-Language"])
    }
}
