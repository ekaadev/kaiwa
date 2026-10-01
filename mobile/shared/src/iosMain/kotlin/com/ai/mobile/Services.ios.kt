@file:OptIn(kotlinx.cinterop.ExperimentalForeignApi::class, kotlin.experimental.ExperimentalNativeApi::class)

package com.ai.mobile

import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.remember
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.room.Room
import androidx.sqlite.driver.bundled.BundledSQLiteDriver
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.IO
import kotlinx.coroutines.suspendCancellableCoroutine
import okio.Path.Companion.toPath
import platform.Foundation.*
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

actual fun formatDate(timestamp: Long): String =
    NSDateFormatter().apply { dateStyle = NSDateFormatterMediumStyle; timeStyle = NSDateFormatterShortStyle }
        .stringFromDate(NSDate.dateWithTimeIntervalSince1970(timestamp / 1000.0))

@Composable
actual fun PlatformBackHandler(enabled: Boolean, onBack: () -> Unit) {
    DisposableEffect(enabled, onBack) {
        IOSHost.backAction = if (enabled) onBack else null; onDispose { IOSHost.backAction = null }
    }
}

private var services: AppServices? = null
@Composable
actual fun platformServices(): AppServices = remember {
    services ?: run {
        val root = NSHomeDirectory() + "/Library/Application Support/Conversation"
        NSFileManager.defaultManager.createDirectoryAtPath(root, true, null, null)
        val database =
            Room.databaseBuilder<ConversationDatabase>(name = "$root/conversations.db").setDriver(BundledSQLiteDriver())
                .setQueryCoroutineContext(Dispatchers.IO).build()
        val store =
            PreferenceDataStoreFactory.createWithPath(produceFile = { "$root/settings.preferences_pb".toPath() })
        val bridge =
            checkNotNull(IOSHost.bridge) { "The Swift host must install IOSHost.bridge before opening Compose." }
        AppServices(
            database, SettingsStore(store), IOSCalls(bridge),
            AppConfiguration(
                allowDevelopmentHttp = kotlin.native.Platform.isDebugBinary,
            ),
        ).also { services = it }
    }
}

private class IOSCalls(private val bridge: IOSMediaBridge) : NativeCalls {
    override suspend fun requestMicrophone(): Boolean = suspendCancellableCoroutine { continuation ->
        bridge.requestPermission(object : PermissionCompletion {
            override fun complete(allowed: Boolean) {
                if (continuation.isActive) continuation.resume(allowed)
            }
        })
    }

    override suspend fun connect(url: String, token: String): Unit = suspendCancellableCoroutine { continuation ->
        continuation.invokeOnCancellation { bridge.disconnectRoom() }
        bridge.connectRoom(url, token, object : OperationCompletion {
            override fun complete(error: String?) {
                if (continuation.isActive) {
                    if (error == null) continuation.resume(Unit) else continuation.resumeWithException(
                        IllegalStateException(error)
                    )
                }
            }
        })
    }

    override suspend fun mute(muted: Boolean): Unit = suspendCancellableCoroutine { continuation ->
        bridge.setMuted(muted, object : OperationCompletion {
            override fun complete(error: String?) {
                if (continuation.isActive) {
                    if (error == null) continuation.resume(Unit) else continuation.resumeWithException(
                        IllegalStateException(error)
                    )
                }
            }
        })
    }

    override fun disconnect() = bridge.disconnectRoom()
    override fun observe(listener: (String) -> Unit) = bridge.setObserver(object : CallObserver {
        override fun event(state: String) = listener(state)
    })

    override fun openPermissionSettings() = bridge.openSettings()
    override fun readSecret(key: String) = bridge.secret(key)
    override fun writeSecret(key: String, value: String?) {
        check(bridge.saveSecret(key, value)) { "Credentials could not be saved securely." }
    }
}
