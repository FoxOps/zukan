package fr.fudabako.app.ui

import fr.fudabako.app.data.GameOut
import fr.fudabako.app.data.PriceOut
import fr.fudabako.app.data.PrintingOut
import java.math.BigDecimal

/** A price of one printing in one finish. */
data class Offer(val printing: PrintingOut, val price: PriceOut) {
    val trend: BigDecimal? get() = price.trend.toBigDecimalOrNull()
    val low: BigDecimal? get() = price.low?.toBigDecimalOrNull()
}

/**
 * Prices shown for a card, in one market: this printing in the chosen finish, then the
 * cheapest and most expensive version and the lowest offer over every printing and finish
 * (null when [complete] is false: only some printings are loaded).
 */
data class PriceStats(val thisVersion: Offer?, val cheapest: Offer?, val dearest: Offer?, val lowestOffer: Offer?)

/** The game's markets among the user's ones, main one first; else the game's first market. */
fun shownSources(game: GameOut?, wanted: List<String>): List<String> {
    val ids = game?.priceSources?.map { it.id }.orEmpty()
    return wanted.filter { it in ids }.ifEmpty { ids.take(1) }
}

/** Prices of [source] (the main market), else those listed first by the server. */
fun mainPrices(printing: PrintingOut, source: String?) =
    printing.prices.filter { it.source == (source ?: printing.prices.firstOrNull()?.source) }

fun priceStats(printings: List<PrintingOut>, printing: PrintingOut, finish: String, complete: Boolean, mainSource: String?): PriceStats {
    // The user's main market (unknown game: the one the server lists first).
    val source = mainSource
        ?: printing.prices.firstOrNull()?.source
        ?: printings.firstNotNullOfOrNull { it.prices.firstOrNull()?.source }
        ?: return PriceStats(null, null, null, null)
    val offers = printings.flatMap { p ->
        p.prices.filter { it.source == source }.map { Offer(p, it) }
    }.filter { it.trend != null }
    val thisVersion = offers.firstOrNull { it.printing.id == printing.id && it.price.finish == finish }
    if (!complete) return PriceStats(thisVersion, null, null, null)
    return PriceStats(
        thisVersion = thisVersion,
        cheapest = offers.minByOrNull { it.trend!! },
        dearest = offers.maxByOrNull { it.trend!! },
        lowestOffer = offers.filter { it.low != null }.minByOrNull { it.low!! },
    )
}
