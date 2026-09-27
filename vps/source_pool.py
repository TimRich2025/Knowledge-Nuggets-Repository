"""Assemble a Short's footage from several different works, by measurement.

A Short cut from one clip is one long take with jump cuts in it.  The obvious
fix, asking the writing model for more sources, is the one that failed: a model
cannot see a video, so it invents plausible URLs and plausible timecodes and
the ingest rejects the job.

So nothing here is invented.  The catalogue returns real assets, ffprobe reads
each one's real duration, the windows are cut inside that measured duration,
and the beats are dealt out across the works by a rule rather than by a
judgement.  The writing model is left with the one job it is actually good at,
describing what a window shows.
"""
from __future__ import annotations

import json
import math
import subprocess
from typing import Any, Callable

from .production_contract import (MAX_CONSECUTIVE_SCENES_PER_SOURCE,
                                  MAX_SOURCE_SHARE, MIN_DISTINCT_SOURCES,
                                  scene_source_key, validate_source_diversity)
from .source_catalog import SourceCatalogError, search_nasa_video_candidates


# NASA clips routinely open on a slate or a static countdown card and close on
# a fade, so both ends are left out of the usable span.
LEAD_IN_SECONDS = 3.0
TAIL_SECONDS = 1.5
# A beat window.  Kept just inside the 2.4s ingest limit, which floating point
# pushes over when it is written as exactly 2.4.
DEFAULT_WINDOW_SECONDS = 2.3
# Two windows from one work must not overlap, or the Short repeats itself
# inside a single source.
MIN_WINDOW_SEPARATION = 0.4
PROBE_TIMEOUT_SECONDS = 40
# More windows than the share cap will ever let one work spend.
MAX_WINDOWS_PER_SOURCE = 8


class SourcePoolError(RuntimeError):
    pass


def probe_duration(url: str) -> float:
    """Read a remote clip's real length from its header, never its metadata.

    The catalogue's own duration field is a free-text string and is sometimes
    absent, so the only trustworthy number is the one the decoder reports.
    """
    try:
        output = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", "-timeout", "20000000", url],
            capture_output=True, text=True, timeout=PROBE_TIMEOUT_SECONDS, check=True,
        ).stdout
        return float(json.loads(output)["format"]["duration"])
    except (subprocess.SubprocessError, OSError, ValueError, KeyError, TypeError):
        return 0.0


