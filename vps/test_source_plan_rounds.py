"""The plan endpoint's rounds, as the scenario that drives it actually calls it.

The flow that uses this is linear: it looks at the footage, asks for a plan,
looks once more and asks again. It cannot skip a step when the first answer was
already good, so both calls happen on every run. These tests hold the endpoint
to what that costs: the second call must never unmake the first call's pairings,
and a beat left empty must be answered with more footage rather than a refusal,
until the caller says there will be no further look.
"""
from __future__ import annotations
import json
import unittest

try:
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover - missing fastapi, or its test client's httpx
    TestClient = None

from . import api
from .source_pool import SourcePoolError, UnmatchedBeats


class FakeRedis:
    """Just the two calls the endpoint makes, with no expiry to reason about."""

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def setex(self, key: str, _ttl: int, value: str) -> None:
        self.values[key] = value


def work(asset: str) -> dict[str, object]:
    return {"candidate_id": asset, "title": f"{asset} footage",
            "selected_asset_page_url": f"https://images.nasa.gov/details/{asset}",
            "direct_download_url": f"https://images-assets.nasa.gov/video/{asset}/x~orig.mp4",
            "width": 1920, "height": 1080, "measured_duration_seconds": 40.0,
            "contact_sheet_url": f"https://w.app/storyboards/{asset}.jpg",
            "frames": [{"index": 1, "at_seconds": 3.0}, {"index": 2, "at_seconds": 9.0}]}


@unittest.skipIf(TestClient is None, "fastapi is not installed")
class PlanRoundTests(unittest.TestCase):

    BEATS = [{"scene": 1, "must_show": ["rocket", "launch"]}]

    def setUp(self) -> None:
        self.redis = FakeRedis()
        self.redis.setex("kn:pool:POOL", 3600,
                         json.dumps({"works": [work("A")], "observations": {}, "rounds": 0,
                                     "plan": None}))
        self.planned: list[dict[str, object]] = []
        self.widened: list[list[str]] = []
        self._original = (api.db, api.auth, api.plan_from_observations, api.widen_for_beats)
        api.db = lambda: self.redis
        api.auth = lambda authorization: None
        self.client = TestClient(api.app)

    def tearDown(self) -> None:
        api.db, api.auth, api.plan_from_observations, api.widen_for_beats = self._original

    def given_plan(self, outcome) -> None:
        def planner(beats, works, **kwargs):
            self.planned.append({"works": [w["candidate_id"] for w in works]})
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        api.plan_from_observations = planner

    def given_widening(self, found) -> None:
        def widen(known, queries, base_url, **kwargs):
            self.widened.append(list(queries))
            return list(found)
        api.widen_for_beats = widen

    def ask(self, **extra) -> object:
        body = {"beats": self.BEATS, "pool_id": "POOL", **extra}
        return self.client.post("/source-pool/plan", json=body,
                                headers={"Authorization": "Bearer t"})

    def test_a_matched_plan_carries_the_plan_and_nothing_else(self) -> None:
        """The caller branches on the status and only looks again when told to."""
        self.given_plan({"beat_plan": [{"scene": 1}]})
        answer = self.ask().json()
        self.assertEqual(answer["status"], "MATCHED")
        self.assertNotIn("second_look", answer)

    def test_the_second_call_is_given_the_first_call_s_plan_unchanged(self) -> None:
        """A pairing already made is never unmade by a look taken for form's sake."""
        self.given_plan({"beat_plan": [{"scene": 1, "candidate_id": "A"}]})
        first = self.ask().json()
        self.given_plan(SourcePoolError("this must never be reached"))
        second = self.ask(final=True, observations=[
            {"candidate_id": "A", "frames": [{"index": 1, "describes": "a blurred frame"}]}]).json()
        self.assertEqual(second["beat_plan"], first["beat_plan"])
        self.assertEqual(second["status"], "MATCHED")

    def test_an_unserved_beat_is_answered_with_more_footage(self) -> None:
        self.given_plan(UnmatchedBeats("nothing matches beat 1", [1], ["clamp arms"]))
        self.given_widening([work("B")])
        answer = self.ask()
        self.assertEqual(answer.status_code, 200)
        body = answer.json()
        self.assertEqual(body["status"], "LOOK_AGAIN")
        self.assertEqual(self.widened, [["clamp arms"]])
        self.assertEqual([source["candidate_id"] for source in body["new_sources"]], ["B"])
        self.assertTrue(body["second_look"]["gemini_parts"])

    def test_the_new_work_joins_the_pool_rather_than_replacing_it(self) -> None:
        self.given_plan(UnmatchedBeats("nothing matches beat 1", [1], ["clamp arms"]))
        self.given_widening([work("B")])
        self.ask()
        self.given_plan({"beat_plan": [{"scene": 1, "candidate_id": "B"}]})
        self.ask(final=True)
        self.assertEqual(self.planned[-1]["works"], ["A", "B"])

    def test_a_last_look_refuses_instead_of_searching_again(self) -> None:
        self.given_plan(UnmatchedBeats("nothing matches beat 1", [1], ["clamp arms"]))
        self.given_widening([work("B")])
        answer = self.ask(final=True)
        self.assertEqual(answer.status_code, 409)
        self.assertEqual(answer.json()["detail"]["status"], "NO_MATCHING_FOOTAGE")
        self.assertEqual(self.widened, [], "the last look must not start another search")

    def test_a_round_that_finds_nothing_refuses_rather_than_looping(self) -> None:
        self.given_plan(UnmatchedBeats("nothing matches beat 1", [1], ["clamp arms"]))
        self.given_widening([])
        answer = self.ask()
        self.assertEqual(answer.status_code, 409)
        self.assertEqual(answer.json()["detail"]["status"], "NO_MATCHING_FOOTAGE")

    def test_observations_survive_the_round_that_follows_them(self) -> None:
        self.given_plan(UnmatchedBeats("nothing matches beat 1", [1], ["clamp arms"]))
        self.given_widening([work("B")])
        self.ask(observations=[{"candidate_id": "A",
                                "frames": [{"index": 1, "describes": "a rocket on the pad"}]}])
        kept = json.loads(self.redis.values["kn:pool:POOL"])
        self.assertEqual(kept["observations"]["A"]["1"], "a rocket on the pad")
        self.assertEqual(kept["rounds"], 1)

    def test_a_pool_written_before_rounds_existed_still_finishes(self) -> None:
        self.redis.setex("kn:pool:OLD", 3600, json.dumps([work("A")]))
        self.given_plan({"beat_plan": [{"scene": 1}]})
        answer = self.client.post("/source-pool/plan",
                                  json={"beats": self.BEATS, "pool_id": "OLD", "final": True},
                                  headers={"Authorization": "Bearer t"})
        self.assertEqual(answer.status_code, 200)
        self.assertEqual(answer.json()["status"], "MATCHED")


if __name__ == "__main__":
    unittest.main()
