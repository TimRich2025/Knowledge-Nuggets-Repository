from __future__ import annotations

import unittest

from .source_cache import estimated_word_cues


class ContinuousFallbackTimingTest(unittest.TestCase):
    def test_cues_cover_exact_words_in_order(self):
        script = "One bright idea, explained clearly. Then the story keeps moving!"
        cues = estimated_word_cues(script, 8.0)
        self.assertEqual(
            [cue["text"] for cue in cues],
            ["one", "bright", "idea", "explained", "clearly", "then", "the", "story", "keeps", "moving"],
        )
        self.assertEqual(cues[0]["start"], 0.0)
        self.assertAlmostEqual(cues[-1]["end"], 8.0)
        self.assertTrue(all(earlier["start"] < later["start"] for earlier, later in zip(cues, cues[1:])))

    def test_sentence_pause_receives_more_time(self):
        cues = estimated_word_cues("Fast. Still moving", 4.0)
        fast_span = cues[1]["start"] - cues[0]["start"]
        still_span = cues[2]["start"] - cues[1]["start"]
        self.assertGreater(fast_span, still_span)


if __name__ == "__main__":
    unittest.main()
