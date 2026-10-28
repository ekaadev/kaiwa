package com.ai.mobile

import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateDpAsState
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.collectIsPressedAsState
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import mobile.shared.generated.resources.Res
import mobile.shared.generated.resources.kaiwa_avatar
import org.jetbrains.compose.resources.painterResource

enum class ChunkyStyle { Primary, Secondary, Danger, Tint }

/** Raised button: a bottom edge that collapses when pressed. */
@Composable
fun ChunkySurface(
    onClick: () -> Unit,
    modifier: Modifier,
    height: Dp,
    shape: Shape,
    style: ChunkyStyle,
    enabled: Boolean = true,
    edge: Dp = when (style) {
        ChunkyStyle.Primary -> 6.dp; ChunkyStyle.Danger -> 5.dp; else -> 4.dp
    },
    description: String? = null,
    content: @Composable BoxScope.(Color) -> Unit,
) {
    val source = remember { MutableInteractionSource() }
    val pressed by source.collectIsPressedAsState()
    val drop by animateDpAsState(if (pressed && enabled) edge else 0.dp, tween(80))
    val (face, edgeColor, ink) = when {
        !enabled -> Triple(Kaiwa.Outline, Kaiwa.Outline, Kaiwa.InkMuted)
        style == ChunkyStyle.Primary -> Triple(Kaiwa.Primary, Kaiwa.PrimaryEdge, Color.White)
        style == ChunkyStyle.Danger -> Triple(Kaiwa.Danger, Kaiwa.DangerEdge, Color.White)
        style == ChunkyStyle.Tint -> Triple(Kaiwa.PrimaryTint, Kaiwa.Primary, Kaiwa.PrimaryEdge)
        else -> Triple(Kaiwa.Card, Kaiwa.OutlineStrong, Kaiwa.Ink)
    }
    val outline = when {
        !enabled -> null
        style == ChunkyStyle.Secondary -> BorderStroke(2.dp, Kaiwa.OutlineStrong)
        style == ChunkyStyle.Tint -> BorderStroke(2.dp, Kaiwa.Primary)
        else -> null
    }
    Box(
        modifier.height(height + edge)
            .clickable(source, null, enabled, role = Role.Button, onClick = onClick)
            .then(if (description != null) Modifier.semantics { contentDescription = description } else Modifier)
    ) {
        Box(Modifier.align(Alignment.BottomCenter).fillMaxWidth().height(height).background(edgeColor, shape))
        Box(
            Modifier.offset(y = drop).fillMaxWidth().height(height).background(face, shape)
                .then(if (outline != null) Modifier.border(outline, shape) else Modifier),
            contentAlignment = Alignment.Center,
        ) { content(ink) }
    }
}

@Composable
fun ChunkyButton(
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    style: ChunkyStyle = ChunkyStyle.Primary,
    enabled: Boolean = true,
    icon: String? = null,
    height: Dp = 58.dp,
) = ChunkySurface(onClick, modifier.fillMaxWidth(), height, RoundedCornerShape(Kaiwa.RadiusButton), style, enabled) { ink ->
    Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        if (icon != null) Symbol(icon, color = ink)
        Text(
            label.uppercase(),
            style = MaterialTheme.typography.titleMedium.copy(
                fontSize = 17.sp, letterSpacing = 1.sp, fontWeight = androidx.compose.ui.text.font.FontWeight.ExtraBold
            ),
            color = ink,
            textAlign = TextAlign.Center,
        )
    }
}

