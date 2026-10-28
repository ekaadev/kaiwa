@file:OptIn(kotlin.time.ExperimentalTime::class)

package com.ai.mobile

import kotlin.time.Instant

val uatScenarios = listOf(
    "Restaurant" to "You are at a restaurant. Order a meal and ask for the bill.",
    "Hotel check-in" to "You arrive at a hotel. Give your name and ask for three nights.",
    "Directions" to "You are lost. Ask how to get to the station.",
    "Shopping" to "You are in a shop. Ask the price of an item and pay.",
)

val likertItems = listOf(
    "Timing felt natural",
    "The AI cut me off",
    "The AI waited too long",
    "Overall conversation flow",
)

val turnLabels = listOf("Cut off", "Too slow", "Fine")

fun Conversation.hasLearnerSpeech() = turns().any { it.role == "user" }

private val months = listOf("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
private val monthNames = listOf(
    "January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
    "November", "December",
)

/** Civil date (year, month 1-12, day) from days since the epoch. */
fun civilDate(epochDay: Long): Triple<Int, Int, Int> {
    val z = epochDay + 719468
    val era = z.floorDiv(146097L)
    val doe = z - era * 146097
    val yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365
    val doy = doe - (365 * yoe + yoe / 4 - yoe / 100)
    val mp = (5 * doy + 2) / 153
    val day = (doy - (153 * mp + 2) / 5 + 1).toInt()
    val month = (if (mp < 10) mp + 3 else mp - 9).toInt()
    val year = (yoe + era * 400 + if (month <= 2) 1 else 0).toInt()
    return Triple(year, month, day)
}


fun shortDate(timestamp: Long): String {
    val (_, month, day) = civilDate(localEpochDay(timestamp))
    return "${months[month - 1]} $day"
}

fun monthLabel(timestamp: Long): String {
    val (year, month, _) = civilDate(localEpochDay(timestamp))
    return "${monthNames[month - 1]} $year"
}

/** Consecutive local days with a saved call, counted back from today (or yesterday). */
fun streakDays(conversations: List<Conversation>, now: Long): Int {
    val days = conversations.filter { it.hasLearnerSpeech() }.map { localEpochDay(it.started) }.toSet()
    var day = localEpochDay(now)
    if (day !in days) day -= 1
    var count = 0
    while (day in days) {
        count++; day--
    }
    return count
}

fun turnMillis(turn: Turn): Long? = runCatching { Instant.parse(turn.timestamp).toEpochMilliseconds() }.getOrNull()

/** Seconds from the first turn, as m:ss, or null if timestamps cannot be read. */
fun turnOffset(turns: List<Turn>, turn: Turn): String? {
    val start = turns.firstNotNullOfOrNull { turnMillis(it) } ?: return null
    val at = turnMillis(turn) ?: return null
    return durationLabel(((at - start) / 1000).coerceAtLeast(0))
}

/**
 * Gap between a learner turn and the tutor turn that follows, from transcript time stamps. These are text
 * times, not audio times, so they are only an approximation of the real reply delay.
 */
fun replyGapMillis(turns: List<Turn>, index: Int): Long? {
    val turn = turns[index]
    val previous = turns.getOrNull(index - 1) ?: return null
    if (turn.role == "user" || previous.role != "user") return null
    val a = turnMillis(previous) ?: return null
    val b = turnMillis(turn) ?: return null
    return (b - a).coerceAtLeast(0)
}

private fun csvCell(value: String): String {
    val safe = if (value.firstOrNull() in listOf('=', '+', '-', '@')) "'$value" else value
    return "\"" + safe.replace("\"", "\"\"") + "\""
}

/**
 * Researcher export of one conversation. The detection method is not on the device, so it is not in this
 * file; the server export (`/v1/uat/export.csv`) joins it by conversation id.
 */
fun conversationCsv(conversation: Conversation, trial: UatTrial?, run: UatRun?): String {
    val turns = conversation.turns()
    val current = trial?.call_id == conversation.id
    val rows = mutableListOf(
        "participant,pilot,run_status,conversation_id,scenario,version,current_attempt,sequence,role,timestamp,text,reply_gap_ms_text_time,turn_label"
    )
    turns.forEachIndexed { i, turn ->
        rows += listOf(
            run?.label ?: "",
            run?.pilot?.toString() ?: "",
            run?.let { if (it.abandoned) "abandoned" else if (it.complete) "complete" else "in_progress" } ?: "",
            conversation.id,
            trial?.let { uatScenarios[it.scenario].first } ?: "",
            trial?.version ?: "",
            if (trial == null) "" else current.toString(),
            turn.sequence.toString(),
            turn.role,
            turn.timestamp,
            turn.text,
            replyGapMillis(turns, i)?.toString() ?: "",
            if (current) trial?.labels?.get(turn.sequence.toString()) ?: "" else "",
        ).joinToString(",") { csvCell(it) }
    }
    return rows.joinToString("\n")
}

fun transcriptText(conversation: Conversation): String =
    "Kaiwa · ${formatDate(conversation.started)}\n\n" + conversation.turns().joinToString("\n\n") {
        "${if (it.role == "user") "You" else "Kaiwa"}: ${it.text}" + if (it.gloss.isNotBlank()) "\n${it.gloss}" else ""
    }
