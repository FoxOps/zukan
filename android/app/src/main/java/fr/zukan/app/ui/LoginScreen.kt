package fr.zukan.app.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.Image
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import fr.zukan.app.R
import fr.zukan.app.data.ServerUrl
import kotlinx.coroutines.launch

@Composable
fun LoginScreen(session: SessionViewModel, state: SessionState) {
    val scope = rememberCoroutineScope()
    val ssoLauncher = rememberLauncherForActivityResult(ActivityResultContracts.StartActivityForResult()) {
        session.ssoResult(it.data)
    }
    var server by rememberSaveable { mutableStateOf(state.serverUrl) }
    var username by rememberSaveable { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    val connected = state.providers != null && state.serverUrl.isNotEmpty()

    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).imePadding().padding(24.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Spacer(Modifier.height(32.dp))
        Image(
            painterResource(R.drawable.zukan_logo),
            contentDescription = "Zukan",
            modifier = Modifier.fillMaxWidth(0.75f),
        )
        Text(stringResource(R.string.tagline), style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.secondary)
        Spacer(Modifier.height(16.dp))

        if (!connected) {
            OutlinedTextField(
                value = server,
                onValueChange = { server = it },
                label = { Text(stringResource(R.string.server_address)) },
                placeholder = { Text(stringResource(R.string.server_address_hint)) },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Go),
                modifier = Modifier.fillMaxWidth(),
            )
            Button(onClick = { session.connect(server) }, colors = ctaColors(), enabled = server.isNotBlank() && !state.busy, modifier = Modifier.fillMaxWidth()) {
                Text(stringResource(R.string.connect))
            }
        } else {
            Text(state.serverUrl, style = MaterialTheme.typography.bodyMedium)
            if (!ServerUrl.isSecure(state.serverUrl)) {
                Text(
                    stringResource(R.string.not_encrypted),
                    color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            TextButton(onClick = session::disconnect) { Text(stringResource(R.string.change_server)) }

            if (state.providers.localLoginEnabled) {
                OutlinedTextField(
                    value = username, onValueChange = { username = it }, label = { Text(stringResource(R.string.user)) },
                    singleLine = true, modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = password, onValueChange = { password = it }, label = { Text(stringResource(R.string.password)) },
                    singleLine = true, visualTransformation = PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                    modifier = Modifier.fillMaxWidth(),
                )
                Button(
                    colors = ctaColors(),
                    onClick = { session.login(username, password) },
                    enabled = username.isNotBlank() && password.isNotEmpty() && !state.busy,
                    modifier = Modifier.fillMaxWidth(),
                ) { Text(stringResource(R.string.log_in)) }
            }
            val sso = state.providers.providers.filter { it.mobileClientId != null }
            if (sso.isNotEmpty() && state.providers.localLoginEnabled) HorizontalDivider(Modifier.padding(vertical = 8.dp))
            val local = state.providers.localLoginEnabled
            sso.forEach { provider ->
                // One provider: a plain "Log in" (its name means nothing on a phone); with the
                // local form too, "with SSO" tells both apart. Several: their names.
                val label = when {
                    sso.size > 1 -> stringResource(R.string.sign_in_with, provider.displayName)
                    local -> stringResource(R.string.log_in_sso)
                    else -> stringResource(R.string.log_in)
                }
                val start = { scope.launch { session.ssoIntent(provider)?.let(ssoLauncher::launch) }; Unit }
                if (!local && sso.size == 1) {
                    Button(colors = ctaColors(), onClick = start, enabled = !state.busy, modifier = Modifier.fillMaxWidth()) { Text(label) }
                } else {
                    OutlinedButton(onClick = start, enabled = !state.busy, modifier = Modifier.fillMaxWidth()) { Text(label) }
                }
            }
        }
        state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
    }
}
