package fr.zukan.app.data

import kotlinx.coroutines.CancellationException

/** [runCatching] that lets cancellation through: leaving a screen or typing on is not an
 * error to show, and the coroutine must stop. */
inline fun <T> runCatchingCancellable(block: () -> T): Result<T> = try {
    Result.success(block())
} catch (e: CancellationException) {
    throw e
} catch (e: Throwable) {
    Result.failure(e)
}
