"""Local-only documentation drafts from public CTLiver and matching annotations.

Run in a fresh visible Slicer with --disable-settings --ignore-slicerrc.
Required: PICTOLOGICS_ANATOMICAL_DEMO_OUTPUT (new temporary directory),
PICTOLOGICS_ANATOMICAL_LABELS (downloaded liver_100 labels),
PICTOLOGICS_SAMPLE_CACHE (contains checksum-verified CTLiver.nrrd), and
SLICERPICTOLOGICS_TEST_DEPENDENCY_PATH (existing qualified private target).
No installs, uploads, normal-setting changes, or published-image replacement.
The CT is cropped on its original lattice; intensities and annotation voxels are
unchanged. Dataset labels, not newly validated clinical segmentations, are shown.
"""

from __future__ import annotations

import hashlib
import itertools
import os
import sys
import time
import traceback
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import ctk
import numpy as np
import SimpleITK as sitk
import slicer
import vtk

sys.path.insert(0, str(Path(__file__).resolve().parent))
from benchmark_slicer_workloads import Workloads, guard, pump  # noqa: E402
from create_sample_data_demo import fit_panel  # noqa: E402
from workload_support import SAMPLES, MemorySampler  # noqa: E402

LABEL_SOURCE = {
    "dataset": "Medical Segmentation Decathlon Task03_Liver / liver_100",
    "mirror_revision": "6a5aad7ca262f2420d1bd4c2517b37b265db53eb",
    "url": "https://huggingface.co/datasets/MedOtter/msd-liver/resolve/6a5aad7ca262f2420d1bd4c2517b37b265db53eb/labelsTr/liver_100.nii.gz",
    "sha256": "ab2d2f85c5143fed2a14480fe172cf7956defab078431ac5315b1d36fefd548c",
    "license": "CC BY-SA 4.0",
    "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
    "homepage": "http://medicaldecathlon.com/",
    "paper": "https://doi.org/10.1038/s41467-022-30695-9",
}


def verify_file(path, expected):
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != expected:
        raise ValueError(f"Public fixture checksum mismatch: {path.name}")


def prepare_anatomy(image_path, label_path):
    verify_file(image_path, SAMPLES["CTLiver"]["sha256"])
    verify_file(label_path, LABEL_SOURCE["sha256"])
    image = sitk.ReadImage(str(image_path))
    labels = sitk.ReadImage(str(label_path))
    if image.GetSize() != labels.GetSize():
        raise ValueError("The CT and annotation dimensions differ")
    # NIfTI and NRRD encode this original geometry with slightly different floats.
    # Check the complete physical lattice, not just its centre/origin. No
    # registration, interpolation, or silent index-space alignment is performed.
    errors = [np.linalg.norm(np.array(image.TransformIndexToPhysicalPoint(index))
                             - labels.TransformIndexToPhysicalPoint(index))
              for index in itertools.product(*[(0, size - 1) for size in image.GetSize()])]
    if max(errors) > 0.001:
        raise ValueError("The CT and annotation physical grids differ by more than 0.001 mm")
    data = sitk.GetArrayFromImage(labels)
    if set(np.unique(data)) != {0, 1, 2}:
        raise ValueError("Expected background=0, liver=1 and tumour=2")
    bounds = []
    for axis in range(3):
        occupied = np.flatnonzero(np.any(data != 0, axis=tuple(i for i in range(3) if i != axis)))
        margin = int(np.ceil(12 / image.GetSpacing()[2 - axis]))
        bounds.append((max(0, int(occupied[0]) - margin),
                       min(data.shape[axis], int(occupied[-1]) + margin + 1)))
    slices = tuple(slice(start, stop) for start, stop in bounds)
    cropped_labels = np.array(data[slices], copy=True)
    del data
    start_ijk = [start for start, _ in bounds][::-1]
    size_ijk = [stop - start for start, stop in bounds][::-1]
    crop = sitk.RegionOfInterest(image, size_ijk, start_ijk)
    volume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "CTLiver — public liver_100")
    matrix = vtk.vtkMatrix4x4()
    ras = np.diag([-1.0, -1.0, 1.0])
    transform = np.eye(4)
    transform[:3, :3] = ras @ np.array(crop.GetDirection()).reshape(3, 3) @ np.diag(crop.GetSpacing())
    transform[:3, 3] = ras @ np.array(crop.GetOrigin())
    matrix.DeepCopy(transform.ravel())
    volume.SetIJKToRASMatrix(matrix)
    slicer.util.updateVolumeFromArray(volume, sitk.GetArrayFromImage(crop))
    volume.CreateDefaultDisplayNodes()
    volume.GetDisplayNode().AutoWindowLevelOff()
    volume.GetDisplayNode().SetWindowLevel(350, 70)
    segmentation = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "MSD liver and tumour annotations")
    segmentation.CreateDefaultDisplayNodes()
    segmentation.SetReferenceImageGeometryParameterFromVolumeNode(volume)
    counts = {}
    for value, name, color in ((1, "Liver tissue (MSD label 1)", (0.96, 0.57, 0.15)),
                                (2, "Liver tumour (MSD label 2)", (0.10, 0.78, 0.86))):
        mask = cropped_labels == value
        counts[name] = int(mask.sum())
        if counts[name] < 100:
            raise ValueError("An anatomical ROI is empty or unexpectedly small")
        if counts[name] != int(np.count_nonzero(sitk.GetArrayViewFromImage(labels) == value)):
            raise ValueError("The crop truncated an annotation")
        identifier = segmentation.GetSegmentation().AddEmptySegment(name, name, color)
        slicer.util.updateSegmentBinaryLabelmapFromArray(mask.astype(np.uint8), segmentation, identifier, volume)
    segmentation.CreateClosedSurfaceRepresentation()
    display = segmentation.GetDisplayNode()
    display.SetOpacity2DFill(0.18)
    display.SetOpacity2DOutline(1.0)
    display.SetOpacity3D(0.55)
    # Show a real slice through a substantial tumour region, never a fabricated ROI.
    tumour = cropped_labels == 2
    k = int(np.argmax(tumour.sum(axis=(1, 2))))
    j, i = np.argwhere(tumour[k]).mean(axis=0)
    centre = transform @ np.array([i, j, k, 1.0])
    info = {"image": SAMPLES["CTLiver"], "annotations": LABEL_SOURCE,
            "label_semantics": {"1": "liver tissue, excluding label-2 tumour", "2": "liver tumour"},
            "roi_voxels": counts, "grid_max_corner_error_mm": float(max(errors)),
            "crop_original_ijk_start": start_ijk, "crop_size_ijk": size_ijk,
            "crop_method": "native-lattice bounding crop, 12 mm margin; no resampling or intensity changes",
            "view_centre_ras": centre[:3].tolist()}
    return volume, segmentation, info


