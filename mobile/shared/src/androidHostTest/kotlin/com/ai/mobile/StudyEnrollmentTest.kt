package com.ai.mobile

import android.content.Context
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.room.Room
import androidx.test.core.app.ApplicationProvider
import kotlinx.coroutines.*
import okio.Path.Companion.toPath
import org.junit.Test
import org.junit.runner.RunWith
import org.robolectric.RobolectricTestRunner
import org.robolectric.annotation.Config
import java.io.File
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.CopyOnWriteArrayList
import kotlin.test.*

@RunWith(RobolectricTestRunner::class)
@Config(sdk = [35])
class StudyEnrollmentTest {
    private val enrollment = Enrollment("participant-test", listOf(StudySession(1, "pending", true), StudySession(2, "pending", false)), "test-resume-token")

    private class Native : NativeCalls {
        val secrets = ConcurrentHashMap<String, String>()
        val events = CopyOnWriteArrayList<String>()
        var allowed = true
        var permissionGranted = false
        var permissionPrompts = 0
        var permissionGate: CompletableDeferred<Boolean>? = null
        var storageFails = false
        override suspend fun requestMicrophone(): Boolean {
            events.add("permission")
            if (permissionGranted) return true
            permissionPrompts++
            return (permissionGate?.await() ?: allowed).also { permissionGranted = it }
        }
        override suspend fun connect(url: String, token: String) { events.add("connect") }
        override suspend fun mute(muted: Boolean) = Unit
        override fun disconnect() = Unit
        override fun observe(listener: (String) -> Unit) = Unit
        override fun openPermissionSettings() = Unit
        override fun readSecret(key: String) = secrets[key]
        override fun writeSecret(key: String, value: String?) {
            events.add("save")
            if (storageFails) error("Test storage failure")
            if (value == null) secrets.remove(key) else secrets[key] = value
        }
    }

