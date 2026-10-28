package com.ai.mobile

import io.ktor.client.*
import io.ktor.client.plugins.*
import io.ktor.client.request.*
import io.ktor.client.statement.*
import io.ktor.http.*
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.encodeToJsonElement

class ApiFailure(val status: Int, message: String) : IllegalStateException(message)

open class ConversationApi {
    private val client = HttpClient {
        install(HttpTimeout) { requestTimeoutMillis = 45_000; connectTimeoutMillis = 15_000 }
    }

    suspend fun request(
        server: String,
        path: String,
        token: String? = null,
        body: String? = null,
        key: String? = null,
        verb: HttpMethod? = null
    ): String {
        val response = client.request("$server$path") {
            method = verb ?: if (body == null) HttpMethod.Get else HttpMethod.Post
            if (token != null) bearerAuth(token)
            if (key != null) header("Idempotency-Key", key)
            if (body != null) {
                contentType(ContentType.Application.Json); setBody(body)
            }
        }
        val text = response.bodyAsText()
        if (!response.status.isSuccess()) {
            val message = when (response.status.value) {
                401 -> if (path.startsWith("/v1/uat/runs")) "This server does not allow creating UAT runs from the app." else if (path.startsWith("/v1/practice/")) "Transcript access has expired or is unavailable." else "Your study access is unavailable. Please contact the researcher."
                409 -> if (path.startsWith("/v1/uat/")) conflictMessage(text) else "This session is not available. Refresh Testing and try again."
                404 -> if (path.startsWith("/v1/uat/runs")) "UAT is not enabled on this server." else "This call or transcript is no longer available."
                503 -> if (text.contains("capacity_full")) "All call slots are busy. Please try again shortly." else "The call service is unavailable. Please try again later."
                else -> "The server could not complete the request (${response.status.value})."
            }
            throw ApiFailure(response.status.value, message)
        }
        return text
    }

    /** Throws unless the server reports that the tutor can take a call right now. */
    open suspend fun readiness(server: String) {
        request(server, "/v1/practice/readiness")
    }

    private fun conflictMessage(text: String) =
        Regex("\"detail\":\"([^\"]+)\"").find(text)?.groupValues?.get(1) ?: "That step is not available now."

    open suspend fun createUatRun(server: String, adminCode: String?, pilot: Boolean, key: String): Pair<UatRun, String> {
        val text = request(server, "/v1/uat/runs", adminCode, "{\"pilot\":$pilot}", key)
        return appJson.decodeFromString<UatRun>(text) to appJson.decodeFromString<UatCreated>(text).resume_token
    }

    open suspend fun uatRun(server: String, token: String): UatRun =
        appJson.decodeFromString(request(server, "/v1/uat/me", token))

    open suspend fun startUatTrial(server: String, token: String, ordinal: Int, key: String): CallCredentials =
        appJson.decodeFromString(request(server, "/v1/uat/trials/$ordinal/calls", token, "{}", key))

    open suspend fun abandonUatRun(server: String, token: String) {
        request(server, "/v1/uat/abandon", token, "{}")
    }

    open suspend fun skipUatTrial(server: String, token: String, ordinal: Int) {
        request(server, "/v1/uat/trials/$ordinal/skip", token, "{}")
    }

    open suspend fun redoUatTrial(server: String, token: String, ordinal: Int) {
        request(server, "/v1/uat/trials/$ordinal/redo", token, "{}")
    }

    open suspend fun rateUatTrial(server: String, token: String, ordinal: Int, ratings: List<Int>, labels: Map<String, String>) {
        val body = appJson.encodeToString(mapOf("ratings" to appJson.encodeToJsonElement(ratings), "labels" to appJson.encodeToJsonElement(labels)))
        request(server, "/v1/uat/trials/$ordinal/rating", token, body, verb = HttpMethod.Put)
    }

    open suspend fun setUatPreference(server: String, token: String, session: Int, scenario: Int, choice: String) {
        request(
            server, "/v1/uat/preferences", token,
            "{\"test_session\":$session,\"scenario\":$scenario,\"choice\":\"$choice\"}", verb = HttpMethod.Put,
        )
    }

    open suspend fun participant(server: String, token: String): Participant =
        appJson.decodeFromString(request(server, "/v1/study/me", token))

    /** [key] makes retries of this enrollment return the same participant; keep it secret. */
    open suspend fun enroll(server: String, key: String): Enrollment =
        appJson.decodeFromString(
            request(server, "/v1/study/participants", body = "{\"accepted\":true}", key = key)
        )

    open suspend fun start(server: String, token: String?, ordinal: Int?, key: String): CallCredentials {
        if (ordinal == null) request(server, "/v1/practice/readiness")
        return appJson.decodeFromString(
            request(
                server,
                if (ordinal == null) "/v1/practice/calls" else "/v1/study/sessions/$ordinal/calls",
                if (ordinal == null) null else token,
                "{}",
                key
            )
        )
    }

    open suspend fun transcript(server: String, id: String, token: String, study: Boolean, after: Int = 0): Transcript =
        appJson.decodeFromString(
            request(
                server,
                "/v1/${if (study) "study" else "practice"}/calls/$id/transcript?after=$after",
                token
            )
        )

    open suspend fun end(server: String, id: String, token: String?, study: Boolean) {
        request(server, "/v1/${if (study) "study" else "practice"}/calls/$id/end", token, "{}")
    }

    suspend fun telemetry(server: String, id: String, token: String, event: String, sequence: Int, timestamp: Long) {
        request(
            server,
            "/v1/study/calls/$id/events",
            token,
            "{\"event\":\"$event\",\"client_sequence\":$sequence,\"client_timestamp_ms\":$timestamp}"
        )
    }

    fun close() = client.close()
}
