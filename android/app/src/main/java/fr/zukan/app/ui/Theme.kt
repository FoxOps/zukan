package fr.zukan.app.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.ButtonColors
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontVariation
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import fr.zukan.app.R

// Zukan identity v1.0: gold, chocolate, cream, leaf green, night.
private val Gold = Color(0xFFFFC21A)
private val Chocolate = Color(0xFF402719)
private val Cream = Color(0xFFFFF6E5)
private val Paper = Color(0xFFFFFCF6)
private val Sand = Color(0xFFE8D8C0)
private val Leaf = Color(0xFF3C7255)
private val Night = Color(0xFF211A17)
private val Muted = Color(0xFF776354)
private val Border = Color(0xFFCDB89B)
private val Danger = Color(0xFFAD3B35)

// Gold is too light for text on cream, so in light mode `primary` (text buttons, links) is
// chocolate and gold is the container colour; filled buttons use the container ([ctaColors]).
private val light = lightColorScheme(
    primary = Chocolate,
    onPrimary = Cream,
    primaryContainer = Gold,
    onPrimaryContainer = Chocolate,
    secondary = Leaf,
    onSecondary = Cream,
    secondaryContainer = Color(0xFFD7E8DC),
    onSecondaryContainer = Color(0xFF1B3A2A),
    tertiary = Leaf,
    onTertiary = Cream,
    background = Cream,
    onBackground = Chocolate,
    surface = Cream,
    onSurface = Chocolate,
    surfaceVariant = Color(0xFFF3E6CF),
    onSurfaceVariant = Muted,
    surfaceContainerLowest = Color.White,
    // Cards, sheets and the navigation bar: paper on cream (theme-map.json "surface").
    surfaceContainerLow = Paper,
    surfaceContainer = Color(0xFFFBF0DC),
    surfaceContainerHigh = Color(0xFFF6E8D0),
    surfaceContainerHighest = Color(0xFFF0E0C5),
    outline = Border,
    outlineVariant = Sand,
    error = Danger,
    onError = Color.White,
)

private val dark = darkColorScheme(
    primary = Gold,
    onPrimary = Chocolate,
    primaryContainer = Gold,
    onPrimaryContainer = Chocolate,
    secondary = Color(0xFF8FC4A5),
    onSecondary = Night,
    secondaryContainer = Leaf,
    onSecondaryContainer = Cream,
    tertiary = Color(0xFF8FC4A5),
    onTertiary = Night,
    background = Night,
    onBackground = Cream,
    surface = Night,
    onSurface = Cream,
    surfaceVariant = Color(0xFF3A2A20),
    onSurfaceVariant = Sand,
    surfaceContainerLowest = Color(0xFF1A1411),
    // Cards, sheets and the navigation bar: chocolate on night (theme-map.json "surface").
    surfaceContainerLow = Chocolate,
    surfaceContainer = Color(0xFF30231C),
    surfaceContainerHigh = Chocolate,
    surfaceContainerHighest = Color(0xFF4A3324),
    outline = Color(0xFF8D7055),
    outlineVariant = Color(0xFF5A4232),
    error = Color(0xFFF2A39E),
    onError = Night,
)

private fun variable(id: Int, weight: FontWeight) =
    Font(id, weight, variationSettings = FontVariation.Settings(FontVariation.weight(weight.weight)))

private val Nunito = FontFamily(variable(R.font.nunito, FontWeight.ExtraBold), variable(R.font.nunito, FontWeight.Bold))
private val Inter = FontFamily(
    variable(R.font.inter, FontWeight.Normal),
    variable(R.font.inter, FontWeight.Medium),
    variable(R.font.inter, FontWeight.SemiBold),
    variable(R.font.inter, FontWeight.Bold),
)

private val typography = Typography().run {
    val title = FontWeight.ExtraBold
    copy(
        displayLarge = displayLarge.copy(fontFamily = Nunito, fontWeight = title),
        displayMedium = displayMedium.copy(fontFamily = Nunito, fontWeight = title),
        displaySmall = displaySmall.copy(fontFamily = Nunito, fontWeight = title),
        headlineLarge = headlineLarge.copy(fontFamily = Nunito, fontWeight = title),
        headlineMedium = headlineMedium.copy(fontFamily = Nunito, fontWeight = title),
        headlineSmall = headlineSmall.copy(fontFamily = Nunito, fontWeight = title),
        titleLarge = titleLarge.copy(fontFamily = Nunito, fontWeight = title),
        titleMedium = titleMedium.copy(fontFamily = Inter, fontWeight = FontWeight.SemiBold),
        titleSmall = titleSmall.copy(fontFamily = Inter, fontWeight = FontWeight.SemiBold),
        bodyLarge = bodyLarge.copy(fontFamily = Inter),
        bodyMedium = bodyMedium.copy(fontFamily = Inter),
        bodySmall = bodySmall.copy(fontFamily = Inter),
        labelLarge = labelLarge.copy(fontFamily = Inter, fontWeight = FontWeight.SemiBold),
        labelMedium = labelMedium.copy(fontFamily = Inter, fontWeight = FontWeight.SemiBold),
        labelSmall = labelSmall.copy(fontFamily = Inter, fontWeight = FontWeight.Medium),
    )
}

private val shapes = Shapes(
    small = RoundedCornerShape(12.dp),
    medium = RoundedCornerShape(16.dp),
    large = RoundedCornerShape(20.dp),
)

@Composable
fun ZukanTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = if (isSystemInDarkTheme()) dark else light,
        typography = typography,
        shapes = shapes,
        content = content,
    )
}

/** Gold call-to-action button, as in the identity guide. */
@Composable
fun ctaColors(): ButtonColors = ButtonDefaults.buttonColors(
    containerColor = MaterialTheme.colorScheme.primaryContainer,
    contentColor = MaterialTheme.colorScheme.onPrimaryContainer,
)
