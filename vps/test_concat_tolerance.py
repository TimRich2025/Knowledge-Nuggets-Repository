from __future__ import annotations

import unittest

from .production_contract import (
    SEGMENT_DURATION_TOLERANCE,
    TIMELINE_FPS,
    concat_duration_tolerance,
)


class ConcatToleranceTests(unittest.TestCase):
    """The joined track drifts more the more scenes it is built from."""

    def test_the_allowance_grows_with_the_scene_count(self) -> None:
        self.assertGreater(
            concat_duration_tolerance([2.0] * 18),
            concat_duration_tolerance([2.0] * 6),
        )

    def test_an_eighteen_scene_short_survives_real_measured_drift(self) -> None:
        """The defect: 18 scenes drifted 0.501s and a 0.300s bound rejected them."""
        self.assertGreaterEqual(concat_duration_tolerance([1.76] * 18), 0.501)

    def test_one_frame_per_scene_is_the_budget(self) -> None:
        scenes = [2.0] * 12
        self.assertAlmostEqual(
            concat_duration_tolerance(scenes), len(scenes) / TIMELINE_FPS
        )

    def test_a_dropped_scene_is_always_still_caught(self) -> None:
        """A lost scene costs its own length, which must exceed the allowance."""
        for scenes in ([2.3] * 6, [1.76] * 18, [2.0] * 40, [1.5] * 200):
            with self.subTest(scenes=len(scenes)):
                self.assertLess(concat_duration_tolerance(scenes), min(scenes))

    def test_the_shortest_scene_caps_the_allowance(self) -> None:
        """A short scene must not be able to hide inside the rounding budget."""
        mixed = [1.76] * 17 + [0.7]
        self.assertLess(concat_duration_tolerance(mixed), 0.7)
        self.assertLess(concat_duration_tolerance(mixed), concat_duration_tolerance([1.76] * 18))

    def test_a_degenerate_input_is_handled(self) -> None:
        self.assertGreater(concat_duration_tolerance([]), 0)
        self.assertGreater(concat_duration_tolerance([0.0, 0.0]), 0)

    def test_per_segment_tolerance_is_the_stated_one(self) -> None:
        self.assertAlmostEqual(SEGMENT_DURATION_TOLERANCE, 0.08)


if __name__ == "__main__":
    unittest.main()
