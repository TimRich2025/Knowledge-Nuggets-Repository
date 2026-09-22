"""Audition three distinct original male narrators without time stretching."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

from kn_open_voice import TEXT, download

OUTPUT = Path("kn-male-voice-audition")
VOICES = ("am_fenrir", "am_puck", "bm_george")


def main() -> None:
    OUTPUT.mkdir(exist_ok=True)
    model = Kokoro(str(download("kokoro-v1.0.onnx")),
                   str(download("voices-v1.0.bin")))
    result = {"text": TEXT, "native_speed": 1.16, "voices": {}}
    for name in VOICES:
        locale = "en-gb" if name.startswith("bm_") else "en-us"
        samples, rate = model.create(TEXT, voice=name, speed=1.16, lang=locale)
        samples = np.asarray(samples, dtype=np.float32)
        if rate != 24000 or not np.isfinite(samples).all() or np.max(np.abs(samples)) < .02:
            raise ValueError(f"Voice {name} returned invalid audio")
        sf.write(OUTPUT / f"{name}.wav", samples, rate, subtype="PCM_16")
        result["voices"][name] = {"seconds": round(len(samples)/rate, 3),
                                  "sample_rate": rate, "channels": 1}
    (OUTPUT / "result.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
