package com.ai.mobile

import io.ktor.client.*
import io.ktor.client.plugins.*
import io.ktor.client.request.*
import io.ktor.client.statement.*
import io.ktor.http.*

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
        key: String? = null
    ): String {
        val response = client.request("$server$path") {
            method = if (body == null) HttpMethod.Get else HttpMethod.Post
            if (token != null) bearerAuth(token)
            if (key != null) header("Idempotency-Key", key)
            if (body != null) {
                contentType(ContentType.Application.Json); setBody(body)
            }
        }
        val text = response.bodyAsText()
        if (!response.status.isSuccess()) {
            val message = when (response.status.value) {
                401 -> if (path.startsWith("/v1/practice/")) "Transcript access has expired or is unavailable." else "Your study access is unavailable. Please contact the researcher."
                409 -> "This session is not available. Refresh Testing and try again."
                503 -> if (text.contains("capacity_full")) "All call slots are busy. Please try again shortly." else "The call service is unavailable. Please try again later."
                404 -> "This call or transcript is no longer available."
                else -> "The server could not complete the request (${response.status.value})."
            }
            throw ApiFailure(response.status.value, message)
        }
        return text
    }

    open suspend fun participant(server: String, token: String): Participant =
        appJson.decodeFromString(request(server, "/v1/study/me", token))

    open suspend fun enroll(server: String): Enrollment =
        appJson.decodeFromString(request(server, "/v1/study/participants", body = "{\"accepted\":true}"))

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
