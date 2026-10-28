@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)

package com.ai.mobile

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlin.time.Clock
import kotlinx.coroutines.delay

@OptIn(kotlin.time.ExperimentalTime::class)
@Composable
fun Home(state: AppState) {
    val last = state.conversations.firstOrNull { it.hasLearnerSpeech() && it.ordinal == null }
    val streak = streakDays(state.conversations.filter { it.ordinal == null }, Clock.System.now().toEpochMilliseconds())
    LaunchedEffect(Unit) {
        while (true) {
            state.checkServer()
            delay(10_000)
        }
    }
    val ready = state.serverStatus == ServerStatus.Online
    Column(Modifier.fillMaxSize()) {
        KTopBar("Kaiwa") {
            if (streak > 0) KChip(
                if (streak == 1) "1 day" else "$streak days",
                streak = true,
                leading = { Symbol("fire", size = 18.dp, color = Kaiwa.Danger) },
            )
        }
        BoxWithConstraints(Modifier.weight(1f).fillMaxWidth()) {
            val stageHeight = (maxHeight - 230.dp).coerceIn(280.dp, 456.dp)
            Column(
                Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 24.dp).padding(bottom = 16.dp),
                verticalArrangement = Arrangement.spacedBy(14.dp),
            ) {
                Box(
                    Modifier.fillMaxWidth().height(stageHeight).clip(RoundedCornerShape(Kaiwa.RadiusStage))
                        .background(Kaiwa.PrimaryTint)
                ) {
                    StatusBadge(
                        when {
                            state.server.isBlank() -> "Offline · not connected"
                            state.busy -> "Connecting"
                            else -> when (state.serverStatus) {
                                ServerStatus.Checking -> "Checking server…"
                                ServerStatus.Online -> "Online · ready to call"
                                ServerStatus.Busy -> "Busy · try again soon"
                                ServerStatus.Offline -> "Offline · can't take calls"
                            }
                        },
                        Modifier.align(Alignment.TopStart).padding(16.dp),
                        active = ready || state.busy,
                    )
                    KaiwaAvatar(
                        Modifier.align(Alignment.TopCenter).padding(top = 48.dp)
                            .height((stageHeight - 48.dp - 96.dp).coerceAtLeast(120.dp))
                    )
                    Column(
                        Modifier.align(Alignment.BottomCenter).padding(14.dp).fillMaxWidth()
                            .background(Kaiwa.Card, RoundedCornerShape(Kaiwa.RadiusControl))
                            .border(BorderStroke(1.5.dp, Kaiwa.Outline), RoundedCornerShape(Kaiwa.RadiusControl))
                            .padding(horizontal = 16.dp, vertical = 8.dp),
                        horizontalAlignment = Alignment.CenterHorizontally,
                    ) {
                        Text("今日は何を話す？", style = MaterialTheme.typography.bodyLarge.copy(fontSize = 22.sp, lineHeight = 36.sp, fontFamily = japaneseFontFamily()))
                        Text("Just start talking whenever you're ready.", style = MaterialTheme.typography.bodySmall, color = Kaiwa.InkMuted)
                    }
                }
                ChunkyButton(
                    if (state.busy) "Preparing…" else "Start call",
                    { state.start(practice = true) },
                    enabled = !state.busy && ready,
                )
                if (last != null) KCard(onClick = { state.selected = last; state.destination = "Session" }) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(Modifier.weight(1f)) {
                            Text("Last call", style = MaterialTheme.typography.titleMedium)
                            Text(callSummary(last), style = MaterialTheme.typography.bodySmall, color = Kaiwa.InkMuted)
                        }
                        Symbol("chevron_right", color = Kaiwa.InkMuted)
                    }
                }
            }
        }
    }
}

private fun callSummary(c: Conversation) = "${shortDate(c.started)} · ${durationLabel(c.duration)} · ${c.turns().size} turns"

private sealed interface HistoryRow {
    data class Header(val text: String) : HistoryRow
    data class Item(val conversation: Conversation) : HistoryRow
}

