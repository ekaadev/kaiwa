from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest

from scripts.try_whisper_microphone import record_turn


def test_microphone_audio_is_float32_pcm_and_never_written_to_disk():
    pcm = np.array([-32768, 0, 32767], dtype="<i2").tobytes()
    with patch(
        "scripts.try_whisper_microphone.subprocess.run",
        return_value=SimpleNamespace(returncode=0, stdout=pcm, stderr=b""),
    ) as run:
        audio = record_turn(5, "default")

    assert audio.dtype == np.float32
    np.testing.assert_allclose(audio, [-1.0, 0.0, 32767 / 32768])
    command = run.call_args.args[0]
    assert command == [
        "arecord", "-q", "-D", "default", "-f", "S16_LE", "-c", "1",
        "-r", "16000", "-d", "5", "-t", "raw",
    ]
    assert run.call_args.kwargs["capture_output"] is True


def test_microphone_errors_are_reported_without_fake_transcript():
    with patch(
        "scripts.try_whisper_microphone.subprocess.run",
        return_value=SimpleNamespace(returncode=1, stdout=b"", stderr=b"device busy"),
    ):
        with pytest.raises(RuntimeError, match="device busy"):
            record_turn(5, "default")
