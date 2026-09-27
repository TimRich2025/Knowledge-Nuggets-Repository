from __future__ import annotations

import unittest

from .production_contract import (MAX_CONSECUTIVE_SCENES_PER_SOURCE,
                                  MIN_DISTINCT_SOURCES, scene_source_key,
                                  validate_source_diversity)


def page(asset: str) -> str:
    return f"https://images.nasa.gov/details/{asset}"


def media(asset: str) -> str:
    return f"https://images-assets.nasa.gov/video/{asset}/{asset}~large.mp4"


def spread(assets: list[str]) -> list[dict]:
    """One scene per entry, in the order the Short would play them."""
    return [{"selected_asset_page_url": page(asset), "direct_download_url": media(asset)}
            for asset in assets]


# Eighteen beats over six works, never more than two in a row from one of them.
GOOD = ["A", "A", "B", "C", "C", "D", "B", "E", "E", "F", "A", "D",
        "C", "F", "B", "E", "D", "F"]


class SourceDiversityTests(unittest.TestCase):
    def test_a_well_spread_eighteen_beat_short_passes(self) -> None:
        validate_source_diversity(spread(GOOD))

    def test_one_clip_for_the_whole_short_is_rejected(self) -> None:
        """The exact shape of every Short uploaded before this rule existed."""
        with self.assertRaisesRegex(ValueError, "at least 5 distinct video sources"):
            validate_source_diversity(spread(["A"] * 18))

    def test_four_sources_is_one_short_of_the_floor(self) -> None:
        assets = ["A", "B", "C", "D"] * 4 + ["A", "B"]
        with self.assertRaisesRegex(ValueError, "found 4"):
            validate_source_diversity(spread(assets))

    def test_five_sources_with_one_dominant_clip_is_rejected(self) -> None:
        """One long take plus four cameos satisfies the count but not the intent."""
        assets = ["A", "B", "A", "C", "A", "D", "A", "E", "A", "B",
                  "A", "C", "A", "D", "A", "E", "A", "B"]
        with self.assertRaisesRegex(ValueError, "share limit"):
            validate_source_diversity(spread(assets))

    def test_three_neighbouring_beats_from_one_clip_are_rejected(self) -> None:
        assets = ["A", "A", "A", "B", "C", "D", "E", "F", "B", "C",
                  "D", "E", "F", "B", "C", "D", "E", "F"]
        with self.assertRaisesRegex(ValueError, "consecutive scenes"):
            validate_source_diversity(spread(assets))

    def test_two_neighbouring_beats_from_one_clip_are_allowed(self) -> None:
        self.assertEqual(MAX_CONSECUTIVE_SCENES_PER_SOURCE, 2)
        validate_source_diversity(spread(GOOD))

    def test_the_page_and_the_media_url_are_the_same_source(self) -> None:
        """Otherwise one clip could be cited eighteen ways and counted as many."""
        scenes = [{"selected_asset_page_url": page("A")}, {"direct_download_url": media("A")}]
        self.assertEqual(scene_source_key(scenes[0]), scene_source_key(scenes[1]))

    def test_a_scene_without_any_source_url_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "source URL is required"):
            validate_source_diversity(spread(GOOD)[:-1] + [{}])

    def test_a_short_job_only_needs_as_many_sources_as_it_has_scenes(self) -> None:
        """A two-scene smoke job must not be blocked by an eighteen-beat rule."""
        validate_source_diversity(spread(["A", "B"]))

    def test_the_floor_is_the_five_sources_the_brief_asks_for(self) -> None:
        self.assertEqual(MIN_DISTINCT_SOURCES, 5)

    def test_a_non_nasa_source_is_still_counted_by_its_url(self) -> None:
        scenes = [{"source_url": "https://upload.wikimedia.org/x/Tide.webm?download"},
                  {"source_url": "https://upload.wikimedia.org/x/tide.webm"}]
        self.assertEqual(scene_source_key(scenes[0]), scene_source_key(scenes[1]))


if __name__ == "__main__":
    unittest.main()
