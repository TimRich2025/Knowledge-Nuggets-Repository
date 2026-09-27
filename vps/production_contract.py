"""Hard production gates for every Knowledge Nuggets preview.

The rules in this module deliberately fail closed.  A preview is not a place
to compensate for vague writing, synthetic timing or a merely related video.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any


# The narration is spoken as one passage and the visual cuts follow its word
# boundaries, so a beat lasts as long as its sentence does rather than being
# stretched into a fixed slot. A six-word beat runs about two seconds; the
# ceiling leaves room for a slower one without letting a shot outstay a cut.
MAX_SHOT_SECONDS = 4.0
MIN_SHOT_SECONDS = 0.6
# The shortest source window the ingest can cut a usable segment from.
MIN_SOURCE_SHOT_SECONDS = 1.5
# How far one encoded segment may miss its target duration.
SEGMENT_DURATION_TOLERANCE = 0.08
# The renderer's fixed output frame rate; one frame is the smallest cut a
# segment boundary can land on.
TIMELINE_FPS = 30.0
# An interval written as exactly 2.4s measures 2.4000000000000004 in binary
# floating point.  Every bound check shares this tolerance so a value at the
# documented limit is accepted everywhere, not only by whichever check is
# written most loosely.
SHOT_BOUND_TOLERANCE = 0.001
# A Short cut entirely from one clip reads as a single long take with jump
# cuts in it, however many beats it is divided into.  Five distinct works is
# the production floor; a job with fewer scenes than that can only offer as
# many sources as it has scenes.
MIN_DISTINCT_SOURCES = 5
# The floor alone would be satisfied by one dominant clip plus four cameos, so
# no single source may carry more than a third of the beats.
MAX_SOURCE_SHARE = 1.0 / 3.0
# Two neighbouring beats from one work read as a cut inside a scene.  A third
# reads as no cut at all, which is the monotony the floor exists to prevent.
MAX_CONSECUTIVE_SCENES_PER_SOURCE = 2
MAX_WORDS_PER_EXPLANATION = 11
MAX_WORDS_PER_CAPTION = 4
NATURAL_MALE_EDGE_VOICES = {
    "en-US-AndrewMultilingualNeural",
    "en-US-ChristopherNeural",
}


# Both the catalogue page and the media file carry the same NASA asset id, so
# two beats citing one work through different URLs must not count as two
# sources.
_NASA_ASSET_ID = re.compile(r"images(?:-assets)?\.nasa\.gov/(?:details|video|asset)/([^/?#]+)", re.I)
_SOURCE_URL_FIELDS = (
    "selected_asset_page_url",
    "source_page_url",
    "source_url",
    "direct_download_url",
)


def scene_source_key(scene: dict[str, Any]) -> str:
    """Identify the work a beat was cut from, not the file it was fetched as."""
    urls = [str(scene.get(field) or "").strip() for field in _SOURCE_URL_FIELDS]
    for url in urls:
        match = _NASA_ASSET_ID.search(url)
        if match:
            return f"nasa:{match.group(1).lower()}"
    for url in urls:
        if url:
            return url.split("?")[0].rstrip("/").lower()
    return ""


def validate_source_diversity(scenes: list[dict[str, Any]]) -> None:
    """Require a Short to be cut from several different works, well spread.

    Three rules, because each one alone is trivially satisfied by footage that
    still looks like one clip: enough distinct works, no dominant one, and no
    run of neighbouring beats long enough to read as an uncut take.
    """
    keys = [scene_source_key(scene) for scene in scenes]
    for number, key in enumerate(keys, 1):
        if not key:
            raise _fail(number, "a source URL is required before footage variety can be counted")
    if not keys:
        return
    distinct = set(keys)
    required = min(MIN_DISTINCT_SOURCES, len(keys))
    if len(distinct) < required:
        raise ValueError(
            f"production contract requires at least {required} distinct video sources "
            f"across {len(keys)} scenes, found {len(distinct)}: {', '.join(sorted(distinct))}"
        )
    cap = max(1, math.ceil(len(keys) * MAX_SOURCE_SHARE))
    source, used = Counter(keys).most_common(1)[0]
    if used > cap:
        raise ValueError(
            f"one source carries {used} of {len(keys)} scenes, above the {cap}-scene share limit: {source}"
        )
    run = 1
    for position, (previous, key) in enumerate(zip(keys, keys[1:]), 2):
        run = run + 1 if key == previous else 1
        if run > MAX_CONSECUTIVE_SCENES_PER_SOURCE:
            raise _fail(
                position,
                f"{run} consecutive scenes come from {key}; at most "
                f"{MAX_CONSECUTIVE_SCENES_PER_SOURCE} neighbouring beats may share one source",
            )


def _words(value: object) -> list[str]:
    return re.findall(r"[A-Za-z0-9']+", str(value or "").lower())


def _fail(scene_number: int | str, message: str) -> ValueError:
    return ValueError(f"scene {scene_number}: {message}")


def concat_duration_tolerance(durations: list[float]) -> float:
    """How far the joined track may drift from the sum of its scenes.

    Every segment's length is rounded to whole frames twice, once when it is
    cut and once when the track is joined, so the drift grows with the number
    of scenes.  Budget a frame per scene.  The allowance is then held below
    half the SHORTEST SCENE ACTUALLY PRESENT, not below the theoretical
    minimum, so a dropped scene can never hide inside it while ordinary
    rounding still passes.
    """
    scenes = [float(value) for value in durations if float(value) > 0]
    if not scenes:
        return 0.12
    frame_budget = max(0.12, len(scenes) / TIMELINE_FPS)
    return min(frame_budget, 0.5 * min(scenes))


def source_window_error(length: float) -> str | None:
    """Return why a source window is unusable, or None when it is fine.

    The ingest cuts the approved window before rendering, so it needs a longer
    span than a single spoken beat does.  Both bounds carry the shared
    tolerance, otherwise an interval at the documented limit passes the
    submission contract and is then rejected on ingest.
    """
    if length < MIN_SOURCE_SHOT_SECONDS - SHOT_BOUND_TOLERANCE:
        return f"verified shot interval must be at least {MIN_SOURCE_SHOT_SECONDS:.1f} seconds"
    if length > MAX_SHOT_SECONDS + SHOT_BOUND_TOLERANCE:
        return f"verified shot exceeds the {MAX_SHOT_SECONDS:.1f}s production limit"
    return None


def validate_submission_contract(job: dict[str, Any]) -> None:
    """Reject an incomplete or non-natural production request before queuing it."""
    if str(job.get("tts_provider") or "").upper() != "EDGE":
        raise ValueError("production contract requires EDGE neural narration")
    voice = str(job.get("tts_voice") or "en-US-AndrewMultilingualNeural")
    if voice not in NATURAL_MALE_EDGE_VOICES:
        allowed = ", ".join(sorted(NATURAL_MALE_EDGE_VOICES))
        raise ValueError(f"production contract requires one approved natural male voice: {allowed}")
    if job.get("audio_url") or job.get("audio_base64") or job.get("scene_audio_base64"):
        raise ValueError("production contract forbids unverified supplied audio")
    rate = str(job.get("tts_rate") or "+8%")
    match = re.fullmatch(r"([+-])(\d{1,2})%", rate)
    if not match or int(match.group(2)) > 12:
        raise ValueError("production contract requires a natural EDGE speaking rate between -12% and +12%")
    scenes = list(job.get("scenes") or [])
    for number, scene in enumerate(scenes, 1):
        validate_scene_contract(scene, number)
    validate_source_diversity(scenes)


def validate_scene_contract(scene: dict[str, Any], number: int | str) -> None:
    """Validate the writing and source interval for one explanatory beat."""
    phrase = str(scene.get("spoken_phrase") or "").strip()
    words = _words(phrase)
    shot_duration = float(scene.get("shot_end_seconds", 0)) - float(scene.get("shot_start_seconds", 0))
    if shot_duration < MIN_SHOT_SECONDS - SHOT_BOUND_TOLERANCE or shot_duration > MAX_SHOT_SECONDS + SHOT_BOUND_TOLERANCE:
        raise _fail(number, f"verified shot must be between {MIN_SHOT_SECONDS:.1f}s and {MAX_SHOT_SECONDS:.1f}s")
    if scene.get("plain_language") is not True:
        raise _fail(number, "plain_language must be true")
    if not 2 <= len(words) <= MAX_WORDS_PER_EXPLANATION:
        raise _fail(number, f"spoken_phrase must contain 2-{MAX_WORDS_PER_EXPLANATION} plain words")
    if len(re.findall(r"[.!?]", phrase)) > 1 or re.search(r"[;:]", phrase):
        raise _fail(number, "spoken_phrase must explain one short sentence only")
    beats = scene.get("caption_beats")
    if not isinstance(beats, list) or not beats:
        raise _fail(number, "tight caption_beats are required")
    caption_words: list[str] = []
    for beat in beats:
        beat_words = _words(beat)
        if not 1 <= len(beat_words) <= MAX_WORDS_PER_CAPTION:
            raise _fail(number, f"each caption beat must contain 1-{MAX_WORDS_PER_CAPTION} words")
        caption_words.extend(beat_words)
    if caption_words != words:
        raise _fail(number, "caption words must exactly match the spoken phrase")


def validate_measured_render_contract(scenes: list[dict[str, Any]]) -> None:
    """Require measured speech and word-boundary captions immediately before render."""
    validate_source_diversity(scenes)
    for number, scene in enumerate(scenes, 1):
        validate_scene_contract(scene, number)
        try:
            speech_start = float(scene["speech_start_seconds"])
            speech_end = float(scene["speech_end_seconds"])
        except (KeyError, TypeError, ValueError) as exc:
            raise _fail(number, "measured speech interval is required") from exc
        duration = speech_end - speech_start
        if duration < MIN_SHOT_SECONDS - SHOT_BOUND_TOLERANCE or duration > MAX_SHOT_SECONDS + SHOT_BOUND_TOLERANCE:
            raise _fail(number, f"measured speech beat must be between {MIN_SHOT_SECONDS:.1f}s and {MAX_SHOT_SECONDS:.1f}s")
        timings = scene.get("caption_timings")
        if not isinstance(timings, list) or not timings:
            raise _fail(number, "measured word-boundary caption timings are required")
        previous_end = 0.0
        caption_words: list[str] = []
        for cue in timings:
            try:
                start = float(cue["start_seconds"])
                end = float(cue["end_seconds"])
                text = str(cue["text"])
            except (KeyError, TypeError, ValueError) as exc:
                raise _fail(number, "invalid measured caption timing") from exc
            if start < previous_end - 0.02 or end <= start or end > duration + 0.03:
                raise _fail(number, "caption timing must be ordered and inside its spoken beat")
            cue_words = _words(text)
            if not 1 <= len(cue_words) <= MAX_WORDS_PER_CAPTION:
                raise _fail(number, f"each measured caption must contain 1-{MAX_WORDS_PER_CAPTION} words")
            caption_words.extend(cue_words)
            previous_end = end
        if caption_words != _words(scene.get("spoken_phrase")):
            raise _fail(number, "measured captions must cover every spoken word exactly once")
