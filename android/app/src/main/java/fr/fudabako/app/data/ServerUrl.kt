package fr.fudabako.app.data

/** Turn what the user typed ("nas.lan:8000", "https://cards.example.org") into a base URL. */
object ServerUrl {
    private val localHost = Regex(
        """^(localhost|\d{1,3}(\.\d{1,3}){3}|\[[0-9a-fA-F:]+]|[^.]+|.+\.(lan|local|home|internal|ts\.net))(:\d+)?(/.*)?$""",
    )

    fun normalize(input: String): String {
        var url = input.trim().trimEnd('/')
        if (url.isEmpty()) return url
        if (!url.startsWith("http://") && !url.startsWith("https://")) {
            // Home network names usually have no certificate; public names should.
            url = (if (localHost.matches(url)) "http://" else "https://") + url
        }
        return "$url/"
    }

    fun isSecure(url: String): Boolean = url.startsWith("https://")
}
