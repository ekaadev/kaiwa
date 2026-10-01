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
import mobile.shared.generated.resources.Res
import mobile.shared.generated.resources.roboto
import mobile.shared.generated.resources.roboto_bold
import mobile.shared.generated.resources.roboto_medium
import org.jetbrains.compose.resources.Font

private val lightColors = lightColorScheme(
    primary = Color(0xFF6750A4),
    onPrimary = Color(0xFFFFFFFF),
    primaryContainer = Color(0xFFE9DDFF),
    onPrimaryContainer = Color(0xFF150D56),
    secondary = Color(0xFF635A75),
    onSecondary = Color(0xFFFFFFFF),
    secondaryContainer = Color(0xFFE9DDFD),
    onSecondaryContainer = Color(0xFF1F182F),
    tertiary = Color(0xFF7D5260),
    onTertiary = Color(0xFFFFFFFF),
    tertiaryContainer = Color(0xFFFDDAE1),
    onTertiaryContainer = Color(0xFF3A0819),
    surface = Color(0xFFFAF8FE),
    surfaceContainerLow = Color(0xFFF5F3F8),
    surfaceContainer = Color(0xFFEFEDF2),
    surfaceContainerHigh = Color(0xFFE9E7ED),
    surfaceContainerHighest = Color(0xFFE4E1E7),
    onSurface = Color(0xFF1C1B1F),
    onSurfaceVariant = Color(0xFF494550),
    outline = Color(0xFF797581),
    outlineVariant = Color(0xFFC9C4D1),
    inverseSurface = Color(0xFF313034),
    inverseOnSurface = Color(0xFFF2F0F5),
    inversePrimary = Color(0xFFD2BCFC),
    error = Color(0xFFB3261E),
    onError = Color(0xFFFFFFFF),
    errorContainer = Color(0xFFF9DEDC),
    onErrorContainer = Color(0xFF410E0B),
    background = Color(0xFFFAF8FE),
    onBackground = Color(0xFF1C1B1F),
    surfaceTint = Color(0xFF6750A4),
)

@Composable
fun ConversationTheme(content: @Composable () -> Unit) {
    val font = FontFamily(
        Font(Res.font.roboto, FontWeight.Normal),
        Font(Res.font.roboto_medium, FontWeight.Medium),
        Font(Res.font.roboto_bold, FontWeight.Bold)
    )
    val base = Typography()
    fun TextStyle.roboto() = copy(fontFamily = font)
    MaterialTheme(
        colorScheme = lightColors,
        motionScheme = MotionScheme.standard(),
        typography = Typography(
            displayLarge = base.displayLarge.roboto(),
            displayMedium = base.displayMedium.roboto(),
            displaySmall = base.displaySmall.roboto(),
            headlineLarge = base.headlineLarge.roboto(),
            headlineMedium = base.headlineMedium.roboto(),
            headlineSmall = base.headlineSmall.roboto(),
            titleLarge = base.titleLarge.roboto(),
            titleMedium = base.titleMedium.roboto(),
            titleSmall = base.titleSmall.roboto(),
            bodyLarge = base.bodyLarge.roboto(),
            bodyMedium = base.bodyMedium.roboto(),
            bodySmall = base.bodySmall.roboto(),
            labelLarge = base.labelLarge.roboto(),
            labelMedium = base.labelMedium.roboto(),
            labelSmall = base.labelSmall.roboto(),
        ),
        content = content,
    )
}
