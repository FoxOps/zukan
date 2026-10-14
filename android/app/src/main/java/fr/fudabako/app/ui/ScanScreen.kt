package fr.fudabako.app.ui

import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.background
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.material3.LocalContentColor
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import coil3.ImageLoader
import fr.fudabako.app.R
import fr.fudabako.app.data.GameOut
import fr.fudabako.app.data.Settings

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ScanScreen(
    scan: ScanViewModel,
    state: ScanState,
    games: List<GameOut>,
    settings: Settings,
    priceSources: List<String>,
    imageUrl: (String?) -> String?,
    imageLoader: ImageLoader,
    onGame: (String?) -> Unit,
) {
    val context = LocalContext.current
    var granted by remember {
        mutableStateOf(ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED)
    }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { granted = it }
    LaunchedEffect(Unit) { if (!granted) permission.launch(Manifest.permission.CAMERA) }
    LaunchedEffect(settings.game, settings.autoNext) {
        scan.game = settings.game
        scan.autoNext = settings.autoNext
    }

    Box(Modifier.fillMaxSize().background(Color.Black)) {
        if (granted) {
            CameraPreview(
                settings.script,
                paused = state.phase != Phase.SCANNING,
                onFrame = scan::onFrame,
                onIdentify = scan::identify,
                onAsianFrame = scan::onAsianFrame,
                modifier = Modifier.fillMaxSize(),
            )
        } else {
            Column(Modifier.align(Alignment.Center).padding(24.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                Text(stringResource(R.string.camera_needed), color = Color.White)
                Button(onClick = { permission.launch(Manifest.permission.CAMERA) }) { Text(stringResource(R.string.allow_camera)) }
            }
        }

        // Game filter: faster and more accurate than trying every game.
        Row(
            Modifier.align(Alignment.TopCenter).padding(8.dp).horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            // Solid chips: readable over any camera image.
            val chipColors = FilterChipDefaults.filterChipColors(
                containerColor = MaterialTheme.colorScheme.surface.copy(alpha = 0.9f),
                selectedContainerColor = MaterialTheme.colorScheme.primary,
                selectedLabelColor = MaterialTheme.colorScheme.onPrimary,
            )
            FilterChip(selected = settings.game == null, onClick = { onGame(null) }, label = { Text(stringResource(R.string.any_game)) }, colors = chipColors)
            games.forEach { g ->
                FilterChip(selected = settings.game == g.id, onClick = { onGame(g.id) }, label = { Text(g.name) }, colors = chipColors)
            }
        }

        val status = when (state.phase) {
            Phase.SCANNING -> stringResource(R.string.point_at_card)
            Phase.IDENTIFYING -> stringResource(R.string.identifying)
            Phase.NOT_FOUND -> stringResource(if (state.result?.notACard == true) R.string.not_a_card else R.string.card_not_found)
            Phase.ERROR -> state.error ?: stringResource(R.string.error_identify)
            Phase.RESULT -> null
        }
        // What was read, so the user sees why nothing matched.
        val detail = when (state.phase) {
            Phase.NOT_FOUND -> state.result?.takeIf { !it.notACard }?.detected?.let { d ->
                listOfNotNull(d.name, listOfNotNull(d.setCode, d.collectorNumber).joinToString(" ").ifEmpty { null })
                    .joinToString(" · ").ifEmpty { null }
            } ?: if (state.result?.notACard == true) stringResource(R.string.not_a_card_help) else null
            else -> null
        }
        if (status != null) {
            Surface(
                Modifier.align(Alignment.BottomCenter).padding(24.dp),
                shape = RoundedCornerShape(24.dp),
                color = MaterialTheme.colorScheme.surface.copy(alpha = 0.85f),
            ) {
                Row(Modifier.padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                    if (state.phase == Phase.IDENTIFYING) CircularProgressIndicator(Modifier.padding(end = 8.dp).size(18.dp), strokeWidth = 2.dp)
                    Column(Modifier.weight(1f, fill = false)) {
                        Text(
                            status,
                            color = if (state.phase == Phase.ERROR) MaterialTheme.colorScheme.error else LocalContentColor.current,
                            fontWeight = if (state.phase == Phase.NOT_FOUND || state.phase == Phase.ERROR) FontWeight.SemiBold else null,
                        )
                        detail?.let { Text(it, style = MaterialTheme.typography.bodySmall) }
                    }
                    if (state.phase == Phase.NOT_FOUND || state.phase == Phase.ERROR) {
                        TextButton(onClick = { scan.resume(forgetCard = true) }) { Text(stringResource(R.string.try_again)) }
                    }
                }
            }
        }

        if (state.phase == Phase.RESULT) {
            // Swiped down or tapped outside: just looking, back to the camera.
            ModalBottomSheet(onDismissRequest = { scan.resume() }, sheetState = rememberModalBottomSheetState()) {
                ResultPanel(
                    state = state,
                    games = games,
                    settings = settings,
                    priceSources = priceSources,
                    imageUrl = imageUrl,
                    imageLoader = imageLoader,
                    onCandidate = scan::selectCandidate,
                    onPrinting = scan::selectPrinting,
                    searchPrintings = scan::searchPrintings,
                    onAdjust = scan::adjust,
                    onClose = { scan.resume() },
                )
            }
        }
    }
}
