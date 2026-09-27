from __future__ import annotations

import unittest

from .production_contract import validate_source_diversity
from .scene_match import (MATCH_FLOOR, match_score, plan_by_content, terms,
                          window_terms)


PAD_BEAT = {"must_show": ["hold-down clamps", "rocket base"],
            "visual_target": "Clamps hold the rocket at the pad",
            "spoken_phrase": "Pad hardware keeps the rocket restrained"}
ASCENT_BEAT = {"must_show": ["rocket climbing", "exhaust trail"],
               "visual_target": "The rocket climbs away through open sky",
               "spoken_phrase": "The rocket climbs past the tower"}


def window(asset: str, start: float, seen: str, end: float | None = None) -> dict:
    return {"candidate_id": asset, "shot_start_seconds": start,
            "shot_end_seconds": end if end is not None else start + 3.2,
            "direct_download_url": f"https://images-assets.nasa.gov/video/{asset}/{asset}~orig.mp4",
            "selected_asset_page_url": f"https://images.nasa.gov/details/{asset}",
            "seen": terms(seen)}


class ScoringTests(unittest.TestCase):
    """A score has to separate footage that fits from footage that does not."""

    def test_footage_showing_what_the_beat_needs_scores_high(self) -> None:
        seen = terms("a rocket base held by hold down clamps on the launch pad")
        self.assertGreater(match_score(PAD_BEAT, seen), 0.7)

    def test_unrelated_footage_scores_zero(self) -> None:
        self.assertEqual(match_score(PAD_BEAT, terms("an empty blue sky with clouds")), 0.0)

    def test_the_wrong_moment_of_the_right_subject_is_rejected(self) -> None:
        """Ascent footage under a pad beat is the exact failure being fixed."""
        seen = terms("a rocket high in the sky trailing a long exhaust plume")
        self.assertLess(match_score(PAD_BEAT, seen), MATCH_FLOOR)

    def test_a_hyphenated_requirement_matches_the_spelled_out_description(self) -> None:
        """A brief writes hold-down, a description writes hold down."""
        self.assertIn("hold", terms("hold-down clamps"))

    def test_one_shared_word_is_not_enough_to_count_as_a_match(self) -> None:
        self.assertLess(match_score(PAD_BEAT, terms("a rocket")), MATCH_FLOOR)

    def test_an_empty_description_never_matches(self) -> None:
        self.assertEqual(match_score(PAD_BEAT, set()), 0.0)


class WindowTermsTests(unittest.TestCase):
    """A window is judged on the frames that fall inside it."""

    FRAMES = [{"at_seconds": 0.0, "describes": "an empty launch pad at dawn"},
              {"at_seconds": 4.0, "describes": "a rocket held by clamps at the pad"},
              {"at_seconds": 8.0, "describes": "bright exhaust under the rocket"},
              {"at_seconds": 12.0, "describes": "the rocket climbing into open sky"}]

    def test_a_window_sees_the_frames_inside_it(self) -> None:
        self.assertIn("clamp", window_terms(self.FRAMES, 3.5, 6.7))

    def test_a_window_between_samples_still_sees_something(self) -> None:
        seen = window_terms(self.FRAMES, 5.0, 6.0)
        self.assertTrue(seen)

    def test_a_late_window_does_not_inherit_the_opening_frame(self) -> None:
        self.assertNotIn("dawn", window_terms(self.FRAMES, 11.0, 13.0))


