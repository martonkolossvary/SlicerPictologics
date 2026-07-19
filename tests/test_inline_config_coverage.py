from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "PictologicsSlicer"))

from PictologicsLib.inline_config import (
    CORE_FEATURE_FAMILIES,
    INLINE_CONFIG_NAME,
    build_inline_configuration_document,
    default_inline_state,
    lint_configuration_document,
    preset_configuration_document,
    preset_names,
)


class DefaultStateTests(unittest.TestCase):
    def test_default_inline_state_shape(self) -> None:
        state = default_inline_state()
        self.assertEqual(state["families"], list(CORE_FEATURE_FAMILIES))
        self.assertTrue(state["resample"])
        self.assertEqual(state["spacing"], [0.5, 0.5, 0.5])
        self.assertEqual(state["discretise_method"], "FBN")
        self.assertEqual(state["source_mode"], "full_image")
        self.assertIsNone(state["sentinel_value"])


class BuildInlineConfigTests(unittest.TestCase):
    def test_default_state_builds_expected_steps(self) -> None:
        document = build_inline_configuration_document(default_inline_state())
        config = document["configs"][INLINE_CONFIG_NAME]
        self.assertEqual(
            [step["step"] for step in config["steps"]],
            ["resample", "discretise", "extract_features"],
        )
        self.assertEqual(document["schema_version"], "1.0")
        self.assertNotIn("sentinel_value", config)

    def test_no_families_is_rejected(self) -> None:
        state = default_inline_state()
        state["families"] = []
        with self.assertRaisesRegex(ValueError, "at least one feature family"):
            build_inline_configuration_document(state)

    def test_unknown_family_is_rejected(self) -> None:
        state = default_inline_state()
        state["families"] = ["intensity", "bogus_family"]
        with self.assertRaisesRegex(ValueError, "Unknown feature families: bogus_family"):
            build_inline_configuration_document(state)

    def test_resample_spacing_wrong_length_is_rejected(self) -> None:
        state = default_inline_state()
        state["spacing"] = [0.5, 0.5]
        with self.assertRaisesRegex(ValueError, "three positive numbers"):
            build_inline_configuration_document(state)

    def test_resample_spacing_non_positive_is_rejected(self) -> None:
        state = default_inline_state()
        state["spacing"] = [0.5, 0.5, -1.0]
        with self.assertRaisesRegex(ValueError, "three positive numbers"):
            build_inline_configuration_document(state)

    def test_unknown_interpolation_is_rejected(self) -> None:
        state = default_inline_state()
        state["interpolation"] = "cubic"
        with self.assertRaisesRegex(ValueError, "Unknown resample interpolation: cubic"):
            build_inline_configuration_document(state)

    def test_discretise_fbn_uses_n_bins(self) -> None:
        state = default_inline_state()
        state["discretise_method"] = "FBN"
        state["discretise_value"] = 32.0
        document = build_inline_configuration_document(state)
        params = document["configs"][INLINE_CONFIG_NAME]["steps"][1]["params"]
        self.assertEqual(params, {"method": "FBN", "n_bins": 32})

    def test_discretise_fbs_uses_bin_width(self) -> None:
        state = default_inline_state()
        state["discretise_method"] = "FBS"
        state["discretise_value"] = 16.0
        document = build_inline_configuration_document(state)
        params = document["configs"][INLINE_CONFIG_NAME]["steps"][1]["params"]
        self.assertEqual(params, {"method": "FBS", "bin_width": 16.0})

    def test_discretise_value_not_positive_is_rejected(self) -> None:
        state = default_inline_state()
        state["discretise_value"] = 0.0
        with self.assertRaisesRegex(ValueError, "bin count/width must be positive"):
            build_inline_configuration_document(state)

    def test_unknown_discretise_method_is_rejected(self) -> None:
        state = default_inline_state()
        state["discretise_method"] = "FBX"
        with self.assertRaisesRegex(ValueError, "Unknown discretisation method: FBX"):
            build_inline_configuration_document(state)

    def test_needs_discretisation_without_discretise_is_rejected(self) -> None:
        state = default_inline_state()
        state["discretise"] = False
        with self.assertRaisesRegex(ValueError, "require a discretise step"):
            build_inline_configuration_document(state)

    def test_unknown_source_mode_is_rejected(self) -> None:
        state = default_inline_state()
        state["source_mode"] = "sideways"
        with self.assertRaisesRegex(ValueError, "Unknown source mode: sideways"):
            build_inline_configuration_document(state)

    def test_sentinel_kept_only_for_non_full_image(self) -> None:
        state = default_inline_state()
        state["source_mode"] = "auto"
        state["sentinel_value"] = -1024.0
        document = build_inline_configuration_document(state)
        self.assertEqual(
            document["configs"][INLINE_CONFIG_NAME]["sentinel_value"], -1024.0
        )

    def test_sentinel_dropped_for_full_image(self) -> None:
        state = default_inline_state()
        state["source_mode"] = "full_image"
        state["sentinel_value"] = -1024.0
        document = build_inline_configuration_document(state)
        self.assertNotIn(
            "sentinel_value", document["configs"][INLINE_CONFIG_NAME]
        )

    def test_no_resample_no_discretise_intensity_only(self) -> None:
        state = {
            "families": ["intensity", "morphology"],
            "resample": False,
            "discretise": False,
            "source_mode": "full_image",
            "sentinel_value": None,
        }
        document = build_inline_configuration_document(state)
        steps = document["configs"][INLINE_CONFIG_NAME]["steps"]
        self.assertEqual([step["step"] for step in steps], ["extract_features"])


