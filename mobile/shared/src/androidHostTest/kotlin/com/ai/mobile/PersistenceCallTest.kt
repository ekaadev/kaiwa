package com.ai.mobile

import android.content.Context
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.first
import okio.Path.Companion.toPath
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File
import kotlin.test.*

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class PersistenceCallTest {
    private val context: Context get() = ApplicationProvider.getApplicationContext()
    private fun database(file: File) = Room.databaseBuilder<ConversationDatabase>(context, file.absolutePath).setQueryCoroutineContext(Dispatchers.IO).build()

    @Test fun conversationsSurviveReopeningAndStaySeparatedByParticipant() = runBlocking {
        val file = File(context.filesDir, "reopen-${System.nanoTime()}.db")
        val first = database(file)
        val practice = Conversation("practice-id", "practice", "https://server", null, 1)
        val study = Conversation("study-id", "participant-one", "https://server", 1, 2)
        first.conversations().save(practice)
        first.conversations().save(study)
        first.close()
        val reopened = database(file)
        assertEquals(listOf(practice), reopened.conversations().observe("practice").first())
        assertEquals(listOf(study), reopened.conversations().observe("participant-one").first())
        assertTrue(reopened.conversations().observe("participant-two").first().isEmpty())
        reopened.conversations().delete(study.id)
        assertTrue(reopened.conversations().observe("participant-one").first().isEmpty())
        reopened.close()
    }

    @Test fun rapidStartsCreateOneCallAndNormalEndSavesTranscript() = runBlocking {
        val database = database(File(context.filesDir, "call-${System.nanoTime()}.db"))
        val testScope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
        val settings = SettingsStore(PreferenceDataStoreFactory.createWithPath(scope = testScope, produceFile = { File(context.filesDir, "settings-${System.nanoTime()}.preferences_pb").absolutePath.toPath() }))
        val native = FakeNative()
        val gate = CompletableDeferred<Unit>()
        var starts = 0
        val api = object : ConversationApi() {
            override suspend fun start(server: String, token: String?, ordinal: Int?, key: String): CallCredentials {
                starts++
                gate.await()
                return CallCredentials("real-id", "wss://livekit", "temporary", "capability")
            }
            override suspend fun transcript(server: String, id: String, token: String, study: Boolean, after: Int): Transcript = Transcript(if (after == 0) listOf(Turn(1, "user", "こんにちは")) else emptyList(), true)
            override suspend fun end(server: String, id: String, token: String?, study: Boolean) = Unit
        }
        settings.saveServer("https://server")
        val state = AppState(AppServices(database, settings, native, AppConfiguration("https://server")), testScope, api)
        withTimeout(5000) { while (state.server.isBlank()) delay(10) }
        state.start()
        state.start()
        withTimeout(5000) { while (starts == 0) delay(10) }
        assertEquals(1, starts)
        gate.complete(Unit)
        try { withTimeout(5000) { native.connected.await() } }
        catch (e: TimeoutCancellationException) { fail("Call did not connect: phase=${state.phase}, message=${state.message}, selected=${state.selected?.outcome}") }
        state.finish()
        withContext(Dispatchers.IO) { withTimeout(5000) { while (state.selected == null) delay(10) } }
        assertEquals("Ended", state.selected!!.outcome)
        assertEquals("こんにちは", state.selected!!.turns().single().text)
        assertTrue(native.disconnected)
        state.close()
        testScope.cancel()
        database.close()
    }

    private class FakeNative : NativeCalls {
        var disconnected = false
        val connected = CompletableDeferred<Unit>()
        val secrets = mutableMapOf<String, String>()
        override suspend fun requestMicrophone() = true
        override suspend fun connect(url: String, token: String) { connected.complete(Unit) }
        override suspend fun mute(muted: Boolean) = Unit
        override fun disconnect() { disconnected = true }
        override fun observe(listener: (String) -> Unit) = Unit
        override fun openPermissionSettings() = Unit
        override fun readSecret(key: String) = secrets[key]
        override fun writeSecret(key: String, value: String?) { if (value == null) secrets.remove(key) else secrets[key] = value }
    }
}