class ContentPlanTests(unittest.TestCase):
    """The plan must be grounded in pixels and still satisfy the contract."""

    def _windows(self):
        pad = "a rocket base held by hold down clamps at the launch pad"
        fly = "a rocket climbing through open sky with an exhaust trail"
        return ([window(f"PAD{n}", n * 4.0, pad) for n in range(4)]
                + [window(f"FLY{n}", n * 4.0, fly) for n in range(4)])

    def test_each_beat_gets_footage_that_shows_what_it_needs(self) -> None:
        beats = [PAD_BEAT, ASCENT_BEAT, PAD_BEAT, ASCENT_BEAT]
        result = plan_by_content(beats, self._windows())
        self.assertEqual(result["unmatched_beats"], [])
        for entry, beat in zip(result["plan"], beats):
            expected = "PAD" if beat is PAD_BEAT else "FLY"
            self.assertTrue(entry["candidate_id"].startswith(expected), entry)

    def test_a_beat_nothing_shows_is_reported_not_guessed(self) -> None:
        """Silently handing it the least bad clip is what produced the mismatch."""
        orbit = {"must_show": ["astronaut floating", "space station interior"],
                 "visual_target": "An astronaut floats inside the station",
                 "spoken_phrase": "An astronaut floats inside the station"}
        result = plan_by_content([PAD_BEAT, orbit], self._windows())
        self.assertEqual(result["unmatched_beats"], [2])

    def test_no_window_is_used_twice(self) -> None:
        result = plan_by_content([PAD_BEAT] * 4, self._windows())
        starts = [(entry["candidate_id"], entry["shot_start_seconds"]) for entry in result["plan"]]
        self.assertEqual(len(starts), len(set(starts)))

    def test_the_variety_contract_still_holds(self) -> None:
        beats = [PAD_BEAT, ASCENT_BEAT] * 9
        result = plan_by_content(beats, self._windows() * 3)
        self.assertEqual(result["unmatched_beats"], [])
        validate_source_diversity(result["plan"])

    def test_no_three_neighbours_share_a_work(self) -> None:
        beats = [PAD_BEAT] * 6
        result = plan_by_content(beats, self._windows() * 2)
        assets = [entry["candidate_id"] for entry in result["plan"]]
        for first, second, third in zip(assets, assets[1:], assets[2:]):
            self.assertFalse(first == second == third)

    def test_a_beat_with_one_possible_clip_is_served_first(self) -> None:
        """Otherwise an easy beat takes the only footage a hard beat could use."""
        only = window("RARE", 0.0, "a gantry arm swinging away from the vehicle")
        gantry = {"must_show": ["gantry arm", "swinging away"],
                  "visual_target": "The gantry arm swings clear of the vehicle",
                  "spoken_phrase": "The gantry arm swings clear"}
        result = plan_by_content([PAD_BEAT, gantry], self._windows() + [only])
        self.assertEqual(result["unmatched_beats"], [])
        self.assertEqual(result["plan"][1]["candidate_id"], "RARE")

    def test_equally_good_windows_go_to_an_unused_work(self) -> None:
        """Otherwise six beats over six works came out of four of them."""
        result = plan_by_content([PAD_BEAT, ASCENT_BEAT] * 3, self._windows())
        self.assertGreaterEqual(result["distinct_sources"], 5)

    def test_the_report_names_the_weakest_pairing(self) -> None:
        result = plan_by_content([PAD_BEAT, ASCENT_BEAT], self._windows())
        self.assertGreaterEqual(result["weakest_match"], MATCH_FLOOR)

    def test_planning_without_footage_is_an_error_not_an_empty_plan(self) -> None:
        with self.assertRaises(ValueError):
            plan_by_content([PAD_BEAT], [])


if __name__ == "__main__":
    unittest.main()


