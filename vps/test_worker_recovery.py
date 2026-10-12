from __future__ import annotations

import json
import unittest

from .worker import recover_recent_audio_jobs


class FakeRedis:
    def __init__(self, rows):
        self.rows = rows
        self.markers = set()
        self.queue = []

    def scan_iter(self, pattern):
        self.pattern = pattern
        return iter(self.rows)

    def hgetall(self, key):
        return dict(self.rows[key])

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.markers:
            return False
        self.markers.add(key)
        return True

    def hset(self, key, mapping):
        self.rows[key].update(mapping)

    def rpush(self, key, value):
        self.queue.append((key, value))


class WorkerRecoveryTests(unittest.TestCase):
    def job(self, message, updated=900.0):
        return {
            "state": "FAILED",
            "updated_at": str(updated),
            "error": json.dumps({"message": message}),
            "payload": json.dumps({"content_id": "kn-test"}),
        }

    def test_recent_edge_failure_is_requeued_once(self):
        redis = FakeRedis({"kn:job:abc": self.job("neural TTS failed after retries: 403")})
        self.assertEqual(recover_recent_audio_jobs(redis, now=1000.0), 1)
        self.assertEqual(redis.rows["kn:job:abc"]["state"], "QUEUED")
        self.assertEqual(redis.queue, [("kn:queue", "abc")])
        redis.rows["kn:job:abc"]["state"] = "FAILED"
        self.assertEqual(recover_recent_audio_jobs(redis, now=1001.0), 0)

    def test_completed_old_audio_render_is_requeued_once(self):
        job = self.job("")
        job.update({
            "state": "COMPLETED",
            "error": "",
            "result": json.dumps({
                "narration_backend": "kokoro-af-bella-continuous",
                "soundtrack_mode": "procedural-upbeat",
            }),
        })
        redis = FakeRedis({"kn:job:published": job})
        self.assertEqual(recover_recent_audio_jobs(redis, now=1000.0), 1)
        self.assertEqual(redis.rows["kn:job:published"]["result"], "")
        self.assertEqual(redis.queue, [("kn:queue", "published")])

    def test_recent_concat_rounding_failure_is_requeued_once(self):
        redis = FakeRedis({
            "kn:job:concat": self.job(
                "concatenated visual track lost scenes after three attempts: "
                "joined 21.600s instead of 22.300s"
            )
        })
        self.assertEqual(recover_recent_audio_jobs(redis, now=1000.0), 1)
        self.assertEqual(redis.rows["kn:job:concat"]["state"], "QUEUED")
        self.assertEqual(redis.queue, [("kn:queue", "concat")])

    def test_unrelated_or_old_failures_are_ignored(self):
        redis = FakeRedis({
            "kn:job:render": self.job("ffmpeg failed"),
            "kn:job:old": self.job("neural TTS failed after retries: 403", updated=-200000.0),
        })
        self.assertEqual(recover_recent_audio_jobs(redis, now=1000.0), 0)
        self.assertEqual(redis.queue, [])


if __name__ == "__main__":
    unittest.main()
