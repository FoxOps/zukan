package fr.zukan.app.ui

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.provider.Settings as AndroidSettings
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.annotation.DrawableRes
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Rect
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.ClipOp
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.drawscope.clipPath
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import coil3.ImageLoader
import fr.zukan.app.R
import fr.zukan.app.data.GameOut
import fr.zukan.app.data.Settings
import fr.zukan.app.scan.GlareMeter

// The scanner of the 2026-10 redesign: a paper header with the game chips, a card-shaped
// frame over the camera, and one status card at the bottom telling what to do next in
// plain words. The maquettes do not draw it: built from the shared components.

/** Card proportions (63 x 88 mm), shared by every supported game. */
private const val CARD_RATIO = 63f / 88f

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
    snackbar: SnackbarHostState,
    onSearch: () -> Unit,
    onGame: (String?) -> Unit,
) {
    val context = LocalContext.current
    val hasCamera = { ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED }
    var granted by remember { mutableStateOf(hasCamera()) }
    // Refused for good: Android no longer shows the question, only the app settings can allow it.
    var blocked by remember { mutableStateOf(false) }
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { ok ->
        granted = ok
        blocked = !ok && context.findActivity()?.shouldShowRequestPermissionRationale(Manifest.permission.CAMERA) == false
    }
    LaunchedEffect(Unit) { if (!granted) permission.launch(Manifest.permission.CAMERA) }
    // Back from the app settings: the camera may be allowed now.
    LifecycleEventEffect(Lifecycle.Event.ON_RESUME) { if (!granted && hasCamera()) granted = true }
    LaunchedEffect(settings.game, settings.autoNext, settings.glareFinish) {
        scan.game = settings.game
        scan.autoNext = settings.autoNext
        scan.glare = if (settings.glareFinish) scan.glare ?: GlareMeter() else null
    }
    var torch by remember { mutableStateOf(false) }
    var torchAvailable by remember { mutableStateOf(false) }
    var moreGames by remember { mutableStateOf(false) }

    if (!granted) {
        CameraPermission(
            blocked = blocked,
            onAllow = { permission.launch(Manifest.permission.CAMERA) },
            onSettings = {
                context.startActivity(
                    Intent(AndroidSettings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", context.packageName, null)),
                )
            },
            onSearch = onSearch,
        )
        return
    }

    // A card opened from the collection or search: no camera behind it (it starts again,
    // in a moment, when the card is closed).
    val manual = state.phase == Phase.RESULT && state.result?.candidates?.firstOrNull()?.match == "manual"
    Box(Modifier.fillMaxSize().background(Color.Black)) {
        if (!manual) {
            CameraPreview(
                settings.script,
                paused = state.phase != Phase.SCANNING,
                onFrame = scan::onFrame,
                onIdentify = scan::identify,
                onAsianFrame = scan::onAsianFrame,
                modifier = Modifier.fillMaxSize(),
                torch = torch,
                onTorchAvailable = { torchAvailable = it },
                glare = { scan.glare },
            )
        }
        Column(Modifier.fillMaxSize()) {
            ScanHeader(
                games = games,
                game = settings.game,
                onGame = onGame,
                onMore = { moreGames = true },
                torch = torch.takeIf { torchAvailable },
                onTorch = { torch = !torch },
            )
            Viewfinder(state.phase, Modifier.weight(1f).fillMaxWidth())
            if (state.phase != Phase.RESULT) {
                StatusCard(state, games, torchAvailable && !torch, onGame = onGame, onRetry = { scan.resume(forgetCard = true) }, onSearch = onSearch)
            }
        }

        if (state.phase == Phase.RESULT) {
            // Swiped down, closed or tapped outside: just looking, back to the camera.
            ModalBottomSheet(
                onDismissRequest = { scan.resume() },
                sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
                containerColor = MaterialTheme.colorScheme.surfaceContainerLow,
                shape = RoundedCornerShape(topStart = 32.dp, topEnd = 32.dp),
            ) {
                Box {
                    Column {
                        Row(Modifier.padding(horizontal = 24.dp), verticalAlignment = Alignment.CenterVertically) {
                            Text(
                                stringResource(R.string.card_found),
                                style = MaterialTheme.typography.headlineSmall,
                                modifier = Modifier.weight(1f).semantics { heading() },
                            )
                            IconButton(onClick = { scan.resume() }) { ZIcon(R.drawable.ic_close, stringResource(R.string.close)) }
                        }
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
                    // The tray opens in a window of its own above the screen's snackbar:
                    // show "Added …", Undo and errors in it too.
                    SnackbarHost(snackbar, Modifier.align(Alignment.BottomCenter))
                }
            }
        }
        if (moreGames) {
            ZukanSheet(title = stringResource(R.string.scan_title), onDismiss = { moreGames = false }) {
                Column {
                    ChoiceRow(stringResource(R.string.any_game), settings.game == null, onClick = { onGame(null); moreGames = false })
                    games.forEach { g -> ChoiceRow(g.name, settings.game == g.id, onClick = { onGame(g.id); moreGames = false }) }
                }
            }
        }
    }
}

/** Before the camera is allowed: why it is needed, and the one button to press. */
@Composable
private fun CameraPermission(blocked: Boolean, onAllow: () -> Unit, onSettings: () -> Unit, onSearch: () -> Unit) {
    Column(
        Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background).verticalScroll(rememberScrollState()).padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp, Alignment.CenterVertically),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        MessageCard(
            title = stringResource(R.string.camera_title),
            text = stringResource(if (blocked) R.string.camera_blocked else R.string.camera_needed),
            picture = { Image(painterResource(R.drawable.zukan_mascot), contentDescription = null, modifier = Modifier.size(96.dp)) },
            action = {
                GoldButton(stringResource(if (blocked) R.string.open_settings else R.string.allow_camera), if (blocked) onSettings else onAllow)
            },
        )
        TextButton(onClick = onSearch, modifier = Modifier.heightIn(min = 48.dp)) {
            Text(stringResource(R.string.search_by_name), style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.onSurface)
        }
    }
}

