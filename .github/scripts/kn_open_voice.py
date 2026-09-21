"""Generate uncompressed, locally synthesised voice alternatives for the rocket short."""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

MODEL_ROOT = Path("/tmp/kn-kokoro")
OUTPUT = Path("kn-open-voice")
MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/"
TEXT = (
    "Engines ignite beneath the rocket. Smoke fills the pad. "
    "Despite the enormous flames, the rocket remains fixed on the pad. "
    "Only then does it lift off and leave the launch site. "
    "The rocket keeps climbing into open sky."
)


def download(name: str) -> Path:
    MODEL_ROOT.mkdir(parents=True, exist_ok=True)
    path = MODEL_ROOT / name
    if not path.exists():
        urllib.request.urlretrieve(MODEL_URL + name, path)
    if path.stat().st_size < 100_000:
        raise ValueError(f"Model file {name} is unexpectedly small")
    return path


def main() -> None:
    OUTPUT.mkdir(exist_ok=True)
    model = Kokoro(str(download("kokoro-v1.0.onnx")), str(download("voices-v1.0.bin")))
    result = {"text": TEXT, "voices": {}}
    for voice in ("am_michael", "af_heart"):
        samples, sample_rate = model.create(TEXT, voice=voice, speed=1.08, lang="en-us")
        samples = np.asarray(samples, dtype=np.float32)
        if sample_rate != 24000 or not np.isfinite(samples).all() or np.max(np.abs(samples)) < 0.02:
            raise ValueError(f"Invalid audio returned for {voice}")
        sf.write(OUTPUT / f"{voice}.wav", samples, sample_rate, subtype="PCM_16")
        result["voices"][voice] = {
            "sample_rate": sample_rate, "format": "PCM_16_WAV",
            "duration_seconds": len(samples) / sample_rate,
            "peak_dbfs": round(20 * np.log10(np.max(np.abs(samples))), 2),
        }
    (OUTPUT / "result.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
