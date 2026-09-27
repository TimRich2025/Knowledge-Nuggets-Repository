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
from urllib.parse import urlencode
from collections import Counter
from typing import Any, Callable

from .production_contract import (MAX_CONSECUTIVE_SCENES_PER_SOURCE,
                                  MAX_SOURCE_SHARE, MIN_DISTINCT_SOURCES,
                                  scene_source_key, validate_source_diversity)
from .scene_match import MATCH_FLOOR, plan_by_content, terms, window_terms
from .source_catalog import (SourceCatalogError, is_full_hd, probe_stream,
                             search_nasa_video_candidates)


# NASA clips routinely open on a slate or a static countdown card and close on
# a fade, so both ends are left out of the usable span.
LEAD_IN_SECONDS = 3.0
TAIL_SECONDS = 1.5
# A beat window. Wider than a beat actually needs, because the narration is
# spoken as one passage and a slower sentence must still fit inside the shot it
# was given. The renderer trims the segment to the spoken length.
DEFAULT_WINDOW_SECONDS = 3.2
# Two windows from one work must not overlap, or the Short repeats itself
# inside a single source.
MIN_WINDOW_SEPARATION = 0.4
# More windows than the share cap will ever let one work spend.
MAX_WINDOWS_PER_SOURCE = 8
# Every kept candidate costs a catalogue round trip and sometimes a header
# read, and Make's HTTP module gives this call a bounded wait.  Three usable
# works per segment already clears the five-source floor with two segments.
MAX_SOURCES_PER_SEGMENT = 4


NASA_DETAILS_PAGE = "https://images.nasa.gov/details/"


class SourcePoolError(RuntimeError):
    pass


def catalogue_page_url(candidate: dict[str, Any]) -> str:
    """The work's catalogue page, not the first link the search happened to list.

    The NASA search puts a preview JPEG first under `links`, so the field that
    reads like a page URL is an image. Every NASA asset has a details page at a
    known address, so build it from the asset id and keep whatever the search
    gave only for a source family that has no such convention.
    """
    if str(candidate.get("source_family") or "") == "NASA Images":
        asset = str(candidate.get("candidate_id") or "").strip()
        if asset:
            return f"{NASA_DETAILS_PAGE}{asset}"
    page = str(candidate.get("catalog_page_url") or "")
    if page.lower().split("?")[0].endswith((".jpg", ".jpeg", ".png")):
        return str(candidate.get("asset_listing_url") or page)
    return page or str(candidate.get("asset_listing_url") or "")


def parse_catalogue_duration(value: object) -> float:
    """Read the catalogue's own duration string, when it published a usable one.

    NASA writes it as "0:00:47", "47.50 s" or simply a number, depending on the
    asset.  Anything else is treated as absent, because a wrong length would
    place a window past the end of the clip.
    """
    text = str(value or "").strip().replace("s", "").strip()
    if not text:
        return 0.0
    try:
        if ":" in text:
            seconds = 0.0
            for part in text.split(":"):
                seconds = seconds * 60 + float(part)
            return seconds
        return float(text)
    except ValueError:
        return 0.0


def parse_catalogue_duration(value: object) -> float:
    """Read the catalogue's own duration string, when it published a usable one.

    NASA writes it as "0:00:47", "47.50 s" or simply a number, depending on the
    asset.  Anything else is treated as absent, because a wrong length would
    place a window past the end of the clip.
    """
    text = str(value or "").strip().replace("s", "").strip()
    if not text:
        return 0.0
    try:
        if ":" in text:
            seconds = 0.0
            for part in text.split(":"):
                seconds = seconds * 60 + float(part)
            return seconds
        return float(text)
    except ValueError:
        return 0.0


def probe_stream(url: str) -> tuple[float, int, int]:
    """Read a remote clip's real length and frame size from its own header.

    The catalogue's duration is free text and its pixel dimensions are often
    absent altogether, and a clip that turns out to be 1630x1080 fails the
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


def probe_duration(url: str) -> float:
    """The clip's length alone, for callers that do not need its frame size."""
    return probe_stream(url)[0]


