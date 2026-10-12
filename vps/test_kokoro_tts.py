from __future__ import annotations

import unittest

from .passage_chunks import MAX_PASSAGE_CHARS, passage_chunks


class PuckPassageTests(unittest.TestCase):
    def test_long_script_is_split_only_after_sentence_boundaries(self):
        script = (
            "At launch, a rocket waits beside its tower. "
            "The engines build enough thrust before it rises. "
            "Once the balance tips, the rocket clears the pad. "
            "In the open sky, it keeps gaining speed steadily."
        )
        chunks = passage_chunks(script, max_chars=105)
        self.assertEqual(" ".join(chunks), script)
        self.assertTrue(all(chunk.endswith(".") for chunk in chunks[:-1]))
        self.assertTrue(all(len(chunk) <= 105 for chunk in chunks))

    def test_production_limit_caps_memory_without_scene_splitting(self):
        script = " ".join(["A complete sentence stays natural."] * 30)
        chunks = passage_chunks(script)
        self.assertEqual(" ".join(chunks), script)
        self.assertTrue(all(len(chunk) <= MAX_PASSAGE_CHARS for chunk in chunks))
        self.assertLess(len(chunks), 15)

    def test_empty_text_has_no_passages(self):
        self.assertEqual(passage_chunks("   \n  "), [])


if __name__ == "__main__":
    unittest.main()
