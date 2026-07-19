from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "PictologicsSlicer"))

from PictologicsLib.inline_config import (
    INLINE_CONFIG_NAME,
    build_inline_configuration_document,
    default_inline_state,
    lint_configuration_document,
    preset_configuration_document,
    preset_names,
)


class BuildInlineConfigTests(unittest.TestCase):
    def test_default_state_reproduces_fbn32_shape(self) -> None:
        document = build_inline_configuration_document(default_inline_state())
        config = document["configs"][INLINE_CONFIG_NAME]
        step_names = [step["step"] for step in config["steps"]]
        self.assertEqual(step_names, ["resample", "discretise", "extract_features"])
        self.assertEqual(config["source_mode"], "full_image")
        self.assertNotIn("sentinel_value", config)
        resample = config["steps"][0]["params"]
        self.assertEqual(resample["new_spacing"], [0.5, 0.5, 0.5])
        discretise = config["steps"][1]["params"]
        self.assertEqual(discretise, {"method": "FBN", "n_bins": 32})
        extract = config["steps"][2]["params"]
        self.assertEqual(
            extract["families"],
            ["intensity", "morphology", "texture", "histogram", "ivh"],
        )

    def test_intensity_only_without_resample_or_discretise(self) -> None:
        state = {
            "families": ["intensity", "morphology"],
            "resample": False,
            "discretise": False,
            "source_mode": "full_image",
        }
        document = build_inline_configuration_document(state)
        steps = document["configs"][INLINE_CONFIG_NAME]["steps"]
        self.assertEqual([step["step"] for step in steps], ["extract_features"])

    def test_texture_without_discretise_is_rejected(self) -> None:
        state = default_inline_state()
        state["discretise"] = False
        with self.assertRaisesRegex(ValueError, "require a discretise step"):
            build_inline_configuration_document(state)

    def test_no_families_is_rejected(self) -> None:
        state = default_inline_state()
        state["families"] = []
        with self.assertRaisesRegex(ValueError, "at least one feature family"):
            build_inline_configuration_document(state)

    def test_fbs_uses_bin_width(self) -> None:
        state = default_inline_state()
        state["discretise_method"] = "FBS"
        state["discretise_value"] = 16.0
        document = build_inline_configuration_document(state)
        discretise = document["configs"][INLINE_CONFIG_NAME]["steps"][1]["params"]
        self.assertEqual(discretise, {"method": "FBS", "bin_width": 16.0})

    def test_sentinel_kept_only_for_non_full_image(self) -> None:
        state = default_inline_state()
        state["source_mode"] = "auto"
        state["sentinel_value"] = -1024.0
        document = build_inline_configuration_document(state)
        self.assertEqual(
            document["configs"][INLINE_CONFIG_NAME]["sentinel_value"], -1024.0
        )

        state["source_mode"] = "full_image"
        document = build_inline_configuration_document(state)
        self.assertNotIn("sentinel_value", document["configs"][INLINE_CONFIG_NAME])


class LintConfigTests(unittest.TestCase):
    def test_valid_document_has_no_issues(self) -> None:
        document = build_inline_configuration_document(default_inline_state())
        self.assertEqual(lint_configuration_document(document), [])

    def test_missing_configs_is_flagged(self) -> None:
        issues = lint_configuration_document({"schema_version": "1.0"})
        self.assertTrue(any("configs" in issue for issue in issues))

    def test_unknown_step_is_flagged(self) -> None:
        document = {"configs": {"c": {"steps": [{"step": "bogus"}]}}}
        issues = lint_configuration_document(document)
        self.assertTrue(any("unknown step type 'bogus'" in issue for issue in issues))

    def test_unknown_param_is_flagged(self) -> None:
        document = {
            "configs": {
                "c": {
                    "steps": [
                        {"step": "resample", "params": {"bogus_param": 1}},
                        {"step": "extract_features", "params": {"families": ["morphology"]}},
                    ]
                }
            }
        }
        issues = lint_configuration_document(document)
        self.assertTrue(any("unknown parameter 'bogus_param'" in issue for issue in issues))

    def test_texture_before_discretise_is_flagged(self) -> None:
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
        self.assertTrue(any("before any discretise step" in issue for issue in issues))

    def test_missing_extract_features_is_flagged(self) -> None:
        document = {"configs": {"c": {"steps": [{"step": "round_intensities"}]}}}
        issues = lint_configuration_document(document)
        self.assertTrue(any("no extract_features step" in issue for issue in issues))


class PresetTemplateTests(unittest.TestCase):
    def test_preset_names_are_the_six_standard_presets(self) -> None:
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

    def test_preset_document_is_lint_clean(self) -> None:
        document = preset_configuration_document("standard_fbs_16")
        self.assertEqual(lint_configuration_document(document), [])
        discretise = document["configs"]["standard_fbs_16"]["steps"][1]["params"]
        self.assertEqual(discretise, {"method": "FBS", "bin_width": 16.0})

    def test_unknown_preset_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown standard preset"):
            preset_configuration_document("standard_nope")


if __name__ == "__main__":
    unittest.main()
