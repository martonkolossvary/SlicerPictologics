from __future__ import annotations

import copy
import json

import pytest
from PictologicsLib.inline_config import default_inline_state
from PictologicsLib.profiles import build_profile, validate_profile


def example():
    return build_profile("Example", ["standard_fbn_32"], default_inline_state())


def test_profile_json_round_trip_and_defensive_copy():
    profile = example()
    restored = validate_profile(json.loads(json.dumps(profile)))
    assert restored == profile
    restored["inline_state"]["spacing"][0] = 2
    assert profile["inline_state"]["spacing"][0] == 0.5
    assert build_profile("  Presets only  ", ["standard_fbn_8"], None)["name"] == "Presets only"
    assert set(profile) == {"format", "schema_version", "name", "presets", "inline_state"}


@pytest.mark.parametrize(
    ("field", "value"),
    [
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
    ],
)
def test_rejects_invalid_profile_fields(field, value):
    profile = example()
    profile[field] = value
    with pytest.raises(ValueError):
        validate_profile(profile)


@pytest.mark.parametrize("document", [None, [], {}, {"unexpected": "patient data"}])
def test_rejects_non_profiles(document):
    with pytest.raises(ValueError):
        validate_profile(document)


@pytest.mark.parametrize(
    ("field", "value"),
    [
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
    ],
)
def test_rejects_unrepresentable_editor_settings(field, value):
    profile = example()
    profile["inline_state"][field] = value
    before = copy.deepcopy(profile)
    with pytest.raises(ValueError):
        validate_profile(profile)
    assert profile.keys() == before.keys()


def test_empty_selection_unknown_settings_and_valid_numeric_sentinel():
    with pytest.raises(ValueError, match="Select at least"):
        build_profile("Empty", [], None)
    profile = example()
    profile["inline_state"]["unexpected"] = "setting"
    with pytest.raises(ValueError, match="unsupported"):
        validate_profile(profile)
    state = default_inline_state()
    state.update(
        source_mode="auto", sentinel_value="-3024", discretise_method="FBS", discretise_value=25.5
    )
    assert build_profile("Sentinel", [], state)["inline_state"] == state
