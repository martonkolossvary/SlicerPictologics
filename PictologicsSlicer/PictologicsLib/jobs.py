"""Versioned, JSON-only job manifests shared by the GUI and scripted CLI."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, cast

JOB_MANIFEST_SCHEMA_VERSION: Final = 1
WHOLE_VOLUME_ROI_ID: Final = "whole-volume"
_NIFTI_SUFFIXES: Final = (".nii", ".nii.gz")
_CONFIGURATION_SUFFIXES: Final = (".json", ".yaml", ".yml")

_MANIFEST_REQUIRED_KEYS: Final = frozenset(
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
_MANIFEST_ALLOWED_KEYS: Final = _MANIFEST_REQUIRED_KEYS | {"subject_metadata"}
_IMAGE_KEYS: Final = frozenset({"path", "name"})
_ROI_REQUIRED_KEYS: Final = frozenset({"roi_id", "roi_name", "roi_source", "mask_path"})
_ROI_ALLOWED_KEYS: Final = _ROI_REQUIRED_KEYS | {"metadata"}
_CONFIGURATION_REQUIRED_KEYS: Final = frozenset(
    {"standard_configurations", "custom_configuration_path", "warmup"}
)
_CONFIGURATION_ALLOWED_KEYS: Final = _CONFIGURATION_REQUIRED_KEYS | {
    "custom_configuration_sha256"
}
_OUTPUT_REQUIRED_KEYS: Final = frozenset({"results_path"})
_OUTPUT_ALLOWED_KEYS: Final = _OUTPUT_REQUIRED_KEYS | {"provenance_path"}
_METADATA_REQUIRED_KEYS: Final = frozenset({"numba_cache_path"})
_METADATA_ALLOWED_KEYS: Final = _METADATA_REQUIRED_KEYS | {
    "pictologics_version_at_submission",
    "input_volume_node_id",
}


class JobManifestError(ValueError):
    """Raised when a job manifest does not conform to the supported schema."""


def _non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise JobManifestError(f"{field} must be a non-empty string")
    return value


def _optional_string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise JobManifestError(f"{field} must be a string")
    return value


def _path_text(value: str | os.PathLike[str], field: str) -> str:
    if isinstance(value, str) and not value.strip():
        raise JobManifestError(f"{field} must be a non-empty local path")
    try:
        path = Path(value).expanduser().resolve(strict=False)
    except (TypeError, ValueError, OSError) as exc:
        raise JobManifestError(f"{field} is not a valid local path") from exc
    return str(path)


def _has_suffix(value: str, suffixes: tuple[str, ...]) -> bool:
    return value.lower().endswith(suffixes)


def _json_clone(value: object, field: str) -> Any:
    """Return a JSON-native deep copy while rejecting NaN and custom objects."""

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
        raise JobManifestError(
            f"{field} must contain only finite JSON values: {exc}"
        ) from exc


def _canonical_json_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise JobManifestError(f"Value is not canonical JSON: {exc}") from exc


def sha256_payload(payload: object) -> str:
    """Return the SHA-256 of a JSON value using a stable canonical encoding."""

    return hashlib.sha256(_canonical_json_bytes(payload)).hexdigest()


def sha256_file(path: str | os.PathLike[str], chunk_size: int = 1024 * 1024) -> str:
    """Return a file's hexadecimal SHA-256 digest without loading it all at once."""

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _normalise_roi(roi: Mapping[str, object], index: int) -> dict[str, Any]:
    prefix = f"rois[{index}]"
    roi_id = roi.get("roi_id", roi.get("id"))
    roi_name = roi.get("roi_name", roi.get("name", roi_id))
    roi_source = roi.get("roi_source", roi.get("source", "segmentation"))
    mask_path = roi.get("mask_path", roi.get("path"))

    normalised: dict[str, Any] = {
        "roi_id": _non_empty_string(roi_id, f"{prefix}.roi_id"),
        "roi_name": _non_empty_string(roi_name, f"{prefix}.roi_name"),
        "roi_source": _non_empty_string(roi_source, f"{prefix}.roi_source"),
        "mask_path": None,
    }
    if mask_path is not None:
        if not isinstance(mask_path, (str, os.PathLike)):
            raise JobManifestError(f"{prefix}.mask_path must be a local path or null")
        normalised["mask_path"] = _path_text(mask_path, f"{prefix}.mask_path")

    if "metadata" in roi:
        metadata = roi["metadata"]
        if not isinstance(metadata, Mapping):
            raise JobManifestError(f"{prefix}.metadata must be an object")
        normalised["metadata"] = _json_clone(dict(metadata), f"{prefix}.metadata")
    return normalised


