#!/usr/bin/env python3
"""Real-wheel FBS, shared-result, crop safety, geometry and interchange gates (two synthetic ROIs).

Runs on 0.5.1 and the 0.6+ candidate. Never installs or changes the adopted pin.
The newer-only cases qualify file-based options, not new GUI controls.
"""
from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("PICTOLOGICS_DISABLE_WARMUP", "1")
os.environ.setdefault("NUMBA_CACHE_DIR", str(Path(tempfile.gettempdir()) / "pictologics-release-cache"))

import nibabel as nib  # noqa: E402
import numpy as np  # noqa: E402
import pictologics  # noqa: E402
from geometry_parity_check import load_worker, oblique_anisotropic_affine  # noqa: E402
from PictologicsLib.inline_config import lint_configuration_document  # noqa: E402
from PictologicsLib.jobs import build_job_manifest  # noqa: E402
from PictologicsLib.results import (  # noqa: E402
    load_result_payload,
    validate_result_payload,
    write_result_payload,
)


def document(*steps):
    return {"schema_version": "1.0", "configs": {"case": {"source_mode": "full_image", "steps": list(steps)}}}


def main():
    worker = load_worker()
    modern = pictologics.__version__ != "0.5.1"
    extract = {"step": "extract_features", "params": {"families": ["histogram", "ivh"]}}
    intensity = {"step": "extract_features", "params": {"families": ["intensity"]}}
    fbs = {"step": "discretise", "params": {"method": "FBS", "bin_width": 16.0, "min_val": -1000.0}}
    with tempfile.TemporaryDirectory(prefix="pictologics-release-") as directory:
        root = Path(directory)
        xyz = np.indices((18, 17, 16))
        data = (xyz[0] ** 2 + xyz[1] * 3 + xyz[2] * 2 - 900).astype(np.float32)
        masks = []
        for region in ((slice(3, 8), slice(4, 10), slice(4, 11)),
                       (slice(9, 15), slice(7, 13), slice(6, 12))):
            mask = np.zeros(data.shape, dtype=np.uint8)
            mask[region] = 1
            masks.append(mask)
        affine = oblique_anisotropic_affine()
        image_path = root / "image.nii.gz"
        nib.save(nib.Nifti1Image(data, affine), image_path)
        rois = []
        for index, mask in enumerate(masks):
            path = root / f"roi-{index}.nii.gz"
            nib.save(nib.Nifti1Image(mask, affine), path)
            rois.append({"roi_id": str(index), "roi_name": f"ROI {index}", "roi_source": "segmentation", "mask_path": path})

        if modern:
            loaded = pictologics.load_image(image_path)
            lps_affine = np.diag([-1., -1., 1., 1.]) @ affine
            np.testing.assert_allclose(loaded.origin, lps_affine[:3, 3], atol=1e-6)
            np.testing.assert_allclose(np.asarray(loaded.direction) @ np.diag(loaded.spacing), lps_affine[:3, :3], atol=1e-6)

        def evaluate(config, crop):
            path = root / "config.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            manifest = worker.validate_manifest(build_job_manifest(
                image_path=image_path, image_name="release-gate", rois=rois,
                configuration_document={"standard_configurations": [], "custom_configuration_path": path,
                    "custom_configuration_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "warmup": False, "crop_to_roi": crop},
                metadata={"numba_cache_path": os.environ["NUMBA_CACHE_DIR"],
                    "pictologics_version_at_submission": pictologics.__version__},
                results_path=root / "result.json", provenance_path=root / "provenance.json",
                extension_version="0.1.0", pictologics_requirement=f"pictologics=={pictologics.__version__}",
            ), base_dir=root)
            payload = validate_result_payload(worker.execute_job(
                manifest, pictologics, Path(pictologics.__file__).parent,
                progress=worker.ProgressReporter(io.StringIO()),
            ))
            assert not payload["errors"], payload["errors"]
            assert payload["rows"] and all(row["status"] == "ok" for row in payload["rows"])
            assert {row["roi_id"] for row in payload["rows"]} == {"0", "1"}
            write_result_payload(root / "roundtrip.json", payload)
            assert load_result_payload(root / "roundtrip.json") == payload
            return payload

        def values(payload):
            return {(row["roi_id"], row["config"], row["feature_key"]): row["value"] for row in payload["rows"]}

        # Two explicit starts/widths, two ROIs; independent binning oracle.
        fixed = document(fbs, extract)
        fixed["configs"]["second"] = copy.deepcopy(fixed["configs"]["case"])
        fixed["configs"]["second"]["steps"][0]["params"].update(bin_width=8.0, min_val=-1024.0)
        uncropped, cropped = evaluate(fixed, False), evaluate(fixed, True)
        a, b = values(uncropped), values(cropped)
        assert a.keys() == b.keys()
        np.testing.assert_allclose(list(a.values()), list(b.values()), rtol=1e-9, atol=1e-12)
        for index, mask in enumerate(masks):
            for name, start, width in (("case", -1000., 16.), ("second", -1024., 8.)):
                bins = np.maximum(1, np.floor((data[mask != 0] - start) / width) + 1)
                np.testing.assert_allclose(a[str(index), name, "mean_discretised_intensity_X6K6"], bins.mean())
        print("Explicit FBS: two configurations/two ROIs, independent bin oracle, crop parity and exact JSON passed.", flush=True)

        # Shared results: a job with several configurations (the reuse shortcut) must
        # give the same bits as a job with each configuration alone. "roi" differs from
        # "full" only in voxel validity, a case that Pictologics 0.5.1 copied wrongly.
        shared = document(
            {"step": "resample", "params": {"new_spacing": [1.5, 1.5, 1.5], "interpolation": "linear"}},
            {"step": "discretise", "params": {"method": "FBN", "n_bins": 16}},
            {"step": "extract_features", "params": {"families": ["intensity", "morphology", "histogram", "texture"]}},
        )
        configs = shared["configs"]
        configs["full"] = configs.pop("case")
        configs["full_32"] = copy.deepcopy(configs["full"])
        configs["full_32"]["steps"][1]["params"]["n_bins"] = 32
        configs["roi"] = {**copy.deepcopy(configs["full"]), "source_mode": "roi_only"}
        together, alone = values(evaluate(shared, False)), {}
        for name, config in configs.items():
            alone.update(values(evaluate({"schema_version": "1.0", "configs": {name: config}}, False)))
        assert together.keys() == alone.keys()
        mismatched = [key for key in together if json.dumps(together[key]) != json.dumps(alone[key])]
        assert not mismatched, mismatched[:5]
        assert any(json.dumps(together[key]) != json.dumps(together[(key[0], "roi", key[2])])
                   for key in together if key[1] == "full"), "the voxel-validity case must change values"
        print(f"Shared results: {len(together)} values of three configurations equal each configuration alone, bit for bit.", flush=True)

        if modern:
            # Defaults and public log provenance are part of acceptance, not just API existence.
            import pandas as pd
            from pictologics.results import format_results

            raw = {name: pd.Series({key: value for (roi, config, key), value in a.items()
                                    if roi == "0" and config == name}) for name in fixed["configs"]}
            long = format_results(raw, fmt="long", output_type="dict")
            assert {(row["config"], row["feature_key"]): row["value"] for row in long} == {
                (config, key): value for (roi, config, key), value in a.items() if roi == "0"}
            wide = format_results(raw, fmt="wide", output_type="dict")
            assert wide == {row["pictologics_feature_name"]: row["value"] for row in uncropped["rows"] if row["roi_id"] == "0"}
            pipeline = pictologics.RadiomicsPipeline()
            for name in pipeline.get_all_standard_config_names():
                if "_fbs_" in name:
                    steps = pipeline.to_dict(config_names=[name])["configs"][name]["steps"]
                    assert next(s["params"]["min_val"] for s in steps if s["step"] == "discretise") == -1000
            for log in uncropped["provenance"]["processing_logs"]:
                for entry in log["entries"]:
                    assert len(entry["config_hash"]) == 64 and entry["environment"]
                    assert entry["elapsed_seconds"] >= 0
                    assert any("min_val_effective" in step for step in entry["steps_executed"])

            for step in (
                {"step": "normalise", "params": {"method": "zscore", "region": "image"}},
                {"step": "grow_mask", "params": {"to_mm": 4., "apply_to": "both"}},
            ):
                config = document(step, intensity)
                full, requested_crop = evaluate(config, False), evaluate(config, True)
                assert values(full) == values(requested_crop)
                assert requested_crop["provenance"]["crop_margin_mm"] is None
                assert all(log["crop_box"] is None for log in requested_crop["provenance"]["processing_logs"])

            inherited = copy.deepcopy(fbs)
            del inherited["params"]["min_val"]
            resegment = {"step": "resegment", "params": {"range_min": -850., "apply_to": "intensity"}}
            explicit = copy.deepcopy(fbs)
            explicit["params"]["min_val"] = -850.
            assert values(evaluate(document(resegment, inherited, extract), False)) == values(evaluate(document(resegment, explicit, extract), False))
            ivh = document(resegment, {"step": "discretise", "params": {"method": "FBN", "n_bins": 32}},
                           {"step": "extract_features", "params": {"families": ["ivh"],
                            "ivh_discretisation": {"method": "FBS", "bin_width": 16.}}})
            ivh_explicit = copy.deepcopy(ivh)
            ivh_explicit["configs"]["case"]["steps"][-1]["params"]["ivh_discretisation"]["min_val"] = -850.
            assert values(evaluate(ivh, False)) == values(evaluate(ivh_explicit, False))
            invalid = [document(inherited, extract),
                       document({"step": "resegment", "params": {"range_min": -850., "apply_to": "morph"}}, inherited, extract),
                       document(resegment, {"step": "normalise", "params": {"method": "zscore", "region": "roi"}}, inherited, extract),
                       document(resegment, {"step": "filter", "params": {"type": "mean", "support": 3}}, inherited, extract),
                       document({"step": "extract_features", "params": {"families": ["ivh"], "ivh_discretisation": {"method": "FBS", "bin_width": 10}}}),
                       document({"step": "grow_mask", "params": {"to_mm": 2, "nearest_roi": True}}, intensity)]
            for config in invalid:
                path = root / "invalid.json"
                path.write_text(json.dumps(config), encoding="utf-8")
                check = worker.check_configuration_file(pictologics, path)
                assert not check["valid"], config

            padded = document({"step": "filter", "params": {
                "type": "gaussian", "sigma_mm": 1., "boundary": "constant", "padding_value": -1000.}}, intensity)
            assert lint_configuration_document(padded) == []
            evaluate(padded, False)
            evaluate(document({"step": "filter", "params": {
                "type": "gabor", "sigma_mm": 1., "lambda_mm": 2., "gamma": 1.,
                "response": "real"}}, intensity), False)
            evaluate(document({"step": "extract_features", "params": {
                "families": ["intensity"], "include_local_intensity": True,
                "include_spatial_intensity": True, "local_intensity_params": {"enabled": True},
                "spatial_intensity_params": {"enabled": True}}}), False)
            print("0.6: LPS geometry, fixed CT presets, FBS inheritance/rejections, crop fallback, joint-ROI rejection and public log passed.", flush=True)
    print(f"Pictologics {pictologics.__version__} expanded compatibility passed.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
