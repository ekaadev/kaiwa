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
data class Turn(val sequence: Int, val role: String, val text: String, val timestamp: String = "")
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
    fun title(): String = if (ordinal == null) "Practice conversation" else "Testing · Session $ordinal"
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
}

data class AppConfiguration(
    val serverUrl: String = BuildConfiguration.serverUrl,
    val allowDevelopmentHttp: Boolean = false,
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
