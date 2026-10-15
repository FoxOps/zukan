package fr.zukan.app.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

// Lacquered card box: vermilion and paper.
private val Vermilion = Color(0xFFB5452F)
private val Paper = Color(0xFFF2E8D5)

@Composable
fun ZukanTheme(content: @Composable () -> Unit) {
    val colors = if (isSystemInDarkTheme()) {
        darkColorScheme(primary = Color(0xFFE07A5F), secondary = Paper, tertiary = Color(0xFFE0C9A0))
    } else {
        lightColorScheme(primary = Vermilion, secondary = Color(0xFF6B4F3A), tertiary = Color(0xFF8E3322))
    }
    MaterialTheme(colorScheme = colors, content = content)
}
