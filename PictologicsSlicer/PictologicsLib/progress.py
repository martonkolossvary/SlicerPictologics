"""Presentation helpers for truthful, ROI-boundary worker feedback."""

from __future__ import annotations

import json

ROI_PROGRESS_PREFIX = "PICTOLOGICS_ROI "


def elapsed_text(seconds: float) -> str:
    """Format monotonic elapsed time without implying a completion estimate."""
    hours, remainder = divmod(max(0, int(seconds)), 3600)
    minutes, seconds_value = divmod(remainder, 60)
    return f"Elapsed: {hours:02d}:{minutes:02d}:{seconds_value:02d}"


def current_roi_index(output: str, roi_count: int) -> int | None:
    """Read the latest valid worker marker; ignore unrelated or partial output."""
    for line in reversed(output.splitlines()):
        if not line.startswith(ROI_PROGRESS_PREFIX):
            continue
        try:
            marker = json.loads(line[len(ROI_PROGRESS_PREFIX) :])
        except ValueError:
            continue
        if not isinstance(marker, dict):
            continue
        index, total = marker.get("index"), marker.get("total")
        if (
            type(index) is int
            and type(total) is int
            and total == roi_count
            and 0 <= index < roi_count
        ):
            return index
    return None
