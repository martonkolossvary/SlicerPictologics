#!/usr/bin/env python3
"""Run the real wrapper worker on a small anisotropic synthetic NIfTI pair."""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "PictologicsSlicer"))

os.environ.setdefault("PICTOLOGICS_DISABLE_WARMUP", "1")
os.environ.setdefault(
    "NUMBA_CACHE_DIR",
    str(Path(tempfile.gettempdir()) / "slicerpictologics-smoke-numba"),
)

import nibabel as nib  # noqa: E402
import numpy as np  # noqa: E402
import pictologics  # noqa: E402
from PictologicsLib.jobs import build_job_manifest  # noqa: E402
from PictologicsLib.results import validate_result_payload  # noqa: E402


def load_worker():
    path = ROOT / "PictologicsCLI/PictologicsCLI.py"
    spec = importlib.util.spec_from_file_location("pictologics_real_worker_smoke", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load worker source: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    worker = load_worker()
    version = str(pictologics.__version__)
    with tempfile.TemporaryDirectory(
        prefix="slicerpictologics-worker-smoke-"
    ) as directory:
        root = Path(directory)
        shape = (18, 16, 14)
        coordinates = np.indices(shape, dtype=np.float32)
        image_array = (
            coordinates[0] * 3.0
            + coordinates[1] * 1.7
            + coordinates[2] * 0.4
            + np.sin(coordinates[0])
        ).astype(np.float32)
        mask_array = np.zeros(shape, dtype=np.uint8)
        mask_array[2:-2, 2:-2, 2:-2] = 1
        affine = np.array(
            [
                [0.7, 0.0, 0.0, 12.0],
                [0.0, 1.3, 0.0, -8.0],
                [0.0, 0.0, 2.5, 4.0],
                [0.0, 0.0, 0.0, 1.0],
            ],
            dtype=np.float64,
        )
        image_path = root / "image.nii.gz"
        mask_path = root / "mask.nii.gz"
        nib.save(nib.Nifti1Image(image_array, affine), image_path)
        nib.save(nib.Nifti1Image(mask_array, affine), mask_path)

        manifest_payload = build_job_manifest(
            image_path=image_path,
            image_name="anisotropic-smoke",
            rois=[
                {
                    "roi_id": "central-cuboid",
                    "roi_name": "Central cuboid",
                    "roi_source": "segmentation",
                    "mask_path": mask_path,
                }
            ],
            configuration_document={
                "standard_configurations": ["standard_fbn_32"],
                "custom_configuration_path": None,
                "custom_configuration_sha256": None,
                "warmup": True,
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
            subject_id="smoke",
        )
        manifest = worker.validate_manifest(manifest_payload, base_dir=root)
        worker.verify_runtime_version(manifest, pictologics)

        os.environ["PICTOLOGICS_DISABLE_WARMUP"] = "0"
        pictologics.warmup_jit()
        payload = validate_result_payload(
            worker.execute_job(manifest, pictologics, Path(pictologics.__file__).parent)
        )

        if payload["errors"]:
            raise RuntimeError(
                f"Synthetic extraction reported errors: {payload['errors']}"
            )
        if not payload["rows"] or any(row["status"] != "ok" for row in payload["rows"]):
            statuses = sorted({row["status"] for row in payload["rows"]})
            raise RuntimeError(
                f"Synthetic extraction did not produce only successful rows: {statuses}"
            )
        if {row["pictologics_version"] for row in payload["rows"]} != {version}:
            raise RuntimeError(
                "Synthetic extraction recorded an unexpected package version"
            )

        print(
            f"Pictologics {version} real worker smoke passed: "
            f"{len(payload['rows'])} anisotropic NIfTI feature rows, all successful."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
