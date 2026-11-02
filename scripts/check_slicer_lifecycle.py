#!/usr/bin/env python3
"""Opt-in, four-process source-checkout acceptance test inside a disposable Slicer.

Run phases install, restart, update, restart-update in separate Slicer processes.
SLICERPICTOLOGICS_LIFECYCLE_ROOT must identify a new, empty test directory for the
first phase. Install/update download the adopted wheels, only into that directory.
This checks dependency/scene persistence, not Extension Factory package installation.
"""

from __future__ import annotations

import importlib.metadata
import json
import math
import os
import sys
import traceback
from pathlib import Path
from unittest.mock import patch

import slicer

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "PictologicsSlicer"))
sys.path.insert(0, str(REPOSITORY / "PictologicsSlicer/Testing/Python"))

from PictologicsLib.inline_config import default_inline_state  # noqa: E402
from PictologicsLib.profiles import build_profile, validate_profile  # noqa: E402
from PictologicsSlicerIntegrationTest import create_oblique_segmentation_fixture  # noqa: E402

from PictologicsSlicer import PictologicsSlicerLogic  # noqa: E402

PHASES = ("install", "restart", "update", "restart-update")
MARKER = "slicer-pictologics-local-lifecycle-v1"


def shared_versions() -> dict[str, str]:
    return {name: importlib.metadata.version(name) for name in ("numpy", "Pillow")}


def compare_rows(actual_rows: list[dict], expected_rows: list[dict], *, new_run: bool = False) -> list[dict]:
    differences = []
    assert len(actual_rows) == len(expected_rows)
    for actual, saved in zip(actual_rows, expected_rows, strict=True):
        assert actual.keys() == saved.keys()
        for name, value in actual.items():
            if new_run and name in ("run_id", "timestamp"):
                continue
            if name == "value" and value is not None:
                expected = float(saved[name])
                matches = (
                    math.isnan(float(value)) and math.isnan(expected)
                ) or (
                    math.isclose(float(value), expected, rel_tol=1e-12, abs_tol=1e-12)
                    if new_run else float(value).hex() == expected.hex()
                )
                if not matches:
                    differences.append({"feature_key": actual["feature_key"], "actual": value, "expected": expected})
            else:
                assert value == saved[name], name
    return differences


