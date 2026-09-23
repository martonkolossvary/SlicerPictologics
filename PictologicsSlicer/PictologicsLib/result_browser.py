"""Read-only filtering and human-readable, per-run result details."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

SEARCH_COLUMNS = (
    "feature_name",
    "feature_key",
    "ibsi_code",
    "pictologics_ibsi_code",
    "pictologics_feature_name",
    "preprocessing_sequence",
)


def roi_identity(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return str(row.get("run_id", "")), str(row.get("roi_source", "")), str(row.get("roi_id", ""))


def filter_result_indices(
    rows: Sequence[Mapping[str, Any]],
    *,
    query: str = "",
    roi: tuple[str, str, str] | None = None,
    configuration: str = "",
    family: str = "",
    status: str = "",
) -> list[int]:
    """All filters are conjunctive; search tokens match across feature identity fields."""
    tokens = query.casefold().split()
    return [
        index
        for index, row in enumerate(rows)
        if (roi is None or roi_identity(row) == roi)
        and (not configuration or row.get("configuration") == configuration)
        and (not family or row.get("feature_family") == family)
        and (not status or row.get("status") == status)
        and all(
            token in " ".join(str(row.get(key, "")) for key in SEARCH_COLUMNS).casefold()
            for token in tokens
        )
    ]


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _records(value: Any) -> list[Mapping[str, Any]]:
    return [item for item in value if isinstance(item, Mapping)] if isinstance(value, list) else []


def _value(value: Any) -> str:
    if value is None:
        return "Not available"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return str(value)


def result_details(row: Mapping[str, Any], history: Sequence[Mapping[str, Any]]) -> str:
    """Resolve provenance by run AND ROI, never by feature name alone."""
    lines = ["FEATURE"]
    for title, key in (
        ("Name", "feature_name"),
        ("Value", "value"),
        ("Status", "status"),
        ("Family", "feature_family"),
        ("Official IBSI code", "ibsi_code"),
        ("Pictologics IBSI code", "pictologics_ibsi_code"),
        ("Native key", "feature_key"),
        ("Package-wide name", "pictologics_feature_name"),
        ("Preprocessing sequence", "preprocessing_sequence"),
    ):
        lines.append(f"{title}: {_value(row.get(key))}")
    lines.extend(["", "REGION AND RUN"])
    for title, key in (
        ("Image", "image_name"),
        ("Subject", "subject_id"),
        ("ROI", "roi_name"),
        ("ROI ID", "roi_id"),
        ("ROI source", "roi_source"),
        ("Configuration", "configuration"),
        ("Run ID", "run_id"),
        ("Started", "timestamp"),
        ("Pictologics version", "pictologics_version"),
        ("Extension version", "extension_version"),
    ):
        lines.append(f"{title}: {_value(row.get(key))}")
    matches = [record for record in history if record.get("run_id") == row.get("run_id")]
    if len(matches) != 1:
        return "\n".join([*lines, "", "Provenance unavailable or ambiguous for this run."])
    record = matches[0]
    provenance = _mapping(record.get("provenance"))
    lines.extend(["", "CONFIGURATION", f"SHA-256: {_value(record.get('configuration_sha256'))}"])
    configs = _mapping(_mapping(provenance.get("effective_configuration")).get("configs"))
    config = _mapping(configs.get(str(row.get("configuration"))))
    for key in ("source_mode", "sentinel_value"):
        if key in config:
            lines.append(f"{key.replace('_', ' ').capitalize()}: {_value(config[key])}")
    for index, step in enumerate(_records(config.get("steps")), 1):
        lines.append(f"{index}. {_value(step.get('step'))}")
        for key, value in _mapping(step.get("params")).items():
            lines.append(f"   {key}: {_value(value)}")
    lines.extend(["", "PROCESSING LOG"])
    logs = [
        log
        for log in _records(provenance.get("processing_logs"))
        if log.get("roi_id") == row.get("roi_id") and log.get("roi_source") == row.get("roi_source")
    ]
    entries = [
        entry
        for log in logs
        for entry in _records(log.get("entries"))
        if entry.get("config_name") == row.get("configuration")
    ]
    if not entries:
        lines.append("No matching processing log is available.")
    for entry in entries:
        for key in ("status", "error", "failed_step", "result_feature_count"):
            if key in entry:
                lines.append(f"{key.replace('_', ' ').capitalize()}: {_value(entry[key])}")
        for step in _records(entry.get("steps_executed")):
            lines.append(f"Step: {_value(step.get('step'))}")
            for key in (
                "params",
                "params_requested",
                "params_effective",
                "boundary_requested",
                "boundary_effective",
            ):
                if key in step:
                    lines.append(f"   {key.replace('_', ' ')}: {_value(step[key])}")
    for error in _records(record.get("errors")):
        if error.get("roi_id") == row.get("roi_id") and error.get("roi_source") == row.get(
            "roi_source"
        ):
            lines.append(f"ROI error: {_value(error.get('error'))}")
    for feature in _records(provenance.get("feature_catalog")):
        if feature.get("config") == row.get("configuration") and feature.get(
            "feature_key"
        ) == row.get("feature_key"):
            lines.extend(["", "FEATURE DICTIONARY"])
            lines.extend(
                f"{key.replace('_', ' ')}: {_value(value)}" for key, value in feature.items()
            )
            break
    return "\n".join(lines)
