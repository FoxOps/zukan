package fr.fudabako.app

import fr.fudabako.app.data.OcrScript
import fr.fudabako.app.scan.ScriptPicker
import org.junit.Assert.assertEquals
import org.junit.Test

class ScriptPickerTest {
    // What each model returns for one frame: Asian models read Latin too, and misread
    // other scripts as their own or as noise.
    private fun readings(latin: String, japanese: String, korean: String, chinese: String) = mapOf(
        OcrScript.LATIN to latin.lines(),
        OcrScript.JAPANESE to japanese.lines(),
        OcrScript.KOREAN to korean.lines(),
        OcrScript.CHINESE to chinese.lines(),
    )

    @Test
    fun japaneseCardHasKana() {
        val pick = ScriptPicker.pick(readings("HP110\nSV1a 001/073", "たね トロピウス HP110\nSV1a 001/073", "HP110\nSV1a 001/073", "HP110\n入 001/073"))
        assertEquals(OcrScript.JAPANESE, pick)
    }

    @Test
    fun koreanCardHasHangul() {
        val pick = ScriptPicker.pick(readings("HP100\nSV4K 078/066", "HP100", "노공룡 HP100\nSV4K 078/066", "HP100"))
        assertEquals(OcrScript.KOREAN, pick)
    }

    @Test
    fun chineseCardHasHanWithoutKana() {
        val pick = ScriptPicker.pick(readings("HP 70", "皮卡丘 HP70", "HP70", "皮卡丘 HP70\n基礎"))
        assertEquals(OcrScript.CHINESE, pick)
    }

    @Test
    fun latinCardStaysLatin() {
        val text = "Llanowar Elves\nCreature — Elf Druid\n168/269 C"
        assertEquals(OcrScript.LATIN, ScriptPicker.pick(readings(text, text, text, text)))
    }
}
