package fr.zukan.app

import android.content.Context
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.LocalActivity
import androidx.activity.compose.BackHandler
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.annotation.DrawableRes
import androidx.annotation.StringRes
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.compose.LifecycleEventEffect
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import coil3.ImageLoader
import coil3.svg.SvgDecoder
import coil3.network.okhttp.OkHttpNetworkFetcherFactory
import fr.zukan.app.data.AppLanguage
import fr.zukan.app.ui.CollectionScreen
import fr.zukan.app.ui.ZukanTheme
import fr.zukan.app.ui.LoginScreen
import fr.zukan.app.ui.ScanScreen
import fr.zukan.app.ui.ScanViewModel
import fr.zukan.app.ui.SearchScreen
import fr.zukan.app.ui.SessionViewModel
import fr.zukan.app.ui.SettingsScreen
import fr.zukan.app.ui.UpdateDialog
import fr.zukan.app.ui.UpdateViewModel
import fr.zukan.app.ui.ZIcon

class MainActivity : ComponentActivity() {
    private val session: SessionViewModel by viewModels()
    private val scan: ScanViewModel by viewModels()
    private val updates: UpdateViewModel by viewModels()

    override fun attachBaseContext(newBase: Context) = super.attachBaseContext(AppLanguage.wrap(newBase))

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent { ZukanTheme { App(session, scan, updates, application as ZukanApp) } }
    }
}

private enum class Tab(@StringRes val label: Int, @DrawableRes val icon: Int) {
    COLLECTION(R.string.tab_collection, R.drawable.ic_collection),
    SCAN(R.string.tab_scan, R.drawable.ic_scan),
    SEARCH(R.string.tab_search, R.drawable.ic_search),
    SETTINGS(R.string.tab_settings, R.drawable.ic_settings),
}

/** Four destinations on paper / chocolate, the current one on a gold pill. */
@Composable
private fun ZukanNavigationBar(tab: Tab, onTab: (Tab) -> Unit) {
    Column {
        HorizontalDivider(color = MaterialTheme.colorScheme.outline)
        NavigationBar(containerColor = MaterialTheme.colorScheme.surfaceContainerLow) {
            Tab.entries.forEach { t ->
                NavigationBarItem(
                    selected = tab == t,
                    onClick = { onTab(t) },
                    icon = { ZIcon(t.icon, contentDescription = null) },
                    // One line: long labels (German "Einstellungen") on big fonts end with "…".
                    label = { Text(stringResource(t.label), fontWeight = if (tab == t) FontWeight.Bold else null, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                    colors = NavigationBarItemDefaults.colors(
                        indicatorColor = MaterialTheme.colorScheme.primaryContainer,
                        selectedIconColor = MaterialTheme.colorScheme.onPrimaryContainer,
                        selectedTextColor = MaterialTheme.colorScheme.onSurface,
                        unselectedIconColor = MaterialTheme.colorScheme.onSurfaceVariant,
                        unselectedTextColor = MaterialTheme.colorScheme.onSurfaceVariant,
                    ),
                )
            }
        }
    }
}

@Composable
private fun App(session: SessionViewModel, scan: ScanViewModel, updates: UpdateViewModel, app: ZukanApp) {
    val state by session.state.collectAsStateWithLifecycle()
    val settings by session.settings.collectAsStateWithLifecycle()
    val scanState by scan.state.collectAsStateWithLifecycle()
    val client by app.client.collectAsStateWithLifecycle()
    val updateState by updates.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val activity = LocalActivity.current
    val undoLabel = stringResource(R.string.undo)
    // Card images go through the authenticated HTTP client; caches outlive the client.
    val imageLoader = remember(client) {
        ImageLoader.Builder(context)
            .memoryCache { app.imageMemory }
            .diskCache { app.imageDisk }
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
            // The collection is the home screen; back from another tab returns to it.
            var tab by rememberSaveable { mutableStateOf(Tab.COLLECTION) }
            BackHandler(enabled = tab != Tab.COLLECTION) { tab = Tab.COLLECTION }
            val snackbar = remember { SnackbarHostState() }
            // Offers a newer app (asks before downloading anything).
            LaunchedEffect(Unit) { updates.checkAutomatically() }
            // Settings shared with the web UI may have changed there.
            LifecycleEventEffect(Lifecycle.Event.ON_RESUME) { session.refreshAccount() }
            // Interface language: the account's (shared with the web UI), whatever the phone's.
            LaunchedEffect(state.serverLanguage) {
                val server = state.serverLanguage?.takeIf { it in AppLanguage.SUPPORTED } ?: return@LaunchedEffect
                if (server != AppLanguage.chosen(context)) activity?.let { AppLanguage.choose(it, server) }
            }
            UpdateDialog(updates, updateState)
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
                bottomBar = { ZukanNavigationBar(tab) { tab = it } },
            ) { padding ->
                Box(Modifier.padding(padding)) {
                    when (tab) {
                        Tab.SCAN -> ScanScreen(scan, scanState, state.catalog, settings, state.priceSources, imageUrl, imageLoader, snackbar, onSearch = { tab = Tab.SEARCH }) { game ->
                            session.updateSettings { it.copy(game = game) }
                        }
                        Tab.COLLECTION -> CollectionScreen(
                            client?.api,
                            state.games,
                            state.games.flatMap { it.priceSources }.firstOrNull { it.id == state.priceSources.firstOrNull() },
                            scanState.stock,
                            settings,
                            imageUrl,
                            imageLoader,
                            onGrid = { grid -> session.updateSettings { it.copy(collectionGrid = grid) } },
                            onAdjust = { item, delta -> scan.adjustItem(item, delta) },
                            onOpen = { item ->
                                scan.showCard(item.cardId, item.printingId, item.language, item.finish)
                                tab = Tab.SCAN
                            },
                        )
                        Tab.SEARCH -> SearchScreen(client?.api, settings.game, state.catalog, imageUrl, imageLoader, onScan = { tab = Tab.SCAN }) { card ->
                            scan.showCard(card)
                            tab = Tab.SCAN
                        }
                        Tab.SETTINGS -> SettingsScreen(session, state, settings, updates, updateState)
                    }
                }
            }
        }
    }
}
