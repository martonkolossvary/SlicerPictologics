#!/usr/bin/env python-real
"""Standalone Slicer scripted CLI worker for Pictologics.

The module deliberately imports only Python's standard library at module import
time.  ``main`` first removes non-private site-package paths, then imports
Pictologics from the extension-owned pip target.  Most functions accept their
dependencies as arguments so they can be tested without Slicer or Pictologics.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import json
import math
import ntpath
import os
import re
import sys
import tempfile
import traceback
import warnings
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO, cast
from xml.sax.saxutils import escape as xml_escape

MANIFEST_SCHEMA_VERSION = 1
OUTPUT_SCHEMA_VERSION = 2
# The GUI runs `PictologicsCLI.py --check-configuration <file> <dependencyPath>` and
# reads the one output line that starts with this prefix.
CONFIGURATION_CHECK_PREFIX = "PICTOLOGICS_CONFIGURATION_CHECK "

MANIFEST_REQUIRED_KEYS = frozenset(
    {
        "schema_version",
        "run_id",
        "timestamp",
        "subject_id",
        "image",
        "rois",
        "configuration_document",
        "configuration_sha256",
        "output",
        "extension_version",
        "pictologics_requirement",
        "metadata",
    }
)
MANIFEST_OPTIONAL_KEYS = frozenset({"subject_metadata", "result_columns"})
MANIFEST_KEYS = MANIFEST_REQUIRED_KEYS | MANIFEST_OPTIONAL_KEYS

IMAGE_KEYS = frozenset({"path", "name"})
ROI_REQUIRED_KEYS = frozenset({"roi_id", "roi_name", "roi_source", "mask_path"})
ROI_KEYS = ROI_REQUIRED_KEYS | {"metadata"}
CONFIGURATION_DOCUMENT_REQUIRED_KEYS = frozenset(
    {"standard_configurations", "custom_configuration_path", "warmup"}
)
CONFIGURATION_DOCUMENT_KEYS = CONFIGURATION_DOCUMENT_REQUIRED_KEYS | {
    "custom_configuration_sha256",
    "crop_to_roi",
}
OUTPUT_REQUIRED_KEYS = frozenset({"results_path"})
OUTPUT_KEYS = OUTPUT_REQUIRED_KEYS | {"provenance_path"}
METADATA_REQUIRED_KEYS = frozenset({"numba_cache_path"})
METADATA_KEYS = METADATA_REQUIRED_KEYS | {
    "pictologics_version_at_submission",
    "input_volume_node_id",
}

LONG_ROW_COLUMNS = (
    "run_id",
    "timestamp",
    "subject_id",
    "image_name",
    "roi_source",
    "roi_id",
    "roi_name",
    "config",
    "family",
    "feature_name",
    "feature_key",
    "ibsi_code",
    "pictologics_ibsi_code",
    "pictologics_feature_name",
    "preprocessing_sequence",
    "value",
    "status",
    "pictologics_version",
    "extension_version",
)

# Must equal the rule of PictologicsLib.results.is_extra_column_name.
_EXTRA_COLUMN_NAME = re.compile(r"[A-Za-z](?:_?[A-Za-z0-9])*")
_NIFTI_SUFFIXES = (".nii", ".nii.gz")
_CONFIG_SUFFIXES = (".json", ".yaml", ".yml")
_SITE_PACKAGE_PARTS = frozenset({"site-packages", "dist-packages"})
_WHOLE_VOLUME_SOURCE = "whole-volume"
_EXACT_PICTOLOGICS_REQUIREMENT = re.compile(
    r"^pictologics==(?P<version>[0-9]+\.[0-9]+\.[0-9]+)$",
    re.IGNORECASE,
)
_PICTOLOGICS_FEATURE_CODE = re.compile(
    r"_(?P<ibsi_code>[A-Z0-9]{3,4})(?P<variant>_\d+)?$"
)


def _pictologics_ibsi_code(
    feature_key: str, feature_name: str, ibsi_code: str
) -> str:
    """Return Pictologics' full, potentially disambiguated feature identifier."""

    prefix = f"{feature_name}_"
    if feature_name and feature_key.startswith(prefix):
        candidate = feature_key[len(prefix) :]
        if candidate:
            return candidate
    return ibsi_code


def _pictologics_feature_name(configuration: str, feature_key: str) -> str:
    """Return the exact column name produced by Pictologics' wide formatter."""

    return f"{configuration}__{feature_key}"


class PictologicsCLIError(RuntimeError):
    """Expected worker error that can be shown to the user without a traceback."""


class ManifestValidationError(PictologicsCLIError):
    """The job manifest does not conform to the v1 contract."""


class DependencyIsolationError(PictologicsCLIError):
    """The private dependency target cannot be used safely."""


class WorkerSetupError(PictologicsCLIError):
    """Pictologics or its requested configurations cannot be prepared."""


class JobExecutionError(PictologicsCLIError):
    """A fatal error prevents the complete job from being executed."""


@dataclass(frozen=True)
class ROIManifest:
    """One independently processed ROI."""

    roi_id: str
    roi_name: str
    roi_source: str
    mask_path: Path | None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "roi_id": self.roi_id,
            "roi_name": self.roi_name,
            "roi_source": self.roi_source,
            "mask_path": str(self.mask_path) if self.mask_path is not None else None,
        }
        if self.metadata is not None:
            result["metadata"] = copy.deepcopy(self.metadata)
        return result


@dataclass(frozen=True)
class JobManifest:
    """Validated and normalized v1 job manifest."""

    schema_version: int
    run_id: str
    timestamp: str
    extension_version: str
    subject_id: str
    image_name: str
    image_path: Path
    rois: tuple[ROIManifest, ...]
    configuration_document: dict[str, Any]
    configuration_sha256: str
    standard_configurations: tuple[str, ...]
    custom_configuration_path: Path | None
    custom_configuration_sha256: str | None
    warmup: bool
    results_path: Path
    provenance_path: Path | None
    numba_cache_path: Path
    pictologics_requirement: str
    metadata: dict[str, Any]
    subject_metadata: dict[str, Any] | None = None
    result_columns: tuple[tuple[str, str], ...] | None = None
    crop_to_roi: bool = False

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "subject_id": self.subject_id,
            "image": {"path": str(self.image_path), "name": self.image_name},
            "rois": [roi.to_dict() for roi in self.rois],
            # Preserve the original manifest-relative custom configuration path:
            # changing it here would invalidate configuration_sha256.
            "configuration_document": copy.deepcopy(self.configuration_document),
            "configuration_sha256": self.configuration_sha256,
            "output": {"results_path": str(self.results_path)},
            "extension_version": self.extension_version,
            "pictologics_requirement": self.pictologics_requirement,
            "metadata": copy.deepcopy(self.metadata),
        }
        if self.provenance_path is not None:
            result["output"]["provenance_path"] = str(self.provenance_path)
        if self.subject_metadata is not None:
            result["subject_metadata"] = copy.deepcopy(self.subject_metadata)
        if self.result_columns is not None:
            result["result_columns"] = [list(pair) for pair in self.result_columns]
        return result


@dataclass(frozen=True)
class PipelineBundle:
    """Pipeline plus immutable metadata used to format every ROI consistently."""

    pipeline: Any
    selected_configurations: tuple[str, ...]
    catalog_records: tuple[dict[str, Any], ...]
    catalog_by_config: dict[str, tuple[dict[str, Any], ...]]
    configuration_document: Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _format_key_error(context: str, actual: set[str], expected: frozenset[str]) -> str:
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    details: list[str] = []
    if missing:
        details.append(f"missing keys: {', '.join(missing)}")
    if unknown:
        details.append(f"unknown keys: {', '.join(unknown)}")
    return f"{context} has an invalid shape ({'; '.join(details)})"


