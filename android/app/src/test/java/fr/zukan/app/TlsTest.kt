package fr.zukan.app

import fr.zukan.app.data.ApiClient
import fr.zukan.app.data.SslKind
import fr.zukan.app.data.TokenStore
import fr.zukan.app.data.Tokens
import fr.zukan.app.data.sslDetail
import fr.zukan.app.data.sslKind
import java.net.InetAddress
import java.net.ServerSocket
import javax.net.ssl.SSLException
import kotlin.concurrent.thread
import kotlinx.coroutines.test.runTest
import mockwebserver3.MockResponse
import mockwebserver3.MockWebServer
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.tls.HandshakeCertificates
import okhttp3.tls.HeldCertificate
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

/** Real TLS failures against a local server, as a phone meets them behind a misconfigured proxy. */
class TlsTest {
    private companion object {
        val LOOPBACK: InetAddress = InetAddress.getByName("127.0.0.1")
    }

    private val servers = mutableListOf<MockWebServer>()
    private val root = HeldCertificate.Builder().commonName("Test Root").certificateAuthority(1).build()
    private val intermediate = HeldCertificate.Builder()
        .commonName("Test Intermediate").certificateAuthority(0).signedBy(root).build()

    @After
    fun stop() = servers.forEach { it.close() }

    private fun server(leafName: String? = null, sendIntermediate: Boolean = true): MockWebServer {
        val server = MockWebServer()
        if (leafName != null) {
            val leaf = HeldCertificate.Builder().addSubjectAlternativeName(leafName).signedBy(intermediate).build()
            val chain = if (sendIntermediate) arrayOf(intermediate.certificate) else emptyArray()
            val certs = HandshakeCertificates.Builder().heldCertificate(leaf, *chain).build()
            server.useHttps(certs.sslSocketFactory())
        }
        server.enqueue(MockResponse.Builder().body("""{"status":"ok"}""").build())
        server.start(LOOPBACK, 0)
        servers += server
        return server
    }

    private fun MockWebServer.at(path: String, https: Boolean = false) =
        "${if (https) "https" else "http"}://127.0.0.1:$port$path"

    /** A client that trusts only the test root (like a phone with the public roots). */
    private val client = HandshakeCertificates.Builder().addTrustedCertificate(root.certificate).build().let {
        OkHttpClient.Builder().sslSocketFactory(it.sslSocketFactory(), it.trustManager).build()
    }

    private fun failure(url: String): SSLException {
        try {
            client.newCall(Request.Builder().url(url).build()).execute().close()
        } catch (e: SSLException) {
            return e
        }
        fail("expected an SSLException")
        error("unreachable")
    }

    @Test
    fun fullChainWorks() {
        val server = server("127.0.0.1")
        client.newCall(Request.Builder().url(server.at("/api/health", https = true)).build()).execute().use {
            assertEquals(200, it.code)
        }
    }

    @Test
    fun missingIntermediateIsUntrusted() {
        val server = server("127.0.0.1", sendIntermediate = false)
        val e = failure(server.at("/api/health", https = true))
        assertEquals(SslKind.UNTRUSTED, e.sslKind())
        assertTrue(e.sslDetail().isNotBlank())
    }

    @Test
    fun otherNameIsHostname() {
        val server = server("cards.example.org")
        assertEquals(SslKind.HOSTNAME, failure(server.at("/api/health", https = true)).sslKind())
    }

    @Test
    fun plainHttpPortIsPlain() {
        // Like uvicorn or nginx on a plain port: answers the TLS hello with an HTTP error.
        ServerSocket(0, 1, LOOPBACK).use { socket ->
            thread {
                socket.accept().use { it.getOutputStream().write("HTTP/1.1 400 Bad Request\r\n\r\n".toByteArray()) }
            }
            assertEquals(SslKind.PLAIN, failure("https://127.0.0.1:${socket.localPort}/api/health").sslKind())
        }
    }

    @Test
    fun followsProxyRedirectToFinalBase() = runTest {
        val target = server()
        val proxy = MockWebServer().also { servers += it }
        proxy.enqueue(MockResponse.Builder().code(301).addHeader("Location", target.at("/zukan/api/health")).build())
        proxy.start(LOOPBACK, 0)
        val store = object : TokenStore {
            override var tokens: Tokens? = null
            override suspend fun saveTokens(value: Tokens?) {}
        }
        val api = ApiClient(proxy.at("/"), store) {}
        assertEquals(target.at("/zukan/"), api.redirectedBaseUrl())
    }
}