def parse_catalogue_duration(value: object) -> float:
    """Read the catalogue's own duration string, when it published a usable one.

    NASA writes it as "0:00:47", "47.50 s" or simply a number, depending on the
    asset.  Anything else is treated as absent, because a wrong length would
    place a window past the end of the clip.
    """
    text = str(value or "").strip().replace("s", "").strip()
    if not text:
        return 0.0
    try:
        if ":" in text:
            seconds = 0.0
            for part in text.split(":"):
                seconds = seconds * 60 + float(part)
            return seconds
        return float(text)
    except ValueError:
        return 0.0


def parse_catalogue_duration(value: object) -> float:
    """Read the catalogue's own duration string, when it published a usable one.

    NASA writes it as "0:00:47", "47.50 s" or simply a number, depending on the
    asset.  Anything else is treated as absent, because a wrong length would
    place a window past the end of the clip.
    """
    text = str(value or "").strip().replace("s", "").strip()
    if not text:
        return 0.0
    try:
        if ":" in text:
            seconds = 0.0
            for part in text.split(":"):
                seconds = seconds * 60 + float(part)
            return seconds
        return float(text)
    except ValueError:
        return 0.0


def probe_stream(url: str) -> tuple[float, int, int]:
    """Read a remote clip's real length and frame size from its own header.

    The catalogue's duration is free text and its pixel dimensions are often
    absent altogether, and a clip that turns out to be 1630x1080 fails the
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


def probe_duration(url: str) -> float:
    """The clip's length alone, for callers that do not need its frame size."""
    return probe_stream(url)[0]


def is_full_hd(width: int, height: int) -> bool:
    """The renderer's own gate, applied here so a job is never built to fail it."""
    return (width >= 1920 and height >= 1080) or (height >= 1920 and width >= 1080)


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


def _usable_source(width: int, height: int, duration: float, window: float) -> bool:
    if not is_full_hd(width, height):
        return False
    return duration >= LEAD_IN_SECONDS + TAIL_SECONDS + window


def collect_sources(
    segments: list[dict[str, Any]],
    per_query: int,
    window: float,
    search: Callable[[str, int], list[dict[str, Any]]],
    measure: Callable[[str], tuple[float, int, int]],
    max_per_segment: int = MAX_SOURCES_PER_SEGMENT,
) -> list[dict[str, Any]]:
    """Discover and measure the works behind every query, keeping the order.

    A work found by two queries belongs to the first one that found it, so the
    later segment is pushed towards footage the earlier segment did not use.
    """
    seen: set[str] = set()
    sources: list[dict[str, Any]] = []
    failures: list[str] = []
    # Why a candidate was dropped is the only thing that explains a short pool,
    # and the message in the datastore is the only place anyone reads it.
    rejected = Counter()
    smallest_rejected = ""
    for position, segment in enumerate(segments):
        query = str(segment.get("query") or "").strip()
        if not query:
            raise SourcePoolError(f"segment {position + 1} has no search query")
        try:
            candidates = search(query, per_query)
        except SourceCatalogError as exc:
            failures.append(f"{query}: {exc}")
            continue
        rejected["candidates offered"] += len(candidates)
        kept = 0
        for candidate in candidates:
            if kept >= max_per_segment:
                break
            key = str(candidate.get("candidate_id") or "")
            if not key:
                rejected["no catalogue id"] += 1
                continue
            if key in seen:
                rejected["already used by an earlier segment"] += 1
                continue
            direct = str(candidate.get("direct_download_url") or "")
            if not direct:
                rejected["no direct video file"] += 1
                continue
            if candidate.get("technical_status") == "REJECT_BELOW_FHD":
                rejected["below Full HD"] += 1
                continue
            # The published figures cost nothing; reading the file's own header
            # costs a network round trip, so it is the fallback, not the rule.
            duration = parse_catalogue_duration(candidate.get("source_duration"))
            width = int(candidate.get("source_width") or 0)
            height = int(candidate.get("source_height") or 0)
            if not duration or not is_full_hd(width, height):
                measured_duration, measured_width, measured_height = measure(direct)
                duration = duration or measured_duration
                if measured_width and measured_height:
                    width, height = measured_width, measured_height
            if not width or not height:
                rejected["size unreadable"] += 1
                continue
            if not is_full_hd(width, height):
                rejected["below Full HD"] += 1
                smallest_rejected = smallest_rejected or f"{width}x{height}"
                continue
            if not _usable_source(width, height, duration, window):
                rejected[f"shorter than {LEAD_IN_SECONDS + TAIL_SECONDS + window:.1f}s"] += 1
                continue
            seen.add(key)
            kept += 1
            sources.append({
                "segment": position,
                "query": query,
                "candidate_id": key,
                "title": candidate.get("title", ""),
                "description": candidate.get("description", ""),
                "keywords": candidate.get("keywords", []),
                "selected_asset_page_url": catalogue_page_url(candidate),
                "direct_download_url": direct,
                # The catalogue's own storyboard frames, carried through so a
                # later vision pass can look at the work before a beat claims
                # what it shows.
                "review_frame_urls": candidate.get("review_frame_urls") or [],
                "width": width,
                "height": height,
                "measured_duration_seconds": round(duration, 2),
            })
    summary = rejection_summary(rejected, smallest_rejected)
    if not sources:
        detail = "; ".join([part for part in failures + [summary] if part])
        raise SourcePoolError(f"no usable source was found for any segment ({detail})")
    collect_sources.last_rejections = summary
    return sources


