"""Create the original rotating music library shipped with the renderer.

The tracks are deterministic, loop on complete eight-bar phrases, and use
different tempos, chord progressions and lead patterns.  They are rendered at
48 kHz stereo and encoded as high-quality Vorbis during the container build.
No third-party recording or music licence is involved.
"""
from __future__ import annotations

import argparse
import math
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np


SAMPLE_RATE = 48_000
BARS = 8


@dataclass(frozen=True)
class TrackRecipe:
    filename: str
    bpm: float
    roots: tuple[int, int, int, int]
    quality: str
    melody: tuple[int, ...]
    seed: int
    bass_drive: float
    pad_level: float


TRACKS = (
    TrackRecipe("kn_original_neon_drive.ogg", 126, (40, 36, 43, 38), "minor",
                (7, 12, 10, 7, 3, 7, 10, 12), 1101, 1.00, 0.72),
    TrackRecipe("kn_original_discovery_spark.ogg", 122, (45, 41, 48, 43), "minor",
                (12, 10, 7, 10, 3, 7, 10, 14), 2202, 0.82, 0.92),
    TrackRecipe("kn_original_momentum_grid.ogg", 132, (42, 38, 45, 40), "minor",
                (7, 7, 10, 12, 15, 12, 10, 7), 3303, 1.12, 0.62),
    TrackRecipe("kn_original_future_motion.ogg", 128, (38, 34, 41, 36), "minor",
                (3, 7, 10, 14, 12, 10, 7, 5), 4404, 0.92, 0.80),
)


def midi_hz(note: float) -> float:
    return 440.0 * 2.0 ** ((float(note) - 69.0) / 12.0)


def _pan(signal: np.ndarray, value: float) -> tuple[np.ndarray, np.ndarray]:
    angle = (max(-1.0, min(1.0, value)) + 1.0) * math.pi / 4.0
    return signal * math.cos(angle), signal * math.sin(angle)


def _place(left: np.ndarray, right: np.ndarray, signal: np.ndarray,
           start: int, pan: float = 0.0, level: float = 1.0) -> None:
    if start >= len(left):
        return
    end = min(len(left), start + len(signal))
    mono = signal[:end - start] * level
    l_sig, r_sig = _pan(mono, pan)
    left[start:end] += l_sig
    right[start:end] += r_sig


def _osc(freq: float, seconds: float, sr: int, harmonics: tuple[float, ...]) -> np.ndarray:
    t = np.arange(max(1, int(seconds * sr)), dtype=np.float64) / sr
    phase = 2.0 * np.pi * freq * t
    signal = np.zeros_like(t)
    for index, amount in enumerate(harmonics, 1):
        signal += amount * np.sin(phase * index)
    return signal.astype(np.float32)


def _pluck(freq: float, seconds: float, sr: int, brightness: float = 1.0) -> np.ndarray:
    t = np.arange(max(1, int(seconds * sr)), dtype=np.float64) / sr
    tone = _osc(freq, seconds, sr, (1.0, .42 * brightness, .22 * brightness, .10))
    attack = np.minimum(1.0, t / .008)
    envelope = attack * np.exp(-5.8 * t / max(.12, seconds))
    return (tone * envelope).astype(np.float32)


def _bass(freq: float, seconds: float, sr: int, drive: float) -> np.ndarray:
    t = np.arange(max(1, int(seconds * sr)), dtype=np.float64) / sr
    tone = _osc(freq, seconds, sr, (1.0, .38, .20, .10, .05))
    attack = np.minimum(1.0, t / .012)
    release = np.minimum(1.0, np.maximum(0.0, (seconds - t) / .09))
    return np.tanh(tone * drive) * attack * release * .43


def _kick(sr: int) -> np.ndarray:
    seconds = .24
    t = np.arange(int(seconds * sr), dtype=np.float64) / sr
    phase = 2 * np.pi * (43 * t + (118 - 43) * .045 * (1 - np.exp(-24 * t)))
    body = np.sin(phase) * np.exp(-17 * t)
    click = np.sin(2 * np.pi * 2100 * t) * np.exp(-85 * t)
    return np.tanh((body + .10 * click) * 1.8).astype(np.float32)


def _noise_hit(rng: np.random.Generator, sr: int, seconds: float,
               decay: float, body_freq: float = 0.0) -> np.ndarray:
    t = np.arange(max(1, int(seconds * sr)), dtype=np.float64) / sr
    noise = rng.standard_normal(len(t))
    # A difference filter removes the muddy low end without scipy.
    noise = np.concatenate(([0.0], np.diff(noise)))
    noise /= max(.001, float(np.max(np.abs(noise))))
    hit = noise * np.exp(-decay * t)
    if body_freq:
        hit += .35 * np.sin(2 * np.pi * body_freq * t) * np.exp(-18 * t)
    return hit.astype(np.float32)


