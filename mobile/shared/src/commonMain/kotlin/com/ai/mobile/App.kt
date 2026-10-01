@file:OptIn(
    androidx.compose.material3.ExperimentalMaterial3Api::class,
    androidx.compose.material3.ExperimentalMaterial3ExpressiveApi::class
)

package com.ai.mobile

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.pager.HorizontalPager
import androidx.compose.foundation.pager.rememberPagerState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.scale
import androidx.compose.ui.platform.LocalAccessibilityManager
import androidx.compose.ui.semantics.LiveRegionMode
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.liveRegion
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.coroutines.delay

@Composable
expect fun PlatformBackHandler(enabled: Boolean, onBack: () -> Unit)

private val cardWidth = 380.dp
private val cardHeight = 400.dp
private val actionWidth = 182.dp
private val actionSpacing = 48.dp

private object MicrophonePermissionSnackbar : SnackbarVisuals {
    override val message = "Please enable microphone permission to make calls."
    override val actionLabel = "Settings"
    override val withDismissAction = true

    // The shared timer below supplies the custom eight-second timeout.
    override val duration = SnackbarDuration.Indefinite
}

@Composable
private fun pressModifier(source: MutableInteractionSource): Modifier {
    val pressed by source.collectIsPressedAsState()
    val scale by animateFloatAsState(if (pressed) .97f else 1f, tween(120))
    return Modifier.scale(scale)
}

@Composable
private fun Action(
    label: String,
    icon: String? = null,
    modifier: Modifier = Modifier,
    enabled: Boolean = true,
    tonal: Boolean = true,
    onClick: () -> Unit
) {
    val source = remember { MutableInteractionSource() }
    val content: @Composable RowScope.() -> Unit = {
        if (icon != null) {
            Symbol(icon, size = ButtonDefaults.iconSizeFor(56.dp)); Spacer(Modifier.width(8.dp))
        }; Text(label, style = ButtonDefaults.textStyleFor(56.dp))
    }
    if (tonal) FilledTonalButton(
        onClick,
        modifier.then(pressModifier(source)).heightIn(min = 56.dp),
        enabled = enabled,
        shape = RoundedCornerShape(50),
        contentPadding = ButtonDefaults.contentPaddingFor(56.dp),
        interactionSource = source,
        content = content
    )
    else Button(
        onClick,
        modifier.then(pressModifier(source)).heightIn(min = 56.dp),
        enabled = enabled,
        shape = RoundedCornerShape(50),
        contentPadding = ButtonDefaults.contentPaddingFor(56.dp),
        interactionSource = source,
        content = content
    )
}

@Composable
private fun IconAction(icon: String, label: String, onClick: () -> Unit) {
    val source = remember { MutableInteractionSource() }
    IconButton(
        onClick,
        Modifier.size(56.dp).then(pressModifier(source)).semantics { contentDescription = label },
        interactionSource = source
    ) { Symbol(icon, label) }
}

