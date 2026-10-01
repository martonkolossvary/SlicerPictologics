"""Create a small CTLiver-derived Slicer example with two illustrative ROIs.

Use a fresh Slicer with --disable-settings --ignore-slicerrc. The first download
is the full ~279 MiB CTLiver sample; the prepared central slab is much smaller.
PICTOLOGICS_CT_DEMO_OUTPUT must be a new directory; optional
PICTOLOGICS_SAMPLE_CACHE may point at an existing checksum-verified sample cache.
No dependencies are installed, no screenshots are captured, and nothing uploads.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import numpy as np
import qt
import SampleData
import slicer
import vtk

sys.path.insert(0, str(Path(__file__).resolve().parent))
from workload_support import SAMPLES, demonstration_masks  # noqa: E402


def load_sample(name, cache):
    cache.mkdir(parents=True, exist_ok=True)
    slicer.mrmlScene.GetCacheManager().SetRemoteCacheDirectory(str(cache))
    item = SAMPLES[name]
    return SampleData.downloadFromURL(
        uris=slicer.util.TESTING_DATA_URL + "SHA256/" + item["sha256"],
        fileNames=item["filename"], nodeNames=name, checksums="SHA256:" + item["sha256"],
        loadFiles=True,
    )[0]


def ct_slab(source, *, slices=96, stride=2):
    """Nearest-neighbour decimation of a central CT slab, with correct geometry."""
    array = slicer.util.arrayFromVolume(source)
    if slices > array.shape[0] or slices < 32 or stride not in (1, 2):
        raise ValueError("Unsupported CT slab dimensions.")
    centre = round((array.shape[0] - 1) * 0.55)
    start = min(array.shape[0] - slices, max(0, centre - slices // 2))
    data = np.array(array[start:start + slices:stride, ::stride, ::stride], copy=True)
    volume = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "CTLiver — derived demonstration slab")
    matrix = vtk.vtkMatrix4x4()
    source.GetIJKToRASMatrix(matrix)
    transform = slicer.util.arrayFromVTKMatrix(matrix)
    origin = transform @ np.array([0, 0, start, 1])
    transform[:3, :3] *= stride
    transform[:3, 3] = origin[:3]
    matrix.DeepCopy(transform.ravel())
    volume.SetIJKToRASMatrix(matrix)
    slicer.util.updateVolumeFromArray(volume, data)
    volume.CreateDefaultDisplayNodes()
    volume.GetDisplayNode().AutoWindowLevelOff()
    volume.GetDisplayNode().SetWindowLevel(400, 60)
    volume.SetAttribute("Pictologics.DemoSource", SAMPLES["CTLiver"]["source"])
    volume.SetAttribute("Pictologics.DemoDerivation", json.dumps({"slice_start_k": start, "slice_stop_k": start + slices, "stride_ijk": stride,
        "method": "nearest-neighbour lattice decimation; not original-grid radiomics"}))
    return volume


def add_demo_rois(volume, *, sample="CTLiver"):
    array = slicer.util.arrayFromVolume(volume)
    masks, centres = demonstration_masks(array.shape, volume.GetSpacing(), sample=sample)
    segmentation = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode", "Two illustrative ROIs — not clinical labels")
    segmentation.CreateDefaultDisplayNodes()
    segmentation.SetReferenceImageGeometryParameterFromVolumeNode(volume)
    names = ["ROI A (demo)", "ROI B (demo)"]
    for name, color, mask in zip(names, ((0.96, 0.57, 0.15), (0.10, 0.78, 0.86)), masks, strict=True):
        identifier = segmentation.GetSegmentation().AddEmptySegment(name, name, color)
        slicer.util.updateSegmentBinaryLabelmapFromArray(mask, segmentation, identifier, volume)
    segmentation.GetDisplayNode().SetOpacity2DFill(0.18)
    segmentation.GetDisplayNode().SetOpacity2DOutline(1.0)
    return segmentation, {"roi_voxels": {name: int(mask.sum()) for name, mask in zip(names, masks, strict=True)},
                           "centres_ijk": centres, "roi_kind": "illustrative geometric masks, not clinical annotations"}


def save_fixture(volume, segmentation, output, info):
    output.mkdir(parents=True, exist_ok=False)
    for node, name in ((volume, "image.nrrd"), (segmentation, "segmentation.seg.nrrd")):
        if not slicer.util.saveNode(node, str(output / name)):
            raise RuntimeError(f"Could not save public demonstration {name}")
    (output / "source.json").write_text(json.dumps({**SAMPLES["CTLiver"], **info,
        "derived_dimensions_ijk": volume.GetImageData().GetDimensions(), "derived_spacing_ijk": volume.GetSpacing(),
        "derivation": json.loads(volume.GetAttribute("Pictologics.DemoDerivation"))}, indent=2) + "\n")


def create_demo():
    if slicer.util.getNodesByClass("vtkMRMLVolumeNode"):
        raise RuntimeError("Use a fresh Slicer process; existing images will not be changed.")
    output = Path(os.environ["PICTOLOGICS_CT_DEMO_OUTPUT"]).expanduser().resolve()
    if output.exists():
        raise RuntimeError("Choose a new CT demo output directory.")
    cache = Path(os.environ.get("PICTOLOGICS_SAMPLE_CACHE", str(output.parent / "sample-cache"))).resolve()
    source = load_sample("CTLiver", cache)
    volume = ct_slab(source)
    slicer.mrmlScene.RemoveNode(source)
    segmentation, info = add_demo_rois(volume)
    segmentation.CreateClosedSurfaceRepresentation()
    save_fixture(volume, segmentation, output, info)
    slicer.util.selectModule("PictologicsSlicer")
    widget = slicer.modules.pictologicsslicer.widgetRepresentation().self()
    widget.ui.inputVolumeSelector.setCurrentNode(volume)
    widget.ui.segmentationSelector.setCurrentNode(segmentation)
    widget.ui.wholeVolumeCheckBox.setChecked(False)
    widget.ui.cropCheckBox.setChecked(True)
    widget.ui.subjectIdLineEdit.setText("public-CTLiver-demo")
    widget.updateParameterNodeFromGUI()
    slicer.app.layoutManager().setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView)
    slicer.util.setSliceViewerLayers(background=volume)
    slicer.util.resetSliceViews()
    matrix = vtk.vtkMatrix4x4()
    volume.GetIJKToRASMatrix(matrix)
    centre = matrix.MultiplyPoint([*info["centres_ijk"][0], 1])
    slicer.modules.markups.logic().JumpSlicesToLocation(*centre[:3], True)
    slicer.util.resetThreeDViews()
    print("CT_DEMO_READY " + json.dumps(info), flush=True)


if __name__ == "__main__":
    qt.QTimer.singleShot(0, create_demo)