def _validate_object_keys(
    value: Mapping[str, Any],
    context: str,
    *,
    required: frozenset[str],
    allowed: frozenset[str],
) -> None:
    actual = set(value)
    missing = sorted(required - actual)
    unknown = sorted(actual - allowed)
    details: list[str] = []
    if missing:
        details.append(f"missing keys: {', '.join(missing)}")
    if unknown:
        details.append(f"unknown keys: {', '.join(unknown)}")
    if details:
        raise ManifestValidationError(
            f"{context} has an invalid shape ({'; '.join(details)})"
        )


def _require_string(
    value: Any,
    field: str,
    *,
    allow_empty: bool = False,
) -> str:
    if type(value) is not str:
        raise ManifestValidationError(f"'{field}' must be a string")
    if not allow_empty and not value.strip():
        raise ManifestValidationError(f"'{field}' must not be empty")
    return value


def _resolve_manifest_path(value: str, base_dir: Path) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = base_dir / candidate
    return candidate.resolve(strict=False)


def _require_existing_file(path: Path, field: str) -> None:
    if not path.exists():
        raise ManifestValidationError(f"'{field}' does not exist: {path}")
    if not path.is_file():
        raise ManifestValidationError(f"'{field}' must be a file: {path}")


def _has_suffix(path: Path, suffixes: Sequence[str]) -> bool:
    return path.name.lower().endswith(tuple(suffixes))


def _validate_timestamp(value: str) -> None:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ManifestValidationError(
            "'timestamp' must be an ISO-8601 date-time with a timezone"
        ) from exc
    if "T" not in value or parsed.tzinfo is None:
        raise ManifestValidationError(
            "'timestamp' must be an ISO-8601 date-time with a timezone"
        )


def _strict_json_copy(value: Any, field: str) -> Any:
    try:
        encoded = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ManifestValidationError(
            f"'{field}' must contain only finite JSON values: {exc}"
        ) from exc