class ObservationPlanTests(unittest.TestCase):
    """The endpoint layer: real works, real frames, a grounded beat plan."""

    def _work(self, asset: str, timeline: list[tuple[float, str]], duration: float = 36.0):
        return {"candidate_id": asset, "title": asset,
                "direct_download_url": f"https://images-assets.nasa.gov/video/{asset}/{asset}~orig.mp4",
                "selected_asset_page_url": f"https://images.nasa.gov/details/{asset}",
                "width": 1920, "height": 1080, "measured_duration_seconds": duration,
                "frames": [{"index": i + 1, "at_seconds": at, "describes": text}
                           for i, (at, text) in enumerate(timeline)]}

    def _works(self):
        pad = [(t, "a rocket held by hold down clamps at the launch pad") for t in range(0, 36, 3)]
        fly = [(t, "a rocket climbing through open sky with an exhaust trail") for t in range(0, 36, 3)]
        return [self._work(f"PAD{n}", pad) for n in range(3)] + \
               [self._work(f"FLY{n}", fly) for n in range(3)]

    def test_a_plan_is_built_from_what_the_frames_showed(self) -> None:
        from .source_pool import plan_from_observations
        beats = [PAD_BEAT, ASCENT_BEAT] * 3
        result = plan_from_observations(beats, self._works())
        self.assertEqual(result["beats"], 6)
        validate_source_diversity(result["beat_plan"])
        self.assertGreaterEqual(result["weakest_match"], MATCH_FLOOR)

    def test_a_work_nobody_looked_at_is_not_used(self) -> None:
        from .source_pool import plan_from_observations, SourcePoolError
        blind = [{**work, "frames": [{"index": 1, "at_seconds": 0.0, "describes": ""}]}
                 for work in self._works()]
        with self.assertRaisesRegex(SourcePoolError, "frame description"):
            plan_from_observations([PAD_BEAT], blind)

    def test_a_beat_no_footage_shows_fails_loudly(self) -> None:
        from .source_pool import plan_from_observations, SourcePoolError
        orbit = {"must_show": ["astronaut floating", "station interior"],
                 "visual_target": "An astronaut floats inside the station",
                 "spoken_phrase": "An astronaut floats inside the station"}
        with self.assertRaisesRegex(SourcePoolError, "no observed footage matches beats"):
            plan_from_observations([PAD_BEAT, orbit] * 3, self._works())

    def test_every_interval_lies_inside_the_measured_clip(self) -> None:
        from .source_pool import plan_from_observations
        result = plan_from_observations([PAD_BEAT, ASCENT_BEAT] * 3, self._works())
        for entry in result["beat_plan"]:
            self.assertLessEqual(entry["shot_end_seconds"], entry["measured_duration_seconds"])
            self.assertGreaterEqual(entry["shot_start_seconds"], 0.0)


class ContactSheetTests(unittest.TestCase):
    """A description is only usable if each frame's second is known."""

    def test_the_frame_times_span_the_clip(self) -> None:
        from .source_pool import SHEET_FRAMES, sheet_frames
        times = [frame["at_seconds"] for frame in sheet_frames(36.0)]
        self.assertEqual(times[0], 0.0)
        self.assertLess(times[-1], 36.0)
        self.assertEqual(len(times), SHEET_FRAMES)
        self.assertGreater(times[-1], 24.0)

    def test_a_short_clip_still_yields_several_frames(self) -> None:
        from .source_pool import sheet_frames
        self.assertGreaterEqual(len(sheet_frames(8.0)), 2)

    def test_the_sheet_url_carries_the_clip_and_its_window(self) -> None:
        from .source_pool import describe_request
        source = {"candidate_id": "A", "direct_download_url": "https://x/a.mp4",
                  "measured_duration_seconds": 36.0}
        url = describe_request([source], "https://worker.app/")[0]["contact_sheet_url"]
        self.assertIn("source-probes/contact-sheet.jpg", url)
        self.assertIn("candidate_end_seconds=36.000", url)
        self.assertIn("samples=6", url)
        self.assertNotIn("//source-probes", url.replace("https://", ""))

    def test_only_a_readable_number_of_sheets_is_sent(self) -> None:
        """Past eight sheets the vision pass blurs one clip into the next."""
        from .source_pool import MAX_DESCRIBED_WORKS, describe_request
        sources = [{"candidate_id": f"A{n}", "direct_download_url": f"https://x/{n}.mp4",
                    "measured_duration_seconds": 36.0} for n in range(14)]
        self.assertEqual(len(describe_request(sources, "https://w.app")), MAX_DESCRIBED_WORKS)


