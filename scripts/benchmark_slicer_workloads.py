"""Opt-in public-data performance run inside a fresh installed Slicer.

Required environment: PICTOLOGICS_BENCHMARK_OUTPUT (new directory),
SLICERPICTOLOGICS_TEST_DEPENDENCY_PATH (existing qualified private target).
Optional PICTOLOGICS_SAMPLE_CACHE avoids repeat sample downloads; optional
PICTOLOGICS_BENCHMARK_CASES selects comma-separated case names from main().
No package installation, shared-package mutation, uploads or screenshots.
"""

from __future__ import annotations

import gc
import hashlib
import json
import math
import os
import platform
import sys
import time
import traceback
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import qt
import slicer

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "scripts"))
sys.path.insert(0, str(REPOSITORY / "PictologicsSlicer"))

from create_ct_sample_demo import add_demo_rois, ct_slab, load_sample, save_fixture  # noqa: E402
from PictologicsLib.dependencies import inspect_target  # noqa: E402
from PictologicsLib.inline_config import (  # noqa: E402
    build_inline_configuration_document,
    default_inline_state,
)
from PictologicsLib.results import load_result_payload  # noqa: E402
from PictologicsWidgets.results_browser import ResultsBrowser  # noqa: E402
from workload_support import SAMPLES, MemorySampler  # noqa: E402

from PictologicsSlicer import EXTENSION_VERSION, PictologicsSlicerLogic  # noqa: E402

MAX_TREE_RSS = 12 * 1024**3
JOB_TIMEOUT = 900


def configuration(spacing=1.0, bins=(32,)):
    configs = {}
    for count in bins:
        state = default_inline_state()
        state.update(spacing=[spacing] * 3, discretise_value=count)
        document = build_inline_configuration_document(state)
        configs[f"benchmark_{spacing:g}mm_fbn{count}"] = document["configs"]["in_app"]
    return {"configs": configs}


def pump():
    slicer.app.processEvents()
    time.sleep(0.02)


def remove_fixture(*nodes):
    """Only remove nodes owned by this disposable benchmark scene."""
    for node in nodes:
        family = PictologicsSlicerLogic._temporaryNodeFamily(node, includeColor=False)
        if node.GetStorageNode() is not None:
            family.append(node.GetStorageNode())
        PictologicsSlicerLogic._removeTemporaryNodes(family)


def guard(sampler, started, *, timeout=JOB_TIMEOUT):
    if time.perf_counter() - started > timeout:
        raise TimeoutError("Benchmark time budget exceeded")
    if sampler.samples and sum(sampler.samples[-1][1:]) > MAX_TREE_RSS:
        raise MemoryError("Benchmark reached its 12 GiB sampled process-tree guard")


def comparable_values(rows):
    return {(row["roi_name"], row["config"], row["feature_key"]): row["value"] for row in rows}


def assert_parity(first, second):
    a, b = comparable_values(first), comparable_values(second)
    if a.keys() != b.keys():
        raise AssertionError("Repeat/crop result keys differ")
    for key in a:
        if a[key] is None or b[key] is None:
            if a[key] != b[key]:
                raise AssertionError(f"Missing-value mismatch: {key}")
        elif not math.isclose(a[key], b[key], rel_tol=1e-9, abs_tol=1e-9):
            raise AssertionError(f"Repeat/crop numeric mismatch: {key}")


