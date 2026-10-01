import org.jetbrains.kotlin.gradle.dsl.JvmTarget
import java.util.Properties

plugins {
    alias(libs.plugins.androidApplication)
    alias(libs.plugins.composeCompiler)
}

kotlin {
    compilerOptions {
        jvmTarget = JvmTarget.JVM_11
    }
}
dependencies {
    implementation(project(":shared"))

    implementation(libs.androidx.activity.compose)

    implementation(libs.compose.uiToolingPreview)
    debugImplementation(libs.compose.uiTooling)
}

val releaseCredentials = Properties().apply {
    val file = rootProject.file(".signing/release.properties")
    if (file.exists()) file.inputStream().use { load(it) }
}

android {
    namespace = "com.ai.mobile"
    compileSdk = libs.versions.android.compileSdk.get().toInt()

    defaultConfig {
        applicationId = "com.ai.mobile"
        minSdk = libs.versions.android.minSdk.get().toInt()
        targetSdk = libs.versions.android.targetSdk.get().toInt()
        versionCode = 12
        versionName = "1.0.11"
    }
    packaging {
        resources {
            excludes += "/META-INF/{AL2.0,LGPL2.1}"
        }
    }
    signingConfigs {
        if (releaseCredentials.isNotEmpty()) create("conversationRelease") {
            storeFile = file(releaseCredentials.getProperty("storeFile"))
            storePassword = releaseCredentials.getProperty("storePassword")
            keyAlias = releaseCredentials.getProperty("keyAlias")
            keyPassword = releaseCredentials.getProperty("keyPassword")
        }
    }
    buildTypes {
        debug {
            applicationIdSuffix = ".debug"
            versionNameSuffix = "-local"
        }
        release {
            isMinifyEnabled = true
            isShrinkResources = true
            if (releaseCredentials.isNotEmpty()) signingConfig = signingConfigs.getByName("conversationRelease")
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    buildFeatures {
        compose = true
    }
}
