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

    def test_a_beat_nothing_shows_is_served_but_marked(self) -> None:
        """Losing a whole Short over one beat is worse than a loose pairing.

        What may never happen is a silent one: the entry says it was not
        matched on its own evidence, so nothing downstream can read it as
        proven.
        """
        orbit = {"must_show": ["astronaut floating", "space station interior"],
                 "visual_target": "An astronaut floats inside the station",
                 "spoken_phrase": "An astronaut floats inside the station"}
        result = plan_by_content([PAD_BEAT, orbit], self._windows())
        self.assertEqual(result["unmatched_beats"], [])
        loose = next(entry for entry in result["plan"] if entry["beat"] == 2)
        self.assertEqual(loose["served_by"], "best available")

    def test_a_proved_beat_is_never_marked(self) -> None:
        result = plan_by_content([PAD_BEAT], self._windows())
        self.assertNotIn("served_by", result["plan"][0])

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

    def test_a_beat_no_footage_shows_is_still_given_a_shot(self) -> None:
        """It is marked, and it is never a slate: those carry no terms at all."""
        from .source_pool import plan_from_observations
        orbit = {"must_show": ["astronaut floating", "station interior"],
                 "visual_target": "An astronaut floats inside the station",
                 "spoken_phrase": "An astronaut floats inside the station"}
        result = plan_from_observations([PAD_BEAT, orbit] * 3, self._works())
        self.assertEqual(len(result["beat_plan"]), 6)
        loose = [entry for entry in result["beat_plan"] if entry.get("served_by")]
        self.assertTrue(loose)

    def test_every_interval_lies_inside_the_measured_clip(self) -> None:
        from .source_pool import plan_from_observations
        result = plan_from_observations([PAD_BEAT, ASCENT_BEAT] * 3, self._works())
        for entry in result["beat_plan"]:
            self.assertLessEqual(entry["shot_end_seconds"], entry["measured_duration_seconds"])
            self.assertGreaterEqual(entry["shot_start_seconds"], 0.0)


class ContactSheetTests(unittest.TestCase):
    """A description is only usable if each frame's second is known."""

    def test_the_still_times_spread_across_the_clip(self) -> None:
        from .storyboard import assumed_times
        times = assumed_times(6, 36.0)
        self.assertEqual(len(times), 6)
        self.assertGreater(times[0], 0.0)
        self.assertLess(times[-1], 36.0)
        self.assertGreater(times[-1] - times[0], 24.0)

    def test_the_stills_are_evenly_spaced(self) -> None:
        """The catalogue publishes them that way; nothing here measures it."""
        from .storyboard import assumed_times
        times = assumed_times(5, 30.0)
        gaps = [round(b - a, 3) for a, b in zip(times, times[1:])]
        self.assertEqual(len(set(gaps)), 1)

    def test_the_sheet_is_served_from_a_prebuilt_file(self) -> None:
        """A sheet generated on request timed the vision pass out with a 404."""
        from .source_pool import describe_request
        source = {"candidate_id": "A", "measured_duration_seconds": 36.0,
                  "review_frame_urls": ["https://x/1.jpg", "https://x/2.jpg"]}
        url = describe_request([source], "https://worker.app/",
                               build=lambda urls: ("b" * 32, 2))[0]["contact_sheet_url"]
        self.assertEqual(url, "https://worker.app/storyboards/" + "b" * 32 + ".jpg")

    def test_a_work_without_catalogue_stills_is_left_out(self) -> None:
        from .source_pool import describe_request
        from .storyboard import StoryboardError

        def refuse(urls):
            raise StoryboardError("no stills")

        source = {"candidate_id": "A", "measured_duration_seconds": 36.0, "review_frame_urls": []}
        self.assertEqual(describe_request([source], "https://w.app", build=refuse), [])

    def test_only_a_readable_number_of_sheets_is_sent(self) -> None:
        """Past eight sheets the vision pass blurs one clip into the next."""
        from .source_pool import MAX_DESCRIBED_WORKS, describe_request
        sources = [{"candidate_id": f"A{n}", "measured_duration_seconds": 36.0,
                    "review_frame_urls": ["https://x/1.jpg"]} for n in range(14)]
        described = describe_request(sources, "https://w.app", build=lambda urls: ("c" * 32, 5))
        self.assertEqual(len(described), MAX_DESCRIBED_WORKS)


