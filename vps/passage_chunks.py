from __future__ import annotations

import re


MAX_PASSAGE_CHARS = 280


def passage_chunks(text: str, max_chars: int = MAX_PASSAGE_CHARS) -> list[str]:
    """Split only at natural sentence boundaries to cap inference memory.

    The final WAV remains one independent narration track. This split is
    unrelated to the visual scene plan, so picture cuts cannot restart the
    voice. Two or three sentences normally stay together as one passage.
    """
    normalized = " ".join(str(text or "").split())
    if not normalized:
        return []
    sentences = re.split(r"(?<=[.!?])\s+", normalized)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) > max_chars:
            for word in sentence.split():
                candidate = f"{current} {word}".strip()
                if current and len(candidate) > max_chars:
                    chunks.append(current)
                    current = word
                else:
                    current = candidate
            continue
        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks
