from __future__ import annotations

import unittest

from .production_contract import (
    MIN_SHOT_SECONDS,
    SEGMENT_DURATION_TOLERANCE,
    concat_duration_tolerance,
)


class ConcatToleranceTests(unittest.TestCase):
    """The joined track drifts more the more scenes it is built from."""

    def test_a_short_film_keeps_the_original_allowance(self) -> None:
        self.assertAlmostEqual(concat_duration_tolerance(6), 0.12)

    def test_the_allowance_grows_with_the_scene_count(self) -> None:
        self.assertGreater(concat_duration_tolerance(18), concat_duration_tolerance(6))

    def test_a_dropped_scene_is_always_still_caught(self) -> None:
        """A lost scene costs at least MIN_SHOT_SECONDS, never within tolerance."""
        for count in (1, 6, 12, 18, 24, 40, 200):
            with self.subTest(scenes=count):
                self.assertLess(concat_duration_tolerance(count), MIN_SHOT_SECONDS)

    def test_the_allowance_never_runs_away(self) -> None:
        self.assertEqual(concat_duration_tolerance(40), concat_duration_tolerance(200))

    def test_an_eighteen_scene_short_survives_worst_case_rounding(self) -> None:
        """The defect: eighteen segments each a frame short failed a fixed 0.12s."""
        scenes = 18
        # Half a frame at 30fps per segment is ordinary encoder rounding.
        realistic_drift = scenes * (1 / 30) / 2
        self.assertLessEqual(realistic_drift, concat_duration_tolerance(scenes))

    def test_a_degenerate_scene_count_is_handled(self) -> None:
        self.assertGreater(concat_duration_tolerance(0), 0)

    def test_per_segment_tolerance_is_the_stated_one(self) -> None:
        self.assertAlmostEqual(SEGMENT_DURATION_TOLERANCE, 0.08)


if __name__ == "__main__":
    unittest.main()
