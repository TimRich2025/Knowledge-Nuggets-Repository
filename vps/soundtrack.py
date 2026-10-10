"""The music bed under the narration.

A faceless knowledge Short is carried by its voice, so the bed exists to stop
the silence between sentences from sounding empty, not to be noticed. It sits
far below the speech and ducks further whenever a word is spoken, which is what
makes a bed feel produced rather than laid on top.

The renderer prefers licensed tracks placed in the music directory. When that
library is empty it generates a restrained cinematic pad locally, so a finished
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
# Far enough under the voice that it reads as atmosphere. The ducking takes it
# lower again while a word is being spoken.
DEFAULT_GAIN_DB = float(os.environ.get("KN_MUSIC_GAIN_DB", "-19"))
FADE_IN_SECONDS = 1.2
FADE_OUT_SECONDS = 1.6
# A Short opens on a question, so the bed should already be there. Anything
# longer than this and the first beat plays dry.
MAX_FADE_IN_SHARE = 0.08


def procedural_bed_source(duration: float) -> str:
    """A quiet, original ambient chord generated entirely by FFmpeg.

    The low fifth and octave make it read as a bed instead of a test tone. A
    slow swell and a very light upper pulse keep it moving without competing
    with the narration. The regular ducking and gain stage are applied later.
    """
    duration = max(0.5, float(duration))
    expression = (
        "0.10*(sin(2*PI*55*t)+0.55*sin(2*PI*82.4069*t)+"
        "0.35*sin(2*PI*110*t))*(0.75+0.25*sin(2*PI*0.07*t))+"
        "0.012*sin(2*PI*220*t)*(0.5+0.5*sin(2*PI*1.6*t))"
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
        # Measured against a spoken passage: this pair dips the bed 11.5 dB while
        # a word is being said and lets it back up in the pause. A steeper
        # setting reached 24 dB, which reads as the music switching off and on
        # rather than as it making room.
        "[bedraw][duckkey]sidechaincompress=threshold=0.08:ratio=4:attack=15:"
        "release=380:makeup=1[bed];"
        "[voiceout][bed]amix=inputs=2:duration=first:dropout_transition=0:"
        "normalize=0[mixed];"
        "[mixed]alimiter=limit=0.94[a]"
    )