def render_recipe(recipe: TrackRecipe, sample_rate: int = SAMPLE_RATE,
                  bars: int = BARS) -> np.ndarray:
    sr = int(sample_rate)
    beat = 60.0 / recipe.bpm
    bar = beat * 4.0
    duration = bars * bar
    count = int(round(duration * sr))
    left = np.zeros(count, dtype=np.float32)
    right = np.zeros(count, dtype=np.float32)
    rng = np.random.default_rng(recipe.seed)
    kick = _kick(sr)
    snare = _noise_hit(rng, sr, .27, 13.0, 185.0)
    hat = _noise_hit(rng, sr, .075, 42.0)
    open_hat = _noise_hit(rng, sr, .20, 17.0)
    triad = (0, 3, 7) if recipe.quality == "minor" else (0, 4, 7)

    for bar_index in range(bars):
        bar_start = bar_index * bar
        root = recipe.roots[bar_index % len(recipe.roots)]

        # Wide sustained harmony, intentionally quiet under the narration.
        for chord_index, interval in enumerate(triad):
            pad = _osc(midi_hz(root + 12 + interval), bar * 1.03, sr,
                       (1.0, .16, .07, .03))
            t = np.arange(len(pad), dtype=np.float64) / sr
            envelope = np.sin(np.clip(t / bar, 0, 1) * np.pi) ** .55
            _place(left, right, pad * envelope, int(bar_start * sr),
                   pan=(-.52 + chord_index * .52), level=.065 * recipe.pad_level)

        # Syncopated bass creates motion without fighting the spoken rhythm.
        bass_pattern = (0.0, .75, 1.5, 2.0, 2.75, 3.5)
        for step_index, beat_offset in enumerate(bass_pattern):
            note = root + (12 if step_index in (1, 4) else 0)
            bass = _bass(midi_hz(note), beat * .42, sr, recipe.bass_drive)
            _place(left, right, bass, int((bar_start + beat_offset * beat) * sr),
                   pan=(-.06 if step_index % 2 else .06), level=.65)

        # Bright eighth-note arpeggio, alternated in the stereo image.
        for eighth in range(8):
            degree = recipe.melody[(bar_index * 2 + eighth) % len(recipe.melody)]
            note = root + 12 + degree
            pluck = _pluck(midi_hz(note), beat * .46, sr,
                           brightness=.85 + .12 * (bar_index % 3))
            _place(left, right, pluck, int((bar_start + eighth * beat / 2) * sr),
                   pan=(-.38 if eighth % 2 == 0 else .38), level=.13)

        for beat_index in range(4):
            position = bar_start + beat_index * beat
            _place(left, right, kick, int(position * sr), level=.62)
            if beat_index in (1, 3):
                _place(left, right, snare, int(position * sr), level=.20)
            for half in range(2):
                hat_pos = position + half * beat / 2
                _place(left, right, hat, int(hat_pos * sr),
                       pan=(-.58 if (beat_index + half) % 2 else .58), level=.075)
            if beat_index == 3 and bar_index % 2 == 1:
                _place(left, right, open_hat, int((position + beat / 2) * sr),
                       pan=.44, level=.07)

    # Rhythmic pumping keeps the arrangement energetic and leaves clean space
    # around each kick even before the narration sidechain is applied.
    time = np.arange(count, dtype=np.float64) / sr
    phase = np.mod(time, beat)
    pump = 1.0 - .23 * np.exp(-phase / .095)
    left *= pump.astype(np.float32)
    right *= pump.astype(np.float32)

    # A short non-wrapping stereo reflection adds width without washing out the
    # centre where the voice sits.
    delay = max(1, int(.018 * sr))
    left[delay:] += right[:-delay] * .075
    right[delay:] += left[:-delay].copy() * .065

    stereo = np.stack((left, right), axis=1)
    stereo = np.tanh(stereo * 1.25)
    peak = float(np.max(np.abs(stereo))) or 1.0
    stereo *= .91 / peak
    fade = min(int(.035 * sr), count // 8)
    if fade:
        curve = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        stereo[:fade] *= curve[:, None]
        stereo[-fade:] *= curve[::-1, None]
    return stereo.astype(np.float32)


def write_wav(path: Path, stereo: np.ndarray, sample_rate: int = SAMPLE_RATE) -> None:
    pcm = (np.clip(stereo, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(int(sample_rate))
        wav.writeframes(pcm.tobytes())


def build_library(output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated = []
    with tempfile.TemporaryDirectory(prefix="kn-music-") as temporary:
        scratch = Path(temporary)
        for recipe in TRACKS:
            target = output_dir / recipe.filename
            wav = scratch / f"{target.stem}.wav"
            write_wav(wav, render_recipe(recipe))
            process = subprocess.run([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(wav), "-c:a", "libvorbis", "-q:a", "6", str(target),
            ], capture_output=True, text=True, timeout=180)
            if process.returncode or not target.is_file() or target.stat().st_size < 80_000:
                raise RuntimeError(f"music encode failed for {recipe.filename}: {process.stderr[-500:]}")
            generated.append(target)
    return generated


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path,
                        default=Path(__file__).resolve().parent.parent / "assets" / "music")
    options = parser.parse_args()
    for output in build_library(options.output_dir):
        print(output.name, flush=True)


if __name__ == "__main__":
    main()
