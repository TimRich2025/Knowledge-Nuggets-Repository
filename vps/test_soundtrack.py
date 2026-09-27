from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from .soundtrack import (DEFAULT_GAIN_DB, audio_graph, available_tracks,
                         bed_filter, pick_track)


class TrackChoiceTests(unittest.TestCase):
    """The bed is chosen, not left to chance, and a missing one is not a failure."""

    def test_an_empty_library_yields_no_track(self) -> None:
        with TemporaryDirectory() as empty:
            self.assertEqual(available_tracks(Path(empty)), [])
        self.assertIsNone(pick_track("kn-1", []))

    def test_a_missing_directory_is_not_an_error(self) -> None:
        self.assertEqual(available_tracks(Path("/nonexistent/music")), [])

    def test_only_audio_files_are_offered(self) -> None:
        with TemporaryDirectory() as room:
            root = Path(room)
            (root / "bed.mp3").write_bytes(b"x")
            (root / "notes.txt").write_text("not music")
            (root / "cover.png").write_bytes(b"x")
            self.assertEqual([p.name for p in available_tracks(root)], ["bed.mp3"])

    def test_the_same_short_always_gets_the_same_bed(self) -> None:
        tracks = [Path(f"/m/{name}.mp3") for name in "abcdef"]
        self.assertEqual(pick_track("kn-2026-07", tracks), pick_track("kn-2026-07", tracks))

    def test_consecutive_shorts_move_through_the_library(self) -> None:
        tracks = [Path(f"/m/{name}.mp3") for name in "abcdefgh"]
        chosen = {pick_track(f"kn-{n}", tracks).name for n in range(24)}
        self.assertGreater(len(chosen), 3)


class BedFilterTests(unittest.TestCase):
    def test_a_short_track_is_looped_to_the_full_length(self) -> None:
        self.assertIn("aloop=loop=-1", bed_filter(32.0))

    def test_the_bed_is_trimmed_to_the_narration(self) -> None:
        self.assertIn("atrim=0:32.000", bed_filter(32.0))

    def test_both_ends_are_faded(self) -> None:
        chain = bed_filter(32.0)
        self.assertIn("afade=t=in:st=0", chain)
        self.assertIn("afade=t=out", chain)

    def test_the_opening_fade_never_swallows_the_first_beat(self) -> None:
        """A Short opens on its question; the bed has to be there already."""
        chain = bed_filter(10.0)
        fade_in = float(chain.split("afade=t=in:st=0:d=")[1].split(",")[0])
        self.assertLessEqual(fade_in, 0.8)

    def test_the_bed_sits_well_under_the_voice(self) -> None:
        self.assertLessEqual(DEFAULT_GAIN_DB, -12)
        self.assertIn(f"volume={DEFAULT_GAIN_DB:.2f}dB", bed_filter(32.0))


class AudioGraphTests(unittest.TestCase):
    """Measured on a spoken passage: the bed dips 11.5 dB under a word."""

    def test_the_bed_is_ducked_by_the_finished_voice(self) -> None:
        graph = audio_graph("highpass=f=75", 32.0)
        self.assertIn("sidechaincompress", graph)
        self.assertIn("[voiced]asplit=2[voiceout][duckkey]", graph)

    def test_the_duck_is_gentle_enough_to_read_as_headroom(self) -> None:
        graph = audio_graph("highpass=f=75", 32.0)
        self.assertIn("threshold=0.08:ratio=4", graph)

    def test_the_mix_never_rescales_the_voice(self) -> None:
        """amix normalises by default, which would halve the narration."""
        self.assertIn("normalize=0", audio_graph("highpass=f=75", 32.0))

    def test_the_graph_ends_on_a_single_named_output(self) -> None:
        self.assertTrue(audio_graph("highpass=f=75", 32.0).endswith("[a]"))


if __name__ == "__main__":
    unittest.main()
