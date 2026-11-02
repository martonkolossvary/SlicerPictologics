"""Slicer-neutral construction and linting of Pictologics configuration documents.

The GUI never imports Pictologics, so it cannot use ``RadiomicsPipeline`` to build or
validate configurations. This module builds the exact serialization dict that
Pictologics' ``from_dict`` / ``load_configs`` accepts, provides preset starter
templates for the "new configuration from preset" authoring aid, and performs a fast
*structural* lint (shape plus known step/parameter names) for the "validate" aid
when Pictologics is not installed yet. It also reads the result of the worker's
configuration check, which loads a file with Pictologics as a run does.

The step/parameter names below mirror the adopted release
(``RadiomicsPipeline._VALID_STEPS``, filter signatures and standard templates). The worker's
``load_configs(validate=True)`` remains the authoritative validator; this lint only
catches obvious mistakes before a job is submitted.
"""

from __future__ import annotations

import json
import math
import re
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
DISCRETISATION_REQUIRED_FAMILIES: frozenset[str] = frozenset({"texture", "histogram", "ivh"})

RESAMPLE_INTERPOLATIONS: tuple[str, ...] = ("linear", "nearest", "cubic")
DISCRETISATION_METHODS: tuple[str, ...] = ("FBN", "FBS", "FIXED_CUTOFFS")
SOURCE_MODES: tuple[str, ...] = ("full_image", "roi_only", "auto")
MASK_TARGETS: tuple[str, ...] = ("both", "intensity", "morph")
NORMALISE_METHODS: tuple[str, ...] = ("zscore", "percentile")
NORMALISE_REGIONS: tuple[str, ...] = ("image", "roi")
# Pictologics 1.0.0 refines only the intensity mask by default, as IBSI does.
ROI_REFINEMENT_DEFAULTS: dict[str, Any] = {
    "resegment": False,
    "range_min": None,
    "range_max": None,
    "resegment_apply_to": "intensity",
    "filter_outliers": False,
    "outlier_sigma": 3.0,
    "outlier_apply_to": "intensity",
}


# IBSI 2 image filters that the in-app builder offers, with the parameters it shows:
# (name, kind, default, range or choices). The defaults follow the IBSI 2 reference
# settings. The three Riesz entries are the variants of the Pictologics "riesz" filter.
_POOLING: tuple[str, ...] = ("max", "average", "min")
_RIESZ_ORDER = ("order", "riesz_order", "1, 0, 0", None)
FILTER_PARAMETERS: dict[str, tuple[tuple[str, str, Any, Any], ...]] = {
    "mean": (("support", "int", 5, (1, 99)),),
    "gaussian": (
        ("sigma_mm", "float", 1.5, (0.01, 100.0)),
        ("truncate", "float", 4.0, (0.5, 20.0)),
    ),
    "log": (
        ("sigma_mm", "float", 1.5, (0.01, 100.0)),
        ("truncate", "float", 4.0, (0.5, 20.0)),
    ),
    "laws": (
        ("kernel", "laws_kernel", "L5E5E5", None),
        ("rotation_invariant", "bool", True, None),
        ("pooling", "choice", "max", _POOLING),
        ("compute_energy", "bool", True, None),
        ("energy_distance", "int", 7, (1, 50)),
    ),
    "gabor": (
        ("sigma_mm", "float", 5.0, (0.01, 100.0)),
        ("lambda_mm", "float", 2.0, (0.01, 100.0)),
        ("gamma", "float", 1.5, (0.01, 10.0)),
        ("theta", "float", 0.0, (-6.2832, 6.2832)),
        ("rotation_invariant", "bool", True, None),
        ("delta_theta", "float", 0.3927, (0.01, 3.1416)),
        ("pooling", "choice", "average", _POOLING),
        ("average_over_planes", "bool", True, None),
        ("response", "choice", "modulus", ("modulus", "real", "imaginary", "angle")),
    ),
    "wavelet": (
        ("wavelet", "choice", "db3", ("haar", "db2", "db3", "db4", "sym2", "sym3", "coif1", "coif2")),
        ("level", "int", 1, (1, 4)),
        ("decomposition", "decomposition", "LLH", None),
        ("rotation_invariant", "bool", True, None),
        ("pooling", "choice", "average", _POOLING),
    ),
    "simoncelli": (("level", "int", 1, (1, 4)),),
    "riesz": (_RIESZ_ORDER,),
    "riesz_log": (
        _RIESZ_ORDER,
        ("sigma_mm", "float", 1.5, (0.01, 100.0)),
        ("truncate", "float", 4.0, (0.5, 20.0)),
    ),
    "riesz_simoncelli": (_RIESZ_ORDER, ("level", "int", 1, (1, 4))),
}
_RIESZ_VARIANTS = {"riesz": "base", "riesz_log": "log", "riesz_simoncelli": "simoncelli"}
# "default" leaves the boundary to Pictologics: mirror for the spatial filters, periodic
# for the Simoncelli wavelet and the Riesz filters.
FILTER_BOUNDARIES: tuple[str, ...] = ("default", "mirror", "nearest", "zero", "periodic")
_LAWS_KERNEL = re.compile(r"(?:L3|E3|S3|L5|E5|S5|W5|R5){3}")
_DECOMPOSITION = re.compile(r"[LH]{3}")


