"""Find the cases of a batch run: each subfolder holds one image and one segmentation."""

from __future__ import annotations

import os
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path


@dataclass(frozen=True)
class BatchCase:
    """One case folder; its name becomes the subject ID."""

    name: str
    image: Path
    segmentation: Path | None


@dataclass(frozen=True)
class BatchSkip:
    """A case folder that could not be included in a batch."""

    name: str
    reason: str


def discover_cases(
    folder: str | os.PathLike[str], image_pattern: str, segmentation_pattern: str
) -> tuple[list[BatchCase], list[BatchSkip]]:
    """Return valid case folders and structured skip reasons."""

    cases: list[BatchCase] = []
    skipped: list[BatchSkip] = []
    subfolders = sorted(path for path in Path(folder).iterdir() if path.is_dir())
    for case_folder in (path for path in subfolders if not path.name.startswith(".")):
        files = sorted(path for path in case_folder.iterdir() if path.is_file())
        images = [path for path in files if fnmatch(path.name, image_pattern)]
        segmentations = [
            path
            for path in files
            if segmentation_pattern and fnmatch(path.name, segmentation_pattern)
            and path not in images
        ]
        if len(images) != 1:
            skipped.append(BatchSkip(case_folder.name, f"{len(images)} files match {image_pattern!r}"))
        elif segmentation_pattern and len(segmentations) != 1:
            skipped.append(
                BatchSkip(case_folder.name, f"{len(segmentations)} files match {segmentation_pattern!r}")
            )
        else:
            cases.append(
                BatchCase(case_folder.name, images[0], segmentations[0] if segmentations else None)
            )
    return cases, skipped


def find_cases(
    folder: str | os.PathLike[str], image_pattern: str, segmentation_pattern: str
) -> tuple[list[BatchCase], list[str]]:
    """Return the cases in the subfolders of *folder*, and why folders were skipped.

    A case folder must hold exactly one file whose name matches *image_pattern* and,
    when *segmentation_pattern* is not empty, exactly one other file that matches it.
    """

    cases, skipped = discover_cases(folder, image_pattern, segmentation_pattern)
    return cases, [f"{item.name}: {item.reason}" for item in skipped]
