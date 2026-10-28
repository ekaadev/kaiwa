@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)

package com.ai.mobile

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

/** Testing tab: the blind UAT flow from the wireframe. */
@Composable
fun Testing(state: AppState) {
    val sub = state.uat != null && state.uatScreen != UatScreen.Overview
    var exiting by remember { mutableStateOf(false) }
    if (exiting) ExitRunSheet(state) { exiting = false }
    Column(Modifier.fillMaxSize()) {
        if (!sub) KTopBar("Testing") {
            // Before the first trial the chip chooses the run type; afterwards it only labels the run.
            val run = state.uat
            if (run != null) {
                IconAction("logout", "Exit run") { exiting = true }
                KChip(if (run.pilot) "Pilot" else "Main", on = true)
            } else KChip(if (state.uatPilotChoice) "Pilot" else "Main", on = true, onClick = { state.uatPilotChoice = !state.uatPilotChoice })
        }
        Box(Modifier.weight(1f).fillMaxWidth()) {
            when (state.uatScreen) {
                UatScreen.Overview -> UatOverview(state, state.uat)
                UatScreen.Brief -> UatBrief(state)
                UatScreen.Rating -> UatRating(state)
                UatScreen.Marks -> UatMarks(state)
                UatScreen.Preference -> UatPreference(state)
            }
        }
    }
}

@Composable
private fun UatPage(
    title: String,
    state: AppState,
    chip: String?,
    onBack: (() -> Unit)?,
    actions: @Composable ColumnScope.() -> Unit,
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(Modifier.fillMaxSize()) {
        KTopBar(title, onBack = onBack, small = true) { if (chip != null) KChip(chip, on = true) }
        Column(
            Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal = 24.dp, vertical = 4.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
            content = content,
        )
        Column(Modifier.padding(horizontal = 24.dp).padding(top = 8.dp, bottom = 16.dp), verticalArrangement = Arrangement.spacedBy(8.dp), content = actions)
    }
}

@Composable
private fun UatOverview(state: AppState, run: UatRun?) {
    val next = run?.nextTrial()
    val finished = run != null && next == null
    val done = run?.done() ?: 0
    val total = run?.inSession()?.size?.takeIf { it > 0 } ?: 8
    var confirmNew by remember { mutableStateOf(false) }
    if (confirmNew && run != null) androidx.compose.material3.AlertDialog(
        onDismissRequest = { confirmNew = false },
        shape = RoundedCornerShape(Kaiwa.RadiusButtonLg),
        title = { Text("Start a new run?") },
        text = { Text("This device stops using ${run.label}. The run and its results stay on the server.") },
        confirmButton = {
            androidx.compose.material3.TextButton({ confirmNew = false; state.startNewUatRun() }) { Text("Start new run") }
        },
        dismissButton = { androidx.compose.material3.TextButton({ confirmNew = false }) { Text("Cancel") } },
    )
    Column(Modifier.fillMaxSize()) {
        Column(
            Modifier.weight(1f).fillMaxWidth().verticalScroll(rememberScrollState()).padding(horizontal = 24.dp, vertical = 4.dp),
            verticalArrangement = Arrangement.spacedBy(10.dp),
        ) {
            KCard(selected = true) {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(
                        "${run?.label ?: "New run"} · Test session ${run?.test_session ?: 1} of 3",
                        style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f),
                    )
                    Text("$done / $total", style = MaterialTheme.typography.bodySmall, color = Kaiwa.InkMuted)
                }
                Box(Modifier.fillMaxWidth().height(9.dp).background(Kaiwa.Outline, RoundedCornerShape(5.dp))) {
                    Box(Modifier.fillMaxWidth(done / total.toFloat()).height(9.dp).background(Kaiwa.Primary, RoundedCornerShape(5.dp)))
                }
            }
            Text("Scenarios", style = MaterialTheme.typography.bodySmall, color = Kaiwa.InkMuted)
            uatScenarios.forEachIndexed { i, (name, _) ->
                KCard {
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Text("${i + 1} · $name", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                        KChip("${run?.scenarioDone(i) ?: 0} / 2")
                    }
                }
            }
            state.uatError?.let { Text(it, style = MaterialTheme.typography.bodySmall, color = Kaiwa.Danger) }
        }
        Column(Modifier.padding(horizontal = 24.dp).padding(top = 8.dp, bottom = 16.dp)) {
            ChunkyButton(
                when {
                    finished -> "Start new run"
                    run == null || done == 0 -> "Start trials"
                    else -> "Continue trials"
                },
                { if (finished) confirmNew = true else state.startTrials() },
                enabled = !state.busy && !state.uatBusy,
            )
        }
    }
}