class ObservationMergeTests(unittest.TestCase):
    """A model writes descriptions. Every URL and number stays server-side."""

    def _described(self):
        from .source_pool import describe_request
        return describe_request([{"candidate_id": "A", "title": "Launch",
                                  "direct_download_url": "https://images-assets.nasa.gov/video/A/A~orig.mp4",
                                  "selected_asset_page_url": "https://images.nasa.gov/details/A",
                                  "review_frame_urls": [f"https://x/A~medium_{n}.jpg" for n in range(1, 7)],
                                  "width": 1920, "height": 1080,
                                  "measured_duration_seconds": 36.0}], "https://worker.app",
                                build=lambda urls: ("a" * 32, 6))

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

    def test_the_images_are_shaped_for_both_vision_modules(self) -> None:
        """Gemini wants file parts, the OpenAI module wants url objects."""
        from .source_pool import vision_payload
        payload = vision_payload(self._described())
        self.assertEqual(payload["gemini_parts"][0]["type"], "file")
        self.assertEqual(payload["gemini_parts"][0]["file_data"]["mime_type"], "image/jpeg")
        self.assertEqual(payload["gemini_parts"][0]["file_data"]["file_uri"],
                         payload["vision_images"][0]["imageUrl"])

    def test_the_vision_note_says_which_image_is_which_clip(self) -> None:
        from .source_pool import vision_payload
        payload = vision_payload(self._described())
        self.assertEqual(len(payload["vision_images"]), 1)
        self.assertEqual(payload["vision_images"][0]["imageUploadType"], "url")
        self.assertIn("IMAGE 1: work A", payload["vision_context"])
        self.assertIn("1=3.0s", payload["vision_context"])


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


class RetrySuggestionTests(unittest.TestCase):
    """A failed match is only useful if it says what is missing."""

    BEATS = [{"must_show": ["hold down hardware", "rocket base", "launch platform"]},
             {"must_show": ["restraint arms", "rocket base"]},
             {"must_show": ["mission control room", "screens"]}]

    def test_the_suggestions_are_the_beats_own_phrases(self) -> None:
        """Recombining ranked tokens gave "base control", which asks for nothing."""
        from .scene_match import suggested_queries
        queries = suggested_queries(self.BEATS, [1, 2, 3])
        self.assertIn("rocket base", queries)
        self.assertIn("launch platform", queries)

    def test_no_suggestion_is_longer_than_a_catalogue_can_take(self) -> None:
        from .scene_match import suggested_queries
        for query in suggested_queries(self.BEATS, [1, 2, 3]):
            self.assertLessEqual(len(query.split()), 2, query)

    def test_only_the_unmatched_beats_shape_the_search(self) -> None:
        from .scene_match import suggested_queries
        queries = suggested_queries(self.BEATS, [3])
        self.assertIn("mission control", queries)
        self.assertFalse(any("rocket" in query for query in queries), queries)

    def test_the_same_failure_always_suggests_the_same_search(self) -> None:
        """Requirements arrive as a set, whose order changes with the hash seed."""
        from .scene_match import suggested_queries
        first = suggested_queries(self.BEATS, [1, 2, 3])
        self.assertEqual(first, suggested_queries(self.BEATS, [1, 2, 3]))
        self.assertEqual(first, sorted(first, key=first.index))

    def test_a_word_too_broad_to_search_on_is_left_out(self) -> None:
        from .scene_match import suggested_queries
        queries = suggested_queries([{"must_show": ["vehicle hardware", "clamp"]}], [1])
        self.assertNotIn("vehicle", " ".join(queries))
        self.assertIn("clamp", queries)

    def test_the_failure_carries_the_beats_and_the_queries(self) -> None:
        from .source_pool import UnmatchedBeats
        error = UnmatchedBeats("nothing matched", unmatched=[4, 5], retry_queries=["rocket clamp"])
        self.assertEqual(error.unmatched, [4, 5])
        self.assertEqual(error.retry_queries, ["rocket clamp"])


