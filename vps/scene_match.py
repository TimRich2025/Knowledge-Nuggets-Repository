"""Match a spoken beat to footage that was actually looked at.

Until now a beat was paired with a clip on the strength of the clip's catalogue
title. A title says what a work is about; it does not say what is on screen at
second fourteen. So a beat about hold-down clamps could be given a wide shot of
an empty sky and nothing in the chain would notice, because nothing in the chain
had seen the picture.

This module works from observed frames instead: real stills pulled from the clip
at known times and described by a vision pass. A window is scored on what its
own frames were seen to contain, a beat is scored against what it says it needs,
and the assignment is the best pairing that still satisfies the footage-variety
contract. A beat that nothing matches is reported as unmatched rather than
quietly given the least bad option.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Any

from .production_contract import (MAX_CONSECUTIVE_SCENES_PER_SOURCE,
                                  MAX_SOURCE_SHARE, MIN_DISTINCT_SOURCES)

# Words that carry no visual meaning. Without this a beat matches any window
# that happens to contain "the" or "a" in its description.
STOPWORDS = frozenset("""
a an and are as at be been before being below beneath between both but by can
could did do does down during each for from further had has have having he her
here hers him his how i if in into is it its itself just me more most my no nor
not of off on once only or other our out over own same she should so some such
than that the their them then there these they this those through to too under
until up very was we were what when where which while who whom why will with you
your visible shows showing shown seen view shot footage frame frames clip video
image picture camera scene appears appear
""".split())
# A description that only repeats one word is not evidence of a match.
MIN_TERMS_FOR_A_MATCH = 2
# Below this a pairing is a guess. Measured on real manifests: a genuine match
# scores well above it, a wrong one rarely reaches it.
MATCH_FLOOR = 0.34
# A window is scored on the frames inside it plus one on each side, because a
# 3.2s window rarely lands exactly on a sample.
NEIGHBOUR_FRAMES = 1


def stem(word: str) -> str:
    """Enough normalisation that 'rockets' and 'rocket' are the same thing."""
    for suffix in ("ing", "ted", "ded", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def terms(text: object) -> set[str]:
    """The visually meaningful words of a phrase, normalised."""
    # Hyphens separate. A brief writes "hold-down clamps" and a description
    # writes "hold down clamps"; kept together they never match each other.
    words = re.findall(r"[a-zA-Z][a-zA-Z']*", str(text or "").lower())
    return {stem(word) for word in words if word not in STOPWORDS and len(word) > 2}


def beat_requirements(beat: dict[str, Any]) -> tuple[set[str], set[str]]:
    """What a beat insists on, and what it would merely like.

    must_show is the contract with the viewer: name a clamp and a clamp had
    better be on screen. visual_target is the fuller sentence around it and
    counts for less, because it carries framing words the footage cannot own.
    """
    required: set[str] = set()
    for item in beat.get("must_show") or []:
        required |= terms(item)
    preferred = terms(beat.get("visual_target")) | terms(beat.get("spoken_phrase"))
    return required, preferred - required


def window_terms(frames: list[dict[str, Any]], start: float, end: float) -> set[str]:
    """Everything the vision pass saw inside this window, and just outside it."""
    inside = [index for index, frame in enumerate(frames)
              if start - 0.001 <= float(frame.get("at_seconds", -1)) <= end + 0.001]
    if not inside:
        # No sample landed in the window; take the nearest one on each side.
        ordered = sorted(range(len(frames)),
                         key=lambda index: abs(float(frames[index].get("at_seconds", 0))
                                               - (start + end) / 2))
        inside = ordered[:1]
    lowest = max(0, min(inside) - NEIGHBOUR_FRAMES)
    highest = min(len(frames) - 1, max(inside) + NEIGHBOUR_FRAMES)
    seen: set[str] = set()
    for frame in frames[lowest: highest + 1]:
        seen |= terms(frame.get("describes"))
    return seen


def match_score(beat: dict[str, Any], seen: set[str]) -> float:
    """How well observed footage satisfies one beat, between 0 and 1.

    Required elements dominate: a window that shows none of them scores near
    zero however much else it has in common. The preferred terms break ties
    between windows that all satisfy the requirement.
    """
    required, preferred = beat_requirements(beat)
    if not seen:
        return 0.0
    if required:
        met = len(required & seen) / len(required)
    else:
        met = 1.0 if preferred & seen else 0.0
    extra = len(preferred & seen) / len(preferred) if preferred else 0.0
    if len(required & seen) + len(preferred & seen) < MIN_TERMS_FOR_A_MATCH:
        met = min(met, 0.5)
    return round(0.75 * met + 0.25 * extra, 4)


def plan_by_content(
    beats: list[dict[str, Any]],
    windows: list[dict[str, Any]],
    match_floor: float = MATCH_FLOOR,
) -> dict[str, Any]:
    """Give every beat the best-matching window the variety contract allows.

    Beats are served hardest first: the one with the fewest acceptable windows
    chooses before the one with many, so a beat with a single possible piece of
    footage is not left with nothing because an easier beat took it.
    """
    if not beats:
        raise ValueError("no beats to plan")
    if not windows:
        raise ValueError("no observed windows to choose from")

    scored: dict[int, list[tuple[float, int]]] = {}
    for position, beat in enumerate(beats):
        options = []
        for index, window in enumerate(windows):
            value = match_score(beat, window["seen"])
            if value >= match_floor:
                options.append((value, index))
        options.sort(key=lambda pair: (-pair[0], pair[1]))
        scored[position] = options

    share_cap = max(1, math.ceil(len(beats) * MAX_SOURCE_SHARE))
    used_windows: set[int] = set()
    per_source: Counter = Counter()
    chosen: dict[int, tuple[int, float]] = {}

    for position in sorted(scored, key=lambda pos: (len(scored[pos]), pos)):
        allowed = [(value, index) for value, index in scored[position]
                   if index not in used_windows
                   and per_source[windows[index]["candidate_id"]] < share_cap
                   and not _neighbour_conflict(chosen, windows, position,
                                               windows[index]["candidate_id"])]
        if not allowed:
            continue
        # Score decides. Where two windows fit a beat equally well, the work
        # that has not been used yet wins, because five clips that each appear
        # once read as a cut Short and two that appear three times do not.
        value, index = min(allowed, key=lambda pair: (-pair[0],
                                                      per_source[windows[pair[1]]["candidate_id"]],
                                                      pair[1]))
        chosen[position] = (index, value)
        used_windows.add(index)
        per_source[windows[index]["candidate_id"]] += 1

    plan: list[dict[str, Any]] = []
    unmatched: list[int] = []
    for position, beat in enumerate(beats):
        if position not in chosen:
            unmatched.append(position + 1)
            continue
        index, value = chosen[position]
        window = windows[index]
        plan.append({**{key: value for key, value in window.items() if key != "seen"},
                     "beat": position + 1,
                     "match_score": value,
                     "matched_terms": sorted((beat_requirements(beat)[0] | beat_requirements(beat)[1])
                                             & window["seen"])})
    return {
        "plan": plan,
        "unmatched_beats": unmatched,
        "distinct_sources": len({entry["candidate_id"] for entry in plan}),
        "match_floor": match_floor,
        "weakest_match": min((entry["match_score"] for entry in plan), default=0.0),
    }


def _neighbour_conflict(chosen, windows, position, source) -> bool:
    """True when taking this source would put too many neighbours together."""
    run = 1
    for step in (-1, 1):
        cursor = position + step
        while cursor in chosen and windows[chosen[cursor][0]]["candidate_id"] == source:
            run += 1
            cursor += step
    return run > MAX_CONSECUTIVE_SCENES_PER_SOURCE
