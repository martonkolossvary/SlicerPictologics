#!/usr/bin/env python3
"""Assert the wrapper worker reproduces direct Pictologics values on identical NIfTI.

Two code paths are compared on the *same* NIfTI files:

1. PictologicsCLI worker: ``execute_job()`` -> long result rows.
2. Direct Pictologics: ``RadiomicsPipeline().run()`` on the same file paths.

The synthetic volume uses an anisotropic, obliquely rotated affine (a non
axis-aligned direction matrix and a nonzero origin), so any drift in the worker's
image/mask loading, configuration selection, or value extraction surfaces as a
numeric mismatch rather than passing silently on a trivially axis-aligned grid.

Scope: this does NOT cover the Slicer -> NIfTI staging round-trip (``saveNode`` and
labelmap export). That round-trip requires a real Slicer executable and remains the
documented release gate; this script locks the wrapper-vs-library half of it.
"""

from __future__ import annotations

import importlib.util
import math
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "PictologicsSlicer"))

os.environ.setdefault("PICTOLOGICS_DISABLE_WARMUP", "1")
os.environ.setdefault(
    "NUMBA_CACHE_DIR",
    str(Path(tempfile.gettempdir()) / "slicerpictologics-parity-numba"),
)

import nibabel as nib  # noqa: E402
import numpy as np  # noqa: E402
import pictologics  # noqa: E402
from PictologicsLib.jobs import build_job_manifest  # noqa: E402
from PictologicsLib.results import validate_result_payload  # noqa: E402

CONFIG = "standard_fbn_32"
RELATIVE_TOLERANCE = 1e-9
ABSOLUTE_TOLERANCE = 1e-12


