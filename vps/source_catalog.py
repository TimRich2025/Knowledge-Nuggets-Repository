"""Official-source candidate discovery.

Discovery is intentionally separate from visual verification: an API response can
prove neither the exact contents of a shot nor an acceptable time interval.  It
only removes the manual file-search/download step by returning direct, official
NASA video candidates that can subsequently be probed frame by frame.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse, urlunparse

import requests


NASA_IMAGES_SEARCH = "https://images-api.nasa.gov/search"
MAX_CANDIDATES = 12
_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "KnowledgeNuggetsSourceCatalog/1.0"})


class SourceCatalogError(RuntimeError):
    pass


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
    originals = sorted(videos, key=lambda link: ("~orig" not in link.lower(), len(link)))
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


def search_nasa_video_candidates(query: str, limit: int = 6) -> list[dict[str, Any]]:
    """Return unverified direct NASA video candidates for later frame review.

    No returned object has `semantic_match=EXACT`, `temporal_match=VERIFIED`,
    a licence PASS, or a timecode claim.  Those fields are deliberately absent
    so this function cannot accidentally become a render approval bypass.
    """
    query = _text(query, 240)
    if len(query) < 2:
        raise SourceCatalogError("source query must contain at least two characters")
    requested = max(1, min(int(limit), MAX_CANDIDATES))
    try:
        response = _SESSION.get(
            NASA_IMAGES_SEARCH,
            params={"q": query, "media_type": "video", "page_size": min(100, requested * 8)},
            timeout=(10, 30),
        )
        response.raise_for_status()
        items = response.json().get("collection", {}).get("items", [])
    except (requests.RequestException, ValueError) as exc:
        raise SourceCatalogError(f"NASA catalogue search failed: {exc}") from exc

    candidates: list[dict[str, Any]] = []
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
        candidates.append({
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
        })
    return candidates
