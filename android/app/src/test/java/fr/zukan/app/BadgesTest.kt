package fr.zukan.app

import fr.zukan.app.data.PrintingOut
import fr.zukan.app.data.SetOut
import fr.zukan.app.ui.CONDITIONS
import fr.zukan.app.ui.CONDITION_COLORS
import fr.zukan.app.ui.languageFlag
import fr.zukan.app.ui.printingMatches
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class BadgesTest {
    @Test
    fun conditionsMatchTheWebColors() {
        assertEquals(listOf("MT", "NM", "EX", "GD", "LP", "PL", "PO"), CONDITIONS)
        // web/src/lib/format.ts CONDITIONS
        val web = listOf(0x17a2b8, 0x3caf56, 0x82891e, 0xffc107, 0xfd8b2b, 0xe56874, 0xdc3545)
        val app = CONDITION_COLORS.values.map {
            val argb = (it.value shr 32).toLong()
            (argb and 0xFFFFFF).toInt()
        }
        assertEquals(web, app)
    }

    @Test
    fun flagsAreRegionalIndicators() {
        assertEquals("🇬🇧", languageFlag("en")) // GB
        assertEquals("🇯🇵", languageFlag("ja")) // JP
        assertEquals("🇹🇼", languageFlag("zh-hant")) // TW
        assertNull(languageFlag("ph"))
    }

    @Test
    fun printingFilter() {
        val printing = PrintingOut(
            id = 1,
            set = SetOut(1, "DOM", "Dominaria"),
            collectorNumber = "168",
            finishes = emptyList(),
            languages = listOf("en"),
        )
        assertTrue(printingMatches(printing, ""))
        assertTrue(printingMatches(printing, "domin"))
        assertTrue(printingMatches(printing, "dom 168"))
        assertTrue(printingMatches(printing, "168"))
        assertFalse(printingMatches(printing, "war"))
    }
}
