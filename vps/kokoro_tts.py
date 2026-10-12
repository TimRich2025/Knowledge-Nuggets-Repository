"""Generate one continuous, energetic narration with the offline Kokoro model."""
from __future__ import annotations

import argparse
import os
import wave
from pathlib import Path

import numpy as np
import onnxruntime as ort
from kokoro_onnx import Kokoro


DEFAULT_MODEL = "/opt/kokoro/kokoro-v1.0.int8.onnx"
DEFAULT_VOICES = "/opt/kokoro/voices-v1.0.bin"
VOICE = "af_bella"


def synthesize(text: str, output: Path) -> None:
    model = os.environ.get("KN_KOKORO_MODEL", DEFAULT_MODEL)
    voices = os.environ.get("KN_KOKORO_VOICES", DEFAULT_VOICES)
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    session = ort.InferenceSession(model, sess_options=options, providers=["CPUExecutionProvider"])
    kokoro = Kokoro.from_session(session, voices)
    try:
        samples, sample_rate = kokoro.create(
            text,
            voice=VOICE,
            speed=1.08,
            lang="en-us",
            sentence_pause=0.18,
            clause_pause=0.07,
            continuous=True,
        )
    finally:
        kokoro.voices.close()
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
    with wave.open(str(output), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(int(sample_rate))
        wav.writeframes(pcm.tobytes())
    if output.stat().st_size < 10_000:
        raise RuntimeError("Kokoro returned no usable narration")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", required=True)
    parser.add_argument("--output", type=Path, required=True)
    options = parser.parse_args()
    synthesize(options.text, options.output)


if __name__ == "__main__":
    main()
