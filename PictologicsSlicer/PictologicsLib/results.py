"""Slicer-neutral result rows, payload validation, and file export."""

from __future__ import annotations

import csv
import json
import math
import numbers
import os
import tempfile
from collections import OrderedDict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any, Final

RESULT_PAYLOAD_SCHEMA_VERSION: Final = 1
_RESULT_PAYLOAD_REQUIRED_KEYS: Final = frozenset({"schema_version", "run_id", "rows"})
_RESULT_PAYLOAD_ALLOWED_KEYS: Final = _RESULT_PAYLOAD_REQUIRED_KEYS | {
    "provenance",
    "errors",
}

# This order is the extension's durable table and long-export contract.
#
# NOTE: This schema is deliberately richer than Pictologics' own
# ``format_results()`` output and does not match it column-for-column -- notably
# this uses ``configuration`` where Pictologics uses ``config``, and adds
# provenance columns (run_id, timestamp, roi_*, status, versions). The extension
# owns this layout on purpose so tables carry full provenance. If Pictologics
# later grows a canonical long/wide result schema we intend to reconcile this
# with it (and bump RESULT_PAYLOAD_SCHEMA_VERSION); until then treat the two
# layouts as intentionally distinct.
LONG_RESULT_COLUMNS: Final[tuple[str, ...]] = (
    "run_id",
    "timestamp",
    "subject_id",
    "image_name",
    "roi_source",
    "roi_id",
    "roi_name",
    "configuration",
    "feature_family",
    "feature_name",
    "ibsi_code",
    "value",
    "status",
    "pictologics_version",
    "extension_version",
)

WIDE_ID_COLUMNS: Final[tuple[str, ...]] = (
    "run_id",
    "timestamp",
    "subject_id",
    "image_name",
    "roi_source",
    "roi_id",
    "roi_name",
    "status",
    "pictologics_version",
    "extension_version",
)


class ResultPayloadError(ValueError):
    """Raised when CLI result data violates the interchange contract."""


def _normalise_value(value: object, field: str) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        raise ResultPayloadError(f"{field} must be a real number or null")
    if isinstance(value, numbers.Integral):
        return int(value)
    result = float(value)
    if math.isinf(result):
        raise ResultPayloadError(f"{field} must not be infinite")
    # NaN is the intentional per-feature failure sentinel.  Strict JSON exports map it
    # to null, while in-memory/Slicer table consumers retain IEEE NaN.
    return result


def normalise_result_row(
    row: object,
    *,
    index: int | None = None,
    expected_run_id: str | None = None,
) -> dict[str, Any]:
    """Validate one long-form row and return it in canonical column order."""

    location = f"rows[{index}]" if index is not None else "row"
    if not isinstance(row, Mapping):
        raise ResultPayloadError(f"{location} must be an object")
    missing = [column for column in LONG_RESULT_COLUMNS if column not in row]
    if missing:
        raise ResultPayloadError(
            f"{location} is missing required columns: {', '.join(missing)}"
        )
    unknown = sorted(set(row) - set(LONG_RESULT_COLUMNS), key=str)
    if unknown:
        raise ResultPayloadError(
            f"{location} has unknown columns: {', '.join(str(item) for item in unknown)}"
        )

    normalised: dict[str, Any] = {}
    for column in LONG_RESULT_COLUMNS:
        value = row[column]
        if column == "value":
            normalised[column] = _normalise_value(value, f"{location}.value")
        else:
            if not isinstance(value, str):
                raise ResultPayloadError(f"{location}.{column} must be a string")
            normalised[column] = value

    if not normalised["run_id"]:
        raise ResultPayloadError(f"{location}.run_id must not be empty")
    if not normalised["timestamp"]:
        raise ResultPayloadError(f"{location}.timestamp must not be empty")
    if not normalised["roi_id"]:
        raise ResultPayloadError(f"{location}.roi_id must not be empty")
    if not normalised["configuration"]:
        raise ResultPayloadError(f"{location}.configuration must not be empty")
    if not normalised["feature_name"]:
        raise ResultPayloadError(f"{location}.feature_name must not be empty")
    if not normalised["status"]:
        raise ResultPayloadError(f"{location}.status must not be empty")
    if expected_run_id is not None and normalised["run_id"] != expected_run_id:
        raise ResultPayloadError(
            f"{location}.run_id does not match payload run_id {expected_run_id!r}"
        )
    return normalised