class WideningRoundTests(unittest.TestCase):
    """A plan that cannot serve a beat is a search that has not been run yet."""

    def _catalogue(self, query, limit):
        subject = query.split()[0]
        return [{"candidate_id": f"{subject.upper()}{n}", "title": query,
                 "source_family": "NASA Images",
                 "direct_download_url": f"https://images-assets.nasa.gov/video/{subject}{n}/x~orig.mp4",
                 "catalog_page_url": "", "asset_listing_url": "",
                 "review_frame_urls": [f"https://x/{n}-{i}.jpg" for i in range(1, 6)],
                 "source_width": 1920, "source_height": 1080, "source_duration": "0:00:40",
                 "technical_status": "ELIGIBLE_FHD_OR_HIGHER"} for n in range(3)][:limit]

    def _widen(self, known, queries):
        from .source_pool import widen_for_beats
        return widen_for_beats(known, queries, "https://w.app",
                               search=self._catalogue,
                               measure=lambda url: (40.0, 1920, 1080),
                               build=lambda urls: ("e" * 32, 5))

    def test_a_second_round_adds_works_rather_than_replacing_them(self) -> None:
        found = self._widen([{"candidate_id": "CLAMP0"}], ["clamp arms", "launch platform"])
        self.assertTrue(found)
        self.assertNotIn("CLAMP0", [work["candidate_id"] for work in found])

    def test_the_new_works_arrive_with_sheets_to_look_at(self) -> None:
        found = self._widen([], ["clamp arms"])
        self.assertTrue(all(work["contact_sheet_url"].startswith("https://w.app/storyboards/")
                            for work in found))
        self.assertTrue(all(work["frames"] for work in found))

    def test_no_queries_means_no_search(self) -> None:
        self.assertEqual(self._widen([], []), [])

    def test_a_round_is_bounded(self) -> None:
        """A subject the library does not hold will not appear on the third try."""
        from .source_pool import MAX_WIDENING_ROUNDS, WORKS_PER_WIDENING
        self.assertLessEqual(MAX_WIDENING_ROUNDS, 2)
        found = self._widen([], ["clamp arms", "launch platform", "mission control"])
        self.assertLessEqual(len(found), WORKS_PER_WIDENING)


class ObservationStateTests(unittest.TestCase):
    """A second look describes only the new works; the first round must survive."""

    WORKS = [{"candidate_id": "A", "frames": [{"index": 1, "at_seconds": 3.0},
                                              {"index": 2, "at_seconds": 9.0}]},
             {"candidate_id": "B", "frames": [{"index": 1, "at_seconds": 3.0}]}]

    def test_two_rounds_of_observations_accumulate(self) -> None:
        from .source_pool import apply_observations, observation_map
        first = observation_map([{"candidate_id": "A",
                                  "frames": [{"index": 1, "describes": "a rocket at the pad"}]}])
        second = observation_map([{"candidate_id": "B",
                                   "frames": [{"index": 1, "describes": "a control room"}]}])
        merged = apply_observations(self.WORKS, {**first, **second})
        described = {work["candidate_id"]: work["frames"][0]["describes"] for work in merged}
        self.assertEqual(described["A"], "a rocket at the pad")
        self.assertEqual(described["B"], "a control room")

    def test_a_later_round_can_correct_an_earlier_frame(self) -> None:
        from .source_pool import apply_observations, observation_map
        first = observation_map([{"candidate_id": "A",
                                  "frames": [{"index": 1, "describes": "blurred frame"}]}])
        second = observation_map([{"candidate_id": "A",
                                   "frames": [{"index": 1, "describes": "a rocket at the pad"}]}])
        merged = apply_observations(self.WORKS, {**first, **second})
        self.assertEqual(merged[0]["frames"][0]["describes"], "a rocket at the pad")

    def test_a_frame_nobody_described_stays_empty(self) -> None:
        from .source_pool import apply_observations, observation_map
        merged = apply_observations(self.WORKS, observation_map(
            [{"candidate_id": "A", "frames": [{"index": 1, "describes": "sky"}]}]))
        self.assertEqual(merged[0]["frames"][1]["describes"], "")

    def test_the_map_survives_a_round_trip_through_json(self) -> None:
        """It is stored in Redis between rounds, so its keys must be strings."""
        import json
        from .source_pool import apply_observations, observation_map
        described = observation_map([{"candidate_id": "A",
                                      "frames": [{"index": 2, "describes": "exhaust plume"}]}])
        restored = json.loads(json.dumps(described))
        merged = apply_observations(self.WORKS, restored)
        self.assertEqual(merged[0]["frames"][1]["describes"], "exhaust plume")