def plan_windows(duration: float, count: int, window: float = DEFAULT_WINDOW_SECONDS) -> list[tuple[float, float]]:
    """Spread `count` non-overlapping windows over a clip's usable span.

    Evenly spaced rather than consecutive, so two beats from one work show two
    genuinely different moments instead of four seconds of the same shot.
    """
    if count < 1:
        return []
    start = LEAD_IN_SECONDS if duration > LEAD_IN_SECONDS + TAIL_SECONDS + window else 0.0
    end = max(start, duration - TAIL_SECONDS)
    span = end - start
    if span < window:
        return []
    usable = int((span + MIN_WINDOW_SEPARATION) // (window + MIN_WINDOW_SEPARATION))
    count = min(count, max(1, usable))
    if count == 1:
        first = round(start + (span - window) / 2, 2)
        return [(first, round(first + window, 2))]
    step = (span - window) / (count - 1)
    windows = []
    for index in range(count):
        first = round(start + index * step, 2)
        windows.append((first, round(first + window, 2)))
    return windows


def _usable_source(candidate: dict[str, Any], duration: float, window: float) -> bool:
    if candidate.get("technical_status") == "REJECT_BELOW_FHD":
        return False
    return duration >= LEAD_IN_SECONDS + TAIL_SECONDS + window


def collect_sources(
    segments: list[dict[str, Any]],
    per_query: int,
    window: float,
    search: Callable[[str, int], list[dict[str, Any]]],
    measure: Callable[[str], float],
) -> list[dict[str, Any]]:
    """Discover and measure the works behind every query, keeping the order.

    A work found by two queries belongs to the first one that found it, so the
    later segment is pushed towards footage the earlier segment did not use.
    """
    seen: set[str] = set()
    sources: list[dict[str, Any]] = []
    failures: list[str] = []
    for position, segment in enumerate(segments):
        query = str(segment.get("query") or "").strip()
        if not query:
            raise SourcePoolError(f"segment {position + 1} has no search query")
        try:
            candidates = search(query, per_query)
        except SourceCatalogError as exc:
            failures.append(f"{query}: {exc}")
            continue
        for candidate in candidates:
            key = str(candidate.get("candidate_id") or "")
            if not key or key in seen:
                continue
            direct = str(candidate.get("direct_download_url") or "")
            if not direct:
                continue
            duration = measure(direct)
            if not _usable_source(candidate, duration, window):
                continue
            seen.add(key)
            sources.append({
                "segment": position,
                "query": query,
                "candidate_id": key,
                "title": candidate.get("title", ""),
                "description": candidate.get("description", ""),
                "keywords": candidate.get("keywords", []),
                "selected_asset_page_url": candidate.get("catalog_page_url") or candidate.get("asset_listing_url"),
                "direct_download_url": direct,
                "width": candidate.get("source_width") or 1920,
                "height": candidate.get("source_height") or 1080,
                "measured_duration_seconds": round(duration, 2),
            })
    if not sources:
        detail = "; ".join(failures) or "no catalogue result carried a usable direct video"
        raise SourcePoolError(f"no usable source was found for any segment ({detail})")
    return sources


def assign_beats(
    segments: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    window: float = DEFAULT_WINDOW_SECONDS,
) -> list[dict[str, Any]]:
    """Deal every beat to a work, by rule, so the diversity contract holds.

    Each beat prefers its own segment's footage, because that is what the
    narration at that point is about.  Within the segment the least-used work
    wins, the work that carried the previous beat is skipped outright, and a
    work that has already spent its share is skipped too.  A thin segment
    therefore borrows from the wider pool instead of leaning on its one clip,
    which is the case that produced the monotony this module exists to end.
    """
    total_beats = sum(int(segment.get("beats") or 0) for segment in segments)
    share_cap = max(1, math.ceil(total_beats * MAX_SOURCE_SHARE))
    by_segment: dict[int, list[dict[str, Any]]] = {}
    for source in sources:
        by_segment.setdefault(source["segment"], []).append(source)

    used: dict[str, int] = {source["candidate_id"]: 0 for source in sources}
    windows: dict[str, list[tuple[float, float]]] = {}
    plan: list[dict[str, Any]] = []
    previous = ""

    for source in sources:
        # The share cap already forbids one work carrying more than a third of
        # an eighteen-beat Short, so MAX_WINDOWS_PER_SOURCE is never the binding
        # limit; a short clip's own length is.
        windows[source["candidate_id"]] = plan_windows(
            source["measured_duration_seconds"], MAX_WINDOWS_PER_SOURCE, window)

    for position, segment in enumerate(segments):
        for _ in range(int(segment.get("beats") or 0)):
            preferred = by_segment.get(position) or []
            choice = (_pick(preferred, used, windows, previous, share_cap)
                      or _pick(sources, used, windows, previous, share_cap))
            if choice is None:
                raise SourcePoolError(
                    f"the discovered footage cannot fill {total_beats} beats without "
                    f"repeating a clip back to back or pushing one past its "
                    f"{share_cap}-beat share; widen the search queries"
                )
            index = used[choice["candidate_id"]]
            start, end = windows[choice["candidate_id"]][index]
            used[choice["candidate_id"]] = index + 1
            previous = choice["candidate_id"]
            plan.append({
                "beat": len(plan) + 1,
                "query": segment.get("query"),
                "candidate_id": choice["candidate_id"],
                "title": choice["title"],
                "description": choice["description"],
                "selected_asset_page_url": choice["selected_asset_page_url"],
                "direct_download_url": choice["direct_download_url"],
                "width": choice["width"],
                "height": choice["height"],
                "measured_duration_seconds": choice["measured_duration_seconds"],
                "shot_start_seconds": start,
                "shot_end_seconds": end,
            })
    return plan


def _pick(pool, used, windows, previous, share_cap):
    """The least-used work that is not exhausted, not last used, not over share."""
    options = [source for source in pool
               if source["candidate_id"] != previous
               and used[source["candidate_id"]] < share_cap
               and used[source["candidate_id"]] < len(windows[source["candidate_id"]])]
    if not options:
        return None
    return min(options, key=lambda source: (used[source["candidate_id"]], source["candidate_id"]))


def build_source_pool(
    segments: list[dict[str, Any]],
    per_query: int = 5,
    window_seconds: float = DEFAULT_WINDOW_SECONDS,
    search: Callable[[str, int], list[dict[str, Any]]] | None = None,
    measure: Callable[[str], float] | None = None,
) -> dict[str, Any]:
    """Return a measured, contract-clean beat plan the writing model can dress."""
    if not segments:
        raise SourcePoolError("at least one search segment is required")
    beats = sum(int(segment.get("beats") or 0) for segment in segments)
    if beats < 1:
        raise SourcePoolError("the segments request no beats")
    sources = collect_sources(segments, per_query, window_seconds,
                              search or search_nasa_video_candidates,
                              measure or probe_duration)
    required = min(MIN_DISTINCT_SOURCES, beats)
    if len(sources) < required:
        raise SourcePoolError(
            f"only {len(sources)} usable works were found, below the {required} the "
            f"production contract requires; add or broaden a search segment"
        )
    plan = assign_beats(segments, sources, window_seconds)
    # Fail here rather than three scenarios later: the plan is machine-made, so
    # a contract breach in it is a bug in this module, not a writing mistake.
    validate_source_diversity(plan)
    distinct = sorted({scene_source_key(beat) for beat in plan})
    return {
        "beats": len(plan),
        "distinct_sources": len(distinct),
        "window_seconds": window_seconds,
        "sources": sources,
        "beat_plan": plan,
        "diversity": {
            "minimum_required": required,
            "max_consecutive_per_source": MAX_CONSECUTIVE_SCENES_PER_SOURCE,
            "verified": True,
        },
        "assignment_policy": (
            "Intervals and URLs are measured facts. Copy them character for character "
            "and never invent, round or recompute one."
        ),
    }