class PresetTests(unittest.TestCase):
    def test_preset_names(self) -> None:
        self.assertEqual(
            set(preset_names()),
            {
                "standard_fbn_8",
                "standard_fbn_16",
                "standard_fbn_32",
                "standard_fbs_8",
                "standard_fbs_16",
                "standard_fbs_32",
            },
        )

    def test_each_preset_builds_a_lint_clean_document(self) -> None:
        for name in preset_names():
            with self.subTest(preset=name):
                document = preset_configuration_document(name)
                self.assertEqual(lint_configuration_document(document), [])

    def test_unknown_preset_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown standard preset"):
            preset_configuration_document("standard_nope")


class LintConfigTests(unittest.TestCase):
    def test_non_mapping_root(self) -> None:
        self.assertEqual(
            lint_configuration_document(["not", "a", "mapping"]),
            ["The configuration root must be a mapping/object."],
        )

    def test_missing_configs(self) -> None:
        issues = lint_configuration_document({"schema_version": "1.0"})
        self.assertTrue(any("non-empty 'configs'" in issue for issue in issues))

    def test_empty_configs(self) -> None:
        issues = lint_configuration_document({"configs": {}})
        self.assertTrue(any("non-empty 'configs'" in issue for issue in issues))

    def test_configs_not_a_mapping(self) -> None:
        issues = lint_configuration_document({"configs": [1, 2, 3]})
        self.assertTrue(any("non-empty 'configs'" in issue for issue in issues))

    def test_config_not_mapping_or_list(self) -> None:
        issues = lint_configuration_document({"configs": {"c": 123}})
        self.assertTrue(any("must define a 'steps' list" in issue for issue in issues))

    def test_config_as_bare_list_of_steps(self) -> None:
        document = {
            "configs": {
                "c": [
                    {"step": "extract_features", "params": {"families": ["morphology"]}}
                ]
            }
        }
        self.assertEqual(lint_configuration_document(document), [])

    def test_steps_not_a_list(self) -> None:
        issues = lint_configuration_document({"configs": {"c": {"steps": 123}}})
        self.assertTrue(any("'steps' must be a list" in issue for issue in issues))

    def test_step_not_a_mapping(self) -> None:
        issues = lint_configuration_document({"configs": {"c": {"steps": [123]}}})
        self.assertTrue(any("must be a mapping" in issue for issue in issues))

    def test_step_missing_name(self) -> None:
        issues = lint_configuration_document(
            {"configs": {"c": {"steps": [{"params": {}}]}}}
        )
        self.assertTrue(any("missing a 'step' name" in issue for issue in issues))

    def test_step_empty_name(self) -> None:
        issues = lint_configuration_document(
            {"configs": {"c": {"steps": [{"step": ""}]}}}
        )
        self.assertTrue(any("missing a 'step' name" in issue for issue in issues))

    def test_unknown_step_type(self) -> None:
        issues = lint_configuration_document(
            {"configs": {"c": {"steps": [{"step": "bogus"}]}}}
        )
        self.assertTrue(any("unknown step type 'bogus'" in issue for issue in issues))

    def test_params_not_a_mapping(self) -> None:
        document = {
            "configs": {
                "c": {
                    "steps": [
                        {"step": "resample", "params": [1, 2, 3]},
                        {
                            "step": "extract_features",
                            "params": {"families": ["morphology"]},
                        },
                    ]
                }
            }
        }
        issues = lint_configuration_document(document)
        self.assertTrue(any("'params' must be a mapping" in issue for issue in issues))

    def test_unknown_parameter(self) -> None:
        document = {
            "configs": {
                "c": {
                    "steps": [
                        {"step": "resample", "params": {"bogus_param": 1}},
                        {
                            "step": "extract_features",
                            "params": {"families": ["morphology"]},
                        },
                    ]
                }
            }
        }
        issues = lint_configuration_document(document)
        self.assertTrue(
            any("unknown parameter 'bogus_param'" in issue for issue in issues)
        )

    def test_discretise_sets_flag_allows_texture(self) -> None:
        document = {
            "configs": {
                "c": {
                    "steps": [
                        {"step": "discretise", "params": {"method": "FBN", "n_bins": 8}},
                        {
                            "step": "extract_features",
                            "params": {"families": ["texture"]},
                        },
                    ]
                }
            }
        }
        self.assertEqual(lint_configuration_document(document), [])

    def test_extract_features_empty_families(self) -> None:
        document = {
            "configs": {
                "c": {"steps": [{"step": "extract_features", "params": {"families": []}}]}
            }
        }
        issues = lint_configuration_document(document)
        self.assertTrue(
            any("at least one feature family" in issue for issue in issues)
        )

    def test_extract_features_non_list_families(self) -> None:
        document = {
            "configs": {
                "c": {
                    "steps": [
                        {"step": "extract_features", "params": {"families": "texture"}}
                    ]
                }
            }
        }
        issues = lint_configuration_document(document)
        self.assertTrue(
            any("at least one feature family" in issue for issue in issues)
        )

    def test_extract_features_non_mapping_falsy_params(self) -> None:
        # An empty (falsy) non-mapping params list is left as-is, so families are
        # resolved via the non-mapping branch (an empty list).
        document = {
            "configs": {
                "c": {"steps": [{"step": "extract_features", "params": []}]}
            }
        }
        issues = lint_configuration_document(document)
        self.assertTrue(
            any("at least one feature family" in issue for issue in issues)
        )

    def test_texture_before_discretise(self) -> None:
        document = {
            "configs": {
                "c": {
                    "steps": [
                        {"step": "extract_features", "params": {"families": ["texture"]}}
                    ]
                }
            }
        }
        issues = lint_configuration_document(document)
        self.assertTrue(
            any("before any discretise step" in issue for issue in issues)
        )

    def test_missing_extract_features(self) -> None:
        issues = lint_configuration_document(
            {"configs": {"c": {"steps": [{"step": "round_intensities"}]}}}
        )
        self.assertTrue(
            any("no extract_features step" in issue for issue in issues)
        )


if __name__ == "__main__":
    unittest.main()
