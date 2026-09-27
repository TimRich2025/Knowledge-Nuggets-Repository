from __future__ import annotations

import unittest
from unittest.mock import patch

from .source_catalog import (DEFAULT_EARLIEST_YEAR, _asset_video_urls,
                             search_nasa_video_candidates)


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


class CatalogueQueryTests(unittest.TestCase):
    """Standard-definition archive material can never pass the render gate."""

    def _params(self) -> dict:
        captured: dict = {}

        def get(url, params=None, timeout=None):
            captured.update(params or {})
            return FakeResponse({"collection": {"items": []}})

        with patch("vps.source_catalog._SESSION.get", side_effect=get):
            search_nasa_video_candidates("rocket launch", 5)
        return captured

    def test_the_search_asks_only_for_hd_era_assets(self) -> None:
        self.assertEqual(self._params()["year_start"], str(DEFAULT_EARLIEST_YEAR))

    def test_the_page_is_wide_enough_to_filter_from(self) -> None:
        """Most results are discarded, so a narrow page leaves nothing behind."""
        self.assertGreaterEqual(int(self._params()["page_size"]), 40)

    def test_only_video_is_requested(self) -> None:
        self.assertEqual(self._params()["media_type"], "video")


if __name__ == "__main__":
    unittest.main()