class ObservationNamingTests(unittest.TestCase):
    """Which work a description belongs to, when the id came back mistyped.

    A live run lost every description at once: the vision pass answered with
    work ids that matched nothing in the pool, so the matcher was told that none
    of eight clips had been looked at. Guessing by order would have paired each
    beat with whatever footage happened to be listed there, which is the exact
    failure this pass exists to prevent, so an unrecognisable name is dropped
    and said out loud instead.
    """

    KNOWN = [{"candidate_id": "KSC-20190914-RV-ILW01_0001-Wet_Flow-3231741"},
             {"candidate_id": "PSI_Test-ID_28"}]

    def name(self, entry):
        from .source_pool import name_observed_work
        return name_observed_work(entry, self.KNOWN)

    def test_the_id_copied_back_exactly(self) -> None:
        self.assertEqual(self.name({"candidate_id": "PSI_Test-ID_28"}), "PSI_Test-ID_28")

    def test_the_same_id_in_another_spelling(self) -> None:
        """Underscores dropped, hyphens added, case changed: still that work."""
        self.assertEqual(self.name({"candidate_id": "psi test id 28"}), "PSI_Test-ID_28")
        self.assertEqual(self.name({"candidate_id": "KSC 20190914 RV ILW01 0001 wet flow 3231741"}),
                         "KSC-20190914-RV-ILW01_0001-Wet_Flow-3231741")

    def test_the_image_number_when_the_id_is_wrong(self) -> None:
        self.assertEqual(self.name({"candidate_id": "image two", "image": 2}), "PSI_Test-ID_28")

    def test_the_image_number_alone(self) -> None:
        self.assertEqual(self.name({"image": 1}),
                         "KSC-20190914-RV-ILW01_0001-Wet_Flow-3231741")

    def test_an_unknown_name_is_dropped_rather_than_guessed(self) -> None:
        self.assertEqual(self.name({"candidate_id": "STS-51L-something-else"}), "")
        self.assertEqual(self.name({"candidate_id": "x", "image": 9}), "")

    def test_the_order_entries_arrive_in_is_never_used(self) -> None:
        """Two unrecognisable entries stay unrecognised, however they are ordered."""
        from .source_pool import observation_map
        described = observation_map(
            [{"candidate_id": "wrong one", "frames": [{"index": 1, "describes": "a pad"}]},
             {"candidate_id": "wrong two", "frames": [{"index": 1, "describes": "a tower"}]}],
            self.KNOWN)
        self.assertEqual(described, {})

    def test_the_names_that_fit_nothing_are_reported(self) -> None:
        from .source_pool import unplaced_observations
        self.assertEqual(unplaced_observations(
            [{"candidate_id": "PSI_Test-ID_28"}, {"candidate_id": "invented"}], self.KNOWN),
            ["invented"])

    def test_without_a_pool_the_id_is_taken_as_given(self) -> None:
        """The plan can also be asked for with the works spelled out in full."""
        from .source_pool import name_observed_work
        self.assertEqual(name_observed_work({"candidate_id": "anything"}, []), "anything")


