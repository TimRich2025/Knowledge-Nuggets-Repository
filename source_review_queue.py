"""Build a no-cost visual review queue from official NASA video candidates.

This command performs discovery and creates contact sheets.  It never assigns
semantic/temporal approval and can therefore never make a job renderable.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

import requests
from PIL import Image, ImageOps

from vps.source_catalog import SourceCatalogError, search_nasa_video_candidates


OUT = Path("output")
REVIEW = OUT / "source-review"
MAX_CANDIDATES_PER_SCENE = 2
SAMPLE_COUNT = 6


def _run(command: list[str], timeout: int = 90) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout)


def _probe(url: str) -> dict[str, Any] | None:
    result = _run([
        "ffprobe", "-v", "error", "-user_agent", "KnowledgeNuggetsReviewQueue/1.0",
        "-select_streams", "v:0", "-show_entries", "stream=width,height,codec_name",
        "-show_entries", "format=duration", "-of", "json", url,
    ], timeout=60)
    if result.returncode:
        return None
    try:
        payload = json.loads(result.stdout)
        stream = (payload.get("streams") or [{}])[0]
        duration = float((payload.get("format") or {}).get("duration") or 0)
        width, height = int(stream.get("width") or 0), int(stream.get("height") or 0)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if duration < 1.5 or width < 1 or height < 1:
        return None
    return {"duration": duration, "width": width, "height": height, "codec": stream.get("codec_name")}


def _contact_sheet(frame_urls: list[str], destination: Path) -> dict[str, Any] | None:
    frames: list[Image.Image] = []
    session = requests.Session()
    session.headers.update({"User-Agent": "KnowledgeNuggetsReviewQueue/1.0"})
    for url in frame_urls[:SAMPLE_COUNT]:
        try:
            response = session.get(url, timeout=(10, 25))
            response.raise_for_status()
            from io import BytesIO
            frame = Image.open(BytesIO(response.content)).convert("RGB")
            frames.append(ImageOps.fit(frame, (480, 270), method=Image.Resampling.LANCZOS))
        except (requests.RequestException, OSError):
            continue
    if len(frames) < 2:
        return None
    canvas = Image.new("RGB", (480 * 3 + 24, 270 * 2 + 18), "white")
    for index, frame in enumerate(frames[:SAMPLE_COUNT]):
        x = 6 + (index % 3) * 486
        y = 6 + (index // 3) * 276
        canvas.paste(frame, (x, y))
    canvas.save(destination, "JPEG", quality=88, optimize=True)
    return {"frame_count": min(len(frames), SAMPLE_COUNT), "frame_width": 480, "frame_height": 270}


def _queries(scene: dict[str, Any]) -> list[str]:
    supplied = [str(value).strip() for value in (scene.get("search_queries") or []) if str(value).strip()]
    fallback = str(scene.get("visual_target") or scene.get("spoken_phrase") or "").strip()
    return (supplied or ([fallback] if fallback else []))[:3]


def main() -> None:
    scenes = json.loads(os.environ["KN_SCENE_BRIEF"])
    if isinstance(scenes, dict):
        scenes = scenes.get("scenes") or []
    if not isinstance(scenes, list) or not scenes:
        raise SystemExit("KN_SCENE_BRIEF must contain a non-empty JSON scene list")
    OUT.mkdir(exist_ok=True)
    REVIEW.mkdir(parents=True, exist_ok=True)
    queue: list[dict[str, Any]] = []
    used_urls: set[str] = set()

    for position, scene in enumerate(scenes, 1):
        scene_number = scene.get("scene_number") or scene.get("scene") or position
        candidates: list[dict[str, Any]] = []
        for query in _queries(scene):
            try:
                discovered = search_nasa_video_candidates(query, 6)
            except SourceCatalogError:
                continue
            for candidate in discovered:
                url = candidate["direct_download_url"]
                if url in used_urls:
                    continue
                # Catalogue metadata is useful but not authoritative enough to
                # admit an unknown-quality file.  Probe the actual stream before
                # any visual contact sheet is created, so sub-HD and technically
                # opaque candidates cannot enter the review queue.
                technical = _probe(url)
                if not technical or not (
                    (technical["width"] >= 1920 and technical["height"] >= 1080)
                    or (technical["height"] >= 1920 and technical["width"] >= 1080)
                ):
                    continue
                sheet = REVIEW / f"scene-{scene_number}-candidate-{len(candidates) + 1}.jpg"
                evidence = _contact_sheet(candidate.get("review_frame_urls") or [], sheet)
                if not evidence:
                    continue
                used_urls.add(url)
                candidates.append({
                    **candidate,
                    "source_width": technical["width"],
                    "source_height": technical["height"],
                    "source_duration_seconds": round(technical["duration"], 3),
                    "source_codec": technical["codec"],
                    "technical_status": "ELIGIBLE_FHD_OR_HIGHER",
                    "technical_evidence": "FFPROBE_DIRECT_VIDEO",
                    "review_evidence": {**evidence, "type": "NASA_CATALOG_STORYBOARD", "timecodes": "UNAVAILABLE"},
                    "contact_sheet": str(sheet),
                    "semantic_match": "UNVERIFIED",
                    "temporal_match": "UNVERIFIED",
                    "semantic_score": 0,
                    "shot_start_seconds": None,
                    "shot_end_seconds": None,
                })
                if len(candidates) >= MAX_CANDIDATES_PER_SCENE:
                    break
            if len(candidates) >= MAX_CANDIDATES_PER_SCENE:
                break
        queue.append({
            "scene_number": scene_number,
            "spoken_phrase": scene.get("spoken_phrase", ""),
            "visual_target": scene.get("visual_target", ""),
            "must_show": scene.get("must_show") or [],
            "status": "VISUAL_REVIEW_REQUIRED" if candidates else "MISSING",
            "candidates": candidates,
        })

    payload = {
        "status": "VISUAL_REVIEW_REQUIRED",
        "render_allowed": False,
        "approval_policy": "Only visible frame evidence plus an exact continuous time interval may change a scene to EXACT/VERIFIED.",
        "scenes": queue,
    }
    (OUT / "source_review_queue.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"status": payload["status"], "scenes": len(queue), "candidates": sum(len(item["candidates"]) for item in queue)}))


if __name__ == "__main__":
    main()
