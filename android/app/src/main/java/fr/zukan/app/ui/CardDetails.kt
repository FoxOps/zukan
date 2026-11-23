package fr.zukan.app.ui

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.heading
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.dp
import coil3.ImageLoader
import fr.zukan.app.R
import fr.zukan.app.data.GameOut
import fr.zukan.app.data.PrintingOut
import fr.zukan.app.data.Settings

/** The tray of a card: the scanner's result, or a card opened from the collection or search
 * (over that tab, without the camera; closing it goes back to the list as it was). */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun CardSheet(
    title: String,
    onDismiss: () -> Unit,
    snackbar: SnackbarHostState,
    content: @Composable () -> Unit,
) {
    ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
        containerColor = MaterialTheme.colorScheme.surfaceContainerLow,
        shape = RoundedCornerShape(topStart = 32.dp, topEnd = 32.dp),
    ) {
        Box {
            Column {
                Row(Modifier.padding(horizontal = 24.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        title,
                        style = MaterialTheme.typography.headlineSmall,
                        modifier = Modifier.weight(1f).semantics { heading() },
                    )
                    IconButton(onClick = onDismiss) { ZIcon(R.drawable.ic_close, stringResource(R.string.close)) }
                }
                content()
            }
            // The tray opens in a window of its own above the screen's snackbar:
            // show "Added …", Undo and errors in it too.
            SnackbarHost(snackbar, Modifier.align(Alignment.BottomCenter))
        }
    }
}

/** A card opened by hand: loading, failure with retry, then the result panel. */
@Composable
fun CardDetailsSheet(
    scan: ScanViewModel,
    details: DetailsState,
    games: List<GameOut>,
    settings: Settings,
    priceSources: List<String>,
    imageUrl: (String?) -> String?,
    imageLoader: ImageLoader,
    snackbar: SnackbarHostState,
) {
    CardSheet(stringResource(R.string.card_details), scan::closeDetails, snackbar) {
        val card = details.card
        when {
            card != null -> ResultPanel(
                state = card,
                games = games,
                settings = settings,
                priceSources = priceSources,
                imageUrl = imageUrl,
                imageLoader = imageLoader,
                onCandidate = { scan.selectCandidate(Panel.DETAILS, it) },
                onPrinting = { p: PrintingOut -> scan.selectPrinting(Panel.DETAILS, p) },
                searchPrintings = scan::searchPrintings,
                onAdjust = { f, c, l, d -> scan.adjust(Panel.DETAILS, f, c, l, d) },
                onClose = scan::closeDetails,
                scanNext = false,
            )
            details.error != null -> MessageCard(
                stringResource(R.string.error_title),
                details.error,
                Modifier.padding(24.dp),
                action = { OutlinedButton(onClick = scan::retryDetails) { Text(stringResource(R.string.try_again)) } },
            )
            else -> Box(Modifier.fillMaxWidth().padding(48.dp), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        }
    }
}
