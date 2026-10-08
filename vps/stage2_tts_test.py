"""Stage 2: dynamic Edge narration and word marks with fixed local video fixtures.

Technical proof only. The synthetic clips do not establish production quality.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
import time
import uuid
from pathlib import Path

from .production_contract import validate_measured_render_contract
from .source_cache import synthesize_continuous_narration
from .local_renderer import render_job
from .stress_test import fixtures, verify_mp4

NUMBERS = ("one", "two", "three", "four", "five",
           "six", "seven", "eight", "nine", "ten")
VOICE = "en-US-AndrewMultilingualNeural"
RATE = "+8%"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("stage2-results"))
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": f"stage2-{int(time.time())}-{uuid.uuid4().hex[:8]}",
        "topic": "DYNAMIC TTS WITH FIXED TECHNICAL VIDEO FIXTURES",
        "stage": "EDGE_TTS_WORD_MARKS_AND_RENDERER",
        "external_services": ["Microsoft Edge TTS"],
        "technical_status": "TECHNICAL_FAIL",
        "quality_status": "NOT_EVALUATED",
        "production_ready": False,
        "iterations_required": 10,
        "iterations_passed": 0,
        "retries": 0,
        "started_at": time.time(),
        "attempts": [],
    }
    try:
        with tempfile.TemporaryDirectory(prefix="kn-stage2-") as directory:
            root = Path(directory)
            fixture_job, _ = fixtures(root)
            manifest["assets"] = {
                "clips_sha256": [
                    hashlib.sha256(Path(scene["local_path"]).read_bytes()).hexdigest()
                    for scene in fixture_job["scenes"]
                ]
            }
            for index, number in enumerate(NUMBERS, 1):
                started = time.time()
                try:
                    job = {
                        **fixture_job,
                        "content_id": f"STAGE2-DYNAMIC-{index:02d}",
                        "tts_voice": VOICE,
                        "tts_rate": RATE,
                        "scenes": [dict(scene) for scene in fixture_job["scenes"]],
                    }
                    phrases = [
                        f"Run {number} begins with shapes crossing the frame.",
                        "Green shapes move slowly across the entire screen.",
                        "Orange shapes now cover the center of frame.",
                        "Purple shapes appear briefly before fading away again.",
                        "Red shapes finish the sequence with final motion.",
                    ]
                    for scene, phrase in zip(job["scenes"], phrases):
                        scene["spoken_phrase"] = phrase
                        scene["caption_beats"] = phrase.rstrip(".").split()
                    audio, speech_timings, captions = synthesize_continuous_narration(
                        job["scenes"], VOICE, RATE
                    )
                    for scene, timing, words in zip(job["scenes"], speech_timings, captions):
                        scene.update(timing)
                        scene["caption_timings"] = words
                    validate_measured_render_contract(job["scenes"])
                    work = root / f"run-{index:02d}"
                    work.mkdir()
                    result = render_job(job, {"audio": audio, "scenes": job["scenes"]}, work)
                    verify_mp4(Path(result["preview_path"]))
                    manifest["attempts"].append({
                        "iteration": index,
                        "status": "TECHNICAL_PASS",
                        "tts_audio_sha256": hashlib.sha256(Path(audio["path"]).read_bytes()).hexdigest(),
                        "word_count": sum(len(words) for words in captions),
                        "duration_seconds": result["duration_seconds"],
                        "elapsed_seconds": round(time.time() - started, 2),
                    })
                    manifest["iterations_passed"] = index
                    print(f"{index}/10 TECHNICAL_PASS", flush=True)
                except Exception as exc:
                    manifest["attempts"].append({
                        "iteration": index,
                        "status": "TECHNICAL_FAIL",
                        "error": f"{type(exc).__name__}: {exc}",
                        "elapsed_seconds": round(time.time() - started, 2),
                    })
                    raise
            manifest["technical_status"] = "TECHNICAL_PASS"
    finally:
        manifest["ended_at"] = time.time()
        path = output / "stage2-manifest.json"
        path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"Stage 2 manifest: {path}", flush=True)


if __name__ == "__main__":
    main()
