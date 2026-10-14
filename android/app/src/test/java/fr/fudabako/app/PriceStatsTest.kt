package fr.fudabako.app

import fr.fudabako.app.data.CardOut
import fr.fudabako.app.data.CardSummaryOut
import fr.fudabako.app.data.PriceOut
import fr.fudabako.app.data.PrintingOut
import fr.fudabako.app.data.SetOut
import fr.fudabako.app.data.json
import fr.fudabako.app.data.GameOut
import fr.fudabako.app.data.MeOut
import fr.fudabako.app.data.PriceSourceOut
import fr.fudabako.app.ui.priceStats
import fr.fudabako.app.ui.shownSources
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class PriceStatsTest {
    private fun price(finish: String, trend: String, low: String? = null, source: String = "cardmarket") =
        PriceOut(finish = finish, trend = trend, low = low, date = "2026-10-14", source = source)

    private fun printing(id: Int, set: String, vararg prices: PriceOut) = PrintingOut(
        id = id,
        set = SetOut(id = id, code = set, name = set),
        finishes = prices.map { it.finish }.distinct(),
        languages = listOf("en"),
        prices = prices.toList(),
    )

    private val mew = printing(1, "MEW", price("normal", "0.12", "0.05"), price("reverse", "0.45", "0.30"), price("normal", "0.20", source = "tcgplayer"))
    private val base = printing(2, "BS", price("normal", "38.00", "25.00"))
    private val promo = printing(3, "SVP")

    @Test
    fun thisVersionFollowsTheFinish() {
        val stats = priceStats(listOf(mew, base, promo), mew, "reverse", complete = true, mainSource = null)
        assertEquals("0.45", stats.thisVersion?.price?.trend)
        assertEquals("0.12", stats.cheapest?.price?.trend)
        assertEquals("MEW", stats.cheapest?.printing?.set?.code)
        assertEquals("38.00", stats.dearest?.price?.trend)
        assertEquals("0.05", stats.lowestOffer?.price?.low)
    }

    @Test
    fun cardWidePricesNeedEveryPrinting() {
        val stats = priceStats(listOf(mew), mew, "normal", complete = false, mainSource = null)
        assertEquals("0.12", stats.thisVersion?.price?.trend)
        assertNull(stats.cheapest)
        assertNull(stats.dearest)
        assertNull(stats.lowestOffer)
    }

    @Test
    fun mainSourceIsTheUsersNotTheFirstListed() {
        // This printing has no Cardmarket price: the stats stay on Cardmarket.
        val tcgOnly = printing(4, "TCG", price("normal", "9.00", source = "tcgplayer"))
        val stats = priceStats(listOf(tcgOnly, base), tcgOnly, "normal", complete = true, mainSource = "cardmarket")
        assertNull(stats.thisVersion)
        assertEquals("38.00", stats.cheapest?.price?.trend)
    }

    @Test
    fun shownSourcesFollowTheUserAndTheGame() {
        val cm = PriceSourceOut("cardmarket", "Cardmarket", "EUR")
        val tcg = PriceSourceOut("tcgplayer", "TCGplayer", "USD")
        val mtg = GameOut("mtg", "MTG", emptyList(), emptyList(), listOf("en"), hasPrices = true, priceSources = listOf(cm, tcg))
        val sorcery = mtg.copy(id = "sorcery", priceSources = listOf(cm))
        assertEquals(listOf("tcgplayer", "cardmarket"), shownSources(mtg, listOf("tcgplayer", "cardmarket")))
        assertEquals(listOf("cardmarket"), shownSources(mtg, listOf("cardmarket")))
        // The game has none of the user's sources: its first one.
        assertEquals(listOf("cardmarket"), shownSources(sorcery, listOf("tcgplayer")))
        // Servers before 0.7 only send the main source.
        val old = json.decodeFromString<MeOut>("""{"id":1,"username":"a","role":"user","price_source":"tcgplayer"}""")
        assertEquals(listOf("tcgplayer"), old.shownPriceSources)
    }

    @Test
    fun noPrices() {
        val stats = priceStats(listOf(promo), promo, "normal", complete = true, mainSource = null)
        assertNull(stats.thisVersion)
        assertNull(stats.cheapest)
    }

    @Test
    fun readsNamesAndPrintingsOfNewAndOldServers() {
        val summary = json.decodeFromString<CardSummaryOut>(
            """{"id":1,"game_id":"pokemon","name":"ビードル","translation":"Aspicot","colors":[],"printing_count":3,"printing_id":9,"extra":1}""",
        )
        assertEquals("Aspicot", summary.translation)
        assertEquals(9, summary.printingId)
        val old = json.decodeFromString<CardOut>("""{"id":1,"game_id":"pokemon","name":"Weedle","colors":[],"printings":[]}""")
        assertNull(old.translation)
        assertNull(old.defaultPrintingId)
    }
}
