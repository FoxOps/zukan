package fr.zukan.app.data

import java.security.cert.CertPathValidatorException
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import javax.net.ssl.SSLException
import javax.net.ssl.SSLPeerUnverifiedException

/** Why a secure connection failed, so the user knows what to fix on the server side. */
enum class SslKind {
    /** The certificate is for another name (often the proxy's default certificate). */
    HOSTNAME,

    /** The chain does not lead to a trusted root: missing intermediate, self-signed, private CA. */
    UNTRUSTED,

    /** The address answers in plain HTTP (e.g. https:// sent to port 8000). */
    PLAIN,
    OTHER,
}

private fun Throwable.chain(): Sequence<Throwable> = generateSequence(this) { e -> e.cause?.takeIf { it !== e } }

private val plainHints = listOf(
    "packet header", // Android (Conscrypt): "Unable to parse TLS packet header"
    "unrecognized ssl message", // JVM
    "wrong_version_number",
    "wrong version number",
    "http_request",
)

fun SSLException.sslKind(): SslKind {
    val causes = chain().toList()
    val text = causes.joinToString(" ") { it.message.orEmpty() }.lowercase()
    return when {
        causes.any { it is SSLPeerUnverifiedException } || "not verified" in text -> SslKind.HOSTNAME
        causes.any { it is CertPathValidatorException || it is CertificateException } ||
            "trust anchor" in text || "certification path" in text -> SslKind.UNTRUSTED
        plainHints.any { it in text } -> SslKind.PLAIN
        else -> SslKind.OTHER
    }
}

/**
 * A short technical detail to show next to the message: who issued the last certificate the
 * server sent (a missing intermediate shows up as an issuer the phone does not know), else the
 * innermost exception message.
 */
fun SSLException.sslDetail(): String {
    val path = chain().filterIsInstance<CertPathValidatorException>().firstOrNull()?.certPath
    val last = path?.certificates?.lastOrNull() as? X509Certificate
    val detail = last?.let { "issuer ${it.issuerX500Principal.name}" }
        ?: chain().last().message
        ?: javaClass.simpleName
    return detail.take(200)
}