def validate_result_rows(
    rows: object, *, expected_run_id: str | None = None
) -> list[dict[str, Any]]:
    """Validate an iterable of long-form rows."""

    if isinstance(rows, (str, bytes, bytearray, Mapping)) or not isinstance(
        rows, Iterable
    ):
        raise ResultPayloadError("rows must be an iterable of objects")
    return [
        normalise_result_row(row, index=index, expected_run_id=expected_run_id)
        for index, row in enumerate(rows)
    ]


def _strict_json_clone(value: object, field: str) -> Any:
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        return json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ResultPayloadError(
            f"{field} must contain strict JSON values: {exc}"
        ) from exc


def build_result_payload(
    *,
    run_id: str,
    rows: Iterable[Mapping[str, object]],
    provenance: Mapping[str, object] | None = None,
    errors: Sequence[Mapping[str, object]] | None = None,
) -> dict[str, Any]:
    """Build and validate a versioned result payload for the GUI process."""

    payload: dict[str, Any] = {
        "schema_version": RESULT_PAYLOAD_SCHEMA_VERSION,
        "run_id": run_id,
        "rows": list(rows),
    }
    if provenance is not None:
        payload["provenance"] = dict(provenance)
    if errors is not None:
        payload["errors"] = list(errors)
    return validate_result_payload(payload)


def validate_result_payload(payload: object) -> dict[str, Any]:
    """Validate a CLI result payload and return a detached, normalized copy."""

    if not isinstance(payload, Mapping):
        raise ResultPayloadError("result payload must be an object")
    payload_keys = set(payload)
    missing_keys = sorted(_RESULT_PAYLOAD_REQUIRED_KEYS - payload_keys)
    unknown_keys = sorted(payload_keys - _RESULT_PAYLOAD_ALLOWED_KEYS, key=str)
    if missing_keys or unknown_keys:
        details: list[str] = []
        if missing_keys:
            details.append(f"missing keys: {', '.join(missing_keys)}")
        if unknown_keys:
            details.append(
                f"unknown keys: {', '.join(str(key) for key in unknown_keys)}"
            )
        raise ResultPayloadError(
            f"result payload has an invalid shape ({'; '.join(details)})"
        )
    version = payload.get("schema_version")
    if isinstance(version, bool) or version != RESULT_PAYLOAD_SCHEMA_VERSION:
        raise ResultPayloadError(
            f"Unsupported schema_version {version!r}; expected {RESULT_PAYLOAD_SCHEMA_VERSION}"
        )
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ResultPayloadError("run_id must be a non-empty string")

    normalised: dict[str, Any] = {
        "schema_version": RESULT_PAYLOAD_SCHEMA_VERSION,
        "run_id": run_id,
        "rows": validate_result_rows(payload.get("rows"), expected_run_id=run_id),
    }
    if "provenance" in payload:
        if not isinstance(payload["provenance"], Mapping):
            raise ResultPayloadError("provenance must be an object")
        normalised["provenance"] = _strict_json_clone(
            dict(payload["provenance"]), "provenance"
        )
    if "errors" in payload:
        errors = payload["errors"]
        if isinstance(errors, (str, bytes, bytearray)) or not isinstance(
            errors, Sequence
        ):
            raise ResultPayloadError("errors must be an array of objects")
        detached_errors: list[dict[str, Any]] = []
        for index, error in enumerate(errors):
            if not isinstance(error, Mapping):
                raise ResultPayloadError(f"errors[{index}] must be an object")
            detached_errors.append(_strict_json_clone(dict(error), f"errors[{index}]"))
        normalised["errors"] = detached_errors
    return normalised


