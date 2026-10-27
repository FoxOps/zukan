package fr.zukan.app.ui

import android.app.Application
import android.content.Context
import android.content.Intent
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import androidx.core.net.toUri
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import fr.zukan.app.BuildConfig
import fr.zukan.app.R
import fr.zukan.app.ZukanApp
import fr.zukan.app.data.AndroidReleaseOut
import fr.zukan.app.data.ApkDownloader
import fr.zukan.app.data.ChecksumException
import fr.zukan.app.data.UpdatePolicy
import fr.zukan.app.data.userMessage
import java.io.File
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Job
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import retrofit2.HttpException

sealed interface UpdateState {
    data object Idle : UpdateState
    data object Checking : UpdateState
    data object UpToDate : UpdateState
    /** Offered: nothing is downloaded until the user says so. */
    data class Available(val release: AndroidReleaseOut) : UpdateState
    data class Downloading(val release: AndroidReleaseOut, val progress: Float) : UpdateState
    data class Ready(val release: AndroidReleaseOut, val file: File) : UpdateState
    data class Failed(val message: String, val release: AndroidReleaseOut? = null) : UpdateState
}

/**
 * App updates from the server's latest Android release (GitHub): checked once a day and
 * from Settings, offered in a dialog, downloaded only once the user accepts, then handed to
 * the system installer (Android asks for confirmation; apps installed outside a store
 * cannot update silently).
 */
class UpdateViewModel(application: Application) : AndroidViewModel(application) {
    private val app = application as ZukanApp
    private val downloader = ApkDownloader(File(application.cacheDir, "updates"))
    private val _state = MutableStateFlow<UpdateState>(UpdateState.Idle)
    val state: StateFlow<UpdateState> = _state.asStateFlow()
    private var download: Job? = null

    /** Dev builds are a separate app (`fr.zukan.app.dev`): a release APK cannot update them. */
    val supported = !BuildConfig.APPLICATION_ID.endsWith(".dev")

    /** At most once a day, after signing in. */
    fun checkAutomatically() {
        if (!supported || _state.value != UpdateState.Idle) return
        viewModelScope.launch {
            val (last, _) = app.store.updateCheck()
            if (UpdatePolicy.shouldCheck(last, System.currentTimeMillis())) check(manual = false)
        }
    }

    fun checkNow() {
        if (!supported) return
        viewModelScope.launch { check(manual = true) }
    }

    private suspend fun check(manual: Boolean) {
        val client = app.client.value ?: return
        if (manual) _state.value = UpdateState.Checking
        val result = runCatching { client.api.androidRelease() }
        app.store.markUpdateChecked(System.currentTimeMillis())
        val (_, skipped) = app.store.updateCheck()
        _state.value = result.fold(
            onSuccess = { release ->
                when {
                    UpdatePolicy.offer(release, BuildConfig.VERSION_NAME, skipped, manual) -> UpdateState.Available(release)
                    manual -> UpdateState.UpToDate
                    else -> UpdateState.Idle
                }
            },
            onFailure = { e ->
                when {
                    !manual -> UpdateState.Idle
                    // No release published (or GitHub unreachable from the server).
                    e is HttpException && e.code() == 404 -> UpdateState.UpToDate
                    else -> UpdateState.Failed(e.userMessage(app))
                }
            },
        )
    }

    fun download() {
        val release = when (val s = _state.value) {
            is UpdateState.Available -> s.release
            is UpdateState.Failed -> s.release ?: return
            else -> return
        }
        download = viewModelScope.launch {
            _state.value = UpdateState.Downloading(release, 0f)
            try {
                val file = downloader.download(release) { p -> _state.value = UpdateState.Downloading(release, p) }
                _state.value = UpdateState.Ready(release, file)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                val message = if (e is ChecksumException) app.getString(R.string.update_checksum) else e.userMessage(app)
                _state.value = UpdateState.Failed(app.getString(R.string.update_failed, message), release)
            }
        }
    }

    fun skip() {
        val release = (_state.value as? UpdateState.Available)?.release ?: return
        viewModelScope.launch { app.store.skipVersion(release.version) }
        _state.value = UpdateState.Idle
    }

    fun dismiss() {
        download?.cancel()
        download = null
        _state.value = UpdateState.Idle
    }
}

object Installer {
    /** Whether Android lets this app hand APKs to the installer ("Install unknown apps"). */
    fun allowed(context: Context): Boolean =
        Build.VERSION.SDK_INT < Build.VERSION_CODES.O || context.packageManager.canRequestPackageInstalls()

    /** Opens the "Install unknown apps" switch of this app. */
    fun openPermission(context: Context) {
        context.startActivity(
            Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, "package:${context.packageName}".toUri())
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
        )
    }

    /** Starts the system installer, which asks the user to confirm. */
    fun install(context: Context, file: File) {
        val uri = FileProvider.getUriForFile(context, "${context.packageName}.updates", file)
        context.startActivity(
            Intent(Intent.ACTION_VIEW)
                .setDataAndType(uri, "application/vnd.android.package-archive")
                .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK),
        )
    }
}