class Workloads:
    def __init__(self, root, target):
        self.root = root
        self.target = target

        class Logic(PictologicsSlicerLogic):
            @classmethod
            def dependencyRoot(cls):
                return root / "private-benchmark-state"

            def ensureDependencies(self, *, forceUpgrade):
                if forceUpgrade:
                    raise RuntimeError("Benchmark must never install/update dependencies")
                inspection = inspect_target(target, self.pictologicsRequirement())
                if not inspection.satisfied:
                    raise RuntimeError("Provide the existing qualified private dependency target")
                return inspection

        self.logic = Logic()
        # ScriptedLoadableModuleLogic otherwise strips "Logic" to an empty
        # singleton name for this local subclass, making saved scenes noisy.
        self.logic.moduleName = "PictologicsSlicer"
        self.inspection = self.logic.ensureDependencies(forceUpgrade=False)
        self.report = {"scope": "Local source-checkout performance observations, not clinical validation or hardware guarantees",
            "versions": {"extension": EXTENSION_VERSION, "pictologics": self.inspection.installed_version,
                "slicer": slicer.app.applicationVersion, "slicer_revision": slicer.app.repositoryRevision,
                "python": platform.python_version(), "qt": qt.qVersion(), "os": platform.system(),
                "os_release": platform.mac_ver()[0] or platform.release(), "process_architecture": platform.machine(),
                "logical_cpus": os.cpu_count()},
            "sources": SAMPLES, "sample_loading_seconds": {}, "measurements": [], "success": False,
            "memory_method": "0.5s POSIX ps RSS samples; descendants sum can double-count shared pages; not exact peak or unique RAM",
            "max_tree_rss_bytes": MAX_TREE_RSS,
            "source_hashes": {str(p.relative_to(REPOSITORY)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in [Path(__file__), REPOSITORY / "scripts/workload_support.py",
                          REPOSITORY / "scripts/create_ct_sample_demo.py", REPOSITORY / "PictologicsSlicer/PictologicsSlicer.py",
                          REPOSITORY / "PictologicsCLI/PictologicsCLI.py"]}}
        self.save()

    def save(self):
        self.logic._atomicWriteJSON(self.root / "report.json", self.report)

    def record(self, measurement):
        self.report["measurements"].append(measurement)
        self.save()
        print("BENCHMARK_RESULT " + json.dumps(measurement), flush=True)

    def widget(self):
        # Use the application-owned widget/dialog lifetime, as normal users do.
        with patch("PictologicsSlicer.PictologicsSlicerLogic", return_value=self.logic):
            widget = slicer.modules.pictologicsslicer.widgetRepresentation().self()
        widget.logic = self.logic
        return widget

    def run(self, label, volume, segmentation, document, *, crop=False):
        started = time.perf_counter()
        cache = self.logic.privatePaths()["numba_cache"]
        cache_files = len(list(cache.rglob("*.nbc"))) if cache.exists() else 0
        job = node = None
        with MemorySampler() as memory:
            try:
                job = self.logic.prepareJob(inputVolumeNode=volume, segmentationNode=segmentation,
                    selectedSegmentIDs=self.logic.segmentIDs(segmentation), includeWholeVolume=False,
                    standardConfigurations=[], customConfigurationPath=None, inlineConfigurationDocument=document,
                    subjectID="public-data-benchmark", installedVersion=self.inspection.installed_version,
                    dependencyPath=self.target, cropToRegion=crop)
                staged = time.perf_counter()
                node = self.logic.startJob(job)
                terminal = int(node.Completed) | int(node.ErrorsMask) | int(node.Cancelled)
                while node.IsBusy() or not int(node.GetStatus()) & terminal:
                    guard(memory, started)
                    pump()
                if node.GetStatus() & node.ErrorsMask or node.GetStatus() == node.Cancelled:
                    raise RuntimeError(str(node.GetErrorText() or node.GetStatusString()))
                finished = time.perf_counter()
                payload = load_result_payload(job["output_path"])
                if len({row["roi_id"] for row in payload["rows"]}) != 2 or payload["errors"]:
                    raise RuntimeError("Expected actual results from two ROIs without ROI failures")
                table = self.logic.commitRows(None, payload["rows"], append=False, payload=payload, manifest=job["manifest"])
                committed = time.perf_counter()
                self.logic.exportTable(table, self.root / f"{label}.json")
                self.logic.exportTable(table, self.root / f"{label}.csv")
                exported = time.perf_counter()
                measurement = {"case": label, "dimensions_ijk": volume.GetImageData().GetDimensions(),
                    "spacing_ijk": volume.GetSpacing(), "roi_count": 2, "configuration_count": len(document["configs"]),
                    "configuration": document, "crop_requested": crop,
                    "crop_used": [item["crop_box"] is not None for item in payload["provenance"]["processing_logs"]],
                    "numba_cache_files_before": cache_files, "numba_cache_condition": "empty" if not cache_files else "reused",
                    "stage_seconds": staged - started, "worker_seconds": finished - staged,
                    "commit_seconds": committed - finished, "export_seconds": exported - committed,
                    "total_seconds": exported - started, "rows": len(payload["rows"]),
                    "statuses": dict(Counter(row["status"] for row in payload["rows"]))}
                slicer.mrmlScene.RemoveNode(table)
            finally:
                if node is not None and node.IsBusy():
                    node.Cancel()
                    deadline = time.perf_counter() + 60
                    while (node.IsBusy() or self.logic.jobWorkerIsAlive(job)) and time.perf_counter() < deadline:
                        pump()
                if job is not None and not self.logic.jobWorkerIsAlive(job):
                    self.logic.cleanupJob(job)
                if node is not None and not node.IsBusy():
                    slicer.mrmlScene.RemoveNode(node)
        measurement["memory"] = memory.summary()
        self.record(measurement)
        return payload

    def batch(self, volume, segmentation, *, count=10):
        folder = self.root / "batch-inputs"
        for index in range(count):
            case = folder / f"repeat-{index + 1:02d}"
            case.mkdir(parents=True)
            for node, name in ((volume, "image.nrrd"), (segmentation, "segmentation.seg.nrrd")):
                if not slicer.util.saveNode(node, str(case / name)):
                    raise RuntimeError("Could not save repeated public batch fixture")
        widget = self.widget()
        widget.initializeParameterNode()
        widget.ui.outputTableSelector.setCurrentNode(None)
        widget.ui.wholeVolumeCheckBox.setChecked(False)
        widget.ui.cropCheckBox.setChecked(True)
        for index in range(widget.ui.standardConfigListWidget.count):
            widget.ui.standardConfigListWidget.item(index).setCheckState(qt.Qt.Unchecked)
        custom = self.root / "batch-configuration.json"
        custom.write_text(json.dumps(configuration()))
        widget.ui.additionalConfigCombo.setCurrentIndex(2)
        widget.ui.customConfigPathLineEdit.setText(str(custom))
        widget.ui.batchFolderLineEdit.setText(str(folder))
        widget.ui.batchImagePatternLineEdit.setText("image.nrrd")
        widget.ui.batchSegmentationPatternLineEdit.setText("segmentation.seg.nrrd")
        started = time.perf_counter()
        case_points = []
        seen = set()
        with MemorySampler() as memory, patch.object(slicer.util, "confirmOkCancelDisplay", return_value=True), patch.object(
            slicer.util, "warningDisplay"
        ) as warnings, patch.object(self.logic, "showTable"):
            try:
                widget.onRunBatch()
                while widget._batch is not None:
                    guard(memory, started, timeout=1800)
                    index = widget._batch["index"]
                    if index not in seen and memory.samples:
                        seen.add(index)
                        case_points.append({"case_index": index, "seconds": time.perf_counter() - started,
                                            "gui_rss_bytes": memory.samples[-1][1]})
                    pump()
            except BaseException:
                if widget._batch is not None:
                    widget._batch["stopped"] = True
                widget.onCancel()
                deadline = time.perf_counter() + 60
                while widget._activeJob is not None and time.perf_counter() < deadline:
                    pump()
                raise
        table = widget.ui.outputTableSelector.currentNode()
        rows = self.logic.rowsFromTable(table)
        if warnings.called or len({row["subject_id"] for row in rows}) != count:
            raise RuntimeError("Not every batch case produced results")
        self.logic.exportTable(table, self.root / "batch-results.json")
        self.logic.exportTable(table, self.root / "batch-results.csv")
        self.record({"case": "batch10", "fixture": "Ten copies of the same public CT and two demo ROIs; not ten independent patients",
            "cases": count, "rows": len(rows), "total_seconds": time.perf_counter() - started,
            "case_boundaries": case_points, "memory": memory.summary(), "status": str(widget.ui.statusLabel.text)})
        widget.ui.outputTableSelector.setCurrentNode(None)
        slicer.mrmlScene.RemoveNode(table)

    def table_scale(self, payload, count):
        widget = self.widget()
        rows = []
        for index in range(count):
            row = dict(payload["rows"][index % len(payload["rows"])])
            row.update(run_id="synthetic-ui-scale", subject_id="synthetic-duplicate",
                       image_name="UI stress fixture — copied values, not new extractions",
                       roi_id=f"copy-{index // len(payload['rows'])}-{row['roi_id']}")
            rows.append(row)
        document = {**payload, "run_id": "synthetic-ui-scale", "rows": rows,
                    "provenance": {"benchmark": "Duplicated measured rows for UI-only scaling", "feature_catalog": payload["provenance"]["feature_catalog"]}}
        started = time.perf_counter()
        with MemorySampler() as memory:
            table = self.logic.commitRows(None, rows, append=False, payload=document, manifest={"configuration_sha256": "synthetic-ui-scale"})
            committed = time.perf_counter()
            widget.ui.outputTableSelector.setCurrentNode(table)
            if widget._resultsBrowser is None:
                widget._resultsBrowser = ResultsBrowser(widget.parent, widget._refreshResultsBrowser)
            browser = widget._resultsBrowser
            if not widget._refreshResultsBrowser():
                raise RuntimeError("Could not load the results browser")
            loaded = time.perf_counter()
            browser.search.setText("mean")
            filtered = time.perf_counter()
            browser.next_page()
            paged = time.perf_counter()
            self.logic.exportTable(table, self.root / f"table-{count}.json")
            exported = time.perf_counter()
            # Export before saving/closing even these synthetic scenes.
            scene = self.root / f"table-{count}.mrb"
            if not slicer.util.saveScene(str(scene)):
                raise RuntimeError("Could not save scale-test scene")
            saved = time.perf_counter()
            browser.close()
            widget.ui.outputTableSelector.setCurrentNode(None)
            slicer.mrmlScene.RemoveNode(table)
        self.record({"case": f"table{count}", "fixture": "Repeated calculated values, UI-only synthetic stress data",
            "rows": count, "commit_seconds": committed - started, "browser_load_seconds": loaded - committed,
            "filter_seconds": filtered - loaded, "page_seconds": paged - filtered,
            "export_seconds": exported - paged, "scene_save_seconds": saved - exported,
            "scene_bytes": scene.stat().st_size, "memory": memory.summary()})
        del rows, document, browser
        gc.collect()


def main():
    if slicer.util.getNodesByClass("vtkMRMLVolumeNode"):
        raise RuntimeError("Use a fresh, disposable Slicer process")
    root = Path(os.environ["PICTOLOGICS_BENCHMARK_OUTPUT"]).expanduser().resolve()
    if root.exists():
        raise RuntimeError("Benchmark output must be a new directory")
    root.mkdir(parents=True)
    target = Path(os.environ["SLICERPICTOLOGICS_TEST_DEPENDENCY_PATH"]).resolve(strict=True)
    cache = Path(os.environ.get("PICTOLOGICS_SAMPLE_CACHE", str(root / "sample-cache"))).resolve()
    workload = Workloads(root, target)
    selected = set(os.environ.get("PICTOLOGICS_BENCHMARK_CASES", "cold,warm,mri,large,crop,multiple,fine,batch,tables").split(","))
    if selected - {"cold", "warm", "mri", "large", "crop", "multiple", "fine", "batch", "tables"}:
        raise ValueError("Unknown benchmark case selection")
    try:
        started = time.perf_counter()
        source = load_sample("CTLiver", cache)
        small = ct_slab(source)
        large = ct_slab(source, slices=192, stride=1) if selected & {"large", "crop"} else None
        remove_fixture(source)
        del source
        gc.collect()
        small_seg, info = add_demo_rois(small)
        large_seg = add_demo_rois(large)[0] if large is not None else None
        save_fixture(small, small_seg, root / "ct-example", info)
        workload.report["sample_loading_seconds"]["CTLiver_and_fixtures"] = time.perf_counter() - started
        baseline = None
        if selected & {"cold", "warm", "tables"}:
            baseline = workload.run("ct-cold", small, small_seg, configuration())
        if "warm" in selected:
            for index in range(2):
                repeat = workload.run(f"ct-warm-{index + 1}", small, small_seg, configuration())
                assert_parity(baseline["rows"], repeat["rows"])
        if "mri" in selected:
            started = time.perf_counter()
            mri = load_sample("MRHead", cache)
            mri_seg, _ = add_demo_rois(mri, sample="MRHead")
            workload.report["sample_loading_seconds"]["MRHead"] = time.perf_counter() - started
            workload.run("mri", mri, mri_seg, configuration())
            remove_fixture(mri_seg, mri)
            del mri_seg, mri
            gc.collect()
        uncropped = None
        if "large" in selected:
            uncropped = workload.run("ct-large", large, large_seg, configuration())
        if "crop" in selected:
            cropped = workload.run("ct-large-crop", large, large_seg, configuration(), crop=True)
            if uncropped:
                assert_parity(uncropped["rows"], cropped["rows"])
        if "multiple" in selected:
            workload.run("ct-two-configs", small, small_seg, configuration(bins=(16, 32)))
        if "fine" in selected:
            workload.run("ct-fine-0.5mm", small, small_seg, configuration(spacing=0.5))
        if large is not None:
            remove_fixture(large_seg, large)
            del large_seg, large
            gc.collect()
        if "batch" in selected:
            workload.batch(small, small_seg)
        if "tables" in selected:
            for count in (10_000, 100_000):
                workload.table_scale(baseline, count)
        # Exports/scenes have been saved. Release only this disposable scene's UI
        # observers while application-owned PythonQt objects are still alive.
        if selected & {"batch", "tables"}:
            workload.widget().cleanup()
        slicer.mrmlScene.Clear()
        slicer.app.processEvents()
        workload.report["success"] = True
        workload.save()
    except BaseException as exc:
        workload.report["failure"] = f"{type(exc).__name__}: {exc}"
        workload.save()
        raise


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        traceback.print_exc()
        slicer.util.exit(1)
    else:
        slicer.util.exit(0)