def filter_defaults(filter_type: str) -> dict[str, Any]:
    """Return the default parameters that the builder shows for *filter_type*."""

    return {name: default for name, _, default, _ in FILTER_PARAMETERS[filter_type]}


def default_filter(filter_type: str = "log") -> dict[str, Any]:
    """Return one entry of the filter list, with the defaults of *filter_type*."""

    return {"type": filter_type, "boundary": "default", "params": filter_defaults(filter_type)}


def numbers(text: Any, label: str) -> list[float]:
    """Parse numbers separated by commas or spaces, such as "-100, 0, 100"."""

    parts = re.split(r"[,\s]+", str(text).strip()) if text is not None else []
    if not parts or parts == [""]:
        raise ValueError(f"{label} needs at least one number.")
    return [finite_number(part, label) for part in parts]


def filter_step(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one entry of the filter list and return its pipeline step."""

    filter_type = entry.get("type")
    if not isinstance(filter_type, str) or filter_type not in FILTER_PARAMETERS:
        raise ValueError(f"Unknown image filter: {filter_type}")
    boundary = entry.get("boundary", "default")
    if boundary not in FILTER_BOUNDARIES:
        raise ValueError(f"Unknown filter boundary: {boundary}")
    values = entry.get("params")
    names = [name for name, _, _, _ in FILTER_PARAMETERS[filter_type]]
    if not isinstance(values, Mapping) or set(values) != set(names):
        raise ValueError(f"The {filter_type} filter needs these parameters: {', '.join(names)}.")
    params: dict[str, Any] = {"type": filter_type}
    if filter_type in _RIESZ_VARIANTS:
        params = {"type": "riesz", "variant": _RIESZ_VARIANTS[filter_type]}
    for name, kind, _, limits in FILTER_PARAMETERS[filter_type]:
        value = values[name]
        label = f"Filter {name.replace('_', ' ')}"
        if kind == "bool":
            if type(value) is not bool:
                raise ValueError(f"{label} must be on or off.")
        elif kind in ("int", "float"):
            number = finite_number(value, label)
            if kind == "int" and not number.is_integer():
                raise ValueError(f"{label} must be a whole number.")
            if not limits[0] <= number <= limits[1]:
                raise ValueError(f"{label} must be from {limits[0]} to {limits[1]}.")
            value = int(number) if kind == "int" else number
        elif kind == "choice":
            if value not in limits:
                raise ValueError(f"{label} must be one of: {', '.join(limits)}.")
        elif kind == "riesz_order":
            order = numbers(value, label)
            if len(order) != 3 or any(part < 0 or not part.is_integer() for part in order) or not sum(order):
                raise ValueError(f"{label} must be three whole numbers of 0 or more, such as 1, 0, 0.")
            value = [int(part) for part in order]
        else:
            pattern = _LAWS_KERNEL if kind == "laws_kernel" else _DECOMPOSITION
            if not isinstance(value, str) or pattern.fullmatch(value) is None:
                example = "L5E5E5" if kind == "laws_kernel" else "LLH"
                raise ValueError(f"{label} must look like {example}.")
        params[name] = value
    if boundary != "default":
        params["boundary"] = boundary
    return {"step": "filter", "params": params}


def finite_number(value: Any, label: str) -> float:
    """Parse a numeric editor value without accepting booleans or infinities."""
    try:
        if isinstance(value, bool) or not isinstance(value, (str, int, float)):
            raise ValueError
        result = float(value)
        if not math.isfinite(result):
            raise ValueError
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{label} must be a finite number.") from exc
    return result


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
    "grow_mask": frozenset({"to_mm", "from_mm", "nearest_roi", "apply_to"}),
    "normalise": frozenset({"method", "region", "percentiles", "range_min", "range_max"}),
    "round_intensities": frozenset(),
    "discretise": frozenset({"method", "n_bins", "bin_width", "min_val", "max_val", "cutoffs"}),
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
            "local_intensity_params",
            "spatial_intensity_params",
        }
    ),
}

# The package validates filters from their function signatures, not just _VALID_STEPS.
# These valid arguments are absent from that dispatch table.
FILTER_EXTRA_PARAMS = frozenset({"padding_value", "response"})


def default_inline_state() -> dict[str, Any]:
    """Builder state matching ``standard_fbn_32`` (a sensible starting point).

    The keys are in the order in which the steps run.
    """

    return {
        "source_mode": "full_image",
        "sentinel_value": None,
        "resample": True,
        "spacing": [0.5, 0.5, 0.5],
        "interpolation": "linear",
        "grow_mask": False,
        "grow_to_mm": 3.0,
        "grow_from_mm": None,
        "grow_apply_to": "both",
        "normalise": False,
        "normalise_method": "zscore",
        "normalise_region": "image",
        "normalise_percentiles": [1.0, 99.0],
        "normalise_range_min": None,
        "normalise_range_max": None,
        **ROI_REFINEMENT_DEFAULTS,
        "keep_largest": False,
        "keep_largest_apply_to": "both",
        "filter": False,
        "filters": [default_filter()],
        "include_unfiltered": False,
        "discretise": True,
        "discretise_method": "FBN",
        "discretise_value": 32.0,
        "fbs_minimum": None,
        "discretise_cutoffs": None,
        "families": list(CORE_FEATURE_FAMILIES),
        "texture_distance": 1,
        "ngldm_alpha": 0,
        "ivh_use_continuous": False,
    }


def upgrade_inline_state(state: Mapping[str, Any]) -> dict[str, Any]:
    """Return saved builder state with every current key.

    A step that did not exist when the state was saved stays off. A missing FBS
    minimum stays unchosen, and the one filter of older state becomes the filter list.
    """

    upgraded = dict(state)
    if "filter_type" in upgraded:
        upgraded["filters"] = [{
            "type": upgraded.pop("filter_type"),
            "boundary": upgraded.pop("filter_boundary", "default"),
            "params": upgraded.pop("filter_params", None),
        }]
    return {**default_inline_state(), "fbs_minimum": None, **upgraded}


def _optional_number(state: Mapping[str, Any], key: str, label: str) -> float | None:
    value = state.get(key)
    return None if value is None else finite_number(value, label)


def _whole_number(value: Any, label: str, minimum: int) -> int:
    number = finite_number(value, label)
    if not number.is_integer() or number < minimum:
        raise ValueError(f"{label} must be a whole number of {minimum} or more.")
    return int(number)


def _mask_target(state: Mapping[str, Any], key: str, label: str) -> str:
    target = state.get(key)
    if target not in MASK_TARGETS:
        raise ValueError(f"Unknown {label} mask target.")
    return str(target)


def _bounds(state: Mapping[str, Any], low_key: str, high_key: str, label: str) -> dict[str, float]:
    """Return the given ends of an intensity range, checked for order."""

    low = _optional_number(state, low_key, f"{label} minimum")
    high = _optional_number(state, high_key, f"{label} maximum")
    if low is not None and high is not None and low > high:
        raise ValueError(f"The {label.lower()} minimum must not exceed its maximum.")
    return {key: value for key, value in (("range_min", low), ("range_max", high)) if value is not None}


def build_inline_configuration_document(state: Mapping[str, Any]) -> dict[str, Any]:
    """Build a Pictologics configuration document from in-app builder state.

    Raises ``ValueError`` for choices the builder must not submit (no families, an
    unknown discretisation-requiring family without a discretise step, etc.). The
    returned dict is in the ``from_dict`` / ``load_configs`` serialization format.
    The document holds one configuration without a filter (``in_app``) and one for
    each entry of the filter list (``in_app_log_1``, ``in_app_log_2``, ...).
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

    # Mask growth runs after resampling and before the intensity range, so that a
    # range can keep one tissue of a ring (see the Pictologics step guide).
    if state.get("grow_mask", False):
        to_mm = finite_number(state.get("grow_to_mm"), "Growth distance")
        if not -100 <= to_mm <= 100:
            raise ValueError("The growth distance must be from -100 to 100 mm.")
        grow: dict[str, Any] = {"to_mm": to_mm}
        from_mm = _optional_number(state, "grow_from_mm", "Ring start")
        if from_mm is not None:
            if from_mm >= to_mm:
                raise ValueError("The ring start must be less than the growth distance.")
            grow["from_mm"] = from_mm
        grow["apply_to"] = _mask_target(state, "grow_apply_to", "mask-growth")
        steps.append({"step": "grow_mask", "params": grow})

    if state.get("normalise", False):
        method = state.get("normalise_method")
        region = state.get("normalise_region")
        if method not in NORMALISE_METHODS or region not in NORMALISE_REGIONS:
            raise ValueError("Unknown normalisation method or region.")
        normalise: dict[str, Any] = {"method": method, "region": region}
        if method == "percentile":
            percentiles = state.get("normalise_percentiles")
            low, high = (
                [finite_number(value, "Percentile") for value in percentiles]
                if isinstance(percentiles, (list, tuple)) and len(percentiles) == 2
                else (0.0, -1.0)
            )
            if not 0 <= low < high <= 100:
                raise ValueError("The two percentiles must rise from 0 to 100.")
            normalise["percentiles"] = [low, high]
        normalise.update(_bounds(state, "normalise_range_min", "normalise_range_max", "Normalisation"))
        steps.append({"step": "normalise", "params": normalise})

    # Refinement runs on continuous intensities, after any resampling and before
    # discretisation. Always serialize the target: upstream defaults affect shape.
    if state.get("resegment", False):
        bounds = _bounds(state, "range_min", "range_max", "Intensity range")
        if not bounds:
            raise ValueError("The intensity range needs at least one bound.")
        target = _mask_target(state, "resegment_apply_to", "resegmentation")
        steps.append({"step": "resegment", "params": {"range_min": None, "range_max": None, **bounds, "apply_to": target}})

    if state.get("filter_outliers", False):
        sigma = finite_number(state.get("outlier_sigma", 3.0), "Outlier sigma")
        if sigma <= 0:
            raise ValueError("Outlier sigma must be positive.")
        target = _mask_target(state, "outlier_apply_to", "outlier-filter")
        steps.append({"step": "filter_outliers", "params": {"sigma": sigma, "apply_to": target}})

    if state.get("keep_largest", False):
        target = _mask_target(state, "keep_largest_apply_to", "largest-part")
        steps.append({"step": "keep_largest_component", "params": {"apply_to": target}})

    tail: list[dict[str, Any]] = []
    needs_discretisation = bool(DISCRETISATION_REQUIRED_FAMILIES.intersection(families))
    if state.get("discretise", False):
        method = str(state.get("discretise_method", "FBN"))
        if method not in DISCRETISATION_METHODS:
            raise ValueError(f"Unknown discretisation method: {method}")
        params: dict[str, Any] = {"method": method}
        if method == "FIXED_CUTOFFS":
            cutoffs = numbers(state.get("discretise_cutoffs"), "Bin edges")
            if any(high <= low for low, high in zip(cutoffs, cutoffs[1:], strict=False)):
                raise ValueError("The bin edges must rise from left to right.")
            params["cutoffs"] = cutoffs
        else:
            value = float(state.get("discretise_value", 0.0))
            if value <= 0:
                raise ValueError("The discretisation bin count/width must be positive.")
            if method == "FBN":
                if not value.is_integer():
                    raise ValueError("The FBN bin count must be a whole number.")
                params["n_bins"] = int(value)
            else:
                params["bin_width"] = value
                if state.get("fbs_minimum") is None:
                    raise ValueError(
                        "FBS requires an explicit fixed minimum intensity. Enter the bin start "
                        "in image units (CT presets use -1000 HU); older FBS settings need review."
                    )
                params["min_val"] = finite_number(state["fbs_minimum"], "FBS minimum intensity")
        tail.append({"step": "discretise", "params": params})
    elif needs_discretisation:
        offenders = sorted(DISCRETISATION_REQUIRED_FAMILIES.intersection(families))
        raise ValueError("These families require a discretise step: " + ", ".join(offenders))

    extract: dict[str, Any] = {"families": families}
    distance = _whole_number(state.get("texture_distance", 1), "Texture distance", 1)
    alpha = _whole_number(state.get("ngldm_alpha", 0), "NGLDM coarseness", 0)
    if "texture" in families and (distance, alpha) != (1, 0):
        extract["texture_matrix_params"] = {
            "glcm_distance": distance,
            "ngtdm_distance": distance,
            "ngldm_distance": distance,
            "ngldm_alpha": alpha,
        }
    if "ivh" in families and state.get("ivh_use_continuous") is True:
        extract["ivh_use_continuous"] = True
    tail.append({"step": "extract_features", "params": extract})

    source_mode = str(state.get("source_mode", "full_image"))
    if source_mode not in SOURCE_MODES:
        raise ValueError(f"Unknown source mode: {source_mode}")

    def config(config_steps: list[dict[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {"source_mode": source_mode, "steps": config_steps}
        sentinel_value = state.get("sentinel_value")
        if sentinel_value is not None and source_mode != "full_image":
            result["sentinel_value"] = float(sentinel_value)
        return result

    configs: dict[str, Any] = {}
    filtered = bool(state.get("filter", False))
    if not filtered or state.get("include_unfiltered", False):
        configs[INLINE_CONFIG_NAME] = config(steps + tail)
    if filtered:
        entries = state.get("filters")
        if not isinstance(entries, list) or not entries:
            raise ValueError("Add a filter to the list, or turn off the image filter step.")
        counts: dict[str, int] = {}
        # IBSI 2: filter after resampling and mask refinement, and before discretisation.
        for entry in entries:
            step = filter_step(entry)
            counts[entry["type"]] = counts.get(entry["type"], 0) + 1
            configs[f"{INLINE_CONFIG_NAME}_{entry['type']}_{counts[entry['type']]}"] = config(steps + [step] + tail)

    return {"schema_version": CONFIG_SCHEMA_VERSION, "configs": configs}


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
    """Editable starter document for one standard preset."""

    if name not in _PRESET_DISCRETISATION:
        raise ValueError(f"Unknown standard preset: {name}")
    discretisation = dict(_PRESET_DISCRETISATION[name])
    if discretisation["method"] == "FBS":
        discretisation["min_val"] = -1000.0
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
                        "params": discretisation,
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
        allowed = _VALID_STEP_PARAMS[step_name]
        if step_name == "filter":
            allowed = allowed | FILTER_EXTRA_PARAMS
        if step_name == "grow_mask" and params.get("nearest_roi"):
            issues.append(f"{location}: nearest_roi requires joint-ROI execution, unsupported by this extension")
        for param in params:
            if param not in allowed:
                issues.append(f"{location} ({step_name}) has unknown parameter '{param}'")
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

    This is a pre-submission convenience check only. Apart from rejecting unsupported
    joint-ROI growth, it does not validate parameter *values*; the worker's
    ``load_configs(validate=True)`` is authoritative.
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


# Must equal PictologicsCLI.CONFIGURATION_CHECK_PREFIX.
CONFIGURATION_CHECK_PREFIX = "PICTOLOGICS_CONFIGURATION_CHECK "


def parse_configuration_check(output: str) -> dict[str, Any]:
    """Return the result that ``PictologicsCLI.py --check-configuration`` printed.

    The result has ``valid``, and then ``configurations`` and ``document`` or ``error``.
    Other output lines are log text; the last one explains a check that did not finish.
    """

    lines = [line for line in output.splitlines() if line.strip()]
    for line in reversed(lines):
        if line.startswith(CONFIGURATION_CHECK_PREFIX):
            result: dict[str, Any] = json.loads(line[len(CONFIGURATION_CHECK_PREFIX) :])
            return result
    raise ValueError(
        "The configuration check did not finish: " + (lines[-1] if lines else "no output")
    )