    private inner class Fixture(val native: Native = Native(), val failRequest: Boolean = false, val url: String = "https://study.example", val development: Boolean = false, val readyCalls: Boolean = false) {
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.Default)
        val context: Context = ApplicationProvider.getApplicationContext()
        val suffix = System.nanoTime()
        val database = Room.databaseBuilder<ConversationDatabase>(context, File(context.filesDir, "enroll-$suffix.db").absolutePath).setQueryCoroutineContext(Dispatchers.IO).build()
        val settings = SettingsStore(PreferenceDataStoreFactory.createWithPath(scope = scope, produceFile = { File(context.filesDir, "enroll-$suffix.preferences_pb").absolutePath.toPath() }))
        val api = object : ConversationApi() {
            override suspend fun enroll(server: String): Enrollment {
                native.events.add("enroll")
                assertEquals(url, server)
                if (failRequest) throw ApiFailure(503, "The service is unavailable.")
                return enrollment
            }
            override suspend fun participant(server: String, token: String): Participant {
                native.events.add("resume")
                assertEquals(enrollment.resume_token, token)
                return enrollment.participant()
            }
            override suspend fun start(server: String, token: String?, ordinal: Int?, key: String): CallCredentials {
                native.events.add("start")
                assertEquals(url, server)
                if (!readyCalls) throw ApiFailure(503, "The call service is unavailable.")
                return CallCredentials("permission-call", "wss://livekit.example", "test-join-token", "test-transcript-token")
            }
            override suspend fun transcript(server: String, id: String, token: String, study: Boolean, after: Int): Transcript = Transcript(emptyList(), false)
            override suspend fun end(server: String, id: String, token: String?, study: Boolean) = Unit
        }
        fun state() = AppState(AppServices(database, settings, native, AppConfiguration(url, development)), scope, api)
        fun close(state: AppState) {
            state.close()
            scope.cancel()
            database.close()
        }
    }

    private suspend fun await(predicate: () -> Boolean) = withTimeout(5000) {
        while (!predicate()) delay(10)
    }

    @Test fun decliningDoesNotRequestPermissionOrEnroll() = runBlocking {
        val fixture = Fixture()
        val state = fixture.state()
        try {
            await { state.settingsReady }
            state.enterTesting()
            assertTrue(state.studySetupOpen)
            state.declineStudy()
            assertFalse(state.studySetupOpen)
            assertTrue(fixture.native.events.isEmpty())
            assertTrue(state.token.isEmpty())
            assertNull(state.participant)
        } finally { fixture.close(state) }
    }

    @Test fun deniedMicrophoneStopsBeforeRegistrationAndRapidTapsRequestOnce() = runBlocking {
        val native = Native().apply { permissionGate = CompletableDeferred() }
        val fixture = Fixture(native)
        val state = fixture.state()
        try {
            await { state.settingsReady }
            state.enterTesting()
            state.agreeToStudy()
            state.agreeToStudy()
            await { native.events.contains("permission") }
            state.declineStudy()
            assertTrue(state.studySetupOpen)
            native.permissionGate!!.complete(false)
            await { !state.joiningStudy }
            assertEquals(listOf("permission"), native.events.toList())
            assertTrue(state.microphonePermissionNotice)
            assertNull(state.studySetupError)
            assertTrue(state.studySetupOpen)
            assertTrue(state.token.isEmpty())
            native.permissionGate = CompletableDeferred()
            state.agreeToStudy()
            assertFalse(state.microphonePermissionNotice)
            await { native.events.count { it == "permission" } == 2 }
            native.permissionGate!!.complete(true)
            await { !state.joiningStudy && state.participant != null }
            assertFalse(state.microphonePermissionNotice)
            assertFalse(state.studySetupOpen)
            assertEquals(listOf("permission", "permission", "enroll", "save"), native.events.toList())
        } finally { fixture.close(state) }
    }

    @Test fun registrationFollowsPermissionSavesCredentialAndResumesWithoutReenrolling() = runBlocking {
        val fixture = Fixture()
        val state = fixture.state()
        try {
            await { state.settingsReady }
            state.enterTesting()
            state.agreeToStudy()
            await { !state.joiningStudy && state.participant != null }
            assertEquals(listOf("permission", "enroll", "save"), fixture.native.events.toList())
            assertEquals(enrollment.resume_token, fixture.native.secrets["study:https://study.example"])
            assertFalse(state.studySetupOpen)
            assertTrue(state.canStartStudy(1))
            assertFalse(state.canStartStudy(2))
            val resumed = fixture.state()
            await { resumed.participant != null && !resumed.busy }
            resumed.enterTesting()
            assertFalse(resumed.studySetupOpen)
            assertEquals(1, fixture.native.events.count { it == "enroll" })
            assertFalse(fixture.native.events.contains("connect"))
            resumed.close()
        } finally { fixture.close(state) }
    }

    @Test fun storageFailureRetriesSavingTheSameParticipant() = runBlocking {
        val native = Native().apply { storageFails = true }
        val fixture = Fixture(native)
        val state = fixture.state()
        try {
            await { state.settingsReady }
            state.enterTesting()
            state.agreeToStudy()
            await { !state.joiningStudy && state.studySetupError != null }
            assertTrue(state.studySetupOpen)
            assertNull(state.participant)
            assertTrue(state.token.isEmpty())
            native.storageFails = false
            state.agreeToStudy()
            await { !state.joiningStudy && state.participant != null }
            assertEquals(1, native.events.count { it == "enroll" })
            assertEquals(enrollment.resume_token, state.token)
            assertEquals(enrollment.resume_token, native.secrets["study:https://study.example"])
        } finally { fixture.close(state) }
    }

    @Test fun failedRegistrationShowsErrorAndCreatesNoLocalAccess() = runBlocking {
        val fixture = Fixture(failRequest = true)
        val state = fixture.state()
        try {
            await { state.settingsReady }
            state.enterTesting()
            state.agreeToStudy()
            await { !state.joiningStudy && state.studySetupError != null }
            assertTrue(state.studySetupOpen)
            assertTrue(fixture.native.secrets.isEmpty())
            assertNull(state.participant)
            assertTrue(state.token.isEmpty())
            assertEquals(listOf("permission", "enroll"), fixture.native.events.toList())
        } finally { fixture.close(state) }
    }

    @Test fun absentBackendDoesNotInventParticipantAccess() = runBlocking {
        val fixture = Fixture(url = "")
        val state = fixture.state()
        try {
            await { state.settingsReady }
            state.enterTesting()
            state.agreeToStudy()
            await { !state.joiningStudy && state.studySetupError != null }
            assertEquals(listOf("permission"), fixture.native.events.toList())
            assertTrue(state.studySetupOpen)
            assertNull(state.participant)
            assertTrue(fixture.native.secrets.isEmpty())
        } finally { fixture.close(state) }
    }

    @Test fun httpBackendIsAcceptedOnlyInDevelopmentConfiguration() = runBlocking {
        val release = Fixture(url = "http://127.0.0.1:8000")
        val production = release.state()
        try { await { production.settingsReady }; assertTrue(production.server.isBlank()) }
        finally { release.close(production) }
        val debug = Fixture(url = "http://127.0.0.1:8000", development = true)
        val local = debug.state()
        try { await { local.settingsReady }; assertEquals("http://127.0.0.1:8000", local.server) }
        finally { debug.close(local) }
    }

    @Test fun homeDenialShowsSettingsNoticeAndRequestsAgainAfterRestart() = runBlocking {
        val native = Native().apply { permissionGate = CompletableDeferred() }
        // Microphone permission is requested even when the backend is not configured yet.
        val fixture = Fixture(native, url = "")
        val state = fixture.state()
        var restarted: AppState? = null
        try {
            await { state.settingsReady }
            state.start()
            state.start()
            await { native.permissionPrompts == 1 }
            assertFalse(state.studySetupOpen)
            native.permissionGate!!.complete(false)
            await { !state.busy && state.microphonePermissionNotice }
            assertNull(state.call)
            assertEquals(listOf("permission"), native.events.toList())
            state.close()
            native.permissionGate = CompletableDeferred()
            val next = fixture.state().also { restarted = it }
            await { next.settingsReady }
            next.start()
            await { native.permissionPrompts == 2 }
            native.permissionGate!!.complete(false)
            await { !next.busy && next.microphonePermissionNotice }
            assertFalse(next.studySetupOpen)
            assertEquals(listOf("permission", "permission"), native.events.toList())
        } finally {
            restarted?.close()
            fixture.close(state)
        }
    }

    @Test fun homeGrantIsReusedForTestingEnrollmentAndCallAttempt() = runBlocking {
        val fixture = Fixture()
        val state = fixture.state()
        try {
            await { state.settingsReady }
            state.start()
            await { !state.busy && fixture.native.events.contains("start") }
            assertFalse(state.studySetupOpen)
            assertEquals(1, fixture.native.permissionPrompts)
            assertFalse(state.microphonePermissionNotice)
            state.enterTesting()
            assertTrue(state.studySetupOpen)
            state.agreeToStudy()
            await { !state.joiningStudy && state.participant != null }
            state.start()
            await { !state.busy && fixture.native.events.count { it == "start" } == 2 }
            assertEquals(1, fixture.native.permissionPrompts)
            assertFalse(state.microphonePermissionNotice)
            assertEquals(1, fixture.native.events.count { it == "enroll" })
        } finally { fixture.close(state) }
    }

    @Test fun testingGrantLetsHomeConnectAndRevocationBlocksTheNextCall() = runBlocking {
        val fixture = Fixture(readyCalls = true)
        val state = fixture.state()
        try {
            await { state.settingsReady }
            state.enterTesting()
            state.agreeToStudy()
            await { !state.joiningStudy && state.participant != null }
            state.destination = "Home"
            state.start()
            await { state.call != null && state.phase == "Listening" }
            assertTrue(state.showingCallScreen)
            assertEquals(1, fixture.native.permissionPrompts)
            assertTrue(fixture.native.events.contains("connect"))
            assertFalse(state.studySetupOpen)
            state.finish()
            await { state.call == null && !state.busy && state.selected != null }
            fixture.native.permissionGranted = false
            fixture.native.allowed = false
            state.selected = null
            state.start()
            await { !state.busy && state.microphonePermissionNotice }
            assertEquals(2, fixture.native.permissionPrompts)
            assertEquals(1, fixture.native.events.count { it == "start" })
            assertNull(state.call)
        } finally { fixture.close(state) }
    }

}