def _json_safe(value: object) -> Any:
    if isinstance(value, float):
        return None if not math.isfinite(value) else value
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def rows_to_wide(rows: Iterable[Mapping[str, object]]) -> list[dict[str, Any]]:
    """Pivot long rows to one row per run/ROI with configuration-feature columns."""

    long_rows = validate_result_rows(rows)
    identity_columns = tuple(column for column in WIDE_ID_COLUMNS if column != "status")
    grouped: OrderedDict[tuple[str, ...], dict[str, Any]] = OrderedDict()
    statuses: dict[tuple[str, ...], list[str]] = {}

    for row in long_rows:
        key = tuple(str(row[column]) for column in identity_columns)
        if key not in grouped:
            grouped[key] = {column: row[column] for column in identity_columns}
            statuses[key] = []
        if row["status"] not in statuses[key]:
            statuses[key].append(row["status"])

        feature_column = f"{row['configuration']}__{row['feature_name']}"
        if feature_column in grouped[key]:
            raise ResultPayloadError(
                "Wide export collision for "
                f"ROI {row['roi_id']!r} and feature {feature_column!r}"
            )
        grouped[key][feature_column] = row["value"]

    result: list[dict[str, Any]] = []
    for key, row in grouped.items():
        ordered: dict[str, Any] = {}
        for column in WIDE_ID_COLUMNS:
            ordered[column] = (
                ";".join(statuses[key]) if column == "status" else row[column]
            )
        ordered.update(
            (column, value)
            for column, value in row.items()
            if column not in identity_columns
        )
        result.append(ordered)
    return result


def _fsync_parent_dir(path: Path) -> None:
    """Persist a rename by fsyncing the destination's directory.

    Directory fsync is a no-op or unsupported on some platforms (notably Windows),
    so any failure to open/sync the directory is ignored.
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


def _atomic_text_path(
    destination: Path,
) -> tuple[tempfile._TemporaryFileWrapper[str], Path]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    stream = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
        delete=False,
    )
    return stream, Path(stream.name)


def export_rows_csv(
    rows: Iterable[Mapping[str, object]],
    path: str | os.PathLike[str],
    *,
    wide: bool = False,
) -> Path:
    """Atomically export validated rows as UTF-8 CSV."""

    exported_rows = rows_to_wide(rows) if wide else validate_result_rows(rows)
    if wide:
        feature_columns = sorted(
            {
                column
                for row in exported_rows
                for column in row
                if column not in WIDE_ID_COLUMNS
            }
        )
        columns: Sequence[str] = (*WIDE_ID_COLUMNS, *feature_columns)
    else:
        columns = LONG_RESULT_COLUMNS

    destination = Path(path).expanduser().resolve(strict=False)
    stream, temporary = _atomic_text_path(destination)
    try:
        with stream:
            writer = csv.DictWriter(
                stream,
                fieldnames=columns,
                extrasaction="ignore",
                lineterminator="\n",
            )
            writer.writeheader()
            # Map non-finite floats (NaN failure sentinel) to empty cells so CSV and
            # JSON agree: JSON emits null, CSV emits an empty field rather than "nan".
            writer.writerows(_json_safe(exported_rows))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        _fsync_parent_dir(destination)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return destination


def export_rows_json(
    rows: Iterable[Mapping[str, object]],
    path: str | os.PathLike[str],
    *,
    wide: bool = False,
) -> Path:
    """Atomically export rows as strict UTF-8 JSON (NaN becomes ``null``)."""

    exported_rows = rows_to_wide(rows) if wide else validate_result_rows(rows)
    destination = Path(path).expanduser().resolve(strict=False)
    stream, temporary = _atomic_text_path(destination)
    try:
        with stream:
            json.dump(
                _json_safe(exported_rows),
                stream,
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        _fsync_parent_dir(destination)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return destination


def export_rows(
    rows: Iterable[Mapping[str, object]],
    path: str | os.PathLike[str],
    *,
    format: str | None = None,
    wide: bool = False,
) -> Path:
    """Export rows as CSV or JSON, inferred from *path* unless specified."""

    destination = Path(path)
    selected_format = (format or destination.suffix.removeprefix(".")).lower()
    if selected_format == "csv":
        return export_rows_csv(rows, destination, wide=wide)
    if selected_format == "json":
        return export_rows_json(rows, destination, wide=wide)
    raise ValueError("Result export format must be 'csv' or 'json'")


def write_result_payload(path: str | os.PathLike[str], payload: object) -> Path:
    """Atomically write a validated CLI payload as strict JSON."""

    normalised = validate_result_payload(payload)
    destination = Path(path).expanduser().resolve(strict=False)
    stream, temporary = _atomic_text_path(destination)
    try:
        with stream:
            json.dump(
                _json_safe(normalised),
                stream,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                indent=2,
            )
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        _fsync_parent_dir(destination)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
    return destination


def load_result_payload(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Read and validate a CLI result payload from disk."""

    source = Path(path)
    try:
        with source.open("r", encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, json.JSONDecodeError) as exc:
        raise ResultPayloadError(
            f"Unable to read result payload {source}: {exc}"
        ) from exc
    return validate_result_payload(payload)
