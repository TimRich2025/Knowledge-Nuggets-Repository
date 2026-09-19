"""Official-source candidate discovery.

Discovery is intentionally separate from visual verification: an API response can
prove neither the exact contents of a shot nor an acceptable time interval.  It
only removes the manual file-search/download step by returning direct, official
NASA video candidates that can subsequently be probed frame by frame.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

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


def _asset_video_url(asset_listing_url: str) -> str | None:
    """Resolve one NASA asset listing to a direct MP4 without guessing a URL."""
    response = _SESSION.get(asset_listing_url, timeout=(10, 25))
    response.raise_for_status()
    links = response.json()
    if not isinstance(links, list):
        return None
    videos = [str(link) for link in links if isinstance(link, str) and link.lower().split("?")[0].endswith(".mp4")]
    # NASA normally supplies a ~orig asset. Prefer it, then retain the first
    # actual MP4 returned by the official listing.
    videos.sort(key=lambda link: ("~orig" not in link.lower(), len(link)))
    return next((link for link in videos if _approved_nasa_url(link)), None)


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
            direct_url = _asset_video_url(asset_listing)
        except (requests.RequestException, ValueError):
            continue
        if not direct_url:
            continue
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
            "candidate_status": "UNVERIFIED_REQUIRES_FRAME_REVIEW",
            "rights_status": "UNVERIFIED_REQUIRES_SOURCE_REVIEW",
            "verification_note": "Metadata is discovery evidence only. Extract and inspect a bounded frame probe before assigning a shot interval.",
        })
    return candidates
