from __future__ import annotations

import copy

import pytest
from PictologicsLib.inline_config import (
    MASK_TARGETS,
    ROI_REFINEMENT_DEFAULTS,
    build_inline_configuration_document,
    default_inline_state,
    finite_number,
    lint_configuration_document,
)
from PictologicsLib.profiles import build_profile, validate_profile


def refined_state(**changes):
    return {
        **default_inline_state(),
        "resegment": True,
        "range_min": "-100.5",
        "range_max": "400",
        "filter_outliers": True,
        **changes,
    }


@pytest.mark.parametrize("target", MASK_TARGETS)
def test_order_targets_and_exact_native_parameters(target):
    state = refined_state(resegment_apply_to=target, outlier_apply_to=target)
    original = copy.deepcopy(state)
    document = build_inline_configuration_document(state)
    steps = document["configs"]["in_app"]["steps"]
    assert [item["step"] for item in steps] == [
        "resample",
        "resegment",
        "filter_outliers",
        "discretise",
        "extract_features",
    ]
    assert steps[1]["params"] == {"range_min": -100.5, "range_max": 400.0, "apply_to": target}
    assert steps[2]["params"] == {"sigma": 3.0, "apply_to": target}
    assert lint_configuration_document(document) == []
    assert state == original


@pytest.mark.parametrize("lower,upper", [(None, 0), (-12, None), (0, 0)])
def test_one_sided_and_inclusive_equal_bounds(lower, upper):
    state = refined_state(
        range_min=lower,
        range_max=upper,
        resample=False,
        filter_outliers=False,
        discretise=False,
        families=["intensity"],
    )
    steps = build_inline_configuration_document(state)["configs"]["in_app"]["steps"]
    assert len(steps) == 2
    assert steps[0]["params"] == {"range_min": lower, "range_max": upper, "apply_to": "both"}


@pytest.mark.parametrize(
    "changes,message",
    [
        ({"range_min": None, "range_max": None}, "at least one bound"),
        ({"range_min": 1000}, "must not exceed"),
        ({"range_min": "bad"}, "finite number"),
        ({"range_max": float("nan")}, "finite number"),
        ({"resegment_apply_to": "other"}, "mask target"),
        ({"outlier_apply_to": "other"}, "mask target"),
        ({"outlier_sigma": 0}, "must be positive"),
        ({"outlier_sigma": -1}, "must be positive"),
        ({"outlier_sigma": "inf"}, "finite number"),
    ],
)
def test_invalid_enabled_refinement_blocks_configuration(changes, message):
    with pytest.raises(ValueError, match=message):
        build_inline_configuration_document(refined_state(**changes))


@pytest.mark.parametrize("value", [True, [], {}, "", "NaN", "-inf", "1e999", 10**400])
def test_finite_number_rejects_invalid_values(value):
    with pytest.raises(ValueError, match="finite number"):
        finite_number(value, "Intensity")


def test_disabled_refinement_leaves_defaults_unchanged():
    state = refined_state(resegment=False, filter_outliers=False, range_min="unfinished")
    assert build_inline_configuration_document(state) == build_inline_configuration_document(
        default_inline_state()
    )
    legacy = {
        key: value
        for key, value in default_inline_state().items()
        if key not in ROI_REFINEMENT_DEFAULTS
    }
    assert build_inline_configuration_document(legacy) == build_inline_configuration_document(
        default_inline_state()
    )


def test_profiles_preserve_refinement_and_migrate_original_profiles_without_mutation():
    state = refined_state(
        outlier_sigma=1.25, resegment_apply_to="intensity", outlier_apply_to="morph"
    )
    profile = build_profile("Refined ROI", [], state)
    assert validate_profile(profile)["inline_state"] == state
    old_profile = build_profile("Original profile", [], default_inline_state())
    old_profile["inline_state"] = {
        key: value
        for key, value in old_profile["inline_state"].items()
        if key not in ROI_REFINEMENT_DEFAULTS
    }
    before = copy.deepcopy(old_profile)
    migrated = validate_profile(old_profile)
    assert old_profile == before
    assert migrated["inline_state"] == default_inline_state()
    assert build_inline_configuration_document(
        migrated["inline_state"]
    ) == build_inline_configuration_document(old_profile["inline_state"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("resegment", "yes"),
        ("filter_outliers", 1),
        ("range_min", True),
        ("range_max", "NaN"),
        ("outlier_sigma", 0),
        ("outlier_sigma", 1001),
        ("outlier_sigma", 1.2345),
        ("outlier_sigma", "3"),
        ("resegment_apply_to", "other"),
        ("outlier_apply_to", None),
    ],
)
def test_profiles_reject_invalid_refinement_even_if_disabled(field, value):
    state = default_inline_state()
    state[field] = value
    with pytest.raises(ValueError):
        build_profile("Invalid", [], state)


def test_partial_refinement_settings_are_not_silently_migrated():
    document = build_profile("Partial", [], default_inline_state())
    del document["inline_state"]["outlier_apply_to"]
    with pytest.raises(ValueError, match="unsupported"):
        validate_profile(document)
