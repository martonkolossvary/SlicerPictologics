"""Actual Slicer input/config/export/scene paths with spaces and Unicode.

Use a fresh disposable Slicer. Set PICTOLOGICS_PATHS_OUTPUT to a new directory and
SLICERPICTOLOGICS_TEST_DEPENDENCY_PATH to an existing qualified private target.
No installation, package mutation, uploads or screenshots. All fixtures synthetic.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
import traceback
from pathlib import Path

import slicer

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "scripts"))
sys.path.insert(0, str(REPOSITORY / "PictologicsSlicer"))
sys.path.insert(0, str(REPOSITORY / "PictologicsSlicer/Testing/Python"))

from benchmark_slicer_workloads import Workloads, configuration  # noqa: E402
from PictologicsSlicerIntegrationTest import create_oblique_segmentation_fixture  # noqa: E402


def main():
    if slicer.util.getNodesByClass("vtkMRMLVolumeNode") or slicer.util.getNodesByClass("vtkMRMLTableNode"):
        raise RuntimeError("Use a fresh disposable Slicer process")
    root = Path(os.environ["PICTOLOGICS_PATHS_OUTPUT"]).resolve()
    root.mkdir(parents=True, exist_ok=False)
    folder = root / "input export \u00e1rv\u00edz \u03a9"
    folder.mkdir()
    target = Path(os.environ["SLICERPICTOLOGICS_TEST_DEPENDENCY_PATH"]).resolve(strict=True)
    workload = Workloads(root, target)
    workload.report["source_hashes"]["scripts/check_slicer_paths.py"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    logic = workload.logic
    try:
        fixture = create_oblique_segmentation_fixture()
        second = slicer.vtkSegment()
        second.DeepCopy(fixture.segmentation_node.GetSegmentation().GetSegment(fixture.segment_id))
        second.SetName("Second synthetic ROI")
        fixture.segmentation_node.GetSegmentation().AddSegment(second)
        image_path = folder / "synthetic scan \u00e9.nii.gz"
        mask_path = folder / "two regions \u03a9.seg.nrrd"
        assert slicer.util.saveNode(fixture.volume_node, str(image_path))
        assert slicer.util.saveNode(fixture.segmentation_node, str(mask_path))
        # No calculated results exist at this point.
        slicer.mrmlScene.Clear()
        volume = slicer.util.loadVolume(str(image_path))
        segmentation = slicer.util.loadSegmentation(str(mask_path))
        document = configuration(bins=(16, 32))
        config_path = folder / "settings \u00e1.json"
        config_path.write_text(json.dumps(document), encoding="utf-8")
        table = logic.process(volume, segmentation, standardConfigurations=[],
                              customConfigurationPath=str(config_path), subjectID="synthetic-path-test")
        table.SetName("Path acceptance results")
        rows = logic.rowsFromTable(table)
        assert workload.inspection.installed_version == "0.5.1"
        assert len(rows) == 680 and all(row["status"] == "ok" for row in rows)
        assert len({row["roi_id"] for row in rows}) == 2
        assert {row["config"] for row in rows} == set(document["configs"])
        exports = []
        for suffix in ("csv", "json"):
            exports.extend(logic.exportTable(table, folder / f"features \u03a9.{suffix}"))
        assert len(exports) == 4 and all(path.is_file() and path.stat().st_size for path in exports)
        expected = {(row["roi_id"], row["config"], row["feature_key"]): row["value"] for row in rows}
        independent_rows = 0
        for name, value in document["configs"].items():
            single_path = folder / f"single {name} \u00e1.json"
            single_path.write_text(json.dumps({"configs": {name: value}}), encoding="utf-8")
            single = logic.process(volume, segmentation, standardConfigurations=[],
                                   customConfigurationPath=str(single_path), subjectID="synthetic-path-test")
            actual = logic.rowsFromTable(single)
            assert len(actual) == 340 and all(row["status"] == "ok" for row in actual)
            for row in actual:
                key = (row["roi_id"], row["config"], row["feature_key"])
                assert math.isclose(row["value"], expected[key], rel_tol=1e-12, abs_tol=1e-12)
            logic.exportTable(single, folder / f"independent {name}.json")
            independent_rows += len(actual)
            slicer.mrmlScene.RemoveNode(single)
        scene = folder / "saved results \u00e1.mrb"
        assert slicer.util.saveScene(str(scene))
        slicer.mrmlScene.Clear()
        assert slicer.util.loadScene(str(scene))
        restored = slicer.mrmlScene.GetFirstNodeByName("Path acceptance results")
        readback = logic.rowsFromTable(restored)
        assert len(rows) == len(readback)
        for before, after in zip(rows, readback, strict=True):
            assert before.keys() == after.keys()
            for key in before:
                if key == "value":
                    assert float(before[key]).hex() == float(after[key]).hex()
                else:
                    assert before[key] == after[key]
        logic.exportTable(restored, folder / "reopened \u03a9.json")
        workload.report.update(success=True, rows=len(rows), independent_configuration_rows=independent_rows,
                               scene_binary64_mismatches=0, input_export_scene_unicode_paths=True,
                               csv_companions_verified=True)
    except BaseException as exc:
        workload.report.update(success=False, failure=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        workload.save()


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        traceback.print_exc()
        slicer.util.exit(1)
    else:
        slicer.util.exit(0)