class RequirementCountingTests(unittest.TestCase):
    """A beat asks for things. Counting its words instead punished good briefs.

    Measured on a live refusal: a beat whose must_show read "Stationary rocket",
    "Launch pad or support structure" and "Engine activity or exhaust" became
    nine required words, so footage of a rocket on a launch pad matched three of
    nine and scored 0.25 against a floor of 0.34. It was turned down for showing
    what was asked.
    """

    NAMED = {"must_show": ["rocket", "launch pad", "hold down"],
             "visual_target": "A rocket stands on its launch pad",
             "spoken_phrase": "The rocket remains fixed to its pad"}

    def test_a_thing_named_in_four_words_still_counts_once(self) -> None:
        from .scene_match import required_items
        wordy = {"must_show": ["Launch pad or support structure"]}
        self.assertEqual(len(required_items(wordy)), 1)

    def test_footage_of_the_pad_satisfies_a_pad_beat(self) -> None:
        seen = terms("Rocket standing on a launch pad, exhaust below, service tower beside it")
        self.assertGreater(match_score(self.NAMED, seen), MATCH_FLOOR)

    def test_ascent_footage_still_fails_that_same_beat(self) -> None:
        seen = terms("A rocket high in the sky trailing a long exhaust plume")
        self.assertLess(match_score(self.NAMED, seen), MATCH_FLOOR)

    def test_a_two_word_name_needs_both_words(self) -> None:
        from .scene_match import item_is_shown
        self.assertFalse(item_is_shown(terms("rocket base"), terms("a rocket in flight")))
        self.assertTrue(item_is_shown(terms("rocket base"), terms("the base of the rocket")))

    def test_a_longer_entry_is_met_by_half_its_words(self) -> None:
        from .scene_match import item_is_shown
        self.assertTrue(item_is_shown(terms("rocket exhaust plume"),
                                      terms("a rocket with a long exhaust trail")))

    def test_clamps_are_not_satisfied_by_arms(self) -> None:
        """Two words, both needed: holding something is not a clamp."""
        from .scene_match import item_is_shown
        self.assertFalse(item_is_shown(terms("hold down clamps"),
                                       terms("hold down arms gripping the vehicle")))

    def test_a_doubled_consonant_does_not_hide_a_match(self) -> None:
        self.assertEqual(terms("gripping"), terms("grips"))
        self.assertEqual(terms("running"), terms("runs"))


class SlateTests(unittest.TestCase):
    """A NASA title card is not footage, and must never be cut into a Short.

    A measured contact sheet came back with four of one clip's five tiles
    reading "title card". Scored as words, "title" and "card" simply failed to
    match anything, which is harmless; but a window resting on them was still
    offered, and a beat with loose requirements could have taken it.
    """

    FRAMES = [{"index": 1, "at_seconds": 2.0, "describes": "title card"},
              {"index": 2, "at_seconds": 8.0, "describes": "Title card showing TW@N text "
                                                           "over a starry space background"},
              {"index": 3, "at_seconds": 14.0, "describes": "Rocket lifting off a coastal "
                                                            "launch pad in white smoke"},
              {"index": 4, "at_seconds": 20.0, "describes": "black frame"}]

    def test_a_window_resting_on_a_slate_offers_nothing(self) -> None:
        self.assertEqual(window_terms(self.FRAMES, 1.0, 4.2), set())

    def test_a_slate_that_goes_on_to_describe_the_graphic_is_still_a_slate(self) -> None:
        self.assertEqual(window_terms(self.FRAMES, 7.0, 10.2), set())

    def test_a_window_on_real_footage_keeps_its_words(self) -> None:
        self.assertIn("rocket", window_terms(self.FRAMES, 13.0, 16.2))

    def test_a_neighbouring_slate_adds_nothing_to_a_real_window(self) -> None:
        seen = window_terms(self.FRAMES, 13.0, 16.2)
        self.assertNotIn("card", seen)
        self.assertNotIn("starry", seen)

    def test_a_black_frame_is_not_footage_either(self) -> None:
        self.assertEqual(window_terms(self.FRAMES, 19.0, 22.2), set())


class StemmingTests(unittest.TestCase):
    """The words this footage is actually described in have to meet each other."""

    def test_the_words_a_launch_is_described_in(self) -> None:
        for one, other in [("pads", "pad"), ("flames", "flame"), ("clamps", "clamp"),
                           ("grips", "gripping"), ("runs", "running"),
                           ("mounted", "mounts"), ("lifted", "lifts"),
                           ("structures", "structure"), ("skies", "sky"),
                           ("exhausts", "exhaust")]:
            with self.subTest(one=one, other=other):
                self.assertEqual(terms(one), terms(other))

    def test_short_words_are_left_alone(self) -> None:
        self.assertEqual(terms("gas"), {"gas"})
        self.assertEqual(terms("across"), {"across"})