def configuration_sha256(configuration_document: Any) -> str:
    """Hash configuration JSON exactly as the GUI-side manifest builder does."""

    try:
        canonical = json.dumps(
            configuration_document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ManifestValidationError(
            f"'configuration_document' is not canonical JSON: {exc}"
        ) from exc
    return hashlib.sha256(canonical).hexdigest()


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while chunk := stream.read(chunk_size):
                digest.update(chunk)
    except OSError as exc:
        raise ManifestValidationError(
            f"cannot hash custom configuration '{path}': {exc}"
        ) from exc
    return digest.hexdigest()


def validate_manifest(
    data: Any,
    *,
    base_dir: str | Path | None = None,
    check_paths: bool = True,
) -> JobManifest:
    """Validate and normalize one v1 manifest.

    Relative paths are resolved against ``base_dir`` (the manifest directory in
    normal CLI use).  Unknown fields are rejected so GUI/worker contract drift
    fails loudly instead of silently producing incomplete provenance.
    """

    if not isinstance(data, dict):
        raise ManifestValidationError("job manifest root must be a JSON object")
    data = _strict_json_copy(data, "job manifest")
    _validate_object_keys(
        data,
        "job manifest",
        required=MANIFEST_REQUIRED_KEYS,
        allowed=MANIFEST_KEYS,
    )

    schema_version = data["schema_version"]
    if type(schema_version) is not int or schema_version != MANIFEST_SCHEMA_VERSION:
        raise ManifestValidationError(
            f"'schema_version' must be integer {MANIFEST_SCHEMA_VERSION}"
        )

    run_id = _require_string(data["run_id"], "run_id")
    timestamp = _require_string(data["timestamp"], "timestamp")
    _validate_timestamp(timestamp)
    extension_version = _require_string(
        data["extension_version"], "extension_version", allow_empty=True
    )
    pictologics_requirement = _require_string(
        data["pictologics_requirement"], "pictologics_requirement", allow_empty=True
    )
    subject_id = _require_string(data["subject_id"], "subject_id", allow_empty=True)

    base_path = Path(base_dir if base_dir is not None else os.getcwd()).resolve(
        strict=False
    )
    image_data = data["image"]
    if not isinstance(image_data, dict):
        raise ManifestValidationError("'image' must be an object")
    if set(image_data) != IMAGE_KEYS:
        raise ManifestValidationError(
            _format_key_error("image", set(image_data), IMAGE_KEYS)
        )
    image_name = _require_string(image_data["name"], "image.name")
    image_path_text = _require_string(image_data["path"], "image.path")
    image_path = _resolve_manifest_path(image_path_text, base_path)
    if not _has_suffix(image_path, _NIFTI_SUFFIXES):
        raise ManifestValidationError(
            "'image.path' must point to a .nii or .nii.gz file"
        )
    if check_paths:
        _require_existing_file(image_path, "image.path")

    roi_data = data["rois"]
    if type(roi_data) is not list or not roi_data:
        raise ManifestValidationError("'rois' must be a non-empty array")
    rois: list[ROIManifest] = []
    roi_ids_seen: set[str] = set()
    for index, raw_roi in enumerate(roi_data):
        field_prefix = f"rois[{index}]"
        if not isinstance(raw_roi, dict):
            raise ManifestValidationError(f"'{field_prefix}' must be an object")
        _validate_object_keys(
            raw_roi,
            field_prefix,
            required=ROI_REQUIRED_KEYS,
            allowed=ROI_KEYS,
        )
        roi_id = _require_string(raw_roi["roi_id"], f"{field_prefix}.roi_id")
        roi_name = _require_string(raw_roi["roi_name"], f"{field_prefix}.roi_name")
        roi_source = _require_string(
            raw_roi["roi_source"], f"{field_prefix}.roi_source"
        )
        if roi_id in roi_ids_seen:
            raise ManifestValidationError(
                f"duplicate ROI id at '{field_prefix}': {roi_id}"
            )
        roi_ids_seen.add(roi_id)

        raw_mask_path = raw_roi["mask_path"]
        mask_path: Path | None
        if raw_mask_path is None:
            if roi_source != _WHOLE_VOLUME_SOURCE:
                raise ManifestValidationError(
                    f"'{field_prefix}.mask_path' may be null only when roi_source is "
                    f"'{_WHOLE_VOLUME_SOURCE}'"
                )
            mask_path = None
        else:
            if roi_source == _WHOLE_VOLUME_SOURCE:
                raise ManifestValidationError(
                    f"'{field_prefix}.mask_path' must be null for whole volume"
                )
            mask_path_text = _require_string(raw_mask_path, f"{field_prefix}.mask_path")
            mask_path = _resolve_manifest_path(mask_path_text, base_path)
            if not _has_suffix(mask_path, _NIFTI_SUFFIXES):
                raise ManifestValidationError(
                    f"'{field_prefix}.mask_path' must point to a .nii or .nii.gz file"
                )
            if check_paths:
                _require_existing_file(mask_path, f"{field_prefix}.mask_path")

        roi_metadata: dict[str, Any] | None = None
        if "metadata" in raw_roi:
            if not isinstance(raw_roi["metadata"], dict):
                raise ManifestValidationError(
                    f"'{field_prefix}.metadata' must be an object"
                )
            roi_metadata = _strict_json_copy(
                raw_roi["metadata"], f"{field_prefix}.metadata"
            )

        rois.append(
            ROIManifest(
                roi_id=roi_id,
                roi_name=roi_name,
                roi_source=roi_source,
                mask_path=mask_path,
                metadata=roi_metadata,
            )
        )

    configuration_document = data["configuration_document"]
    if not isinstance(configuration_document, dict):
        raise ManifestValidationError("'configuration_document' must be an object")
    _validate_object_keys(
        configuration_document,
        "configuration_document",
        required=CONFIGURATION_DOCUMENT_REQUIRED_KEYS,
        allowed=CONFIGURATION_DOCUMENT_KEYS,
    )
    expected_configuration_hash = configuration_sha256(configuration_document)
    supplied_configuration_hash = _require_string(
        data["configuration_sha256"], "configuration_sha256"
    )
    if len(supplied_configuration_hash) != 64 or any(
        character not in "0123456789abcdef" for character in supplied_configuration_hash
    ):
        raise ManifestValidationError(
            "'configuration_sha256' must be a lowercase SHA-256 digest"
        )
    if supplied_configuration_hash != expected_configuration_hash:
        raise ManifestValidationError(
            "'configuration_sha256' does not match configuration_document"
        )

    raw_standard_configs = configuration_document["standard_configurations"]
    if type(raw_standard_configs) is not list:
        raise ManifestValidationError("'standard_configurations' must be an array")
    standard_configurations: list[str] = []
    seen_configs: set[str] = set()
    for index, raw_name in enumerate(raw_standard_configs):
        name = _require_string(raw_name, f"standard_configurations[{index}]")
        if not name.startswith("standard_"):
            raise ManifestValidationError(
                f"'standard_configurations[{index}]' must name a standard_ configuration"
            )
        if name in seen_configs:
            raise ManifestValidationError(f"duplicate standard configuration: {name}")
        seen_configs.add(name)
        standard_configurations.append(name)

    raw_custom_path = configuration_document["custom_configuration_path"]
    custom_path: Path | None
    if raw_custom_path is None:
        custom_path = None
    else:
        custom_path_text = _require_string(raw_custom_path, "custom_configuration_path")
        custom_path = _resolve_manifest_path(custom_path_text, base_path)
        if not _has_suffix(custom_path, _CONFIG_SUFFIXES):
            raise ManifestValidationError(
                "'custom_configuration_path' must point to JSON or YAML"
            )
        if check_paths:
            _require_existing_file(custom_path, "custom_configuration_path")

    raw_custom_hash = configuration_document.get("custom_configuration_sha256")
    custom_configuration_hash: str | None
    if raw_custom_hash is None:
        custom_configuration_hash = None
    else:
        custom_configuration_hash = _require_string(
            raw_custom_hash, "configuration_document.custom_configuration_sha256"
        )
        if len(custom_configuration_hash) != 64 or any(
            character not in "0123456789abcdef"
            for character in custom_configuration_hash
        ):
            raise ManifestValidationError(
                "'configuration_document.custom_configuration_sha256' must be null or "
                "a lowercase SHA-256 digest"
            )
    if custom_path is None and custom_configuration_hash is not None:
        raise ManifestValidationError(
            "'configuration_document.custom_configuration_sha256' must be null when "
            "custom_configuration_path is null"
        )
    if (
        check_paths
        and custom_path is not None
        and custom_configuration_hash is not None
    ):
        actual_custom_hash = file_sha256(custom_path)
        if actual_custom_hash != custom_configuration_hash:
            raise ManifestValidationError(
                "'configuration_document.custom_configuration_sha256' does not match "
                "the custom configuration file"
            )

    if not standard_configurations and custom_path is None:
        raise ManifestValidationError(
            "the manifest must select a standard configuration or provide a custom configuration"
        )

    warmup = configuration_document["warmup"]
    if type(warmup) is not bool:
        raise ManifestValidationError(
            "'configuration_document.warmup' must be a boolean"
        )
    crop_to_roi = configuration_document.get("crop_to_roi", False)
    if type(crop_to_roi) is not bool:
        raise ManifestValidationError(
            "'configuration_document.crop_to_roi' must be a boolean"
        )

    output = data["output"]
    if not isinstance(output, dict):
        raise ManifestValidationError("'output' must be an object")
    _validate_object_keys(
        output,
        "output",
        required=OUTPUT_REQUIRED_KEYS,
        allowed=OUTPUT_KEYS,
    )
    results_path = _resolve_manifest_path(
        _require_string(output["results_path"], "output.results_path"), base_path
    )
    if results_path.suffix.lower() != ".json":
        raise ManifestValidationError("'output.results_path' must end in .json")
    if results_path.exists() and results_path.is_dir():
        raise ManifestValidationError(
            f"'output.results_path' is a directory: {results_path}"
        )
    provenance_path: Path | None = None
    if "provenance_path" in output:
        provenance_path = _resolve_manifest_path(
            _require_string(output["provenance_path"], "output.provenance_path"),
            base_path,
        )
        if provenance_path.suffix.lower() != ".json":
            raise ManifestValidationError("'output.provenance_path' must end in .json")
        if provenance_path == results_path:
            raise ManifestValidationError(
                "'output.provenance_path' must differ from output.results_path"
            )
        if provenance_path.exists() and provenance_path.is_dir():
            raise ManifestValidationError(
                f"'output.provenance_path' is a directory: {provenance_path}"
            )

    metadata = data["metadata"]
    if not isinstance(metadata, dict):
        raise ManifestValidationError("'metadata' must be an object")
    _validate_object_keys(
        metadata,
        "metadata",
        required=METADATA_REQUIRED_KEYS,
        allowed=METADATA_KEYS,
    )
    metadata = _strict_json_copy(metadata, "metadata")
    if "pictologics_version_at_submission" in metadata:
        submitted_version = metadata["pictologics_version_at_submission"]
        if submitted_version is not None and type(submitted_version) is not str:
            raise ManifestValidationError(
                "'metadata.pictologics_version_at_submission' must be a string or null"
            )
    if (
        "input_volume_node_id" in metadata
        and type(metadata["input_volume_node_id"]) is not str
    ):
        raise ManifestValidationError(
            "'metadata.input_volume_node_id' must be a string"
        )
    cache_path_text = _require_string(
        metadata["numba_cache_path"], "metadata.numba_cache_path"
    )
    numba_cache_path = _resolve_manifest_path(cache_path_text, base_path)
    if numba_cache_path.exists() and not numba_cache_path.is_dir():
        raise ManifestValidationError(
            f"'metadata.numba_cache_path' exists but is not a directory: {numba_cache_path}"
        )

    subject_metadata: dict[str, Any] | None = None
    if "subject_metadata" in data:
        if not isinstance(data["subject_metadata"], dict):
            raise ManifestValidationError("'subject_metadata' must be an object")
        subject_metadata = _strict_json_copy(
            data["subject_metadata"], "subject_metadata"
        )

    result_columns: tuple[tuple[str, str], ...] | None = None
    if "result_columns" in data:
        result_columns = _validate_result_columns(data["result_columns"])

    return JobManifest(
        schema_version=schema_version,
        run_id=run_id,
        timestamp=timestamp,
        extension_version=extension_version,
        subject_id=subject_id,
        image_name=image_name,
        image_path=image_path,
        rois=tuple(rois),
        configuration_document=copy.deepcopy(configuration_document),
        configuration_sha256=supplied_configuration_hash,
        standard_configurations=tuple(standard_configurations),
        custom_configuration_path=custom_path,
        custom_configuration_sha256=custom_configuration_hash,
        warmup=warmup,
        results_path=results_path,
        provenance_path=provenance_path,
        numba_cache_path=numba_cache_path,
        pictologics_requirement=pictologics_requirement,
        metadata=metadata,
        subject_metadata=subject_metadata,
        result_columns=result_columns,
        crop_to_roi=crop_to_roi,
    )


def _validate_result_columns(value: Any) -> tuple[tuple[str, str], ...]:
    """Return the ordered [name, text] pairs that the worker adds to every row."""

    pairs = value if isinstance(value, list) else [None]
    columns = tuple(
        (pair[0], pair[1])
        for pair in pairs
        if isinstance(pair, list)
        and len(pair) == 2
        and isinstance(pair[0], str)
        and isinstance(pair[1], str)
        and len(pair[0]) <= 64
        and pair[0] not in LONG_ROW_COLUMNS
        and _EXTRA_COLUMN_NAME.fullmatch(pair[0])
    )
    if len(columns) != len(pairs) or len({name for name, _ in columns}) != len(columns):
        raise ManifestValidationError(
            "'result_columns' must be [name, text] pairs with unique extra column names"
        )
    return columns


def load_manifest(path: str | Path) -> JobManifest:
    """Read and validate a UTF-8 JSON manifest."""

    manifest_path = Path(path).resolve(strict=False)
    if not manifest_path.exists():
        raise ManifestValidationError(f"job manifest does not exist: {manifest_path}")
    if not manifest_path.is_file():
        raise ManifestValidationError(f"job manifest must be a file: {manifest_path}")
    if manifest_path.suffix.lower() != ".json":
        raise ManifestValidationError("job manifest filename must end in .json")
    try:
        with manifest_path.open("r", encoding="utf-8") as stream:
            data = json.load(stream)
    except UnicodeDecodeError as exc:
        raise ManifestValidationError("job manifest must be UTF-8 encoded") from exc
    except json.JSONDecodeError as exc:
        raise ManifestValidationError(
            f"job manifest is not valid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    except OSError as exc:
        raise ManifestValidationError(f"cannot read job manifest: {exc}") from exc
    return validate_manifest(data, base_dir=manifest_path.parent)


def _is_site_package_entry(path_entry: str) -> bool:
    if not path_entry:
        return False
    try:
        parts = Path(path_entry).parts
    except (OSError, TypeError, ValueError):
        return False
    return any(part.casefold() in _SITE_PACKAGE_PARTS for part in parts)


def isolate_dependency_path(
    dependency_path: str | Path,
    *,
    search_path: Sequence[str] | None = None,
) -> list[str]:
    """Put the private pip target first and remove every other site-packages entry.

    If ``search_path`` is omitted then ``sys.path`` is modified in place and
    import caches are invalidated.  Supplying a sequence makes the function
    side-effect free, which is useful for unit tests.
    """

    target = Path(dependency_path).resolve(strict=False)
    if not target.exists():
        raise DependencyIsolationError(
            f"private dependency directory does not exist: {target}"
        )
    if not target.is_dir():
        raise DependencyIsolationError(
            f"private dependency path is not a directory: {target}"
        )

    original = list(sys.path if search_path is None else search_path)
    target_text = str(target)
    kept: list[str] = []
    for entry in original:
        if entry:
            try:
                if Path(entry).resolve(strict=False) == target:
                    continue
            except (OSError, ValueError):
                pass
        if _is_site_package_entry(entry):
            continue
        kept.append(entry)
    isolated = [target_text, *kept]

    if search_path is None:
        sys.path[:] = isolated
        importlib.invalidate_caches()
    return isolated


def _numba_cache_directory(path: Path) -> str:
    """Keep Numba's long generated filenames usable under Windows MAX_PATH.

    The manifest already contains an absolute cache path. Use the extended path
    spelling only for Python/Numba I/O; provenance keeps the ordinary spelling.
    This does not require a registry or machine-wide long-path policy change.
    """

    directory = str(path)
    if sys.platform != "win32":
        return directory
    directory = ntpath.normpath(directory)
    if directory.startswith("\\\\?\\"):
        return directory
    if directory.startswith("\\\\"):
        return "\\\\?\\UNC\\" + directory[2:]
    return "\\\\?\\" + directory


def configure_environment(manifest: JobManifest) -> None:
    """Configure Numba and suppress Pictologics' import-time JIT warmup."""

    cache_directory = _numba_cache_directory(manifest.numba_cache_path)
    try:
        Path(cache_directory).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise WorkerSetupError(
            f"cannot create Numba cache directory '{manifest.numba_cache_path}': {exc}"
        ) from exc
    os.environ["NUMBA_CACHE_DIR"] = cache_directory
    os.environ["PICTOLOGICS_DISABLE_WARMUP"] = "1"


def _path_is_inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def import_private_pictologics(dependency_path: str | Path, *, warmup: bool) -> Any:
    """Import Pictologics and verify it came from the private dependency target."""

    target = Path(dependency_path).resolve(strict=False)
    try:
        module = importlib.import_module("pictologics")
    except Exception as exc:
        raise WorkerSetupError(
            f"cannot import Pictologics from private dependency directory '{target}': "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    module_file = getattr(module, "__file__", None)
    if not module_file:
        raise DependencyIsolationError("imported Pictologics has no filesystem origin")
    origin = Path(module_file).resolve(strict=False)
    if not _path_is_inside(origin, target):
        raise DependencyIsolationError(
            "refusing to run because Pictologics was imported outside the private "
            f"dependency directory (origin: {origin}, expected under: {target})"
        )

    if warmup:
        warmup_jit = getattr(module, "warmup_jit", None)
        if not callable(warmup_jit):
            raise WorkerSetupError("installed Pictologics does not expose warmup_jit()")
        os.environ["PICTOLOGICS_DISABLE_WARMUP"] = "0"
        try:
            warmup_jit()
        except Exception as exc:
            raise WorkerSetupError(
                f"Pictologics JIT warmup failed: {type(exc).__name__}: {exc}"
            ) from exc
    return module


def verify_runtime_version(manifest: JobManifest, pictologics: Any) -> str:
    """Require the worker import to match the exact version submitted by the GUI."""

    requirement_match = _EXACT_PICTOLOGICS_REQUIREMENT.fullmatch(
        manifest.pictologics_requirement.strip()
    )
    if requirement_match is None:
        raise WorkerSetupError(
            "the job does not contain an exact adopted Pictologics requirement"
        )
    expected = requirement_match.group("version")
    submitted = manifest.metadata.get("pictologics_version_at_submission")
    if submitted != expected:
        raise WorkerSetupError(
            "the submitted Pictologics version does not match the adopted requirement "
            f"({submitted!r} != {expected!r})"
        )
    imported = str(getattr(pictologics, "__version__", ""))
    if imported != expected:
        raise WorkerSetupError(
            "the imported private Pictologics version changed after submission "
            f"({imported!r} != {expected!r})"
        )
    return imported


def _catalog_to_records(catalog: Any) -> list[dict[str, Any]]:
    if isinstance(catalog, list):
        raw_records = catalog
    else:
        to_dict = getattr(catalog, "to_dict", None)
        if not callable(to_dict):
            raise WorkerSetupError(
                "describe_features() did not return a tabular catalog"
            )
        try:
            raw_records = to_dict(orient="records")
        except TypeError:
            raw_records = to_dict("records")
    if not isinstance(raw_records, list):
        raise WorkerSetupError(
            "describe_features() catalog could not be converted to records"
        )

    records: list[dict[str, Any]] = []
    for index, record in enumerate(raw_records):
        if not isinstance(record, Mapping):
            raise WorkerSetupError(f"feature catalog row {index} is not an object")
        copied = dict(record)
        if not isinstance(copied.get("config"), str) or not isinstance(
            copied.get("feature_key"), str
        ):
            raise WorkerSetupError(
                f"feature catalog row {index} lacks string 'config' or 'feature_key'"
            )
        configuration = copied["config"]
        feature_key = copied["feature_key"]
        feature_name_value = copied.get("feature_name", feature_key)
        feature_name = (
            feature_name_value if isinstance(feature_name_value, str) else feature_key
        )
        ibsi_code_value = copied.get("ibsi_code", "")
        ibsi_code = ibsi_code_value if isinstance(ibsi_code_value, str) else ""
        copied["pictologics_ibsi_code"] = _pictologics_ibsi_code(
            feature_key, feature_name, ibsi_code
        )
        copied["pictologics_feature_name"] = _pictologics_feature_name(
            configuration, feature_key
        )
        records.append(copied)
    return records


def _new_pipeline(pictologics: Any) -> Any:
    try:
        # Pictologics 0.5.1 and earlier can copy wrong values from one configuration
        # to another when its reuse shortcut (deduplication) is on. Compute every
        # configuration on its own until the adopted release contains the fix.
        return pictologics.RadiomicsPipeline(deduplicate=False)
    except Exception as exc:
        raise WorkerSetupError(
            f"cannot initialize RadiomicsPipeline: {type(exc).__name__}: {exc}"
        ) from exc


def _merge_custom_configurations(
    pictologics: Any, pipeline: Any, path: Path
) -> list[str]:
    """Add the configurations of a custom file to ``pipeline``; return their names."""

    try:
        # Pictologics' load_configs(validate=True) only *warns* on malformed
        # steps/params and on configs it silently skips; it never raises. Capture
        # those UserWarnings and fail loudly so an invalid custom file is rejected
        # before extraction instead of silently producing NaN feature rows.
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            custom_pipeline = pictologics.RadiomicsPipeline.load_configs(
                path,
                validate=True,
                load_standard=False,
            )
            custom_names = list(custom_pipeline.list_configs())
        validation_messages = [
            str(entry.message)
            for entry in caught
            if issubclass(entry.category, UserWarning)
        ]
    except Exception as exc:
        raise WorkerSetupError(
            f"cannot load custom configuration '{path}': {type(exc).__name__}: {exc}"
        ) from exc
    if validation_messages:
        raise WorkerSetupError(
            "custom configuration failed validation: " + "; ".join(validation_messages)
        )
    if not custom_names:
        raise WorkerSetupError("custom configuration file contains no configurations")
    existing = set(pipeline.list_configs())
    collisions = sorted(existing.intersection(custom_names))
    if collisions:
        raise WorkerSetupError(
            "custom configuration names collide with built-in configurations: "
            + ", ".join(collisions)
        )
    if len(custom_names) != len(set(custom_names)):
        raise WorkerSetupError("custom configuration file contains duplicate names")
    try:
        pipeline.merge_configs(custom_pipeline, overwrite=False)
    except Exception as exc:
        raise WorkerSetupError(f"cannot register custom configurations: {exc}") from exc
    return custom_names


def _describe_configurations(
    pipeline: Any, selected: Sequence[str]
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]], dict[str, Any]]:
    """Return the feature catalog of ``selected``, by configuration, and their settings."""

    try:
        catalog_records = _catalog_to_records(pipeline.describe_features())
    except PictologicsCLIError:
        raise
    except Exception as exc:
        raise WorkerSetupError(f"cannot describe configured features: {exc}") from exc

    selected_set = set(selected)
    selected_records = [
        record for record in catalog_records if record["config"] in selected_set
    ]
    catalog_by_config: dict[str, list[dict[str, Any]]] = {name: [] for name in selected}
    for record in selected_records:
        catalog_by_config[record["config"]].append(record)
    empty_configs = [name for name in selected if not catalog_by_config[name]]
    if empty_configs:
        raise WorkerSetupError(
            "configuration(s) describe no features; add an extract_features step: "
            + ", ".join(empty_configs)
        )

    try:
        configuration_document = pipeline.to_dict(config_names=list(selected))
    except Exception as exc:
        raise WorkerSetupError(
            f"cannot serialize effective configurations: {exc}"
        ) from exc
    return selected_records, catalog_by_config, configuration_document


def create_pipeline(pictologics: Any, manifest: JobManifest) -> PipelineBundle:
    """Create a standard/custom pipeline and its describe_features lookup."""

    pipeline = _new_pipeline(pictologics)
    try:
        available_standard = set(pipeline.get_all_standard_config_names())
    except Exception as exc:
        raise WorkerSetupError(
            f"cannot enumerate standard configurations: {exc}"
        ) from exc
    missing_standard = [
        name
        for name in manifest.standard_configurations
        if name not in available_standard
    ]
    if missing_standard:
        raise WorkerSetupError(
            "requested standard configuration(s) are unavailable in the installed "
            f"Pictologics version: {', '.join(missing_standard)}"
        )

    selected = list(manifest.standard_configurations)
    if manifest.custom_configuration_path is not None:
        selected.extend(
            _merge_custom_configurations(
                pictologics, pipeline, manifest.custom_configuration_path
            )
        )
    if not selected:
        raise WorkerSetupError("no configurations were selected")

    selected_records, catalog_by_config, configuration_document = (
        _describe_configurations(pipeline, selected)
    )
    return PipelineBundle(
        pipeline=pipeline,
        selected_configurations=tuple(selected),
        catalog_records=tuple(selected_records),
        catalog_by_config={
            name: tuple(records) for name, records in catalog_by_config.items()
        },
        configuration_document=configuration_document,
    )


def check_configuration_file(pictologics: Any, path: Path) -> dict[str, Any]:
    """Check a custom configuration file with the same steps as a run."""

    try:
        pipeline = _new_pipeline(pictologics)
        names = _merge_custom_configurations(pictologics, pipeline, path)
        _, _, document = _describe_configurations(pipeline, names)
    except WorkerSetupError as exc:
        return {"valid": False, "error": str(exc)}
    return {"valid": True, "configurations": names, "document": document}


# The local-intensity (peak) features use a 1 cm3 sphere around each ROI voxel.
_LOCAL_INTENSITY_RADIUS_MM = 6.2035


def _wavelet_taps(name: Any) -> int | None:
    match = re.fullmatch(r"(haar)|(?:db|sym)(\d+)|coif(\d+)", str(name))
    if match is None:
        return None
    if match.group(1):
        return 2
    return 2 * int(match.group(2)) if match.group(2) else 6 * int(match.group(3))


def crop_margin_mm(
    configuration_document: Mapping[str, Any], spacing: Sequence[float]
) -> float | None:
    """Return the margin around a ROI that every selected configuration needs.

    The margin holds the voxels that interpolation, filters, and the local-intensity
    features read outside the ROI. Return None when a configuration needs the whole
    image. Sentinel detection (``auto``), FFT filters, periodic boundaries, and
    cubic interpolation's spline prefilter cannot use a finite local margin.
    Only a leading resample is supported by the crop grid-alignment calculation.
    """

    configs = configuration_document.get("configs")
    margin = 0.0
    for config in configs.values() if isinstance(configs, Mapping) else ():
        if config.get("source_mode") == "auto":
            return None
        step_spacing = max(spacing)
        needed = 0.0
        for index, step in enumerate(config.get("steps", [])):
            name, params = step.get("step"), step.get("params") or {}
            if name == "resample":
                if index != 0 or params.get("interpolation", "linear") not in ("linear", "nearest"):
                    return None
                needed += 2 * max(spacing)
                step_spacing = max(params["new_spacing"])
            elif name == "filter":
                if params.get("boundary") == "periodic" or "spacing_mm" in params:
                    # Wrapped image edges and an explicit filter spacing do not
                    # share this crop planner's local physical-coordinate model.
                    return None
                kind = params.get("type")
                if kind == "mean":
                    radius_mm = (int(params.get("support", 15)) // 2) * step_spacing
                elif kind == "log":
                    radius_mm = float(params.get("truncate", 4.0)) * float(params["sigma_mm"])
                elif kind == "gabor":
                    radius_mm = 6.0 * float(params["sigma_mm"])
                elif kind == "laws":
                    codes = re.findall(r"[LESWR](\d)", str(params.get("kernel", "L5E5E5")))
                    energy = int(params.get("energy_distance", 7)) if params.get("compute_energy") else 0
                    radius_mm = (max(int(code) // 2 for code in codes) + energy) * step_spacing
                elif kind == "wavelet" and _wavelet_taps(params.get("wavelet", "db2")):
                    taps = _wavelet_taps(params.get("wavelet", "db2")) or 0
                    radius_mm = taps * 2 ** int(params.get("level", 1)) * step_spacing
                else:
                    return None
                needed += radius_mm + step_spacing
            elif name == "extract_features" and (
                "local_intensity" in params.get("families", [])
                or params.get("include_local_intensity")
            ):
                needed += _LOCAL_INTENSITY_RADIUS_MM + step_spacing
        margin = max(margin, needed)
    return margin


def resample_targets(configuration_document: Mapping[str, Any]) -> list[tuple[float, ...]]:
    """Return the new spacing of every resample step of the selected configurations."""

    configs = configuration_document.get("configs")
    return [
        tuple(float(value) for value in step["params"]["new_spacing"])
        for config in (configs.values() if isinstance(configs, Mapping) else ())
        for step in config.get("steps", [])
        if step.get("step") == "resample"
    ]


def _grid_error(start: int, stop: int, full: int, old: float, new: float) -> float:
    """Distance, in new voxels, of a crop's resampling grid from the whole-axis grid.

    Pictologics centers the new grid on the image, with ceil(size * old / new) points.
    """

    scale = old / new
    offset = (start + (stop - start - 1) / 2 - (full - 1) / 2) * scale + (
        math.ceil(round(full * scale, 9)) - math.ceil(round((stop - start) * scale, 9))
    ) / 2
    return abs(offset - round(offset))


def aligned_range(
    lower: int, upper: int, full: int, old: float, targets: Sequence[float]
) -> tuple[int, int]:
    """Grow [lower, upper) until its resampling grid lies on the whole-axis grid.

    Even a very small grid shift can move a voxel into another intensity bin, so the
    grids must agree to rounding precision. Even a centered crop can have a
    half-voxel shift when the resampled sizes have different parity. Use the whole
    axis when no aligned range adds at most 256 voxels in total to this axis.
    """

    for extra in range(257):
        for below in range(extra + 1):
            start, stop = lower - below, upper + extra - below
            if 0 <= start and stop <= full and all(
                _grid_error(start, stop, full, old, new) < 1e-9 for new in targets
            ):
                return start, stop
    return 0, full


def crop_to_region(
    pictologics: Any,
    image: Any,
    mask: Any,
    margin_mm: float,
    targets: Sequence[Sequence[float]] = (),
) -> tuple[Any, Any, list[list[int]] | None]:
    """Crop the image and mask to the ROI box plus *margin_mm* on each side.

    Along each axis, the box grows until its resampling grid for every spacing in
    *targets* lies on the grid of the whole image, so that the values do not change.
    Return the images unchanged, and no box, when the box covers the whole image.
    """

    import numpy as np

    indices = np.nonzero(mask.array)
    if indices[0].size == 0:
        return image, mask, None
    shape = np.asarray(image.array.shape)
    spacing = np.asarray(image.spacing, dtype=float)
    pad = np.ceil(margin_mm / spacing).astype(int)
    lower = np.maximum(np.min(indices, axis=1) - pad, 0)
    upper = np.minimum(np.max(indices, axis=1) + pad + 1, shape)
    for axis in range(3):
        lower[axis], upper[axis] = aligned_range(
            int(lower[axis]), int(upper[axis]), int(shape[axis]), float(spacing[axis]),
            sorted({float(target[axis]) for target in targets}),
        )
    if np.array_equal(lower, np.zeros(3)) and np.array_equal(upper, shape):
        return image, mask, None
    box = tuple(slice(int(start), int(stop)) for start, stop in zip(lower, upper, strict=True))
    direction = image.direction if image.direction is not None else np.eye(3)
    origin = tuple(
        float(value)
        for value in np.asarray(image.origin)
        + np.asarray(direction, dtype=float).reshape(3, 3) @ (lower * spacing)
    )

    def cropped(source: Any) -> Any:
        source_mask = getattr(source, "source_mask", None)
        return pictologics.Image(
            array=source.array[box].copy(),
            spacing=source.spacing,
            origin=origin,
            direction=source.direction,
            modality=source.modality,
            source_mask=None if source_mask is None else source_mask[box].copy(),
        )

    return cropped(image), cropped(mask), [lower.tolist(), upper.tolist()]


class ProgressReporter:
    """Emit Slicer Execution Model progress at ROI boundaries."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self.stream = stream if stream is not None else sys.stdout

    def _write(self, text: str) -> None:
        self.stream.write(text + "\n")
        self.stream.flush()

    def progress(self, fraction: float) -> None:
        bounded = min(1.0, max(0.0, float(fraction)))
        self._write(f"<filter-progress>{bounded:.6f}</filter-progress>")

    def comment(self, message: str) -> None:
        self._write(f"<filter-comment>{xml_escape(message)}</filter-comment>")

    def roi_started(self, index: int, total: int, roi: ROIManifest) -> None:
        self.progress(index / total)
        self.comment(f"Processing ROI {index + 1} of {total}: {roi.roi_name}")
        # Slicer's Python API exposes progress percentages but not SEM's
        # ProgressMessage. Keep a compact marker in ordinary stdout so the GUI
        # can read exact ROI boundaries without inferring them from rounded %.
        self._write("PICTOLOGICS_ROI " + json.dumps({"index": index, "total": total}))

    def roi_finished(self, index: int, total: int) -> None:
        self.progress((index + 1) / total)


def _copy_processing_log(pipeline: Any) -> list[dict[str, Any]]:
    """Get a defensive processing-log copy across current and future core APIs."""

    for getter_name in ("get_processing_log", "get_processing_logs", "get_log"):
        getter = getattr(pipeline, getter_name, None)
        if callable(getter):
            value = getter()
            break
    else:
        value = getattr(pipeline, "_log", [])
    if value is None:
        return []
    if not isinstance(value, list):
        raise JobExecutionError("Pictologics processing log is not a list")
    return copy.deepcopy(value)


def _processing_statuses(entries: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    statuses: dict[str, str] = {}
    for entry in entries:
        config = entry.get("config_name")
        status = entry.get("status")
        if isinstance(config, str) and isinstance(status, str):
            statuses[config] = status
    return statuses


def _series_to_mapping(series: Any) -> dict[str, Any]:
    if series is None:
        return {}
    if isinstance(series, Mapping):
        return dict(series)
    items = getattr(series, "items", None)
    if callable(items):
        return dict(items())
    raise JobExecutionError(
        f"Pictologics returned unsupported feature result type: {type(series).__name__}"
    )


def _feature_value(value: Any) -> float | None:
    if value is None:
        return None
    item = getattr(value, "item", None)
    if callable(item):
        try:
            value = item()
        except (TypeError, ValueError):
            pass
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return numeric if math.isfinite(numeric) else None


def _fallback_feature_identity(feature_key: str) -> tuple[str, str, str]:
    """Conservative fallback used only if a result is absent from the catalog."""

    match = _PICTOLOGICS_FEATURE_CODE.search(feature_key)
    if match is None:
        return feature_key, "", ""
    ibsi_code = match.group("ibsi_code")
    return (
        feature_key[: match.start()],
        ibsi_code,
        ibsi_code + (match.group("variant") or ""),
    )


def _row_status(config_status: str, *, present: bool, value: float | None) -> str:
    if config_status in {"completed", "ok", "success"}:
        return "ok" if present and value is not None else "not_computed"
    return config_status or "error"


def build_long_rows(
    manifest: JobManifest,
    roi: ROIManifest,
    bundle: PipelineBundle,
    results: Mapping[str, Any],
    processing_log: Sequence[Mapping[str, Any]],
    *,
    pictologics_version: str,
) -> list[dict[str, Any]]:
    """Map results through describe_features() into the fixed long-row schema."""

    statuses = _processing_statuses(processing_log)
    rows: list[dict[str, Any]] = []
    for config_name in bundle.selected_configurations:
        series_present = config_name in results
        values = _series_to_mapping(results.get(config_name)) if series_present else {}
        config_status = statuses.get(
            config_name,
            "completed" if series_present else "error",
        )
        known_keys: set[str] = set()

        for metadata in bundle.catalog_by_config[config_name]:
            feature_key = metadata["feature_key"]
            feature_name = str(metadata.get("feature_name", feature_key))
            ibsi_code = str(metadata.get("ibsi_code", ""))
            known_keys.add(feature_key)
            present = feature_key in values
            value = _feature_value(values.get(feature_key)) if present else None
            row = {
                "run_id": manifest.run_id,
                "timestamp": manifest.timestamp,
                "subject_id": manifest.subject_id,
                "image_name": manifest.image_name,
                "roi_source": roi.roi_source,
                "roi_id": roi.roi_id,
                "roi_name": roi.roi_name,
                "config": config_name,
                "family": str(metadata.get("family", "unknown")),
                "feature_name": feature_name,
                "feature_key": feature_key,
                "ibsi_code": ibsi_code,
                "pictologics_ibsi_code": str(
                    metadata.get(
                        "pictologics_ibsi_code",
                        _pictologics_ibsi_code(
                            feature_key, feature_name, ibsi_code
                        ),
                    )
                ),
                "pictologics_feature_name": str(
                    metadata.get(
                        "pictologics_feature_name",
                        _pictologics_feature_name(config_name, feature_key),
                    )
                ),
                "preprocessing_sequence": str(
                    metadata.get("preprocessing_sequence") or ""
                ),
                "value": value,
                "status": _row_status(config_status, present=present, value=value),
                "pictologics_version": pictologics_version,
                "extension_version": manifest.extension_version,
            }
            rows.append(row)

        # A newer Pictologics release may add a runtime feature before its catalog
        # metadata catches up. Preserve the value and mark the fallback explicitly.
        for feature_key, raw_value in values.items():
            if feature_key in known_keys:
                continue
            feature_key = str(feature_key)
            feature_name, ibsi_code, pictologics_ibsi_code = (
                _fallback_feature_identity(feature_key)
            )
            value = _feature_value(raw_value)
            rows.append(
                {
                    "run_id": manifest.run_id,
                    "timestamp": manifest.timestamp,
                    "subject_id": manifest.subject_id,
                    "image_name": manifest.image_name,
                    "roi_source": roi.roi_source,
                    "roi_id": roi.roi_id,
                    "roi_name": roi.roi_name,
                    "config": config_name,
                    "family": "unknown",
                    "feature_name": feature_name,
                    "feature_key": feature_key,
                    "ibsi_code": ibsi_code,
                    "pictologics_ibsi_code": pictologics_ibsi_code,
                    "pictologics_feature_name": _pictologics_feature_name(
                        config_name, feature_key
                    ),
                    "preprocessing_sequence": "",
                    "value": value,
                    "status": _row_status(config_status, present=True, value=value),
                    "pictologics_version": pictologics_version,
                    "extension_version": manifest.extension_version,
                }
            )

    for row in rows:
        if tuple(row) != LONG_ROW_COLUMNS:
            raise AssertionError("internal long-row column order drift")
        row.update(manifest.result_columns or ())
    return rows


def execute_job(
    manifest: JobManifest,
    pictologics: Any,
    dependency_path: str | Path,
    *,
    progress: ProgressReporter | None = None,
) -> dict[str, Any]:
    """Execute all configurations across all ROIs in one process."""

    reporter = progress if progress is not None else ProgressReporter()
    started_at = _utc_now()
    reporter.progress(0.0)

    bundle = create_pipeline(pictologics, manifest)
    try:
        image = pictologics.load_image(str(manifest.image_path))
    except Exception as exc:
        raise JobExecutionError(
            f"cannot load NIfTI image '{manifest.image_path}': {type(exc).__name__}: {exc}"
        ) from exc

    pictologics_version = str(getattr(pictologics, "__version__", "unknown"))
    crop_margin = (
        crop_margin_mm(bundle.configuration_document, image.spacing)
        if manifest.crop_to_roi
        else None
    )
    rows: list[dict[str, Any]] = []
    processing_logs: list[dict[str, Any]] = []
    roi_errors: list[dict[str, str]] = []
    total = len(manifest.rois)

    for index, roi in enumerate(manifest.rois):
        reporter.roi_started(index, total, roi)
        bundle.pipeline.clear_log()
        crop_box = None
        try:
            mask = (
                None
                if roi.mask_path is None
                else pictologics.load_image(str(roi.mask_path), reference_image=image)
            )
            roi_image = image
            if crop_margin is not None and mask is not None:
                roi_image, mask, crop_box = crop_to_region(
                    pictologics, image, mask, crop_margin,
                    resample_targets(bundle.configuration_document),
                )
            raw_results = bundle.pipeline.run(
                roi_image,
                mask,
                subject_id=manifest.subject_id,
                config_names=list(bundle.selected_configurations),
            )
            if not isinstance(raw_results, Mapping):
                raise JobExecutionError(
                    "RadiomicsPipeline.run() did not return a configuration mapping"
                )
            log_entries = _copy_processing_log(bundle.pipeline)
            roi_rows = build_long_rows(
                manifest,
                roi,
                bundle,
                raw_results,
                log_entries,
                pictologics_version=pictologics_version,
            )
        except Exception as exc:
            # ROI-level loading/execution failures are nonfatal.  Emit the full
            # expected catalog as null values and continue with subsequent ROIs.
            message = f"{type(exc).__name__}: {exc}"
            log_entries = [
                {
                    "timestamp": _utc_now(),
                    "subject_id": manifest.subject_id,
                    "config_name": config_name,
                    "status": "error",
                    "failed_step": "roi",
                    "error": message,
                }
                for config_name in bundle.selected_configurations
            ]
            roi_errors.append(
                {
                    "roi_source": roi.roi_source,
                    "roi_id": roi.roi_id,
                    "roi_name": roi.roi_name,
                    "error": message,
                }
            )
            roi_rows = build_long_rows(
                manifest,
                roi,
                bundle,
                {},
                log_entries,
                pictologics_version=pictologics_version,
            )
        finally:
            reporter.roi_finished(index, total)

        rows.extend(roi_rows)
        processing_logs.append(
            {
                "roi_source": roi.roi_source,
                "roi_id": roi.roi_id,
                "roi_name": roi.roi_name,
                "mask_path": str(roi.mask_path) if roi.mask_path is not None else None,
                "metadata": copy.deepcopy(roi.metadata),
                "crop_box": crop_box,
                "entries": log_entries,
            }
        )

    completed_at = _utc_now()
    payload = {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "run_id": manifest.run_id,
        "rows": rows,
        "provenance": {
            "started_at": started_at,
            "completed_at": completed_at,
            "run_metadata": {
                "timestamp": manifest.timestamp,
                "subject_id": manifest.subject_id,
                "subject_metadata": copy.deepcopy(manifest.subject_metadata),
                "image_name": manifest.image_name,
                "image_path": str(manifest.image_path),
                "extension_version": manifest.extension_version,
                "pictologics_version": pictologics_version,
                "pictologics_requirement": manifest.pictologics_requirement,
            },
            "input_manifest": manifest.to_dict(),
            "dependency_path": str(Path(dependency_path).resolve(strict=False)),
            "numba_cache_path": str(manifest.numba_cache_path),
            "configuration_sha256": manifest.configuration_sha256,
            "crop_margin_mm": crop_margin,
            "effective_configuration": bundle.configuration_document,
            "feature_catalog": list(bundle.catalog_records),
            "processing_logs": processing_logs,
        },
        "errors": roi_errors,
    }
    return cast("dict[str, Any]", _json_safe(payload))


def _json_safe(value: Any) -> Any:
    """Recursively convert package scalars and non-finite floats to strict JSON."""

    if is_dataclass(value) and not isinstance(value, type):
        return _json_safe(asdict(value))
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return _json_safe(item())
        except (TypeError, ValueError):
            pass
    return str(value)


def _fsync_parent_dir(path: Path) -> None:
    """Persist a rename by fsyncing the destination's directory.

    Directory fsync is unsupported on some platforms (notably Windows), so any
    failure to open/sync the directory is ignored.
    """

    try:
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


def atomic_write_json(path: str | Path, payload: Any) -> None:
    """Durably write strict JSON and atomically replace the destination."""

    output_path = Path(path).resolve(strict=False)
    if output_path.suffix.lower() != ".json":
        raise PictologicsCLIError(
            f"JSON output filename must end in .json: {output_path}"
        )
    if output_path.exists() and output_path.is_dir():
        raise PictologicsCLIError(f"JSON output is a directory: {output_path}")
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise PictologicsCLIError(
            f"cannot create output directory '{output_path.parent}': {exc}"
        ) from exc

    fd = -1
    temporary_name: str | None = None
    try:
        fd, temporary_name = tempfile.mkstemp(
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            dir=str(output_path.parent),
        )
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            fd = -1
            json.dump(_json_safe(payload), stream, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, output_path)
        temporary_name = None
        _fsync_parent_dir(output_path)
    except (OSError, TypeError, ValueError) as exc:
        raise PictologicsCLIError(
            f"cannot atomically write JSON output '{output_path}': {exc}"
        ) from exc
    finally:
        if fd >= 0:
            os.close(fd)
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="PictologicsCLI",
        description="Execute one versioned Pictologics Slicer job manifest.",
    )
    parser.add_argument("jobManifest", help="input v1 JSON job manifest")
    parser.add_argument("dependencyPath", help="private pip target directory")
    parser.add_argument("outputResults", help="output JSON result file")
    return parser.parse_args(argv)


def run_cli(
    args: argparse.Namespace,
    *,
    stdout: TextIO | None = None,
) -> None:
    """Run parsed CLI arguments; separated from ``main`` for unit testing."""

    manifest_path = Path(args.jobManifest).resolve(strict=False)
    manifest = load_manifest(manifest_path)
    active_marker = manifest_path.parent / ".worker-active"
    try:
        active_marker.write_text(f"pid={os.getpid()}\n", encoding="utf-8")
    except OSError as exc:
        raise PictologicsCLIError(
            f"cannot create worker activity marker in '{manifest_path.parent}': {exc}"
        ) from exc

    try:
        output_path = Path(args.outputResults).resolve(strict=False)
        if output_path.suffix.lower() != ".json":
            raise PictologicsCLIError("outputResults filename must end in .json")
        if output_path != manifest.results_path:
            raise ManifestValidationError(
                "CLI outputResults does not match manifest output.results_path "
                f"({output_path} != {manifest.results_path})"
            )
        dependency_path = Path(args.dependencyPath).resolve(strict=False)

        configure_environment(manifest)
        isolate_dependency_path(dependency_path)
        pictologics = import_private_pictologics(
            dependency_path, warmup=manifest.warmup
        )
        verify_runtime_version(manifest, pictologics)
        payload = execute_job(
            manifest,
            pictologics,
            dependency_path,
            progress=ProgressReporter(stdout),
        )
        # Write the optional sidecar first. The result payload is the commit marker
        # consumed by the GUI and is replaced only after all other output succeeds.
        if manifest.provenance_path is not None:
            atomic_write_json(
                manifest.provenance_path,
                {
                    "schema_version": OUTPUT_SCHEMA_VERSION,
                    "run_id": manifest.run_id,
                    "provenance": payload["provenance"],
                    "errors": payload["errors"],
                },
            )
        atomic_write_json(manifest.results_path, payload)
    finally:
        try:
            active_marker.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            # Leaving the marker is safe: startup recovery treats it as active for
            # seven days, then removes the abandoned staging directory.
            pass


def run_configuration_check(
    configuration_path: str,
    dependency_path: str,
    *,
    stdout: TextIO | None = None,
) -> None:
    """Print the check of one custom configuration file, for the GUI Validate aid."""

    isolate_dependency_path(dependency_path)
    pictologics = import_private_pictologics(dependency_path, warmup=False)
    result = check_configuration_file(pictologics, Path(configuration_path))
    stream = stdout if stdout is not None else sys.stdout
    stream.write(CONFIGURATION_CHECK_PREFIX + json.dumps(_json_safe(result)) + "\n")
    stream.flush()


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """CLI entry point. Return nonzero and a concise, actionable stderr message."""

    error_stream = stderr if stderr is not None else sys.stderr
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        if arguments[:1] == ["--check-configuration"]:
            configuration_path, dependency_path = arguments[1:]
            run_configuration_check(configuration_path, dependency_path, stdout=stdout)
        else:
            run_cli(parse_arguments(arguments), stdout=stdout)
    except PictologicsCLIError as exc:
        error_stream.write(f"PictologicsCLI error: {exc}\n")
        error_stream.flush()
        return 2
    except Exception as exc:  # pragma: no cover - last-resort diagnostic boundary
        error_stream.write(
            f"PictologicsCLI unexpected error ({type(exc).__name__}): {exc}\n"
        )
        traceback.print_exc(file=error_stream)
        error_stream.flush()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
