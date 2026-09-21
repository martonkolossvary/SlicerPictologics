"""Create a deterministic, non-patient scene for genuine catalog screenshots.

Run in a separate Slicer process with --disable-settings --ignore-slicerrc and
--additional-module-paths <repo>/PictologicsSlicer <repo>/PictologicsCLI.
This creates an illustrative CT-like phantom, not realistic anatomy or clinical
test data. It never downloads data or installs dependencies. Start extraction
with the normal Run radiomics button after inspecting the prepared scene.
"""

from __future__ import annotations

import numpy as np
import qt
import slicer


def create_demo() -> None:
    if slicer.util.getNodesByClass("vtkMRMLVolumeNode"):
        raise RuntimeError("Use a fresh Slicer session; the demo will not replace existing data.")
    k, j, i = np.indices((80, 112, 128), dtype=np.float32)
    x, y, z = (i - 63.5) * 2.5, (j - 55.5) * 2.5, (k - 39.5) * 3.0
    rng = np.random.default_rng(20260921)
    body = (x / 147) ** 2 + (y / 105) ** 2 + (z / 250) ** 2 < 1
    lungs = (
        ((x - 59) / 47) ** 2 + ((y + 8) / 70) ** 2 + (z / 115) ** 2 < 1
    ) | (((x + 59) / 47) ** 2 + ((y + 8) / 70) ** 2 + (z / 115) ** 2 < 1)
    values = np.full(x.shape, -1000, dtype=np.float32)
    noise = rng.normal(0, 18, x.shape).astype(np.float32)
    values[body] = (35 + noise)[body]
    values[lungs] = (-780 + 2 * noise)[lungs]
    spine = (x / 16) ** 2 + ((y - 68) / 16) ** 2 < 1
    values[spine & body] = (650 + noise)[spine & body]
    for angle in np.linspace(0.2, 2.9, 8):
        for sign in (-1, 1):
            ribs = ((x - sign * 133 * np.sin(angle)) / 5) ** 2
            ribs += ((y - 93 * np.cos(angle)) / 5) ** 2
            values[(ribs < 1) & body] = (480 + noise)[(ribs < 1) & body]
    regions = [
        ("Region A", (0.95, 0.55, 0.13), ((x + 58) / 17) ** 2 + ((y + 12) / 15) ** 2 + (z / 22) ** 2 < 1),
        ("Region B", (0.12, 0.75, 0.85), ((x - 58) / 14) ** 2 + ((y + 5) / 18) ** 2 + (z / 20) ** 2 < 1),
    ]
    for index, (_, _, mask) in enumerate(regions):
        values[mask] = (65 + 35 * index + noise + 20 * np.sin(x / 4))[mask]

    volume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "Synthetic CT phantom")
    volume.SetSpacing(2.5, 2.5, 3.0)
    volume.SetOrigin(-63.5 * 2.5, -55.5 * 2.5, -39.5 * 3.0)
    slicer.util.updateVolumeFromArray(volume, values.astype(np.int16))
    volume.CreateDefaultDisplayNodes()
    volume.GetDisplayNode().AutoWindowLevelOff()
    volume.GetDisplayNode().SetWindowLevel(1300, -350)

    segmentation = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "Synthetic regions")
    segmentation.CreateDefaultDisplayNodes()
    segmentation.SetReferenceImageGeometryParameterFromVolumeNode(volume)
    for name, color, mask in regions:
        segment_id = segmentation.GetSegmentation().AddEmptySegment(name, name, color)
        slicer.util.updateSegmentBinaryLabelmapFromArray(mask.astype(np.uint8), segmentation, segment_id, volume)
    segmentation.CreateClosedSurfaceRepresentation()
    segmentation.GetDisplayNode().SetOpacity2DFill(0.2)
    segmentation.GetDisplayNode().SetOpacity2DOutline(1.0)

    slicer.util.setSliceViewerLayers(background=volume)
    slicer.util.resetThreeDViews()
    slicer.util.resetSliceViews()
    for name in slicer.app.layoutManager().sliceViewNames():
        slicer.app.layoutManager().sliceWidget(name).sliceLogic().SetSliceOffset(0)

    slicer.util.selectModule("PictologicsSlicer")
    widget = slicer.modules.pictologicsslicer.widgetRepresentation().self()
    inspection = widget.logic.inspectDependencies()
    if not inspection.satisfied:
        raise RuntimeError("Install the adopted Pictologics release before running this demo.")
    widget.ui.inputVolumeSelector.setCurrentNode(volume)
    widget.ui.segmentationSelector.setCurrentNode(segmentation)
    widget.ui.wholeVolumeCheckBox.setChecked(False)
    widget.ui.subjectIdLineEdit.setText("synthetic-demo")
    widget.updateParameterNodeFromGUI()
    widget.ui.configurationCollapsibleButton.collapsed = False
    widget.ui.outputCollapsibleButton.collapsed = True
    slicer.util.setDataProbeVisible(False)
    slicer.util.mainWindow().resize(1560, 1050)
    slicer.util.mainWindow().setWindowTitle("Pictologics — synthetic CT phantom (no patient data)")
    print("CATALOG_DEMO_READY: synthetic CT phantom; two regions; no patient data", flush=True)


if __name__ == "__main__":
    qt.QTimer.singleShot(0, create_demo)
