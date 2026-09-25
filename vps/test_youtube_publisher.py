from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from .youtube_publisher import YouTubePublishError, publish_private_short


class YouTubePublisherTests(unittest.TestCase):
    @patch("vps.youtube_publisher.YOUTUBE_OAUTH_REFRESH_TOKEN", "refresh")
    @patch("vps.youtube_publisher.YOUTUBE_OAUTH_CLIENT_SECRET", "secret")
    @patch("vps.youtube_publisher.YOUTUBE_OAUTH_CLIENT_ID", "client")
    @patch("vps.youtube_publisher.requests.put")
    @patch("vps.youtube_publisher.requests.post")
    def test_upload_is_always_private(self, post, put) -> None:
        token = Mock()
        token.json.return_value = {"access_token": "access"}
        token.raise_for_status.return_value = None
        session = Mock()
        session.headers = {"Location": "https://upload.example.test/session"}
        session.raise_for_status.return_value = None
        post.side_effect = [token, session]
        complete = Mock()
        complete.json.return_value = {"id": "abc123"}
        complete.raise_for_status.return_value = None
        put.return_value = complete
        with tempfile.TemporaryDirectory() as temp:
            video = Path(temp) / "preview.mp4"
            video.write_bytes(b"video")
            result = publish_private_short(video, "but the fact is, test", "but the fact is, test\n\n#Shorts")
        self.assertEqual(result["privacy_status"], "private")
        self.assertEqual(result["short_url"], "https://youtube.com/shorts/abc123")
        self.assertEqual(post.call_args_list[1].kwargs["json"]["status"]["privacyStatus"], "private")

    def test_rejects_metadata_that_cannot_be_paired(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            video = Path(temp) / "preview.mp4"
            video.write_bytes(b"video")
            with self.assertRaisesRegex(YouTubePublishError, "start the description"):
                publish_private_short(video, "title", "different opening")


if __name__ == "__main__":
    unittest.main()
