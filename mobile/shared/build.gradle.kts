import org.jetbrains.kotlin.gradle.dsl.JvmTarget
import org.gradle.api.DefaultTask
import org.gradle.api.file.DirectoryProperty
import org.gradle.api.provider.Property
import org.gradle.api.tasks.Input
import org.gradle.api.tasks.OutputDirectory
import org.gradle.api.tasks.TaskAction
import java.net.URI
import java.util.Properties

plugins {
    id("com.google.devtools.ksp") version "2.3.12"
    kotlin("plugin.serialization") version "2.4.20"
    alias(libs.plugins.kotlinMultiplatform)
    alias(libs.plugins.androidMultiplatformLibrary)
    alias(libs.plugins.composeMultiplatform)
    alias(libs.plugins.composeCompiler)
}

abstract class GenerateAppConfiguration : DefaultTask() {
    @get:Input
    abstract val serverUrl: Property<String>

    @get:Input
    abstract val researcherMode: Property<Boolean>

    @get:OutputDirectory
    abstract val outputDirectory: DirectoryProperty

    @TaskAction
    fun generate() {
        val value = serverUrl.get().trim().trimEnd('/')
        if (value.isNotEmpty()) {
            val uri = URI(value)
            require(uri.scheme in listOf("https", "http") && !uri.host.isNullOrBlank()
                && uri.userInfo == null && uri.query == null && uri.fragment == null) {
                "conversationServerUrl must be an HTTP(S) backend URL without credentials or query."
            }
        }
        val literal = value.replace("\\", "\\\\").replace("\"", "\\\"").replace("$", "\\$")
        val source = outputDirectory.get().file("com/ai/mobile/BuildConfiguration.kt").asFile
        source.parentFile.mkdirs()
        source.writeText("package com.ai.mobile\ninternal object BuildConfiguration {\n    const val serverUrl = \"$literal\"\n    const val researcherMode = ${researcherMode.get()}\n}\n")
    }
}

val localProperties = providers.fileContents(
    rootProject.layout.projectDirectory.file("local.properties")
).asText.map { contents -> Properties().apply { contents.reader().use { load(it) } } }
val localServerUrl = localProperties.map { it.getProperty("conversationServerUrl", "") }
val localResearcherMode = localProperties.map { it.getProperty("researcherMode", "") }

val generateAppConfiguration = tasks.register<GenerateAppConfiguration>("generateAppConfiguration") {
    serverUrl.set(providers.gradleProperty("conversationServerUrl")
        .orElse(providers.environmentVariable("CONVERSATION_SERVER_URL"))
        .orElse(localServerUrl).orElse(""))
    researcherMode.set(providers.gradleProperty("researcherMode")
        .orElse(providers.environmentVariable("KAIWA_RESEARCHER_MODE"))
        .orElse(localResearcherMode)
        .map { it.equals("true", ignoreCase = true) }.orElse(false))
    outputDirectory.set(layout.buildDirectory.dir("generated/appConfiguration"))
}

kotlin {
    listOf(
        iosArm64(),
        iosSimulatorArm64()
    ).forEach { iosTarget ->
        iosTarget.binaries.framework {
            baseName = "Shared"
            isStatic = true
        }
    }

    android {
        namespace = "com.ai.mobile.shared"
        compileSdk = libs.versions.android.compileSdk.get().toInt()
        minSdk = libs.versions.android.minSdk.get().toInt()

        compilerOptions {
            jvmTarget = JvmTarget.JVM_11
        }
        androidResources {
            enable = true
        }
        withHostTest {
            isIncludeAndroidResources = true
        }
        withDeviceTestBuilder {
            sourceSetTreeName = "test"
        }.configure {
            instrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        }
    }

    sourceSets {
        commonMain { kotlin.srcDir(generateAppConfiguration) }
        androidMain.dependencies {
            implementation("io.livekit:livekit-android:2.29.0")
            implementation("io.ktor:ktor-client-okhttp:3.6.0")
            implementation("androidx.activity:activity-compose:1.13.0")
            implementation(libs.compose.uiToolingPreview)
            implementation(libs.compose.uiTooling)
        }
        iosMain.dependencies { implementation("io.ktor:ktor-client-darwin:3.6.0") }
        commonMain.dependencies {
            implementation("io.ktor:ktor-client-core:3.6.0")
            implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.11.0")
            implementation("androidx.room:room-runtime:2.8.5")
            implementation("androidx.sqlite:sqlite-bundled:2.6.2")
            implementation("androidx.datastore:datastore-preferences:1.2.1")
            implementation(libs.compose.runtime)
            implementation(libs.compose.foundation)
            implementation(libs.compose.material3)
            implementation(libs.compose.ui)
            implementation(libs.compose.components.resources)
            implementation(libs.compose.uiToolingPreview)
            implementation(libs.androidx.lifecycle.viewmodelCompose)
            implementation(libs.androidx.lifecycle.runtimeCompose)
        }
        getByName("androidHostTest").dependencies {
            implementation("org.robolectric:robolectric:4.17")
            implementation("androidx.test:core:1.7.0")
        }
        commonTest.dependencies {
            implementation(libs.kotlin.test)
        }
    }
}

dependencies {
    androidRuntimeClasspath(libs.compose.uiTooling)
}

dependencies {
    add("kspAndroid", "androidx.room:room-compiler:2.8.5")
    add("kspIosArm64", "androidx.room:room-compiler:2.8.5")
    add("kspIosSimulatorArm64", "androidx.room:room-compiler:2.8.5")
}
