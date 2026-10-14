package fr.fudabako.app.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle

/** A card name as the server shows it: non-Latin names come with a muted Latin
 * translation, e.g. "ビードル (Aspicot)". */
@Composable
fun shownName(name: String, translation: String?): AnnotatedString {
    val muted = MaterialTheme.colorScheme.onSurfaceVariant
    return buildAnnotatedString {
        append(name)
        if (!translation.isNullOrEmpty()) {
            withStyle(SpanStyle(color = muted, fontWeight = FontWeight.Normal)) { append(" ($translation)") }
        }
    }
}
