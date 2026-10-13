package fr.fudabako.app.ui

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
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
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import fr.fudabako.app.data.ServerUrl
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
        Text("Fudabako", style = MaterialTheme.typography.displaySmall)
        Text("札箱 · card box", style = MaterialTheme.typography.titleMedium, color = MaterialTheme.colorScheme.secondary)
        Spacer(Modifier.height(16.dp))

        if (!connected) {
            OutlinedTextField(
                value = server,
                onValueChange = { server = it },
                label = { Text("Server address") },
                placeholder = { Text("cards.example.org or 192.168.1.10:8000") },
                singleLine = true,
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Go),
                modifier = Modifier.fillMaxWidth(),
            )
            Button(onClick = { session.connect(server) }, enabled = server.isNotBlank() && !state.busy, modifier = Modifier.fillMaxWidth()) {
                Text("Connect")
            }
        } else {
            Text(state.serverUrl, style = MaterialTheme.typography.bodyMedium)
            if (!ServerUrl.isSecure(state.serverUrl)) {
                Text(
                    "Not encrypted (HTTP): use only on your home network or a VPN.",
                    color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodySmall,
                )
            }
            TextButton(onClick = session::disconnect) { Text("Change server") }

            if (state.providers.localLoginEnabled) {
                OutlinedTextField(
                    value = username, onValueChange = { username = it }, label = { Text("User") },
                    singleLine = true, modifier = Modifier.fillMaxWidth(),
                )
                OutlinedTextField(
                    value = password, onValueChange = { password = it }, label = { Text("Password") },
                    singleLine = true, visualTransformation = PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                    modifier = Modifier.fillMaxWidth(),
                )
                Button(
                    onClick = { session.login(username, password) },
                    enabled = username.isNotBlank() && password.isNotEmpty() && !state.busy,
                    modifier = Modifier.fillMaxWidth(),
                ) { Text("Log in") }
            }
            val sso = state.providers.providers.filter { it.mobileClientId != null }
            if (sso.isNotEmpty() && state.providers.localLoginEnabled) HorizontalDivider(Modifier.padding(vertical = 8.dp))
            sso.forEach { provider ->
                OutlinedButton(
                    onClick = { scope.launch { session.ssoIntent(provider)?.let(ssoLauncher::launch) } },
                    enabled = !state.busy,
                    modifier = Modifier.fillMaxWidth(),
                ) { Text("Sign in with ${provider.displayName}") }
            }
        }
        state.error?.let { Text(it, color = MaterialTheme.colorScheme.error) }
    }
}
