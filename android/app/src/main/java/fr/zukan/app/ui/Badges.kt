package fr.zukan.app.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import fr.zukan.app.data.GameOut

/** Cardmarket grading scale with Cardmarket's badge colors (same as the web UI). */
val CONDITION_COLORS = linkedMapOf(
    "MT" to Color(0xFF17A2B8),
    "NM" to Color(0xFF3CAF56),
    "EX" to Color(0xFF82891E),
    "GD" to Color(0xFFFFC107),
    "LP" to Color(0xFFFD8B2B),
    "PL" to Color(0xFFE56874),
    "PO" to Color(0xFFDC3545),
)
val CONDITIONS = CONDITION_COLORS.keys.toList()

fun conditionTextColor(code: String): Color = if (code == "GD") Color(0xFF171717) else Color.White

/** Special finishes stand out from the game's base finish (same gradients as the web UI). */
private val FINISH_GRADIENTS = mapOf(
    "foil" to listOf(0xFF7DD3FC, 0xFFF0ABFC, 0xFFFDE68A),
    "holo" to listOf(0xFFA5B4FC, 0xFF7DD3FC, 0xFF6EE7B7),
    "reverse" to listOf(0xFFF9A8D4, 0xFFC4B5FD, 0xFF7DD3FC),
    "etched" to listOf(0xFFD6D3D1, 0xFFFDE68A, 0xFFA8A29E),
    "rainbow" to listOf(0xFFFCA5A5, 0xFFFEF08A, 0xFF7DD3FC),
)

/** Country whose flag stands for a card language (same as the web UI). */
private val LANGUAGE_FLAGS = mapOf(
    "en" to "GB", "fr" to "FR", "de" to "DE", "it" to "IT", "es" to "ES", "pt" to "PT",
    "ja" to "JP", "ko" to "KR", "zh-hans" to "CN", "zh-hant" to "TW", "ru" to "RU",
    "th" to "TH", "id" to "ID",
)

/** Flag emoji of a card language (regional indicator letters), null when unknown. */
fun languageFlag(code: String): String? = LANGUAGE_FLAGS[code]?.let { country ->
    country.map { Character.toChars(0x1F1E6 + (it - 'A')).concatToString() }.joinToString("")
}

private val badgeText = TextStyle(fontSize = 12.sp, fontWeight = FontWeight.SemiBold)

@Composable
private fun Badge(text: String, background: Brush, color: Color, modifier: Modifier = Modifier) {
    Box(
        modifier.background(background, RoundedCornerShape(50)).padding(horizontal = 8.dp, vertical = 2.dp),
    ) { Text(text, style = badgeText, color = color, maxLines = 1) }
}

@Composable
fun ConditionBadge(code: String, modifier: Modifier = Modifier) {
    val color = CONDITION_COLORS[code] ?: Color.Gray
    Badge(code, Brush.linearGradient(listOf(color, color)), conditionTextColor(code), modifier)
}

@Composable
fun FinishBadge(game: GameOut?, code: String, modifier: Modifier = Modifier) {
    val name = game?.finishes?.firstOrNull { it.code == code }?.name ?: code
    val gradient = FINISH_GRADIENTS[code]
    when {
        gradient != null -> Badge(name, Brush.horizontalGradient(gradient.map { Color(it) }), Color(0xFF171717), modifier)
        game?.finishes?.firstOrNull()?.code == code -> Box(
            modifier.border(1.dp, MaterialTheme.colorScheme.outlineVariant, RoundedCornerShape(50))
                .padding(horizontal = 8.dp, vertical = 2.dp),
        ) { Text(name, style = badgeText, maxLines = 1) }
        else -> Badge(
            name,
            Brush.linearGradient(listOf(MaterialTheme.colorScheme.secondary, MaterialTheme.colorScheme.secondary)),
            MaterialTheme.colorScheme.onSecondary,
            modifier,
        )
    }
}

/** Flag of a card language; the code when no flag is known. */
@Composable
fun LangFlag(code: String, modifier: Modifier = Modifier, size: Int = 16) {
    val flag = languageFlag(code)
    if (flag != null) Text(flag, modifier, fontSize = size.sp) else Text(code, modifier, style = badgeText)
}
