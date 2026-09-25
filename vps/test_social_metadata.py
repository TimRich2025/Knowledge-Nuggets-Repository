from __future__ import annotations

import unittest
from unittest.mock import patch

from .social_metadata import build_social_metadata


class SocialMetadataTests(unittest.TestCase):
    def test_title_is_the_literal_start_of_the_required_description_opening(self) -> None:
        result = build_social_metadata(
            "why water forms spheres in space",
            "surface tension pulls the droplet into its smallest shape",
        )
        self.assertTrue(result["title"].startswith("but the fact is,"))
        self.assertTrue(result["description"].startswith(result["title"]))
        self.assertLessEqual(len(result["title"]), 100)
        self.assertIn("#Shorts", result["hashtags"])
        self.assertLessEqual(len(result["hashtags"]), 5)
        self.assertEqual(result["trend_source"], "TOPIC_FALLBACK")

    def test_long_opening_is_bounded_without_breaking_the_title_description_match(self) -> None:
        result = build_social_metadata(
            "water in space",
            "surface tension pulls every water molecule toward the center, creating a perfectly round floating sphere in microgravity.",
        )
        self.assertLessEqual(len(result["title"]), 100)
        self.assertTrue(result["description"].startswith(result["title"]))

    @patch("vps.social_metadata._youtube_items")
    def test_live_hashtags_are_topic_filtered_and_ranked(self, items) -> None:
        items.return_value = [
            {
                "snippet": {"title": "Water in space #Microgravity #SpaceScience #FYP", "description": ""},
                "statistics": {"viewCount": "8000000"},
            },
            {
                "snippet": {"title": "Why water floats #SpaceScience", "description": "#WaterInSpace"},
                "statistics": {"viewCount": "1000000"},
            },
        ]
        result = build_social_metadata("water in space", "surface tension wins", api_key="test-key")
        self.assertEqual(result["trend_source"], "LIVE_YOUTUBE")
        self.assertIn("#Microgravity", result["hashtags"])
        self.assertNotIn("#FYP", result["hashtags"])


if __name__ == "__main__":
    unittest.main()
