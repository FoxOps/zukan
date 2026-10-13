package fr.fudabako.app.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
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
import androidx.compose.ui.res.pluralStringResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import coil3.ImageLoader
import coil3.compose.AsyncImage
import fr.fudabako.app.R
import fr.fudabako.app.data.CardSummaryOut
import fr.fudabako.app.data.FudabakoApi
import fr.fudabako.app.data.GameOut
import fr.fudabako.app.data.userMessage
import kotlinx.coroutines.delay

/** Find a card by name when it cannot be scanned (damaged, foil glare, unusual layout). */
@Composable
fun SearchScreen(
    api: FudabakoApi?,
    game: String?,
    games: List<GameOut>,
    imageUrl: (String?) -> String?,
    imageLoader: ImageLoader,
    onPick: (CardSummaryOut) -> Unit,
) {
    var query by rememberSaveable { mutableStateOf("") }
    var results by remember { mutableStateOf<List<CardSummaryOut>>(emptyList()) }
    var error by remember { mutableStateOf<String?>(null) }
    val context = LocalContext.current

    LaunchedEffect(query, game) {
        if (api == null || query.trim().length < 2) {
            results = emptyList()
            return@LaunchedEffect
        }
        delay(300) // typing debounce
        runCatching { api.searchCards(query.trim(), game) }
            .onSuccess { results = it.items; error = null }
            .onFailure { error = it.userMessage(context) }
    }

    Column(Modifier.fillMaxSize().padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
        OutlinedTextField(
            value = query,
            onValueChange = { query = it },
            label = { Text(stringResource(R.string.search_hint)) },
            singleLine = true,
            modifier = Modifier.fillMaxWidth(),
        )
        error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
        LazyColumn(verticalArrangement = Arrangement.spacedBy(8.dp)) {
            items(results, key = { it.id }) { card ->
                Row(
                    Modifier.fillMaxWidth().clickable { onPick(card) }.padding(4.dp),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(12.dp),
                ) {
                    AsyncImage(
                        model = imageUrl(card.image),
                        contentDescription = null,
                        imageLoader = imageLoader,
                        modifier = Modifier.width(48.dp).aspectRatio(63f / 88f),
                    )
                    Column {
                        Text(card.name, style = MaterialTheme.typography.titleMedium)
                        Text(
                            pluralStringResource(
                                R.plurals.printing_count,
                                card.printingCount,
                                games.firstOrNull { it.id == card.gameId }?.name ?: card.gameId,
                                card.printingCount,
                            ),
                            style = MaterialTheme.typography.bodySmall,
                        )
                    }
                }
            }
        }
    }
}
