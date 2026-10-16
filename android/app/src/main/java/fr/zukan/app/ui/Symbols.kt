package fr.zukan.app.ui

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.TrendingDown
import androidx.compose.material.icons.automirrored.filled.TrendingFlat
import androidx.compose.material.icons.automirrored.filled.TrendingUp
import androidx.compose.material.icons.filled.FlipCameraAndroid
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.layout.layout
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.Constraints
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.core.graphics.toColorInt
import coil3.ImageLoader
import coil3.compose.AsyncImage
import fr.zukan.app.R
import fr.zukan.app.data.GameOut
import fr.zukan.app.data.TrendOut
import fr.zukan.app.data.TrendsOut

/** Hex badge color of a game color, gray when the server sends something unreadable. */
fun colorOf(hex: String): Color = runCatching { Color(hex.toColorInt()) }.getOrDefault(Color.Gray)

/** The card's colors as the game's symbols (mana, energies, domains), a colored dot when
 * the server has no symbol for one (same as the web UI). */
@Composable
fun ColorSymbols(game: GameOut?, codes: List<String>, imageUrl: (String?) -> String?, imageLoader: ImageLoader, size: Int = 16) {
    if (codes.isEmpty()) return
    Row(horizontalArrangement = Arrangement.spacedBy(2.dp), verticalAlignment = Alignment.CenterVertically) {
        codes.forEach { code ->
            val color = game?.colors?.firstOrNull { it.code == code }
            if (color?.icon != null) {
                AsyncImage(model = imageUrl(color.icon), contentDescription = color.name, imageLoader = imageLoader, modifier = Modifier.size(size.dp))
            } else {
                Box(Modifier.size((size * 0.75).dp).clip(CircleShape).background(colorOf(color?.hex ?: "#888888")))
            }
        }
    }
}

/** Rarity pictogram (when the game has one) next to the rarity's name: both shown. */
@Composable
fun RarityBadge(game: GameOut?, rarity: String?, code: String?, imageUrl: (String?) -> String?, imageLoader: ImageLoader) {
    if (rarity.isNullOrEmpty()) return
    val icon = code?.let { c -> game?.rarities?.firstOrNull { it.code == c }?.icon }
    Row(horizontalArrangement = Arrangement.spacedBy(4.dp), verticalAlignment = Alignment.CenterVertically) {
        if (icon != null) {
            AsyncImage(model = imageUrl(icon), contentDescription = null, imageLoader = imageLoader, modifier = Modifier.size(14.dp))
        }
        Text(rarity.replaceFirstChar(Char::uppercase), style = MaterialTheme.typography.bodySmall)
    }
}

/** Market price trend over 24 h, 7 days and 30 days (same marks as the web UI). */
@Composable
fun TrendIcons(trends: TrendsOut) {
    val periods = listOf("24h" to trends.d1, "7d" to trends.d7, "30d" to trends.d30).filter { it.second != null }
    if (periods.isEmpty()) return
    Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
        periods.forEach { (label, trend) -> TrendMark(label, trend!!) }
    }
}

@Composable
private fun TrendMark(label: String, trend: TrendOut) {
    val (icon, tint) = when (trend.direction) {
        "up" -> Icons.AutoMirrored.Filled.TrendingUp to Color(0xFF16A34A)
        "down" -> Icons.AutoMirrored.Filled.TrendingDown to Color(0xFFDC2626)
        else -> Icons.AutoMirrored.Filled.TrendingFlat to MaterialTheme.colorScheme.onSurfaceVariant
    }
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text(label, fontSize = 10.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Icon(icon, contentDescription = trendText(trend), tint = tint, modifier = Modifier.size(14.dp))
    }
}

/** "+12 %" / "-3 %" / "0 %". */
fun trendText(trend: TrendOut): String {
    val percent = Math.round(trend.change * 100)
    return if (percent > 0) "+$percent %" else "$percent %"
}

/** A landscape picture turned a quarter clockwise to fill a portrait frame. */
private fun Modifier.turnedQuarter() = layout { measurable, constraints ->
    val placeable = measurable.measure(Constraints.fixed(constraints.maxHeight, constraints.maxWidth))
    layout(constraints.maxWidth, constraints.maxHeight) {
        placeable.placeWithLayer((constraints.maxWidth - placeable.width) / 2, (constraints.maxHeight - placeable.height) / 2) {
            rotationZ = 90f
        }
    }
}

/** Card picture at card proportions (63:88): landscape cards turned to fit, double-faced
 * cards with a flip button (the back is downloaded once asked for). */
@Composable
fun CardPicture(
    image: String?,
    imageUrl: (String?) -> String?,
    imageLoader: ImageLoader,
    modifier: Modifier = Modifier,
    back: String? = null,
    landscape: Boolean = false,
    contentDescription: String? = null,
) {
    var flipped by remember(image) { mutableStateOf(false) }
    val turn by animateFloatAsState(if (flipped) 180f else 0f, tween(400), label = "flip")
    val showBack = back != null && turn > 90f
    Box(modifier.aspectRatio(63f / 88f)) {
        Box(
            Modifier.matchParentSize()
                .graphicsLayer {
                    rotationY = turn
                    cameraDistance = 12f * density
                }
                .clip(RoundedCornerShape(6.dp)),
        ) {
            val shown = if (showBack) back else image
            if (shown == null) {
                Box(Modifier.matchParentSize().background(MaterialTheme.colorScheme.surfaceVariant), contentAlignment = Alignment.Center) {
                    Text(stringResource(R.string.no_picture), style = MaterialTheme.typography.bodySmall)
                }
            } else {
                AsyncImage(
                    model = imageUrl(shown),
                    contentDescription = contentDescription,
                    imageLoader = imageLoader,
                    contentScale = ContentScale.Crop,
                    modifier = Modifier.matchParentSize()
                        // The back is drawn mirrored by the turn: mirror it back.
                        .graphicsLayer { if (showBack) rotationY = 180f }
                        .let { if (landscape && !showBack) it.turnedQuarter() else it },
                )
            }
        }
        if (back != null) {
            val label = stringResource(if (flipped) R.string.show_front else R.string.show_back)
            Box(
                Modifier.align(Alignment.BottomEnd).padding(4.dp).size(28.dp).clip(CircleShape)
                    .background(MaterialTheme.colorScheme.surface.copy(alpha = 0.85f))
                    .clickable(onClickLabel = label) { flipped = !flipped },
                contentAlignment = Alignment.Center,
            ) {
                Icon(Icons.Default.FlipCameraAndroid, contentDescription = label, modifier = Modifier.size(18.dp).graphicsLayer { rotationZ = turn })
            }
        }
    }
}