class ObservationMergeTests(unittest.TestCase):
    """A model writes descriptions. Every URL and number stays server-side."""

    def _described(self):
        from .source_pool import describe_request
        return describe_request([{"candidate_id": "A", "title": "Launch",
                                  "direct_download_url": "https://images-assets.nasa.gov/video/A/A~orig.mp4",
                                  "selected_asset_page_url": "https://images.nasa.gov/details/A",
                                  "width": 1920, "height": 1080,
                                  "measured_duration_seconds": 36.0}], "https://worker.app")

    def test_a_description_lands_on_the_right_frame(self) -> None:
        from .source_pool import merge_observations
        merged = merge_observations(self._described(), [
            {"candidate_id": "A", "frames": [{"index": 3, "describes": "a rocket at the pad"}]}])
        described = {frame["index"]: frame["describes"] for frame in merged[0]["frames"]}
        self.assertEqual(described[3], "a rocket at the pad")
        self.assertEqual(described[1], "")

    def test_the_urls_come_from_the_server_not_the_observation(self) -> None:
        from .source_pool import merge_observations
        merged = merge_observations(self._described(), [
            {"candidate_id": "A", "frames": [{"index": 1, "describes": "sky"}]}])
        self.assertEqual(merged[0]["direct_download_url"],
                         "https://images-assets.nasa.gov/video/A/A~orig.mp4")
        self.assertEqual(merged[0]["measured_duration_seconds"], 36.0)

    def test_an_observation_for_an_unknown_work_is_ignored(self) -> None:
        from .source_pool import merge_observations
        merged = merge_observations(self._described(), [
            {"candidate_id": "GHOST", "frames": [{"index": 1, "describes": "invented"}]}])
        self.assertTrue(all(frame["describes"] == "" for frame in merged[0]["frames"]))

    def test_the_vision_note_says_which_image_is_which_clip(self) -> None:
        from .source_pool import vision_payload
        payload = vision_payload(self._described())
        self.assertEqual(len(payload["vision_images"]), 1)
        self.assertEqual(payload["vision_images"][0]["imageUploadType"], "url")
        self.assertIn("IMAGE 1: work A", payload["vision_context"])
        self.assertIn("1=0.0s", payload["vision_context"])


class ToleranceTests(unittest.TestCase):
    """A scenario splices a model's answer straight into a request body."""

    def test_a_plain_json_list_is_read(self) -> None:
        from .source_pool import loads_tolerant
        self.assertEqual(loads_tolerant('[{"candidate_id":"A"}]'), [{"candidate_id": "A"}])

    def test_a_fenced_answer_is_read_rather_than_refused(self) -> None:
        """Refusing the fence costs a production run to teach a lesson nobody learns."""
        from .source_pool import loads_tolerant
        fenced = '```json\n[{"candidate_id":"B"}]\n```'
        self.assertEqual(loads_tolerant(fenced), [{"candidate_id": "B"}])

    def test_a_wrapped_object_is_unwrapped(self) -> None:
        from .source_pool import loads_tolerant
        self.assertEqual(loads_tolerant('{"observations":[{"candidate_id":"C"}]}'),
                         [{"candidate_id": "C"}])

    def test_an_already_parsed_list_passes_through(self) -> None:
        from .source_pool import loads_tolerant
        self.assertEqual(loads_tolerant([{"candidate_id": "D"}]), [{"candidate_id": "D"}])

    def test_unreadable_input_yields_nothing_rather_than_raising(self) -> None:
        from .source_pool import loads_tolerant
        for value in ("not json", "", None, "{{broken}}"):
            self.assertEqual(loads_tolerant(value), [])

    def test_the_images_are_shaped_for_both_vision_modules(self) -> None:
        """Gemini wants file parts, the OpenAI module wants url objects."""
        from .source_pool import vision_payload
        payload = vision_payload(self._described())
        self.assertEqual(payload["gemini_parts"][0]["type"], "file")
        self.assertEqual(payload["gemini_parts"][0]["file_data"]["mime_type"], "image/jpeg")
        self.assertEqual(payload["gemini_parts"][0]["file_data"]["file_uri"],
                         payload["vision_images"][0]["imageUrl"])
