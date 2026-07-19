#!/usr/bin/env python3
"""Probe one private Pictologics environment in a fresh PythonSlicer process.

This file intentionally uses only the Python standard library until the private
target has been placed first on ``sys.path``.  It is executed as a script by the
GUI after pip resolves a candidate environment and before that environment is
made active for new jobs.
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import os
import sys
from importlib import metadata
from pathlib import Path
from typing import Any, Sequence

EXPECTED_STANDARD_CONFIGURATIONS = {
    "standard_fbn_8",
    "standard_fbn_16",
    "standard_fbn_32",
    "standard_fbs_8",
    "standard_fbs_16",
    "standard_fbs_32",
}
EXPECTED_CATALOG_COLUMNS = {
    "config",
    "feature_key",
    "feature_name",
    "ibsi_code",
    "family",
}
EXPECTED_RUN_PARAMETERS = {"image", "mask", "subject_id", "config_names"}
EXPECTED_PIPELINE_METHODS = {
    "load_configs",
    "merge_configs",
    "list_configs",
    "to_dict",
    "clear_log",
}
_SITE_PACKAGE_PARTS = frozenset({"site-packages", "dist-packages"})


class ProbeError(RuntimeError):
    """The candidate environment cannot safely serve Pictologics jobs."""


def _path_is_inside(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def isolate_target(
    target: str | Path, search_path: Sequence[str] | None = None
) -> list[str]:
    """Place *target* first and remove every other package-directory entry."""

    target_path = Path(target).expanduser().resolve(strict=True)
    if not target_path.is_dir():
        raise ProbeError(f"private dependency target is not a directory: {target_path}")

    original = list(sys.path if search_path is None else search_path)
    isolated: list[str] = [str(target_path)]
    for entry in original:
        if entry:
            try:
                if Path(entry).resolve(strict=False) == target_path:
                    continue
            except (OSError, ValueError):
                pass
        try:
            parts = Path(entry).parts
        except (OSError, TypeError, ValueError):
            parts = ()
        if any(part.casefold() in _SITE_PACKAGE_PARTS for part in parts):
            continue
        isolated.append(entry)

    if search_path is None:
        sys.path[:] = isolated
        importlib.invalidate_caches()
    return isolated


def _distribution_version(target: Path) -> str:
    versions: list[str] = []
    for distribution in metadata.distributions(path=[str(target)]):
        name = distribution.metadata.get("Name")
        if name and name.casefold().replace("_", "-") == "pictologics":
            versions.append(str(distribution.version))
    if len(versions) != 1:
        found = ", ".join(sorted(versions)) or "none"
        raise ProbeError(
            "candidate must contain exactly one Pictologics distribution; "
            f"found: {found}"
        )
    return versions[0]


def _require_origin_inside(module: Any, target: Path, label: str) -> None:
    module_file = getattr(module, "__file__", None)
    if not module_file:
        raise ProbeError(f"imported {label} has no filesystem origin")
    origin = Path(module_file).resolve(strict=False)
    if not _path_is_inside(origin, target):
        raise ProbeError(
            f"imported {label} outside the private target: {origin} (target: {target})"
        )


def probe(target: str | Path, expected_version: str, *, warmup: bool = True) -> int:
    """Import, validate, and optionally warm one candidate environment."""

    target_path = Path(target).expanduser().resolve(strict=True)
    metadata_version = _distribution_version(target_path)
    if metadata_version != expected_version:
        raise ProbeError(
            f"distribution version {metadata_version!r} does not match adopted "
            f"version {expected_version!r}"
        )

    os.environ["PICTOLOGICS_DISABLE_WARMUP"] = "1"
    isolate_target(target_path)
    try:
        pictologics = importlib.import_module("pictologics")
    except Exception as exc:
        raise ProbeError(
            f"cannot import Pictologics from the candidate: {type(exc).__name__}: {exc}"
        ) from exc
    _require_origin_inside(pictologics, target_path, "Pictologics")

    imported_version = str(getattr(pictologics, "__version__", ""))
    if imported_version != expected_version:
        raise ProbeError(
            f"pictologics.__version__={imported_version!r} does not match adopted "
            f"version {expected_version!r}"
        )

    pipeline_type = getattr(pictologics, "RadiomicsPipeline", None)
    if not callable(pipeline_type):
        raise ProbeError("Pictologics does not expose RadiomicsPipeline")
    pipeline = pipeline_type()

    get_standard = getattr(pipeline, "get_all_standard_config_names", None)
    if not callable(get_standard):
        raise ProbeError(
            "RadiomicsPipeline.get_all_standard_config_names() is unavailable"
        )
    standard = set(get_standard())
    if standard != EXPECTED_STANDARD_CONFIGURATIONS:
        raise ProbeError(
            "standard configuration contract changed: "
            f"expected {sorted(EXPECTED_STANDARD_CONFIGURATIONS)}, got {sorted(standard)}"
        )

    describe = getattr(pipeline, "describe_features", None)
    if not callable(describe):
        raise ProbeError("RadiomicsPipeline.describe_features() is unavailable")
    catalog = describe()
    columns = set(getattr(catalog, "columns", ()))
    missing_columns = EXPECTED_CATALOG_COLUMNS - columns
    if missing_columns:
        raise ProbeError(
            f"feature catalog is missing columns: {', '.join(sorted(missing_columns))}"
        )
    if bool(getattr(catalog, "empty", True)):
        raise ProbeError("feature catalog is empty")

    run = getattr(pipeline, "run", None)
    if not callable(run):
        raise ProbeError("RadiomicsPipeline.run() is unavailable")
    missing_parameters = EXPECTED_RUN_PARAMETERS - set(
        inspect.signature(run).parameters
    )
    if missing_parameters:
        raise ProbeError(
            f"RadiomicsPipeline.run() is missing parameters: "
            f"{', '.join(sorted(missing_parameters))}"
        )
    for name in sorted(EXPECTED_PIPELINE_METHODS):
        if not callable(getattr(pipeline, name, None)):
            raise ProbeError(f"RadiomicsPipeline.{name}() is unavailable")
    if not callable(getattr(pictologics, "load_image", None)):
        raise ProbeError("pictologics.load_image() is unavailable")

    warmup_jit = getattr(pictologics, "warmup_jit", None)
    if not callable(warmup_jit):
        raise ProbeError("pictologics.warmup_jit() is unavailable")
    if warmup:
        os.environ["PICTOLOGICS_DISABLE_WARMUP"] = "0"
        try:
            warmup_jit()
        except Exception as exc:
            raise ProbeError(
                f"Pictologics JIT warmup failed: {type(exc).__name__}: {exc}"
            ) from exc

    print(
        f"Pictologics {expected_version} private-environment probe passed "
        f"({len(catalog)} described configuration-feature rows)."
    )
    return len(catalog)


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="candidate private dependency directory")
    parser.add_argument("expectedVersion", help="exact adopted Pictologics version")
    parser.add_argument(
        "--skip-warmup",
        action="store_true",
        help="validate the API without compiling kernels (tests only)",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_arguments(argv)
    try:
        probe(args.target, args.expectedVersion, warmup=not args.skip_warmup)
    except ProbeError as exc:
        print(f"Pictologics dependency probe failed: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        # Any other failure (import side effects, an API contract call raising an
        # unexpected type, filesystem errors) is still a probe failure: report it
        # cleanly with exit code 2 instead of leaking an unhandled traceback.
        print(
            f"Pictologics dependency probe failed ({type(exc).__name__}): {exc}",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