@Composable
private fun UatBrief(state: AppState) {
    val trial = state.uat?.trial(state.uatTrial) ?: return
    val (name, brief) = uatScenarios[trial.scenario]
    UatPage(
        "Trial ${trial.positionInSession} of 8", state, "Version ${trial.version}",
        onBack = { state.uatScreen = UatScreen.Overview },
        actions = {
            ChunkyButton(if (state.busy) "Preparing…" else "Start call", state::startTrialCall, enabled = !state.busy && trial.available)
            ChunkyButton("Skip trial", state::skipTrial, style = ChunkyStyle.Secondary, height = 48.dp, enabled = !state.busy && !state.uatBusy && trial.available)
        },
    ) {
        KCard {
            Text("Scenario ${trial.scenario + 1} · $name · Rep ${trial.repetition}", style = MaterialTheme.typography.bodySmall, color = Kaiwa.InkMuted)
            Text(brief, style = MaterialTheme.typography.bodyMedium)
        }
        Box(
            Modifier.fillMaxWidth().height(260.dp).background(Kaiwa.PrimaryTint, RoundedCornerShape(Kaiwa.RadiusStage)),
            contentAlignment = Alignment.Center,
        ) { KaiwaAvatar(Modifier.height(190.dp)) }
        KCard(tone = Kaiwa.StreakBg) {
            Text("Blind trial", style = MaterialTheme.typography.titleMedium, color = Kaiwa.StreakInk)
            Text("A and B are assigned by the server. The detection mode is not shown.", style = MaterialTheme.typography.bodySmall, color = Kaiwa.StreakInk)
        }
    }
}

@Composable
private fun UatRating(state: AppState) {
    val trial = state.uat?.trial(state.uatTrial) ?: return
    val ratings = state.draftRatings
    UatPage(
        "Rate trial ${trial.positionInSession}", state, "Version ${trial.version}",
        onBack = { state.uatScreen = UatScreen.Overview },
        actions = {
            ChunkyButton("Next: mark turns", { state.uatScreen = UatScreen.Marks }, enabled = ratings.all { it > 0 })
            ChunkyButton("Redo this trial", state::redoTrial, style = ChunkyStyle.Secondary, height = 48.dp, enabled = !state.uatBusy)
        },
    ) {
        likertItems.forEachIndexed { item, label ->
            Text(label, style = MaterialTheme.typography.titleMedium)
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                (1..5).forEach { score ->
                    val on = ratings[item] == score
                    Box(
                        Modifier.weight(1f).height(46.dp)
                            .background(if (on) Kaiwa.Primary else Kaiwa.Card, RoundedCornerShape(Kaiwa.RadiusChip))
                            .border(BorderStroke(2.dp, if (on) Kaiwa.PrimaryEdge else Kaiwa.OutlineStrong), RoundedCornerShape(Kaiwa.RadiusChip))
                            .clickable(role = Role.RadioButton) { state.rate(item, score) },
                        contentAlignment = Alignment.Center,
                    ) {
                        Text("$score", style = MaterialTheme.typography.titleMedium.copy(fontWeight = androidx.compose.ui.text.font.FontWeight.ExtraBold), color = if (on) Color.White else Kaiwa.Ink)
                    }
                }
            }
        }
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            Text("1 Strongly disagree", style = MaterialTheme.typography.bodySmall, color = Kaiwa.InkMuted)
            Text("5 Strongly agree", style = MaterialTheme.typography.bodySmall, color = Kaiwa.InkMuted)
        }
        Text("Item wording is a placeholder until the final instrument is set.", style = MaterialTheme.typography.bodySmall, color = Kaiwa.InkMuted)
    }
}

