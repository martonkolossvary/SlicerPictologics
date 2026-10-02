"""Opt-in mixed public CT/MRI batches, real recovery, and continuous RSS sampling.

Run only in a fresh disposable installed Slicer. Required environment:
PICTOLOGICS_SOAK_OUTPUT (new directory), SLICERPICTOLOGICS_TEST_DEPENDENCY_PATH
(existing qualified target). Optional PICTOLOGICS_SAMPLE_CACHE and
PICTOLOGICS_SOAK_ROUNDS (2–20, default 6). No installs, uploads or screenshots.
"""

from __future__ import annotations

import gc
import hashlib
import json
import os
import sys
import time
import traceback
from collections import defaultdict
from pathlib import Path
from unittest.mock import patch

import numpy as np
import qt
import slicer

REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY / "scripts"))
sys.path.insert(0, str(REPOSITORY / "PictologicsSlicer"))

from batch_soak_support import FIXTURES, audit_batch, mixed_plan  # noqa: E402
from benchmark_slicer_workloads import (  # noqa: E402
    Workloads,
    assert_parity,
    configuration,
    guard,
    pump,
    remove_fixture,
)
from create_ct_sample_demo import add_demo_rois, ct_slab, load_sample  # noqa: E402
from PictologicsLib.batch_reports import export_report  # noqa: E402
from workload_support import SAMPLES, MemorySampler  # noqa: E402

SCENE_CLASSES = ("vtkMRMLScalarVolumeNode", "vtkMRMLSegmentationNode",
                 "vtkMRMLCommandLineModuleNode", "vtkMRMLDisplayNode",
                 "vtkMRMLStorageNode", "vtkMRMLTableNode")


def node_counts():
    return {name: len(slicer.util.getNodesByClass(name)) for name in SCENE_CLASSES}


