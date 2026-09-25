"""Live, topic-safe YouTube metadata for Knowledge Nuggets Shorts.

This module deliberately does not promise that a hashtag will make a Short
viral.  It uses YouTube's own recent, high-view search results as a live
signal, keeps only topic-related tags, and always leaves a useful fallback
when the live API is unavailable.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
import math
import os
import re
from typing import Any

import requests


YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
HASHTAG_RE = re.compile(r"(?<!\w)#([A-Za-z][A-Za-z0-9_]{1,48})")
WORD_RE = re.compile(r"[A-Za-z0-9]+")
STOP_WORDS = {
    "a", "an", "and", "are", "at", "by", "does", "do", "for", "from", "how",
    "in", "is", "of", "on", "or", "the", "to", "what", "why", "with",
}
GENERIC_RELEVANT_TAGS = {
    "science", "spacescience", "physics", "astronomy", "space", "nasa",
    "microgravity", "earthscience", "learnontiktok", "education",
}
BLOCKED_TAGS = {"fyp", "foryou", "viral", "trending", "follow", "subscribe", "like"}


class MetadataError(RuntimeError):
    pass


def _words(text: str) -> list[str]:
    return [word.lower() for word in WORD_RE.findall(text) if word.lower() not in STOP_WORDS]


def _camel_hashtag(words: list[str]) -> str:
    return "#" + "".join(word[:1].upper() + word[1:] for word in words[:5])


def _normalise_hashtag(value: str) -> str:
    return "#" + re.sub(r"[^A-Za-z0-9_]", "", value.lstrip("#"))


def _tag_is_relevant(tag: str, topic_words: set[str]) -> bool:
    flat = tag.lstrip("#").lower().replace("_", "")
    if flat in BLOCKED_TAGS or len(flat) < 3:
        return False
    if flat in GENERIC_RELEVANT_TAGS:
        return True
    return any(word in flat for word in topic_words if len(word) >= 3)


def _fallback_tags(topic: str) -> list[str]:
    words = _words(topic)
    topic_tag = _camel_hashtag(words) if words else "#ScienceFacts"
    tags = [topic_tag]
    joined = " ".join(words)
    if any(word in joined for word in ("space", "astronaut", "orbit", "gravity", "water")):
        tags.extend(["#SpaceScience", "#Microgravity"])
    else:
        tags.append("#Science")
    tags.append("#Shorts")
    return list(dict.fromkeys(tags))[:5]


def _fact_from_script(script: str) -> str:
    compact = " ".join(script.split())
    if not compact:
        return "science gets stranger when you look closely."
    return compact[:420].rsplit(" ", 1)[0].rstrip(".,;:!") + "."


def _description(fact_statement: str, hashtags: list[str]) -> str:
    fact = _fact_from_script(fact_statement)
    if fact.lower().startswith("but the fact is"):
        fact = re.sub(r"^but the fact is[,:]?\s*", "", fact, flags=re.I)
    return f"But the fact is, {fact}\n\n{' '.join(hashtags)}"


def _youtube_items(topic: str, api_key: str, region: str) -> list[dict[str, Any]]:
    published_after = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat().replace("+00:00", "Z")
    try:
        search = requests.get(
            YOUTUBE_SEARCH_URL,
            params={
                "part": "snippet",
                "q": f"{topic} shorts",
                "type": "video",
                "videoDuration": "short",
                "order": "viewCount",
                "publishedAfter": published_after,
                "regionCode": region,
                "relevanceLanguage": "en",
                "maxResults": 25,
                "key": api_key,
            },
            timeout=(5, 15),
        )
        search.raise_for_status()
        ids = [str(item.get("id", {}).get("videoId") or "") for item in search.json().get("items", [])]
        ids = [video_id for video_id in ids if video_id]
        if not ids:
            return []
        videos = requests.get(
            YOUTUBE_VIDEOS_URL,
            params={"part": "snippet,statistics", "id": ",".join(ids), "key": api_key},
            timeout=(5, 15),
        )
        videos.raise_for_status()
        return list(videos.json().get("items", []))
    except requests.RequestException as exc:
        raise MetadataError(f"live YouTube trend lookup failed: {exc}") from exc


def _rank_live_hashtags(topic: str, api_key: str, region: str) -> list[str]:
    topic_words = set(_words(topic))
    scores: defaultdict[str, float] = defaultdict(float)
    for item in _youtube_items(topic, api_key, region):
        snippet = item.get("snippet") or {}
        title = str(snippet.get("title") or "")
        description = str(snippet.get("description") or "")
        views = int((item.get("statistics") or {}).get("viewCount") or 0)
        reach = max(1.0, math.log10(max(10, views)))
        for source, multiplier in ((title, 3.0), (description, 1.0)):
            for raw_tag in HASHTAG_RE.findall(source):
                tag = _normalise_hashtag(raw_tag)
                if _tag_is_relevant(tag, topic_words):
                    scores[tag] += reach * multiplier
    return [tag for tag, _ in sorted(scores.items(), key=lambda pair: (-pair[1], pair[0]))]


def build_social_metadata(
    topic: str,
    fact_statement: str = "",
    *,
    api_key: str | None = None,
    region: str | None = None,
) -> dict[str, Any]:
    """Return a compact, publish-ready description and up to five safe hashtags."""
    normalized_topic = " ".join(topic.split())
    if len(normalized_topic) < 3:
        raise MetadataError("topic must contain at least three characters")
    configured_key = api_key if api_key is not None else os.getenv("KN_YOUTUBE_DATA_API_KEY", "")
    configured_region = (region or os.getenv("KN_YOUTUBE_TREND_REGION", "US")).upper()
    fallback = _fallback_tags(normalized_topic)
    live_tags: list[str] = []
    source_status = "TOPIC_FALLBACK"
    live_error = "YouTube Data API key is not configured"
    if configured_key:
        try:
            live_tags = _rank_live_hashtags(normalized_topic, configured_key, configured_region)
            source_status = "LIVE_YOUTUBE"
            live_error = ""
        except MetadataError as exc:
            live_error = str(exc)

    selected: list[str] = []
    for tag in [*live_tags, *fallback]:
        if tag not in selected:
            selected.append(tag)
        if len(selected) == 5:
            break
    if "#Shorts" not in selected:
        selected = (selected[:4] + ["#Shorts"])
    return {
        "topic": normalized_topic,
        "description": _description(fact_statement, selected),
        "hashtags": selected,
        "trend_source": source_status,
        "trend_region": configured_region,
        "live_lookup_error": live_error or None,
        "policy": "Use this result per Short. It is live-ranked when the YouTube API is configured; no algorithm can guarantee virality.",
    }
