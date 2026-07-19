"""Slicer-neutral construction and linting of Pictologics configuration documents.

The GUI never imports Pictologics, so it cannot use ``RadiomicsPipeline`` to build or
validate configurations. This module builds the exact serialization dict that
Pictologics' ``from_dict`` / ``load_configs`` accepts, provides preset starter
templates for the "new configuration from preset" authoring aid, and performs a fast
*structural* lint (shape plus known step/parameter names) for the "validate" aid.

The step/parameter names below mirror the adopted Pictologics contract
(``RadiomicsPipeline._VALID_STEPS`` and the standard templates). The worker's
``load_configs(validate=True)`` remains the authoritative validator; this lint only
catches obvious mistakes before a job is submitted.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

CONFIG_SCHEMA_VERSION = "1.0"
INLINE_CONFIG_NAME = "in_app"

# Families the in-app builder offers. Presets expose the first five; spatial/local
# intensity are added here as standalone families (their own FEATURE_NAMES groups).
CORE_FEATURE_FAMILIES: tuple[str, ...] = (
    "intensity",
    "morphology",
    "texture",
    "histogram",
    "ivh",
)
OPTIONAL_FEATURE_FAMILIES: tuple[str, ...] = (
    "spatial_intensity",
    "local_intensity",
)
ALL_FEATURE_FAMILIES: tuple[str, ...] = CORE_FEATURE_FAMILIES + OPTIONAL_FEATURE_FAMILIES

# Families that are only meaningful on a discretised image.
DISCRETISATION_REQUIRED_FAMILIES: frozenset[str] = frozenset(
    {"texture", "histogram", "ivh"}
)

RESAMPLE_INTERPOLATIONS: tuple[str, ...] = ("linear", "nearest")
DISCRETISATION_METHODS: tuple[str, ...] = ("FBN", "FBS")
SOURCE_MODES: tuple[str, ...] = ("full_image", "roi_only", "auto")

# Mirror of RadiomicsPipeline._VALID_STEPS for the adopted Pictologics release.
_VALID_STEP_PARAMS: dict[str, frozenset[str]] = {
    "resample": frozenset(
        {
            "new_spacing",
            "interpolation",
            "mask_interpolation",
            "mask_threshold",
            "round_intensities",
        }
    ),
    "resegment": frozenset({"range_min", "range_max", "apply_to"}),
    "filter_outliers": frozenset({"sigma", "apply_to"}),
    "binarize_mask": frozenset({"threshold", "mask_values", "apply_to"}),
    "keep_largest_component": frozenset({"apply_to"}),
    "round_intensities": frozenset(),
    "discretise": frozenset(
        {"method", "n_bins", "bin_width", "min_val", "max_val", "cutoffs"}
    ),
    "filter": frozenset(
        {
            "type",
            "boundary",
            "support",
            "sigma_mm",
            "spacing_mm",
            "truncate",
            "kernel",
            "compute_energy",
            "energy_distance",
            "lambda_mm",
            "gamma",
            "theta",
            "delta_theta",
            "average_over_planes",
            "wavelet",
            "decomposition",
            "level",
            "order",
            "variant",
            "rotation_invariant",
            "pooling",
            "use_parallel",
        }
    ),
    "extract_features": frozenset(
        {
            "families",
            "include_spatial_intensity",
            "include_local_intensity",
            "texture_matrix_params",
            "ivh_params",
            "ivh_use_continuous",
            "ivh_discretisation",
        }
    ),
}


def default_inline_state() -> dict[str, Any]:
    """Builder state matching ``standard_fbn_32`` (a sensible starting point)."""

    return {
        "families": list(CORE_FEATURE_FAMILIES),
        "resample": True,
        "spacing": [0.5, 0.5, 0.5],
        "interpolation": "linear",
        "discretise": True,
        "discretise_method": "FBN",
        "discretise_value": 32.0,
        "source_mode": "full_image",
        "sentinel_value": None,
    }


def build_inline_configuration_document(state: Mapping[str, Any]) -> dict[str, Any]:
    """Build a Pictologics configuration document from in-app builder state.

    Raises ``ValueError`` for choices the builder must not submit (no families, an
    unknown discretisation-requiring family without a discretise step, etc.). The
    returned dict is in the ``from_dict`` / ``load_configs`` serialization format.
    """

    families = [str(family) for family in state.get("families", [])]
    if not families:
        raise ValueError("Select at least one feature family.")
    unknown = [family for family in families if family not in ALL_FEATURE_FAMILIES]
    if unknown:
        raise ValueError(f"Unknown feature families: {', '.join(unknown)}")

    steps: list[dict[str, Any]] = []

    if state.get("resample", False):
        spacing = [float(value) for value in state.get("spacing", [])]
        if len(spacing) != 3 or any(value <= 0 for value in spacing):
            raise ValueError("Resampling spacing must be three positive numbers.")
        interpolation = str(state.get("interpolation", "linear"))
        if interpolation not in RESAMPLE_INTERPOLATIONS:
            raise ValueError(f"Unknown resample interpolation: {interpolation}")
        steps.append(
            {
                "step": "resample",
                "params": {"new_spacing": spacing, "interpolation": interpolation},
            }
        )

    needs_discretisation = bool(DISCRETISATION_REQUIRED_FAMILIES.intersection(families))
    if state.get("discretise", False):
        method = str(state.get("discretise_method", "FBN"))
        if method not in DISCRETISATION_METHODS:
            raise ValueError(f"Unknown discretisation method: {method}")
        value = float(state.get("discretise_value", 0.0))
        if value <= 0:
            raise ValueError("The discretisation bin count/width must be positive.")
        params: dict[str, Any] = {"method": method}
        if method == "FBN":
            params["n_bins"] = int(value)
        else:
            params["bin_width"] = value
        steps.append({"step": "discretise", "params": params})
    elif needs_discretisation:
        offenders = sorted(DISCRETISATION_REQUIRED_FAMILIES.intersection(families))
        raise ValueError(
            "These families require a discretise step: " + ", ".join(offenders)
        )

    steps.append({"step": "extract_features", "params": {"families": families}})

    source_mode = str(state.get("source_mode", "full_image"))
    if source_mode not in SOURCE_MODES:
        raise ValueError(f"Unknown source mode: {source_mode}")

    config: dict[str, Any] = {"source_mode": source_mode, "steps": steps}
    sentinel_value = state.get("sentinel_value")
    if sentinel_value is not None and source_mode != "full_image":
        config["sentinel_value"] = float(sentinel_value)

    return {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "configs": {INLINE_CONFIG_NAME: config},
    }


# Preset step templates, mirrored from Pictologics' standard_configs.yaml for the
# adopted release. Used only to seed an editable starter file; the worker validates
# the file it actually loads.
_PRESET_DISCRETISATION: dict[str, dict[str, Any]] = {
    "standard_fbn_8": {"method": "FBN", "n_bins": 8},
    "standard_fbn_16": {"method": "FBN", "n_bins": 16},
    "standard_fbn_32": {"method": "FBN", "n_bins": 32},
    "standard_fbs_8": {"method": "FBS", "bin_width": 8.0},
    "standard_fbs_16": {"method": "FBS", "bin_width": 16.0},
    "standard_fbs_32": {"method": "FBS", "bin_width": 32.0},
}


def preset_names() -> tuple[str, ...]:
    return tuple(_PRESET_DISCRETISATION)


def preset_configuration_document(name: str) -> dict[str, Any]:
    """Editable starter document reproducing a standard preset by name."""

    if name not in _PRESET_DISCRETISATION:
        raise ValueError(f"Unknown standard preset: {name}")
    return {
        "schema_version": CONFIG_SCHEMA_VERSION,
        "configs": {
            name: {
                "source_mode": "full_image",
                "steps": [
                    {
                        "step": "resample",
                        "params": {
                            "new_spacing": [0.5, 0.5, 0.5],
                            "interpolation": "linear",
                        },
                    },
                    {
                        "step": "discretise",
                        "params": dict(_PRESET_DISCRETISATION[name]),
                    },
                    {
                        "step": "extract_features",
                        "params": {"families": list(CORE_FEATURE_FAMILIES)},
                    },
                ],
            }
        },
    }


def _lint_steps(config_name: str, steps: Sequence[Any]) -> list[str]:
    issues: list[str] = []
    discretised = False
    has_extract = False
    for index, step in enumerate(steps):
        location = f"config '{config_name}' step {index}"
        if not isinstance(step, Mapping):
            issues.append(f"{location} must be a mapping")
            continue
        step_name = step.get("step")
        if not isinstance(step_name, str) or not step_name:
            issues.append(f"{location} is missing a 'step' name")
            continue
        if step_name not in _VALID_STEP_PARAMS:
            issues.append(f"{location} has unknown step type '{step_name}'")
            continue
        params = step.get("params", {})
        if params and not isinstance(params, Mapping):
            issues.append(f"{location} 'params' must be a mapping")
            params = {}
        for param in params:
            if param not in _VALID_STEP_PARAMS[step_name]:
                issues.append(
                    f"{location} ({step_name}) has unknown parameter '{param}'"
                )
        if step_name == "discretise":
            discretised = True
        if step_name == "extract_features":
            has_extract = True
            families = params.get("families", []) if isinstance(params, Mapping) else []
            if not isinstance(families, (list, tuple)) or not families:
                issues.append(f"{location} must request at least one feature family")
                families = []
            if not discretised and DISCRETISATION_REQUIRED_FAMILIES.intersection(
                str(family) for family in families
            ):
                offenders = sorted(
                    DISCRETISATION_REQUIRED_FAMILIES.intersection(
                        str(family) for family in families
                    )
                )
                issues.append(
                    f"{location} requests {', '.join(offenders)} before any discretise step"
                )
    if not has_extract:
        issues.append(f"config '{config_name}' has no extract_features step")
    return issues


def lint_configuration_document(document: Any) -> list[str]:
    """Return a list of structural problems (empty means the shape looks valid).

    This is a pre-submission convenience check only. It does not validate parameter
    *values*; the worker's ``load_configs(validate=True)`` is authoritative.
    """

    if not isinstance(document, Mapping):
        return ["The configuration root must be a mapping/object."]
    configs = document.get("configs")
    if not isinstance(configs, Mapping) or not configs:
        return ["The configuration must contain a non-empty 'configs' mapping."]

    issues: list[str] = []
    for config_name, config_data in configs.items():
        if isinstance(config_data, Mapping) and "steps" in config_data:
            steps = config_data["steps"]
        elif isinstance(config_data, (list, tuple)):
            steps = config_data
        else:
            issues.append(f"config '{config_name}' must define a 'steps' list")
            continue
        if not isinstance(steps, (list, tuple)):
            issues.append(f"config '{config_name}' 'steps' must be a list")
            continue
        issues.extend(_lint_steps(str(config_name), steps))
    return issues
