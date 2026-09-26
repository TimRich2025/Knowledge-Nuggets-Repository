from __future__ import annotations

import unittest

from .production_contract import (
    MAX_SHOT_SECONDS,
    MIN_SOURCE_SHOT_SECONDS,
    source_window_error,
    validate_scene_contract,
)


def scene(start: float, end: float) -> dict:
    return {
        "shot_start_seconds": start,
        "shot_end_seconds": end,
        "plain_language": True,
        "spoken_phrase": "engines build thrust before release",
        "caption_beats": ["engines build", "thrust before", "release"],
    }


class ShotBoundTests(unittest.TestCase):
    """A window at the documented limit must be accepted by every check."""

    def test_binary_floating_point_overshoots_the_written_limit(self) -> None:
        # The defect this guards: 8.4 - 6.0 is not 2.4 but a hair above it.
        self.assertGreater(8.4 - 6.0, MAX_SHOT_SECONDS)

    def test_a_window_at_the_limit_is_accepted_on_ingest(self) -> None:
        self.assertIsNone(source_window_error(8.4 - 6.0))

    def test_a_window_at_the_lower_limit_is_accepted_on_ingest(self) -> None:
        self.assertIsNone(source_window_error(7.5 - 6.0))

    def test_a_window_beyond_the_limit_is_still_rejected(self) -> None:
        self.assertIsNotNone(source_window_error(MAX_SHOT_SECONDS + 0.2))
        self.assertIsNotNone(source_window_error(MIN_SOURCE_SHOT_SECONDS - 0.2))

    def test_ingest_and_submission_contract_agree_at_the_limit(self) -> None:
        """The defect was a window /jobs accepted and the ingest then refused."""
        for start, end in ((6.0, 8.4), (8.4, 10.8), (10.8, 13.2), (13.2, 15.6)):
            with self.subTest(start=start, end=end):
                validate_scene_contract(scene(start, end), 1)
                self.assertIsNone(source_window_error(end - start))

    def test_every_grid_window_of_a_full_short_is_accepted(self) -> None:
        start = 6.0
        for index in range(18):
            end = round(start + MAX_SHOT_SECONDS, 10)
            with self.subTest(shot=index + 1):
                self.assertIsNone(source_window_error(end - start))
            start = end


if __name__ == "__main__":
    unittest.main()
