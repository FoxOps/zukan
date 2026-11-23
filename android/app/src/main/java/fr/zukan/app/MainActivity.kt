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
import androidx.compose.runtime.saveable.rememberSaveableStateHolder
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
import fr.zukan.app.ui.CardDetailsSheet
import fr.zukan.app.ui.CollectionScreen
import fr.zukan.app.ui.CollectionViewModel
import fr.zukan.app.ui.SearchViewModel
import fr.zukan.app.ui.ZukanTheme
import fr.zukan.app.ui.LoginScreen
import fr.zukan.app.ui.ScanScreen
import fr.zukan.app.ui.ScanViewModel
import fr.zukan.app.ui.SearchScreen
import fr.zukan.app.ui.SessionViewModel
import fr.zukan.app.ui.SettingsScreen
import fr.zukan.app.ui.ShoppingScreen
import fr.zukan.app.ui.UpdateDialog
import fr.zukan.app.ui.UpdateViewModel
import fr.zukan.app.ui.ZIcon

class MainActivity : ComponentActivity() {
    private val session: SessionViewModel by viewModels()
    private val scan: ScanViewModel by viewModels()
    private val updates: UpdateViewModel by viewModels()
    private val collection: CollectionViewModel by viewModels()
    private val search: SearchViewModel by viewModels()

    override fun attachBaseContext(newBase: Context) = super.attachBaseContext(AppLanguage.wrap(newBase))

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent { ZukanTheme { App(session, scan, updates, collection, search, application as ZukanApp) } }
    }
}

private enum class Tab(@StringRes val label: Int, @DrawableRes val icon: Int) {
    COLLECTION(R.string.tab_collection, R.drawable.ic_collection),
    SCAN(R.string.tab_scan, R.drawable.ic_scan),
    SEARCH(R.string.tab_search, R.drawable.ic_search),
    // Decks module only.
    SHOPPING(R.string.tab_shopping, R.drawable.ic_checklist),
    SETTINGS(R.string.tab_settings, R.drawable.ic_settings),
}

/** Four or five destinations on paper / chocolate, the current one on a gold pill. */
@Composable
private fun ZukanNavigationBar(tab: Tab, tabs: List<Tab>, onTab: (Tab) -> Unit) {
    Column {
        HorizontalDivider(color = MaterialTheme.colorScheme.outline)
        NavigationBar(containerColor = MaterialTheme.colorScheme.surfaceContainerLow) {
            tabs.forEach { t ->
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
private fun App(
    session: SessionViewModel,
    scan: ScanViewModel,
    updates: UpdateViewModel,
    collection: CollectionViewModel,
    search: SearchViewModel,
    app: ZukanApp,
) {
    val state by session.state.collectAsStateWithLifecycle()
    val settings by session.settings.collectAsStateWithLifecycle()
    val scanState by scan.state.collectAsStateWithLifecycle()
    val details by scan.details.collectAsStateWithLifecycle()
    val client by app.client.collectAsStateWithLifecycle()
    val updateState by updates.state.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val activity = LocalActivity.current
    val undoLabel = stringResource(R.string.undo)
    // Card images go through the authenticated HTTP client; caches outlive the client. The
    // loader of an ended session stops (its pictures are no longer asked for).
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
    // Not on leaving the screen (rotation): the memory cache is shared.
    val previousLoader = remember { arrayOfNulls<ImageLoader>(1) }
    LaunchedEffect(imageLoader) {
        previousLoader[0]?.takeIf { it !== imageLoader }?.shutdown()
        previousLoader[0] = imageLoader
    }
    val imageUrl = { path: String? -> client?.imageUrl(path) }

    when {
        state.loading -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { CircularProgressIndicator() }
        !state.loggedIn -> Scaffold { padding -> Box(Modifier.padding(padding)) { LoginScreen(session, state) } }
        else -> {
            // The collection is the home screen; back from another tab returns to it.
            var tab by rememberSaveable { mutableStateOf(Tab.COLLECTION) }
            // Shopping lists come from decks: with the Decks module only.
            val tabs = Tab.entries.filter { it != Tab.SHOPPING || "decks" in state.modules }
            LaunchedEffect(tabs) { if (tab !in tabs) tab = Tab.COLLECTION }
            BackHandler(enabled = tab != Tab.COLLECTION) { tab = Tab.COLLECTION }
            val snackbar = remember { SnackbarHostState() }
            val tabStates = rememberSaveableStateHolder()
            // Offers a newer app (asks before downloading anything).
            LaunchedEffect(Unit) { updates.checkAutomatically() }
            // Settings shared with the web UI may have changed there.
            LifecycleEventEffect(Lifecycle.Event.ON_RESUME) { session.refreshAccount() }
            // Interface language: one picked on the account (shared with the web UI), else the
            // phone's (the server took it from Accept-Language for card names and pictures).
            LaunchedEffect(state.serverLanguage, state.languageChosen) {
                val server = state.serverLanguage?.takeIf { it in AppLanguage.SUPPORTED } ?: return@LaunchedEffect
                if (state.languageChosen) {
                    if (server != AppLanguage.chosen(context)) activity?.let { AppLanguage.choose(it, server) }
                } else if (AppLanguage.chosen(context) != null) {
                    activity?.let { AppLanguage.choose(it, null) }
                }
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
                bottomBar = { ZukanNavigationBar(tab, tabs) { tab = it } },
            ) { padding ->
                Box(Modifier.padding(padding)) {
                    // Each tab keeps its saved state (scroll position, open filters) while
                    // another one is shown.
                    tabStates.SaveableStateProvider(tab.name) {
                    when (tab) {
                        Tab.SCAN -> ScanScreen(scan, scanState, state.catalog, settings, state.priceSources, imageUrl, imageLoader, snackbar, onSearch = { tab = Tab.SEARCH }) { game ->
                            session.updateSettings { it.copy(game = game) }
                        }
                        Tab.COLLECTION -> CollectionScreen(
                            collection,
                            client?.api,
                            // Games shown in the settings, like scan and search.
                            state.catalog,
                            state.games.flatMap { it.priceSources }.firstOrNull { it.id == state.priceSources.firstOrNull() },
                            scanState.stock,
                            settings,
                            imageUrl,
                            imageLoader,
                            onGrid = { grid -> session.updateSettings { it.copy(collectionGrid = grid) } },
                            onAdjust = { item, delta -> scan.adjustItem(item, delta) },
                            // Over the collection: closing the card goes back to the same place.
                            onOpen = scan::openItem,
                        )
                        Tab.SEARCH -> SearchScreen(search, client?.api, settings.game, state.catalog, imageUrl, imageLoader, onScan = { tab = Tab.SCAN }, onPick = scan::openCard)
                        Tab.SHOPPING -> ShoppingScreen(client?.api)
                        Tab.SETTINGS -> SettingsScreen(session, state, settings, updates, updateState)
                    }
                    }
                }
            }
            // A card opened from the collection or search: no camera, no tab change.
            details?.let { d ->
                CardDetailsSheet(scan, d, state.catalog, settings, state.priceSources, imageUrl, imageLoader, snackbar)
            }
        }
    }
}
