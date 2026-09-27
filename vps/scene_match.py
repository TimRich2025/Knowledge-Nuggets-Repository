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
# What the vision pass is told to write when a tile is not a picture of
# anything. These windows are dropped rather than scored.
SLATE = re.compile(r"\b(title|logo)\s+card\b|\b(black|blurred)\s+frame\b"
                   r"|\bcolou?r\s+bars\b|\bslate\b", re.I)


def stem(word: str) -> str:
    """Enough normalisation that 'rockets' and 'rocket' are the same thing.

    Not a real stemmer, and it does not need to be: both sides of every
    comparison run through it, so it only has to be consistent. What it does
    have to get right are the words this footage is described in, and the
    earlier version got three of them wrong. "flames" became "flam" while
    "flame" stayed whole, "launch pads" never met "launch pad" because a
    four-letter plural was left alone, and "gripping" became "gripp" while
    "grips" became "grip".
    """
    if len(word) > 5 and word.endswith("ing"):
        cut = word[:-3]
        # English doubles the consonant before -ing.
        if len(cut) > 3 and cut[-1] == cut[-2] and cut[-1] not in "aeiou":
            cut = cut[:-1]
        return cut
    if len(word) > 5 and word.endswith(("ted", "ded")):
        # Only the ending, not the consonant before it, so "mounted" and
        # "mounts" both come out as "mount".
        return word[:-2]
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("ses", "xes", "zes", "ches", "shes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def terms(text: object) -> set[str]:
    """The visually meaningful words of a phrase, normalised."""
    # Hyphens separate. A brief writes "hold-down clamps" and a description
    # writes "hold down clamps"; kept together they never match each other.
    words = re.findall(r"[a-zA-Z][a-zA-Z']*", str(text or "").lower())
    return {stem(word) for word in words if word not in STOPWORDS and len(word) > 2}


def required_items(beat: dict[str, Any]) -> list[set[str]]:
    """Each thing the beat insists on, as its own set of words.

    A must_show entry is one thing to put on screen, however many words the
    brief spent naming it. Pooling their words and asking what fraction of the
    pool a window matched punished the brief for being descriptive: three
    entries reading "Stationary rocket", "Launch pad or support structure" and
    "Engine activity or exhaust" become nine required words, and real footage of
    a rocket lifting off a launch pad matched three of them and scored 0.25
    against a floor of 0.34. It was refused for showing exactly what was asked.
    Counted as things rather than words, that same window satisfies two entries
    of three.
    """
    return [found for item in beat.get("must_show") or [] if (found := terms(item))]


def item_is_shown(item: set[str], seen: set[str]) -> bool:
    """Whether one required thing is on screen.

    A short name has to be there in full. "rocket base" is not satisfied by a
    rocket, and "hold down" is not satisfied by holding: it was footage of a
    rocket already high in the sky, passed off against a beat about clamps at
    the pad, that this module was written to stop. A longer entry may be met by
    half its words, because past two or three words a brief is describing
    rather than naming.
    """
    return len(item & seen) >= (len(item) if len(item) <= 2 else math.ceil(len(item) / 2))


def beat_requirements(beat: dict[str, Any]) -> tuple[set[str], set[str]]:
    """Every required word, and the ones that only break ties.

    visual_target is the fuller sentence around the requirement and counts for
    less, because it carries framing words the footage cannot own.
    """
    required: set[str] = set()
    for item in required_items(beat):
        required |= item
    preferred = terms(beat.get("visual_target")) | terms(beat.get("spoken_phrase"))
    return required, preferred - required


def is_footage(described: object) -> bool:
    """Whether a described frame is a picture of something, or a caption.

    The vision pass is told to write exactly "title card", "logo card", "black
    frame" or "blurred frame" when a tile is one of those, and a measured run
    came back with four of one clip's five tiles reading "title card". They are
    not footage: a window resting on them has nothing to offer a beat, and
    cutting one into a Short puts a NASA slate in the middle of a sentence. So
    a tile that names one of them contributes nothing, even when it goes on to
    describe the graphic, because the graphic is still not the subject.
    """
    body = str(described or "").strip()
    return bool(body) and not SLATE.search(body)


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
    # A neighbouring tile may stand in for a window that no sample landed in,
    # but it may not rescue one that landed on a slate: that window really does
    # show the slate, and borrowing the next picture along would hide it.
    if not any(is_footage(frames[index].get("describes")) for index in inside):
        return set()
    lowest = max(0, min(inside) - NEIGHBOUR_FRAMES)
    highest = min(len(frames) - 1, max(inside) + NEIGHBOUR_FRAMES)
    seen: set[str] = set()
    for frame in frames[lowest: highest + 1]:
        if is_footage(frame.get("describes")):
            seen |= terms(frame.get("describes"))
    return seen


def match_score(beat: dict[str, Any], seen: set[str]) -> float:
    """How well observed footage satisfies one beat, between 0 and 1.

    Required elements dominate: a window that shows none of them scores near
    zero however much else it has in common. The preferred terms break ties
    between windows that all satisfy the requirement. What is counted is how
    many of the beat's must_show entries are on screen, not how many of their
    words, so a brief is not punished for naming a thing in four words.
    """
    required, preferred = beat_requirements(beat)
    if not seen:
        return 0.0
    items = required_items(beat)
    if items:
        met = sum(1 for item in items if item_is_shown(item, seen)) / len(items)
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


def suggested_queries(beats: list[dict[str, Any]], unmatched: list[int],
                      limit: int = 4) -> list[str]:
    """What to go looking for so the beats nothing matched can be served.

    A failed match is only useful if it says what is missing, and what is
    missing is written in the beats themselves. Their must_show entries are
    already noun phrases, so they are trimmed to a searchable two words rather
    than shredded into tokens and recombined: pairing the ranked words of
    several unrelated beats produced "base control", which asks for nothing.
    """
    seen: Counter = Counter()
    for position in unmatched:
        if not 1 <= position <= len(beats):
            continue
        for phrase in beats[position - 1].get("must_show") or []:
            words = [stem(word) for word in re.findall(r"[a-zA-Z][a-zA-Z']*", str(phrase).lower())
                     if word not in STOPWORDS and word not in GENERIC_SUBJECTS and len(word) > 2]
            if len(words) >= 2:
                seen[" ".join(words[:2])] += 1
            elif words:
                seen[words[0]] += 1
    # Sorted rather than most_common: a set's iteration order changes with the
    # interpreter's hash seed, and a retry that differs run to run cannot be
    # reasoned about.
    ranked = sorted(seen.items(), key=lambda pair: (-pair[1], pair[0]))
    return [phrase for phrase, _ in ranked[:limit]]


# Words too broad to narrow a catalogue search on their own. They are still
# scored against; they just make a poor query.
GENERIC_SUBJECTS = frozenset({"vehicle", "hardware", "structure", "area", "place",
                              "thing", "object", "system", "equipment", "surrounding"})


def _neighbour_conflict(chosen, windows, position, source) -> bool:
    """True when taking this source would put too many neighbours together."""
    run = 1
    for step in (-1, 1):
        cursor = position + step
        while cursor in chosen and windows[chosen[cursor][0]]["candidate_id"] == source:
            run += 1
            cursor += step
    return run > MAX_CONSECUTIVE_SCENES_PER_SOURCE
