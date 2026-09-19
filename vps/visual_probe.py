from __future__ import annotations

import hashlib
import hmac
import os
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from .config import API_TOKEN, OUTPUTS
from .source_cache import IngestError


PROBE_ROOT = OUTPUTS / "source-probes"
MAX_WINDOW_SECONDS = 90.0
MAX_SAMPLES = 12
PROBE_TTL_SECONDS = 24 * 60 * 60
ALLOWED_SOURCE_HOST_SUFFIXES = (
    "nasa.gov", "nih.gov", "nlm.nih.gov", "cdc.gov", "wikimedia.org", "wikipedia.org",
)


def _safe_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise IngestError("source_url must be a direct http(s) video URL")
    host = (parsed.hostname or "").lower()
    if not any(host == suffix or host.endswith(f".{suffix}") for suffix in ALLOWED_SOURCE_HOST_SUFFIXES):
        raise IngestError("source host is outside the approved NASA, US-government, or Wikimedia families")
    return url


def _clean_old_probes() -> None:
    PROBE_ROOT.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - PROBE_TTL_SECONDS
    for path in PROBE_ROOT.iterdir():
        try:
            if path.is_dir() and path.stat().st_mtime < cutoff:
                shutil.rmtree(path)
        except OSError:
            # A concurrent vision request may still be reading an older probe.
            continue


def make_probe_token(probe_id: str) -> str:
    return hmac.new(API_TOKEN.encode(), f"source-probe:{probe_id}".encode(), hashlib.sha256).hexdigest()


def verify_probe_token(probe_id: str, token: str) -> bool:
    return bool(API_TOKEN) and hmac.compare_digest(token, make_probe_token(probe_id))


def source_probe_key(source_url: str, start_seconds: float, end_seconds: float) -> str:
    material = f"{source_url}|{float(start_seconds):.3f}|{float(end_seconds):.3f}".encode()
    return hashlib.sha256(material).hexdigest()[:32]


def _existing_probe(probe_id: str, source_url: str, start: float, end: float, period: float) -> dict | None:
    target = PROBE_ROOT / probe_id
    frames = sorted(target.glob("frame-*.jpg")) if target.is_dir() else []
    sheet = target / "contact-sheet.jpg"
    if not frames or not sheet.is_file():
        return None
    return {
        "probe_id": probe_id,
        "source_url": source_url,
        "candidate_start_seconds": start,
        "candidate_end_seconds": end,
        "sample_period_seconds": period,
        "frames": [
            {"index": index + 1, "approx_seconds": round(start + index * period, 3), "name": frame.name}
            for index, frame in enumerate(frames)
        ],
        "contact_sheet_name": sheet.name,
    }


def create_source_probe(source_url: str, start_seconds: float, end_seconds: float, probe_id: str | None = None) -> dict:
    """Extract evenly spaced, small JPEG frames from a bounded candidate interval.

    This deliberately does not claim that an interval is semantically correct.  It
    makes the evidence available to the connected vision model, which is the only
    component allowed to issue a VERIFIED temporal match.
    """
    source_url = _safe_url(source_url)
    start = max(0.0, float(start_seconds))
    end = float(end_seconds)
    window = end - start
    if window < 1.5:
        raise IngestError("candidate interval must be at least 1.5 seconds")
    if window > MAX_WINDOW_SECONDS:
        raise IngestError(f"candidate interval exceeds {MAX_WINDOW_SECONDS:.0f}-second probe limit")

    _clean_old_probes()
    probe_id = probe_id or uuid.uuid4().hex
    target = PROBE_ROOT / probe_id
    sample_count = max(2, min(MAX_SAMPLES, int(window) + 1))
    period = window / sample_count
    existing = _existing_probe(probe_id, source_url, start, end, period)
    if existing:
        return existing
    if target.exists():
        shutil.rmtree(target, ignore_errors=True)
    target.mkdir(parents=True, exist_ok=False)
    # The input URL is never interpolated into a shell command.
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-rw_timeout", "15000000", "-user_agent", "KnowledgeNuggetsVisualProbe/1.0",
        "-ss", f"{start:.3f}", "-i", source_url, "-t", f"{window:.3f}",
        "-an", "-vf", f"fps=1/{period:.6f},scale=960:-2",
        "-frames:v", str(sample_count), "-q:v", "3", str(target / "frame-%03d.jpg"),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=150)
        frames = sorted(target.glob("frame-*.jpg"))
        if result.returncode or not frames:
            detail = (result.stderr or "frame extraction failed")[-1000:]
            raise IngestError(f"source-frame probe failed: {detail}")
        sheet = target / "contact-sheet.jpg"
        sheet_cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-framerate", "1", "-i", str(target / "frame-%03d.jpg"),
            "-frames:v", "1", "-vf", "scale=480:-2,tile=3x4:padding=4", "-q:v", "3", str(sheet),
        ]
        sheet_result = subprocess.run(sheet_cmd, capture_output=True, text=True, timeout=45)
        if sheet_result.returncode or not sheet.is_file():
            detail = (sheet_result.stderr or "contact-sheet extraction failed")[-1000:]
            raise IngestError(f"source-frame contact sheet failed: {detail}")
        return {
            "probe_id": probe_id,
            "source_url": source_url,
            "candidate_start_seconds": start,
            "candidate_end_seconds": end,
            "sample_period_seconds": period,
            "frames": [
                {"index": index + 1, "approx_seconds": round(start + index * period, 3), "name": frame.name}
                for index, frame in enumerate(frames)
            ],
            "contact_sheet_name": sheet.name,
        }
    except Exception:
        shutil.rmtree(target, ignore_errors=True)
        raise


def probe_frame_path(probe_id: str, frame_name: str) -> Path:
    permitted_name = (frame_name.startswith("frame-") and frame_name.endswith(".jpg")) or frame_name == "contact-sheet.jpg"
    if not re_fullmatch_hex(probe_id) or not permitted_name:
        raise IngestError("invalid probe frame identifier")
    path = (PROBE_ROOT / probe_id / frame_name).resolve()
    root = PROBE_ROOT.resolve()
    if root not in path.parents or not path.is_file():
        raise IngestError("probe frame unavailable")
    return path


def re_fullmatch_hex(value: str) -> bool:
    return len(value) == 32 and all(char in "0123456789abcdef" for char in value)
