from __future__ import annotations

import unittest

from .production_contract import validate_source_diversity
from .source_pool import (DEFAULT_WINDOW_SECONDS, LEAD_IN_SECONDS,
                          MAX_SOURCES_PER_SEGMENT, SourcePoolError,
                          TAIL_SECONDS, assign_beats, build_source_pool,
                          parse_catalogue_duration, plan_windows)


def candidate(asset: str) -> dict:
    return {
        "candidate_id": asset,
        "title": f"{asset} launch",
        "description": f"official footage {asset}",
        "keywords": [],
        "catalog_page_url": f"https://images.nasa.gov/details/{asset}",
        "asset_listing_url": f"https://images-assets.nasa.gov/video/{asset}/collection.json",
        "direct_download_url": f"https://images-assets.nasa.gov/video/{asset}/{asset}~large.mp4",
        "source_width": 1920,
        "source_height": 1080,
        "technical_status": "ELIGIBLE_FHD_OR_HIGHER",
    }


class FakeCatalogue:
    """Stands in for the NASA API so the rules can be tested without a network."""

    def __init__(self, results: dict[str, list[str]], duration: float = 90.0) -> None:
        self.results = results
        self.duration = duration
        self.queries: list[str] = []

    def search(self, query: str, limit: int) -> list[dict]:
        self.queries.append(query)
        return [candidate(asset) for asset in self.results.get(query, [])][:limit]

    def measure(self, url: str) -> float:
        return self.duration


SEGMENTS = [
    {"query": "ignition", "beats": 6},
    {"query": "liftoff", "beats": 4},
    {"query": "ascent", "beats": 8},
]
CATALOGUE = {
    "ignition": ["IGN1", "IGN2", "IGN3"],
    "liftoff": ["OFF1", "OFF2"],
    "ascent": ["ASC1", "ASC2", "ASC3"],
}


class WindowPlanningTests(unittest.TestCase):
    def test_windows_stay_inside_the_measured_clip(self) -> None:
        for start, end in plan_windows(60.0, 6):
            self.assertGreaterEqual(start, LEAD_IN_SECONDS)
            self.assertLessEqual(end, 60.0 - TAIL_SECONDS + 0.01)

    def test_windows_never_overlap(self) -> None:
        windows = plan_windows(60.0, 6)
        for (_, first_end), (second_start, _) in zip(windows, windows[1:]):
            self.assertGreaterEqual(second_start, first_end)

    def test_every_window_spans_the_requested_beat_length(self) -> None:
        for start, end in plan_windows(45.0, 5):
            self.assertAlmostEqual(end - start, DEFAULT_WINDOW_SECONDS, places=2)

    def test_a_clip_too_short_for_one_window_yields_none(self) -> None:
        self.assertEqual(plan_windows(1.4, 4), [])

    def test_a_clip_is_never_asked_for_more_windows_than_it_holds(self) -> None:
        """Ten windows do not fit in twelve seconds; the plan must not pretend."""
        windows = plan_windows(12.0, 10)
        self.assertLess(len(windows), 10)
        for (_, first_end), (second_start, _) in zip(windows, windows[1:]):
            self.assertGreaterEqual(second_start, first_end)


class CatalogueDurationTests(unittest.TestCase):
    """The published length saves a network round trip when it is readable."""

    def test_a_clock_string_is_read_as_seconds(self) -> None:
        self.assertAlmostEqual(parse_catalogue_duration("0:01:12"), 72.0)

    def test_a_plain_number_is_read_as_seconds(self) -> None:
        self.assertAlmostEqual(parse_catalogue_duration("47.5 s"), 47.5)

    def test_an_unreadable_value_falls_back_to_measuring(self) -> None:
        self.assertEqual(parse_catalogue_duration("unknown"), 0.0)
        self.assertEqual(parse_catalogue_duration(None), 0.0)

    def test_a_published_length_is_preferred_over_a_header_read(self) -> None:
        fake = FakeCatalogue(CATALOGUE)
        published = {**CATALOGUE}
        reads: list[str] = []

        def search(query, limit):
            return [{**candidate(asset), "source_duration": "0:01:30"}
                    for asset in published.get(query, [])][:limit]

        def measure(url):
            reads.append(url)
            return 90.0

        build_source_pool(SEGMENTS, search=search, measure=measure)
        self.assertEqual(reads, [])
        del fake