@Composable
private fun UatMarks(state: AppState) {
    val trial = state.uat?.trial(state.uatTrial) ?: return
    val conversation = state.conversations.firstOrNull { it.id == trial.call_id }
    val turns = conversation?.turns().orEmpty()
    UatPage(
        "Mark turns", state, "Version ${trial.version}",
        onBack = { state.uatScreen = UatScreen.Rating },
        actions = { ChunkyButton(if (state.uatBusy) "Saving…" else "Save trial", state::saveTrial, enabled = !state.uatBusy) },
    ) {
        Text("Choose how each change of turn felt.", style = MaterialTheme.typography.bodySmall, color = Kaiwa.InkMuted)
        if (turns.isEmpty()) Text("The transcript is not available on this device.", style = MaterialTheme.typography.bodyMedium)
        turns.forEachIndexed { i, turn ->
            val mine = turn.role == "user"
            Column(Modifier.fillMaxWidth(), horizontalAlignment = if (mine) Alignment.End else Alignment.Start) {
                Text((if (mine) "YOU" else "KAIWA"), style = MaterialTheme.typography.labelMedium, color = Kaiwa.InkMuted)
                Text(
                    turn.text,
                    Modifier.background(if (mine) Kaiwa.PrimaryTint else Kaiwa.Card, RoundedCornerShape(Kaiwa.RadiusControl))
                        .border(BorderStroke(1.5.dp, if (mine) Kaiwa.PrimaryTint else Kaiwa.Outline), RoundedCornerShape(Kaiwa.RadiusControl))
                        .padding(horizontal = 14.dp, vertical = 8.dp),
                    style = MaterialTheme.typography.bodyMedium.copy(fontFamily = japaneseFontFamily(), lineHeight = 24.sp),
                )
            }
            // A turn change is a learner turn followed by the tutor's reply.
            if (mine && turns.getOrNull(i + 1)?.role == "assistant") Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                turnLabels.forEach { label ->
                    KChip(label, on = state.draftLabels[turn.sequence] == label, onClick = { state.markTurn(turn.sequence, label) })
                }
            }
        }
    }
}

@Composable
private fun UatPreference(state: AppState) {
    val scenario = state.uatPair
    val run = state.uat ?: return
    val session = run.trial(state.uatTrial)?.test_session ?: run.test_session
    var choice by remember(scenario) { mutableStateOf(run.preferences.firstOrNull { it.test_session == session && it.scenario == scenario }?.choice) }
    val pair = run.inSession(session).filter { it.scenario == scenario }.sortedBy { it.version }
    UatPage(
        "Which felt better?", state, null,
        onBack = null,
        actions = { ChunkyButton("Confirm choice", { choice?.let(state::choosePreference) }, enabled = choice != null && !state.uatBusy) },
    ) {
        Text("${uatScenarios[scenario].first} · Rep $session", style = MaterialTheme.typography.bodySmall, color = Kaiwa.InkMuted)
        pair.forEach { t ->
            val r = t.ratings ?: List(4) { 0 }
            KCard(selected = choice == t.version, onClick = { choice = t.version }) {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Text("Version ${t.version}", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
                    if (choice == t.version) KChip("Preferred", on = true)
                }
                Text(
                    if (t.status == "skipped") "Skipped" else "Natural ${r[0]} · Flow ${r[3]}",
                    style = MaterialTheme.typography.bodySmall, color = Kaiwa.InkMuted,
                )
            }
        }
        KCard(selected = choice == "None", onClick = { choice = "None" }) {
            Text("No preference", style = MaterialTheme.typography.titleMedium)
        }
    }
}

/** Bottom drawer that asks before the expert leaves a run (pilot or main). */
@Composable
private fun ExitRunSheet(state: AppState, onDismiss: () -> Unit) {
    val run = state.uat ?: return
    val sheet = androidx.compose.material3.rememberModalBottomSheetState(skipPartiallyExpanded = true)
    androidx.compose.material3.ModalBottomSheet(
        onDismissRequest = onDismiss,
        sheetState = sheet,
        shape = RoundedCornerShape(topStart = Kaiwa.RadiusButtonLg, topEnd = Kaiwa.RadiusButtonLg),
        containerColor = Kaiwa.Bg,
        contentColor = Kaiwa.Ink,
    ) {
        Column(
            Modifier.fillMaxWidth().padding(horizontal = 24.dp).padding(bottom = 24.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp),
        ) {
            KCard {
                Text("Exit ${run.label}?", style = MaterialTheme.typography.titleMedium)
                Text(
                    "This device stops using the ${if (run.pilot) "pilot" else "main"} run. Results so far stay on the " +
                        "server and the run is marked as left; you cannot continue it.",
                    style = MaterialTheme.typography.bodySmall, color = Kaiwa.InkMuted,
                )
            }
            ChunkyButton(
                if (state.uatBusy) "Leaving…" else "Exit run",
                { state.exitUatRun(); onDismiss() },
                style = ChunkyStyle.Danger,
                enabled = !state.uatBusy && !state.busy,
            )
            androidx.compose.material3.TextButton(onDismiss, Modifier.fillMaxWidth()) {
                Text("NOT YET", style = MaterialTheme.typography.titleMedium, color = Kaiwa.Primary)
            }
        }
    }
}
