"""Continuous higher-pitched narration when the Edge consumer endpoint is unavailable."""
from __future__ import annotations

import argparse
from pathlib import Path

from gtts import gTTS


def synthesize(text: str, output: Path) -> None:
    # The US Google voice is lighter than the previous male narrator.  It is
    # generated as one request so sentence cadence survives across visual cuts.
    gTTS(text=text, lang="en", tld="com", slow=False, lang_check=False).save(str(output))
    if not output.is_file() or output.stat().st_size < 1_000:
        raise RuntimeError("Google fallback TTS returned no usable audio")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    synthesize(options.text, options.output)


if __name__ == "__main__":
    main()