def load_worker():
    path = ROOT / "PictologicsCLI/PictologicsCLI.py"
    spec = importlib.util.spec_from_file_location("pictologics_parity_worker", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load worker source: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def oblique_anisotropic_affine() -> np.ndarray:
    """Anisotropic spacing combined with an in-plane rotation and a nonzero origin."""

    angle = math.radians(18.0)
    cos, sin = math.cos(angle), math.sin(angle)
    rotation = np.array(
        [[cos, -sin, 0.0], [sin, cos, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64
    )
    spacing = np.diag(np.array([0.7, 1.3, 2.5], dtype=np.float64))
    affine = np.eye(4, dtype=np.float64)
    affine[:3, :3] = rotation @ spacing
    affine[:3, 3] = np.array([12.0, -8.0, 4.0], dtype=np.float64)
    return affine


def worker_values(worker, pictologics_module, root: Path) -> dict[tuple[str, str], float]:
    image_path = root / "image.nii.gz"
    mask_path = root / "mask.nii.gz"
    version = str(pictologics_module.__version__)
    manifest_payload = build_job_manifest(
        image_path=image_path,
        image_name="oblique-parity",
        rois=[
            {
                "roi_id": "cuboid",
                "roi_name": "Cuboid",
                "roi_source": "segmentation",
                "mask_path": mask_path,
            }
        ],
        configuration_document={
            "standard_configurations": [CONFIG],
            "custom_configuration_path": None,
            "custom_configuration_sha256": None,
            "warmup": False,
        },
        metadata={
            "numba_cache_path": os.environ["NUMBA_CACHE_DIR"],
            "pictologics_version_at_submission": version,
            "input_volume_node_id": "synthetic",
        },
        results_path=root / "results.json",
        provenance_path=root / "provenance.json",
        extension_version="0.1.0",
        pictologics_requirement=f"pictologics=={version}",
        subject_id="parity",
    )
    manifest = worker.validate_manifest(manifest_payload, base_dir=root)
    worker.verify_runtime_version(manifest, pictologics_module)
    payload = validate_result_payload(
        worker.execute_job(manifest, pictologics_module, Path(pictologics_module.__file__).parent)
    )
    if payload["errors"]:
        raise RuntimeError(f"Worker reported ROI errors: {payload['errors']}")

    values: dict[tuple[str, str], float] = {}
    for row in payload["rows"]:
        if row["configuration"] != CONFIG or row["status"] != "ok":
            continue
        identity = (row["feature_name"], row["ibsi_code"])
        if identity in values:
            raise RuntimeError(f"Ambiguous worker feature identity: {identity}")
        values[identity] = float(row["value"])
    return values


def direct_values(pictologics_module, root: Path) -> dict[tuple[str, str], float]:
    image_path = root / "image.nii.gz"
    mask_path = root / "mask.nii.gz"
    pipeline = pictologics_module.RadiomicsPipeline()
    results = pipeline.run(str(image_path), str(mask_path), config_names=[CONFIG])
    catalog = pipeline.describe_features()
    key_to_identity: dict[str, tuple[str, str]] = {}
    for record in catalog.to_dict(orient="records"):
        if record["config"] == CONFIG:
            key_to_identity[str(record["feature_key"])] = (
                str(record["feature_name"]),
                str(record["ibsi_code"]),
            )

    values: dict[tuple[str, str], float] = {}
    for feature_key, value in results[CONFIG].items():
        identity = key_to_identity.get(str(feature_key))
        if identity is None:
            continue
        numeric = float(value)
        if math.isfinite(numeric):
            values[identity] = numeric
    return values


def main() -> int:
    worker = load_worker()
    version = str(pictologics.__version__)
    os.environ["PICTOLOGICS_DISABLE_WARMUP"] = "0"
    pictologics.warmup_jit()

    with tempfile.TemporaryDirectory(prefix="slicerpictologics-parity-") as directory:
        root = Path(directory)
        shape = (22, 20, 18)
        coordinates = np.indices(shape, dtype=np.float32)
        image_array = (
            coordinates[0] * 3.0
            + coordinates[1] * 1.7
            + coordinates[2] * 0.4
            + 5.0 * np.sin(coordinates[0] * 0.5)
            + 3.0 * np.cos(coordinates[1] * 0.3)
        ).astype(np.float32)
        mask_array = np.zeros(shape, dtype=np.uint8)
        mask_array[3:-3, 3:-3, 3:-3] = 1
        affine = oblique_anisotropic_affine()
        nib.save(nib.Nifti1Image(image_array, affine), root / "image.nii.gz")
        nib.save(nib.Nifti1Image(mask_array, affine), root / "mask.nii.gz")

        via_worker = worker_values(worker, pictologics, root)
        via_direct = direct_values(pictologics, root)

    if not via_worker:
        raise RuntimeError("Worker produced no successful feature values to compare.")
    if set(via_worker) != set(via_direct):
        only_worker = sorted(set(via_worker) - set(via_direct))
        only_direct = sorted(set(via_direct) - set(via_worker))
        raise RuntimeError(
            "Finite-feature sets differ between worker and direct Pictologics.\n"
            f"  worker-only: {only_worker}\n  direct-only: {only_direct}"
        )

    mismatches = []
    for identity, worker_value in via_worker.items():
        direct_value = via_direct[identity]
        if not math.isclose(
            worker_value,
            direct_value,
            rel_tol=RELATIVE_TOLERANCE,
            abs_tol=ABSOLUTE_TOLERANCE,
        ):
            mismatches.append((identity, worker_value, direct_value))

    if mismatches:
        preview = "\n".join(
            f"  {name} ({code}): worker={w!r} direct={d!r}"
            for (name, code), w, d in mismatches[:10]
        )
        raise RuntimeError(
            f"{len(mismatches)} feature value(s) diverged between the worker and "
            f"direct Pictologics on an oblique anisotropic grid:\n{preview}"
        )

    print(
        f"Pictologics {version} geometry parity passed: {len(via_worker)} features "
        f"match direct execution on an oblique anisotropic NIfTI (config {CONFIG})."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
