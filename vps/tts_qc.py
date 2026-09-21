"""Produce a speech integrity reference for the rocket preview.

Only the verified narration and its measured word timestamps are exported.
No render job, callback, or publishing flow is invoked.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .source_cache import synthesize_edge_scene_audio


SCENES = [
    {"spoken_phrase": "Engines ignite beneath the rocket.",
     "caption_beats": ["ENGINES IGNITE", "BENEATH", "THE ROCKET"]},
    {"spoken_phrase": "Smoke fills the pad.",
     "caption_beats": ["SMOKE FILLS", "THE PAD"]},
    {"spoken_phrase": "Despite the enormous flames, the rocket remains fixed on the pad.",
     "caption_beats": ["DESPITE THE", "ENORMOUS FLAMES", "THE ROCKET REMAINS", "FIXED ON THE PAD"]},
    {"spoken_phrase": "Only then does it lift off and leave the launch site.",
     "caption_beats": ["ONLY THEN", "DOES IT LIFT OFF", "AND LEAVE", "THE LAUNCH SITE"]},
    {"spoken_phrase": "The rocket keeps climbing into open sky.",
     "caption_beats": ["THE ROCKET", "KEEPS CLIMBING", "INTO OPEN SKY"]},
]


def main() -> None:
    audio,timings,captions=synthesize_edge_scene_audio(
        SCENES,"en-US-AndrewMultilingualNeural","+8%",[3.5,2.1,5.0,5.5,4.0],
    )
    output=Path("tts-qc-output")
    output.mkdir(exist_ok=True)
    shutil.copyfile(audio["path"],output/"narration.wav")
    (output/"timings.json").write_text(json.dumps({
        "scenes":SCENES,"speech_timings":timings,"caption_timings":captions,
        "duration_seconds":audio["duration"],"voice":"en-US-AndrewMultilingualNeural",
    },indent=2),encoding="utf-8")
    print(f"Verified {sum(len(x) for x in captions)} spoken words across {len(timings)} scenes; "
          f"narration {audio['duration']:.2f}s")


if __name__=="__main__":
    main()
