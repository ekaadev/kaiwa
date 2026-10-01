@file:OptIn(kotlin.time.ExperimentalTime::class, kotlin.uuid.ExperimentalUuidApi::class)

package com.ai.mobile

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.combine
import kotlin.time.Clock
import kotlin.uuid.Uuid

enum class StudyJoinPhase { Consent, Microphone, Registering }

class AppState(
    val services: AppServices,
    private val scope: CoroutineScope,
    val api: ConversationApi = ConversationApi()
) {
    var destination by mutableStateOf("Home")
    var settingsOpen by mutableStateOf(false)
    var server by mutableStateOf(runCatching {
        val configured = services.configuration.serverUrl
        if (configured.isBlank()) "" else validateServer(configured, services.configuration.allowDevelopmentHttp)
    }.getOrDefault(""))
    var settingsReady by mutableStateOf(false)
    var studySetupOpen by mutableStateOf(false)
    var studySetupError by mutableStateOf<String?>(null)
    var joiningStudy by mutableStateOf(false)
    var studyJoinPhase by mutableStateOf(StudyJoinPhase.Consent)
    var token by mutableStateOf("")
    var participant by mutableStateOf<Participant?>(null)
    var conversations by mutableStateOf<List<Conversation>>(emptyList())
    var selected by mutableStateOf<Conversation?>(null)
    var selectedOrdinal by mutableStateOf(1)
    var busy by mutableStateOf(false)
    var message by mutableStateOf<String?>(null)
    var microphonePermissionNotice by mutableStateOf(false)
    var call by mutableStateOf<Conversation?>(null)
    val showingCallScreen get() = call != null
    var phase by mutableStateOf("Preparing")
    var muted by mutableStateOf(false)
    var elapsed by mutableStateOf(0L)
    var turns by mutableStateOf<List<Turn>>(emptyList())
    var transcriptFinal by mutableStateOf(false)
    var transcriptWarning by mutableStateOf(false)
    var endConfirmation by mutableStateOf(false)
    private var joinJob: Job? = null
    private var refreshJob: Job? = null
    private var pendingEnrollment: Enrollment? = null
    private var callJob: Job? = null
    private var historyJob: Job? = null
    private var activeToken: String? = null
    private var startedConnected: Long? = null
    private var requestKey: String? = null
    private var starting = false
    private var connectedAccumulated = 0L
    private var telemetrySequence = 0
    private val recoveryAttempts = mutableSetOf<String>()
    private val time get() = Clock.System.now().toEpochMilliseconds()

    init {
        scope.launch {
            try {
                token = if (server.isNotBlank()) services.calls.readSecret("study:$server") ?: "" else ""
                watchHistory()
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                message = "Study access could not be read from this device."
            } finally {
                settingsReady = true
            }
            if (token.isNotBlank()) refresh()
            else if (destination == "Testing") beginStudySetup()
        }
        services.calls.observe { event ->
            scope.launch {
                if (phase == "Ending" || call == null) return@launch
                if (event.startsWith("remote_audio_")) {
                    val current = call
                    val auth = activeToken
                    if (current?.ordinal != null && auth != null) {
                        try {
                            api.telemetry(current.server, current.id, auth, event, ++telemetrySequence, time)
                        } catch (e: Exception) {
                            if (e is CancellationException) throw e
                        }
                    }
                    return@launch
                }
                when (event) {
                    "Disconnected" -> if (call != null && phase != "Ending") {
                        phase = "Connection lost"; finish(false)
                    }

                    "Reconnecting" -> {
                        connectedAccumulated += startedConnected?.let { time - it } ?: 0; startedConnected =
                            null; phase = "Reconnecting"
                    }

                    "Connected" -> {
                        phase = "Listening"; if (startedConnected == null) startedConnected = time
                    }

                    else -> phase = event
                }
            }
        }
    }

    private fun watchHistory() {
        historyJob?.cancel()
        historyJob = scope.launch {
            services.database.conversations().observe("practice").combine(
                services.database.conversations().observe(participant?.participant_id ?: "none")
            ) { practice, study -> (practice + study).sortedByDescending { it.started } }.catch {
                message =
                    "Saved conversations could not be read. Check device storage and try again."; emit(emptyList())
            }.collect { conversations = it }
        }
    }

    fun enterTesting() {
        destination = "Testing"
        if (!settingsReady) return
        if (token.isBlank()) beginStudySetup() else refresh()
    }

    fun beginStudySetup() {
        if (!settingsReady || busy || joiningStudy || showingCallScreen || token.isNotBlank()) return
        studySetupError = null
        microphonePermissionNotice = false
        message = null
        studyJoinPhase = StudyJoinPhase.Consent
        studySetupOpen = true
    }

    fun declineStudy() {
        if (joiningStudy) return
        studySetupOpen = false
        studySetupError = null
        microphonePermissionNotice = false
    }

    fun agreeToStudy() {
        if (!studySetupOpen || !settingsReady || joiningStudy || busy) return
        joiningStudy = true
        busy = true
        studySetupError = null
        microphonePermissionNotice = false
        joinJob = scope.launch {
            try {
                studyJoinPhase = StudyJoinPhase.Microphone
                if (!services.calls.requestMicrophone()) {
                    notifyMicrophoneDenied()
                    return@launch
                }
                if (server.isBlank()) {
                    studySetupError = "Testing is not connected yet. Please try again later."
                    return@launch
                }
                studyJoinPhase = StudyJoinPhase.Registering
                // Retain the issued credential if secure storage fails, so Retry saves the same participant.
                val enrollment = pendingEnrollment ?: api.enroll(server).also { pendingEnrollment = it }
                check(enrollment.resume_token.isNotBlank() && enrollment.participant_id.isNotBlank())
                try {
                    services.calls.writeSecret("study:$server", enrollment.resume_token)
                } catch (e: Exception) {
                    if (e is CancellationException) throw e
                    studySetupError = "Your study access could not be saved on this device. Please try again."
                    return@launch
                }
                token = enrollment.resume_token
                participant = enrollment.participant()
                pendingEnrollment = null
                selectedOrdinal = 1
                watchHistory()
                studySetupOpen = false
                message = "You're ready for Session 1."
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                studySetupError = if (e is ApiFailure) e.message else "We couldn't set up your sessions. Check your connection and try again."
            } finally {
                joiningStudy = false
                busy = false
                studyJoinPhase = StudyJoinPhase.Consent
            }
        }
    }

    fun refresh() {
        if (server.isBlank()) {
            message = "The service is not connected yet. Please try again later."
            return
        }
        if (token.isBlank()) {
            if (destination == "Testing") beginStudySetup()
            return
        }
        if (refreshJob?.isActive == true || joiningStudy) return
        refreshJob = scope.launch {
            busy = true
            try {
                participant = api.participant(server, token)
                watchHistory()
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                message = if (e is ApiFailure) e.message else "Your sessions couldn't be loaded. Check your connection and try again."
            } finally {
                busy = false
            }
        }
    }

    private fun attemptSecret(server: String, owner: String, ordinal: Int) = "attempt:$server:$owner:$ordinal"
    private fun notifyMicrophoneDenied() {
        message = null
        microphonePermissionNotice = true
    }

    fun canStartStudy(ordinal: Int): Boolean {
        val person = participant ?: return false
        return person.sessions.find { it.ordinal == ordinal }?.available == true || services.calls.readSecret(
            attemptSecret(server, person.participant_id, ordinal)
        ) != null
    }

    fun start() {
        if (busy || starting || showingCallScreen) return
        val ordinal = if (destination == "Testing") selectedOrdinal else null
        if (ordinal != null && token.isBlank()) {
            beginStudySetup()
            return
        }
        if (ordinal != null && !canStartStudy(ordinal)) {
            message = "This session isn't available yet. Refresh Testing and try again."; return
        }
        val configuredServer = server
        val configuredToken = token
        val callOwner = if (ordinal == null) "practice" else participant!!.participant_id
        microphonePermissionNotice = false
        starting = true
        callJob = scope.launch {
            busy = true
            try {
                if (!services.calls.requestMicrophone()) {
                    notifyMicrophoneDenied()
                    return@launch
                }
                if (configuredServer.isBlank()) {
                    message = "The call service is not connected yet. Please try again later."
                    return@launch
                }
                phase = "Preparing"
                turns = emptyList(); elapsed = 0; connectedAccumulated = 0; telemetrySequence = 0; muted =
                    false; transcriptFinal = false; transcriptWarning = false
                val secret = ordinal?.let { attemptSecret(configuredServer, callOwner, it) }
                val key = secret?.let { services.calls.readSecret(it) } ?: requestKey ?: Uuid.random().toString()
                requestKey = key
                if (secret != null) services.calls.writeSecret(secret, key)
                val issued = api.start(configuredServer, configuredToken, ordinal, key)
                requestKey = null
                activeToken = if (ordinal == null) issued.transcript_token else configuredToken
                val conversation = Conversation(issued.call_id, callOwner, configuredServer, ordinal, time)
                if (ordinal == null && issued.transcript_token != null) services.calls.writeSecret(
                    "call:${conversation.server}:${conversation.id}",
                    issued.transcript_token
                )
                call = conversation
                services.database.conversations().save(conversation)
                phase = "Connecting"
                services.calls.connect(issued.room_url, issued.join_token)
                startedConnected = time
                phase = "Listening"
                busy = false
                while (isActive && call != null) {
                    elapsed =
                        ((connectedAccumulated + (startedConnected?.let { time - it } ?: 0)) / 1000).coerceAtLeast(0)
                    fetchTranscript()
                    delay(1000)
                }
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                message =
                    e.message?.takeIf { it.length < 180 } ?: "Unable to connect. Check your connection and try again."
                if (call != null) {
                    services.calls.disconnect(); finish(false)
                } else if (e is ApiFailure) {
                    requestKey = null
                    if (ordinal != null) services.calls.writeSecret(
                        attemptSecret(configuredServer, callOwner, ordinal),
                        null
                    )
                }
            } finally {
                busy = false; starting = false
            }
        }
    }

    private suspend fun fetchTranscript() {
        val current = call ?: return
        val auth = activeToken ?: return
        try {
            val result = api.transcript(
                current.server,
                current.id,
                auth,
                current.ordinal != null,
                turns.lastOrNull()?.sequence ?: 0
            )
            turns = mergeTurns(turns, result.turns)
            transcriptFinal = result.finalized
            transcriptWarning = false
        } catch (e: Exception) {
            if (e is CancellationException) throw e; transcriptWarning = true
        }
        try {
            persistCurrent()
        } catch (e: Exception) {
            if (e is CancellationException) throw e; message = "Transcript could not be saved on this device."
        }
    }

    private suspend fun persistCurrent() {
        val current = call ?: return
        services.database.conversations().save(
            current.copy(
                duration = elapsed,
                turnsJson = appJson.encodeToString(turns),
                transcriptFinal = transcriptFinal
            )
        )
    }

    fun toggleMute() {
        scope.launch {
            try {
                services.calls.mute(!muted); muted = !muted
            } catch (e: Exception) {
                message = "Microphone state could not be changed."
            }
        }
    }

    fun finish(normal: Boolean = true) {
        if (call == null || phase == "Ending") return
        elapsed = ((connectedAccumulated + (startedConnected?.let { time - it } ?: 0)) / 1000).coerceAtLeast(0)
        phase = "Ending"
        endConfirmation = false
        callJob?.cancel()
        scope.launch {
            val current = call ?: return@launch
            var ended = normal
            try {
                if (normal) {
                    services.calls.mute(true)
                    muted = true
                    api.end(current.server, current.id, activeToken, current.ordinal != null)
                }
            } catch (e: Exception) {
                ended = false; message = "Call disconnected. The server could not confirm a normal ending."
            } finally {
                services.calls.disconnect()
            }
            // The final transcript may arrive after the room finishes closing.
            repeat(5) {
                if (!transcriptFinal) {
                    fetchTranscript(); delay(400)
                }
            }
            val saved = current.copy(
                duration = elapsed,
                outcome = if (ended) "Ended" else "Interrupted",
                turnsJson = appJson.encodeToString(turns),
                transcriptFinal = transcriptFinal
            )
            try {
                services.database.conversations().save(saved); selected = saved; destination = "Session"
            } catch (e: Exception) {
                selected = saved; message =
                    "Conversation could not be saved. Keep this screen open to read your transcript."
            }
            if (current.ordinal != null) services.calls.writeSecret(
                attemptSecret(
                    current.server,
                    current.owner,
                    current.ordinal
                ), null
            )
            call = null; activeToken = null; startedConnected = null; phase = "Ended"
            if (current.ordinal != null) refresh()
        }
    }

    fun delete(conversation: Conversation) {
        scope.launch {
            try {
                services.database.conversations().delete(conversation.id); services.calls.writeSecret(
                    "call:${conversation.server}:${conversation.id}",
                    null
                ); if (selected?.id == conversation.id) selected = null; message =
                    "Conversation deleted from this device."
            } catch (e: Exception) {
                message = "Conversation could not be deleted."
            }
        }
    }

    fun retryConversation(conversation: Conversation) {
        selected = null
        destination = if (conversation.ordinal == null) "Home" else "Testing"
        if (conversation.ordinal != null) {
            selectedOrdinal = conversation.ordinal
            refresh()
            message = "Refresh session availability, then start your call from Testing."
        } else start()
    }

    fun recoverTranscript(conversation: Conversation, automatic: Boolean = false) {
        if (conversation.transcriptFinal || (automatic && !recoveryAttempts.add(conversation.id))) return
        scope.launch {
            try {
                val auth =
                    if (conversation.ordinal == null) services.calls.readSecret("call:${conversation.server}:${conversation.id}") else if (conversation.owner == participant?.participant_id && conversation.server == server) token else null
                if (auth.isNullOrBlank()) {
                    if (!automatic) message = "Transcript access is unavailable for this conversation."; return@launch
                }
                val result = api.transcript(conversation.server, conversation.id, auth, conversation.ordinal != null)
                val saved = conversation.copy(
                    turnsJson = appJson.encodeToString(
                        mergeTurns(
                            conversation.turns(),
                            result.turns
                        )
                    ), transcriptFinal = result.finalized
                )
                services.database.conversations().save(saved)
                if (selected?.id == saved.id) selected = saved
                if (!automatic) message =
                    if (result.finalized) "Transcript updated." else "Transcript updated; finalization is still pending."
            } catch (e: Exception) {
                if (e is CancellationException) throw e; if (!automatic) message =
                    e.message ?: "Transcript could not be retrieved."
            }
        }
    }

    fun back() {
        when {
            studySetupOpen -> declineStudy(); endConfirmation -> endConfirmation = false; call != null -> endConfirmation =
            true; settingsOpen -> settingsOpen = false; selected != null -> selected =
            null; destination != "Home" -> destination = "Home"
        }
    }

    fun background() {
        if (starting) {
            callJob?.cancel(); starting = false; busy = false
        }
        if (call != null) {
            services.calls.disconnect(); finish(false)
        }
    }

    fun close() {
        joinJob?.cancel()
        refreshJob?.cancel()
        services.calls.disconnect(); api.close()
    }
}
