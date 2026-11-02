"""Estimate the image size that the resampling steps of a run create."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

# Pictologics keeps image intensities as float64.
BYTES_PER_VOXEL = 8


def resampled_voxel_count(
    dimensions: Sequence[int], spacing: Sequence[float], new_spacing: Sequence[float]
) -> int:
    """Return the voxel count after resampling, rounded as Pictologics rounds it."""

    return math.prod(
        math.ceil(round(size * old / new, 9))
        for size, old, new in zip(dimensions, spacing, new_spacing, strict=True)
    )


def _resample_spacings(document: Mapping[str, Any]) -> list[list[float]]:
    spacings: list[list[float]] = []
    configs = document.get("configs")
    if not isinstance(configs, Mapping):
        return spacings
    for config in configs.values():
        steps = config.get("steps") if isinstance(config, Mapping) else config
        if not isinstance(steps, (list, tuple)):
            continue
        for step in steps:
            if not isinstance(step, Mapping) or step.get("step") != "resample":
                continue
            params = step.get("params")
            value = params.get("new_spacing") if isinstance(params, Mapping) else None
            if not isinstance(value, (list, tuple)):
                continue
            try:
                spacing = [float(item) for item in value]
            except (TypeError, ValueError):
                continue
            if len(spacing) == 3 and all(math.isfinite(item) and item > 0 for item in spacing):
                spacings.append(spacing)
    return spacings


def largest_voxel_count(
    dimensions: Sequence[int],
    spacing: Sequence[float],
    documents: Iterable[Mapping[str, Any]],
) -> int:
    """Return the largest image, in voxels, that any configuration creates.

    Pictologics resamples the whole scan, not only the region, so the count is the
    same for every region. A configuration without resampling keeps the scan grid.
    Invalid spacings are skipped here; the worker reports them.
    """

    largest = math.prod(dimensions)
    for document in documents:
        for new_spacing in _resample_spacings(document):
            largest = max(largest, resampled_voxel_count(dimensions, spacing, new_spacing))
    return largest
