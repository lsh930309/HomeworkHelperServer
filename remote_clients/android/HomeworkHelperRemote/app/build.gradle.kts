import java.util.Properties

val localProperties = Properties().apply {
    val file = rootProject.file("local.properties")
    if (file.exists()) file.inputStream().use(::load)
}

fun localProperty(name: String, defaultValue: String = ""): String =
    localProperties.getProperty(name)?.trim().orEmpty().ifBlank { defaultValue }

fun gradleProperty(name: String): String =
    providers.gradleProperty(name).orNull?.trim().orEmpty()

fun localOrGradleProperty(name: String, defaultValue: String = ""): String =
    gradleProperty(name).ifBlank { localProperty(name) }.ifBlank { defaultValue }

fun localOrGradleIntProperty(name: String, defaultValue: Int): Int =
    localOrGradleProperty(name).toIntOrNull() ?: defaultValue

fun localSecretFile(name: String): String =
    listOf(
        rootProject.file("../../../local-artifacts/secrets/$name"),
        rootProject.file(name),
        rootProject.file("../../../$name"),
    )
        .firstOrNull { it.isFile }
        ?.readText()
        ?.trim()
        .orEmpty()

fun localPropertyOrSecretFile(name: String, secretFileName: String, defaultValue: String = ""): String =
    localProperty(name).ifBlank { localSecretFile(secretFileName) }.ifBlank { defaultValue }

fun buildConfigString(value: String): String = "\"" + value.replace("\\", "\\\\").replace("\"", "\\\"") + "\""

val androidDebugStoreFile = localOrGradleProperty("homeworkhelper.android.debugStoreFile")
val androidDebugStorePassword = localOrGradleProperty("homeworkhelper.android.debugStorePassword", "android")
val androidDebugKeyAlias = localOrGradleProperty("homeworkhelper.android.debugKeyAlias", "androiddebugkey")
val androidDebugKeyPassword = localOrGradleProperty("homeworkhelper.android.debugKeyPassword", androidDebugStorePassword)

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "dev.homeworkhelper.remote"
    compileSdk = 36

    defaultConfig {
        applicationId = "dev.homeworkhelper.remote"
        minSdk = 26
        targetSdk = 36
        versionCode = localOrGradleIntProperty("homeworkhelper.android.versionCode", 1)
        versionName = localOrGradleProperty("homeworkhelper.android.versionName", "0.1.0")

        buildConfigField("String", "SMARTTHINGS_DEFAULT_DEVICE_ID", buildConfigString(localProperty("smartthings.deviceId", "145ad447-9969-4ee7-bda0-1760430d9be1")))
        buildConfigField("String", "SMARTTHINGS_DEFAULT_DEVICE_LABEL", buildConfigString(localProperty("smartthings.deviceLabel", "PC 켜기")))
        buildConfigField("String", "SMARTTHINGS_DEFAULT_LOCATION_ID", buildConfigString(localProperty("smartthings.locationId", "7bbf137d-1f96-4ad4-9e39-1cdab082d41a")))
        buildConfigField("String", "SMARTTHINGS_DEBUG_PAT", buildConfigString(localPropertyOrSecretFile("smartthings.pat", "SmartThings_Token")))
        buildConfigField("String", "DEFAULT_REMOTE_BASE_URL", buildConfigString(localOrGradleProperty("homeworkhelper.android.defaultRemoteBaseUrl")))
    }

    signingConfigs {
        if (androidDebugStoreFile.isNotBlank()) {
            getByName("debug") {
                storeFile = file(androidDebugStoreFile)
                storePassword = androidDebugStorePassword
                keyAlias = androidDebugKeyAlias
                keyPassword = androidDebugKeyPassword
            }
        }
    }

    buildTypes {
        debug {
            signingConfig = signingConfigs.getByName("debug")
        }
        release {
            signingConfig = signingConfigs.getByName("debug")
            isMinifyEnabled = false
            isShrinkResources = false
        }
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

kotlin {
    jvmToolchain(17)
}

dependencies {
    implementation(platform("androidx.compose:compose-bom:2026.03.00"))
    implementation("androidx.activity:activity-compose:1.12.0")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.ui:ui-tooling-preview")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.9.4")
    implementation("androidx.lifecycle:lifecycle-viewmodel-compose:2.9.4")
    implementation("io.coil-kt.coil3:coil-compose:3.4.0")
    implementation("io.coil-kt.coil3:coil-network-okhttp:3.4.0")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.10.2")
    debugImplementation("androidx.compose.ui:ui-tooling")
}
