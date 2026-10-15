package fr.zukan.app

import fr.zukan.app.scan.CardTurn
import fr.zukan.app.scan.CardTurn.Read
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class CardTurnTest {
    private val upright = listOf(Read("Abundance", 1f), Read("An Elite Aura of milk and honey", -2f))
    private val sideways = listOf(Read("Valley of Delight", 88f), Read("Site", 91f), Read("1", 0f))

    @Test
    fun sidewaysText() {
        assertFalse(CardTurn.sideways(upright))
        assertTrue(CardTurn.sideways(sideways))
        assertFalse(CardTurn.sideways(emptyList()))
    }

    @Test
    fun scoreCountsUprightLetters() {
        assertEquals(0, CardTurn.score(sideways.take(2)))
        assertTrue(CardTurn.weak(sideways))
        assertFalse(CardTurn.weak(upright))
    }

    @Test
    fun bestTurnKeepsTies() {
        assertEquals(90, CardTurn.best(0, mapOf(0 to 3, 90 to 40, 270 to 12)))
        assertEquals(0, CardTurn.best(0, mapOf(0 to 20, 90 to 20, 270 to 5)))
        assertEquals(270, CardTurn.best(270, mapOf(0 to 0, 90 to 0, 270 to 0)))
    }
}
