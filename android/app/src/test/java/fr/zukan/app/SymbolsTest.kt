package fr.zukan.app

import fr.zukan.app.data.CardSummaryOut
import fr.zukan.app.data.GameOut
import fr.zukan.app.data.ItemOut
import fr.zukan.app.data.TrendOut
import fr.zukan.app.data.json
import fr.zukan.app.ui.trendText
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class SymbolsTest {
    @Test
    fun readsRaritiesOrientationAndTrendsOfNewServers() {
        val game = json.decodeFromString<GameOut>(
            """{"id":"lorcana","name":"Disney Lorcana","colors":[],"finishes":[],"languages":["en"],"has_prices":true,
               "rarities":[{"code":"common","name":"Common","icon":"/api/games/lorcana/rarities/common/icon"}]}""",
        )
        assertEquals("/api/games/lorcana/rarities/common/icon", game.rarities.single().icon)
        val card = json.decodeFromString<CardSummaryOut>(
            """{"id":1,"game_id":"riftbound","name":"Altar","colors":["colorless"],"printing_count":1,
               "orientation":"landscape","rarity":"Rare","rarity_code":"rare","back_image":null}""",
        )
        assertEquals("landscape", card.orientation)
        assertEquals("rare", card.rarityCode)
        val item = json.decodeFromString<ItemOut>(
            """{"id":1,"name":"Ahri","quantity":2,"colors":["calm"],"trends":{"d1":{"direction":"up","change":0.12},"d7":null}}""",
        )
        assertEquals("up", item.trends.d1?.direction)
        assertNull(item.trends.d7)
    }

    @Test
    fun oldServersKeepDefaults() {
        val game = json.decodeFromString<GameOut>(
            """{"id":"mtg","name":"Magic","colors":[],"finishes":[],"languages":["en"],"has_prices":true}""",
        )
        assertEquals(emptyList<Any>(), game.rarities)
        val item = json.decodeFromString<ItemOut>("""{"id":1,"name":"Forest","quantity":1}""")
        assertEquals("portrait", item.orientation)
        assertNull(item.trends.d30)
    }

    @Test
    fun trendPercent() {
        assertEquals("+12 %", trendText(TrendOut("up", 0.123)))
        assertEquals("-3 %", trendText(TrendOut("down", -0.031)))
        assertEquals("0 %", trendText(TrendOut("flat", 0.001)))
    }
}
