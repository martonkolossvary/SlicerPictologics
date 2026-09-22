"""Prepare public Slicer MRHead data with two illustrative radiomics ROIs.

Launch in a fresh, isolated Slicer process using --disable-settings and
--ignore-slicerrc. The built-in SampleData downloader verifies the public data's
checksum. It may download MRHead but never installs Pictologics or uploads data.
The two ellipsoidal masks are demonstration ROIs, not clinical annotations.
Run radiomics with the normal module button; no result values are fabricated.
Set PICTOLOGICS_DEMO_AUTORUN=1 to invoke that same module workflow on startup.
Keep screenshots in local-output until the maintainer approves publication.
"""

from __future__ import annotations

import json
import os
from collections import Counter

import numpy as np
import qt
import SampleData
import slicer
import vtk


def create_demo() -> None:
    if slicer.util.getNodesByClass("vtkMRMLVolumeNode"):
        raise RuntimeError("Use a fresh Slicer session; existing image data will not be replaced.")
    slicer.util.selectModule("PictologicsSlicer")
    widget = slicer.modules.pictologicsslicer.widgetRepresentation().self()
    inspection = widget.logic.inspectDependencies()
    if not inspection.satisfied:
        raise RuntimeError("Install the adopted Pictologics release before running this demo.")

    volume = SampleData.downloadSample("MRHead")
    volume.SetName("MRHead — public Slicer sample")
    array = slicer.util.arrayFromVolume(volume)
    bounds = [0.0] * 6
    volume.GetRASBounds(bounds)
    matrix = vtk.vtkMatrix4x4()
    volume.GetIJKToRASMatrix(matrix)
    k, j, i = (axis.astype(np.float32) for axis in np.ogrid[tuple(slice(n) for n in array.shape)])
    x, y, z = [
        matrix.GetElement(axis, 0) * i
        + matrix.GetElement(axis, 1) * j
        + matrix.GetElement(axis, 2) * k
        + matrix.GetElement(axis, 3)
        for axis in range(3)
    ]
    centre = (
        (bounds[0] + bounds[1]) / 2,
        (bounds[2] + bounds[3]) / 2,
        bounds[4] + 0.70 * (bounds[5] - bounds[4]),
    )
    segmentation = slicer.mrmlScene.AddNewNodeByClass(
        "vtkMRMLSegmentationNode", "Two demonstration ROIs"
    )
    segmentation.CreateDefaultDisplayNodes()
    segmentation.SetReferenceImageGeometryParameterFromVolumeNode(volume)
    regions = [
        ("Left ROI (demo)", (0.96, 0.57, 0.15), centre[0] - 27),
        ("Right ROI (demo)", (0.10, 0.78, 0.86), centre[0] + 27),
    ]
    voxel_counts = {}
    for name, color, centre_x in regions:
        mask = ((x - centre_x) / 18) ** 2 + ((y - centre[1]) / 25) ** 2 + (
            (z - centre[2]) / 18
        ) ** 2 < 1
        voxel_counts[name] = int(mask.sum())
        if voxel_counts[name] < 100:
            raise RuntimeError(f"Demonstration ROI is outside the sample image: {name}")
        segment_id = segmentation.GetSegmentation().AddEmptySegment(name, name, color)
        slicer.util.updateSegmentBinaryLabelmapFromArray(
            mask.astype(np.uint8), segmentation, segment_id, volume
        )
    segmentation.CreateClosedSurfaceRepresentation()
    segmentation.GetDisplayNode().SetOpacity2DFill(0.18)
    segmentation.GetDisplayNode().SetOpacity2DOutline(1.0)

    widget.ui.inputVolumeSelector.setCurrentNode(volume)
    widget.ui.segmentationSelector.setCurrentNode(segmentation)
    widget.ui.wholeVolumeCheckBox.setChecked(False)
    widget.ui.subjectIdLineEdit.setText("MRHead-demo")
    widget.updateParameterNodeFromGUI()
    widget.ui.configurationCollapsibleButton.collapsed = False
    widget.ui.outputCollapsibleButton.collapsed = True
    # Compact the demo's two short lists; this is only presentation, not saved settings.
    widget.ui.segmentListWidget.setMaximumHeight(80)
    widget.ui.standardConfigListWidget.setMaximumHeight(150)

    layout = slicer.app.layoutManager()
    layout.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView)
    slicer.util.setSliceViewerLayers(background=volume)
    slicer.util.resetSliceViews()
    layout.sliceWidget("Red").sliceLogic().SetSliceOffset(centre[2])
    layout.sliceWidget("Green").sliceLogic().SetSliceOffset(centre[1])
    layout.sliceWidget("Yellow").mrmlSliceNode().JumpSliceByCentering(
        centre[0] - 27, centre[1], centre[2]
    )
    layout.sliceWidget("Red").mrmlSliceNode().SetSliceVisible(True)
    slicer.util.resetThreeDViews()
    camera = (
        layout.threeDWidget(0)
        .threeDView()
        .renderWindow()
        .GetRenderers()
        .GetFirstRenderer()
        .GetActiveCamera()
    )
    camera.Azimuth(20)
    camera.Elevation(30)
    layout.threeDWidget(0).threeDView().scheduleRender()
    slicer.util.setDataProbeVisible(False)
    slicer.util.mainWindow().resize(1560, 1050)
    slicer.util.mainWindow().setWindowTitle(
        "Pictologics — public MRHead sample / demonstration ROIs"
    )
    print(
        "SAMPLE_DEMO_READY "
        + json.dumps(
            {
                "sample": "MRHead",
                "shape": array.shape,
                "bounds_ras": bounds,
                "centre_ras": centre,
                "roi_voxels": voxel_counts,
            }
        ),
        flush=True,
    )

    # Observe the real GUI workflow; never create or alter calculated values.
    completion_timer = qt.QTimer(slicer.util.mainWindow())
    completion_timer.setInterval(500)

    def review_completed_run() -> None:
        if widget._lastPayload is None:
            return
        completion_timer.stop()
        table = widget.ui.outputTableSelector.currentNode()
        rows = widget.logic.rowsFromTable(table)
        counts = Counter(row["roi_name"] for row in rows)
        if set(counts) != {name for name, _, _ in regions}:
            raise RuntimeError(
                f"Both demonstration regions must have actual results: {dict(counts)}"
            )
        print(
            "SAMPLE_DEMO_RESULTS "
            + json.dumps(
                {
                    "rows": len(rows),
                    "rows_per_roi": dict(counts),
                    "statuses": dict(Counter(row["status"] for row in rows)),
                }
            ),
            flush=True,
        )
        layout.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView)

    completion_timer.connect("timeout()", review_completed_run)
    completion_timer.start()
    if os.environ.get("PICTOLOGICS_DEMO_AUTORUN") == "1":
        qt.QTimer.singleShot(0, widget.onRun)


if __name__ == "__main__":
    qt.QTimer.singleShot(0, create_demo)
