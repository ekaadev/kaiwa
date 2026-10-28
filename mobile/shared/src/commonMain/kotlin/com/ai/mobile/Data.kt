package com.ai.mobile

import androidx.compose.runtime.Composable
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.room.*
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

val appJson = Json { ignoreUnknownKeys = true; encodeDefaults = true }

@Serializable
data class Turn(
    val sequence: Int,
    val role: String,
    val text: String,
    val timestamp: String = "",
    /** English gloss; the backend does not send one yet. */
    val gloss: String = "",
)
@Serializable
data class Transcript(val turns: List<Turn> = emptyList(), val finalized: Boolean = false)
@Serializable
data class StudySession(val ordinal: Int, val status: String, val available: Boolean)
@Serializable
data class Participant(val participant_id: String, val sessions: List<StudySession>)
@Serializable
data class Enrollment(val participant_id: String, val sessions: List<StudySession>, val resume_token: String) {
    fun participant() = Participant(participant_id, sessions)
}
@Serializable
data class CallCredentials(
    val call_id: String,
    val room_url: String,
    val join_token: String,
    val transcript_token: String? = null
)

@Serializable
data class UatTrial(
    val ordinal: Int,
    val test_session: Int,
    val scenario: Int,
    val repetition: Int,
    /** Neutral letter; the server never sends the detection method. */
    val version: String,
    /** pending, in_progress, awaiting_rating, rated or skipped. */
    val status: String,
    val attempts: Int = 0,
    val available: Boolean = false,
    val call_id: String? = null,
    val ratings: List<Int>? = null,
    val labels: Map<String, String>? = null,
) {
    val finished get() = status == "rated" || status == "skipped"
    /** 1-based position inside its test session (8 per session). */
    val positionInSession get() = (ordinal - 1) % 8 + 1
}
@Serializable
data class UatPreferenceView(val test_session: Int, val scenario: Int, val choice: String)
@Serializable
data class UatRun(
    val participant_id: String,
    val label: String,
    val pilot: Boolean,
    val test_session: Int,
    val complete: Boolean,
    val trials: List<UatTrial>,
    val preferences: List<UatPreferenceView> = emptyList(),
    val abandoned: Boolean = false,
) {
    fun inSession(session: Int = test_session) = trials.filter { it.test_session == session }
    fun done(session: Int = test_session) = inSession(session).count { it.finished }
    fun scenarioDone(scenario: Int, session: Int = test_session) =
        inSession(session).count { it.scenario == scenario && it.finished }
    fun nextTrial() = trials.firstOrNull { !it.finished }
    fun trial(ordinal: Int) = trials.firstOrNull { it.ordinal == ordinal }
}
@Serializable
data class UatCreated(val resume_token: String)

/** Conversations of UAT trials are stored with ordinal = this base + trial ordinal. */
const val UAT_ORDINAL_BASE = 1000

@Entity(tableName = "conversations")
data class Conversation(
    @PrimaryKey val id: String,
    val owner: String,
    val server: String,
    val ordinal: Int?,
    val started: Long,
    val duration: Long = 0,
    val outcome: String = "Interrupted",
    val turnsJson: String = "[]",
    val transcriptFinal: Boolean = false,
) {
    fun turns(): List<Turn> = appJson.decodeFromString(turnsJson)
    val uatOrdinal: Int? get() = ordinal?.takeIf { it >= UAT_ORDINAL_BASE }?.minus(UAT_ORDINAL_BASE)
    fun title(): String = when {
        ordinal == null -> "Practice conversation"
        uatOrdinal != null -> "Testing · Trial $uatOrdinal"
        else -> "Testing · Session $ordinal"
    }
    fun matches(query: String): Boolean = title().contains(query, true) || turns().any { it.text.contains(query, true) }
}

@Dao
interface ConversationDao {
    @Query("SELECT * FROM conversations WHERE owner = :owner ORDER BY started DESC")
    fun observe(owner: String): Flow<List<Conversation>>
    @Upsert
    suspend fun save(conversation: Conversation)
    @Query("DELETE FROM conversations WHERE id = :id")
    suspend fun delete(id: String)
}

@Database(entities = [Conversation::class], version = 1, exportSchema = false)
@ConstructedBy(ConversationDatabaseConstructor::class)
abstract class ConversationDatabase : RoomDatabase() {
    abstract fun conversations(): ConversationDao
}

@Suppress("NO_ACTUAL_FOR_EXPECT")
expect object ConversationDatabaseConstructor : RoomDatabaseConstructor<ConversationDatabase> {
    override fun initialize(): ConversationDatabase
}

class SettingsStore(private val store: DataStore<Preferences>) {
    val server: Flow<String> = store.data.map { it[stringPreferencesKey("server")] ?: "" }
    suspend fun saveServer(url: String) {
        store.edit { it[stringPreferencesKey("server")] = url }
    }
}

interface NativeCalls {
    suspend fun requestMicrophone(): Boolean
    suspend fun connect(url: String, token: String)
    suspend fun mute(muted: Boolean)
    fun disconnect()
    fun observe(listener: (String) -> Unit)
    fun openPermissionSettings()
    fun readSecret(key: String): String?
    fun writeSecret(key: String, value: String?)
    /** Opens the system share sheet with plain text; false when the platform cannot share yet. */
    fun shareText(title: String, text: String): Boolean = false
}

data class AppConfiguration(
    val serverUrl: String = BuildConfiguration.serverUrl,
    val allowDevelopmentHttp: Boolean = false,
    /** Build-time switch: shows Testing, timing details and the researcher overlay. */
    val researcherMode: Boolean = BuildConfiguration.researcherMode,
)

class AppServices(
    val database: ConversationDatabase,
    val settings: SettingsStore,
    val calls: NativeCalls,
    val configuration: AppConfiguration = AppConfiguration(),
)

@Composable
expect fun platformServices(): AppServices
expect fun formatDate(timestamp: Long): String
/** Whole days since 1970-01-01 in the device's local time zone. */
expect fun localEpochDay(timestamp: Long): Long
/** True when the user asked the system to reduce animation. */
@Composable
expect fun rememberReducedMotion(): Boolean

fun validateServer(raw: String, allowDevelopmentHttp: Boolean = false): String {
    val value = raw.trim().trimEnd('/')
    require(value.startsWith("https://") || (allowDevelopmentHttp && value.startsWith("http://"))) { "Enter an HTTPS server address." }
    val url = io.ktor.http.Url(value)
    require(url.host.isNotBlank() && url.user == null && url.password == null && url.parameters.isEmpty() && url.fragment.isEmpty()) { "Enter a server address without credentials, query, or fragment." }
    return value
}

fun mergeTurns(old: List<Turn>, new: List<Turn>): List<Turn> =
    (old + new).associateBy { it.sequence }.values.sortedBy { it.sequence }

fun durationLabel(seconds: Long) = "${seconds / 60}:${(seconds % 60).toString().padStart(2, '0')}"
