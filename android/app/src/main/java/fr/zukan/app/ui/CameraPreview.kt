package fr.zukan.app.ui

import android.util.Log
import androidx.camera.core.Camera
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import fr.zukan.app.R
import fr.zukan.app.data.OcrLineIn
import fr.zukan.app.data.OcrScript
import fr.zukan.app.scan.GlareMeter
import fr.zukan.app.scan.ScanPicture
import fr.zukan.app.scan.TextAnalyzer
import java.util.concurrent.Executors

private const val TAG = "CameraPreview"

/** Back camera (else the front one) preview with on-device text recognition feeding
 * [onFrame]. A camera that cannot start goes to [onError] instead of crashing. */
@Composable
fun CameraPreview(
    script: OcrScript,
    paused: Boolean,
    onFrame: (List<OcrLineIn>) -> Boolean,
    onIdentify: (List<OcrLineIn>, ScanPicture?) -> Unit,
    onAsianFrame: (List<OcrLineIn>) -> Boolean,
    modifier: Modifier = Modifier,
    torch: Boolean = false,
    // Whether the camera has a torch, once bound.
    onTorchAvailable: (Boolean) -> Unit = {},
    glare: () -> GlareMeter? = { null },
    wantPicture: () -> Boolean = { false },
    onError: (String) -> Unit = {},
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    // TextureView mode: composes correctly under the overlays drawn on top of the preview.
    val previewView = remember { PreviewView(context).apply { implementationMode = PreviewView.ImplementationMode.COMPATIBLE } }
    val analyzer = remember(script) { TextAnalyzer(script, onFrame, onIdentify, onAsianFrame, glare, wantPicture) }
    analyzer.paused = paused
    var camera by remember { mutableStateOf<Camera?>(null) }
    val reportError by rememberUpdatedState(onError)
    val reportTorch by rememberUpdatedState(onTorchAvailable)

    DisposableEffect(lifecycleOwner, analyzer) {
        val executor = Executors.newSingleThreadExecutor()
        val future = ProcessCameraProvider.getInstance(context)
        // Left before the camera was ready (or quickly back): nothing is bound afterwards.
        var active = true
        var bound: ProcessCameraProvider? = null
        val preview = Preview.Builder().build().also { it.surfaceProvider = previewView.surfaceProvider }
        // 1280x720 is plenty for card text and keeps recognition fast.
        val analysis = ImageAnalysis.Builder()
            .setResolutionSelector(
                ResolutionSelector.Builder()
                    .setResolutionStrategy(ResolutionStrategy(android.util.Size(1280, 720), ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER))
                    .build(),
            )
            .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
            .build()
            .also { it.setAnalyzer(executor, analyzer) }
        future.addListener({
            if (!active) return@addListener
            try {
                val provider = future.get()
                val selector = when {
                    provider.hasCamera(CameraSelector.DEFAULT_BACK_CAMERA) -> CameraSelector.DEFAULT_BACK_CAMERA
                    // Tablets and some phones only have a front camera.
                    provider.hasCamera(CameraSelector.DEFAULT_FRONT_CAMERA) -> CameraSelector.DEFAULT_FRONT_CAMERA
                    else -> null
                }
                if (selector == null) {
                    reportError(context.getString(R.string.camera_none))
                    return@addListener
                }
                camera = provider.bindToLifecycle(lifecycleOwner, selector, preview, analysis).also {
                    reportTorch(it.cameraInfo.hasFlashUnit())
                }
                bound = provider
            } catch (e: Exception) {
                // In use by another app, closed by the system, unsupported...
                Log.w(TAG, "Camera could not start", e)
                reportError(context.getString(R.string.camera_failed))
            }
        }, ContextCompat.getMainExecutor(context))
        onDispose {
            active = false
            camera = null
            // Only this screen's use cases, never waiting for the provider here.
            bound?.unbind(preview, analysis)
            analysis.clearAnalyzer()
            // Closed once the frame being read is done, on the analysis thread.
            executor.execute { analyzer.close() }
            executor.shutdown()
        }
    }
    LaunchedEffect(camera, torch) {
        camera?.takeIf { it.cameraInfo.hasFlashUnit() }?.cameraControl?.enableTorch(torch)
    }
    AndroidView(factory = { previewView }, modifier = modifier)
}