@Composable
fun App() {
    val services = platformServices()
    val scope = rememberCoroutineScope()
    val state = remember(services) { AppState(services, scope) }
    val snackbar = remember { SnackbarHostState() }
    val accessibilityManager = LocalAccessibilityManager.current
    LaunchedEffect(snackbar.currentSnackbarData, accessibilityManager) {
        val data = snackbar.currentSnackbarData ?: return@LaunchedEffect
        if (data.visuals === MicrophonePermissionSnackbar) {
            val timeout = accessibilityManager?.calculateRecommendedTimeoutMillis(
                originalTimeoutMillis = 8_000L,
                containsIcons = true,
                containsText = true,
                containsControls = true,
            ) ?: 8_000L
            delay(timeout)
            data.dismiss()
        }
    }
    DisposableEffect(state) {
        AppLifecycle.onBackground = state::background; onDispose {
        AppLifecycle.onBackground = null; state.close()
    }
    }
    LaunchedEffect(state.message, state.microphonePermissionNotice) {
        if (state.microphonePermissionNotice) {
            val result = snackbar.showSnackbar(MicrophonePermissionSnackbar)
            state.microphonePermissionNotice = false
            if (result == SnackbarResult.ActionPerformed) state.services.calls.openPermissionSettings()
        } else state.message?.let { message ->
            snackbar.showSnackbar(message)
            if (state.message == message) state.message = null
        }
    }
    PlatformBackHandler(state.studySetupOpen || state.showingCallScreen || state.settingsOpen || state.selected != null || state.destination != "Home") { state.back() }
    ConversationTheme {
        val route = when {
            state.showingCallScreen -> "Call"; state.settingsOpen -> "Settings"; state.selected != null -> "Detail"; else -> state.destination
        }
        Scaffold(
            containerColor = MaterialTheme.colorScheme.surface,
            topBar = {
                if (route in listOf("Home", "Testing", "Session", "Settings")) CenterAlignedTopAppBar(
                    title = {
                        Text(
                            when (route) {
                                "Home" -> "Practice Call"; "Testing" -> "Testing Call"; else -> route
                            }, style = MaterialTheme.typography.headlineSmall.copy(fontSize = 28.sp, lineHeight = 36.sp)
                        )
                    },
                    navigationIcon = { if (route == "Settings") IconAction("back", "Back", state::back) },
                    actions = {
                        when (route) {
                            "Session" -> IconAction("settings", "Settings", { state.settingsOpen = true })
                            "Testing" -> IconAction("refresh", "Refresh sessions", state::refresh)
                        }
                    },
                    colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.surface),
                )
            },
            snackbarHost = { if (!state.studySetupOpen) SnackbarHost(snackbar) { AppSnackbar(it) } },
            bottomBar = {
                if (!state.showingCallScreen && !state.settingsOpen && state.selected == null) BottomNavigation(
                    state
                )
            },
        ) { padding ->
            Box(Modifier.fillMaxSize().padding(padding)) {
                key(route) {
                    when (route) {
                        "Home" -> Home(state)
                        "Testing" -> Testing(state)
                        "Session" -> History(state)
                        "Call" -> CallScreen(state)
                        "Settings" -> SettingsScreen(state)
                        "Detail" -> state.selected?.let { TranscriptScreen(state, it) }
                    }
                }
            }
        }
        if (state.studySetupOpen) StudyConsentSheet(state, snackbar)
        if (state.endConfirmation) AlertDialog(
            onDismissRequest = { state.endConfirmation = false },
            shape = RoundedCornerShape(40.dp),
            title = { Text("End this call?") },
            text = { Text("Your conversation transcript will be saved on this device.") },
            confirmButton = {
                TextButton({ state.finish() }) {
                    Text(
                        "Hang Up",
                        style = ButtonDefaults.textStyleFor(56.dp)
                    )
                }
            },
            dismissButton = { TextButton({ state.endConfirmation = false }) { Text("Keep talking") } })
    }
}

@Composable
private fun AppSnackbar(data: SnackbarData) {
    val colors = MaterialTheme.colorScheme
    val actionSource = remember { MutableInteractionSource() }
    val dismissSource = remember { MutableInteractionSource() }
    Snackbar(
        modifier = Modifier.padding(horizontal = 16.dp, vertical = 8.dp),
        shape = RoundedCornerShape(8.dp),
        containerColor = colors.inverseSurface,
        contentColor = colors.inverseOnSurface,
        action = data.visuals.actionLabel?.let { label ->
            {
                TextButton(
                    onClick = data::performAction,
                    modifier = pressModifier(actionSource),
                    shape = RoundedCornerShape(50),
                    colors = ButtonDefaults.textButtonColors(contentColor = colors.inversePrimary),
                    interactionSource = actionSource,
                ) { Text(label) }
            }
        },
        dismissAction = if (data.visuals.withDismissAction) {
            {
                IconButton(
                    onClick = data::dismiss,
                    modifier = Modifier.size(48.dp).then(pressModifier(dismissSource)),
                    interactionSource = dismissSource,
                ) { Symbol("close", "Dismiss", color = colors.inverseOnSurface) }
            }
        } else null,
    ) {
        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            if (data.visuals.actionLabel == "Settings") Symbol("mic_off")
            Text(data.visuals.message, modifier = Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium)
        }
    }
}

@Composable
private fun BottomNavigation(state: AppState) {
    NavigationBar(
        containerColor = MaterialTheme.colorScheme.surfaceContainer,
        windowInsets = WindowInsets.navigationBars
    ) {
        listOf("Home" to "home", "Testing" to "graphic_eq", "Session" to "history").forEach { (label, icon) ->
            val source = remember { MutableInteractionSource() }
            NavigationBarItem(
                selected = state.destination == label,
                onClick = { if (label == "Testing") state.enterTesting() else state.destination = label },
                icon = { Symbol(icon, filled = state.destination == label) },
                label = { Text(label, style = MaterialTheme.typography.labelMedium) },
                modifier = pressModifier(source),
                interactionSource = source,
                colors = NavigationBarItemDefaults.colors(indicatorColor = MaterialTheme.colorScheme.secondaryContainer)
            )
        }
    }
}