/** Paper header over the camera: title, torch, and which game to look for. */
@Composable
private fun ScanHeader(
    games: List<GameOut>,
    game: String?,
    onGame: (String?) -> Unit,
    onMore: () -> Unit,
    // null: no torch on this phone.
    torch: Boolean?,
    onTorch: () -> Unit,
) {
    Surface(
        color = MaterialTheme.colorScheme.surfaceContainerLow,
        shape = RoundedCornerShape(bottomStart = 32.dp, bottomEnd = 32.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(start = 24.dp, end = 12.dp, top = 12.dp, bottom = 16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    stringResource(R.string.scan_title),
                    style = MaterialTheme.typography.headlineSmall,
                    modifier = Modifier.weight(1f).semantics { heading() },
                )
                if (torch != null) {
                    IconButton(
                        onClick = onTorch,
                        colors = if (torch) {
                            IconButtonDefaults.iconButtonColors(
                                containerColor = MaterialTheme.colorScheme.primaryContainer,
                                contentColor = MaterialTheme.colorScheme.onPrimaryContainer,
                            )
                        } else {
                            IconButtonDefaults.iconButtonColors()
                        },
                    ) { ZIcon(R.drawable.ic_flash, stringResource(if (torch) R.string.torch_off else R.string.torch_on)) }
                }
            }
            // Game filter: faster and more accurate than trying every game.
            GameChips(games, game, onGame, onMore)
        }
    }
}

/** Card-shaped frame: the rest of the picture is dimmed so the eye goes to it. */
@Composable
private fun Viewfinder(phase: Phase, modifier: Modifier = Modifier) {
    val pulse by rememberInfiniteTransition(label = "frame").animateFloat(
        initialValue = 1f,
        targetValue = 0.35f,
        animationSpec = infiniteRepeatable(tween(600), RepeatMode.Reverse),
        label = "pulse",
    )
    val color = when (phase) {
        Phase.SCANNING -> MaterialTheme.colorScheme.primaryContainer
        Phase.IDENTIFYING -> MaterialTheme.colorScheme.primaryContainer.copy(alpha = pulse)
        Phase.RESULT -> MaterialTheme.colorScheme.secondary
        Phase.NOT_FOUND, Phase.ERROR -> MaterialTheme.colorScheme.error
    }
    Canvas(modifier) {
        val height = minOf(size.height - 32.dp.toPx(), (size.width - 64.dp.toPx()) / CARD_RATIO)
        if (height <= 0f) return@Canvas
        val frame = Size(height * CARD_RATIO, height)
        val topLeft = Offset((size.width - frame.width) / 2, (size.height - frame.height) / 2)
        val radius = 16.dp.toPx()
        val card = Path().apply { addRoundRect(androidx.compose.ui.geometry.RoundRect(Rect(topLeft, frame), CornerRadius(radius))) }
        clipPath(card, ClipOp.Difference) { drawRect(Color.Black.copy(alpha = 0.5f)) }
        drawPath(card, Color.White.copy(alpha = 0.5f), style = Stroke(1.dp.toPx()))
        // Thick corners, as on a camera viewfinder.
        val arm = minOf(32.dp.toPx(), frame.width / 4)
        val stroke = 5.dp.toPx()
        val left = topLeft.x
        val top = topLeft.y
        val right = left + frame.width
        val bottom = top + frame.height
        listOf(
            listOf(Offset(left, top + arm), Offset(left, top), Offset(left + arm, top)),
            listOf(Offset(right - arm, top), Offset(right, top), Offset(right, top + arm)),
            listOf(Offset(right, bottom - arm), Offset(right, bottom), Offset(right - arm, bottom)),
            listOf(Offset(left + arm, bottom), Offset(left, bottom), Offset(left, bottom - arm)),
        ).forEach { (a, corner, b) ->
            drawLine(color, a, corner, stroke, StrokeCap.Round)
            drawLine(color, corner, b, stroke, StrokeCap.Round)
        }
    }
}