@Composable
fun History(state: AppState) {
    var menu by remember { mutableStateOf(false) }
    val kept = state.conversations.filter { it.hasLearnerSpeech() }
    val isTrial = { c: Conversation -> c.uatOrdinal != null }
    val isTesting = { c: Conversation -> c.ordinal != null || isTrial(c) }
    val shown = kept.filter {
        when (state.sessionFilter) {
            "Practice" -> !isTesting(it); "Testing" -> isTesting(it); else -> true
        }
    }
    val rows = buildList {
        shown.filter { !isTesting(it) }.groupBy { monthLabel(it.started) }.forEach { (month, items) ->
            add(HistoryRow.Header(month)); items.forEach { add(HistoryRow.Item(it)) }
        }
        val trials = shown.filter(isTrial)
        if (trials.isNotEmpty()) {
            add(HistoryRow.Header("Testing · ${state.uat?.label ?: "UAT"}")); trials.forEach { add(HistoryRow.Item(it)) }
        }
        val study = shown.filter { it.ordinal != null && !isTrial(it) }
        if (study.isNotEmpty()) {
            add(HistoryRow.Header("Testing · Study")); study.forEach { add(HistoryRow.Item(it)) }
        }
    }
    Column(Modifier.fillMaxSize()) {
        KTopBar("Session") {
            if (state.researcherMode) Box {
                KChip(state.sessionFilter, leading = null, onClick = { menu = true }, modifier = Modifier)
                DropdownMenu(menu, { menu = false }) {
                    listOf("All", "Practice", "Testing").forEach {
                        DropdownMenuItem({ Text(it) }, { state.sessionFilter = it; menu = false })
                    }
                }
            }
        }
        if (rows.isEmpty()) Column(
            Modifier.fillMaxSize().padding(32.dp),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Symbol("forum", size = 64.dp, color = Kaiwa.Primary)
            Text("Your conversations live here", Modifier.padding(top = 20.dp), style = MaterialTheme.typography.titleLarge, textAlign = TextAlign.Center)
            Text(
                "After a call, come back to read your transcript.",
                Modifier.padding(top = 12.dp),
                style = MaterialTheme.typography.bodyMedium,
                color = Kaiwa.InkMuted,
                textAlign = TextAlign.Center
            )
        } else LazyColumn(contentPadding = PaddingValues(horizontal = 24.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            items(rows.size) { i ->
                when (val row = rows[i]) {
                    is HistoryRow.Header -> Text(row.text, Modifier.padding(top = 6.dp), style = MaterialTheme.typography.bodySmall, color = Kaiwa.InkMuted)
                    is HistoryRow.Item -> HistoryCard(state, row.conversation)
                }
            }
        }
    }
}

@Composable
private fun HistoryCard(state: AppState, c: Conversation) {
    val trial = state.trialOf(c)
    KCard(onClick = { state.selected = c }) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(12.dp)) {
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(
                        when {
                            trial != null -> "Trial ${trial.positionInSession} · ${uatScenarios[trial.scenario].first}"
                            c.ordinal != null -> "Study session ${c.ordinal}"
                            else -> "Practice call"
                        },
                        style = MaterialTheme.typography.titleMedium,
                        modifier = Modifier.weight(1f, fill = false),
                    )
                    // Only the neutral letter is shown, never the detection mode.
                    if (trial != null) KChip("Version ${trial.version}", on = true)
                }
                val extra = trial?.let { t ->
                    if (t.call_id != c.id) " · earlier attempt" else if (t.status == "rated") " · rated" else ""
                } ?: ""
                Text(callSummary(c) + extra, style = MaterialTheme.typography.bodySmall, color = Kaiwa.InkMuted)
            }
            Symbol("chevron_right", color = Kaiwa.InkMuted)
        }
    }
}

@Composable
private fun TurnBubble(turns: List<Turn>, turn: Turn, researcher: Boolean, label: String?) {
    val mine = turn.role == "user"
    val who = (if (mine) "You" else "Kaiwa") + (turnOffset(turns, turn)?.let { " · $it" } ?: "")
    Column(
        Modifier.fillMaxWidth(),
        horizontalAlignment = if (mine) Alignment.End else Alignment.Start,
        verticalArrangement = Arrangement.spacedBy(2.dp),
    ) {
        Text(who.uppercase(), style = MaterialTheme.typography.labelMedium.copy(letterSpacing = 0.8.sp), color = Kaiwa.InkMuted)
        Column(
            Modifier.fillMaxWidth(0.88f).background(if (mine) Kaiwa.PrimaryTint else Kaiwa.Card, RoundedCornerShape(Kaiwa.RadiusControl))
                .then(if (mine) Modifier else Modifier.border(BorderStroke(1.5.dp, Kaiwa.Outline), RoundedCornerShape(Kaiwa.RadiusControl)))
                .padding(horizontal = 14.dp, vertical = 8.dp),
            horizontalAlignment = if (mine) Alignment.End else Alignment.Start,
        ) {
            SelectionContainer {
                Text(turn.text, style = MaterialTheme.typography.bodyLarge.copy(fontFamily = japaneseFontFamily(), lineHeight = 30.sp))
            }
            if (turn.gloss.isNotBlank()) Text(turn.gloss, style = MaterialTheme.typography.bodySmall, color = Kaiwa.InkMuted)
        }
    }
}

