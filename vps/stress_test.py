"""Stage 1: real renderer, fixed local fixtures, technical status only."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

from .local_renderer import render_job


def run(command: list[str]) -> None:
    subprocess.run(command, check=True, capture_output=True, text=True)


def verify_mp4(path: Path) -> None:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,width,height",
         "-of", "json", str(path)], check=True, capture_output=True, text=True)
    streams = json.loads(probe.stdout)["streams"]
    if not any(s.get("codec_type") == "video" and s.get("width") == 1080
               and s.get("height") == 1920 for s in streams):
        raise ValueError("final MP4 is missing the 1080x1920 video stream")
    if not any(s.get("codec_type") == "audio" for s in streams):
        raise ValueError("final MP4 is missing its audio stream")
    run(["ffmpeg", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"])


def fixtures(root: Path) -> tuple[dict, dict]:
    clips = []
    for index in range(5):
        clip = root / f"fixed-{index}.mp4"
        run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
             "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30",
             "-vf", f"hue=h={index * 55}", "-t", "4", "-c:v", "libx264",
             "-threads", "2", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(clip)])
        clips.append(clip)
    audio = root / "fixed-tone.m4a"
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
         "-t", "15.5", "-c:a", "aac", str(audio)])
    scenes = []
    for index, clip in enumerate(clips):
        scene = {
            "source_url": f"https://fixture.invalid/fixed-{index}.mp4",
            "local_path": str(clip),
            "shot_start_seconds": 0.0, "shot_end_seconds": 4.0,
            "speech_start_seconds": index * 3.1,
            "speech_end_seconds": (index + 1) * 3.1,
            "spoken_phrase": f"Scene number {index + 1}",
            "caption_beats": ["Scene", "number", str(index + 1)],
            "caption_timings": [
                {"text": word, "start_seconds": start, "end_seconds": end}
                for word, start, end in (("Scene", 0.0, 1.0),
                                         ("number", 1.0, 2.0),
                                         (str(index + 1), 2.0, 3.1))
            ],
            "plain_language": True, "layout_mode": "CROP_FILL",
        }
        scenes.append(scene)
    job = {"content_id": "STAGE1-FIXED", "production_status": "READY",
           "tts_provider": "EDGE", "core_question_lines": ["WHY DOES THIS", "TEST WORK?"],
           "scenes": scenes}
    return job, {"audio": {"path": str(audio)}, "scenes": scenes}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--output", type=Path, default=Path("stage1-results"))
    args = parser.parse_args()
    if args.iterations < 1:
        parser.error("iterations must be positive")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = {"run_id": f"stage1-{int(time.time())}-{uuid.uuid4().hex[:8]}",
                "topic": "FIXED TECHNICAL FIXTURE", "stage": "RENDERER",
                "external_services": [], "technical_status": "TECHNICAL_FAIL",
                "quality_status": "NOT_EVALUATED", "production_ready": False,
                "iterations_required": args.iterations, "iterations_passed": 0,
                "retries": 0, "started_at": time.time(), "attempts": []}
    manifest_path = output / "stage1-manifest.json"
    try:
        with tempfile.TemporaryDirectory(prefix="kn-stage1-") as temp:
            root = Path(temp)
            job, ingested = fixtures(root)
            manifest["assets"] = {
                "audio_sha256": hashlib.sha256(Path(ingested["audio"]["path"]).read_bytes()).hexdigest(),
                "clips_sha256": [hashlib.sha256(Path(scene["local_path"]).read_bytes()).hexdigest()
                                 for scene in job["scenes"]]}
            for index in range(1, args.iterations + 1):
                started = time.time()
                work = root / f"run-{index:02d}"
                work.mkdir()
                try:
                    result = render_job(job, ingested, work)
                    verify_mp4(Path(result["preview_path"]))
                    manifest["attempts"].append({"iteration": index, "status": "TECHNICAL_PASS",
                        "duration_seconds": result["duration_seconds"],
                        "layout_header_mae": result["layout_header_mae"],
                        "elapsed_seconds": round(time.time() - started, 2)})
                    manifest["iterations_passed"] = index
                    print(f"{index}/{args.iterations} TECHNICAL_PASS", flush=True)
                except Exception as exc:
                    manifest["attempts"].append({"iteration": index, "status": "TECHNICAL_FAIL",
                        "error": f"{type(exc).__name__}: {exc}",
                        "elapsed_seconds": round(time.time() - started, 2)})
                    raise
            manifest["technical_status"] = "TECHNICAL_PASS"
    finally:
        manifest["ended_at"] = time.time()
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        print(f"Stage 1 manifest: {manifest_path}", flush=True)


if __name__ == "__main__":
    main()
