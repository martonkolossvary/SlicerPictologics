"""Portable batch-report records used by the Slicer widget.

The report is deliberately independent of feature-table persistence.  A report
can therefore describe a failed, skipped, or cancelled case even when it did not
produce a feature row.  The GUI stores the document in a hidden MRML table node
so it follows normal scene save/load semantics.
"""

from __future__ import annotations

import csv
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

REPORT_SCHEMA_VERSION = "1"
REPORT_ATTRIBUTE = "Pictologics.BatchReportSchemaVersion"
REPORT_METADATA_ATTRIBUTE = "Pictologics.BatchReportMetadataJSON"
REPORT_COLUMNS = (
    "case_name",
    "status",
    "elapsed_seconds",
    "roi_count",
    "row_count",
    "run_id",
    "result_table",
    "reason",
)
REPORT_STATUSES = frozenset(
    {"not_started", "running", "completed", "partial", "failed", "cancelled", "skipped", "interrupted"}
)


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _nonnegative_number(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Report field {field!r} is not numeric.") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"Report field {field!r} must be finite and non-negative.")
    return number


def new_report(cases: Iterable[str], skipped: Iterable[tuple[str, str]] = ()) -> dict[str, Any]:
    """Create a report document with deterministic case order."""

    rows = [
        {
            "case_name": name,
            "status": "not_started",
            "elapsed_seconds": 0.0,
            "roi_count": 0,
            "row_count": 0,
            "run_id": "",
            "result_table": "",
            "reason": "",
        }
        for name in cases
    ]
    rows.extend(
        {
            "case_name": name,
            "status": "skipped",
            "elapsed_seconds": 0.0,
            "roi_count": 0,
            "row_count": 0,
            "run_id": "",
            "result_table": "",
            "reason": _clean_text(reason),
        }
        for name, reason in skipped
    )
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "batch_id": "",
        "started_at": "",
        "finished_at": "",
        "state": "running",
        "rows": rows,
    }


def validate_report(document: Any) -> dict[str, Any]:
    """Validate and normalize a report loaded from MRML or an export."""

    if not isinstance(document, dict) or str(document.get("schema_version", "")) != REPORT_SCHEMA_VERSION:
        raise ValueError("Unsupported or missing batch-report schema version.")
    state = _clean_text(document.get("state"))
    if state not in {"running", "finished", "stopped", "interrupted"}:
        raise ValueError("Invalid batch-report state.")
    raw_rows = document.get("rows")
    if not isinstance(raw_rows, list):
        raise ValueError("Batch report rows are missing.")
    rows: list[dict[str, Any]] = []
    names: set[str] = set()
    for raw in raw_rows:
        if not isinstance(raw, dict):
            raise ValueError("Batch report contains a non-object row.")
        name = raw.get("case_name")
        status = _clean_text(raw.get("status"))
        if not isinstance(name, str) or not name.strip() or name in names or status not in REPORT_STATUSES:
            raise ValueError("Batch report contains an invalid case row.")
        names.add(name)
        elapsed = _nonnegative_number(raw.get("elapsed_seconds", 0), "elapsed_seconds")
        roi_count = _nonnegative_number(raw.get("roi_count", 0), "roi_count")
        row_count = _nonnegative_number(raw.get("row_count", 0), "row_count")
        if not roi_count.is_integer() or not row_count.is_integer():
            raise ValueError("Batch report counts must be whole numbers.")
        rows.append(
            {
                "case_name": name,
                "status": status,
                "elapsed_seconds": elapsed,
                "roi_count": int(roi_count),
                "row_count": int(row_count),
                "run_id": _clean_text(raw.get("run_id")),
                "result_table": _clean_text(raw.get("result_table")),
                "reason": _clean_text(raw.get("reason")),
            }
        )
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "batch_id": _clean_text(document.get("batch_id")),
        "started_at": _clean_text(document.get("started_at")),
        "finished_at": _clean_text(document.get("finished_at")),
        "state": state,
        "rows": rows,
    }


def export_report(document: dict[str, Any], path: Path) -> Path:
    """Atomically write a validated report as JSON or CSV."""

    normalized = validate_report(document)
    destination = path.expanduser().resolve(strict=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    suffix = destination.suffix.lower()
    if suffix not in {".json", ".csv"}:
        raise ValueError("Batch reports can be exported as .json or .csv.")
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="", dir=destination.parent,
            prefix=f".{destination.name}.", suffix=".tmp", delete=False
        ) as handle:
            temporary_name = handle.name
            if suffix == ".json":
                json.dump(normalized, handle, indent=2, sort_keys=True)
                handle.write("\n")
            else:
                writer = csv.DictWriter(handle, fieldnames=REPORT_COLUMNS, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(normalized["rows"])
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, destination)
    except Exception:
        if temporary_name:
            try:
                Path(temporary_name).unlink()
            except OSError:
                pass
        raise
    return destination
