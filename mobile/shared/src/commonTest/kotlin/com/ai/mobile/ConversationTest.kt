package com.ai.mobile

import kotlin.test.*

class ConversationTest {
    @Test
    fun turnsAreOrderedAndRepeatedUpdatesReplaceExistingSequences() {
        val first = Turn(1, "user", "Hello")
        val corrected = first.copy(text = "こんにちは")
        val second = Turn(2, "assistant", "こんにちは。")
        assertEquals(listOf(corrected, second), mergeTurns(listOf(first), listOf(second, corrected)))
    }

    @Test
    fun serverAddressesRequireSecureTransportAndRejectEmbeddedCredentials() {
        assertEquals("https://example.org/api", validateServer(" https://example.org/api/ "))
        listOf(
            "",
            "http://example.org",
            "https://user:secret@example.org",
            "https://example.org?token=secret",
            "https://example.org#section"
        ).forEach { assertFailsWith<IllegalArgumentException> { validateServer(it) } }
    }

    @Test
    fun historySearchIncludesRealTranscriptContent() {
        val conversation = Conversation(
            "real-call",
            "practice",
            "https://server",
            null,
            1,
            turnsJson = "[{\"sequence\":1,\"role\":\"user\",\"text\":\"旅行が好きです\"}]"
        )
        assertTrue(conversation.matches("旅行"))
        assertTrue(conversation.matches("PRACTICE"))
        assertFalse(conversation.matches("not present"))
        assertEquals("2:01", durationLabel(121))
    }
}
