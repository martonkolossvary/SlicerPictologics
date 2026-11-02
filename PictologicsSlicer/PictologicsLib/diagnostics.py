"""Allowlisted support summaries; never serialize scene data, logs, or exceptions.

Callers supply individual technical facts, not a scene/provenance/log dictionary.
Unknown strings are replaced rather than heuristically redacted. Reports are
ephemeral: this module does not read files, contact services, or write anything.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any

_VERSION = re.compile(r"[0-9]{1,4}(?:\.[0-9]{1,4}){1,3}(?:(?:a|b|rc|\.dev)[0-9]{1,4})?")
_REVISION = re.compile(r"[0-9a-f]{7,40}")
HEALTH_STATES = frozenset({"compatible", "missing", "incompatible", "ambiguous", "inspection_failed"})
RUN_STATES = frozenset({"not_started", "starting", "running", "completed", "partial", "failed", "cancelled", "discarded"})
RECOVERY = {
    "none": "No failure associated with the last recorded operation.",
    "dependency_install_failed": "Check network access and free disk space, then retry Install / update. A failed candidate does not replace the active environment.",
    "run_start_failed": "Check package status, input geometry, configuration and available disk space; then retry. Previous results are retained.",
    "worker_failed": "Check configuration and memory availability, then retry with fewer ROIs or coarser settings. Previous results are retained.",
    "result_rejected": "Keep the previous table and retry with an unchanged output selection. Invalid or incomplete worker output is not committed.",
    "partial_results": "Review failed rows and ROI errors locally in Browse results and provenance before using or exporting these results.",
    "export_failed": "Keep the result table open. Check output-folder permissions and free disk space, then retry; JSON stores results and provenance together.",
}


def _choice(value: object, allowed: set[str] | frozenset[str], default: str) -> str:
    return value if isinstance(value, str) and value in allowed else default


def _version(value: object) -> str:
    return value if isinstance(value, str) and _VERSION.fullmatch(value) else "unknown"


def _count(value: object) -> int | None:
    # Reject booleans, floats (including non-finite ones), strings and huge values.
    return value if type(value) is int and 0 <= value <= 1_000_000_000 else None


def build_diagnostics(
    *,
    runtime: Mapping[str, object],
    dependency: Mapping[str, object],
    operation: Mapping[str, object],
    run: Mapping[str, object],
) -> dict[str, Any]:
    """Return only enumerated states, validated versions, and bounded counts."""

    revision = runtime.get("slicer_revision")
    code = _choice(operation.get("failure_code"), set(RECOVERY), "none")
    return {
        "diagnostics_schema": 1,
        "scope": "Current module session only; dependency metadata check, not an import/API/JIT test.",
        "privacy": "No images, patient/ROI/configuration names, paths, DICOM metadata, environment variables, raw logs or exception text. Nothing is uploaded automatically.",
        "runtime": {
            **{key: _version(runtime.get(key)) for key in (
                "extension_version", "slicer_version", "python_version", "qt_version",
            )},
            "slicer_revision": revision if isinstance(revision, str) and _REVISION.fullmatch(revision) else "unknown",
            "os": _choice(runtime.get("os"), {"Darwin", "Linux", "Windows"}, "unknown"),
            "process_architecture": _choice(runtime.get("process_architecture"), {"x86_64", "AMD64", "arm64", "aarch64", "i386", "i686"}, "unknown"),
        },
        "dependency": {
            "adopted_version": _version(dependency.get("adopted_version")),
            "installed_version": _version(dependency.get("installed_version")),
            "metadata_status": _choice(dependency.get("metadata_status"), HEALTH_STATES, "inspection_failed"),
        },
        "last_operation": {
            "kind": _choice(operation.get("kind"), {"none", "dependency_update", "run", "export"}, "none"),
            "outcome": _choice(operation.get("outcome"), {"none", "in_progress", "completed", "partial", "failed", "cancelled", "discarded"}, "none"),
            "failure_code": code,
            "recovery": RECOVERY[code],
        },
        "last_run": {
            "state": _choice(run.get("state"), RUN_STATES, "not_started"),
            **{key: _count(run.get(key)) for key in ("roi_count", "feature_rows", "elapsed_seconds")},
        },
    }


def diagnostics_text(**sections: Mapping[str, object]) -> str:
    """Stable, plain-text JSON suitable for a read-only preview and clipboard."""

    return json.dumps(build_diagnostics(**sections), indent=2, ensure_ascii=True, allow_nan=False)
