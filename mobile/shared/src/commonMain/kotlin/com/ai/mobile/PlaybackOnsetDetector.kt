package com.ai.mobile

/**
 * Detects when decoded remote audio becomes audible-level after silence, from per-frame RMS.
 * Pure logic so it can be tested without a device. Decoded audio is still not proof that the
 * speaker output was heard.
 */
class PlaybackOnsetDetector(
    private val rmsThreshold: Double = 0.01,
    private val onsetSilenceMs: Long = 300,
    private val stopSilenceMs: Long = 300,
) {
    private var playing = false
    private var lastLoudMs: Long? = null
    private var silentSinceMs: Long? = null

    /** Returns "remote_audio_playback_started"/"remote_audio_playback_stopped" or null. */
    fun accept(nowMs: Long, rms: Double): String? {
        val loud = rms >= rmsThreshold
        if (loud) {
            val gap = lastLoudMs?.let { nowMs - it } ?: Long.MAX_VALUE
            lastLoudMs = nowMs
            silentSinceMs = null
            if (!playing && gap >= onsetSilenceMs) {
                playing = true
                return "remote_audio_playback_started"
            }
            return null
        }
        if (playing) {
            val since = silentSinceMs ?: nowMs.also { silentSinceMs = it }
            if (nowMs - since >= stopSilenceMs) {
                playing = false
                silentSinceMs = null
                return "remote_audio_playback_stopped"
            }
        }
        return null
    }

    fun reset() {
        playing = false; lastLoudMs = null; silentSinceMs = null
    }
}
