package com.ai.mobile

import androidx.compose.foundation.layout.size
import androidx.compose.material3.Icon
import androidx.compose.material3.LocalContentColor
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import mobile.shared.generated.resources.*
import org.jetbrains.compose.resources.painterResource

// Material Symbols use their native square viewport, rather than a text baseline.
private val symbols = mapOf(
    "home" to Res.drawable.symbol_home,
    "graphic_eq" to Res.drawable.symbol_graphic_eq,
    "history" to Res.drawable.symbol_history,
    "settings" to Res.drawable.symbol_settings,
    "mic" to Res.drawable.symbol_mic,
    "mic_off" to Res.drawable.symbol_mic_off,
    "call_end" to Res.drawable.symbol_call_end,
    "back" to Res.drawable.symbol_back,
    "lock" to Res.drawable.symbol_lock,
    "check" to Res.drawable.symbol_check,
    "delete" to Res.drawable.symbol_delete,
    "search" to Res.drawable.symbol_search,
    "close" to Res.drawable.symbol_close,
    "refresh" to Res.drawable.symbol_refresh,
    "forum" to Res.drawable.symbol_forum,
    "school" to Res.drawable.symbol_school,
    "arrow" to Res.drawable.symbol_arrow,
    "chevron_right" to Res.drawable.symbol_chevron_right,
    "science" to Res.drawable.symbol_science,
    "fire" to Res.drawable.symbol_fire,
    "expand" to Res.drawable.symbol_expand,
    "share" to Res.drawable.symbol_share,
    "logout" to Res.drawable.symbol_logout,
    "home_filled" to Res.drawable.symbol_home_filled,
    "graphic_eq_filled" to Res.drawable.symbol_graphic_eq_filled,
    "history_filled" to Res.drawable.symbol_history_filled,
)

@Composable
fun Symbol(
    name: String,
    description: String? = null,
    size: Dp = 24.dp,
    filled: Boolean = false,
    color: Color = LocalContentColor.current,
) {
    val key = if (filled && symbols.containsKey("${name}_filled")) "${name}_filled" else name
    Icon(
        painter = painterResource(symbols.getValue(key)),
        contentDescription = description,
        modifier = Modifier.size(size),
        tint = color,
    )
}