@Composable
private fun Header(
    title: String,
    state: AppState,
    back: Boolean = false,
    trailing: @Composable () -> Unit = {
        IconAction(
            "settings",
            "Settings",
            { state.settingsOpen = true })
    }
) {
    Row(Modifier.fillMaxWidth().padding(horizontal = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        if (back) IconAction("back", "Back", state::back) else Spacer(Modifier.width(56.dp))
        Text(
            title,
            modifier = Modifier.weight(1f),
            style = MaterialTheme.typography.headlineSmall.copy(fontSize = 28.sp, lineHeight = 36.sp),
            textAlign = TextAlign.Center
        )
        trailing()
    }
}

@Composable
private fun Home(state: AppState) {
    BoxWithConstraints(Modifier.fillMaxSize()) {
        val viewport = maxHeight
        Column(
            Modifier.fillMaxWidth().verticalScroll(rememberScrollState())
                .heightIn(min = viewport).padding(horizontal = 16.dp, vertical = 16.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Box(
                Modifier.widthIn(max = cardWidth).fillMaxWidth().height(cardHeight)
                    .background(MaterialTheme.colorScheme.surfaceContainerHigh, RoundedCornerShape(28.dp))
            )
            Spacer(Modifier.height(actionSpacing))
            Action(
                if (state.busy) "Preparing…" else "Start to Call",
                "graphic_eq",
                Modifier.width(actionWidth),
                !state.busy,
                onClick = state::start
            )
        }
    }
}

@Composable
private fun Testing(state: AppState) {
    val pager = rememberPagerState(initialPage = (state.selectedOrdinal - 1).coerceIn(0, 1)) { 2 }
    LaunchedEffect(pager.settledPage) { state.selectedOrdinal = pager.settledPage + 1 }
    BoxWithConstraints(Modifier.fillMaxSize()) {
        val viewport = maxHeight
        Column(
            Modifier.fillMaxWidth().verticalScroll(rememberScrollState())
                .heightIn(min = viewport).padding(horizontal = 16.dp, vertical = 16.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            HorizontalPager(
                state = pager,
                modifier = Modifier.widthIn(max = cardWidth).fillMaxWidth().height(cardHeight),
                pageSpacing = 8.dp,
                overscrollEffect = null,
            ) { index ->
                val session = state.participant?.sessions?.find { it.ordinal == index + 1 }
                val complete = session?.status == "completed"
                Surface(
                    Modifier.fillMaxSize(),
                    shape = RoundedCornerShape(16.dp),
                    color = if (index == 0) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.tertiaryContainer
                ) {
                    Column(
                        Modifier.verticalScroll(rememberScrollState()).heightIn(min = cardHeight).padding(24.dp),
                        verticalArrangement = Arrangement.spacedBy(16.dp)
                    ) {
                        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                            Text("${index + 1} / 2", style = MaterialTheme.typography.labelLarge)
                            Spacer(Modifier.weight(1f))
                            Symbol(
                                if (complete) "check" else if (session?.available == true) "graphic_eq" else "lock",
                                size = 32.dp
                            )
                        }
                        Spacer(Modifier.weight(1f))
                        Symbol("school", size = 72.dp)
                        Text(
                            when {
                                complete -> "Session complete"; session?.available == true -> "Ready when you are"; state.participant == null -> if (state.token.isBlank()) "Join the conversation study" else "Your sessions are unavailable"; state.participant?.sessions?.firstOrNull()?.status != "completed" && index == 1 -> "Available after Session 1"; else -> "Session processing"
                            }, style = MaterialTheme.typography.titleLarge
                        )
                        Text(
                            when {
                                complete -> "Thank you for taking part."; state.participant == null -> if (state.token.isBlank()) "Read the participation agreement and allow microphone access to set up your two sessions." else "Check your connection, then try loading your sessions again."; session?.available == true -> "Choose your own topic. Speak for at least two minutes, then end the call normally."; state.participant?.sessions?.firstOrNull()?.status != "completed" && index == 1 -> "Your first session must finish and its evidence must be saved before you continue."; else -> "A call is active or its evidence is being saved. Refresh to check availability."
                            }, style = MaterialTheme.typography.bodyMedium
                        )
                        Text("Session ${index + 1}", style = MaterialTheme.typography.headlineMedium)
                    }
                }
            }
            Box(Modifier.height(actionSpacing), contentAlignment = Alignment.Center) {
                Text(
                    "${pager.settledPage + 1} of 2",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            if (state.participant == null) Action(
                if (state.token.isBlank()) "Get started" else "Try again",
                "graphic_eq",
                Modifier.width(actionWidth),
                enabled = state.settingsReady && !state.busy,
                onClick = { if (state.token.isBlank()) state.beginStudySetup() else state.refresh() })
            else Action(
                if (state.busy) "Preparing…" else "Start to Call",
                "graphic_eq",
                Modifier.width(actionWidth),
                !state.busy && state.canStartStudy(state.selectedOrdinal),
                onClick = state::start
            )
            if (state.participant?.sessions?.all { it.status == "completed" } == true) Text(
                "Testing complete. Thank you!",
                Modifier.padding(16.dp),
                style = MaterialTheme.typography.bodyLarge
            )
        }
    }
}

@Composable
private fun CallScreen(state: AppState) {
    val colors = MaterialTheme.colorScheme
    val muted = state.muted
    val controlsEnabled = state.phase != "Ending"
    val hang = remember { MutableInteractionSource() }
    val mic = remember { MutableInteractionSource() }

    Column(Modifier.fillMaxSize().padding(16.dp)) {
        Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
            Surface(shape = CircleShape, color = colors.primaryContainer) {
                Box(Modifier.size(136.dp), contentAlignment = Alignment.Center) {
                    Symbol(
                        if (muted) "mic_off" else "graphic_eq",
                        size = 80.dp,
                        color = colors.onPrimaryContainer,
                    )
                }
            }
        }
        // End-call stays centered above the bottom-right microphone control.
        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center) {
            FilledIconButton(
                onClick = { state.finish() },
                modifier = Modifier.size(56.dp).then(pressModifier(hang))
                    .semantics { contentDescription = "Hang up" },
                enabled = controlsEnabled,
                shape = CircleShape,
                colors = IconButtonDefaults.filledIconButtonColors(
                    containerColor = colors.error,
                    contentColor = colors.onError,
                ),
                interactionSource = hang,
            ) { Symbol("call_end", size = 28.dp) }
        }
        Spacer(Modifier.height(16.dp))
        Row(
            Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.End,
            verticalAlignment = Alignment.CenterVertically,
        ) {
            OutlinedIconToggleButton(
                checked = muted,
                onCheckedChange = { state.toggleMute() },
                modifier = Modifier.size(56.dp).then(pressModifier(mic))
                    .semantics { contentDescription = if (muted) "Unmute microphone" else "Mute microphone" },
                enabled = controlsEnabled,
                shape = CircleShape,
                border = BorderStroke(if (muted) 2.dp else 1.dp, if (muted) colors.primary else colors.outline),
                colors = IconButtonDefaults.outlinedIconToggleButtonColors(
                    containerColor = colors.onPrimary,
                    contentColor = colors.onSurface,
                    checkedContainerColor = colors.onPrimary,
                    checkedContentColor = colors.primary,
                ),
                interactionSource = mic,
            ) { Symbol(if (muted) "mic_off" else "mic", size = 28.dp) }
        }
    }
}

@Composable
private fun History(state: AppState) {
    var query by remember { mutableStateOf("") }
    Column(Modifier.fillMaxSize()) {
        OutlinedTextField(
            query,
            { query = it },
            Modifier.fillMaxWidth().padding(16.dp),
            placeholder = { Text("Search conversations") },
            leadingIcon = { Symbol("search") },
            trailingIcon = { if (query.isNotEmpty()) IconAction("close", "Clear search", { query = "" }) },
            shape = RoundedCornerShape(50),
            singleLine = true
        )
        val shown = state.conversations.filter { it.matches(query) }
        if (shown.isEmpty()) Column(
            Modifier.fillMaxSize().padding(32.dp),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Symbol("forum", size = 64.dp, color = MaterialTheme.colorScheme.primary)
            Text(
                if (query.isBlank()) "Your conversations live here" else "No conversations found",
                Modifier.padding(top = 20.dp),
                style = MaterialTheme.typography.titleLarge,
                textAlign = TextAlign.Center
            )
            Text(
                if (query.isBlank()) "After a call, come back to read your transcript." else "Try another word or clear your search.",
                Modifier.padding(top = 12.dp),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center
            )
        } else LazyColumn(contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            items(shown, key = { it.id }) { conversation ->
                val source = remember { MutableInteractionSource() }
                Card(
                    onClick = { state.selected = conversation },
                    modifier = Modifier.fillMaxWidth().then(pressModifier(source)),
                    shape = RoundedCornerShape(32.dp),
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceContainerLow),
                    interactionSource = source
                ) {
                    Row(Modifier.padding(20.dp), verticalAlignment = Alignment.CenterVertically) {
                        Symbol(
                            if (conversation.ordinal == null) "forum" else "school",
                            color = MaterialTheme.colorScheme.primary
                        )
                        Column(
                            Modifier.weight(1f).padding(horizontal = 16.dp),
                            verticalArrangement = Arrangement.spacedBy(4.dp)
                        ) {
                            Text(conversation.title(), style = MaterialTheme.typography.titleMedium)
                            Text(
                                formatDate(conversation.started),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                            Text(
                                "${durationLabel(conversation.duration)} · ${conversation.outcome}",
                                style = MaterialTheme.typography.labelMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                        Symbol("arrow")
                    }
                }
            }
        }
    }
}

@Composable
private fun TurnCard(turn: Turn) {
    Surface(
        color = if (turn.role == "user") MaterialTheme.colorScheme.surfaceContainerLow else MaterialTheme.colorScheme.primaryContainer,
        shape = RoundedCornerShape(24.dp),
        modifier = Modifier.fillMaxWidth()
    ) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text(
                if (turn.role == "user") "You" else "AI partner",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            SelectionContainer { Text(turn.text, style = MaterialTheme.typography.bodyLarge) }
        }
    }
}

@Composable
private fun TranscriptScreen(state: AppState, conversation: Conversation) {
    var deleting by remember { mutableStateOf(false) }
    LaunchedEffect(conversation.id) { state.recoverTranscript(conversation, automatic = true) }
    Column(Modifier.fillMaxSize().padding(top = 16.dp)) {
        Header(
            "Transcript",
            state,
            true,
            trailing = { IconAction("delete", "Delete conversation", { deleting = true }) })
        LazyColumn(contentPadding = PaddingValues(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            item {
                Text(conversation.title(), style = MaterialTheme.typography.titleLarge); Text(
                "${
                    formatDate(
                        conversation.started
                    )
                } · ${durationLabel(conversation.duration)} · ${conversation.outcome}",
                Modifier.padding(top = 8.dp),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            }
            item {
                Action(
                    if (conversation.ordinal == null) "Call again" else "Return to Testing",
                    "graphic_eq",
                    onClick = { state.retryConversation(conversation) })
            }
            if (!conversation.transcriptFinal) item {
                Text(
                    "This transcript may be incomplete because the call or transcript connection was interrupted.",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                ); Action(
                "Retry transcript",
                "refresh",
                Modifier.padding(top = 12.dp),
                onClick = { state.recoverTranscript(conversation) })
            }
            if (conversation.turns().isEmpty()) item {
                Text(
                    "No completed speech turns were received for this call.",
                    Modifier.padding(vertical = 32.dp),
                    style = MaterialTheme.typography.bodyLarge
                )
            }
            items(conversation.turns(), key = { it.sequence }) { TurnCard(it) }
        }
    }
    if (deleting) AlertDialog(
        onDismissRequest = { deleting = false },
        shape = RoundedCornerShape(40.dp),
        title = { Text("Delete this conversation?") },
        text = { Text("This permanently removes the transcript from this device. Research evidence on the server is managed by the researcher.") },
        confirmButton = { TextButton({ state.delete(conversation); deleting = false }) { Text("Delete") } },
        dismissButton = { TextButton({ deleting = false }) { Text("Cancel") } })
}

@Composable
private fun SettingsScreen(state: AppState) {
    Column(
        Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Text("Microphone", style = MaterialTheme.typography.titleLarge)
        Text(
            "Microphone access lets you speak during a call. You can manage access in your device settings.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Action(
            "Microphone settings",
            "mic",
            Modifier.fillMaxWidth(),
            onClick = state.services.calls::openPermissionSettings
        )
        Text("Testing participation", style = MaterialTheme.typography.titleLarge)
        Text(
            if (state.token.isBlank()) "Join from Testing after reading the participation agreement. Your access will be saved automatically on this device."
            else "Your study access is saved on this device. Return to Testing to continue your sessions.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        Text("Your conversations", style = MaterialTheme.typography.titleLarge)
        Text(
            "Saved transcripts stay on this device. You can read and delete them from Session. Testing also stores recordings and transcripts on the research server.",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun StudyConsentSheet(state: AppState, snackbar: SnackbarHostState) {
    val sheet = rememberBottomSheetState(
        initialValue = SheetValue.Hidden,
        enabledValues = setOf(SheetValue.Hidden, SheetValue.Expanded),
        confirmValueChange = { it != SheetValue.Hidden || !state.joiningStudy },
    )
    ModalBottomSheet(
        onDismissRequest = state::declineStudy,
        sheetState = sheet,
        shape = RoundedCornerShape(topStart = 40.dp, topEnd = 40.dp),
        containerColor = MaterialTheme.colorScheme.surfaceContainerLow,
        contentColor = MaterialTheme.colorScheme.onSurface,
    ) {
        Column(Modifier.fillMaxWidth()) {
            Box(Modifier.weight(1f, fill = false).fillMaxWidth()) {
                Column(
                    Modifier.fillMaxWidth().verticalScroll(rememberScrollState())
                        .padding(horizontal = 24.dp)
                        .padding(bottom = 16.dp),
                    verticalArrangement = Arrangement.spacedBy(16.dp),
                ) {
                    Surface(shape = RoundedCornerShape(50), color = MaterialTheme.colorScheme.primaryContainer) {
                        Box(Modifier.size(72.dp), contentAlignment = Alignment.Center) {
                            Symbol("school", size = 40.dp, color = MaterialTheme.colorScheme.onPrimaryContainer)
                        }
                    }
                    Text(
                        "Testing participation",
                        style = MaterialTheme.typography.labelLarge,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    Text("Before you join", style = MaterialTheme.typography.headlineMedium)
                    Text(
                        "You are invited to take part in a study with two conversation sessions. Speak for at least two minutes in each session, then end the call normally.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Text(
                        "Testing records your audio and transcripts and stores them on the research server. Saved transcripts also stay on this device.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Text(
                        "Taking part is your choice. You can decline or stop a call at any time. By selecting Agree and continue, you agree to take part and to this recording and use of your conversation for the study.",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    state.studySetupError?.let { error ->
                        Surface(shape = RoundedCornerShape(24.dp), color = MaterialTheme.colorScheme.errorContainer) {
                            Text(
                                error,
                                Modifier.fillMaxWidth().padding(16.dp).semantics { liveRegion = LiveRegionMode.Polite },
                                style = MaterialTheme.typography.bodyMedium,
                                color = MaterialTheme.colorScheme.onErrorContainer
                            )
                        }
                    }
                    if (state.joiningStudy) {
                        LinearProgressIndicator(Modifier.fillMaxWidth())
                        Text(
                            if (state.studyJoinPhase == StudyJoinPhase.Microphone) "Waiting for microphone permission…" else "Setting up your sessions…",
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.semantics { liveRegion = LiveRegionMode.Polite },
                        )
                    }
                }
                // Overlay within the modal window: floats above the actions without adding height.
                SnackbarHost(snackbar, Modifier.align(Alignment.BottomCenter)) { AppSnackbar(it) }
            }
            Column(
                Modifier.fillMaxWidth().padding(horizontal = 24.dp).padding(bottom = 24.dp),
                verticalArrangement = Arrangement.spacedBy(16.dp),
            ) {
                Action(
                    "Agree and continue",
                    modifier = Modifier.fillMaxWidth(),
                    enabled = !state.joiningStudy && state.settingsReady,
                    tonal = false,
                    onClick = state::agreeToStudy
                )
                val decline = remember { MutableInteractionSource() }
                OutlinedButton(
                    onClick = state::declineStudy,
                    modifier = Modifier.fillMaxWidth().heightIn(min = 56.dp).then(pressModifier(decline)),
                    enabled = !state.joiningStudy,
                    shape = RoundedCornerShape(50),
                    contentPadding = ButtonDefaults.contentPaddingFor(56.dp),
                    interactionSource = decline,
                ) { Text("Decline", style = ButtonDefaults.textStyleFor(56.dp)) }
            }
        }
    }
}
