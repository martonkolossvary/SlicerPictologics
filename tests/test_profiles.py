from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "PictologicsSlicer"))

from PictologicsLib.inline_config import default_inline_state
from PictologicsLib.profiles import build_profile, validate_profile


def example():
    return build_profile("Example", ["standard_fbn_32"], default_inline_state())


class ProfileTests(unittest.TestCase):
    def test_legacy_fbn_migrates_but_fbs_requires_user_choice(self):
        document = example()
        del document["inline_state"]["fbs_minimum"]
        self.assertIsNone(validate_profile(document)["inline_state"]["fbs_minimum"])
        self.assertNotIn("fbs_minimum", document["inline_state"])
        document["inline_state"]["discretise_method"] = "FBS"
        with self.assertRaisesRegex(ValueError, "older FBS settings need review"):
            validate_profile(document)
        document["inline_state"]["fbs_minimum"] = "-123.456789"
        self.assertEqual(validate_profile(document)["inline_state"]["fbs_minimum"], "-123.456789")
        document["inline_state"]["fbs_minimum"] = float("nan")
        with self.assertRaisesRegex(ValueError, "finite"):
            validate_profile(document)

    def test_profile_json_round_trip_and_defensive_copy(self) -> None:
        profile = example()
        restored = validate_profile(json.loads(json.dumps(profile)))
        self.assertEqual(restored, profile)
        restored["inline_state"]["spacing"][0] = 2
        self.assertEqual(profile["inline_state"]["spacing"][0], 0.5)
        self.assertEqual(
            build_profile("  Presets only  ", ["standard_fbn_8"], None)["name"], "Presets only"
        )
        self.assertEqual(
            set(profile), {"format", "schema_version", "name", "presets", "inline_state"}
        )

    def test_rejects_invalid_profile_fields(self) -> None:
        for field, value in (
            ("format", "other"),
            ("schema_version", 2),
            ("schema_version", True),
            ("name", ""),
            ("name", "a\nb"),
            ("name", 1),
            ("name", "a" * 121),
            ("presets", ["unknown"]),
            ("presets", ["standard_fbn_32"] * 2),
            ("presets", [None]),
            ("presets", "standard_fbn_32"),
            ("inline_state", []),
        ):
            with self.subTest(field=field, value=value):
                profile = example()
                profile[field] = value
                with self.assertRaises(ValueError):
                    validate_profile(profile)

    def test_rejects_non_profiles(self) -> None:
        for document in (None, [], {}, {"unexpected": "patient data"}):
            with self.subTest(document=document):
                with self.assertRaises(ValueError):
                    validate_profile(document)

    def test_rejects_unrepresentable_editor_settings(self) -> None:
        for field, value in (
            ("resample", "true"),
            ("discretise", 1),
            ("families", "intensity"),
            ("families", [None]),
            ("families", ["intensity"] * 2),
            ("families", []),
            ("families", ["unknown"]),
            ("spacing", [1, 1]),
            ("spacing", "1,1,1"),
            ("spacing", [0, 1, 1]),
            ("spacing", [101, 1, 1]),
            ("spacing", [0.0001, 1, 1]),
            ("spacing", [float("nan"), 1, 1]),
            ("spacing", [float("inf"), 1, 1]),
            ("spacing", [True, 1, 1]),
            ("spacing", ["1", 1, 1]),
            ("spacing", [0.1234, 1, 1]),
            ("discretise_value", 32.5),
            ("discretise_method", "other"),
            ("interpolation", "other"),
            ("sentinel_value", float("inf")),
            ("sentinel_value", []),
            ("sentinel_value", True),
            ("source_mode", "other"),
        ):
            with self.subTest(field=field, value=value):
                profile = example()
                profile["inline_state"][field] = value
                before = copy.deepcopy(profile)
                with self.assertRaises(ValueError):
                    validate_profile(profile)
                self.assertEqual(profile.keys(), before.keys())

    def test_empty_selection_unknown_settings_and_valid_numeric_sentinel(self) -> None:
        with self.assertRaisesRegex(ValueError, "Select at least"):
            build_profile("Empty", [], None)
        profile = example()
        profile["inline_state"]["unexpected"] = "setting"
        with self.assertRaisesRegex(ValueError, "unsupported"):
            validate_profile(profile)
        state = default_inline_state()
        state.update(
            source_mode="auto",
            sentinel_value="-3024",
            discretise_method="FBS",
            discretise_value=25.5,
            fbs_minimum=-1000.0,
        )
        self.assertEqual(build_profile("Sentinel", [], state)["inline_state"], state)


if __name__ == "__main__":
    unittest.main()
