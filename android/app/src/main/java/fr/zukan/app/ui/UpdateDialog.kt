package fr.zukan.app.ui

import android.text.format.Formatter
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import fr.zukan.app.BuildConfig
import fr.zukan.app.R

/** Update offer, download progress and install step; nothing shown otherwise. */
@Composable
fun UpdateDialog(updates: UpdateViewModel, state: UpdateState) {
    val context = LocalContext.current
    when (state) {
        is UpdateState.Available -> AlertDialog(
            onDismissRequest = updates::dismiss,
            title = { Text(stringResource(R.string.update_available_title)) },
            text = {
                Text(
                    stringResource(
                        R.string.update_available_text,
                        state.release.version,
                        BuildConfig.VERSION_NAME,
                        Formatter.formatShortFileSize(context, state.release.size),
                    ),
                )
            },
            confirmButton = { TextButton(onClick = updates::download) { Text(stringResource(R.string.update_download)) } },
            dismissButton = {
                Column(horizontalAlignment = androidx.compose.ui.Alignment.End) {
                    TextButton(onClick = updates::dismiss) { Text(stringResource(R.string.update_later)) }
                    TextButton(onClick = updates::skip) { Text(stringResource(R.string.update_skip)) }
                }
            },
        )
        is UpdateState.Downloading -> AlertDialog(
            onDismissRequest = {},
            title = { Text(stringResource(R.string.update_downloading, state.release.version)) },
            text = { LinearProgressIndicator(progress = { state.progress }, modifier = Modifier.fillMaxWidth()) },
            confirmButton = {},
            dismissButton = { TextButton(onClick = updates::dismiss) { Text(stringResource(R.string.update_cancel)) } },
        )
        is UpdateState.Ready -> {
            var asked by remember { mutableStateOf(false) }
            AlertDialog(
                onDismissRequest = updates::dismiss,
                title = { Text(stringResource(R.string.update_ready_title)) },
                text = {
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        Text(stringResource(R.string.update_ready_text, state.release.version))
                        if (asked && !Installer.allowed(context)) {
                            Text(stringResource(R.string.update_permission), color = MaterialTheme.colorScheme.error)
                        }
                    }
                },
                confirmButton = {
                    TextButton(onClick = {
                        if (Installer.allowed(context)) {
                            Installer.install(context, state.file)
                        } else {
                            asked = true
                            Installer.openPermission(context)
                        }
                    }) { Text(stringResource(R.string.update_install)) }
                },
                dismissButton = { TextButton(onClick = updates::dismiss) { Text(stringResource(R.string.update_later)) } },
            )
        }
        is UpdateState.Failed -> if (state.release != null) {
            AlertDialog(
                onDismissRequest = updates::dismiss,
                title = { Text(stringResource(R.string.update_available_title)) },
                text = { Text(state.message) },
                confirmButton = { TextButton(onClick = updates::download) { Text(stringResource(R.string.update_retry)) } },
                dismissButton = { TextButton(onClick = updates::dismiss) { Text(stringResource(R.string.update_later)) } },
            )
        }
        else -> Unit
    }
}
