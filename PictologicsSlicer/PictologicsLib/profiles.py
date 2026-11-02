"""Portable, patient-free profiles for the supported in-app configuration controls."""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from typing import Any

from .inline_config import (
    DISCRETISATION_METHODS,
    FILTER_PARAMETERS,
    MASK_TARGETS,
    NORMALISE_METHODS,
    NORMALISE_REGIONS,
    RESAMPLE_INTERPOLATIONS,
    build_inline_configuration_document,
    default_inline_state,
    filter_step,
    finite_number,
    numbers,
    upgrade_inline_state,
)
from .preset_catalog import all_preset_names

PROFILE_FORMAT = "slicer-pictologics-profile"
PROFILE_SCHEMA_VERSION = 1

_FLAGS = (
    "resample", "grow_mask", "normalise", "resegment", "filter_outliers", "keep_largest",
    "filter", "include_unfiltered", "discretise", "ivh_use_continuous",
)
# Editor values with their ranges; the editors show three decimals.
_EDITOR_RANGES = (
    ("discretise_value", 0.001, 100000.0),
    ("outlier_sigma", 0.001, 1000.0),
    ("grow_to_mm", -100.0, 100.0),
)
_WHOLE_NUMBERS = (("texture_distance", 1, 20), ("ngldm_alpha", 0, 20))


def _editor_value(value: Any, low: float, high: float) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(value)
        and low <= value <= high
        and math.isclose(value, round(value, 3), abs_tol=1e-10, rel_tol=0)
    )


def validate_profile(document: Any) -> dict[str, Any]:
    """Reject unsupported settings before touching the GUI (no silent clamping)."""
    expected = {"format", "schema_version", "name", "presets", "inline_state"}
    if not isinstance(document, dict) or set(document) != expected:
        raise ValueError("Not a Pictologics settings profile (unexpected or missing fields).")
    if (
        document["format"] != PROFILE_FORMAT
        or type(document["schema_version"]) is not int
        or document["schema_version"] != PROFILE_SCHEMA_VERSION
    ):
        raise ValueError("Unsupported Pictologics profile format or version.")
    name = document["name"]
    if (
        not isinstance(name, str)
        or not name.strip()
        or len(name) > 120
        or any(ord(char) < 32 for char in name)
    ):
        raise ValueError("Profile name must contain 1–120 printable characters.")
    presets = document["presets"]
    if (
        not isinstance(presets, list)
        or any(not isinstance(item, str) or item not in all_preset_names() for item in presets)
        or len(set(presets)) != len(presets)
    ):
        raise ValueError("Profile contains unknown or duplicate presets.")
    state = document["inline_state"]
    if state is None:
        if not presets:
            raise ValueError("Select at least one preset or an in-app configuration.")
    else:
        # Profiles saved before a step existed keep their meaning: the step is off.
        if not isinstance(state, dict):
            raise ValueError("Profile contains unsupported in-app settings.")
        state = upgrade_inline_state(state)
        if set(state) != set(default_inline_state()):
            raise ValueError("Profile contains unsupported in-app settings.")
        if any(type(state[key]) is not bool for key in _FLAGS):
            raise ValueError("Preprocessing enable flags must be booleans.")
        families = state["families"]
        if (
            not isinstance(families, list)
            or any(not isinstance(item, str) for item in families)
            or len(set(families)) != len(families)
        ):
            raise ValueError("Feature families must be a unique list of names.")
        spacing, percentiles = state["spacing"], state["normalise_percentiles"]
        if not isinstance(spacing, list) or len(spacing) != 3:
            raise ValueError("Spacing must contain three numbers.")
        if not isinstance(percentiles, list) or len(percentiles) != 2:
            raise ValueError("Normalisation percentiles must contain two numbers.")
        values = [(value, 0.001, 100.0) for value in spacing] + [(value, 0.0, 100.0) for value in percentiles]
        values += [(state[key], low, high) for key, low, high in _EDITOR_RANGES]
        if not all(_editor_value(*item) for item in values):
            raise ValueError("Profile values must fit the editor's range and three-decimal precision.")
        if any(
            type(state[key]) is not int or not low <= state[key] <= high
            for key, low, high in _WHOLE_NUMBERS
        ):
            raise ValueError("Texture distance and NGLDM coarseness must be whole numbers in the editor's range.")
        if (
            state["discretise_method"] not in DISCRETISATION_METHODS
            or state["interpolation"] not in RESAMPLE_INTERPOLATIONS
            or state["normalise_method"] not in NORMALISE_METHODS
            or state["normalise_region"] not in NORMALISE_REGIONS
        ):
            raise ValueError("Unsupported discretisation, interpolation or normalisation method.")
        if (
            state["discretise"]
            and state["discretise_method"] == "FBN"
            and float(state["discretise_value"]) % 1
        ):
            raise ValueError("Fixed bin count must be an integer.")
        sentinel = state["sentinel_value"]
        if sentinel is not None:
            try:
                valid_sentinel = not isinstance(sentinel, bool) and math.isfinite(float(sentinel))
            except (TypeError, ValueError):
                valid_sentinel = False
            if not valid_sentinel:
                raise ValueError("Sentinel must be a finite number or null.")
        for key in ("range_min", "range_max", "fbs_minimum", "grow_from_mm",
                    "normalise_range_min", "normalise_range_max"):
            if state[key] is not None:
                finite_number(state[key], key)
        if state["discretise_cutoffs"] is not None:
            if not isinstance(state["discretise_cutoffs"], str):
                raise ValueError("Bin edges must be text, such as -100, 0, 100.")
            numbers(state["discretise_cutoffs"], "Bin edges")
        for key in ("resegment_apply_to", "outlier_apply_to", "grow_apply_to", "keep_largest_apply_to"):
            if state[key] not in MASK_TARGETS:
                raise ValueError("Unsupported mask target.")
        # Disabled controls are restored too: reject invalid values before changing
        # any widgets, rather than letting Qt silently clamp or round them.
        filters = state["filters"]
        if not isinstance(filters, list) or not filters or any(
            not isinstance(entry, dict) or set(entry) != {"type", "boundary", "params"} for entry in filters
        ):
            raise ValueError("Profile filters must be a list of filter settings.")
        for entry in filters:
            filter_step(entry)
            for key, kind, _, _ in FILTER_PARAMETERS[entry["type"]]:
                if kind in ("int", "float"):
                    value = entry["params"][key]
                    if not isinstance(value, (int, float)) or not math.isclose(
                        value, round(value, 4), abs_tol=1e-10, rel_tol=0
                    ):
                        raise ValueError(
                            "Profile filter values must be numbers with at most four-decimal precision."
                        )
        build_inline_configuration_document(state)
    result = copy.deepcopy(document)
    result["inline_state"] = copy.deepcopy(state)
    result["name"] = name.strip()
    return result


def build_profile(name: str, presets: list[str], state: Mapping[str, Any] | None) -> dict[str, Any]:
    return validate_profile(
        {
            "format": PROFILE_FORMAT,
            "schema_version": PROFILE_SCHEMA_VERSION,
            "name": name,
            "presets": presets,
            "inline_state": dict(state) if state is not None else None,
        }
    )
