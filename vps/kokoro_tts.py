"""Generate one continuous, energetic narration with the offline Kokoro model."""
from __future__ import annotations

import argparse
import os
import wave
from pathlib import Path

import numpy as np
import onnxruntime as ort
from kokoro_onnx import Kokoro

from .passage_chunks import passage_chunks


DEFAULT_MODEL = "/opt/kokoro/kokoro-v1.0.fp16.onnx"
DEFAULT_VOICES = "/opt/kokoro/voices-v1.0.bin"
VOICE = "am_puck"
SPEED = 0.80


def synthesize(text: str, output: Path) -> None:
    model = os.environ.get("KN_KOKORO_MODEL", DEFAULT_MODEL)
    voices = os.environ.get("KN_KOKORO_VOICES", DEFAULT_VOICES)
    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    # Railway's production worker has a tight memory ceiling.  ONNX's arenas
    # otherwise retain the peak allocation of a passage for the whole process.
    options.enable_cpu_mem_arena = False
    options.enable_mem_pattern = False
    session = ort.InferenceSession(model, sess_options=options, providers=["CPUExecutionProvider"])
    kokoro = Kokoro.from_session(session, voices)
    passages = passage_chunks(text)
    if not passages:
        raise RuntimeError("Kokoro narration text is empty")
    try:
        sample_rate: int | None = None
        with wave.open(str(output), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            for passage in passages:
                samples, passage_rate = kokoro.create(
                    passage,
                    voice=VOICE,
                    # Puck's natural delivery is unusually fast.  This
                    # model-level pace preserves quality without post-stretch.
                    speed=SPEED,
                    lang="en-us",
                    sentence_pause=0.15,
                    clause_pause=0.05,
                    # Prosody remains continuous inside each multi-sentence
                    # passage.  Passage joins occur only after punctuation.
                    continuous=True,
                )
                if sample_rate is None:
                    sample_rate = int(passage_rate)
                    wav.setframerate(sample_rate)
                elif int(passage_rate) != sample_rate:
                    raise RuntimeError("Kokoro changed sample rate between passages")
                pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2")
                wav.writeframes(pcm.tobytes())
                del pcm, samples
    finally:
        kokoro.voices.close()
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
