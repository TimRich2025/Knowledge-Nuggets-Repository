from __future__ import annotations

import copy
import unittest

from .production_contract import (MAX_SHOT_SECONDS, validate_measured_render_contract,
                                  validate_submission_contract)


SCENE = {
    "spoken_phrase": "Water pulls itself into a sphere.",
    "plain_language": True,
    "caption_beats": ["WATER PULLS", "ITSELF INTO", "A SPHERE"],
    "shot_start_seconds": 12.0,
    "shot_end_seconds": 14.4,
    "selected_asset_page_url": "https://images.nasa.gov/details/EXAMPLE-DROPLET-0001",
}
NARRATION = (
    "Water in space pulls itself into a sphere because surface tension draws "
    "every exposed molecule toward the smallest possible shape around it."
)


class ProductionContractTests(unittest.TestCase):
    def test_accepts_a_short_natural_edge_beat(self) -> None:
        job = {
            "tts_provider": "EDGE",
            "tts_voice": "en-US-ChristopherNeural",
            "narration_text": NARRATION,
            "scenes": [SCENE],
        }
        validate_submission_contract(job)

    def test_rejects_a_shot_longer_than_the_documented_ceiling(self) -> None:
        scene = {**SCENE, "shot_end_seconds": 12.0 + MAX_SHOT_SECONDS + 0.05}
        with self.assertRaisesRegex(ValueError, "verified shot must be between"):
            validate_submission_contract({"tts_provider": "EDGE", "narration_text": NARRATION,
                                          "scenes": [scene]})

    def test_accepts_a_measured_visual_interval_without_scene_captions(self) -> None:
        scene = copy.deepcopy(SCENE)
        scene.update({
            "visual_start_seconds": 0.0,
            "visual_end_seconds": 2.4,
        })
        validate_measured_render_contract([scene])

    def test_rejects_supplied_audio_without_word_boundaries(self) -> None:
        with self.assertRaisesRegex(ValueError, "forbids unverified supplied audio"):
            validate_submission_contract({
                "tts_provider": "EDGE",
                "audio_url": "https://example.test/voice.mp3",
                "narration_text": NARRATION,
                "scenes": [SCENE],
            })

    def test_normal_narration_text_may_span_visual_beats(self) -> None:
        scenes = []
        for index in range(3):
            scenes.append({
                "shot_start_seconds": 1.0,
                "shot_end_seconds": 4.2,
                "selected_asset_page_url": f"https://images.nasa.gov/details/N{index}",
            })
        validate_submission_contract({
            "tts_provider": "EDGE",
            "tts_voice": "en-US-ChristopherNeural",
            "tts_rate": "+2%",
            "narration_text": (
                "A rocket can wait motionless on its launch pad while fuel and "
                "pressure build below, then rise in one continuous burst past the tower."
            ),
            "scenes": scenes,
        })

    def test_missing_master_narration_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "one complete passage"):
            validate_submission_contract({
                "tts_provider": "EDGE",
                "tts_voice": "en-US-ChristopherNeural",
                "tts_rate": "+2%",
                "scenes": [SCENE],
            })


if __name__ == "__main__":
    unittest.main()