/** What is happening and what to do next, in plain words, with at most one main button. */
@Composable
private fun StatusCard(
    state: ScanState,
    games: List<GameOut>,
    // The torch is there and off: suggested after failures (holo cards, dim light).
    torchHint: Boolean,
    onGame: (String?) -> Unit,
    onRetry: () -> Unit,
    onSearch: () -> Unit,
) {
    val result = state.result.takeIf { state.phase == Phase.NOT_FOUND }
    val otherGame = result?.otherGame?.takeIf { id -> games.any { it.id == id } }
    val otherName = otherGame?.let { id -> games.first { it.id == id }.name }
    // What was read, so the user sees why nothing matched.
    val read = result?.takeIf { !it.notACard }?.detected?.let { d ->
        listOfNotNull(d.name, listOfNotNull(d.setCode, d.collectorNumber).joinToString(" ").ifEmpty { null })
            .joinToString(" · ").ifEmpty { null }
    }
    val title: String
    val text: String?
    @DrawableRes val icon: Int?
    when {
        state.phase == Phase.SCANNING -> {
            title = stringResource(R.string.point_at_card)
            text = stringResource(R.string.point_at_card_help)
            icon = R.drawable.ic_scan
        }
        state.phase == Phase.IDENTIFYING -> {
            title = stringResource(R.string.identifying)
            text = stringResource(R.string.identifying_help)
            icon = null
        }
        state.phase == Phase.ERROR -> {
            title = state.error ?: stringResource(R.string.error_identify)
            text = stringResource(R.string.error_identify_help)
            icon = R.drawable.ic_refresh
        }
        otherName != null -> {
            title = stringResource(R.string.card_of_other_game, otherName)
            text = stringResource(R.string.card_of_other_game_help)
            icon = R.drawable.ic_card
        }
        result?.notACard == true -> {
            title = stringResource(R.string.not_a_card)
            text = stringResource(R.string.not_a_card_help)
            icon = R.drawable.ic_card
        }
        else -> {
            title = stringResource(R.string.card_not_found)
            text = listOfNotNull(
                read?.let { stringResource(R.string.read_text, it) },
                stringResource(R.string.scan_tips),
                stringResource(if (torchHint) R.string.scan_tips_light_torch else R.string.scan_tips_light).takeIf { state.failures >= 2 },
            ).joinToString("\n")
            icon = R.drawable.ic_search
        }
    }
    val failed = state.phase == Phase.NOT_FOUND || state.phase == Phase.ERROR

    Surface(
        shape = RoundedCornerShape(topStart = 32.dp, topEnd = 32.dp),
        color = MaterialTheme.colorScheme.surfaceContainerLow,
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(
            Modifier.padding(horizontal = 24.dp, vertical = 20.dp).semantics { liveRegion = LiveRegionMode.Polite },
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(16.dp), verticalAlignment = Alignment.CenterVertically) {
                Box(
                    Modifier.size(48.dp).clip(CircleShape).background(
                        if (failed) MaterialTheme.colorScheme.errorContainer else MaterialTheme.colorScheme.primaryContainer,
                    ),
                    contentAlignment = Alignment.Center,
                ) {
                    val tint = if (failed) MaterialTheme.colorScheme.onErrorContainer else MaterialTheme.colorScheme.onPrimaryContainer
                    if (icon == null) {
                        CircularProgressIndicator(Modifier.size(24.dp), color = tint, strokeWidth = 3.dp)
                    } else {
                        ZIcon(icon, null, tint = tint)
                    }
                }
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(title, style = MaterialTheme.typography.titleLarge)
                    text?.let { Text(it, style = MaterialTheme.typography.bodyLarge, color = MaterialTheme.colorScheme.onSurfaceVariant) }
                }
            }
            if (failed) {
                if (otherGame != null && otherName != null) {
                    // Scan again with the card's game selected.
                    GoldButton(stringResource(R.string.switch_to_game, otherName), {
                        onGame(otherGame)
                        onRetry()
                    })
                } else {
                    GoldButton(stringResource(R.string.try_again), onRetry)
                }
                TextButton(onClick = onSearch, modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp)) {
                    Text(stringResource(R.string.search_by_name), style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.onSurface)
                }
            }
        }
    }
}

private tailrec fun Context.findActivity(): Activity? = when (this) {
    is Activity -> this
    is ContextWrapper -> baseContext.findActivity()
    else -> null
}
