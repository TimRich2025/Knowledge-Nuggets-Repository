"""The music bed under the narration.

A faceless knowledge Short is carried by its voice, so the bed exists to stop
the silence between sentences from sounding empty, not to be noticed. It sits
far below the speech and ducks further whenever a word is spoken, which is what
makes a bed feel produced rather than laid on top.

No track ships with this repository. The renderer plays whatever licensed audio
is placed in the music directory, and renders without a bed when it is empty,
because a missing soundtrack is never a reason to fail a finished Short.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

from .config import ROOT

MUSIC_DIR = Path(os.environ.get("KN_MUSIC_DIR", str(ROOT / "music")))
SUPPORTED_SUFFIXES = (".mp3", ".m4a", ".wav", ".ogg", ".opus", ".flac")
# Far enough under the voice that it reads as atmosphere. The ducking takes it
# lower again while a word is being spoken.
DEFAULT_GAIN_DB = float(os.environ.get("KN_MUSIC_GAIN_DB", "-19"))
FADE_IN_SECONDS = 1.2
FADE_OUT_SECONDS = 1.6
# A Short opens on a question, so the bed should already be there. Anything
# longer than this and the first beat plays dry.
MAX_FADE_IN_SHARE = 0.08


def available_tracks(directory: Path | None = None) -> list[Path]:
    """Every usable track in the music directory, in a stable order."""
    root = Path(directory or MUSIC_DIR)
    if not root.is_dir():
        return []
    return sorted(path for path in root.iterdir()
                  if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES)


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
