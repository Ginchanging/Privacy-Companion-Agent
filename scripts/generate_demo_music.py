"""Generate the repository-owned deterministic local Demo music asset."""

from __future__ import annotations

import argparse
import hashlib
import math
import struct
import wave
from pathlib import Path


SAMPLE_RATE = 24_000
DURATION_SECONDS = 30
CHANNELS = 1
SAMPLE_WIDTH = 2
OUTPUT = Path(__file__).resolve().parents[1] / "data" / "music" / "tracks" / "calm_piano_01.wav"

# A gentle original four-chord loop. No samples or third-party recordings are used.
CHORDS = (
    (261.6256, 329.6276, 391.9954),
    (220.0000, 261.6256, 329.6276),
    (174.6141, 220.0000, 261.6256),
    (195.9977, 246.9417, 293.6648),
)


def _sample(index: int) -> int:
    time_seconds = index / SAMPLE_RATE
    beat = time_seconds / 2.5
    chord = CHORDS[int(beat) % len(CHORDS)]
    within = beat - math.floor(beat)
    attack = min(1.0, within / 0.08)
    release = min(1.0, (1.0 - within) / 0.18)
    envelope = max(0.0, min(attack, release))
    fade = min(1.0, time_seconds / 1.2, (DURATION_SECONDS - time_seconds) / 1.8)
    signal = 0.0
    for position, frequency in enumerate(chord):
        phase = 2.0 * math.pi * frequency * time_seconds
        signal += math.sin(phase) * (0.16 - position * 0.025)
        signal += math.sin(phase * 2.0) * 0.025
    bass_phase = 2.0 * math.pi * (chord[0] / 2.0) * time_seconds
    signal += math.sin(bass_phase) * 0.10
    value = max(-1.0, min(1.0, signal * envelope * max(0.0, fade)))
    return round(value * 32767)


def render() -> bytes:
    frames = bytearray()
    for index in range(SAMPLE_RATE * DURATION_SECONDS):
        frames.extend(struct.pack("<h", _sample(index)))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(OUTPUT), "wb") as wav:
        wav.setnchannels(CHANNELS)
        wav.setsampwidth(SAMPLE_WIDTH)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(frames)
    return OUTPUT.read_bytes()


def validate(audio: bytes) -> None:
    if audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        raise SystemExit("generated asset is not a WAV file")
    expected_bytes = 44 + SAMPLE_RATE * DURATION_SECONDS * CHANNELS * SAMPLE_WIDTH
    if len(audio) != expected_bytes:
        raise SystemExit(f"unexpected WAV size: {len(audio)} != {expected_bytes}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify that regenerating produces the checked-in bytes",
    )
    args = parser.parse_args()
    before = OUTPUT.read_bytes() if args.check and OUTPUT.exists() else None
    audio = render()
    validate(audio)
    if before is not None and before != audio:
        raise SystemExit("checked-in music differs from deterministic output")
    print(f"{OUTPUT.relative_to(OUTPUT.parents[3])} sha256={hashlib.sha256(audio).hexdigest()} bytes={len(audio)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
