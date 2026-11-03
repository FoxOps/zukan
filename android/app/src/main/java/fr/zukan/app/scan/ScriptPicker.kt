package fr.zukan.app.scan

import fr.zukan.app.data.OcrScript

/**
 * Picks the text recognition model whose reading fits the card: each Asian model reads
 * its own script plus Latin, so the card's script is the one whose own letters were
 * found (kana for Japanese, Hangul for Korean, Han without kana for Chinese).
 */
object ScriptPicker {
    private const val MIN_GLYPHS = 2
    // Share of a reading's letters its script must have: the Japanese model reads Latin
    // letters as look-alike katakana ("ロ" for "O", "エ" for "I", "ー" for "-"), so a
    // French card read by it has a few kana among many Latin letters.
    private const val MIN_SHARE = 0.2

    fun pick(readings: Map<OcrScript, List<String>>): OcrScript {
        val japanese = readings[OcrScript.JAPANESE]
        val kana = count(japanese) { it.isKana() }
        val japaneseHan = count(japanese) { it.isHan() }
        val hangul = count(readings[OcrScript.KOREAN]) { Character.UnicodeScript.of(it) == Character.UnicodeScript.HANGUL }
        val han = count(readings[OcrScript.CHINESE]) { it.isHan() }
        val japaneseShare = fits(kana + japaneseHan, japanese)
        return when {
            hangul >= MIN_GLYPHS && hangul >= kana && fits(hangul, readings[OcrScript.KOREAN]) -> OcrScript.KOREAN
            kana >= MIN_GLYPHS && japaneseShare -> OcrScript.JAPANESE
            han >= MIN_GLYPHS && fits(han, readings[OcrScript.CHINESE]) -> OcrScript.CHINESE
            // Kanji-only Japanese text (rare): the Japanese model still read it.
            japaneseHan >= MIN_GLYPHS && japaneseShare -> OcrScript.JAPANESE
            else -> OcrScript.LATIN
        }
    }

    /** [glyphs] are enough of the reading's letters. */
    private fun fits(glyphs: Int, lines: List<String>?): Boolean = glyphs >= MIN_SHARE * count(lines) { Character.isLetter(it) }

    fun hasKana(lines: List<String>): Boolean = count(lines) { it.isKana() } > 0

    private fun Int.isKana(): Boolean = Character.UnicodeScript.of(this).let {
        it == Character.UnicodeScript.HIRAGANA || it == Character.UnicodeScript.KATAKANA
    }

    private fun Int.isHan(): Boolean = Character.UnicodeScript.of(this) == Character.UnicodeScript.HAN

    private fun count(lines: List<String>?, test: (Int) -> Boolean): Int =
        lines.orEmpty().sumOf { line -> line.codePoints().filter { test(it) }.count().toInt() }
}
