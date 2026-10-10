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


class ProductionContractTests(unittest.TestCase):
    def test_accepts_a_short_natural_edge_beat(self) -> None:
        job = {
            "tts_provider": "EDGE",
            "tts_voice": "en-US-AndrewMultilingualNeural",
            "scenes": [SCENE],
        }
        validate_submission_contract(job)

    def test_rejects_a_shot_longer_than_the_documented_ceiling(self) -> None:
        scene = {**SCENE, "shot_end_seconds": 12.0 + MAX_SHOT_SECONDS + 0.05}
        with self.assertRaisesRegex(ValueError, "verified shot must be between"):
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

    def test_normal_narration_text_may_span_visual_beats(self) -> None:
        chunks = [
            "Rocket stands on its launch pad",
            "while engines ignite beneath it",
            "then it climbs past the tower",
        ]
        scenes = []
        for index, phrase in enumerate(chunks):
            words = phrase.split()
            scenes.append({
                "spoken_phrase": phrase,
                "plain_language": True,
                "caption_beats": [
                    " ".join(words[start:start + 4])
                    for start in range(0, len(words), 4)
                ],
                "shot_start_seconds": 1.0,
                "shot_end_seconds": 4.2,
                "selected_asset_page_url": f"https://images.nasa.gov/details/N{index}",
            })
        validate_submission_contract({
            "tts_provider": "EDGE",
            "tts_voice": "en-US-AndrewMultilingualNeural",
            "tts_rate": "+8%",
            "narration_text": (
                "Rocket stands on its launch pad while engines ignite beneath it. "
                "Then it climbs past the tower."
            ),
            "scenes": scenes,
        })

    def test_narration_text_cannot_drift_from_the_subtitles(self) -> None:
        with self.assertRaisesRegex(ValueError, "exactly the spoken_phrase words"):
            validate_submission_contract({
                "tts_provider": "EDGE",
                "tts_voice": "en-US-AndrewMultilingualNeural",
                "tts_rate": "+8%",
                "narration_text": "Different narration entirely.",
                "scenes": [SCENE],
            })


if __name__ == "__main__":
    unittest.main()
