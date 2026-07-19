#!/usr/bin/env python3
"""Fail fast when a released Pictologics no longer matches the wrapper API."""

from __future__ import annotations

import inspect
import os
import sys
import tempfile
from importlib.metadata import version
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "PictologicsSlicer"))


# This script is a release preflight, not a performance benchmark. Avoid import-time
# compilation while still giving Numba a deterministic writable cache location.
os.environ.setdefault("PICTOLOGICS_DISABLE_WARMUP", "1")
os.environ.setdefault(
    "NUMBA_CACHE_DIR", str(Path(tempfile.gettempdir()) / "pictologics-api-check-cache")
)

import pictologics  # noqa: E402

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


def _check_inline_builder_round_trip() -> None:
    """The GUI's in-app config builder emits documents it never loads itself.

    Confirm the adopted Pictologics accepts the builder output and each preset
    starter template through ``load_configs`` so the mirrored contract in
    ``PictologicsLib.inline_config`` cannot silently drift from the real library.
    """

    import yaml
    from PictologicsLib.inline_config import (
        INLINE_CONFIG_NAME,
        build_inline_configuration_document,
        default_inline_state,
        preset_configuration_document,
        preset_names,
    )

    documents = {INLINE_CONFIG_NAME: build_inline_configuration_document(default_inline_state())}
    for preset in preset_names():
        documents[preset] = preset_configuration_document(preset)

    with tempfile.TemporaryDirectory(prefix="pictologics-inline-check-") as directory:
        for expected_name, document in documents.items():
            path = Path(directory) / f"{expected_name}.yaml"
            path.write_text(yaml.safe_dump(document), encoding="utf-8")
            loaded = pictologics.RadiomicsPipeline.load_configs(
                path, validate=True, load_standard=False
            )
            names = list(loaded.list_configs())
            if expected_name not in names:
                raise RuntimeError(
                    f"Inline/preset document did not register '{expected_name}'; got {names}"
                )
            catalog = loaded.describe_features()
            described = {
                record["config"] for record in catalog.to_dict(orient="records")
            }
            if expected_name not in described:
                raise RuntimeError(
                    f"Inline/preset config '{expected_name}' described no features"
                )


def main() -> int:
    installed = version("pictologics")
    if str(pictologics.__version__) != installed:
        raise RuntimeError(
            f"pictologics.__version__={pictologics.__version__!r} does not match "
            f"distribution metadata {installed!r}"
        )

    pipeline = pictologics.RadiomicsPipeline()
    standard = set(pipeline.get_all_standard_config_names())
    if standard != EXPECTED_STANDARD_CONFIGURATIONS:
        raise RuntimeError(
            "Standard configuration contract changed: "
            f"expected {sorted(EXPECTED_STANDARD_CONFIGURATIONS)}, got {sorted(standard)}"
        )

    catalog = pipeline.describe_features()
    missing_columns = EXPECTED_CATALOG_COLUMNS - set(catalog.columns)
    if missing_columns or catalog.empty:
        raise RuntimeError(
            f"Feature catalog contract changed; missing={sorted(missing_columns)}, "
            f"empty={catalog.empty}"
        )

    run_parameters = inspect.signature(pipeline.run).parameters
    missing_parameters = {"image", "mask", "subject_id", "config_names"} - set(
        run_parameters
    )
    if missing_parameters:
        raise RuntimeError(
            f"RadiomicsPipeline.run contract changed; missing {sorted(missing_parameters)}"
        )
    for name in (
        "load_configs",
        "merge_configs",
        "list_configs",
        "to_dict",
        "clear_log",
    ):
        if not callable(getattr(pipeline, name, None)):
            raise RuntimeError(f"RadiomicsPipeline.{name} is unavailable")
    for name in ("load_image", "warmup_jit"):
        if not callable(getattr(pictologics, name, None)):
            raise RuntimeError(f"pictologics.{name} is unavailable")

    _check_inline_builder_round_trip()

    print(
        f"Pictologics {installed} wrapper API check passed "
        f"({len(catalog)} described configuration-feature rows)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
