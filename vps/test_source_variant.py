from __future__ import annotations

import unittest
from unittest.mock import patch

from .source_catalog import (DEFAULT_EARLIEST_YEAR, MAX_MEASUREMENTS_PER_SEARCH,
                             _asset_video_urls, search_nasa_video_candidates)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def resolve(links: list[str]):
    with patch("vps.source_catalog._SESSION.get", return_value=FakeResponse(links)):
        return _asset_video_urls("https://images-assets.nasa.gov/video/x/collection.json")


BASE = "https://images-assets.nasa.gov/video/ksc_102004_pegasus/ksc_102004_pegasus"


class VideoVariantTests(unittest.TestCase):
    """An asset with no original must fall back to large, never to preview."""

    def test_the_original_wins_when_it_exists(self) -> None:
        original, _, _ = resolve([f"{BASE}~preview.mp4", f"{BASE}~orig.mp4", f"{BASE}~large.mp4"])
        self.assertEqual(original, f"{BASE}~orig.mp4")

    def test_large_wins_when_there_is_no_original(self) -> None:
        """The 320x212 preview that failed a whole render was chosen this way."""
        original, _, _ = resolve([f"{BASE}~preview.mp4", f"{BASE}~small.mp4", f"{BASE}~large.mp4"])
        self.assertEqual(original, f"{BASE}~large.mp4")

    def test_a_shorter_url_never_beats_a_bigger_variant(self) -> None:
        original, _, _ = resolve([f"{BASE}~small.mp4", f"{BASE}~medium.mp4"])
        self.assertEqual(original, f"{BASE}~medium.mp4")

    def test_a_preview_is_the_last_resort_not_the_first(self) -> None:
        original, _, _ = resolve([f"{BASE}~preview.mp4"])
        self.assertEqual(original, f"{BASE}~preview.mp4")

    def test_a_listing_without_video_yields_nothing(self) -> None:
        original, _, _ = resolve([f"{BASE}~large.jpg"])
        self.assertIsNone(original)

    def test_the_review_proxy_still_prefers_the_smallest(self) -> None:
        """Vision reviews a cheap copy; the render never uses it."""
        _, review, _ = resolve([f"{BASE}~orig.mp4", f"{BASE}~preview.mp4"])
        self.assertEqual(review, f"{BASE}~preview.mp4")


def item(nasa_id: str) -> dict:
    return {"href": f"https://images-assets.nasa.gov/video/{nasa_id}/collection.json",
            "data": [{"nasa_id": nasa_id, "title": nasa_id}],
            "links": [{"href": f"https://images-assets.nasa.gov/video/{nasa_id}/{nasa_id}~large.jpg"}]}


class CatalogueQueryTests(unittest.TestCase):
    """The year filter is a preference. It must never starve the search."""

    def _run(self, pages: list[list[dict]]):
        calls: list[dict] = []

        def get(url, params=None, timeout=None):
            calls.append(dict(params or {}))
            page = pages[min(len(calls) - 1, len(pages) - 1)]
            return FakeResponse({"collection": {"items": page}})

        with patch("vps.source_catalog._SESSION.get", side_effect=get):
            with patch("vps.source_catalog._asset_video_urls",
                       return_value=(f"{BASE}~orig.mp4", f"{BASE}~preview.mp4", [])):
                with patch("vps.source_catalog._asset_metadata",
                           return_value={"metadata_url": "", "source_width": 1920,
                                         "source_height": 1080, "source_duration": "0:01:00"}):
                    found = search_nasa_video_candidates("rocket launch", 5)
        return calls, found

    def test_the_first_page_asks_for_hd_era_assets(self) -> None:
        calls, _ = self._run([[item(f"A{n}") for n in range(20)]])
        self.assertEqual(calls[0]["year_start"], str(DEFAULT_EARLIEST_YEAR))

    def test_a_full_page_is_not_retried_unfiltered(self) -> None:
        calls, _ = self._run([[item(f"A{n}") for n in range(20)]])
        self.assertEqual(len(calls), 1)

    def test_a_nearly_empty_page_falls_back_to_the_whole_catalogue(self) -> None:
        """One candidate from three queries is how this failure actually looked."""
        calls, found = self._run([[item("A0")], [item(f"B{n}") for n in range(12)]])
        self.assertEqual(len(calls), 2)
        self.assertNotIn("year_start", calls[1])
        self.assertEqual(len(found), 5)

    def test_the_fallback_does_not_repeat_a_work(self) -> None:
        calls, found = self._run([[item("A0")], [item("A0"), item("B1"), item("B2")]])
        ids = [c["candidate_id"] for c in found]
        self.assertEqual(len(ids), len(set(ids)))

    def test_the_page_is_wide_enough_to_filter_from(self) -> None:
        calls, _ = self._run([[item(f"A{n}") for n in range(20)]])
        self.assertGreaterEqual(int(calls[0]["page_size"]), 40)

    def test_only_video_is_requested(self) -> None:
        calls, _ = self._run([[item(f"A{n}") for n in range(20)]])
        self.assertEqual(calls[0]["media_type"], "video")