def rejection_summary(rejected: Counter, smallest: str) -> str:
    """Say what the searches returned and where each candidate went.

    A short pool with no explanation is indistinguishable from an empty
    catalogue, and this string is the only place anyone will read the
    difference.
    """
    offered = rejected.pop("candidates offered", 0)
    parts = [f"{count} {reason}" for reason, count in rejected.most_common()]
    for index, part in enumerate(parts):
        if "below Full HD" in part and smallest:
            parts[index] = f"{part} (e.g. {smallest})"
    head = f"the searches offered {offered} candidates"
    return head + ("; dropped " + ", ".join(parts) if parts else "; none were dropped by a gate")


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


def _widen(sources, segments, fallback_queries, per_query, window, search, measure, max_per_segment):
    """Add works found by broader terms, spread evenly over the segments."""
    known = {source["candidate_id"] for source in sources}
    widened = [{"query": str(query), "beats": 1} for query in fallback_queries if str(query).strip()]
    extra = collect_sources(widened, per_query, window, search, measure,
                            max_per_segment=max_per_segment)
    for position, source in enumerate(source for source in extra if source["candidate_id"] not in known):
        sources.append({**source, "segment": position % max(1, len(segments))})
    return sources


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
    fallback_queries: list[str] | None = None,
    per_query: int = 10,
    window_seconds: float = DEFAULT_WINDOW_SECONDS,
    search: Callable[[str, int], list[dict[str, Any]]] | None = None,
    measure: Callable[[str], tuple[float, int, int]] | None = None,
    max_per_segment: int = MAX_SOURCES_PER_SEGMENT,
) -> dict[str, Any]:
    """Return a measured, contract-clean beat plan the writing model can dress."""
    if not segments:
        raise SourcePoolError("at least one search segment is required")
    beats = sum(int(segment.get("beats") or 0) for segment in segments)
    if beats < 1:
        raise SourcePoolError("the segments request no beats")
    # When the real catalogue is used, record what its scan did with every item.
    # A pool that comes back short is otherwise indistinguishable from a
    # catalogue that holds nothing, and the two need opposite responses.
    scan: dict[str, int] = {}
    if search is None:
        def search(query: str, limit: int) -> list[dict[str, Any]]:
            return search_nasa_video_candidates(query, limit, scan=scan)
    measure = measure or probe_stream
    sources = collect_sources(segments, per_query, window_seconds, search, measure,
                              max_per_segment=max_per_segment)
    required = min(MIN_DISTINCT_SOURCES, beats)
    if len(sources) < required and fallback_queries:
        # A precise query returns a handful of works; a broad one returns dozens.
        # Rather than fail a good script because its subject was named too
        # exactly, widen once with the caller's broader terms and keep going.
        sources = _widen(sources, segments, fallback_queries, per_query, window_seconds,
                         search, measure, max_per_segment)
    if len(sources) < required:
        why = getattr(collect_sources, "last_rejections", "")
        catalogue = ", ".join(f"{count} {reason}" for reason, count in sorted(scan.items()))
        raise SourcePoolError(
            f"only {len(sources)} usable works were found, below the {required} the "
            f"production contract requires"
            + (f"; {why}" if why else "")
            + (f"; the catalogue scan saw {catalogue}" if catalogue else "")
            + ". A query naming one mission or vehicle matches only a handful of "
              "works; search for the subject instead"
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


# Frames per contact sheet. Six well-spaced stills describe a thirty-second
# clip well enough to place a three-second window, and several six-tile sheets
# are read far more accurately in one pass than several twelve-tile ones.
SHEET_FRAMES = 6
MAX_SHEET_SECONDS = 90.0
# How many works are sent for description at once. Beyond this the vision pass
# starts blurring one sheet into the next.
MAX_DESCRIBED_WORKS = 8


def sheet_frames(duration: float) -> list[dict[str, Any]]:
    """Where the contact sheet's frames fall in a clip, in seconds.

    The probe route derives its sampling from the window it is given, so the
    same arithmetic here tells the vision pass which second each numbered frame
    belongs to. Without that a description is just a list of pictures.
    """
    window = min(float(duration), MAX_SHEET_SECONDS)
    count = max(2, min(SHEET_FRAMES, int(window) + 1))
    period = window / count
    return [{"index": index + 1, "at_seconds": round(index * period, 3)}
            for index in range(count)]


def describe_request(sources: list[dict[str, Any]], base_url: str) -> list[dict[str, Any]]:
    """Each discovered work with the picture evidence needed to judge it."""
    described = []
    for source in sources[:MAX_DESCRIBED_WORKS]:
        window = min(float(source["measured_duration_seconds"]), MAX_SHEET_SECONDS)
        frames = sheet_frames(source["measured_duration_seconds"])
        query = urlencode({"source_url": source["direct_download_url"],
                           "candidate_start_seconds": "0",
                           "candidate_end_seconds": f"{window:.3f}",
                           "samples": len(frames)})
        described.append({**source,
                          "contact_sheet_url": f"{base_url.rstrip('/')}/source-probes/contact-sheet.jpg?{query}",
                          "frames": frames})
    return described


def plan_from_observations(
    beats: list[dict[str, Any]],
    works: list[dict[str, Any]],
    window_seconds: float = DEFAULT_WINDOW_SECONDS,
    match_floor: float = MATCH_FLOOR,
) -> dict[str, Any]:
    """Assign beats to windows on what the frames were seen to contain.

    Every window a work can offer is scored against every beat, so a beat is
    given footage that shows what it says it needs rather than footage whose
    catalogue title happens to mention the subject.
    """
    if not works:
        raise SourcePoolError("no observed works were supplied")
    candidates: list[dict[str, Any]] = []
    for work in works:
        frames = work.get("frames") or []
        if not any(str(frame.get("describes") or "").strip() for frame in frames):
            continue
        duration = float(work.get("measured_duration_seconds") or 0)
        for start, end in plan_windows(duration, MAX_WINDOWS_PER_SOURCE, window_seconds):
            candidates.append({
                "candidate_id": work["candidate_id"],
                "title": work.get("title", ""),
                "selected_asset_page_url": work.get("selected_asset_page_url"),
                "direct_download_url": work.get("direct_download_url"),
                "width": work.get("width"),
                "height": work.get("height"),
                "measured_duration_seconds": duration,
                "shot_start_seconds": start,
                "shot_end_seconds": end,
                "seen": window_terms(frames, start, end),
            })
    if not candidates:
        raise SourcePoolError(
            "none of the supplied works carried a frame description; the vision "
            "pass must say what each numbered frame shows")

    result = plan_by_content(beats, candidates, match_floor=match_floor)
    plan = result["plan"]
    required = min(MIN_DISTINCT_SOURCES, len(beats))
    if result["unmatched_beats"]:
        raise SourcePoolError(
            f"no observed footage matches beats {result['unmatched_beats']}; every "
            f"window scored below {match_floor}. Search for the subject those beats "
            f"describe, or rewrite them to something the footage can show")
    if result["distinct_sources"] < required:
        raise SourcePoolError(
            f"the matching footage came from only {result['distinct_sources']} works, "
            f"below the {required} the production contract requires")
    validate_source_diversity(plan)
    return {
        "beats": len(plan),
        "distinct_sources": result["distinct_sources"],
        "window_seconds": window_seconds,
        "weakest_match": result["weakest_match"],
        "match_floor": match_floor,
        "beat_plan": plan,
        "assignment_policy": (
            "Every interval was cut inside a measured length and every pairing was "
            "scored against frames taken from the clip itself. Copy the URLs and "
            "intervals character for character."),
    }
