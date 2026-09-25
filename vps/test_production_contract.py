from __future__ import annotations

import copy
import unittest

from .production_contract import validate_measured_render_contract, validate_submission_contract


SCENE = {
    "spoken_phrase": "Water pulls itself into a sphere.",
    "plain_language": True,
    "caption_beats": ["WATER PULLS", "ITSELF INTO", "A SPHERE"],
    "shot_start_seconds": 12.0,
    "shot_end_seconds": 14.4,
}


class ProductionContractTests(unittest.TestCase):
    def test_accepts_a_short_natural_edge_beat(self) -> None:
        job = {
            "tts_provider": "EDGE",
            "tts_voice": "en-US-AndrewMultilingualNeural",
            "tts_rate": "+8%",
            "scenes": [SCENE],
        }
        validate_submission_contract(job)

    def test_rejects_a_shot_longer_than_two_point_four_seconds(self) -> None:
        scene = {**SCENE, "shot_end_seconds": 14.41}
        with self.assertRaisesRegex(ValueError, "2.4s"):
            validate_submission_contract({"tts_provider": "EDGE", "scenes": [scene]})

    def test_rejects_unmeasured_or_long_caption_beats(self) -> None:
        scene = copy.deepcopy(SCENE)
        scene.update({
            "speech_start_seconds": 0.0,
            "speech_end_seconds": 2.4,
            "caption_timings": [
                {"text": "WATER PULLS", "start_seconds": 0.0, "end_seconds": 0.7},
                {"text": "ITSELF INTO", "start_seconds": 0.7, "end_seconds": 1.4},
                {"text": "A SPHERE", "start_seconds": 1.4, "end_seconds": 2.4},
            ],
        })
        validate_measured_render_contract([scene])
        scene["caption_timings"][0]["text"] = "WATER PULLS ITSELF INTO A"
        with self.assertRaisesRegex(ValueError, "1-4 words"):
            validate_measured_render_contract([scene])

    def test_rejects_supplied_audio_without_word_boundaries(self) -> None:
        with self.assertRaisesRegex(ValueError, "forbids unverified supplied audio"):
            validate_submission_contract({
                "tts_provider": "EDGE",
                "audio_url": "https://example.test/voice.mp3",
                "scenes": [SCENE],
            })


if __name__ == "__main__":
    unittest.main()
