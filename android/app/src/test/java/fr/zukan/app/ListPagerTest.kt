package fr.zukan.app

import fr.zukan.app.ui.ListPager
import fr.zukan.app.ui.Paged
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertSame
import org.junit.Test

class ListPagerTest {
    private val id = { s: String -> s }

    @Test
    fun answerForAnotherQueryIsDropped() {
        val b = Paged<String, String>("B").withPage("B", 1, listOf("b1"), 1, id)
        // Page 2 of game A answered after page 1 of game B.
        assertSame(b, b.withPage("A", 2, listOf("a51"), 80, id))
        assertEquals(listOf("b1"), b.items)
        assertEquals(1, b.total)
    }

    @Test
    fun onlyTheNextPageIsAdded() {
        val one = Paged<String, String>("A").withPage("A", 1, listOf("x", "y"), 4, id)
        val two = one.withPage("A", 2, listOf("y", "z"), 4, id)
        assertEquals(listOf("x", "y", "z"), two.items)
        // The same page answered twice (or an older one) changes nothing.
        assertSame(two, two.withPage("A", 2, listOf("w"), 4, id))
    }

    @Test
    fun failedPageIsAskedAgain() = runTest {
        val scope = TestScope(StandardTestDispatcher(testScheduler))
        val asked = mutableListOf<Int>()
        val fail = CompletableDeferred<Boolean>().apply { complete(true) }
        var failing = true
        val pager = ListPager<String, String>(scope, "A", id, { "failed" }) { _, page ->
            asked += page
            if (page == 2 && failing && fail.await()) error("network")
            listOf("p$page") to 3
        }
        pager.load("A")
        scope.advanceUntilIdle()
        pager.more()
        scope.advanceUntilIdle()
        assertEquals("failed", pager.state.value.error)
        assertEquals(1, pager.state.value.page)

        failing = false
        pager.retry()
        scope.advanceUntilIdle()
        assertEquals(listOf(1, 2, 2), asked)
        assertEquals(2, pager.state.value.page)
        assertNull(pager.state.value.error)
    }

    @Test
    fun newQueryCancelsTheOldOne() = runTest {
        val scope = TestScope(StandardTestDispatcher(testScheduler))
        val slowA = CompletableDeferred<Unit>()
        val pager = ListPager<String, String>(scope, "A", id, { "failed" }) { key, page ->
            if (key == "A") slowA.await()
            listOf("$key$page") to 1
        }
        pager.load("A")
        scope.advanceUntilIdle()
        pager.load("B")
        scope.advanceUntilIdle()
        slowA.complete(Unit)
        scope.advanceUntilIdle()
        assertEquals("B", pager.state.value.key)
        assertEquals(listOf("B1"), pager.state.value.items)
    }
}
