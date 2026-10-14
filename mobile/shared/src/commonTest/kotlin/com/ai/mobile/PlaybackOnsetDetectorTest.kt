package com.ai.mobile

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class PlaybackOnsetDetectorTest {
    @Test
    fun reportsStartAfterSilenceAndStopAfterQuietGap() {
        val detector = PlaybackOnsetDetector()
        assertNull(detector.accept(0, 0.0))
        assertEquals("remote_audio_playback_started", detector.accept(1_000, 0.2))
        assertNull(detector.accept(1_010, 0.2))
        assertNull(detector.accept(1_100, 0.0))
        assertEquals("remote_audio_playback_stopped", detector.accept(1_400, 0.0))
        assertEquals("remote_audio_playback_started", detector.accept(2_000, 0.3))
    }

    @Test
    fun shortPauseDoesNotRestartPlayback() {
        val detector = PlaybackOnsetDetector()
        detector.accept(0, 0.2)
        assertNull(detector.accept(100, 0.0))
        assertNull(detector.accept(150, 0.2))
    }
}
