package fr.zukan.app.data

/** Turn what the user typed ("nas.lan:8000", "https://cards.example.org") into a base URL. */
object ServerUrl {
    private val scheme = Regex("^(https?)://", RegexOption.IGNORE_CASE)
    private const val HEALTH = "api/health"

    /** HTTPS unless `http://` is typed: passwords and tokens are never sent unencrypted
     * without the user asking for it (a home network does not protect them). */
    fun normalize(input: String): String {
        var url = input.trim().trimEnd('/')
        if (url.isEmpty()) return url
        val typed = scheme.find(url)
        url = if (typed != null) {
            typed.groupValues[1].lowercase() + url.substring(typed.groupValues[1].length)
        } else {
            "https://$url"
        }
        return "$url/"
    }

    fun isSecure(url: String): Boolean = url.startsWith("https://")

    /**
     * The base URL to use after `GET <base>api/health` ended on [finalHealthUrl], or null to keep
     * [base]: not redirected, redirected elsewhere than a health URL, or downgraded to http.
     */
    fun redirectedBase(base: String, finalHealthUrl: String): String? {
        val target = finalHealthUrl.substringBefore('?').substringBefore('#')
        if (!target.endsWith(HEALTH)) return null
        val newBase = target.removeSuffix(HEALTH)
        if (newBase == base) return null
        if (isSecure(base) && !isSecure(newBase)) return null
        return newBase
    }
}
