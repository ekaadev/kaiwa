@file:OptIn(androidx.compose.material3.ExperimentalMaterial3ExpressiveApi::class)

package com.ai.mobile

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.MotionScheme
import androidx.compose.material3.Typography
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import mobile.shared.generated.resources.Res
import mobile.shared.generated.resources.nunito_bold
import mobile.shared.generated.resources.nunito_extrabold
import mobile.shared.generated.resources.nunito_semibold
import mobile.shared.generated.resources.zen_maru_gothic_medium
import org.jetbrains.compose.resources.Font

/** Design tokens from the Kaiwa wireframe (single light theme). */
object Kaiwa {
    val Bg = Color(0xFFFBF6EC)
    val Card = Color(0xFFFFFFFF)
    val Primary = Color(0xFF5B7A2E)
    val PrimaryEdge = Color(0xFF3E5520)
    val PrimaryTint = Color(0xFFE6EDD3)
    val PrimaryRing = Color(0xFFD5E0B8)
    val Ink = Color(0xFF2B2748)
    val InkMuted = Color(0xFF5A5575)
    val Outline = Color(0xFFE3DACA)
    val OutlineStrong = Color(0xFF948A74)
    val Danger = Color(0xFFC8472D)
    val DangerEdge = Color(0xFF8F2F1C)
    val StreakBg = Color(0xFFFBEFC9)
    val StreakInk = Color(0xFF6B4A00)

    val RadiusChip = 14.dp
    val RadiusButton = 18.dp
    val RadiusControl = 20.dp
    val RadiusCard = 24.dp
    val RadiusButtonLg = 28.dp
    val RadiusStage = 32.dp
}

private val lightColors = lightColorScheme(
    primary = Kaiwa.Primary,
    onPrimary = Color.White,
    primaryContainer = Kaiwa.PrimaryTint,
    onPrimaryContainer = Kaiwa.PrimaryEdge,
    secondary = Kaiwa.InkMuted,
    onSecondary = Color.White,
    secondaryContainer = Kaiwa.PrimaryTint,
    onSecondaryContainer = Kaiwa.PrimaryEdge,
    tertiary = Kaiwa.StreakInk,
    onTertiary = Color.White,
    tertiaryContainer = Kaiwa.StreakBg,
    onTertiaryContainer = Kaiwa.StreakInk,
    surface = Kaiwa.Bg,
    surfaceContainerLowest = Kaiwa.Card,
    surfaceContainerLow = Kaiwa.Card,
    surfaceContainer = Kaiwa.Card,
    surfaceContainerHigh = Kaiwa.PrimaryTint,
    surfaceContainerHighest = Kaiwa.PrimaryRing,
    onSurface = Kaiwa.Ink,
    onSurfaceVariant = Kaiwa.InkMuted,
    outline = Kaiwa.OutlineStrong,
    outlineVariant = Kaiwa.Outline,
    inverseSurface = Kaiwa.Ink,
    inverseOnSurface = Kaiwa.Bg,
    inversePrimary = Kaiwa.PrimaryRing,
    error = Kaiwa.Danger,
    onError = Color.White,
    errorContainer = Color(0xFFFBE3DC),
    onErrorContainer = Kaiwa.DangerEdge,
    background = Kaiwa.Bg,
    onBackground = Kaiwa.Ink,
    surfaceTint = Kaiwa.Primary,
)

/** Zen Maru Gothic carries the Japanese lines; Nunito (no kana/kanji) is used for everything else. */
@Composable
fun japaneseFontFamily() = FontFamily(Font(Res.font.zen_maru_gothic_medium, FontWeight.Medium))

@Composable
fun ConversationTheme(content: @Composable () -> Unit) {
    val nunito = FontFamily(
        Font(Res.font.nunito_semibold, FontWeight.Normal),
        Font(Res.font.nunito_semibold, FontWeight.Medium),
        Font(Res.font.nunito_bold, FontWeight.SemiBold),
        Font(Res.font.nunito_bold, FontWeight.Bold),
        Font(Res.font.nunito_extrabold, FontWeight.ExtraBold),
    )
    val base = Typography()
    fun TextStyle.nunito() = copy(fontFamily = nunito)
    MaterialTheme(
        colorScheme = lightColors,
        motionScheme = MotionScheme.standard(),
        typography = Typography(
            displayLarge = base.displayLarge.nunito(),
            displayMedium = base.displayMedium.nunito(),
            displaySmall = base.displaySmall.nunito(),
            headlineLarge = base.headlineLarge.nunito(),
            headlineMedium = base.headlineMedium.nunito().copy(fontWeight = FontWeight.ExtraBold),
            headlineSmall = base.headlineSmall.nunito().copy(
                fontSize = 24.sp, lineHeight = 32.sp, fontWeight = FontWeight.ExtraBold
            ),
            titleLarge = base.titleLarge.nunito().copy(fontWeight = FontWeight.ExtraBold),
            titleMedium = base.titleMedium.nunito().copy(
                fontSize = 15.sp, lineHeight = 22.sp, fontWeight = FontWeight.Bold
            ),
            titleSmall = base.titleSmall.nunito(),
            bodyLarge = base.bodyLarge.nunito().copy(fontSize = 17.sp, lineHeight = 26.sp),
            bodyMedium = base.bodyMedium.nunito().copy(fontSize = 15.sp, lineHeight = 22.sp),
            bodySmall = base.bodySmall.nunito().copy(fontSize = 13.sp, lineHeight = 18.sp),
            labelLarge = base.labelLarge.nunito().copy(fontWeight = FontWeight.Bold),
            labelMedium = base.labelMedium.nunito().copy(
                fontSize = 12.sp, lineHeight = 16.sp, fontWeight = FontWeight.Bold
            ),
            labelSmall = base.labelSmall.nunito(),
        ),
        content = content,
    )
}
