package fr.zukan.app.data

import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock

data class Tokens(val access: String, val refresh: String)

/**
 * Where API clients read and store tokens. Each login, logout, expiry or server change starts
 * a new session ([generation]): a client only ever reads the tokens of the session it was made
 * for, so a call still running for an old server or account never carries newer tokens.
 */
interface TokenStore {
    val generation: Long

    /** The tokens of session [generation]; null once it has ended or without tokens. */
    fun tokensFor(generation: Long): Tokens?

    /** Stores [next] only while [generation] is current and its tokens are still [expected]
     * (a refresh answered after a logout or another login must not bring old tokens back). */
    suspend fun replaceIf(generation: Long, expected: Tokens?, next: Tokens?): Boolean

    /** Ends the current session: its tokens go, and the new session has none. */
    suspend fun invalidate(): Long
}

/** [TokenStore] in memory; [persist] stores every change, one at a time and in order. */
open class TokenSessions(tokens: Tokens? = null) : TokenStore {
    private data class Session(val generation: Long, val tokens: Tokens?)

    private val lock = Mutex()

    // Read by OkHttp threads on every request; kept in memory to avoid blocking reads.
    @Volatile
    private var session = Session(0, tokens)

    override val generation get() = session.generation

    /** The tokens of the current session. */
    val tokens get() = session.tokens

    override fun tokensFor(generation: Long): Tokens? = session.takeIf { it.generation == generation }?.tokens

    override suspend fun replaceIf(generation: Long, expected: Tokens?, next: Tokens?): Boolean = lock.withLock {
        val current = session
        if (current.generation != generation || current.tokens != expected) return@withLock false
        persist(next)
        session = current.copy(tokens = next)
        true
    }

    override suspend fun invalidate(): Long = lock.withLock {
        // Seen at once: clients of the old session stop sending its tokens before the write.
        val next = Session(session.generation + 1, null)
        session = next
        persist(null)
        next.generation
    }

    protected open suspend fun persist(tokens: Tokens?) {}

    /** Tokens read from storage at start, for the current session. */
    protected suspend fun restore(tokens: Tokens?) = lock.withLock { session = session.copy(tokens = tokens) }
}