class BatchSoak(Workloads):
    def __init__(self, root, target):
        super().__init__(root, target)
        self.report.update(kind="mixed-public-data-batch-soak", fixtures={}, phases=[],
                           checkpoints=[], saved_reports={}, success=False)
        self.report["fixture_scope"] = "Repeated variants of two public scans; not independent patients or clinical masks"
        self.report["source_hashes"].update({str(path.relative_to(REPOSITORY)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (Path(__file__), REPOSITORY / "scripts/batch_soak_support.py")})
        self.document = configuration(bins=(16, 32))
        self.report["configuration"] = self.document
        self.config_path = root / "configuration.json"
        self.logic._atomicWriteJSON(self.config_path, self.document)
        self.jobs = []
        self.clock_start = time.perf_counter()
        self.memory = None
        self.ui_widget = None

    def save_fixture(self, label, volume, sample):
        segmentation, roi_info = add_demo_rois(volume, sample=sample)
        folder = self.root / "fixtures" / label
        folder.mkdir(parents=True)
        for node, name in ((volume, "image.nrrd"), (segmentation, "segmentation.seg.nrrd")):
            if not slicer.util.saveNode(node, str(folder / name)):
                raise RuntimeError(f"Could not save {label} fixture")
        info = {**SAMPLES[sample], **roi_info, "sample": sample,
                "dimensions_ijk": volume.GetImageData().GetDimensions(), "spacing_ijk": volume.GetSpacing(),
                "derivation": volume.GetAttribute("Pictologics.DemoDerivation") or "Original sample lattice",
                "files": {}}
        for name in ("image.nrrd", "segmentation.seg.nrrd"):
            with (folder / name).open("rb") as handle:
                digest = hashlib.file_digest(handle, "sha256").hexdigest()
            info["files"][name] = {"sha256": digest, "bytes": (folder / name).stat().st_size}
        self.logic._atomicWriteJSON(folder / "source.json", info)
        self.report["fixtures"][label] = info
        remove_fixture(segmentation, volume)

    def prepare_fixtures(self, cache):
        started = time.perf_counter()
        ct = load_sample("CTLiver", cache)
        for label, slices, stride in (("ct-small", 96, 2), ("ct-medium", 192, 2), ("ct-large", 192, 1)):
            self.save_fixture(label, ct_slab(ct, slices=slices, stride=stride), "CTLiver")
        remove_fixture(ct)
        del ct
        gc.collect()
        mri = load_sample("MRHead", cache)
        coarse = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "MRHead — lattice decimation")
        coarse.CopyOrientation(mri)
        coarse.SetSpacing(*[value * 2 for value in mri.GetSpacing()])
        slicer.util.updateVolumeFromArray(coarse, np.array(slicer.util.arrayFromVolume(mri)[::2, ::2, ::2], copy=True))
        coarse.CreateDefaultDisplayNodes()
        coarse.SetAttribute("Pictologics.DemoDerivation", "Every second voxel on all axes; same origin/direction, doubled spacing; not original-grid radiomics")
        self.save_fixture("mri-coarse", coarse, "MRHead")
        self.save_fixture("mri-native", mri, "MRHead")
        gc.collect()
        self.report["fixture_preparation_seconds"] = time.perf_counter() - started
        self.save()

    def make_study(self, label, plan):
        folder = self.root / "studies" / label
        folder.mkdir(parents=True)
        for item in plan:
            case = folder / item["case_name"]
            case.mkdir()
            source = self.root / "fixtures" / item["fixture"]
            # Hard links avoid duplicating large public images. The batch only reads
            # these inputs; deliberately malformed files are separate new files.
            for name in ("image.nrrd", "source.json"):
                os.link(source / name, case / name)
            if item.get("injection") == "invalid-segmentation":
                (case / "segmentation.seg.nrrd").write_text("Deliberately invalid public soak fixture.\n", encoding="utf-8")
            elif item.get("injection") != "missing-segmentation":
                os.link(source / "segmentation.seg.nrrd", case / "segmentation.seg.nrrd")
        self.logic._atomicWriteJSON(self.root / f"{label}-plan.json", plan)
        return folder

    def setup_widget(self):
        widget = self.widget()
        self.ui_widget = widget
        widget.initializeParameterNode()
        widget.ui.inputVolumeSelector.setCurrentNode(None)
        widget.ui.segmentationSelector.setCurrentNode(None)
        widget.ui.outputTableSelector.setCurrentNode(None)
        widget.ui.wholeVolumeCheckBox.setChecked(False)
        widget.ui.cropCheckBox.setChecked(True)
        for index in range(widget.ui.standardConfigListWidget.count):
            widget.ui.standardConfigListWidget.item(index).setCheckState(qt.Qt.Unchecked)
        widget.ui.additionalConfigCombo.setCurrentIndex(2)
        widget.ui.customConfigPathLineEdit.setText(str(self.config_path))
        widget.ui.batchImagePatternLineEdit.setText("image.nrrd")
        widget.ui.batchSegmentationPatternLineEdit.setText("segmentation.seg.nrrd")

    def checkpoint(self, label, **extra):
        sample = self.memory.samples[-1] if self.memory and self.memory.samples else None
        point = {"label": label, "seconds": time.perf_counter() - self.clock_start,
                 "nodes": node_counts(), **extra}
        if sample:
            point.update(gui_rss_bytes=sample[1], descendants_rss_bytes=sample[2],
                         sample_age_seconds=time.perf_counter() - sample[0])
        self.report["checkpoints"].append(point)
        print("SOAK_CHECKPOINT " + json.dumps(point), flush=True)

    def idle(self, label, seconds=3):
        gc.collect()
        started = time.perf_counter()
        while time.perf_counter() - started < seconds:
            guard(self.memory, started)
            pump()
        self.checkpoint(label)

    def export_state(self, label):
        widget = self.ui_widget
        table = widget.ui.outputTableSelector.currentNode()
        if table is not None:
            self.logic.exportTable(table, self.root / f"{label}-results.json")
            self.logic.exportTable(table, self.root / f"{label}-results.csv")
        for node in widget._batchReportNodes():
            document = widget._reportDocument(node)
            export_report(document, self.root / f"report-{document['batch_id']}.json")
            export_report(document, self.root / f"report-{document['batch_id']}.csv")

    def stop_owned_work(self):
        widget = self.ui_widget
        if widget is None:
            return
        if widget._batch is not None:
            widget._batch["stopped"] = True
        widget.onCancel()
        deadline = time.perf_counter() + 60
        while (widget._activeJob is not None or widget._batch is not None or
               any(self.logic.jobWorkerIsAlive(job) for job in self.jobs)) and time.perf_counter() < deadline:
            pump()
        if widget._activeJob is not None or any(self.logic.jobWorkerIsAlive(job) for job in self.jobs):
            raise RuntimeError("An owned worker still needs cleanup; staging has been retained")

    def run_phase(self, label, plan, *, cancel_case=None):
        widget = self.ui_widget
        folder = self.make_study(label, plan)
        widget.ui.batchFolderLineEdit.setText(str(folder))
        table = widget.ui.outputTableSelector.currentNode()
        previous = self.logic.rowsFromTable(table) if table is not None else []
        baseline_nodes = node_counts()
        by_name = {case["case_name"]: case for case in plan}
        started = time.perf_counter()
        phase_jobs = []
        original_prepare = self.logic.prepareJob
        original_remove = widget._removeBatchNodes
        cancelled = None

        def prepare(**kwargs):
            job = original_prepare(**kwargs)
            self.jobs.append(job)
            phase_jobs.append(job)
            if by_name[kwargs["subjectID"]].get("injection") == "invalid-worker-manifest":
                self.logic._atomicWriteJSON(Path(job["manifest_path"]), dict(job["manifest"], schema_version=999))
            return job

        def remove():
            original_remove()
            batch = widget._batch
            if batch is not None and 0 <= batch["index"] < len(batch["cases"]):
                case = batch["cases"][batch["index"]]
                record = batch["report"]["rows"][batch["index"]]
                self.checkpoint(label + ":case-cleanup", case_name=case.name,
                                status=record["status"], elapsed_seconds=record["elapsed_seconds"],
                                result_rows=widget.ui.outputTableSelector.currentNode().GetNumberOfRows()
                                if widget.ui.outputTableSelector.currentNode() is not None else 0)

        # Plain replacements do not retain call arguments. A MagicMock spy would
        # keep each volume/segmentation wrapper (and its pixels) alive, turning
        # instrumentation into artificial linear memory growth across the batch.
        with patch.object(self.logic, "prepareJob", new=prepare), patch.object(widget, "_removeBatchNodes", new=remove), \
                patch.object(slicer.util, "confirmOkCancelDisplay", return_value=True), \
                patch.object(slicer.util, "warningDisplay") as warnings, \
                patch.object(slicer.util, "errorDisplay") as errors, patch.object(self.logic, "showTable"):
            widget.onRunBatch()
            report_node = widget._selectedBatchReportNode()
            if report_node is None:
                raise AssertionError("The GUI did not create a batch report")
            while widget._batch is not None:
                guard(self.memory, started, timeout=2700)
                job = widget._activeJob
                active = widget._batch
                name = active["cases"][active["index"]].name
                if name == cancel_case and cancelled is None and job is not None and self.logic.jobWorkerIsAlive(job):
                    if widget._runStartedAt is not None and time.monotonic() - widget._runStartedAt >= 0.5:
                        cancelled = {"case_name": name, "worker_observed_alive": True,
                                     "requested_after_seconds": time.perf_counter() - started}
                        self.checkpoint(label + ":cancel-requested", case_name=name)
                        widget.onCancel()
                pump()
            # Reaper cleanup can trail terminal CLI notification. Require release,
            # not merely a cancelled UI label, before starting a recovery batch.
            deadline = time.perf_counter() + 60
            while any(self.logic.jobWorkerIsAlive(job) or Path(job["work_dir"]).exists() for job in phase_jobs):
                if time.perf_counter() > deadline:
                    raise AssertionError("Worker/staging remained after the batch")
                pump()
            if errors.called or warnings.call_count != int(any(case["expected_status"] == "failed" for case in plan)):
                raise AssertionError("Unexpected error/warning dialog outcome")
        if cancel_case is not None and cancelled is None:
            raise AssertionError("The intended real-worker cancellation was not exercised")
        table = widget.ui.outputTableSelector.currentNode()
        rows = self.logic.rowsFromTable(table)
        if rows[:len(previous)] != previous:
            raise AssertionError("A later batch changed previously committed rows")
        document = widget._reportDocument(report_node)
        expected_state = "stopped" if cancel_case else "finished"
        if document["state"] != expected_state or not document["finished_at"]:
            raise AssertionError("Incorrect terminal batch-report state")
        new_rows = rows[len(previous):]
        audit = audit_batch(document, new_rows, plan, self.document["configs"])
        groups = defaultdict(list)
        for row in new_rows:
            groups[row["subject_id"]].append(row)
        references = {}
        for case in plan:
            if case["expected_status"] == "completed":
                current = groups[case["case_name"]]
                fixture = case["fixture"]
                if fixture in references:
                    assert_parity(references[fixture], current)
                references[fixture] = current
        for name in SCENE_CLASSES[:3]:
            if node_counts()[name] != baseline_nodes[name]:
                raise AssertionError(f"Batch left temporary {name} nodes in the scene")
        if widget._activeJob is not None or widget.ui.cancelButton.enabled or widget._runFeedbackTimer.isActive():
            raise AssertionError("Batch terminal controls/timer did not recover")
        self.export_state(label)
        # Compare prior reports after another batch has run: history is immutable.
        for node in widget._batchReportNodes():
            old = widget._reportDocument(node)
            if old["batch_id"] in self.report["saved_reports"] and old != self.report["saved_reports"][old["batch_id"]]:
                raise AssertionError("Starting another batch changed an earlier report")
        self.report["saved_reports"][document["batch_id"]] = document
        self.report["phases"].append({"label": label, **audit, "seconds": time.perf_counter() - started,
                                      "cancel": cancelled, "cumulative_rows": len(rows), "plan": plan,
                                      "repeat_parity": "1e-9 relative/absolute tolerance",
                                      "worker_and_staging_released": True, "previous_rows_unchanged": True})
        self.save()
        self.idle(label + ":idle")

    def save_and_reload(self):
        widget = self.ui_widget
        table = widget.ui.outputTableSelector.currentNode()
        rows = self.logic.rowsFromTable(table)
        table_name = table.GetName()
        self.export_state("final")
        scene = self.root / "results-and-reports.mrb"
        if not slicer.util.saveScene(str(scene)):
            raise AssertionError("Could not save soak results and reports")
        slicer.mrmlScene.Clear()
        if not slicer.util.loadScene(str(scene)):
            raise AssertionError("Could not reload soak scene")
        restored = slicer.util.getNode(table_name)
        if self.logic.rowsFromTable(restored) != rows:
            raise AssertionError("Scene reload changed exact result rows")
        reports = {doc["batch_id"]: doc for doc in (widget._reportDocument(node) for node in widget._batchReportNodes())}
        if reports != self.report["saved_reports"] or widget.ui.batchReportCombo.count != len(reports):
            raise AssertionError("Saved report documents or selector did not restore")
        self.report["scene_roundtrip"] = {"rows": len(rows), "reports": len(reports), "exact": True,
                                          "scene_bytes": scene.stat().st_size}

    def execute(self, rounds, cache):
        self.prepare_fixtures(cache)
        self.setup_widget()
        with MemorySampler() as memory:
            self.memory = memory
            try:
                self.idle("initial-idle")
                self.run_phase("mixed", mixed_plan(rounds))
                cancellation = [{"case_name": "cancel-001-complete", "fixture": "ct-small", "expected_status": "completed"},
                                {"case_name": "cancel-002-active", "fixture": "ct-large", "expected_status": "cancelled"},
                                {"case_name": "cancel-003-unreached", "fixture": "mri-native", "expected_status": "not_started"}]
                self.run_phase("cancellation", cancellation, cancel_case="cancel-002-active")
                recovery = [{"case_name": f"recovery-{index:03d}-{fixture}", "fixture": fixture,
                             "expected_status": "completed"} for index, fixture in enumerate(FIXTURES, 1)]
                self.run_phase("recovery", recovery)
                self.save_and_reload()
                self.idle("after-scene-reload")
                self.ui_widget.cleanup()
                slicer.mrmlScene.Clear()
                self.idle("after-owned-scene-release", seconds=5)
                self.report["success"] = True
            except BaseException as original:
                # Preserve the first failed assertion even if a damaged scene
                # also prevents the best-effort final export/cleanup.
                for action in (self.stop_owned_work, lambda: self.export_state("interrupted")):
                    try:
                        action()
                    except Exception as secondary:
                        original.add_note(f"Recovery: {type(secondary).__name__}: {secondary}")
                raise
            finally:
                self.report["memory"] = memory.summary()
                self.report["rss_samples"] = [{"seconds": stamp - self.clock_start, "gui_rss_bytes": gui,
                                               "descendants_rss_bytes": children} for stamp, gui, children in memory.samples]
                self.save()


def main():
    if slicer.util.getNodesByClass("vtkMRMLVolumeNode") or slicer.util.getNodesByClass("vtkMRMLTableNode"):
        raise RuntimeError("Use a fresh disposable Slicer, not an existing user scene")
    rounds = int(os.environ.get("PICTOLOGICS_SOAK_ROUNDS", "6"))
    mixed_plan(rounds)
    root = Path(os.environ["PICTOLOGICS_SOAK_OUTPUT"]).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=False)
    target = Path(os.environ["SLICERPICTOLOGICS_TEST_DEPENDENCY_PATH"]).resolve(strict=True)
    cache = Path(os.environ.get("PICTOLOGICS_SAMPLE_CACHE", str(root / "sample-cache"))).resolve()
    workload = BatchSoak(root, target)
    try:
        workload.execute(rounds, cache)
    except BaseException as exc:
        workload.report.update(success=False, failure=f"{type(exc).__name__}: {exc}")
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
