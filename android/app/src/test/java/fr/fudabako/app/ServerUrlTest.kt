package fr.fudabako.app

import fr.fudabako.app.data.ServerUrl
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
}
