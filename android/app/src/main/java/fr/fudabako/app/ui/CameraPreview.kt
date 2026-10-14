package fr.fudabako.app.ui

import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.Preview
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.viewinterop.AndroidView
import androidx.core.content.ContextCompat
import androidx.lifecycle.compose.LocalLifecycleOwner
import fr.fudabako.app.data.OcrScript
import fr.fudabako.app.data.OcrLineIn
import fr.fudabako.app.scan.TextAnalyzer
import java.util.concurrent.Executors

/** Back camera preview with on-device text recognition feeding [onLines]. */
@Composable
fun CameraPreview(
    script: OcrScript,
    paused: Boolean,
    onFrame: (List<OcrLineIn>) -> Boolean,
    onIdentify: (List<OcrLineIn>) -> Unit,
    onAsianFrame: (List<OcrLineIn>) -> Boolean,
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val lifecycleOwner = LocalLifecycleOwner.current
    // TextureView mode: composes correctly under the overlays drawn on top of the preview.
    val previewView = remember { PreviewView(context).apply { implementationMode = PreviewView.ImplementationMode.COMPATIBLE } }
    val analyzer = remember(script) { TextAnalyzer(script, onFrame, onIdentify, onAsianFrame) }
    analyzer.paused = paused

    DisposableEffect(lifecycleOwner, analyzer) {
        val executor = Executors.newSingleThreadExecutor()
        val future = ProcessCameraProvider.getInstance(context)
        future.addListener({
            val provider = future.get()
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
            provider.unbindAll()
            provider.bindToLifecycle(lifecycleOwner, CameraSelector.DEFAULT_BACK_CAMERA, preview, analysis)
        }, ContextCompat.getMainExecutor(context))
        onDispose {
            runCatching { future.get().unbindAll() }
            executor.shutdown()
            analyzer.close()
        }
    }
    AndroidView(factory = { previewView }, modifier = modifier)
}