def main() -> bool:
    root_text = os.environ.get("SLICERPICTOLOGICS_LIFECYCLE_ROOT", "")
    phase = os.environ.get("SLICERPICTOLOGICS_LIFECYCLE_PHASE", "")
    if not root_text or not Path(root_text).is_absolute() or phase not in PHASES:
        raise RuntimeError("Set an absolute lifecycle root and one of: " + ", ".join(PHASES))
    root = Path(root_text).resolve()
    if os.environ.get("PICTOLOGICS_DEV_SOURCE"):
        raise RuntimeError("Unset PICTOLOGICS_DEV_SOURCE; this checks the adopted PyPI wheel.")
    if slicer.mrmlScene.GetNumberOfNodesByClass("vtkMRMLVolumeNode"):
        raise RuntimeError("Use a new disposable Slicer process, not a working patient scene.")
    marker = root / "lifecycle-marker.json"
    if phase == "install":
        root.mkdir(parents=True, exist_ok=True)
        if any(root.iterdir()):
            raise RuntimeError("The install phase requires an empty test directory.")
        marker.write_text(json.dumps({"format": MARKER}), encoding="utf-8")
    elif not marker.is_file() or json.loads(marker.read_text())["format"] != MARKER:
        raise RuntimeError("This is not a lifecycle-test-owned directory.")
    if (root / f"{phase}.json").exists():
        raise RuntimeError(f"Phase {phase} already completed; use a new test directory.")
    previous = None
    if phase != "install":
        previous_phase = PHASES[PHASES.index(phase) - 1]
        previous = json.loads((root / f"{previous_phase}.json").read_text())

    class LocalLogic(PictologicsSlicerLogic):
        @staticmethod
        def dependencyRoot() -> Path:
            return root / "private-dependencies"

    logic = LocalLogic()
    shared_before = shared_versions()
    from slicer import packaging

    installs_allowed = phase in ("install", "update")
    reextracted_rows = 0
    scene_precision_differences = []
    pip_options = (
        {"wraps": packaging.pip_install}
        if installs_allowed else {"side_effect": AssertionError("Restart attempted to reinstall")}
    )
    with patch.object(packaging, "pip_install", **pip_options) as installer, patch.object(
        slicer.util, "confirmOkCancelDisplay", return_value=installs_allowed
    ):
        inspection = logic.ensureDependencies(forceUpgrade=phase == "update")
        assert inspection.satisfied and not inspection.ambiguous
        target = str(inspection.target)
        if previous is not None:
            assert shared_before == previous["shared_versions"]
            assert (target != previous["dependency_target"]) == (phase == "update")
        if phase == "install":
            fixture = create_oblique_segmentation_fixture()
            second = slicer.vtkSegment()
            second.DeepCopy(fixture.segmentation_node.GetSegmentation().GetSegment(fixture.segment_id))
            second.SetName("Second synthetic ROI")
            fixture.segmentation_node.GetSegmentation().AddSegment(second)
            table = logic.process(
                fixture.volume_node, fixture.segmentation_node,
                subjectID="synthetic-lifecycle", reader="acceptance-test",
            )
            table.SetName("Lifecycle results")
            rows = logic.rowsFromTable(table)
            assert len({row["roi_id"] for row in rows}) == 2
            assert rows and all(row["status"] == "ok" for row in rows)
            profile = build_profile("Lifecycle profile", ["standard_fbn_32"], default_inline_state())
            (root / "settings.pictologics-profile.json").write_text(json.dumps(profile), encoding="utf-8")
            (root / "expected-rows.json").write_text(json.dumps(rows), encoding="utf-8")
        else:
            assert slicer.util.loadScene(str(root / "synthetic-scene.mrb"))
            table = slicer.mrmlScene.GetFirstNodeByName("Lifecycle results")
            rows = logic.rowsFromTable(table)
            expected = json.loads((root / "expected-rows.json").read_text())
            scene_precision_differences = compare_rows(rows, expected)
            validate_profile(json.loads((root / "settings.pictologics-profile.json").read_text()))
            if phase == "restart-update":
                fresh_table = logic.process(
                    slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLScalarVolumeNode"),
                    slicer.mrmlScene.GetFirstNodeByClass("vtkMRMLSegmentationNode"),
                    subjectID="synthetic-lifecycle", reader="acceptance-test",
                )
                fresh_rows = logic.rowsFromTable(fresh_table)
                assert not compare_rows(fresh_rows, expected, new_run=True), "Fresh extraction changed"
                reextracted_rows = len(fresh_rows)
        assert logic.provenanceHistory(table, required=True)
        exports = []
        for suffix in ("csv", "json"):
            exports.extend(logic.exportTable(table, root / f"{phase}-results.{suffix}", wide=True))
        assert all(path.is_file() and path.stat().st_size for path in exports)
        if phase == "install":
            # Keep independent full-precision exports before any scene save/close.
            assert slicer.util.saveScene(str(root / "synthetic-scene.mrb"))
        assert installer.call_count == int(installs_allowed)
    assert shared_versions() == shared_before, "Slicer's shared packages changed"
    assert "pictologics" not in sys.modules, "Pictologics leaked into the GUI process"
    report = {
        "phase": phase,
        "scope": "source-checkout lifecycle, NOT factory package acceptance",
        "slicer_version": slicer.app.applicationVersion,
        "python_version": sys.version,
        "pictologics_version": inspection.installed_version,
        "dependency_target": target,
        "shared_versions": shared_before,
        "install_calls": installer.call_count,
        "row_count": len(rows),
        "roi_count": len({row["roi_id"] for row in rows}),
        "reextracted_rows": reextracted_rows,
        "scene_precision_mismatches": len(scene_precision_differences),
        "scene_precision_comparison": "binary64-exact (including signed zero)",
        "scene_precision_examples": scene_precision_differences[:5],
        "update_scope": "same-version replacement, NOT adoption of a newer package release",
        "exports": [str(path) for path in exports],
        "success": not scene_precision_differences,
    }
    (root / f"{phase}.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("LIFECYCLE_ACCEPTANCE " + json.dumps(report), flush=True)
    # Retain a failing report so subsequent phases can still exercise dependency
    # replacement/reuse independently. A rounded scene is never reported as a pass.
    return bool(report["success"])


if __name__ == "__main__":
    try:
        success = main()
    except BaseException:
        traceback.print_exc()
        slicer.util.exit(1)
    else:
        slicer.util.exit(0 if success else 1)
