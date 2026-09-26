"""Synthesize one scene with native word-level speech boundaries."""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from edge_tts import Communicate, SubMaker


async def synthesize(text: str, voice: str, rate: str, media: Path, subtitles: Path) -> None:
    speech = Communicate(text, voice, rate=rate, boundary="WordBoundary")
    cues = SubMaker()
    with media.open("wb") as output:
        async for chunk in speech.stream():
            if chunk["type"] == "audio":
                output.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                cues.feed(chunk)
    if not cues.cues or not media.stat().st_size:
        raise RuntimeError("neural speech returned no word boundaries or audio")
    subtitles.write_text(cues.get_srt(), encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", required=True)
    parser.add_argument("--voice", required=True)
    parser.add_argument("--rate", required=True)
    parser.add_argument("--write-media", type=Path, required=True)
    parser.add_argument("--write-subtitles", type=Path, required=True)
    return parser


def main() -> None:
    options = build_parser().parse_args()
    asyncio.run(synthesize(options.text, options.voice, options.rate,
                           options.write_media, options.write_subtitles))


if __name__ == "__main__":
    main()