class BeatAssignmentTests(unittest.TestCase):
    def _pool(self, **kwargs):
        fake = FakeCatalogue(CATALOGUE, **kwargs)
        return build_source_pool(SEGMENTS, search=fake.search, measure=fake.measure), fake

    def test_an_eighteen_beat_plan_satisfies_the_diversity_contract(self) -> None:
        pool, _ = self._pool()
        self.assertEqual(pool["beats"], 18)
        validate_source_diversity(pool["beat_plan"])

    def test_the_plan_uses_every_work_it_discovered(self) -> None:
        pool, _ = self._pool()
        self.assertEqual(pool["distinct_sources"], 8)

    def test_a_segment_stops_probing_once_it_has_enough(self) -> None:
        """Each kept candidate costs a round trip, and Make's wait is bounded."""
        wide = {"ignition": [f"IGN{n}" for n in range(9)], "liftoff": ["OFF1", "OFF2"],
                "ascent": ["ASC1", "ASC2"]}
        fake = FakeCatalogue(wide)
        pool = build_source_pool(SEGMENTS, per_query=9, search=fake.search, measure=fake.measure)
        from_ignition = [s for s in pool["sources"] if s["query"] == "ignition"]
        self.assertEqual(len(from_ignition), MAX_SOURCES_PER_SEGMENT)

    def test_no_two_neighbouring_beats_share_a_clip(self) -> None:
        pool, _ = self._pool()
        assets = [beat["candidate_id"] for beat in pool["beat_plan"]]
        for first, second in zip(assets, assets[1:]):
            self.assertNotEqual(first, second)

    def test_a_beat_prefers_the_footage_its_own_narration_asked_for(self) -> None:
        pool, _ = self._pool()
        first_six = {beat["candidate_id"] for beat in pool["beat_plan"][:6]}
        self.assertTrue(first_six <= set(CATALOGUE["ignition"]))

    def test_two_beats_from_one_clip_show_different_moments(self) -> None:
        pool, _ = self._pool()
        seen: dict[str, set] = {}
        for beat in pool["beat_plan"]:
            window = (beat["shot_start_seconds"], beat["shot_end_seconds"])
            self.assertNotIn(window, seen.setdefault(beat["candidate_id"], set()))
            seen[beat["candidate_id"]].add(window)

    def test_every_interval_fits_the_renderer_ingest_window(self) -> None:
        pool, _ = self._pool()
        for beat in pool["beat_plan"]:
            span = beat["shot_end_seconds"] - beat["shot_start_seconds"]
            self.assertGreaterEqual(span, 1.5)
            self.assertLess(span, 2.4)

    def test_too_few_discovered_works_fails_loudly_here(self) -> None:
        """Better a named failure in discovery than a rejected job three steps on."""
        fake = FakeCatalogue({"ignition": ["ONE"], "liftoff": [], "ascent": []})
        with self.assertRaisesRegex(SourcePoolError, "below the 5"):
            build_source_pool(SEGMENTS, search=fake.search, measure=fake.measure)

    def test_an_empty_catalogue_says_so_rather_than_returning_nothing(self) -> None:
        fake = FakeCatalogue({})
        with self.assertRaisesRegex(SourcePoolError, "no usable source"):
            build_source_pool(SEGMENTS, search=fake.search, measure=fake.measure)

    def test_clips_too_short_to_cut_are_not_counted_as_sources(self) -> None:
        fake = FakeCatalogue(CATALOGUE, duration=3.0)
        with self.assertRaises(SourcePoolError):
            build_source_pool(SEGMENTS, search=fake.search, measure=fake.measure)

    def test_one_work_found_by_two_queries_is_used_once(self) -> None:
        overlapping = dict(CATALOGUE, liftoff=["IGN1", "OFF1", "OFF2"])
        fake = FakeCatalogue(overlapping)
        pool = build_source_pool(SEGMENTS, search=fake.search, measure=fake.measure)
        assets = [source["candidate_id"] for source in pool["sources"]]
        self.assertEqual(len(assets), len(set(assets)))

    def test_a_segment_with_one_clip_borrows_rather_than_repeating(self) -> None:
        """Otherwise a thin query would put two identical beats side by side."""
        thin = [{"query": "ignition", "beats": 2}, {"query": "liftoff", "beats": 16}]
        fake = FakeCatalogue({"ignition": ["IGN1", "IGN2", "IGN3", "IGN4", "IGN5"], "liftoff": ["OFF1"]})
        pool = build_source_pool(thin, search=fake.search, measure=fake.measure, max_per_segment=5)
        validate_source_diversity(pool["beat_plan"])
        carried = [beat["candidate_id"] for beat in pool["beat_plan"][2:]]
        self.assertGreater(len(set(carried)), 1)

    def test_a_short_clip_limits_how_often_it_can_be_reused(self) -> None:
        fake = FakeCatalogue(CATALOGUE, duration=20.0)
        pool = build_source_pool(SEGMENTS, search=fake.search, measure=fake.measure)
        validate_source_diversity(pool["beat_plan"])
        for beat in pool["beat_plan"]:
            self.assertLessEqual(beat["shot_end_seconds"], 20.0 - TAIL_SECONDS + 0.01)

    def test_footage_too_thin_for_the_beat_count_says_what_to_do(self) -> None:
        """Eight twelve-second clips hold sixteen windows, not eighteen."""
        fake = FakeCatalogue(CATALOGUE, duration=12.0)
        with self.assertRaisesRegex(SourcePoolError, "widen the search queries"):
            build_source_pool(SEGMENTS, search=fake.search, measure=fake.measure)


if __name__ == "__main__":
    unittest.main()
