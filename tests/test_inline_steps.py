"""The mask, normalisation, discretisation and feature options of the in-app builder."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "PictologicsSlicer"))

from PictologicsLib.inline_config import (
    build_inline_configuration_document,
    default_inline_state,
    lint_configuration_document,
)
from PictologicsLib.profiles import build_profile


def steps(**changes: object) -> list[dict[str, object]]:
    document = build_inline_configuration_document({**default_inline_state(), **changes})
    assert lint_configuration_document(document) == []
    return list(document["configs"]["in_app"]["steps"])


def step(name: str, **changes: object) -> dict[str, object]:
    return next(item["params"] for item in steps(**changes) if item["step"] == name)


class StepOrderTests(unittest.TestCase):
    def test_every_step_runs_in_the_order_of_the_panel(self) -> None:
        order = [item["step"] for item in steps(
            grow_mask=True, normalise=True, resegment=True, range_min=-3, filter_outliers=True,
            keep_largest=True, interpolation="cubic",
        )]
        self.assertEqual(order, [
            "resample", "grow_mask", "normalise", "resegment", "filter_outliers",
            "keep_largest_component", "discretise", "extract_features",
        ])
        self.assertEqual(step("resample", interpolation="cubic")["interpolation"], "cubic")


class MaskStepTests(unittest.TestCase):
    def test_growth_and_rings(self) -> None:
        self.assertEqual(step("grow_mask", grow_mask=True), {"to_mm": 3.0, "apply_to": "both"})
        self.assertEqual(
            step("grow_mask", grow_mask=True, grow_to_mm=5, grow_from_mm="2", grow_apply_to="morph"),
            {"to_mm": 5.0, "from_mm": 2.0, "apply_to": "morph"},
        )
        self.assertEqual(step("grow_mask", grow_mask=True, grow_to_mm=0, grow_from_mm=-1)["from_mm"], -1.0)
        for changes, message in (
            ({"grow_to_mm": 101}, "from -100 to 100"),
            ({"grow_to_mm": "far"}, "finite number"),
            ({"grow_from_mm": 3}, "less than the growth distance"),
            ({"grow_apply_to": "all"}, "mask target"),
        ):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, message):
                steps(grow_mask=True, **changes)

    def test_keep_largest_part(self) -> None:
        self.assertEqual(step("keep_largest_component", keep_largest=True), {"apply_to": "both"})
        with self.assertRaisesRegex(ValueError, "mask target"):
            steps(keep_largest=True, keep_largest_apply_to=None)


class NormaliseTests(unittest.TestCase):
    def test_methods_regions_and_limits(self) -> None:
        self.assertEqual(step("normalise", normalise=True), {"method": "zscore", "region": "image"})
        self.assertEqual(
            step("normalise", normalise=True, normalise_method="percentile", normalise_region="roi",
                 normalise_percentiles=[5, 95], normalise_range_min="10"),
            {"method": "percentile", "region": "roi", "percentiles": [5.0, 95.0], "range_min": 10.0},
        )
        for changes, message in (
            ({"normalise_method": "minmax"}, "Unknown normalisation"),
            ({"normalise_region": "body"}, "Unknown normalisation"),
            ({"normalise_method": "percentile", "normalise_percentiles": [99, 1]}, "rise from 0 to 100"),
            ({"normalise_method": "percentile", "normalise_percentiles": [1]}, "rise from 0 to 100"),
            ({"normalise_range_min": 5, "normalise_range_max": 1}, "must not exceed"),
        ):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, message):
                steps(normalise=True, **changes)


class DiscretiseAndFeatureTests(unittest.TestCase):
    def test_fixed_bin_edges(self) -> None:
        self.assertEqual(
            step("discretise", discretise_method="FIXED_CUTOFFS", discretise_cutoffs="-100, 0 100"),
            {"method": "FIXED_CUTOFFS", "cutoffs": [-100.0, 0.0, 100.0]},
        )
        for cutoffs, message in ((None, "at least one number"), ("", "at least one number"),
                                 ("0, 0", "rise from left to right"), ("0, x", "finite number")):
            with self.subTest(cutoffs=cutoffs), self.assertRaisesRegex(ValueError, message):
                steps(discretise_method="FIXED_CUTOFFS", discretise_cutoffs=cutoffs)

    def test_texture_and_ivh_options_are_written_only_when_used(self) -> None:
        self.assertEqual(step("extract_features"), {"families": default_inline_state()["families"]})
        params = step("extract_features", texture_distance=2, ngldm_alpha=1, ivh_use_continuous=True)
        self.assertEqual(params["texture_matrix_params"], {
            "glcm_distance": 2, "ngtdm_distance": 2, "ngldm_distance": 2, "ngldm_alpha": 1})
        self.assertTrue(params["ivh_use_continuous"])
        quiet = step("extract_features", families=["intensity"], discretise=False, texture_distance=2,
                     ivh_use_continuous=True)
        self.assertEqual(quiet, {"families": ["intensity"]})
        for changes in ({"texture_distance": 0}, {"texture_distance": 1.5}, {"ngldm_alpha": -1}):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, "whole number"):
                steps(**changes)


class StepProfileTests(unittest.TestCase):
    def test_new_settings_round_trip_and_bad_values_are_refused(self) -> None:
        state = {**default_inline_state(), "grow_mask": True, "grow_from_mm": "0", "normalise": True,
                 "normalise_method": "percentile", "keep_largest": True, "texture_distance": 3,
                 "discretise_method": "FIXED_CUTOFFS", "discretise_cutoffs": "-50, 50"}
        self.assertEqual(build_profile("Steps", [], state)["inline_state"], state)
        for changes, message in (
            ({"normalise_percentiles": [1]}, "two numbers"),
            ({"normalise_percentiles": [1, 101]}, "editor's range"),
            ({"grow_to_mm": 1.2345}, "editor's range"),
            ({"texture_distance": 21}, "whole numbers"),
            ({"ngldm_alpha": True}, "whole numbers"),
            ({"normalise_region": "body"}, "normalisation method"),
            ({"discretise_cutoffs": [1, 2]}, "must be text"),
            ({"discretise_cutoffs": "a"}, "finite number"),
            ({"grow_apply_to": "all"}, "mask target"),
            ({"keep_largest": 1}, "booleans"),
        ):
            with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, message):
                build_profile("Invalid", [], {**state, **changes})


if __name__ == "__main__":
    unittest.main()
