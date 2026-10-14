plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
}

// Release signing comes from the environment (CI secrets); without it, release builds are
// unsigned and debug builds use the local debug key.
val keystorePath: String? = providers.environmentVariable("ANDROID_KEYSTORE_PATH").orNull

android {
    namespace = "fr.fudabako.app"
    compileSdk = 37

    defaultConfig {
        applicationId = "fr.fudabako.app"
        minSdk = 26
        targetSdk = 37
        // CI passes -PversionCode / -PversionName (prod: from the release version).
        versionCode = providers.gradleProperty("versionCode").orNull?.toInt() ?: 1
        versionName = providers.gradleProperty("versionName").orNull ?: "0.4.0"
        resValue("string", "app_name", "Fudabako")
        redirectScheme("fr.fudabako.app")
    }

    signingConfigs {
        if (keystorePath != null) {
            create("release") {
                storeFile = file(keystorePath)
                storePassword = providers.environmentVariable("ANDROID_KEYSTORE_PASSWORD").get()
                keyAlias = providers.environmentVariable("ANDROID_KEY_ALIAS").get()
                keyPassword = providers.environmentVariable("ANDROID_KEY_PASSWORD").get()
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
            signingConfig = signingConfigs.findByName("release")
        }
        // Dev builds install next to the released app ("Fudabako dev").
        debug {
            applicationIdSuffix = ".dev"
            versionNameSuffix = providers.gradleProperty("versionNameSuffix").orNull ?: "-dev"
            resValue("string", "app_name", "Fudabako dev")
            redirectScheme("fr.fudabako.app.dev")
            // Same key as releases in CI, so successive dev builds update each other.
            signingConfigs.findByName("release")?.let { signingConfig = it }
        }
    }
    // English (default, res/values) and French (res/values-fr). The generated locale config
    // lists them in the system's per-app language settings (Android 13+).
    androidResources {
        generateLocaleConfig = true
        localeFilters += listOf("en", "fr")
    }
    buildFeatures {
        compose = true
        buildConfig = true
        resValues = true
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.navigation.compose)
    implementation(libs.androidx.datastore.preferences)
    implementation(platform(libs.compose.bom))
    implementation(libs.compose.ui)
    implementation(libs.compose.ui.tooling.preview)
    implementation(libs.compose.material3)
    implementation(libs.compose.material.icons)
    debugImplementation(libs.compose.ui.tooling)
    implementation(libs.camera.camera2)
    implementation(libs.camera.lifecycle)
    implementation(libs.camera.view)
    // Bundled models: scanning works without Google Play services downloads.
    implementation(libs.mlkit.text.latin)
    implementation(libs.mlkit.text.japanese)
    implementation(libs.mlkit.text.chinese)
    implementation(libs.mlkit.text.korean)
    implementation(libs.kotlinx.serialization.json)
    implementation(libs.kotlinx.coroutines.android)
    implementation(libs.okhttp)
    implementation(libs.retrofit)
    implementation(libs.retrofit.kotlinx.serialization)
    implementation(libs.appauth)
    implementation(libs.coil.compose)
    implementation(libs.coil.okhttp)

    testImplementation(libs.junit)
    testImplementation(libs.kotlinx.coroutines.test)
    testImplementation(libs.okhttp.mockwebserver)
}

/** SSO redirect `<scheme>:/oauth2redirect`: register it in your identity provider. */
fun com.android.build.api.dsl.VariantDimension.redirectScheme(scheme: String) {
    manifestPlaceholders["appAuthRedirectScheme"] = scheme
    buildConfigField("String", "REDIRECT_SCHEME", "\"$scheme\"")
}
