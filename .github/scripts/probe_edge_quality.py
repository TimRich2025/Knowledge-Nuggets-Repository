"""Probe whether the free Edge speech endpoint returns better source audio."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import aiohttp
from edge_tts import Communicate
import edge_tts.communicate as communicate_module
from mutagen.mp3 import MP3


FORMATS = {
    "original_24k_48kbps": ("audio-24khz-48kbitrate-mono-mp3", 48_000),
    "higher_24k_160kbps": ("audio-24khz-160kbitrate-mono-mp3", 160_000),
    "higher_48k_192kbps": ("audio-48khz-192kbitrate-mono-mp3", 192_000),
}
OLD = '"outputFormat":"audio-24khz-48kbitrate-mono-mp3"'
TEXT = "Despite the enormous flames, the rocket remains fixed on the pad."


async def try_format(name: str, output_format: str, bitrate: int, root: Path) -> dict:
    original_send = aiohttp.ClientWebSocketResponse.send_str
    original_bitrate = communicate_module.MP3_BITRATE_BPS
    did_replace = False

    async def send(self, data, *args, **kwargs):
        nonlocal did_replace
        if "Path:speech.config" in data:
            if OLD not in data:
                raise RuntimeError("upstream audio format configuration changed")
            data = data.replace(OLD, f'"outputFormat":"{output_format}"')
            did_replace = True
        return await original_send(self, data, *args, **kwargs)

    aiohttp.ClientWebSocketResponse.send_str = send
    communicate_module.MP3_BITRATE_BPS = bitrate
    path = root / f"{name}.mp3"
    try:
        speech = Communicate(TEXT, "en-US-AndrewMultilingualNeural",
                             rate="+8%", boundary="WordBoundary")
        words = []
        with path.open("wb") as destination:
            async for chunk in speech.stream():
                if chunk["type"] == "audio":
                    destination.write(chunk["data"])
                elif chunk["type"] == "WordBoundary":
                    words.append(chunk["text"])
        if not did_replace or not words:
            raise RuntimeError("speech or word metadata missing")
        info = MP3(path).info
        return {"status": "success", "sample_rate": info.sample_rate,
                "bitrate": info.bitrate, "bytes": path.stat().st_size,
                "word_count": len(words), "format": output_format}
    except Exception as exc:
        path.unlink(missing_ok=True)
        return {"status": "unsupported", "reason": str(exc)[-320:],
                "format": output_format}
    finally:
        aiohttp.ClientWebSocketResponse.send_str = original_send
        communicate_module.MP3_BITRATE_BPS = original_bitrate


async def main() -> None:
    root = Path("tts-format-probe")
    root.mkdir(exist_ok=True)
    result = {}
    for name, (output_format, bitrate) in FORMATS.items():
        result[name] = await try_format(name, output_format, bitrate, root)
    (root / "result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
