from __future__ import annotations

import unittest

from layout_lock import (CANVAS_W, CAPTION_FONT, CAPTION_MARGIN, CAPTION_MAX_W,
                         CAPTION_SIZE, caption_ass_fontsize, caption_layout)


class CaptionLayoutTests(unittest.TestCase):
    """Captions must wrap rather than leave the frame."""

    def _bounds(self, words):
        from PIL import ImageDraw, ImageFont, Image
        font = ImageFont.truetype(CAPTION_FONT, CAPTION_SIZE)
        probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        left, right = CANVAS_W, 0
        for word, cx, _ in caption_layout(words):
            half = probe.textlength(word, font=font) / 2
            left = min(left, cx - half)
            right = max(right, cx + half)
        return left, right

    def test_a_long_beat_stays_inside_the_margin(self) -> None:
        """Six words are ~1250px wide; the frame is 1080 and the box 888."""
        words = "ENGINES FIRE WHILE CLAMPS HOLD IT".split()
        left, right = self._bounds(words)
        self.assertGreaterEqual(left, CAPTION_MARGIN - 1)
        self.assertLessEqual(right, CANVAS_W - CAPTION_MARGIN + 1)

    def test_a_long_beat_actually_wraps(self) -> None:
        words = "ENGINES FIRE WHILE CLAMPS HOLD IT".split()
        rows = {cy for _, _, cy in caption_layout(words)}
        self.assertGreater(len(rows), 1)

    def test_a_short_beat_stays_on_one_line(self) -> None:
        rows = {cy for _, _, cy in caption_layout(["THRUST", "BUILDS"])}
        self.assertEqual(len(rows), 1)

    def test_every_word_survives_the_layout(self) -> None:
        words = "ONBOARD SYSTEMS CHECK EACH ENGINE HEALTH".split()
        self.assertEqual([w for w, _, _ in caption_layout(words)], words)

    def test_words_are_ordered_left_to_right_within_a_line(self) -> None:
        placed = caption_layout("THRUST BUILDS BEFORE RELEASE".split())
        by_row: dict[int, list[int]] = {}
        for _, cx, cy in placed:
            by_row.setdefault(cy, []).append(cx)
        for row in by_row.values():
            self.assertEqual(row, sorted(row))

    def test_one_very_long_word_is_not_dropped(self) -> None:
        placed = caption_layout(["EXTRAORDINARILY", "LONG"])
        self.assertEqual(len(placed), 2)

    def test_the_ass_font_size_compensates_for_libass(self) -> None:
        """libass sizes by ascent+descent, Pillow by the em square."""
        self.assertGreater(caption_ass_fontsize(), CAPTION_SIZE)

    def test_the_caption_box_is_narrower_than_the_frame(self) -> None:
        self.assertEqual(CAPTION_MAX_W, CANVAS_W - 2 * CAPTION_MARGIN)


if __name__ == "__main__":
    unittest.main()
