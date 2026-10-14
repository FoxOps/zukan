package fr.fudabako.app

import fr.fudabako.app.ui.money
import fr.fudabako.app.ui.moneyByCurrency
import org.junit.Assert.assertEquals
import org.junit.Test
import java.util.Locale

class FormatTest {
    private fun clean(text: String) = text.replace(' ', ' ').replace(' ', ' ')

    @Test
    fun formatsInTheCurrencyGiven() {
        assertEquals("12,50 €", clean(money("12.50", "EUR", Locale.FRANCE)))
        assertEquals("$3.20", money("3.2", "USD", Locale.US))
        assertEquals("—", money(null, "EUR", Locale.US))
    }

    @Test
    fun neverAddsCurrenciesUp() {
        val text = moneyByCurrency(listOf("1.00" to "EUR", "2.50" to "EUR", "4.00" to "USD"), Locale.US)
        assertEquals("€3.50 + $4.00", text)
    }

    @Test
    fun onlyWebLinksAreOpened() {
        assertEquals(true, fr.fudabako.app.ui.isWebLink("https://www.cardmarket.com/en/Magic/Products?idProduct=1"))
        assertEquals(false, fr.fudabako.app.ui.isWebLink("intent://evil#Intent;end"))
        assertEquals(false, fr.fudabako.app.ui.isWebLink("javascript:alert(1)"))
    }
}
