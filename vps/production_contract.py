"""Hard production gates for every Knowledge Nuggets preview.

The rules in this module deliberately fail closed.  A preview is not a place
to compensate for vague writing, synthetic timing or a merely related video.
"""
from __future__ import annotations

import re
from typing import Any


MAX_SHOT_SECONDS = 2.4
MIN_SHOT_SECONDS = 0.6
# The shortest source window the ingest can cut a usable segment from.
MIN_SOURCE_SHOT_SECONDS = 1.5
# An interval written as exactly 2.4s measures 2.4000000000000004 in binary
# floating point.  Every bound check shares this tolerance so a value at the
# documented limit is accepted everywhere, not only by whichever check is
# written most loosely.
SHOT_BOUND_TOLERANCE = 0.001
MAX_WORDS_PER_EXPLANATION = 11
MAX_WORDS_PER_CAPTION = 4
NATURAL_MALE_EDGE_VOICES = {
    "en-US-AndrewMultilingualNeural",
    "en-US-ChristopherNeural",
}


def _words(value: object) -> list[str]:
    return re.findall(r"[A-Za-z0-9']+", str(value or "").lower())


def _fail(scene_number: int | str, message: str) -> ValueError:
    return ValueError(f"scene {scene_number}: {message}")


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
    for number, scene in enumerate(job.get("scenes") or [], 1):
        validate_scene_contract(scene, number)


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
