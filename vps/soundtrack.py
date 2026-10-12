"""The music bed under the narration.

The bed must be audible enough to create forward motion while the narration
stays dominant. Every source is normalised to a fixed musical loudness before
gentle voice ducking, so neither a quiet synth nor a hot licensed master can
silently disappear or overwhelm the words.

The renderer prefers licensed tracks placed in the music directory. When that
library is empty it generates an upbeat electronic groove locally, so a finished
Short never ships with narration alone and no third-party recording is needed.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from .config import ROOT

# Two places, checked in this order. The volume is for anything uploaded to the
# running worker; the repository folder is how a track actually gets here, since
# adding a file to git and letting the image carry it needs no access to the
# volume at all.
MUSIC_DIR = Path(os.environ.get("KN_MUSIC_DIR", str(ROOT / "music")))
BUNDLED_MUSIC_DIR = Path(__file__).resolve().parent.parent / "assets" / "music"
SUPPORTED_SUFFIXES = (".mp3", ".m4a", ".wav", ".ogg", ".opus", ".flac")
# Normalise first, then trim only one decibel. During speech the sidechain takes
# roughly another five to seven decibels away. The result stays present without
# masking consonants.
BED_TARGET_LUFS = float(os.environ.get("KN_MUSIC_TARGET_LUFS", "-20"))
DEFAULT_GAIN_DB = float(os.environ.get("KN_MUSIC_GAIN_DB", "-1"))
FADE_IN_SECONDS = 1.2
FADE_OUT_SECONDS = 1.6
# A Short opens on a question, so the bed should already be there. Anything
# longer than this and the first beat plays dry.
MAX_FADE_IN_SHARE = 0.08


def procedural_bed_source(duration: float) -> str:
    """An original 120 BPM electronic groove generated entirely by FFmpeg.

    A short kick, off-beat bass and four-note arpeggio create movement. Their
    envelopes keep the groove clean under speech instead of becoming a flat
    drone. Loudness matching and voice ducking are applied later.
    """
    duration = max(0.5, float(duration))
    expression = (
        r"0.24*sin(2*PI*55*t)*exp(-18*mod(t\,0.5))+"
        r"0.13*sin(2*PI*110*t)*exp(-10*mod(t+0.25\,0.5))+"
        r"0.10*sin(2*PI*t*if(eq(mod(floor(t*4)\,4)\,0)\,220\,"
        r"if(eq(mod(floor(t*4)\,4)\,1)\,277.18\,"
        r"if(eq(mod(floor(t*4)\,4)\,2)\,329.63\,440))))*exp(-12*mod(t\,0.25))+"
        r"0.025*(2*random(0)-1)*exp(-38*mod(t\,0.25))"
    )
    return f"aevalsrc={expression}:s=48000:d={duration:.3f}"


def _tracks_in(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(path for path in root.iterdir()
                  if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES)


def available_tracks(directory: Path | None = None) -> list[Path]:
    """Every usable track, from the volume if it has any, otherwise from the repo."""
    if directory is not None:
        return _tracks_in(Path(directory))
    return _tracks_in(MUSIC_DIR) or _tracks_in(BUNDLED_MUSIC_DIR)


def pick_track(content_id: str, tracks: list[Path]) -> Path | None:
    """Choose one track for this Short, the same one on every re-render.

    Hashing the content id rather than counting keeps a repeat render of the
    same Short identical, while consecutive Shorts move through the library
    instead of all opening on whichever track sorts first.
    """
    if not tracks:
        return None
    digest = hashlib.sha256(str(content_id or "").encode()).digest()
    return tracks[int.from_bytes(digest[:8], "big") % len(tracks)]


def bed_filter(duration: float, gain_db: float = DEFAULT_GAIN_DB) -> str:
    """Loop the track to the narration's length, fade both ends, set its level."""
    duration = max(0.5, float(duration))
    fade_in = min(FADE_IN_SECONDS, duration * MAX_FADE_IN_SHARE)
    fade_out = min(FADE_OUT_SECONDS, duration / 3)
    start_out = max(0.0, duration - fade_out)
    return (
        # A track shorter than the Short is looped rather than left to run out.
        "aloop=loop=-1:size=2000000000,"
        f"atrim=0:{duration:.3f},asetpts=PTS-STARTPTS,"
        "aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,"
        f"loudnorm=I={BED_TARGET_LUFS:.1f}:TP=-3.0:LRA=7.0,"
        f"afade=t=in:st=0:d={fade_in:.3f},"
        f"afade=t=out:st={start_out:.3f}:d={fade_out:.3f},"
        f"volume={gain_db:.2f}dB"
    )


def audio_graph(voice_chain: str, duration: float, voice_input: str = "2:a",
                music_input: str = "3:a", gain_db: float = DEFAULT_GAIN_DB) -> str:
    """The whole audio graph: treated voice, ducked bed, mixed and limited.

    The voice is split after its own processing so the compressor listens to the
    finished narration, not to the raw file. Ducking from the raw signal lets a
    quiet word pass without pulling the bed down with it.
    """
    return (
        f"[{voice_input}]{voice_chain}[voiced];"
        f"[voiced]asplit=2[voiceout][duckkey];"
        f"[{music_input}]{bed_filter(duration, gain_db)}[bedraw];"
        # A gentle dip keeps the groove audible through a sentence while still
        # clearing the centre for consonants and sentence attacks.
        "[bedraw][duckkey]sidechaincompress=threshold=0.10:ratio=2.5:attack=20:"
        "release=260:makeup=1[bed];"
        "[voiceout][bed]amix=inputs=2:duration=first:dropout_transition=0:"
        "normalize=0[mixed];"
        "[mixed]alimiter=limit=0.94[a]"
    )
