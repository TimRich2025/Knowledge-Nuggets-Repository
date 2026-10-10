from __future__ import annotations

import unittest

from .production_contract import validate_measured_render_contract
from .source_cache import IngestError, split_narration_at_word_boundaries


def reading(phrases: list[str], word_seconds: float = 0.35,
            pause_seconds: float = 0.30) -> tuple[list[dict], float]:
    """One continuous reading: words in a row, a real pause between sentences."""
    spoken: list[dict] = []
    clock = 0.12
    for position, phrase in enumerate(phrases):
        if position:
            clock += pause_seconds
        for word in phrase.lower().split():
            spoken.append({"word": word.strip(".,"), "start": round(clock, 4),
                           "end": round(clock + word_seconds, 4)})
            clock += word_seconds
    return spoken, round(clock + 0.20, 4)


PHRASES = ["Rocket stands on its launch pad.",
           "Engines ignite beneath the waiting rocket.",
           "The rocket climbs past the tower."]


class BeatSplittingTests(unittest.TestCase):
    """The visual cuts follow the speech, not the other way round."""

    def _split(self, phrases=PHRASES, **kwargs):
        spoken, total = reading(phrases, **kwargs)
        return split_narration_at_word_boundaries(phrases, spoken, total), total

    def test_the_beats_tile_the_whole_narration(self) -> None:
        (timings, _), total = self._split()
        self.assertEqual(timings[0]["speech_start_seconds"], 0.0)
        self.assertAlmostEqual(timings[-1]["speech_end_seconds"], total, places=3)
        for earlier, later in zip(timings, timings[1:]):
            self.assertEqual(earlier["speech_end_seconds"], later["speech_start_seconds"])

    def test_a_cut_lands_in_the_pause_not_on_a_word(self) -> None:
        """Half a pause of air on each side is what keeps a cut from clipping."""
        spoken, total = reading(PHRASES)
        timings, _ = split_narration_at_word_boundaries(PHRASES, spoken, total)
        first_sentence_words = len(PHRASES[0].split())
        last_word_end = spoken[first_sentence_words - 1]["end"]
        next_word_start = spoken[first_sentence_words]["start"]
        boundary = timings[0]["speech_end_seconds"]
        self.assertGreater(boundary, last_word_end)
        self.assertLess(boundary, next_word_start)

    def test_every_caption_stays_inside_its_own_beat(self) -> None:
        (timings, captions), _ = self._split()
        for timing, cues in zip(timings, captions):
            duration = timing["speech_end_seconds"] - timing["speech_start_seconds"]
            for cue in cues:
                self.assertGreaterEqual(cue["start_seconds"], 0.0)
                self.assertLessEqual(cue["end_seconds"], duration + 0.001)

    def test_the_captions_carry_every_spoken_word_in_order(self) -> None:
        (_, captions), _ = self._split()
        spoken_words = [w.strip(".,").upper() for phrase in PHRASES for w in phrase.split()]
        self.assertEqual([cue["text"] for cues in captions for cue in cues], spoken_words)

    def test_the_result_satisfies_the_render_contract(self) -> None:
        (timings, captions), _ = self._split()
        scenes = []
        for phrase, timing, cues in zip(PHRASES, timings, captions):
            scenes.append({
                "spoken_phrase": phrase, "plain_language": True,
                "caption_beats": [" ".join(chunk) for chunk in
                                  (phrase.split()[i:i + 3] for i in range(0, len(phrase.split()), 3))],
                "shot_start_seconds": 4.0, "shot_end_seconds": 7.2,
                "selected_asset_page_url": f"https://images.nasa.gov/details/W{len(scenes)}",
                **timing, "caption_timings": cues,
            })
        validate_measured_render_contract(scenes)

    def test_a_script_the_voice_did_not_read_is_rejected(self) -> None:
        spoken, total = reading(PHRASES)
        with self.assertRaisesRegex(IngestError, "differ from the spoken script"):
            split_narration_at_word_boundaries(
                ["Rocket stands on its launch pad.", "Something else entirely here now.",
                 "The rocket climbs past the tower."], spoken, total)

    def test_a_beat_too_short_to_cut_on_is_rejected(self) -> None:
        with self.assertRaisesRegex(IngestError, "give it more words"):
            self._split(phrases=["Go.", "Now.", "Up."], word_seconds=0.12, pause_seconds=0.05)

    def test_a_trailing_word_the_script_does_not_own_is_rejected(self) -> None:
        spoken, total = reading(PHRASES)
        spoken.append({"word": "extra", "start": total - 0.3, "end": total - 0.1})
        with self.assertRaisesRegex(IngestError, "more words than the script"):
            split_narration_at_word_boundaries(PHRASES, spoken, total)

if __name__ == "__main__":
    unittest.main()