class RetryQueryTests(unittest.TestCase):
    """What to search for next, once a brief names single things.

    Telling the planner to write must_show as short names fixed the scoring and
    broke the retry: "clamp", "sky" and "exhaust" went back to the catalogue on
    their own, and a widening round came home with a novelty yule-log video of
    rocket nozzles in a stone fireplace.
    """

    BEATS = [{"must_show": ["rocket", "launch pad", "service tower"]},
             {"must_show": ["rocket", "flames", "launch pad"]},
             {"must_show": ["clamps", "rocket"]},
             {"must_show": ["rocket", "sky"]}]

    def test_a_single_name_is_paired_with_the_script_s_subject(self) -> None:
        from .scene_match import suggested_queries
        self.assertIn("rocket clamp", suggested_queries(self.BEATS, [3]))

    def test_the_subject_itself_is_not_doubled(self) -> None:
        from .scene_match import suggested_queries
        found = suggested_queries(self.BEATS, [3])
        self.assertIn("rocket", found)
        self.assertNotIn("rocket rocket", found)

    def test_a_two_word_name_is_left_as_it_is(self) -> None:
        from .scene_match import suggested_queries
        self.assertIn("launch pad", suggested_queries(self.BEATS, [1]))

    def test_the_same_failure_suggests_the_same_search(self) -> None:
        from .scene_match import suggested_queries
        self.assertEqual(suggested_queries(self.BEATS, [3, 4]),
                         suggested_queries(self.BEATS, [3, 4]))


class SameThirdFallbackTests(unittest.TestCase):
    """One stubborn beat must not cost the whole Short.

    A measured run matched seventeen beats of eighteen and refused, because
    beat 17's brief asked for "open sky" and nobody describing a still writes
    "open". The script is written in three thirds and each third is one visual
    subject by instruction, so that beat's neighbours were written to need the
    same picture: giving it their footage uses a guarantee the pipeline already
    makes, rather than guessing.
    """

    # Six beats, so the thirds are two beats each and the last two are the
    # ascent, exactly as an eighteen-beat script's last third behaves.
    BEATS = [{"must_show": ["rocket", "launch pad"], "visual_target": "A rocket on its launch pad",
              "spoken_phrase": "A rocket waits on the pad"},
             {"must_show": ["launch pad", "smoke"], "visual_target": "Smoke across the launch pad",
              "spoken_phrase": "Smoke spreads across the pad"},
             {"must_show": ["flame", "exhaust"], "visual_target": "Flame and exhaust below",
              "spoken_phrase": "Flame grows beneath the rocket"},
             {"must_show": ["exhaust", "ground"], "visual_target": "Exhaust across the ground",
              "spoken_phrase": "Exhaust spreads across the ground"},
             {"must_show": ["rocket", "sky"], "visual_target": "The rocket climbs through the sky",
              "spoken_phrase": "The rocket climbs away"},
             {"must_show": ["open sky", "rocket"], "visual_target": "Open sky around the rocket",
              "spoken_phrase": "Open sky surrounds the rising rocket"}]

    def windows(self) -> list[dict]:
        return [window("PAD", 4.0, "A rocket standing on a launch pad beside a tower"),
                window("SMOKE", 8.0, "Smoke and steam spreading across the launch pad"),
                window("FLAME", 12.0, "Bright flame and exhaust burning below the vehicle"),
                window("GROUND", 16.0, "Exhaust rolling across the ground around the pad"),
                window("ASCENT", 20.0, "A rocket climbing high through a clear sky trailing exhaust"),
                window("ASCENT", 28.0, "A rocket high in the sky above thin cloud")]

    def test_the_stubborn_beat_is_served_by_its_neighbour_s_work(self) -> None:
        result = plan_by_content(self.BEATS, self.windows())
        self.assertEqual(result["unmatched_beats"], [])

    def test_a_borrowed_beat_says_so(self) -> None:
        result = plan_by_content(self.BEATS, self.windows())
        borrowed = [entry for entry in result["plan"] if entry.get("served_by")]
        self.assertEqual([entry["beat"] for entry in borrowed], [6])
        self.assertEqual(borrowed[0]["served_by"], "same third")
        self.assertEqual(borrowed[0]["candidate_id"], "ASCENT")

    def test_a_borrowed_beat_still_carries_terms_to_describe(self) -> None:
        result = plan_by_content(self.BEATS, self.windows())
        borrowed = next(entry for entry in result["plan"] if entry.get("served_by"))
        self.assertTrue(borrowed["matched_terms"])

    def test_a_beat_from_another_subject_is_not_called_a_third_match(self) -> None:
        """It is still served, but the mark says where that footage came from."""
        beats = list(self.BEATS)
        beats[5] = {"must_show": ["seafloor", "submarine"],
                    "visual_target": "A submarine resting on the seafloor",
                    "spoken_phrase": "A submarine rests on the seafloor"}
        result = plan_by_content(beats, self.windows())
        self.assertEqual(result["unmatched_beats"], [])
        stray = next(entry for entry in result["plan"] if entry["beat"] == 6)
        self.assertEqual(stray["served_by"], "best available")

    def test_a_scored_beat_is_never_marked_as_borrowed(self) -> None:
        result = plan_by_content(self.BEATS, self.windows())
        scored = [entry for entry in result["plan"] if entry["beat"] != 6]
        self.assertTrue(scored)
        self.assertFalse([entry for entry in scored if entry.get("served_by")])


