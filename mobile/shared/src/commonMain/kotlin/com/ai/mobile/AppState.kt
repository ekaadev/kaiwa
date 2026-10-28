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

/** What the server reports about taking a call right now. */
enum class ServerStatus { Checking, Online, Busy, Offline }

/** Where the UAT flow is inside the Testing tab. */
enum class UatScreen { Overview, Brief, Rating, Marks, Preference }

class AppState(
    val services: AppServices,
    private val scope: CoroutineScope,
    val api: ConversationApi = ConversationApi()
) {
    val researcherMode = services.configuration.researcherMode
    var destination by mutableStateOf("Home")
    /** Furigana display preference for transcripts and subtitles. */
    var furigana by mutableStateOf(true)
    /** "UAT" or "Study" inside Testing (researcher mode). */
    var testingTab by mutableStateOf("UAT")
    /** Server-held UAT run for this expert; null until a run is created on this device. */
    var uat by mutableStateOf<UatRun?>(null)
    var uatToken by mutableStateOf("")
    var uatScreen by mutableStateOf(UatScreen.Overview)
    /** Trial ordinal on screen (1-24). */
    var uatTrial by mutableStateOf(1)
    var uatPair by mutableStateOf(0)
    var uatBusy by mutableStateOf(false)
    /** Pilot or main for the run that the first "Start trials" will create. */
    var uatPilotChoice by mutableStateOf(true)
    var uatError by mutableStateOf<String?>(null)
    /** Unsent rating and turn labels for the trial on screen. */
    var draftRatings by mutableStateOf(List(4) { 0 })
    var draftLabels by mutableStateOf<Map<Int, String>>(emptyMap())
    private var uatEnrollKey: String? = null
    var sessionFilter by mutableStateOf("All")
    var serverStatus by mutableStateOf(ServerStatus.Checking)
    private var statusJob: Job? = null
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
    /** The call dropped; the user chooses between retrying the session and ending it. */
    var callFailed by mutableStateOf(false)
    private var joinJob: Job? = null
    private var refreshJob: Job? = null
    private var pendingEnrollment: Enrollment? = null
    private var enrollmentKey: String? = null
    private var retryAfterEnd = false
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
                if (server.isNotBlank()) {
                    uatToken = services.calls.readSecret("uat:$server") ?: ""
                }
                watchHistory()
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                message = "Study access could not be read from this device."
            } finally {
                settingsReady = true
            }
            if (uatToken.isNotBlank()) refreshUat()
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
                    "Disconnected" -> if (call != null && phase != "Ending") markCallFailed()

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

    /** Asks the server whether a call can start now; the Home badge shows exactly this answer. */
    fun checkServer() {
        if (server.isBlank()) {
            serverStatus = ServerStatus.Offline; return
        }
        if (statusJob?.isActive == true || showingCallScreen) return
        statusJob = scope.launch {
            serverStatus = try {
                withTimeout(8_000) { api.readiness(server) }
                ServerStatus.Online
            } catch (e: Exception) {
                if (e is CancellationException && e !is TimeoutCancellationException) throw e
                statusFor(e)
            }
        }
    }

    private fun statusFor(e: Exception) =
        if (e is ApiFailure && e.message?.contains("slots are busy") == true) ServerStatus.Busy else ServerStatus.Offline

    fun enterTesting() {
        destination = "Testing"
        if (testingTab == "UAT") {
            if (uatToken.isNotBlank()) refreshUat()
            return
        }
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
                val enrollment = pendingEnrollment
                    ?: api.enroll(server, enrollmentKeyFor(server)).also { pendingEnrollment = it }
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
                clearEnrollmentKey(server)
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

    /**
     * One random key per enrollment attempt, kept in secure storage so a lost response followed by
     * an app restart still resolves to the same participant. It is as sensitive as the resume token.
     */
    private fun enrollmentKeyFor(server: String): String {
        enrollmentKey?.let { return it }
        val storageKey = "study-enroll:$server"
        val stored = runCatching { services.calls.readSecret(storageKey) }.getOrNull()
        val key = stored?.takeIf { it.length >= 32 }
            ?: (Uuid.random().toString() + Uuid.random().toString()).replace("-", "")
        if (key != stored) runCatching { services.calls.writeSecret(storageKey, key) }
        enrollmentKey = key
        return key
    }

    private fun clearEnrollmentKey(server: String) {
        enrollmentKey = null
        runCatching { services.calls.writeSecret("study-enroll:$server", null) }
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

    fun start(practice: Boolean = false, trial: Int? = null) {
        if (busy || starting || showingCallScreen) return
        val ordinal = trial?.plus(UAT_ORDINAL_BASE)
            ?: if (destination == "Testing" && !practice) selectedOrdinal else null
        if (trial == null && ordinal != null && token.isBlank()) {
            beginStudySetup()
            return
        }
        if (trial == null && ordinal != null && !canStartStudy(ordinal)) {
            message = "This session isn't available yet. Refresh Testing and try again."; return
        }
        val configuredServer = server
        val configuredToken = if (trial != null) uatToken else token
        val callOwner = when {
            trial != null -> uat?.participant_id ?: return
            ordinal == null -> "practice"
            else -> participant!!.participant_id
        }
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
                val issued = if (trial != null) api.startUatTrial(configuredServer, configuredToken, trial, key)
                else api.start(configuredServer, configuredToken, ordinal, key)
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
                if (call == null) serverStatus = statusFor(e)
                if (call != null) {
                    services.calls.disconnect(); markCallFailed()
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
            val trial = current.uatOrdinal
            val learnerSpoke = saved.hasLearnerSpeech()
            try {
                if (learnerSpoke) services.database.conversations().save(saved)
                else {
                    // Calls without learner speech are not kept in the local history.
                    services.database.conversations().delete(saved.id)
                    message = "No speech from you was heard, so this call was not saved."
                }
            } catch (e: Exception) {
                selected = saved; message =
                    "Conversation could not be saved. Keep this screen open to read your transcript."
            }
            destination = if (current.ordinal != null) "Testing" else "Home"
            if (trial != null) {
                uatTrial = trial
                afterTrialCall(ended)
            }
            if (current.ordinal != null) services.calls.writeSecret(
                attemptSecret(
                    current.server,
                    current.owner,
                    current.ordinal
                ), null
            )
            call = null; activeToken = null; startedConnected = null; phase = "Ended"
            callFailed = false
            if (current.ordinal != null && current.uatOrdinal == null) refresh()
            if (retryAfterEnd) {
                retryAfterEnd = false
                redial(current)
            }
        }
    }

    private fun markCallFailed() {
        if (call == null || phase == "Ending") return
        // Stop counting connected time while the connection is down.
        connectedAccumulated += startedConnected?.let { time - it } ?: 0
        startedConnected = null
        phase = "Connection lost"
        endConfirmation = false
        callFailed = true
    }

    /** "End": keep the transcript as an interrupted conversation. */
    fun endFailedCall() {
        if (!callFailed) return
        callFailed = false
        finish(false)
    }

    /** "Retry session": save what exists, then place a new call for the same session. */
    fun retryFailedCall() {
        if (!callFailed) return
        callFailed = false
        retryAfterEnd = true
        finish(false)
    }

    private suspend fun redial(previous: Conversation) {
        selected = null
        if (previous.uatOrdinal != null) {
            destination = "Testing"; testingTab = "UAT"
            uatTrial = previous.uatOrdinal!!
            refreshUat().join()
            message = null
            startTrialCall()
            return
        }
        if (previous.ordinal == null) {
            destination = "Home"
        } else {
            destination = "Testing"
            selectedOrdinal = previous.ordinal
            // The server needs a moment to release the interrupted attempt; wait for fresh state.
            refreshJob?.join()
        }
        message = null
        start()
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
                    if (conversation.ordinal == null) services.calls.readSecret("call:${conversation.server}:${conversation.id}") else if (conversation.uatOrdinal != null && conversation.owner == uat?.participant_id && conversation.server == server) uatToken else if (conversation.owner == participant?.participant_id && conversation.server == server) token else null
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

    /** Reads this expert's run from the server; the server is the only holder of trial state. */
    fun refreshUat(): Job {
        if (server.isBlank() || uatToken.isBlank()) return scope.launch { }
        return scope.launch {
            uatBusy = true
            try {
                uat = api.uatRun(server, uatToken)
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                message = if (e is ApiFailure) e.message else "The UAT run could not be loaded."
            } finally {
                uatBusy = false
            }
        }
    }

    private fun createUatRun(pilot: Boolean, then: () -> Unit) {
        if (uatBusy) return
        if (server.isBlank()) {
            uatError = "Testing is not connected yet. Please try again later."; return
        }
        uatBusy = true; uatError = null
        scope.launch {
            try {
                val key = uatEnrollKey ?: (Uuid.random().toString() + Uuid.random().toString()).replace("-", "")
                uatEnrollKey = key
                val (run, resume) = api.createUatRun(server, null, pilot, key)
                services.calls.writeSecret("uat:$server", resume)
                uatToken = resume; uat = run; uatEnrollKey = null
                uatScreen = UatScreen.Overview
                then()
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                uatError = if (e is ApiFailure) e.message else "The run could not be created. Check the connection."
            } finally {
                uatBusy = false
            }
        }
    }

    /** Leaves the current run: the server keeps its data and marks it abandoned. */
    fun exitUatRun() = uatAction {
        if (!showingCallScreen) {
            api.abandonUatRun(server, uatToken)
            detachUatRun()
            message = "You left the run. Its results stay on the server."
        }
    }

    /** Detaches this device from the finished run; the run and its data stay on the server. */
    fun startNewUatRun() {
        if (uatBusy || showingCallScreen) return
        detachUatRun()
    }

    private fun detachUatRun() {
        runCatching { services.calls.writeSecret("uat:$server", null) }
        uatToken = ""; uat = null; uatScreen = UatScreen.Overview; uatError = null
        draftRatings = List(4) { 0 }; draftLabels = emptyMap()
    }

    private fun uatAction(block: suspend () -> Unit) {
        if (uatBusy) return
        uatBusy = true
        scope.launch {
            try {
                block()
            } catch (e: Exception) {
                if (e is CancellationException) throw e
                message = if (e is ApiFailure) e.message else "That step could not be saved. Check the connection."
            } finally {
                uatBusy = false
            }
        }
    }

    /** Opens the brief for the next trial that still needs work, or its rating if the call already ended. */
    fun startTrials() {
        val run = uat
        if (run == null) {
            // The run is created on the server only when the first trial is started.
            createUatRun(uatPilotChoice) { uat?.nextTrial()?.let(::openTrial) }
            return
        }
        run.nextTrial()?.let(::openTrial)
    }

    private fun openTrial(trial: UatTrial) {
        uatTrial = trial.ordinal
        draftRatings = List(4) { 0 }; draftLabels = emptyMap()
        uatScreen = if (trial.status == "awaiting_rating") UatScreen.Rating else UatScreen.Brief
    }

    fun startTrialCall() {
        if (busy || starting || showingCallScreen || uat?.trial(uatTrial) == null) return
        destination = "Testing"
        start(trial = uatTrial)
    }

    /** After a trial call ends: refresh the server state, then rate it or explain why it cannot be rated. */
    private fun afterTrialCall(normalEnd: Boolean) {
        scope.launch {
            refreshUat().join()
            val trial = uat?.trial(uatTrial)
            if (trial?.status == "awaiting_rating") {
                draftRatings = List(4) { 0 }; draftLabels = emptyMap(); uatScreen = UatScreen.Rating
            } else {
                uatScreen = UatScreen.Brief
                message = if (normalEnd) "That call was too short to count. Please try the trial again."
                else "The call was interrupted. You can start the trial again."
            }
        }
    }

    fun skipTrial() = uatAction {
        api.skipUatTrial(server, uatToken, uatTrial)
        uat = api.uatRun(server, uatToken)
        advanceFrom(uatTrial)
    }

    fun rate(item: Int, score: Int) {
        draftRatings = draftRatings.mapIndexed { i, r -> if (i == item) score else r }
    }

    fun redoTrial() = uatAction {
        api.redoUatTrial(server, uatToken, uatTrial)
        uat = api.uatRun(server, uatToken)
        draftRatings = List(4) { 0 }; draftLabels = emptyMap()
        uatScreen = UatScreen.Brief
    }

    fun markTurn(sequence: Int, label: String) {
        draftLabels = draftLabels + (sequence to label)
    }

    fun saveTrial() = uatAction {
        api.rateUatTrial(server, uatToken, uatTrial, draftRatings, draftLabels.mapKeys { it.key.toString() })
        val run = api.uatRun(server, uatToken)
        uat = run
        val trial = run.trial(uatTrial) ?: return@uatAction
        val pair = run.inSession(trial.test_session).filter { it.scenario == trial.scenario }
        if (pair.all { it.finished } && run.preferences.none { it.test_session == trial.test_session && it.scenario == trial.scenario }) {
            uatPair = trial.scenario; uatScreen = UatScreen.Preference
        } else advanceFrom(uatTrial)
    }

    fun choosePreference(choice: String) = uatAction {
        val trial = uat?.trial(uatTrial) ?: return@uatAction
        api.setUatPreference(server, uatToken, trial.test_session, uatPair, choice)
        uat = api.uatRun(server, uatToken)
        advanceFrom(uatTrial)
    }

    private fun advanceFrom(@Suppress("UNUSED_PARAMETER") trial: Int) {
        val next = uat?.nextTrial()
        if (next == null) {
            uatScreen = UatScreen.Overview
            message = "All test sessions are complete."
        } else if (next.test_session != uat?.trial(uatTrial)?.test_session) {
            uatScreen = UatScreen.Overview
            message = "Test session ${next.test_session - 1} is complete."
        } else openTrial(next)
    }

    /** The trial a saved conversation belongs to, if it was a UAT call. */
    fun trialOf(conversation: Conversation): UatTrial? = conversation.uatOrdinal?.let { uat?.trial(it) }

    fun back() {
        when {
            callFailed -> endFailedCall()
            destination == "Testing" && testingTab == "UAT" && selected == null && uatScreen != UatScreen.Overview ->
                uatScreen = if (uatScreen == UatScreen.Marks) UatScreen.Rating else UatScreen.Overview
            studySetupOpen -> declineStudy(); endConfirmation -> endConfirmation = false; call != null -> endConfirmation =
            true; selected != null -> selected =
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
