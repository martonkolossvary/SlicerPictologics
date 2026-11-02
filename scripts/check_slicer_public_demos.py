"""Exercise the tracked public demonstrations through the real GUI run handler.

Automated widget evidence, not a visual walkthrough. Use a disposable Slicer with
a main window (Invoke-SlicerValidation.ps1 -Visible);
PICTOLOGICS_DEMO_SAMPLE is MRHead or CTLiver, PICTOLOGICS_DEMO_OUTPUT is new,
and SLICERPICTOLOGICS_TEST_DEPENDENCY_PATH is an existing qualified target.
No installs, screenshots, uploads, or changes to normal Slicer settings.
"""
from __future__ import annotations

import hashlib
import os
import sys
import time
import traceback
from pathlib import Path
from unittest.mock import patch

import slicer

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "scripts"))
from benchmark_slicer_workloads import Workloads, guard, pump  # noqa: E402
from workload_support import MemorySampler  # noqa: E402


def main():
    if slicer.util.mainWindow() is None:
        raise RuntimeError("The tracked demos need a main window; launch with -Visible")
    if slicer.util.getNodesByClass("vtkMRMLVolumeNode") or slicer.util.getNodesByClass("vtkMRMLTableNode"):
        raise RuntimeError("Use a fresh disposable Slicer process")
    sample = os.environ["PICTOLOGICS_DEMO_SAMPLE"]
    if sample not in ("MRHead", "CTLiver"):
        raise ValueError("Choose a tracked public demonstration")
    root = Path(os.environ["PICTOLOGICS_DEMO_OUTPUT"]).resolve()
    root.mkdir(parents=True, exist_ok=False)
    target = Path(os.environ["SLICERPICTOLOGICS_TEST_DEPENDENCY_PATH"]).resolve(strict=True)
    workload = Workloads(root, target)
    workload.report.update(kind="automated-public-demo-widget-check", sample=sample)
    for name in ("check_slicer_public_demos.py", "create_sample_data_demo.py"):
        workload.report["source_hashes"]["scripts/" + name] = hashlib.sha256((REPOSITORY / "scripts" / name).read_bytes()).hexdigest()
    widget = workload.widget()
    logic = workload.logic
    cache = Path(os.environ.get("PICTOLOGICS_SAMPLE_CACHE", str(root / "sample-cache"))).resolve()
    cache.mkdir(parents=True, exist_ok=True)
    slicer.mrmlScene.GetCacheManager().SetRemoteCacheDirectory(str(cache))
    # Redirect only dependency inspection to the qualified, existing target.
    # This test must never install into normal per-user application storage.
    with patch.object(logic, "inspectDependencies", return_value=workload.inspection), patch.dict(
        os.environ, {"PICTOLOGICS_DEMO_AUTORUN": "0", "PICTOLOGICS_CT_DEMO_OUTPUT": str(root / "ct-inputs"),
                     "PICTOLOGICS_SAMPLE_CACHE": str(cache)}
    ):
        try:
            assert not widget.ui.wholeVolumeCheckBox.checked
            if sample == "MRHead":
                from create_sample_data_demo import create_demo
            else:
                from create_ct_sample_demo import create_demo
            create_demo()
            assert not widget.ui.wholeVolumeCheckBox.checked
            assert len(logic.segmentIDs(widget.ui.segmentationSelector.currentNode())) == 2
            assert widget._selectedConfigurations() == ["standard_fbn_32"]
            started = time.perf_counter()
            with MemorySampler() as memory:
                widget.onRun()
                while widget._activeJob is not None:
                    guard(memory, started)
                    pump()
            table = widget.ui.outputTableSelector.currentNode()
            rows = logic.rowsFromTable(table)
            logic.exportTable(table, root / "features.csv")
            logic.exportTable(table, root / "features.json")
            assert len(rows) == 340 and all(row["status"] == "ok" for row in rows)
            assert {row["config"] for row in rows} == {"standard_fbn_32"}
            assert len({row["roi_id"] for row in rows}) == 2
            assert slicer.util.saveScene(str(root / "demo.mrb"))
            workload.report.update(success=True, rows=len(rows), configurations=["standard_fbn_32"],
                                   whole_volume=False, elapsed_seconds=time.perf_counter() - started,
                                   memory=memory.summary(), status=str(widget.ui.statusLabel.text))
        except BaseException as exc:
            workload.report.update(success=False, failure=f"{type(exc).__name__}: {exc}")
            table = widget.ui.outputTableSelector.currentNode()
            if table is not None:
                logic.exportTable(table, root / "interrupted-results.json")
            raise
        finally:
            workload.save()
            widget.cleanup()


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        traceback.print_exc()
        slicer.util.exit(1)
    else:
        slicer.util.exit(0)
