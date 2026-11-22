package fr.zukan.app

import fr.zukan.app.data.ApiClient
import fr.zukan.app.data.ShoppingItemIn
import fr.zukan.app.data.TokenStore
import fr.zukan.app.data.Tokens
import kotlinx.coroutines.test.runTest
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** Shopping lists (`/api/shopping-lists`) and the account's `language_chosen`. */
class ShoppingTest {
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

    private fun api() = ApiClient(server.url("/").toString(), store) {}.api

    private fun json(body: String, code: Int = 200) =
        server.enqueue(MockResponse.Builder().code(code).addHeader("Content-Type", "application/json").body(body).build())

    private val list = """
        {"id":3,"name":"Burn","deck_id":null,"game_id":"mtg","created_at":"2026-11-21T10:00:00Z",
         "copies":6,"bought":6,"items":[
           {"id":7,"card_id":1,"printing_id":null,"name":"Lightning Bolt","translation":"Foudre",
            "set_code":"M10","collector_number":"146","quantity":4,"bought_count":4,"bought":true},
           {"id":8,"card_id":null,"printing_id":null,"name":"Mountain","translation":null,
            "set_code":null,"collector_number":null,"quantity":2,"bought":true}]}
    """.trimIndent()

    @Test
    fun listsAndTick() = runTest {
        json("""[{"id":3,"name":"Burn","deck_id":5,"game_id":"mtg","created_at":"2026-11-21T10:00:00Z","copies":6,"bought":0}]""")
        val lists = api().shoppingLists()
        assertEquals(listOf("Burn"), lists.map { it.name })
        assertFalse(lists[0].complete)
        assertTrue(lists[0].items.isEmpty())
        server.takeRequest()

        json(list)
        val ticked = api().updateShoppingItem(3, 7, ShoppingItemIn(4, bought = true))
        assertTrue(ticked.complete)
        assertEquals(4, ticked.items[0].boughtCount)
        // Servers before 0.31 send no bought_count: all copies or none.
        assertEquals(2, ticked.items[1].boughtCount)
        assertEquals("Foudre", ticked.items[0].translation)
        val request = server.takeRequest()
        assertEquals("PATCH", request.method)
        assertEquals("/api/shopping-lists/3/items/7", request.url.encodedPath)
        assertEquals("""{"bought_count":4,"bought":true}""", request.body?.utf8())
    }

    @Test
    fun copiesBought() {
        val item = fr.zukan.app.data.ShoppingItemOut(id = 1, name = "Shock", quantity = 3, bought = false)
        assertEquals(0, item.boughtCount)
        val some = item.withBought(2)
        assertEquals(2, some.boughtCount)
        assertFalse(some.bought)
        assertTrue(item.withBought(3).bought)
    }

    @Test
    fun delete() = runTest {
        server.enqueue(MockResponse.Builder().code(204).build())
        api().deleteShoppingList(3)
        val request = server.takeRequest()
        assertEquals("DELETE", request.method)
        assertEquals("/api/shopping-lists/3", request.url.encodedPath)
    }

    @Test
    fun languageChosen() = runTest {
        // Servers before 0.30 send no language_chosen: their language always applies.
        json("""{"id":1,"username":"alice","role":"user","language":"en"}""")
        assertTrue(api().me().languageChosen)
        json("""{"id":1,"username":"alice","role":"user","language":"en","language_chosen":false,"modules":["decks"]}""")
        val me = api().me()
        assertFalse(me.languageChosen)
        assertEquals(listOf("decks"), me.modules)
    }
}
