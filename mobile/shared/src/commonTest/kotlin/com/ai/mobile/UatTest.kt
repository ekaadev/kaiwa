package com.ai.mobile

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class UatTest {
    private fun trial(ordinal: Int, status: String, scenario: Int = (ordinal - 1) / 2 % 4, session: Int = (ordinal - 1) / 8 + 1) =
        UatTrial(ordinal, session, scenario, session, if (ordinal % 2 == 1) "A" else "B", status)

    @Test
    fun serverViewDecodesWithoutAnyMethodField() {
        val json = """{"participant_id":"p","label":"EXP-01","pilot":true,"test_session":1,"complete":false,
            "trials":[{"ordinal":1,"test_session":1,"scenario":0,"repetition":1,"version":"A","status":"pending","available":true}],
            "preferences":[],"unexpected":1}"""
        val run = appJson.decodeFromString<UatRun>(json)
        assertEquals("A", run.trials.single().version)
        assertTrue(run.trials.single().available)
    }

    @Test
    fun runCountsFinishedTrialsAndPairsPerSession() {
        val trials = listOf(trial(1, "rated"), trial(2, "skipped"), trial(3, "pending"), trial(4, "pending"))
        val run = UatRun("p", "EXP-01", false, 1, false, trials)
        assertEquals(2, run.done())
        assertEquals(2, run.scenarioDone(0))
        assertEquals(0, run.scenarioDone(1))
        assertEquals(3, run.nextTrial()?.ordinal)
    }

    @Test
    fun positionInSessionRestartsEveryEightTrials() {
        assertEquals(1, trial(1, "pending").positionInSession)
        assertEquals(8, trial(8, "pending").positionInSession)
        assertEquals(1, trial(9, "pending").positionInSession)
    }

    @Test
    fun uatConversationsAreRecognisedByOrdinalBase() {
        val practice = Conversation("a", "practice", "s", null, 0)
        val study = Conversation("b", "p", "s", 2, 0)
        val trial = Conversation("c", "p", "s", UAT_ORDINAL_BASE + 5, 0)
        assertNull(practice.uatOrdinal)
        assertNull(study.uatOrdinal)
        assertEquals(5, trial.uatOrdinal)
    }

    @Test
    fun civilDateHandlesEpochAndLeapDay() {
        assertEquals(Triple(1970, 1, 1), civilDate(0))
        assertEquals(Triple(2024, 2, 29), civilDate(19782))
    }

    @Test
    fun replyGapIsOnlyReportedWhenTheTutorAnswersTheLearner() {
        val turns = listOf(
            Turn(1, "assistant", "a", "2026-10-05T10:00:00Z"),
            Turn(2, "user", "b", "2026-10-05T10:00:07Z"),
            Turn(3, "assistant", "c", "2026-10-05T10:00:07.640Z"),
        )
        assertEquals(null, replyGapMillis(turns, 1))
        assertEquals(640L, replyGapMillis(turns, 2))
        assertEquals("0:07", turnOffset(turns, turns[1]))
    }

    @Test
    fun csvEscapesFormulasAndNeverContainsAMethodColumn() {
        val turns = appJson.encodeToString(listOf(Turn(1, "user", "=1+1 \"x\"")))
        val conversation = Conversation("c", "practice", "s", null, 0, turnsJson = turns)
        val csv = conversationCsv(
            conversation, trial(1, "rated").copy(call_id = "c", labels = mapOf("1" to "Fine")),
            UatRun("p", "EXP-01", true, 1, false, emptyList()),
        )
        assertTrue(csv.contains("\"'=1+1 \"\"x\"\"\""))
        assertTrue(csv.contains("\"Fine\""))
        assertFalse(csv.lines().first().contains("method") || csv.lines().first().contains("mode"))
        assertTrue(csv.lines().first().startsWith("participant,pilot,run_status,"))
        assertTrue(csv.lines()[1].startsWith("\"EXP-01\",\"true\",\"in_progress\""))
    }
}
