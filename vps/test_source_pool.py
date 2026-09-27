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

    def __init__(self, results: dict[str, list[str]], duration: float = 90.0,
                 width: int = 1920, height: int = 1080) -> None:
        self.results = results
        self.duration = duration
        self.width = width
        self.height = height
        self.queries: list[str] = []

    def search(self, query: str, limit: int) -> list[dict]:
        self.queries.append(query)
        return [candidate(asset) for asset in self.results.get(query, [])][:limit]

    def measure(self, url: str) -> tuple[float, int, int]:
        return self.duration, self.width, self.height


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

    def test_published_figures_are_preferred_over_a_header_read(self) -> None:
        fake = FakeCatalogue(CATALOGUE)
        published = {**CATALOGUE}
        reads: list[str] = []

        def search(query, limit):
            return [{**candidate(asset), "source_duration": "0:01:30",
                     "source_width": 1920, "source_height": 1080}
                    for asset in published.get(query, [])][:limit]

        def measure(url):
            reads.append(url)
            return 90.0, 1920, 1080

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
        from .production_contract import MAX_SHOT_SECONDS, MIN_SOURCE_SHOT_SECONDS
        pool, _ = self._pool()
        for beat in pool["beat_plan"]:
            span = beat["shot_end_seconds"] - beat["shot_start_seconds"]
            self.assertGreaterEqual(span, MIN_SOURCE_SHOT_SECONDS)
            self.assertLessEqual(span, MAX_SHOT_SECONDS)

    def test_a_window_is_wider_than_the_beat_it_must_hold(self) -> None:
        """A slower sentence must still fit the shot it was given."""
        pool, _ = self._pool()
        for beat in pool["beat_plan"]:
            self.assertGreaterEqual(beat["shot_end_seconds"] - beat["shot_start_seconds"], 3.0)

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


class CataloguePageTests(unittest.TestCase):
    """The page URL must be a page, not the preview image the search lists first."""

    def test_a_nasa_work_gets_its_details_page(self) -> None:
        from .source_pool import catalogue_page_url
        found = candidate("KSC-20190914-RV-ILW01_0001")
        found["source_family"] = "NASA Images"
        found["catalog_page_url"] = ("https://images-assets.nasa.gov/video/KSC-20190914-RV-ILW01_0001/"
                                     "KSC-20190914-RV-ILW01_0001~large.jpg")
        self.assertEqual(catalogue_page_url(found),
                         "https://images.nasa.gov/details/KSC-20190914-RV-ILW01_0001")

    def test_an_image_link_is_never_returned_as_a_page(self) -> None:
        from .source_pool import catalogue_page_url
        found = candidate("OTHER")
        found["source_family"] = "Wikimedia Commons"
        found["catalog_page_url"] = "https://upload.wikimedia.org/x/Tide~large.jpg"
        found["asset_listing_url"] = "https://commons.wikimedia.org/wiki/File:Tide.webm"
        self.assertEqual(catalogue_page_url(found),
                         "https://commons.wikimedia.org/wiki/File:Tide.webm")

    def test_the_pool_publishes_the_page_not_the_thumbnail(self) -> None:
        fake = FakeCatalogue(CATALOGUE)

        def search(query, limit):
            return [{**candidate(asset), "source_family": "NASA Images",
                     "catalog_page_url": f"https://images-assets.nasa.gov/video/{asset}/{asset}~large.jpg"}
                    for asset in CATALOGUE.get(query, [])][:limit]

        pool = build_source_pool(SEGMENTS, search=search, measure=fake.measure)
        for beat in pool["beat_plan"]:
            self.assertTrue(beat["selected_asset_page_url"].startswith("https://images.nasa.gov/details/"))


class WideningTests(unittest.TestCase):
    """A script named too precisely must not cost the whole production."""

    NARROW = {"ignition": ["SATURN1"], "liftoff": ["APOLLO1"], "ascent": ["SHUTTLE1"]}
    BROAD = {"rocket launch": ["GEN1", "GEN2"], "rocket ascent": ["GEN3", "GEN4"]}

    def _catalogue(self):
        return FakeCatalogue({**self.NARROW, **self.BROAD})

    def test_three_narrow_queries_alone_fail_with_advice(self) -> None:
        fake = self._catalogue()
        with self.assertRaisesRegex(SourcePoolError, "search for the subject instead"):
            build_source_pool(SEGMENTS, search=fake.search, measure=fake.measure)

    def test_broader_terms_rescue_the_run(self) -> None:
        fake = self._catalogue()
        pool = build_source_pool(SEGMENTS, fallback_queries=["rocket launch", "rocket ascent"],
                                 search=fake.search, measure=fake.measure)
        validate_source_diversity(pool["beat_plan"])
        self.assertEqual(pool["distinct_sources"], 7)

    def test_widening_is_skipped_when_the_floor_is_already_met(self) -> None:
        fake = FakeCatalogue({**CATALOGUE, **self.BROAD})
        build_source_pool(SEGMENTS, fallback_queries=["rocket launch"],
                          search=fake.search, measure=fake.measure)
        self.assertNotIn("rocket launch", fake.queries)

    def test_a_work_already_found_is_not_added_twice(self) -> None:
        fake = FakeCatalogue({**self.NARROW, "rocket launch": ["SATURN1", "GEN1", "GEN2", "GEN3"]})
        pool = build_source_pool(SEGMENTS, fallback_queries=["rocket launch"],
                                 search=fake.search, measure=fake.measure)
        assets = [source["candidate_id"] for source in pool["sources"]]
        self.assertEqual(len(assets), len(set(assets)))