class NeverRefuseTests(unittest.TestCase):
    """The channel ships a Short. It does not hold out for proof on every beat.

    The channels this competes with do not prove that shot eleven illustrates
    sentence eleven: they pick footage on the topic, cut it fast and let pace
    and captions carry it. Two live runs were thrown away for being right about
    seventeen beats of eighteen, which is worse by any measure a viewer can see.
    What is kept is everything a viewer would notice: no slates, no repeats, no
    single work carrying the Short, and a mark on every unproved pairing.
    """

    BEATS = [{"must_show": ["rocket", "launch pad"], "visual_target": "A rocket on its pad",
              "spoken_phrase": "A rocket waits on the launch pad"},
             {"must_show": ["submarine", "seafloor"], "visual_target": "A submarine on the seafloor",
              "spoken_phrase": "A submarine rests on the seafloor"},
             {"must_show": ["orchestra", "violin"], "visual_target": "An orchestra playing",
              "spoken_phrase": "An orchestra plays on a stage"}]

    def windows(self) -> list[dict]:
        return [window("PAD", 4.0, "A rocket standing on a launch pad beside a tall tower"),
                window("SMOKE", 9.0, "White smoke rolling across the ground below a rocket"),
                window("SKY", 14.0, "A rocket climbing through a clear blue sky")]

    def test_every_beat_is_served(self) -> None:
        result = plan_by_content(self.BEATS, self.windows())
        self.assertEqual(result["unmatched_beats"], [])
        self.assertEqual(len(result["plan"]), 3)

    def test_the_unproved_ones_are_marked(self) -> None:
        result = plan_by_content(self.BEATS, self.windows())
        marked = {entry["beat"] for entry in result["plan"] if entry.get("served_by")}
        self.assertEqual(marked, {2, 3})

    def test_a_slate_is_still_never_used(self) -> None:
        """Slate windows carry no terms, and a window with no terms is skipped."""
        slates = [window("PAD", 4.0, "A rocket standing on a launch pad beside a tall tower"),
                  {**window("CARD", 9.0, ""), "seen": set()},
                  {**window("CARD", 14.0, ""), "seen": set()}]
        result = plan_by_content(self.BEATS, slates)
        self.assertEqual({entry["candidate_id"] for entry in result["plan"]}, {"PAD"})

    def test_no_window_is_handed_out_twice(self) -> None:
        result = plan_by_content(self.BEATS, self.windows())
        used = [(entry["candidate_id"], entry["shot_start_seconds"]) for entry in result["plan"]]
        self.assertEqual(len(used), len(set(used)))
