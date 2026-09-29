from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "PictologicsSlicer"))

from PictologicsLib.inline_config import (
    FILTER_DEFAULTS,
    FILTER_PARAMETERS,
    build_inline_configuration_document,
    default_inline_state,
    filter_defaults,
    lint_configuration_document,
)
from PictologicsLib.profiles import build_profile, validate_profile


def filtered_state(kind: str, **changes: object) -> dict[str, object]:
    state = default_inline_state()
    state.update(
        filter=True,
        filter_type=kind,
        filter_params=filter_defaults(kind),
        filter_outliers=True,
    )
    state.update(changes)
    return state


def steps(state: dict[str, object]) -> list[dict[str, object]]:
    document = build_inline_configuration_document(state)
    return list(document["configs"]["in_app"]["steps"])


class FilterStepTests(unittest.TestCase):
    def test_off_by_default(self) -> None:
        self.assertFalse(default_inline_state()["filter"])
        self.assertNotIn("filter", [step["step"] for step in steps(default_inline_state())])

    def test_default_parameters_are_independent(self) -> None:
        state = default_inline_state()
        state["filter_params"]["sigma_mm"] = 25
        self.assertEqual(default_inline_state()["filter_params"], filter_defaults("log"))
        self.assertEqual(FILTER_DEFAULTS["filter_params"], filter_defaults("log"))

    def test_every_type_gives_a_valid_step_before_discretisation(self) -> None:
        for filter_type in FILTER_PARAMETERS:
            with self.subTest(filter_type=filter_type):
                state = filtered_state(filter_type)
                order = [step["step"] for step in steps(state)]
                self.assertEqual(
                    order,
                    ["resample", "filter_outliers", "filter", "discretise", "extract_features"],
                )
                params = steps(state)[2]["params"]
                self.assertEqual(params, {"type": filter_type, **filter_defaults(filter_type)})
                self.assertEqual(
                    lint_configuration_document(build_inline_configuration_document(state)), []
                )

    def test_boundary_is_written_only_when_chosen(self) -> None:
        params = steps(filtered_state("mean", filter_boundary="mirror"))[2]["params"]
        self.assertEqual(params["boundary"], "mirror")
        self.assertEqual(steps(filtered_state("mean", filter_params={"support": 3.0}))[2]["params"]["support"], 3)

    def test_bad_settings_are_refused(self) -> None:
        laws = filter_defaults("laws")
        cases = [
            ({"filter_type": "riesz"}, "Unknown image filter"),
            ({"filter_boundary": "reflect"}, "Unknown filter boundary"),
            ({"filter_params": {}}, "needs these parameters"),
            ({"filter_params": {**laws, "rotation_invariant": 1}}, "on or off"),
            ({"filter_params": {**laws, "energy_distance": 2.5}}, "whole number"),
            ({"filter_params": {**laws, "energy_distance": 99}}, "from 1 to 50"),
            ({"filter_params": {**laws, "pooling": "median"}}, "one of"),
            ({"filter_params": {**laws, "kernel": "L5E5"}}, "look like L5E5E5"),
        ]
        for changes, message in cases:
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, message):
                steps(filtered_state("laws", **changes))
        wavelet = {**filter_defaults("wavelet"), "decomposition": "LXH"}
        with self.assertRaisesRegex(ValueError, "look like LLH"):
            steps(filtered_state("wavelet", filter_params=wavelet))


class FilterProfileTests(unittest.TestCase):
    def test_invalid_filter_settings_are_rejected_even_when_disabled(self) -> None:
        for enabled in (False, True):
            for changes in (
                {"filter_type": []},
                {"filter_type": "unknown"},
                {"filter_boundary": "unknown"},
                {"filter_params": {}},
                {"filter_params": {"sigma_mm": 1.23456, "truncate": 4.0}},
                {"filter_params": {"sigma_mm": "1.5", "truncate": 4.0}},
                {"filter_params": {"sigma_mm": True, "truncate": 4.0}},
            ):
                with self.subTest(enabled=enabled, changes=changes), self.assertRaises(ValueError):
                    build_profile("Invalid", [], filtered_state("log", filter=enabled, **changes))

    def test_all_filter_profiles_round_trip_at_editor_precision(self) -> None:
        for kind in FILTER_PARAMETERS:
            with self.subTest(kind=kind):
                profile = build_profile("Filter", [], filtered_state(kind))
                self.assertEqual(validate_profile(profile), profile)

    def test_filter_settings_round_trip_and_old_profiles_load_without_a_filter(self) -> None:
        profile = build_profile("Filtered", [], filtered_state("gabor"))
        self.assertEqual(validate_profile(profile)["inline_state"]["filter_type"], "gabor")
        old = dict(profile, inline_state={
            key: value for key, value in profile["inline_state"].items() if key not in FILTER_DEFAULTS
        })
        self.assertFalse(validate_profile(old)["inline_state"]["filter"])
        with self.assertRaisesRegex(ValueError, "on or off|booleans"):
            validate_profile(dict(profile, inline_state={**profile["inline_state"], "filter": "yes"}))


if __name__ == "__main__":
    unittest.main()
