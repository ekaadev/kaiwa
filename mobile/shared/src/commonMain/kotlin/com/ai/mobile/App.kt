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
fun IconAction(icon: String, label: String, onClick: () -> Unit) {
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
    PlatformBackHandler(state.studySetupOpen || state.showingCallScreen || state.selected != null || state.destination != "Home") { state.back() }
    ConversationTheme {
        val route = when {
            state.showingCallScreen -> "Call"; state.selected != null -> "Detail"
            else -> state.destination
        }
        val uatSub = route == "Testing" && state.uat != null && state.uatScreen != UatScreen.Overview
        Scaffold(
            containerColor = Kaiwa.Bg,
            contentWindowInsets = if (route == "Call") WindowInsets(0) else ScaffoldDefaults.contentWindowInsets,
            snackbarHost = { if (!state.studySetupOpen) SnackbarHost(snackbar) { AppSnackbar(it) } },
            bottomBar = {
                if (route != "Call" && !uatSub) BottomNavigation(state, route)
            },
        ) { padding ->
            Box(Modifier.fillMaxSize().padding(padding)) {
                key(route) {
                    when (route) {
                        "Home" -> Home(state)
                        "Testing" -> Testing(state)
                        "Session" -> History(state)
                        "Call" -> CallScreen(state)
                        "Detail" -> state.selected?.let { TranscriptScreen(state, it) }
                    }
                }
            }
        }
        if (state.callFailed) AlertDialog(
            onDismissRequest = {},
            shape = RoundedCornerShape(Kaiwa.RadiusButtonLg),
            title = { Text("Call interrupted") },
            text = {
                Text(
                    "The connection was lost. Retry this session, or end it and keep the transcript."
                )
            },
            confirmButton = {
                TextButton({ state.retryFailedCall() }) {
                    Text("Retry session", style = ButtonDefaults.textStyleFor(56.dp))
                }
            },
            dismissButton = { TextButton({ state.endFailedCall() }) { Text("End") } })
        if (state.endConfirmation && !state.callFailed) AlertDialog(
            onDismissRequest = { state.endConfirmation = false },
            shape = RoundedCornerShape(Kaiwa.RadiusButtonLg),
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
            Text(data.visuals.message, modifier = Modifier.weight(1f), style = MaterialTheme.typography.bodySmall)
        }
    }
}

@Composable
private fun BottomNavigation(state: AppState, route: String) {
    val current = if (route == "Detail") "Session" else route
    Column {
        HorizontalDivider(color = Kaiwa.Outline, thickness = 1.5.dp)
        NavigationBar(containerColor = Kaiwa.Card, windowInsets = WindowInsets.navigationBars) {
            listOf(
                "Home" to "home",
                "Testing" to "science",
                "Session" to "history",
            ).forEach { (label, icon) ->
                val source = remember { MutableInteractionSource() }
                NavigationBarItem(
                    selected = current == label,
                    onClick = {
                        state.selected = null
                        if (label == "Testing") state.enterTesting() else state.destination = label
                    },
                    icon = { Symbol(icon, filled = current == label) },
                    label = { Text(label, style = MaterialTheme.typography.labelMedium) },
                    modifier = pressModifier(source),
                    interactionSource = source,
                    colors = NavigationBarItemDefaults.colors(
                        indicatorColor = Kaiwa.PrimaryTint,
                        selectedIconColor = Kaiwa.PrimaryEdge,
                        selectedTextColor = Kaiwa.PrimaryEdge,
                        unselectedIconColor = Kaiwa.InkMuted,
                        unselectedTextColor = Kaiwa.InkMuted,
                    ),
                )
            }
        }
    }
}
