package fr.zukan.app.scan

import fr.zukan.app.data.OcrScript

/**
 * Picks the text recognition model whose reading fits the card: each Asian model reads
 * its own script plus Latin, so the card's script is the one whose own letters were
 * found (kana for Japanese, Hangul for Korean, Han without kana for Chinese).
 */
object ScriptPicker {
    private const val MIN_GLYPHS = 2

    fun pick(readings: Map<OcrScript, List<String>>): OcrScript {
        val kana = count(readings[OcrScript.JAPANESE]) { it.isKana() }
        val hangul = count(readings[OcrScript.KOREAN]) { Character.UnicodeScript.of(it) == Character.UnicodeScript.HANGUL }
        val han = count(readings[OcrScript.CHINESE]) { Character.UnicodeScript.of(it) == Character.UnicodeScript.HAN }
        val japaneseHan = count(readings[OcrScript.JAPANESE]) { Character.UnicodeScript.of(it) == Character.UnicodeScript.HAN }
        return when {
            hangul >= MIN_GLYPHS && hangul >= kana -> OcrScript.KOREAN
            kana >= MIN_GLYPHS -> OcrScript.JAPANESE
            han >= MIN_GLYPHS -> OcrScript.CHINESE
            // Kanji-only Japanese text (rare): the Japanese model still read it.
            japaneseHan >= MIN_GLYPHS -> OcrScript.JAPANESE
            else -> OcrScript.LATIN
        }
    }

    private fun Int.isKana(): Boolean = Character.UnicodeScript.of(this).let {
        it == Character.UnicodeScript.HIRAGANA || it == Character.UnicodeScript.KATAKANA
    }

    private fun count(lines: List<String>?, test: (Int) -> Boolean): Int =
        lines.orEmpty().sumOf { line -> line.codePoints().filter { test(it) }.count().toInt() }
}
