"""Official-source candidate discovery.

Discovery is intentionally separate from visual verification: an API response can
prove neither the exact contents of a shot nor an acceptable time interval.  It
only removes the manual file-search/download step by returning direct, official
NASA video candidates that can subsequently be probed frame by frame.
"""
from __future__ import annotations

import json
import re
import subprocess
from typing import Any
from urllib.parse import urlparse, urlunparse

import requests


NASA_IMAGES_SEARCH = "https://images-api.nasa.gov/search"
# Largest first; an asset without ~orig still has a usable ~large.
VIDEO_SIZE_ORDER = ("~orig", "~large", "~medium", "~small", "~preview")
MAX_CANDIDATES = 24
# Measuring a work whose catalogue entry is silent costs one header read, so
# the scan stops after this many rather than spending a whole HTTP timeout
# budget on a subject the catalogue only holds in standard definition.
MAX_MEASUREMENTS_PER_SEARCH = 14
# NASA published standard definition for decades. A 2004 asset is genuinely
# 320x212 and can never pass the renderer's Full HD gate, so asking for it
# wastes a catalogue round trip and a header read. HD became the norm well
# before this year.
DEFAULT_EARLIEST_YEAR = 2015
_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "KnowledgeNuggetsSourceCatalog/1.0"})


# One bounded header read. The window the ingest later cuts is fetched the
# same way, so a clip that answers here will answer then.
PROBE_TIMEOUT_SECONDS = 40


class SourceCatalogError(RuntimeError):
    pass


def is_full_hd(width: int, height: int) -> bool:
    """The renderer's own gate, applied during discovery so nothing is built to fail it."""
    return (width >= 1920 and height >= 1080) or (height >= 1920 and width >= 1080)


def probe_stream(url: str) -> tuple[float, int, int]:
    """Read a remote clip's real length and frame size from its own header.

    The catalogue's duration is free text and its pixel dimensions are often
    absent altogether, and a clip that turns out to be 320x212 fails the
    renderer's Full HD gate after the whole job has been assembled. So where
    the catalogue is silent, the decoder answers.
    """
    try:
        output = subprocess.run(
            ["ffprobe", "-v", "error",
             # The same HTTP identity the ingest uses. Without them the
             # catalogue answers 403 and every clip reads as unmeasurable.
             "-user_agent", "KnowledgeNuggetsSourceIngest/4.0",
             "-referer", "https://images.nasa.gov/",
             "-rw_timeout", "20000000",
             "-select_streams", "v:0",
             "-show_entries", "stream=width,height:format=duration",
             "-of", "json", url],
            capture_output=True, text=True, timeout=PROBE_TIMEOUT_SECONDS, check=True,
        ).stdout
        payload = json.loads(output)
        stream = (payload.get("streams") or [{}])[0]
        return (float(payload.get("format", {}).get("duration") or 0),
                int(stream.get("width") or 0), int(stream.get("height") or 0))
    except (subprocess.SubprocessError, OSError, ValueError, KeyError, TypeError, IndexError):
        return 0.0, 0, 0


def _approved_nasa_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and (host == "nasa.gov" or host.endswith(".nasa.gov"))


