package com.ai.mobile

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ApplicationInfo
import android.net.Uri
import android.provider.Settings
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import androidx.activity.compose.BackHandler
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.*
import androidx.compose.ui.platform.LocalContext
import androidx.core.content.ContextCompat
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.room.Room
import androidx.sqlite.driver.bundled.BundledSQLiteDriver
import io.livekit.android.LiveKit
import io.livekit.android.events.RoomEvent
import io.livekit.android.events.collect
import io.livekit.android.room.participant.RemoteParticipant
import io.livekit.android.room.track.Track
import kotlinx.coroutines.*
import okio.Path.Companion.toPath
import java.io.File
import java.security.KeyStore
import java.text.DateFormat
import java.util.*
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

@Composable
actual fun PlatformBackHandler(enabled: Boolean, onBack: () -> Unit) = BackHandler(enabled, onBack)
actual fun formatDate(timestamp: Long): String =
    DateFormat.getDateTimeInstance(DateFormat.MEDIUM, DateFormat.SHORT).format(Date(timestamp))

private var sharedServices: AppServices? = null

@Composable
actual fun platformServices(): AppServices {
    val context = LocalContext.current.applicationContext
    var permission by remember { mutableStateOf<CompletableDeferred<Boolean>?>(null) }
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {
        permission?.complete(it); permission = null
    }
    val services = remember {
        sharedServices ?: run {
            val isDebug = context.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE != 0
            val native = AndroidCalls(context, CoroutineScope(SupervisorJob() + Dispatchers.Main))
            val database = Room.databaseBuilder<ConversationDatabase>(
                context,
                File(context.filesDir, "conversations.db").absolutePath
            ).setDriver(BundledSQLiteDriver()).setQueryCoroutineContext(Dispatchers.IO).build()
            val store = PreferenceDataStoreFactory.createWithPath(produceFile = {
                File(
                    context.filesDir,
                    "settings.preferences_pb"
                ).absolutePath.toPath()
            })
            AppServices(
                database, SettingsStore(store), native,
                AppConfiguration(allowDevelopmentHttp = isDebug),
            ).also { sharedServices = it }
        }
    }
    (services.calls as AndroidCalls).permission = {
        if (ContextCompat.checkSelfPermission(
                context,
                Manifest.permission.RECORD_AUDIO
            ) == PackageManager.PERMISSION_GRANTED
        ) true
        else CompletableDeferred<Boolean>().also { permission = it; launcher.launch(Manifest.permission.RECORD_AUDIO) }
            .await()
    }
    return services
}

private class AndroidCalls(private val context: Context, private val scope: CoroutineScope) : NativeCalls {
    var permission: suspend () -> Boolean = { false }
    private var room: io.livekit.android.room.Room? = null
    private var events: Job? = null
    private var listener: (String) -> Unit = {}
    override suspend fun requestMicrophone() = permission()
    override suspend fun connect(url: String, token: String) {
        disconnect()
        val next = LiveKit.create(context)
        room = next
        events = scope.launch {
            next.events.collect { event ->
                when (event) {
                    is RoomEvent.Disconnected -> listener("Disconnected")
                    is RoomEvent.Reconnecting -> listener("Reconnecting")
                    is RoomEvent.Reconnected -> listener("Connected")
                    is RoomEvent.ActiveSpeakersChanged -> listener(if (event.speakers.any { it is RemoteParticipant }) "Speaking" else "Listening")
                    is RoomEvent.TrackSubscribed -> if (event.track.kind == Track.Kind.AUDIO) {
                        listener("remote_audio_subscribed")
                        (event.track as? io.livekit.android.room.track.RemoteAudioTrack)?.let(::watchPlayback)
                    }
                    is RoomEvent.TrackUnsubscribed -> if (event.track.kind == Track.Kind.AUDIO) {
                        stopWatchingPlayback()
                        listener("remote_audio_unsubscribed")
                    }
                    else -> Unit
                }
            }
        }
        next.connect(url, token)
        next.localParticipant.setMicrophoneEnabled(true)
    }

    override suspend fun mute(muted: Boolean) {
        room?.localParticipant?.setMicrophoneEnabled(!muted) ?: error("No active call")
    }

    private var playbackTrack: io.livekit.android.room.track.RemoteAudioTrack? = null
    private var playbackSink: livekit.org.webrtc.AudioTrackSink? = null

    private fun watchPlayback(track: io.livekit.android.room.track.RemoteAudioTrack) {
        stopWatchingPlayback()
        val detector = PlaybackOnsetDetector()
        val sink = livekit.org.webrtc.AudioTrackSink { data, bits, _, _, frames, _ ->
            if (bits != 16 || frames <= 0) return@AudioTrackSink
            val samples = data.duplicate().order(java.nio.ByteOrder.nativeOrder()).asShortBuffer()
            var sum = 0.0
            val count = minOf(samples.remaining(), frames)
            for (i in 0 until count) {
                val v = samples.get().toDouble() / Short.MAX_VALUE
                sum += v * v
            }
            val rms = if (count > 0) kotlin.math.sqrt(sum / count) else 0.0
            val now = android.os.SystemClock.elapsedRealtime()
            detector.accept(now, rms)?.let { event -> scope.launch { listener(event) } }
        }
        track.addSink(sink)
        playbackTrack = track
        playbackSink = sink
    }

    private fun stopWatchingPlayback() {
        val track = playbackTrack
        val sink = playbackSink
        if (track != null && sink != null) runCatching { track.removeSink(sink) }
        playbackTrack = null; playbackSink = null
    }

    override fun disconnect() {
        stopWatchingPlayback()
        events?.cancel(); events = null; room?.disconnect(); room?.release(); room = null
    }

    override fun observe(listener: (String) -> Unit) {
        this.listener = listener
    }

    override fun openPermissionSettings() {
        context.startActivity(
            Intent(
                Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                Uri.parse("package:${context.packageName}")
            ).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        )
    }

    private val preferences = context.getSharedPreferences("private_credentials", Context.MODE_PRIVATE)
    private fun secretKey(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey("conversation_credentials", null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(
                KeyGenParameterSpec.Builder(
                    "conversation_credentials",
                    KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT
                ).setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                    .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build()
            )
        }.generateKey()
    }

    override fun readSecret(key: String): String? {
        val data = preferences.getString(key, null) ?: return null
        return try {
            val parts = data.split(':')
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(
                Cipher.DECRYPT_MODE,
                secretKey(),
                GCMParameterSpec(128, Base64.decode(parts[0], Base64.NO_WRAP))
            )
            cipher.doFinal(Base64.decode(parts[1], Base64.NO_WRAP)).toString(Charsets.UTF_8)
        } catch (_: Exception) {
            null
        }
    }

    override fun writeSecret(key: String, value: String?) {
        val editor = preferences.edit()
        if (value == null) editor.remove(key)
        else {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.ENCRYPT_MODE, secretKey())
            editor.putString(
                key,
                Base64.encodeToString(
                    cipher.iv,
                    Base64.NO_WRAP
                ) + ":" + Base64.encodeToString(cipher.doFinal(value.toByteArray()), Base64.NO_WRAP)
            )
        }
        check(editor.commit()) { "Credentials could not be saved securely." }
    }
}
