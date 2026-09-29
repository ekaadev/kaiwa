"""Transcribe short microphone turns locally without saving audio to disk.

Run from backend/: uv run --extra tutor --env-file .env python scripts/try_whisper_microphone.py
Requires the Linux `arecord` command and an input device accessible to ALSA.
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16_000


def record_turn(seconds: int, device: str) -> np.ndarray:
    """Capture 16-bit mono PCM directly from arecord's stdout, not a file."""
    result = subprocess.run(
        [
            "arecord",
            "-q",
            "-D",
            device,
            "-f",
            "S16_LE",
            "-c",
            "1",
            "-r",
            str(SAMPLE_RATE),
            "-d",
            str(seconds),
            "-t",
            "raw",
        ],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        error = result.stderr.decode(errors="replace").strip()
        raise RuntimeError(f"Mikrofon gagal diakses: {error}. Lihat perangkat dengan `arecord -L`.")
    if not result.stdout:
        raise RuntimeError("Mikrofon tidak menghasilkan audio.")
    return np.frombuffer(result.stdout, dtype="<i2").astype(np.float32) / 32768.0


def main() -> int:
    parser = argparse.ArgumentParser(description="Uji Whisper langsung dari mikrofon Linux")
    parser.add_argument("--seconds", type=int, default=5, help="Durasi tiap giliran (default: 5)")
    parser.add_argument("--device", default="default", help="Nama ALSA device (default: default)")
    args = parser.parse_args()
    if not 1 <= args.seconds <= 30:
        parser.error("--seconds harus antara 1 dan 30")

    if not shutil.which("arecord"):
        print(
            "Perintah `arecord` tidak ditemukan. Instal alsa-utils terlebih dahulu.",
            file=sys.stderr,
        )
        return 1

    model_path = Path(os.getenv("TUTOR_WHISPER_PATH", ""))
    if not os.getenv("TUTOR_WHISPER_PATH") or not (model_path / "model.bin").is_file():
        print("TUTOR_WHISPER_PATH belum menunjuk folder model Whisper yang valid.", file=sys.stderr)
        return 1

    from faster_whisper import WhisperModel

    print("Memuat Whisper small dari disk (sekali saja)...", flush=True)
    model = WhisperModel(str(model_path), device="cpu", compute_type="int8")
    print("Tekan Enter untuk merekam; ketik q lalu Enter untuk keluar.", flush=True)
    try:
        while input("\nEnter untuk bicara > ").strip().lower() != "q":
            print(f"Merekam {args.seconds} detik — silakan bicara...", flush=True)
            audio = record_turn(args.seconds, args.device)
            print("Mentranskripsi...", flush=True)
            segments, info = model.transcribe(audio, language=None, task="transcribe")
            text = " ".join(segment.text.strip() for segment in segments).strip()
            print(f"Bahasa: {info.language} | Teks: {text or '(tidak ada ujaran terdeteksi)'}")
    except (KeyboardInterrupt, EOFError):
        print("\nSelesai.")
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