def _nasa_https_url(url: str) -> str | None:
    """Upgrade NASA catalogue HTTP links to HTTPS after validating the host."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not (host == "nasa.gov" or host.endswith(".nasa.gov")):
        return None
    return urlunparse(parsed._replace(scheme="https"))


def _asset_video_urls(asset_listing_url: str) -> tuple[str | None, str | None, list[str]]:
    """Resolve original MP4, review MP4, and official storyboard frames."""
    response = _SESSION.get(asset_listing_url, timeout=(10, 25))
    response.raise_for_status()
    links = response.json()
    if not isinstance(links, list):
        return None, None, []
    secured_links = [secured for link in links if isinstance(link, str) for secured in [_nasa_https_url(link)] if secured]
    videos = [link for link in secured_links if link.lower().split("?")[0].endswith(".mp4")]
    # Rank by NASA's own size suffix, best first. Sorting by URL length instead
    # picks ~preview.mp4 whenever an asset has no ~orig, and a 320x212 preview
    # fails the renderer's Full HD gate after the whole job has been built.
    def _size_rank(link: str) -> tuple[int, int]:
        lowered = link.lower()
        for rank, suffix in enumerate(("~orig", "~large", "~medium", "~small", "~preview")):
            if suffix in lowered:
                return rank, len(link)
        return len(VIDEO_SIZE_ORDER), len(link)

    originals = sorted(videos, key=_size_rank)
    review_variants = sorted(
        videos,
        key=lambda link: (
            0 if "~preview" in link.lower() else 1 if "~small" in link.lower() else 2 if "~medium" in link.lower() else 3 if "~large" in link.lower() else 4,
            len(link),
        ),
    )
    original = next((link for link in originals if _approved_nasa_url(link)), None)
    review = next((link for link in review_variants if _approved_nasa_url(link)), original)
    medium_frames = [link for link in secured_links if re.search(r"~medium_\d+\.jpg(?:$|\?)", link, re.I)]
    large_frames = [link for link in secured_links if re.search(r"~large_\d+\.jpg(?:$|\?)", link, re.I)]
    storyboard = sorted(medium_frames or large_frames)[:8]
    return original, review, storyboard


def _asset_metadata(asset_listing_url: str) -> dict[str, Any]:
    """Read technical metadata published next to the official NASA asset."""
    metadata_url = asset_listing_url.rsplit("/", 1)[0] + "/metadata.json"
    try:
        response = _SESSION.get(metadata_url, timeout=(10, 20))
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return {"metadata_url": metadata_url, "source_width": 0, "source_height": 0, "source_duration": ""}
    def integer(*keys: str) -> int:
        for key in keys:
            try:
                value = int(float(payload.get(key) or 0))
            except (TypeError, ValueError):
                value = 0
            if value:
                return value
        return 0
    return {
        "metadata_url": metadata_url,
        "source_width": integer("QuickTime:SourceImageWidth", "QuickTime:ImageWidth"),
        "source_height": integer("QuickTime:SourceImageHeight", "QuickTime:ImageHeight"),
        "source_duration": _text(payload.get("QuickTime:Duration") or payload.get("QuickTime:MediaDuration"), 80),
    }


def _fhd_or_higher(width: int, height: int) -> bool | None:
    if not width or not height:
        return None
    return (width >= 1920 and height >= 1080) or (height >= 1920 and width >= 1080)


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _search_items(query: str, requested: int, earliest_year: int | None) -> list[dict[str, Any]]:
    """One catalogue page, optionally restricted to the HD era."""
    params = {"q": query, "media_type": "video",
              "page_size": min(100, max(40, requested * 8))}
    if earliest_year:
        params["year_start"] = str(int(earliest_year))
    try:
        response = _SESSION.get(NASA_IMAGES_SEARCH, params=params, timeout=(10, 30))
        response.raise_for_status()
        items = response.json().get("collection", {}).get("items", [])
    except (requests.RequestException, ValueError) as exc:
        raise SourceCatalogError(f"NASA catalogue search failed: {exc}") from exc
    return items if isinstance(items, list) else []


def search_nasa_video_candidates(query: str, limit: int = 6,
                                 earliest_year: int = DEFAULT_EARLIEST_YEAR,
                                 measure=probe_stream) -> list[dict[str, Any]]:
    """Return unverified direct NASA video candidates for later frame review.

    No returned object has `semantic_match=EXACT`, `temporal_match=VERIFIED`,
    a licence PASS, or a timecode claim.  Those fields are deliberately absent
    so this function cannot accidentally become a render approval bypass.
    """
    query = _text(query, 240)
    if len(query) < 2:
        raise SourceCatalogError("source query must contain at least two characters")
    requested = max(1, min(int(limit), MAX_CANDIDATES))
    items = _search_items(query, requested, earliest_year)
    if len(items) < requested * 2:
        # The year filter is a preference, not a requirement. When it leaves the
        # page nearly empty, whether because the catalogue holds little recent
        # footage for this subject or because the parameter behaves differently
        # than documented, an unfiltered page is better than no footage at all.
        seen_hrefs = {item.get("href") for item in items}
        items = items + [item for item in _search_items(query, requested, None)
                         if item.get("href") not in seen_hrefs]

    candidates: list[dict[str, Any]] = []
    below_hd: list[dict[str, Any]] = []
    measured = 0
    for item in items:
        if len(candidates) >= requested:
            break
        data = (item.get("data") or [{}])[0]
        asset_listing = item.get("href")
        nasa_id = _text(data.get("nasa_id"), 120)
        if not nasa_id or not isinstance(asset_listing, str) or not _approved_nasa_url(asset_listing):
            continue
        try:
            direct_url, review_url, review_frames = _asset_video_urls(asset_listing)
        except (requests.RequestException, ValueError):
            continue
        if not direct_url:
            continue
        technical = _asset_metadata(asset_listing)
        fhd = _fhd_or_higher(technical["source_width"], technical["source_height"])
        if fhd is None and measured < MAX_MEASUREMENTS_PER_SEARCH:
            # Most NASA video assets publish no metadata.json, so without this
            # the sub-HD ones look eligible and occupy every slot. One header
            # read settles it here, where the loop can simply scan further.
            measured += 1
            duration, width, height = measure(direct_url)
            if width and height:
                technical = {**technical, "source_width": width, "source_height": height,
                             "source_duration": technical["source_duration"] or f"{duration:.2f}"}
                fhd = _fhd_or_higher(width, height)
        record = {
            "candidate_id": nasa_id,
            "source_family": "NASA Images",
            "title": _text(data.get("title"), 300),
            "description": _text(data.get("description"), 1000),
            "date_created": _text(data.get("date_created"), 80),
            "keywords": [_text(keyword, 80) for keyword in (data.get("keywords") or [])[:16]],
            "catalog_page_url": _text(item.get("links", [{}])[0].get("href") if item.get("links") else "", 2000),
            "asset_listing_url": asset_listing,
            "direct_download_url": direct_url,
            "review_proxy_url": review_url,
            "review_frame_urls": review_frames,
            **technical,
            "technical_status": "ELIGIBLE_FHD_OR_HIGHER" if fhd else "REJECT_BELOW_FHD" if fhd is False else "UNVERIFIED_TECHNICAL_METADATA",
            "candidate_status": "UNVERIFIED_REQUIRES_FRAME_REVIEW",
            "rights_status": "UNVERIFIED_REQUIRES_SOURCE_REVIEW",
            "verification_note": "Metadata is discovery evidence only. Extract and inspect a bounded frame probe before assigning a shot interval.",
        }
        # A work the catalogue itself calls sub-HD can never pass the renderer's
        # Full HD gate, so it does not occupy one of the requested slots. It is
        # kept aside rather than discarded, because a caller with nothing else
        # would rather see it than see an empty list.
        if record["technical_status"] == "REJECT_BELOW_FHD":
            below_hd.append(record)
        else:
            candidates.append(record)
    return candidates or below_hd[:requested]
