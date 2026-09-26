from __future__ import annotations

import unittest
from pathlib import Path

from .edge_word_tts import build_parser
from .source_cache import build_tts_command


class TtsCommandTests(unittest.TestCase):
    """A natural speaking rate is negative, and argparse must still see it."""

    def _parse(self, rate: str):
        command = build_tts_command(
            "en-US-ChristopherNeural", rate, "engines build full thrust",
            Path("/tmp/scene.mp3"), Path("/tmp/scene.srt"),
        )
        # Skip the interpreter and -m module selector; the rest is the real argv.
        return build_parser().parse_args(command[3:])

    def test_negative_rate_survives_argument_parsing(self) -> None:
        self.assertEqual(self._parse("-3%").rate, "-3%")

    def test_positive_rate_still_works(self) -> None:
        self.assertEqual(self._parse("+8%").rate, "+8%")

    def test_every_contract_rate_is_accepted(self) -> None:
        for percent in range(-12, 13):
            rate = f"{percent:+d}%"
            with self.subTest(rate=rate):
                self.assertEqual(self._parse(rate).rate, rate)

    def test_phrase_and_voice_are_preserved(self) -> None:
        options = self._parse("-3%")
        self.assertEqual(options.text, "engines build full thrust")
        self.assertEqual(options.voice, "en-US-ChristopherNeural")

    def test_a_separate_argv_entry_would_break(self) -> None:
        """Documents the defect this command builder exists to prevent."""
        broken = ["--voice=v", "--rate", "-3%", "--text=t",
                  "--write-media", "m", "--write-subtitles", "s"]
        with self.assertRaises(SystemExit):
            build_parser().parse_args(broken)


if __name__ == "__main__":
    unittest.main()