def _utc_timestamp() -> str:
    return (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


def _shape_error(
    field: str,
    actual: set[str],
    *,
    required: frozenset[str],
    allowed: frozenset[str],
) -> JobManifestError:
    missing = sorted(required - actual)
    unknown = sorted(actual - allowed)
    details: list[str] = []
    if missing:
        details.append(f"missing keys: {', '.join(missing)}")
    if unknown:
        details.append(f"unknown keys: {', '.join(unknown)}")
    return JobManifestError(f"{field} has an invalid shape ({'; '.join(details)})")


def _validate_object_shape(
    value: Mapping[str, object],
    field: str,
    *,
    required: frozenset[str],
    allowed: frozenset[str],
) -> None:
    actual = set(value)
    if not required.issubset(actual) or not actual.issubset(allowed):
        raise _shape_error(field, actual, required=required, allowed=allowed)


def _validate_lower_sha256(value: object, field: str) -> str:
    digest = _non_empty_string(value, field)
    if len(digest) != 64 or any(
        character not in "0123456789abcdef" for character in digest
    ):
        raise JobManifestError(f"{field} must be a lowercase SHA-256 digest")
    return digest


def _validate_configuration_document(value: object) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise JobManifestError("configuration_document must be an object")
    _validate_object_shape(
        value,
        "configuration_document",
        required=_CONFIGURATION_REQUIRED_KEYS,
        allowed=_CONFIGURATION_ALLOWED_KEYS,
    )

    standard = value["standard_configurations"]
    if not isinstance(standard, list):
        raise JobManifestError(
            "configuration_document.standard_configurations must be an array"
        )
    seen: set[str] = set()
    for index, item in enumerate(standard):
        name = _non_empty_string(
            item, f"configuration_document.standard_configurations[{index}]"
        )
        if not name.startswith("standard_"):
            raise JobManifestError(
                "configuration_document.standard_configurations entries must start "
                "with 'standard_'"
            )
        if name in seen:
            raise JobManifestError(f"Duplicate standard configuration: {name!r}")
        seen.add(name)

    custom_path = value["custom_configuration_path"]
    if custom_path is not None and (
        not isinstance(custom_path, str) or not custom_path.strip()
    ):
        raise JobManifestError(
            "configuration_document.custom_configuration_path must be a string or null"
        )
    if custom_path is not None and not _has_suffix(
        custom_path, _CONFIGURATION_SUFFIXES
    ):
        raise JobManifestError(
            "configuration_document.custom_configuration_path must end in "
            ".json, .yaml, or .yml"
        )
    if not standard and custom_path is None:
        raise JobManifestError(
            "configuration_document must select a standard or custom configuration"
        )
    if type(value["warmup"]) is not bool:
        raise JobManifestError("configuration_document.warmup must be a boolean")

    custom_hash = value.get("custom_configuration_sha256")
    if custom_hash is not None:
        _validate_lower_sha256(
            custom_hash, "configuration_document.custom_configuration_sha256"
        )
        if custom_path is None:
            raise JobManifestError(
                "configuration_document.custom_configuration_sha256 requires "
                "custom_configuration_path"
            )
    return value


def build_job_manifest(
    *,
    image_path: str | os.PathLike[str],
    rois: Sequence[Mapping[str, object]],
    configuration_document: Mapping[str, object],
    metadata: Mapping[str, object],
    results_path: str | os.PathLike[str] | None = None,
    output_path: str | os.PathLike[str] | None = None,
    provenance_path: str | os.PathLike[str] | None = None,
    whole_volume: bool = False,
    subject_id: str = "",
    subject_metadata: Mapping[str, object] | None = None,
    image_name: str | None = None,
    run_id: str | None = None,
    timestamp: str | None = None,
    extension_version: str = "",
    pictologics_requirement: str = "",
) -> dict[str, Any]:
    """Build and validate a version-1 CLI job manifest.

    ``output_path`` is retained as a convenient alias for ``results_path``.  A
    whole-volume job is represented by one explicit ROI with a null mask so downstream
    result handling does not need a special zero-ROI case.
    """

    if results_path is not None and output_path is not None:
        if _path_text(results_path, "results_path") != _path_text(
            output_path, "output_path"
        ):
            raise JobManifestError(
                "results_path and output_path refer to different paths"
            )
    selected_results_path = results_path if results_path is not None else output_path
    if selected_results_path is None:
        raise JobManifestError("results_path is required")

    if isinstance(rois, (str, bytes, bytearray)) or not isinstance(rois, Sequence):
        raise JobManifestError("rois must be a sequence of objects")
    if whole_volume and rois:
        raise JobManifestError("whole_volume cannot be combined with masked ROIs")

    if whole_volume:
        normalised_rois = [
            {
                "roi_id": WHOLE_VOLUME_ROI_ID,
                "roi_name": "Whole volume",
                "roi_source": WHOLE_VOLUME_ROI_ID,
                "mask_path": None,
            }
        ]
    else:
        normalised_rois = []
        for index, roi in enumerate(rois):
            if not isinstance(roi, Mapping):
                raise JobManifestError(f"rois[{index}] must be an object")
            normalised_rois.append(_normalise_roi(roi, index))

    if not isinstance(configuration_document, Mapping):
        raise JobManifestError("configuration_document must be an object")
    configuration_input = dict(configuration_document)
    raw_custom_path = configuration_input.get("custom_configuration_path")
    if isinstance(raw_custom_path, os.PathLike):
        configuration_input["custom_configuration_path"] = _path_text(
            raw_custom_path, "configuration_document.custom_configuration_path"
        )
    configuration = _json_clone(configuration_input, "configuration_document")
    configuration = _validate_configuration_document(configuration)

    if not isinstance(metadata, Mapping):
        raise JobManifestError("metadata must be an object")
    metadata_input = dict(metadata)
    if "numba_cache_path" not in metadata_input:
        raise JobManifestError("metadata.numba_cache_path is required")
    raw_numba_cache_path = metadata_input["numba_cache_path"]
    if not isinstance(raw_numba_cache_path, (str, os.PathLike)):
        raise JobManifestError("metadata.numba_cache_path must be a local path")
    metadata_input["numba_cache_path"] = _path_text(
        raw_numba_cache_path, "metadata.numba_cache_path"
    )
    normalised_metadata = _json_clone(metadata_input, "metadata")
    if not isinstance(normalised_metadata, dict):  # pragma: no cover - JSON invariant
        raise JobManifestError("metadata must be an object")

    normalised_image_path = _path_text(image_path, "image_path")
    image = Path(normalised_image_path)
    manifest: dict[str, Any] = {
        "schema_version": JOB_MANIFEST_SCHEMA_VERSION,
        "run_id": str(uuid.uuid4()) if run_id is None else run_id,
        "timestamp": _utc_timestamp() if timestamp is None else timestamp,
        "subject_id": subject_id,
        "image": {
            "path": str(image),
            "name": image_name if image_name is not None else image.name,
        },
        "rois": normalised_rois,
        "configuration_document": configuration,
        "configuration_sha256": sha256_payload(configuration),
        "output": {
            "results_path": _path_text(selected_results_path, "results_path"),
        },
        "extension_version": extension_version,
        "pictologics_requirement": pictologics_requirement,
        "metadata": normalised_metadata,
    }
    if provenance_path is not None:
        manifest["output"]["provenance_path"] = _path_text(
            provenance_path, "provenance_path"
        )
    if subject_metadata is not None:
        if not isinstance(subject_metadata, Mapping):
            raise JobManifestError("subject_metadata must be an object")
        manifest["subject_metadata"] = _json_clone(
            dict(subject_metadata), "subject_metadata"
        )
    return validate_job_manifest(manifest)


def _validate_timestamp(value: object) -> str:
    timestamp = _non_empty_string(value, "timestamp")
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise JobManifestError("timestamp must be ISO 8601") from exc
    if parsed.tzinfo is None:
        raise JobManifestError("timestamp must include a timezone")
    if "T" not in timestamp:
        raise JobManifestError("timestamp must be an ISO 8601 date-time")
    return timestamp


def validate_job_manifest(payload: object) -> dict[str, Any]:
    """Validate a manifest and return a detached JSON-native copy."""

    if not isinstance(payload, Mapping):
        raise JobManifestError("job manifest must be an object")
    manifest = cast(dict[str, Any], _json_clone(dict(payload), "job manifest"))

    _validate_object_shape(
        manifest,
        "job manifest",
        required=_MANIFEST_REQUIRED_KEYS,
        allowed=_MANIFEST_ALLOWED_KEYS,
    )

    version = manifest.get("schema_version")
    if isinstance(version, bool) or version != JOB_MANIFEST_SCHEMA_VERSION:
        raise JobManifestError(
            f"Unsupported schema_version {version!r}; expected {JOB_MANIFEST_SCHEMA_VERSION}"
        )
    _non_empty_string(manifest.get("run_id"), "run_id")
    _validate_timestamp(manifest.get("timestamp"))
    _optional_string(manifest.get("subject_id"), "subject_id")
    _optional_string(manifest.get("extension_version"), "extension_version")
    _optional_string(manifest.get("pictologics_requirement"), "pictologics_requirement")

    image = manifest.get("image")
    if not isinstance(image, dict):
        raise JobManifestError("image must be an object")
    _validate_object_shape(image, "image", required=_IMAGE_KEYS, allowed=_IMAGE_KEYS)
    image_path = _non_empty_string(image.get("path"), "image.path")
    if not _has_suffix(image_path, _NIFTI_SUFFIXES):
        raise JobManifestError("image.path must end in .nii or .nii.gz")
    _non_empty_string(image.get("name"), "image.name")

    rois = manifest.get("rois")
    if not isinstance(rois, list) or not rois:
        raise JobManifestError("rois must contain at least one ROI")
    seen_ids: set[str] = set()
    for index, roi in enumerate(rois):
        prefix = f"rois[{index}]"
        if not isinstance(roi, dict):
            raise JobManifestError(f"{prefix} must be an object")
        _validate_object_shape(
            roi,
            prefix,
            required=_ROI_REQUIRED_KEYS,
            allowed=_ROI_ALLOWED_KEYS,
        )
        roi_id = _non_empty_string(roi.get("roi_id"), f"{prefix}.roi_id")
        _non_empty_string(roi.get("roi_name"), f"{prefix}.roi_name")
        source = _non_empty_string(roi.get("roi_source"), f"{prefix}.roi_source")
        if roi_id in seen_ids:
            raise JobManifestError(f"Duplicate ROI id: {roi_id!r}")
        seen_ids.add(roi_id)
        mask_path = roi.get("mask_path")
        is_whole_volume = source == WHOLE_VOLUME_ROI_ID
        if is_whole_volume:
            if mask_path is not None:
                raise JobManifestError(
                    f"{prefix}.mask_path must be null for whole volume"
                )
        elif not isinstance(mask_path, str) or not mask_path:
            raise JobManifestError(f"{prefix}.mask_path is required for a masked ROI")
        elif not _has_suffix(mask_path, _NIFTI_SUFFIXES):
            raise JobManifestError(f"{prefix}.mask_path must end in .nii or .nii.gz")
        if "metadata" in roi and not isinstance(roi["metadata"], dict):
            raise JobManifestError(f"{prefix}.metadata must be an object")

    configuration = _validate_configuration_document(
        manifest.get("configuration_document")
    )
    configuration_hash = _validate_lower_sha256(
        manifest.get("configuration_sha256"), "configuration_sha256"
    )
    if configuration_hash != sha256_payload(configuration):
        raise JobManifestError(
            "configuration_sha256 does not match configuration_document"
        )

    output = manifest.get("output")
    if not isinstance(output, dict):
        raise JobManifestError("output must be an object")
    _validate_object_shape(
        output,
        "output",
        required=_OUTPUT_REQUIRED_KEYS,
        allowed=_OUTPUT_ALLOWED_KEYS,
    )
    results_path = _non_empty_string(output.get("results_path"), "output.results_path")
    if not results_path.lower().endswith(".json"):
        raise JobManifestError("output.results_path must end in .json")
    if "provenance_path" in output:
        provenance_path = _non_empty_string(
            output["provenance_path"], "output.provenance_path"
        )
        if not provenance_path.lower().endswith(".json"):
            raise JobManifestError("output.provenance_path must end in .json")
        if Path(provenance_path).resolve(strict=False) == Path(results_path).resolve(
            strict=False
        ):
            raise JobManifestError(
                "output.provenance_path must differ from output.results_path"
            )

    metadata = manifest.get("metadata")
    if not isinstance(metadata, dict):
        raise JobManifestError("metadata must be an object")
    _validate_object_shape(
        metadata,
        "metadata",
        required=_METADATA_REQUIRED_KEYS,
        allowed=_METADATA_ALLOWED_KEYS,
    )
    _non_empty_string(metadata.get("numba_cache_path"), "metadata.numba_cache_path")
    if "pictologics_version_at_submission" in metadata:
        version_at_submission = metadata["pictologics_version_at_submission"]
        if version_at_submission is not None:
            _optional_string(
                version_at_submission, "metadata.pictologics_version_at_submission"
            )
    if "input_volume_node_id" in metadata:
        _optional_string(
            metadata["input_volume_node_id"], "metadata.input_volume_node_id"
        )
    if "subject_metadata" in manifest and not isinstance(
        manifest["subject_metadata"], dict
    ):
        raise JobManifestError("subject_metadata must be an object")
    return manifest


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


def write_job_manifest(path: str | os.PathLike[str], payload: object) -> Path:
    """Atomically write a validated manifest as strict UTF-8 JSON."""

    manifest = validate_job_manifest(payload)
    destination = Path(path).expanduser().resolve(strict=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_name = stream.name
            json.dump(
                manifest,
                stream,
                ensure_ascii=False,
                sort_keys=True,
                indent=2,
                allow_nan=False,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, destination)
        temporary_name = None
        _fsync_parent_dir(destination)
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink(missing_ok=True)
            except OSError:
                pass
    return destination


def load_job_manifest(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Read and validate a manifest from disk."""

    source = Path(path)
    try:
        with source.open("r", encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise JobManifestError(f"Unable to read job manifest {source}: {exc}") from exc
    return validate_job_manifest(payload)