class SubHdSetAsideTests(unittest.TestCase):
    """A sub-HD work must not occupy a slot a usable work could have taken."""

    def _search(self, sizes: list[tuple[int, int]]):
        pages = [[item(f"A{n}") for n in range(len(sizes))]]
        calls: list[dict] = []
        metadata = iter([{"metadata_url": "", "source_width": w, "source_height": h,
                          "source_duration": "0:01:00"} for w, h in sizes] * 4)

        def get(url, params=None, timeout=None):
            calls.append(dict(params or {}))
            return FakeResponse({"collection": {"items": pages[0]}})

        with patch("vps.source_catalog._SESSION.get", side_effect=get):
            with patch("vps.source_catalog._asset_video_urls",
                       return_value=(f"{BASE}~orig.mp4", f"{BASE}~preview.mp4", [])):
                with patch("vps.source_catalog._asset_metadata", side_effect=lambda url: next(metadata)):
                    return search_nasa_video_candidates("rocket launch", 3)

    def test_sub_hd_works_are_skipped_while_hd_ones_remain(self) -> None:
        found = self._search([(320, 212), (320, 212), (1920, 1080), (3840, 2160), (1920, 1080)])
        self.assertEqual(len(found), 3)
        for candidate in found:
            self.assertGreaterEqual(candidate["source_width"], 1920)

    def test_sub_hd_works_are_returned_when_nothing_else_exists(self) -> None:
        """An empty list hides the reason; a rejected candidate states it."""
        found = self._search([(320, 212), (640, 480)])
        self.assertEqual(len(found), 2)
        self.assertTrue(all(c["technical_status"] == "REJECT_BELOW_FHD" for c in found))


if __name__ == "__main__":
    unittest.main()


class SilentMetadataTests(unittest.TestCase):
    """Most NASA video assets publish no metadata.json. Measure, do not assume."""

    def _search(self, measured: list[tuple[int, int]], limit: int = 3):
        pages = [[item(f"A{n}") for n in range(len(measured))]]
        sizes = iter(measured)
        reads: list[str] = []

        def measure(url):
            reads.append(url)
            width, height = next(sizes)
            return 60.0, width, height

        def get(url, params=None, timeout=None):
            return FakeResponse({"collection": {"items": pages[0]}})

        with patch("vps.source_catalog._SESSION.get", side_effect=get):
            with patch("vps.source_catalog._asset_video_urls",
                       return_value=(f"{BASE}~orig.mp4", f"{BASE}~preview.mp4", [])):
                with patch("vps.source_catalog._asset_metadata",
                           return_value={"metadata_url": "", "source_width": 0,
                                         "source_height": 0, "source_duration": ""}):
                    found = search_nasa_video_candidates("rocket launch", limit, measure=measure)
        return found, reads

    def test_a_silent_entry_is_measured_and_its_size_recorded(self) -> None:
        found, reads = self._search([(1920, 1080)], limit=1)
        self.assertEqual(len(reads), 1)
        self.assertEqual(found[0]["source_width"], 1920)
        self.assertEqual(found[0]["technical_status"], "ELIGIBLE_FHD_OR_HIGHER")

    def test_a_measured_sub_hd_work_does_not_occupy_a_slot(self) -> None:
        """Nine of ten candidates measured 320x212 and filled every slot."""
        found, _ = self._search([(320, 212), (320, 212), (1920, 1080), (3840, 2160)], limit=2)
        self.assertEqual(len(found), 2)
        for candidate in found:
            self.assertGreaterEqual(candidate["source_width"], 1920)

    def test_measuring_stops_before_it_eats_the_request_budget(self) -> None:
        found, reads = self._search([(320, 212)] * 30, limit=5)
        self.assertLessEqual(len(reads), MAX_MEASUREMENTS_PER_SEARCH)

    def test_an_unmeasurable_entry_stays_unverified_rather_than_eligible(self) -> None:
        found, _ = self._search([(0, 0)], limit=1)
        self.assertEqual(found[0]["technical_status"], "UNVERIFIED_TECHNICAL_METADATA")
