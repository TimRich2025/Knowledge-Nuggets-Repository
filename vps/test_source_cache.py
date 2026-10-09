from pathlib import Path
from tempfile import TemporaryDirectory
import os
import time
import unittest
from unittest.mock import patch

from . import source_cache


class SourceCachePruningTests(unittest.TestCase):
    def test_prunes_oldest_media_and_interrupted_downloads(self):
        with TemporaryDirectory() as raw:
            cache = Path(raw)
            old = cache / "old.mp4"
            new = cache / "new.mp4"
            old_meta = cache / "old.json"
            partial = cache / "download.part.mp4"
            old.write_bytes(b"o" * 30_000_000)
            old_meta.write_text("{}", encoding="utf-8")
            new.write_bytes(b"n" * 30_000_000)
            partial.write_bytes(b"p")
            now = time.time()
            os.utime(old, (now - 60, now - 60))
            os.utime(new, (now, now))

            with patch.object(source_cache, "CACHE", cache), patch.object(
                source_cache, "MAX_CACHE_GB", 0.00005
            ):
                result = source_cache.prune_cache()

            self.assertFalse(old.exists())
            self.assertFalse(old_meta.exists())
            self.assertTrue(new.exists())
            self.assertFalse(partial.exists())
            self.assertEqual(result["after_bytes"], 30_000_000)
            self.assertEqual(result["removed_files"], 2)


if __name__ == "__main__":
    unittest.main()