def capture(widget, path):
    slicer.app.processEvents()
    image = ctk.ctkWidgetsUtils.grabWidget(widget)
    if not image.save(str(path)):
        raise RuntimeError(f"Could not save local draft {path.name}")
    return {"file": path.name, "width": image.width(), "height": image.height(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}


def main():
    if slicer.util.mainWindow() is None or slicer.util.getNodesByClass("vtkMRMLVolumeNode"):
        raise RuntimeError("Use a fresh visible disposable Slicer process")
    root = Path(os.environ["PICTOLOGICS_ANATOMICAL_DEMO_OUTPUT"]).resolve()
    root.mkdir(parents=True, exist_ok=False)
    workload = Workloads(root, Path(os.environ["SLICERPICTOLOGICS_TEST_DEPENDENCY_PATH"]).resolve(strict=True))
    workload.report.update(kind="anatomical-documentation-draft", publication_approved=False)
    widget = workload.widget()
    try:
        volume, segmentation, source = prepare_anatomy(
            Path(os.environ["PICTOLOGICS_SAMPLE_CACHE"]) / "CTLiver.nrrd",
            Path(os.environ["PICTOLOGICS_ANATOMICAL_LABELS"]))
        workload.report["anatomy"] = source
        slicer.util.selectModule("PictologicsSlicer")
        widget.ui.inputVolumeSelector.setCurrentNode(volume)
        widget.ui.segmentationSelector.setCurrentNode(segmentation)
        widget.ui.wholeVolumeCheckBox.setChecked(False)
        widget.ui.cropCheckBox.setChecked(True)
        widget.ui.subjectIdLineEdit.setText("public-MSD-liver-100")
        widget.updateParameterNodeFromGUI()
        assert widget._selectedConfigurations() == ["standard_fbn_32"]
        widget.ui.configurationCollapsibleButton.collapsed = False
        widget.ui.outputCollapsibleButton.collapsed = True
        fit_panel(widget)
        layout = slicer.app.layoutManager()
        layout.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView)
        slicer.util.setSliceViewerLayers(background=volume)
        slicer.util.resetSliceViews()
        slicer.modules.markups.logic().JumpSlicesToLocation(*source["view_centre_ras"], True)
        layout.sliceWidget("Red").mrmlSliceNode().SetSliceVisible(True)
        slicer.util.resetThreeDViews()
        slicer.util.setDataProbeVisible(False)
        window = slicer.util.mainWindow()
        window.resize(1840, 1140)
        window.setWindowTitle("Pictologics — public CT / MSD liver and tumour annotations (research demo)")
        started = time.perf_counter()
        with MemorySampler() as memory, patch.object(widget.logic, "showTable"), patch.object(
            slicer.util, "confirmOkCancelDisplay", return_value=True
        ):
            widget.onRun()
            while widget._activeJob is not None:
                guard(memory, started)
                pump()
        table = widget.ui.outputTableSelector.currentNode()
        rows = widget.logic.rowsFromTable(table)
        counts = Counter(row["roi_name"] for row in rows)
        if len(rows) != 340 or set(counts) != set(source["roi_voxels"]) or any(row["status"] != "ok" for row in rows):
            raise RuntimeError("Expected 170 successfully calculated features for each anatomical ROI")
        widget.logic.exportTable(table, root / "features.csv")
        widget.logic.exportTable(table, root / "features.json")
        if not slicer.util.saveScene(str(root / "anatomical-demo.mrb")):
            raise RuntimeError("Could not export the draft scene before closing")
        for _ in range(30):
            pump()
        workflow = capture(window, root / "pictologics-workflow-anatomical-draft.png")
        widget.onBrowseResults()
        browser = widget._resultsBrowser
        browser.dialog.resize(1450, 950)
        browser.table.selectRow(0)
        for _ in range(20):
            pump()
        results = capture(browser.dialog, root / "pictologics-results-anatomical-draft.png")
        workload.report.update(success=True, rows=len(rows), rows_per_roi=dict(counts),
                               elapsed_seconds=time.perf_counter() - started,
                               captures=[workflow, results], memory=memory.summary())
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
