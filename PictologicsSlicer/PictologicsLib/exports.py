"""Stage complete export sets and roll back caught publication failures.

Individual renames are atomic; several files cannot be one filesystem transaction.
This protects against caught write/rename errors, not power loss or concurrent
external edits. JSON is the single-file archival option.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path


def export_file_set(destination: Path, writer: Callable[[Path], Sequence[Path]]) -> list[Path]:
    """Write beside the destination, then publish with recoverable old copies.

    ``writer`` receives a temporary main filename and returns all written files
    in that same temporary directory. A failed rollback retains the old copies
    and reports their directory instead of deleting the remaining recovery data.
    """

    destination = destination.expanduser().absolute()
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".pictologics-export-", dir=destination.parent))
    retain = False
    published: list[Path] = []
    originals: dict[Path, Path] = {}
    try:
        new = staging / "new"
        old = staging / "previous"
        new.mkdir()
        old.mkdir()
        files = list(writer(new / destination.name))
        if not files or len(set(files)) != len(files) or any(
            path.parent != new or path.is_symlink() or not path.is_file() for path in files
        ):
            raise ValueError("Export writer returned an invalid file set.")
        destinations = [destination.parent / path.name for path in files]
        for target in destinations:
            if target.is_symlink() or (target.exists() and not target.is_file()):
                raise ValueError("Export destination must be a regular file, not a link or directory.")
            if target.exists():
                backup = old / target.name
                # Preserve restrictive permissions when a backup is moved back.
                shutil.copy2(target, backup)
                originals[target] = backup
        try:
            for source, target in zip(files, destinations, strict=True):
                os.replace(source, target)
                published.append(target)
        except BaseException:
            for target in reversed(published):
                try:
                    if target in originals:
                        os.replace(originals[target], target)
                    else:
                        target.unlink()
                except BaseException:
                    # Even a second interruption must not delete recovery copies.
                    retain = True
            if retain:
                raise RuntimeError(
                    "Export failed and rollback was incomplete. Do not use this export set; "
                    f"remaining previous files are retained for recovery in {old}. "
                    "The result table is unchanged."
                ) from None
            raise
        return destinations
    finally:
        if not retain:
            shutil.rmtree(staging)
