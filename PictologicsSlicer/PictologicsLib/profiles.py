"""Portable, patient-free profiles for the supported in-app configuration controls."""

from __future__ import annotations

import copy
import math
from collections.abc import Mapping
from typing import Any

from .inline_config import build_inline_configuration_document, default_inline_state, preset_names

PROFILE_FORMAT = "slicer-pictologics-profile"
PROFILE_SCHEMA_VERSION = 1


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
        or any(not isinstance(item, str) or item not in preset_names() for item in presets)
        or len(set(presets)) != len(presets)
    ):
        raise ValueError("Profile contains unknown or duplicate presets.")
    state = document["inline_state"]
    if state is None:
        if not presets:
            raise ValueError("Select at least one preset or an in-app configuration.")
    else:
        if not isinstance(state, dict) or set(state) != set(default_inline_state()):
            raise ValueError("Profile contains unsupported in-app settings.")
        if any(type(state[key]) is not bool for key in ("resample", "discretise")):
            raise ValueError("Resample and discretise must be booleans.")
        families = state["families"]
        if (
            not isinstance(families, list)
            or any(not isinstance(item, str) for item in families)
            or len(set(families)) != len(families)
        ):
            raise ValueError("Feature families must be a unique list of names.")
        spacing = state["spacing"]
        if not isinstance(spacing, list) or len(spacing) != 3:
            raise ValueError("Spacing must contain three numbers.")
        for value, maximum in [(value, 100.0) for value in spacing] + [
            (state["discretise_value"], 100000.0)
        ]:
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0.001 <= value <= maximum
                or not math.isclose(value, round(value, 3), abs_tol=1e-10, rel_tol=0)
            ):
                raise ValueError(
                    "Profile values must fit the editor's range and three-decimal precision."
                )
        if state["discretise_method"] not in ("FBN", "FBS") or state["interpolation"] not in (
            "linear",
            "nearest",
        ):
            raise ValueError("Unsupported discretisation or interpolation method.")
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
        build_inline_configuration_document(state)
    result = copy.deepcopy(document)
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
