package fr.zukan.app

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CameraAlt
import androidx.compose.material.icons.filled.CollectionsBookmark
import androidx.compose.material.icons.filled.Search
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarDuration
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.SnackbarResult
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import coil3.ImageLoader
import coil3.svg.SvgDecoder
import coil3.network.okhttp.OkHttpNetworkFetcherFactory
import fr.zukan.app.ui.CollectionScreen
import fr.zukan.app.ui.ZukanTheme
import fr.zukan.app.ui.LoginScreen
import fr.zukan.app.ui.ScanScreen
import fr.zukan.app.ui.ScanViewModel
import fr.zukan.app.ui.SearchScreen
import fr.zukan.app.ui.SessionViewModel
import fr.zukan.app.ui.SettingsScreen

class MainActivity : ComponentActivity() {
    private val session: SessionViewModel by viewModels()
    private val scan: ScanViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent { ZukanTheme { App(session, scan, application as ZukanApp) } }
    }
}

private enum class Tab(@StringRes val label: Int) {
    SCAN(R.string.tab_scan),
    COLLECTION(R.string.tab_collection),
    SEARCH(R.string.tab_search),
    SETTINGS(R.string.tab_settings),
}

@Composable
private fun App(session: SessionViewModel, scan: ScanViewModel, app: ZukanApp) {
    val state by session.state.collectAsStateWithLifecycle()
    val settings by session.settings.collectAsStateWithLifecycle()
    val scanState by scan.state.collectAsStateWithLifecycle()
    val client by app.client.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val undoLabel = stringResource(R.string.undo)
    // Card images go through the authenticated HTTP client.
    val imageLoader = remember(client) {
        ImageLoader.Builder(context)
            .components {
                client?.let { c -> add(OkHttpNetworkFetcherFactory(callFactory = { c.http })) }
                // Game symbols and rarity pictograms are SVG files.
                add(SvgDecoder.Factory())
            }
            .build()
    }
    val imageUrl = { path: String? -> client?.imageUrl(path) }

    when {
        state.loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        !state.loggedIn -> Scaffold { padding -> Box(Modifier.padding(padding)) { LoginScreen(session, state) } }
        else -> {
            var tab by rememberSaveable { mutableStateOf(Tab.SCAN) }
            val snackbar = remember { SnackbarHostState() }
            LaunchedEffect(scanState.undo) {
                val undo = scanState.undo ?: return@LaunchedEffect
                val result = snackbar.showSnackbar(undo.text, actionLabel = undoLabel, duration = SnackbarDuration.Long)
                if (result == SnackbarResult.ActionPerformed) scan.undo() else scan.consumeUndo()
            }
            LaunchedEffect(scanState.message, state.error) {
                val message = scanState.message ?: state.error ?: return@LaunchedEffect
                snackbar.showSnackbar(message)
                scan.consumeMessage()
                session.clearError()
            }
            Scaffold(
                snackbarHost = { SnackbarHost(snackbar) },
                bottomBar = {
                    NavigationBar {
                        Tab.entries.forEach { t ->
                            NavigationBarItem(
                                selected = tab == t,
                                onClick = { tab = t },
                                icon = {
                                    Icon(
                                        when (t) {
                                            Tab.SCAN -> Icons.Default.CameraAlt
                                            Tab.COLLECTION -> Icons.Default.CollectionsBookmark
                                            Tab.SEARCH -> Icons.Default.Search
                                            Tab.SETTINGS -> Icons.Default.Settings
                                        },
                                        contentDescription = null,
                                    )
                                },
                                label = { Text(stringResource(t.label)) },
                            )
                        }
                    }
                },
            ) { padding ->
                Box(Modifier.padding(padding)) {
                    when (tab) {
                        Tab.SCAN -> ScanScreen(scan, scanState, state.games, settings, state.priceSources, imageUrl, imageLoader, snackbar) { game ->
                            session.updateSettings { it.copy(game = game) }
                        }
                        Tab.COLLECTION -> CollectionScreen(
                            client?.api,
                            state.games,
                            scanState.stockVersion,
                            imageUrl,
                            imageLoader,
                            onAdjust = { item, delta -> scan.adjustItem(item.printingId, item.finish, item.condition, item.language, delta) },
                            onOpen = { item ->
                                scan.showCard(item.cardId, item.printingId)
                                tab = Tab.SCAN
                            },
                        )
                        Tab.SEARCH -> SearchScreen(client?.api, settings.game, state.games, imageUrl, imageLoader) { card ->
                            scan.showCard(card)
                            tab = Tab.SCAN
                        }
                        Tab.SETTINGS -> SettingsScreen(session, state, settings)
                    }
                }
            }
        }
    }
}