@Composable
fun TranscriptScreen(state: AppState, conversation: Conversation) {
    var deleting by remember { mutableStateOf(false) }
    LaunchedEffect(conversation.id) { state.recoverTranscript(conversation, automatic = true) }
    val turns = conversation.turns()
    val link = state.trialOf(conversation)
    Column(Modifier.fillMaxSize()) {
        KTopBar(
            "${shortDate(conversation.started)} · ${durationLabel(conversation.duration)}",
            onBack = { state.selected = null },
            small = true,
        ) { KChip("あ", on = state.furigana, onClick = { state.furigana = !state.furigana }) }
        LazyColumn(
            Modifier.weight(1f),
            contentPadding = PaddingValues(horizontal = 24.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            item {
                Text("${turns.size} turns · saved transcript", style = MaterialTheme.typography.bodySmall, color = Kaiwa.InkMuted)
            }
            if (state.researcherMode) item {
                Text("Reply gaps use transcript time stamps, not audio time.", style = MaterialTheme.typography.bodySmall, color = Kaiwa.InkMuted)
            }
            if (!conversation.transcriptFinal) item {
                Text(
                    "This transcript may be incomplete because the call or transcript connection was interrupted.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = Kaiwa.InkMuted
                )
                ChunkyButton("Retry transcript", { state.recoverTranscript(conversation) }, Modifier.padding(top = 12.dp), ChunkyStyle.Secondary, icon = "refresh", height = 48.dp)
            }
            if (turns.isEmpty()) item {
                Text("No completed speech turns were received for this call.", Modifier.padding(vertical = 32.dp), style = MaterialTheme.typography.bodyLarge)
            }
            items(turns.size, key = { turns[it].sequence }) { i ->
                val turn = turns[i]
                if (state.researcherMode) replyGapMillis(turns, i)?.let { gap ->
                    val cut = link?.takeIf { it.call_id == conversation.id }?.labels?.get(turns[i - 1].sequence.toString()) == "Cut off"
                    Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.Center) {
                        Text(
                            "AI replied after $gap ms" + if (cut) " · cut off" else "",
                            style = MaterialTheme.typography.labelMedium,
                            color = if (cut) Kaiwa.Danger else Kaiwa.InkMuted,
                            modifier = Modifier.border(BorderStroke(1.5.dp, if (cut) Kaiwa.Danger else Kaiwa.OutlineStrong), RoundedCornerShape(50))
                                .padding(horizontal = 10.dp, vertical = 2.dp),
                        )
                    }
                }
                TurnBubble(turns, turn, state.researcherMode, null)
            }
            item {
                Column(Modifier.padding(top = 8.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    if (state.researcherMode && link != null) KCard {
                        Text("Mode", style = MaterialTheme.typography.titleMedium)
                        Text("Never shown on the device. The researcher export from the server includes it.", style = MaterialTheme.typography.bodySmall, color = Kaiwa.InkMuted)
                    }
                    ChunkyButton(
                        "Share transcript",
                        {
                            if (!state.services.calls.shareText("Kaiwa transcript", transcriptText(conversation)))
                                state.message = "Sharing is not available on this device."
                        },
                        style = ChunkyStyle.Secondary,
                        enabled = turns.isNotEmpty(),
                    )
                    if (state.researcherMode) ChunkyButton(
                        if (link != null) "Export trial (CSV)" else "Export CSV",
                        {
                            if (!state.services.calls.shareText("Kaiwa CSV", conversationCsv(conversation, link, state.uat)))
                                state.message = "Sharing is not available on this device."
                        },
                        style = ChunkyStyle.Secondary,
                        enabled = turns.isNotEmpty(),
                    )
                    TextButton({ deleting = true }, Modifier.align(Alignment.CenterHorizontally)) {
                        Text("Delete from this device", color = Kaiwa.Danger)
                    }
                }
            }
        }
    }
    if (deleting) AlertDialog(
        onDismissRequest = { deleting = false },
        shape = RoundedCornerShape(Kaiwa.RadiusButtonLg),
        title = { Text("Delete this conversation?") },
        text = { Text("This permanently removes the transcript from this device. Research evidence on the server is managed by the researcher.") },
        confirmButton = { TextButton({ state.delete(conversation); deleting = false }) { Text("Delete") } },
        dismissButton = { TextButton({ deleting = false }) { Text("Cancel") } })
}

@Composable
fun CallScreen(state: AppState) {
    val enabled = state.phase != "Ending"
    val (mood, badge) = when (state.phase) {
        "Speaking" -> GlowMood.Speaking to "Speaking"
        "Listening" -> GlowMood.Listening to "Listening"
        "Ending" -> GlowMood.Flat to "Ending"
        "Connection lost" -> GlowMood.Flat to "Reconnecting"
        else -> GlowMood.Flat to "Connecting"
    }
    val reduced = rememberReducedMotion()
    val latest = state.turns.lastOrNull()
    val debug = state.researcherMode && state.call?.ordinal == null
    Column(Modifier.fillMaxSize().stageGlow(mood, reduced)) {
        Box(Modifier.weight(1f).fillMaxWidth()) {
            Column(Modifier.fillMaxSize().statusBarsPadding()) {
                Row(
                    Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 24.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    // Same as the system back gesture: asks before ending the call.
                    Box(
                        Modifier.size(48.dp).clickable(role = Role.Button) { state.back() }
                            .semantics { contentDescription = "End call options" },
                        contentAlignment = Alignment.Center,
                    ) { Symbol("expand", size = 28.dp, color = Kaiwa.Ink) }
                    Box(Modifier.weight(1f), contentAlignment = Alignment.Center) {
                        StatusBadge(badge, active = mood == GlowMood.Speaking)
                    }
                    Text(
                        durationLabel(state.elapsed),
                        Modifier.width(48.dp),
                        style = MaterialTheme.typography.titleMedium.copy(fontSize = 15.sp),
                        color = Kaiwa.PrimaryEdge,
                        textAlign = TextAlign.End,
                    )
                }
                Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
                    KaiwaAvatar(Modifier.fillMaxWidth(0.82f).aspectRatio(1f))
                }
            }
            if (debug) Column(
                Modifier.statusBarsPadding().padding(start = 20.dp, top = 84.dp)
                    .background(Kaiwa.Ink, RoundedCornerShape(Kaiwa.RadiusChip)).padding(horizontal = 12.dp, vertical = 8.dp)
            ) {
                // The backend does not expose the detector state yet, so these are placeholders.
                listOf("researcher mode", "mode: adaptive (practice)", "p(end) — · silence — ms", "detector values not exposed yet").forEach {
                    Text(it, style = MaterialTheme.typography.labelMedium.copy(fontSize = 12.sp, lineHeight = 19.sp), color = Kaiwa.Bg)
                }
            }
        }
        if (latest != null) Column(
            Modifier.padding(horizontal = 20.dp).padding(bottom = 16.dp).fillMaxWidth()
                .background(Kaiwa.Card, RoundedCornerShape(Kaiwa.RadiusControl))
                .border(BorderStroke(1.5.dp, Kaiwa.Outline), RoundedCornerShape(Kaiwa.RadiusControl))
                .padding(horizontal = 16.dp, vertical = 10.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Text(
                latest.text,
                style = MaterialTheme.typography.bodyLarge.copy(fontSize = 20.sp, lineHeight = 32.sp, fontFamily = japaneseFontFamily()),
                textAlign = TextAlign.Center,
                maxLines = 3,
            )
            if (latest.gloss.isNotBlank()) Text(latest.gloss, style = MaterialTheme.typography.bodySmall, color = Kaiwa.InkMuted, textAlign = TextAlign.Center)
        }
        Row(
            Modifier.fillMaxWidth()
                .background(Kaiwa.Bg, RoundedCornerShape(topStart = Kaiwa.RadiusStage, topEnd = Kaiwa.RadiusStage))
                .border(BorderStroke(1.5.dp, Kaiwa.Outline), RoundedCornerShape(topStart = Kaiwa.RadiusStage, topEnd = Kaiwa.RadiusStage))
                .navigationBarsPadding().padding(horizontal = 24.dp, vertical = 24.dp),
            horizontalArrangement = Arrangement.spacedBy(24.dp, Alignment.CenterHorizontally),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            ChunkySurface(
                { state.furigana = !state.furigana }, Modifier.width(60.dp), 60.dp, RoundedCornerShape(Kaiwa.RadiusControl),
                if (state.furigana) ChunkyStyle.Tint else ChunkyStyle.Secondary, edge = 5.dp,
                description = if (state.furigana) "Hide furigana" else "Show furigana",
            ) { ink -> Text("あ", style = MaterialTheme.typography.bodyLarge.copy(fontSize = 22.sp, fontFamily = japaneseFontFamily()), color = ink) }
            ChunkySurface(
                { state.toggleMute() }, Modifier.width(84.dp), 84.dp, RoundedCornerShape(Kaiwa.RadiusButtonLg),
                if (state.muted) ChunkyStyle.Secondary else ChunkyStyle.Primary, enabled = enabled,
                description = if (state.muted) "Unmute microphone" else "Mute microphone",
            ) { ink -> Symbol(if (state.muted) "mic_off" else "mic", size = 30.dp, color = ink) }
            ChunkySurface(
                { state.finish() }, Modifier.width(60.dp), 60.dp, RoundedCornerShape(Kaiwa.RadiusControl),
                ChunkyStyle.Danger, enabled = enabled, edge = 5.dp, description = "Hang up",
            ) { ink -> Symbol("close", size = 24.dp, color = ink) }
        }
    }
}
