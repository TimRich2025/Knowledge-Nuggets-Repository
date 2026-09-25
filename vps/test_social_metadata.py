from __future__ import annotations

import unittest
from unittest.mock import patch

from .social_metadata import build_social_metadata


class SocialMetadataTests(unittest.TestCase):
    def test_description_always_starts_with_required_opening(self) -> None:
        result = build_social_metadata(
            "why water forms spheres in space",
            "surface tension pulls the droplet into its smallest shape",
        )
        self.assertTrue(result["description"].startswith("But the fact is,"))
        self.assertIn("#Shorts", result["hashtags"])
        self.assertLessEqual(len(result["hashtags"]), 5)
        self.assertEqual(result["trend_source"], "TOPIC_FALLBACK")

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
