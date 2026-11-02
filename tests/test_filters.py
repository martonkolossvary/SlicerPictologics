from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "PictologicsSlicer"))

from PictologicsLib.inline_config import (
    FILTER_PARAMETERS,
    build_inline_configuration_document,
    default_filter,
    default_inline_state,
    filter_defaults,
    lint_configuration_document,
)
from PictologicsLib.profiles import build_profile, validate_profile

RIESZ = {"riesz": "base", "riesz_log": "log", "riesz_simoncelli": "simoncelli"}


def entry(kind: str, **changes: object) -> dict[str, object]:
    return {**default_filter(kind), **changes}


def filtered_state(*entries: dict[str, object], **changes: object) -> dict[str, object]:
    state = default_inline_state()
    state.update(filter=True, filters=list(entries), filter_outliers=True)
    state.update(changes)
    return state


def configs(state: dict[str, object]) -> dict[str, list[dict[str, object]]]:
    document = build_inline_configuration_document(state)
    return {name: config["steps"] for name, config in document["configs"].items()}


def expected_params(kind: str) -> dict[str, object]:
    params = filter_defaults(kind)
    if kind in RIESZ:
        return {"type": "riesz", "variant": RIESZ[kind], **params, "order": [1, 0, 0]}
    return {"type": kind, **params}


class FilterStepTests(unittest.TestCase):
    def test_off_by_default(self) -> None:
        self.assertFalse(default_inline_state()["filter"])
        steps = configs(default_inline_state())["in_app"]
        self.assertNotIn("filter", [step["step"] for step in steps])

    def test_default_parameters_are_independent(self) -> None:
        state = default_inline_state()
        state["filters"][0]["params"]["sigma_mm"] = 25
        self.assertEqual(default_inline_state()["filters"], [default_filter("log")])
        self.assertEqual(default_filter()["params"], filter_defaults("log"))

    def test_every_type_gives_a_valid_step_before_discretisation(self) -> None:
        for kind in FILTER_PARAMETERS:
            with self.subTest(kind=kind):
                state = filtered_state(entry(kind))
                self.assertEqual(list(configs(state)), [f"in_app_{kind}_1"])
                steps = configs(state)[f"in_app_{kind}_1"]
                self.assertEqual(
                    [step["step"] for step in steps],
                    ["resample", "filter_outliers", "filter", "discretise", "extract_features"],
                )
                self.assertEqual(steps[2]["params"], expected_params(kind))
                self.assertEqual(lint_configuration_document(build_inline_configuration_document(state)), [])

    def test_a_filter_bank_gives_one_configuration_for_each_filter(self) -> None:
        state = filtered_state(
            entry("log", params={"sigma_mm": 1.0, "truncate": 4.0}),
            entry("log", params={"sigma_mm": 2.0, "truncate": 4.0}),
            entry("wavelet"),
            include_unfiltered=True,
        )
        result = configs(state)
        self.assertEqual(list(result), ["in_app", "in_app_log_1", "in_app_log_2", "in_app_wavelet_1"])
        self.assertNotIn("filter", [step["step"] for step in result["in_app"]])
        self.assertEqual([steps[2]["params"].get("sigma_mm") for steps in list(result.values())[1:3]], [1.0, 2.0])
        # The steps before the filter are the same, so Pictologics computes them once.
        self.assertEqual(result["in_app_log_1"][:2], result["in_app_wavelet_1"][:2])

    def test_boundary_is_written_only_when_chosen(self) -> None:
        params = configs(filtered_state(entry("mean", boundary="mirror")))["in_app_mean_1"][2]["params"]
        self.assertEqual(params["boundary"], "mirror")
        params = configs(filtered_state(entry("mean", params={"support": 3.0})))["in_app_mean_1"][2]["params"]
        self.assertEqual(params, {"type": "mean", "support": 3})

    def test_riesz_order_is_three_whole_numbers(self) -> None:
        params = configs(filtered_state(entry("riesz", params={"order": "0 2, 1"})))["in_app_riesz_1"][2]["params"]
        self.assertEqual(params["order"], [0, 2, 1])
        for order in ("1, 0", "0, 0, 0", "1.5, 0, 0", "-1, 1, 0", "", "a, b, c"):
            with self.subTest(order=order), self.assertRaises(ValueError):
                configs(filtered_state(entry("riesz", params={"order": order})))

    def test_bad_settings_are_refused(self) -> None:
        laws = filter_defaults("laws")
        cases = [
            ({"type": "unknown"}, "Unknown image filter"),
            ({"boundary": "reflect"}, "Unknown filter boundary"),
            ({"params": {}}, "needs these parameters"),
            ({"params": {**laws, "rotation_invariant": 1}}, "on or off"),
            ({"params": {**laws, "energy_distance": 2.5}}, "whole number"),
            ({"params": {**laws, "energy_distance": 99}}, "from 1 to 50"),
            ({"params": {**laws, "pooling": "median"}}, "one of"),
            ({"params": {**laws, "kernel": "L5E5"}}, "look like L5E5E5"),
        ]
        for changes, message in cases:
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, message):
                configs(filtered_state(entry("laws", **changes)))
        wavelet = {**filter_defaults("wavelet"), "decomposition": "LXH"}
        with self.assertRaisesRegex(ValueError, "look like LLH"):
            configs(filtered_state(entry("wavelet", params=wavelet)))
        with self.assertRaisesRegex(ValueError, "Add a filter"):
            configs(filtered_state())


class FilterProfileTests(unittest.TestCase):
    def test_invalid_filter_settings_are_rejected_even_when_disabled(self) -> None:
        for enabled in (False, True):
            for changes in (
                {"type": []},
                {"type": "unknown"},
                {"boundary": "unknown"},
                {"params": {}},
                {"params": {"sigma_mm": 1.23456, "truncate": 4.0}},
                {"params": {"sigma_mm": "1.5", "truncate": 4.0}},
                {"params": {"sigma_mm": True, "truncate": 4.0}},
                {"extra": 1},
            ):
                with self.subTest(enabled=enabled, changes=changes), self.assertRaises(ValueError):
                    build_profile("Invalid", [], filtered_state(entry("log", **changes), filter=enabled))
        for filters in ([], "log", [["log"]]):
            with self.subTest(filters=filters), self.assertRaisesRegex(ValueError, "list of filter settings"):
                build_profile("Invalid", [], filtered_state(filter=False, filters=filters))

    def test_all_filter_profiles_round_trip_at_editor_precision(self) -> None:
        profile = build_profile("Filters", [], filtered_state(*(entry(kind) for kind in FILTER_PARAMETERS)))
        self.assertEqual(validate_profile(profile), profile)
        self.assertEqual(len(profile["inline_state"]["filters"]), len(FILTER_PARAMETERS))

    def test_old_profiles_load_with_their_filter_or_without_one(self) -> None:
        state = default_inline_state()
        del state["filters"], state["include_unfiltered"], state["filter"]
        profile = build_profile("Old", [], state)
        self.assertFalse(profile["inline_state"]["filter"])
        old_filter = {"filter": True, "filter_type": "gabor", "filter_boundary": "zero",
                      "filter_params": filter_defaults("gabor")}
        profile = build_profile("Old filter", [], {**state, **old_filter})
        self.assertEqual(profile["inline_state"]["filters"], [entry("gabor", boundary="zero")])
        with self.assertRaisesRegex(ValueError, "on or off|booleans"):
            validate_profile(dict(profile, inline_state={**profile["inline_state"], "filter": "yes"}))


if __name__ == "__main__":
    unittest.main()
