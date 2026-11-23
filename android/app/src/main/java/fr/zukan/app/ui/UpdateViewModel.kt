package fr.zukan.app.ui

import android.app.Application
import android.content.Context
import android.content.Intent
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
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
import fr.zukan.app.data.InvalidReleaseException
import fr.zukan.app.data.NoSpaceException
import fr.zukan.app.data.TooLargeException
import fr.zukan.app.data.UpdatePolicy
import fr.zukan.app.data.Versions
import fr.zukan.app.data.userMessage
import java.io.File
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.withContext
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
        val previous = download
        _state.value = UpdateState.Downloading(release, 0f)
        download = viewModelScope.launch {
            // A cancelled download cleans up first: it must not delete this one's file.
            previous?.cancelAndJoin()
            try {
                val file = downloader.download(release) { p -> _state.value = UpdateState.Downloading(release, p) }
                // Never handed to the installer unless it is this app, this version, signed
                // by the same key as the installed one.
                if (!withContext(Dispatchers.IO) { Installer.matches(app, file, release.version) }) {
                    file.delete()
                    throw PackageMismatchException()
                }
                _state.value = UpdateState.Ready(release, file)
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                val message = when (e) {
                    is ChecksumException -> app.getString(R.string.update_checksum)
                    is TooLargeException -> app.getString(R.string.update_too_large)
                    is NoSpaceException -> app.getString(R.string.update_no_space)
                    is InvalidReleaseException, is PackageMismatchException -> app.getString(R.string.update_invalid)
                    else -> e.userMessage(app)
                }
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
        // Kept: a new download waits for this one's cleanup.
        download?.cancel()
        _state.value = UpdateState.Idle
    }
}

/** The downloaded APK is not an update of this app. */
class PackageMismatchException : java.io.IOException("Not an update of this app")

object Installer {
    /** [apk] is this app ([version], same package) signed with the installed app's keys. */
    @Suppress("DEPRECATION")
    fun matches(context: Context, apk: File, version: String): Boolean {
        val pm = context.packageManager
        val flags = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) PackageManager.GET_SIGNING_CERTIFICATES else PackageManager.GET_SIGNATURES
        val archive = pm.getPackageArchiveInfo(apk.path, flags) ?: return false
        if (archive.packageName != context.packageName || Versions.compare(archive.versionName ?: "", version) != 0) return false
        val installed = runCatching { pm.getPackageInfo(context.packageName, flags) }.getOrNull() ?: return false
        val signers = { info: PackageInfo ->
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                info.signingInfo?.apkContentsSigners?.map { it.toCharsString() }?.toSet()
            } else {
                info.signatures?.map { it.toCharsString() }?.toSet()
            }
        }
        val mine = signers(installed)
        return !mine.isNullOrEmpty() && signers(archive) == mine
    }

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