class FullHdGateTests(unittest.TestCase):
    """A 1630x1080 clip passed discovery once and failed the render. Never again."""

    def test_a_clip_below_full_hd_is_not_offered(self) -> None:
        from .source_pool import is_full_hd
        self.assertFalse(is_full_hd(1630, 1080))
        self.assertTrue(is_full_hd(1920, 1080))
        self.assertTrue(is_full_hd(1080, 1920))
        self.assertTrue(is_full_hd(3840, 2160))

    def test_an_unmeasurable_clip_is_dropped_rather_than_assumed(self) -> None:
        def search(query, limit):
            return [{**candidate(asset), "source_width": 0, "source_height": 0}
                    for asset in CATALOGUE.get(query, [])][:limit]

        with self.assertRaises(SourcePoolError):
            build_source_pool(SEGMENTS, search=search, measure=lambda url: (90.0, 0, 0))

    def test_a_clip_the_catalogue_calls_sub_hd_is_never_probed(self) -> None:
        reads: list[str] = []

        def search(query, limit):
            return [{**candidate(asset), "technical_status": "REJECT_BELOW_FHD"}
                    for asset in CATALOGUE.get(query, [])][:limit]

        def measure(url):
            reads.append(url)
            return 90.0, 1920, 1080

        with self.assertRaises(SourcePoolError):
            build_source_pool(SEGMENTS, search=search, measure=measure)
        self.assertEqual(reads, [])

    def test_a_catalogue_without_dimensions_is_measured(self) -> None:
        """The failure came from a work whose metadata.json was missing."""
        reads: list[str] = []

        def search(query, limit):
            return [{**candidate(asset), "source_width": 0, "source_height": 0,
                     "technical_status": "UNVERIFIED_TECHNICAL_METADATA"}
                    for asset in CATALOGUE.get(query, [])][:limit]

        def measure(url):
            reads.append(url)
            return 90.0, 1920, 1080

        pool = build_source_pool(SEGMENTS, search=search, measure=measure)
        self.assertTrue(reads)
        for source in pool["sources"]:
            self.assertGreaterEqual(source["width"], 1920)

    def test_the_measured_size_replaces_a_wrong_published_one(self) -> None:
        def search(query, limit):
            return [{**candidate(asset), "source_width": 0, "source_height": 0}
                    for asset in CATALOGUE.get(query, [])][:limit]

        def measure(url):
            return 90.0, 3840, 2160

        pool = build_source_pool(SEGMENTS, search=search, measure=measure)
        self.assertTrue(all(source["width"] == 3840 for source in pool["sources"]))


class RejectionReportingTests(unittest.TestCase):
    """A short pool must say what it threw away, or nobody can widen the search."""

    def test_the_error_names_the_reason_and_an_example_size(self) -> None:
        def search(query, limit):
            return [{**candidate(asset), "source_width": 1630, "source_height": 1080}
                    for asset in CATALOGUE.get(query, [])][:limit]

        with self.assertRaises(SourcePoolError) as caught:
            build_source_pool(SEGMENTS, search=search, measure=lambda url: (90.0, 1630, 1080))
        message = str(caught.exception)
        self.assertIn("below Full HD", message)
        self.assertIn("1630x1080", message)

    def test_a_short_clip_is_reported_as_short_not_as_small(self) -> None:
        def search(query, limit):
            return [{**candidate(asset), "source_duration": "0:00:04"}
                    for asset in CATALOGUE.get(query, [])][:limit]

        with self.assertRaises(SourcePoolError) as caught:
            build_source_pool(SEGMENTS, search=search, measure=lambda url: (4.0, 1920, 1080))
        self.assertIn("shorter than", str(caught.exception))


class CandidateAccountingTests(unittest.TestCase):
    """A short pool must account for every candidate the searches returned."""

    def test_the_error_reports_how_many_candidates_were_offered(self) -> None:
        def search(query, limit):
            return [{**candidate(asset), "source_width": 1630, "source_height": 1080}
                    for asset in CATALOGUE.get(query, [])][:limit]

        with self.assertRaises(SourcePoolError) as caught:
            build_source_pool(SEGMENTS, search=search, measure=lambda url: (90.0, 1630, 1080))
        self.assertIn("the searches offered 8 candidates", str(caught.exception))

    def test_an_empty_catalogue_is_distinguishable_from_a_filtered_one(self) -> None:
        with self.assertRaises(SourcePoolError) as caught:
            build_source_pool(SEGMENTS, search=lambda q, n: [],
                              measure=lambda url: (90.0, 1920, 1080))
        message = str(caught.exception)
        self.assertIn("offered 0 candidates", message)
        self.assertIn("none were dropped by a gate", message)

    def test_a_candidate_without_a_video_file_is_counted(self) -> None:
        def search(query, limit):
            return [{**candidate(asset), "direct_download_url": ""}
                    for asset in CATALOGUE.get(query, [])][:limit]

        with self.assertRaises(SourcePoolError) as caught:
            build_source_pool(SEGMENTS, search=search, measure=lambda url: (90.0, 1920, 1080))
        self.assertIn("no direct video file", str(caught.exception))
