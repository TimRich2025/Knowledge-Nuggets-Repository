from __future__ import annotations

import unittest

import numpy as np

from .generate_music_library import TRACKS, render_recipe


class MusicLibraryTests(unittest.TestCase):
    def test_library_contains_four_distinct_arrangements(self) -> None:
        self.assertEqual(len(TRACKS), 4)
        self.assertEqual(len({track.filename for track in TRACKS}), 4)
        self.assertEqual(len({track.bpm for track in TRACKS}), 4)
        self.assertEqual(len({track.roots for track in TRACKS}), 4)

    def test_each_track_is_real_stereo_with_safe_headroom(self) -> None:
        for recipe in TRACKS:
            audio = render_recipe(recipe, sample_rate=8_000, bars=1)
            self.assertEqual(audio.ndim, 2)
            self.assertEqual(audio.shape[1], 2)
            self.assertGreater(audio.shape[0], 10_000)
            self.assertGreater(float(np.sqrt(np.mean(audio ** 2))), .025)
            self.assertGreater(float(np.mean(np.abs(audio[:, 0] - audio[:, 1]))), .005)
            self.assertLessEqual(float(np.max(np.abs(audio))), .911)


if __name__ == "__main__":
    unittest.main()
