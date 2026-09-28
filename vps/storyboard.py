"""Contact sheets built from the catalogue's own stills.

Cutting frames out of the video itself gives exact timestamps, but it means
downloading and decoding the clip, which takes tens of seconds per work. The
vision pass fetches the sheet by URL and will not wait that long: the first
attempt returned "[404] Requested entity was not found" after three minutes.

The catalogue already publishes a handful of evenly spaced stills for every
asset. Tiling those costs a few small image fetches and no decoding at all, so
the sheet exists before anything asks for it. The price is that their exact
positions are a convention rather than a measurement, which is why the times
handed to the vision pass are labelled as approximate.
"""
from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image

from .config import OUTPUTS

SHEET_ROOT = OUTPUTS / "storyboards"
# Measured against the vision pass, not against how the sheet looks. A request
# carrying eight sheets at 480px was refused three runs in a row with "this
# model is currently experiencing high demand", while a single sheet came back
# in seconds. The picture only has to be readable enough to name what is in it.
TILE_WIDTH = 384
MAX_TILES = 6
FETCH_TIMEOUT = (5, 20)
_SESSION = requests.Session()
_SESSION.headers.update({"User-Agent": "KnowledgeNuggetsStoryboard/1.0",
                         "Referer": "https://images.nasa.gov/"})


class StoryboardError(RuntimeError):
    pass


def sheet_id(frame_urls: list[str]) -> str:
    """One id per set of stills, so a repeated discovery reuses the sheet."""
    return hashlib.sha256("|".join(frame_urls).encode()).hexdigest()[:32]


def assumed_times(count: int, duration: float) -> list[float]:
    """Where the catalogue's stills most likely sit in the clip.

    They are published evenly spaced, so each still is taken as the middle of
    its share of the running time. Approximate on purpose: the matcher widens a
    window to its neighbouring stills precisely because these are not measured.
    """
    if count < 1:
        return []
    span = max(0.1, float(duration))
    return [round(span * (index + 0.5) / count, 2) for index in range(count)]


def build_sheet(frame_urls: list[str], destination: Path) -> int:
    """Tile the stills into one image. Returns how many made it in."""
    tiles = []
    for url in frame_urls[:MAX_TILES]:
        try:
            response = _SESSION.get(url, timeout=FETCH_TIMEOUT)
            response.raise_for_status()
            image = Image.open(BytesIO(response.content)).convert("RGB")
        except (requests.RequestException, OSError, ValueError):
            continue
        height = max(1, round(image.height * (TILE_WIDTH / image.width)))
        tiles.append(image.resize((TILE_WIDTH, height), Image.Resampling.LANCZOS))
    if not tiles:
        raise StoryboardError("no catalogue still could be fetched for this work")
    columns = 2 if len(tiles) <= 4 else 3
    rows = -(-len(tiles) // columns)
    cell = max(tile.height for tile in tiles)
    sheet = Image.new("RGB", (columns * TILE_WIDTH, rows * cell), (12, 12, 12))
    for position, tile in enumerate(tiles):
        sheet.paste(tile, ((position % columns) * TILE_WIDTH, (position // columns) * cell))
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination, quality=82)
    return len(tiles)


def ensure_sheet(frame_urls: list[str]) -> tuple[str, int]:
    """Build the sheet if it is not already on disk. Returns its id and tile count."""
    usable = [url for url in frame_urls if str(url or "").strip()]
    if not usable:
        raise StoryboardError("this work publishes no catalogue stills")
    identifier = sheet_id(usable)
    path = SHEET_ROOT / f"{identifier}.jpg"
    if path.is_file():
        marker = SHEET_ROOT / f"{identifier}.count"
        try:
            return identifier, int(marker.read_text())
        except (OSError, ValueError):
            path.unlink(missing_ok=True)
    count = build_sheet(usable, path)
    (SHEET_ROOT / f"{identifier}.count").write_text(str(count))
    return identifier, count


def sheet_path(identifier: str) -> Path:
    if len(identifier) != 32 or not all(c in "0123456789abcdef" for c in identifier):
        raise StoryboardError("invalid storyboard identifier")
    path = (SHEET_ROOT / f"{identifier}.jpg").resolve()
    if SHEET_ROOT.resolve() not in path.parents or not path.is_file():
        raise StoryboardError("storyboard sheet unavailable")
    return path
