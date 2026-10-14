package fr.fudabako.app.ui

import java.math.BigDecimal
import java.text.NumberFormat
import java.util.Currency
import java.util.Locale

/** A server price ("12.50") in its currency, formatted for the phone's locale. */
fun money(value: String?, currency: String?, locale: Locale = Locale.getDefault()): String {
    val amount = value?.toBigDecimalOrNull() ?: return "—"
    val format = NumberFormat.getCurrencyInstance(locale)
    runCatching { format.currency = Currency.getInstance(currency ?: "EUR") }
    return format.format(amount)
}

/** Amounts per currency, never added up across currencies ("12,00 € + 3,50 $US"). */
fun moneyByCurrency(amounts: List<Pair<String, String>>, locale: Locale = Locale.getDefault()): String =
    amounts.groupBy({ it.second }, { it.first.toBigDecimalOrNull() ?: BigDecimal.ZERO })
        .map { (currency, values) -> money(values.fold(BigDecimal.ZERO, BigDecimal::add).toPlainString(), currency, locale) }
        .joinToString(" + ")
