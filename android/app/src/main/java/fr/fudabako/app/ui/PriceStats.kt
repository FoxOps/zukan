package fr.fudabako.app.ui

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

fun priceStats(printings: List<PrintingOut>, printing: PrintingOut, finish: String, complete: Boolean): PriceStats {
    // The user's market: the server lists it first in each printing's prices.
    val source = printing.prices.firstOrNull()?.source
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
