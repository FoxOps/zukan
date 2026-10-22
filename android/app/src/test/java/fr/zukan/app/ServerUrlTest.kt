package fr.zukan.app

import fr.zukan.app.data.ServerUrl
import org.junit.Assert.assertEquals
import org.junit.Test

class ServerUrlTest {
    @Test
    fun homeAddressesDefaultToHttp() {
        assertEquals("http://192.168.1.10:8000/", ServerUrl.normalize(" 192.168.1.10:8000/ "))
        assertEquals("http://nas:8000/", ServerUrl.normalize("nas:8000"))
        assertEquals("http://cards.lan/", ServerUrl.normalize("cards.lan"))
        assertEquals("http://box.tail1234.ts.net/", ServerUrl.normalize("box.tail1234.ts.net"))
    }

    @Test
    fun publicNamesDefaultToHttps() {
        assertEquals("https://cards.example.org/", ServerUrl.normalize("cards.example.org"))
        assertEquals("http://cards.example.org/sub/", ServerUrl.normalize("http://cards.example.org/sub"))
    }

    @Test
    fun typedSchemeIgnoresCase() {
        assertEquals("https://cards.example.org/", ServerUrl.normalize("HTTPS://cards.example.org"))
        assertEquals("http://nas:8000/", ServerUrl.normalize("Http://nas:8000"))
    }

    @Test
    fun redirectedBase() {
        val base = "http://cards.example.org/"
        assertEquals("https://cards.example.org/", ServerUrl.redirectedBase(base, "https://cards.example.org/api/health"))
        assertEquals(null, ServerUrl.redirectedBase(base, "http://cards.example.org/api/health"))
        assertEquals(null, ServerUrl.redirectedBase(base, "https://cards.example.org/login"))
        // Never downgrade to plain HTTP.
        assertEquals(null, ServerUrl.redirectedBase("https://a.org/", "http://a.org/api/health"))
    }
}