@Composable
fun KCard(
    modifier: Modifier = Modifier,
    selected: Boolean = false,
    tone: Color? = null,
    onClick: (() -> Unit)? = null,
    content: @Composable ColumnScope.() -> Unit,
) {
    val shape = RoundedCornerShape(Kaiwa.RadiusCard)
    val bg = tone ?: if (selected) Kaiwa.PrimaryTint else Kaiwa.Card
    val line = if (tone != null) tone else if (selected) Kaiwa.Primary else Kaiwa.Outline
    Column(
        modifier.fillMaxWidth().background(bg, shape).border(BorderStroke(1.5.dp, line), shape)
            .then(if (onClick != null) Modifier.clickable(role = Role.Button, onClick = onClick) else Modifier)
            .padding(horizontal = 16.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
        content = content,
    )
}

@Composable
fun KChip(
    text: String,
    modifier: Modifier = Modifier,
    on: Boolean = false,
    streak: Boolean = false,
    leading: (@Composable () -> Unit)? = null,
    onClick: (() -> Unit)? = null,
) {
    val shape = CircleShape
    val bg = if (streak) Kaiwa.StreakBg else if (on) Kaiwa.PrimaryTint else Kaiwa.Card
    val ink = if (streak) Kaiwa.StreakInk else if (on) Kaiwa.PrimaryEdge else Kaiwa.Ink
    val line = if (streak) Kaiwa.StreakBg else if (on) Kaiwa.Primary else Kaiwa.Outline
    Row(
        modifier.background(bg, shape).border(BorderStroke(1.5.dp, line), shape)
            .then(if (onClick != null) Modifier.clickable(role = Role.Button, onClick = onClick) else Modifier)
            .padding(horizontal = 12.dp, vertical = 5.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        leading?.invoke()
        Text(text, style = MaterialTheme.typography.titleMedium.copy(fontSize = 14.sp, lineHeight = 20.sp), color = ink)
    }
}

@Composable
fun StatusBadge(text: String, modifier: Modifier = Modifier, active: Boolean = true) {
    Row(
        modifier.background(Kaiwa.Card, CircleShape).padding(horizontal = 14.dp, vertical = 7.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        Box(Modifier.size(8.dp).background(if (active) Kaiwa.Primary else Kaiwa.InkMuted, CircleShape))
        Text(
            text,
            style = MaterialTheme.typography.titleMedium.copy(fontSize = 14.sp, lineHeight = 20.sp),
            color = Kaiwa.PrimaryEdge,
        )
    }
}

@Composable
fun KTopBar(
    title: String,
    modifier: Modifier = Modifier,
    onBack: (() -> Unit)? = null,
    small: Boolean = false,
    trailing: @Composable RowScope.() -> Unit = {},
) {
    Row(
        modifier.fillMaxWidth().heightIn(min = 64.dp).padding(start = if (onBack != null) 14.dp else 24.dp, end = 24.dp, top = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        if (onBack != null) Box(
            Modifier.size(48.dp).clickable(role = Role.Button, onClick = onBack)
                .semantics { contentDescription = "Back" },
            contentAlignment = Alignment.Center,
        ) { Symbol("back", size = 24.dp) }
        Text(
            title,
            Modifier.weight(1f),
            style = MaterialTheme.typography.headlineSmall.let { if (small) it.copy(fontSize = 20.sp, lineHeight = 28.sp) else it },
            maxLines = 1,
            overflow = androidx.compose.ui.text.style.TextOverflow.Ellipsis,
        )
        trailing()
    }
}

/** The tutor art. Placeholder drawable until the final avatar SVG is converted. */
@Composable
fun KaiwaAvatar(modifier: Modifier = Modifier) {
    Image(painterResource(Res.drawable.kaiwa_avatar), contentDescription = "Kaiwa tutor", modifier = modifier)
}

enum class GlowMood { Speaking, Listening, Flat }

/**
 * Background wash for the call stage. It reads only the call status (who is speaking) and never the
 * end-of-turn detector, so it looks identical in every detection mode.
 */
@Composable
fun Modifier.stageGlow(mood: GlowMood, reducedMotion: Boolean): Modifier {
    val spec = tween<Color>(700)
    val radial by animateColorAsState(
        when (mood) {
            GlowMood.Speaking -> Color(0xFFB9D18A); GlowMood.Listening -> Color(0xFFCFD3E4); GlowMood.Flat -> Kaiwa.PrimaryTint
        }, spec
    )
    val top by animateColorAsState(
        when (mood) {
            GlowMood.Speaking -> Color(0xFFD3E3AF); GlowMood.Listening -> Color(0xFFDCE3D4); GlowMood.Flat -> Kaiwa.PrimaryTint
        }, spec
    )
    val bottom by animateColorAsState(if (mood == GlowMood.Flat) Color(0xFFF3F5E8) else Color(0xFFF6F4E6), spec)
    val drift = if (reducedMotion) 0.5f else {
        val t = rememberInfiniteTransition()
        t.animateFloat(0f, 1f, infiniteRepeatable(tween(7000, easing = LinearEasing), RepeatMode.Reverse)).value
    }
    return this.drawBehind {
        drawRect(Brush.verticalGradient(listOf(top, Kaiwa.PrimaryTint, bottom), startY = 0f, endY = size.height))
        if (mood != GlowMood.Flat) {
            val center = Offset(size.width * (0.15f + 0.1f * drift), size.height * 0.02f)
            drawRect(
                Brush.radialGradient(
                    listOf(radial, radial.copy(alpha = 0f)),
                    center = center,
                    radius = size.width * (0.9f + 0.1f * drift),
                )
            )
        }
    }
}
