"""In-Slicer integration fixture for geometry-sensitive Pictologics tests.

This test deliberately imports Slicer APIs and is registered only with CTest.  It
must not be collected by the normal-Python pytest suite.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import slicer
import vtk

from PictologicsSlicer import PictologicsSlicerLogic

ARRAY_SHAPE_KJI = (14, 16, 18)
SEGMENT_NAME = "Central cuboid"
SUBJECT_ID = "pictologics-integration-subject"


class IsolatedPictologicsSlicerLogic(PictologicsSlicerLogic):
    """Redirect mutable extension cache state into a test-owned directory."""

    isolated_cache_root: Path | None = None

    @classmethod
    def cacheRoot(cls) -> Path:
        if cls.isolated_cache_root is None:
            raise RuntimeError("The integration-test cache root has not been configured.")
        return cls.isolated_cache_root


@dataclass(frozen=True)
class ObliqueSegmentationFixture:
    """MRML nodes and immutable expectations shared by the integration tests."""

    volume_node: Any
    segmentation_node: Any
    transform_node: Any
    segment_id: str
    expected_image: np.ndarray
    expected_mask: np.ndarray
    expected_ijk_to_ras: np.ndarray
    expected_transform_to_parent: np.ndarray
    removed_source_labelmap_id: str


def _matrix4x4(values: np.ndarray) -> vtk.vtkMatrix4x4:
    matrix = vtk.vtkMatrix4x4()
    slicer.util.updateVTKMatrixFromArray(matrix, values)
    return matrix


def _scene_node_ids() -> set[str]:
    return {
        str(node.GetID())
        for index in range(slicer.mrmlScene.GetNumberOfNodes())
        if (node := slicer.mrmlScene.GetNthNode(index)) is not None
        and node.GetID() is not None
    }


def _remove_scene_nodes_not_in(baseline_ids: set[str]) -> None:
    nodes = [
        slicer.mrmlScene.GetNthNode(index)
        for index in range(slicer.mrmlScene.GetNumberOfNodes())
    ]
    for node in reversed(nodes):
        if (
            node is not None
            and node.GetID() is not None
            and str(node.GetID()) not in baseline_ids
            and node.GetScene() == slicer.mrmlScene
        ):
            slicer.mrmlScene.RemoveNode(node)


def _expected_ijk_to_ras() -> np.ndarray:
    """Return an oblique, right-handed IJK-to-RAS matrix with unequal spacing."""

    angle = math.radians(18.0)
    cosine = math.cos(angle)
    sine = math.sin(angle)
    spacing_i, spacing_j, spacing_k = (0.7, 1.3, 2.5)
    return np.array(
        [
            [spacing_i * cosine, -spacing_j * sine, 0.0, 12.0],
            [spacing_i * sine, spacing_j * cosine, 0.0, -8.0],
            [0.0, 0.0, spacing_k, 4.0],
            [0.0, 0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )


def _expected_transform_to_parent() -> np.ndarray:
    """Return a deterministic non-identity rigid transform."""

    angle = math.radians(-11.0)
    cosine = math.cos(angle)
    sine = math.sin(angle)
    return np.array(
        [
            [cosine, 0.0, sine, 6.0],
            [0.0, 1.0, 0.0, -3.0],
            [-sine, 0.0, cosine, 2.0],
            [0.0, 0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )


def create_oblique_segmentation_fixture() -> ObliqueSegmentationFixture:
    """Create a deterministic volume, cuboid segment, and shared linear transform."""

    voxel_count = int(np.prod(ARRAY_SHAPE_KJI))
    image = np.arange(voxel_count, dtype=np.float32).reshape(ARRAY_SHAPE_KJI)
    image = (image * np.float32(0.25) - np.float32(300.0)).copy()

    mask = np.zeros(ARRAY_SHAPE_KJI, dtype=np.uint8)
    mask[3:11, 4:13, 5:15] = 1

    ijk_to_ras = _expected_ijk_to_ras()
    volume = slicer.mrmlScene.AddNewNodeByClass(
        "vtkMRMLScalarVolumeNode", "Pictologics integration image"
    )
    slicer.util.updateVolumeFromArray(volume, image)
    volume.SetIJKToRASMatrix(_matrix4x4(ijk_to_ras))

    source_labelmap = slicer.mrmlScene.AddNewNodeByClass(
        "vtkMRMLLabelMapVolumeNode", "Pictologics integration source mask"
    )
    slicer.util.updateVolumeFromArray(source_labelmap, mask)
    source_labelmap.SetIJKToRASMatrix(_matrix4x4(ijk_to_ras))

    segmentation = slicer.mrmlScene.AddNewNodeByClass(
        "vtkMRMLSegmentationNode", "Pictologics integration segmentation"
    )
    segmentation.SetReferenceImageGeometryParameterFromVolumeNode(volume)
    imported = slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(
        source_labelmap, segmentation
    )
    if not imported:
        raise RuntimeError("Slicer could not import the deterministic cuboid labelmap.")

    segment_ids = PictologicsSlicerLogic.segmentIDs(segmentation)
    if len(segment_ids) != 1:
        raise RuntimeError(
            "Expected one imported segment, "
            f"but Slicer created {len(segment_ids)}: {segment_ids}"
        )
    segment_id = segment_ids[0]
    segment = segmentation.GetSegmentation().GetSegment(segment_id)
    if segment is None:
        raise RuntimeError(f"Imported segment is unavailable: {segment_id}")
    segment.SetName(SEGMENT_NAME)

    # The labelmap is only a construction aid.  Keeping it out of the returned
    # fixture makes later node-leak assertions precise.
    source_labelmap_id = str(source_labelmap.GetID())
    slicer.mrmlScene.RemoveNode(source_labelmap)

    transform_to_parent = _expected_transform_to_parent()
    transform = slicer.mrmlScene.AddNewNodeByClass(
        "vtkMRMLLinearTransformNode", "Pictologics integration transform"
    )
    transform.SetMatrixTransformToParent(_matrix4x4(transform_to_parent))
    volume.SetAndObserveTransformNodeID(transform.GetID())
    segmentation.SetAndObserveTransformNodeID(transform.GetID())

    return ObliqueSegmentationFixture(
        volume_node=volume,
        segmentation_node=segmentation,
        transform_node=transform,
        segment_id=segment_id,
        expected_image=image,
        expected_mask=mask,
        expected_ijk_to_ras=ijk_to_ras,
        expected_transform_to_parent=transform_to_parent,
        removed_source_labelmap_id=source_labelmap_id,
    )


class PictologicsSlicerIntegrationTest(unittest.TestCase):
    """Validate the deterministic MRML fixture and NIfTI staging boundary."""

    def setUp(self) -> None:
        slicer.mrmlScene.Clear()
        self.temporary_directory = tempfile.TemporaryDirectory(
            prefix="SlicerPictologics-integration-"
        )
        self.cache_root = Path(self.temporary_directory.name) / "extension-cache"
        IsolatedPictologicsSlicerLogic.isolated_cache_root = self.cache_root
        self.logic = IsolatedPictologicsSlicerLogic()
        self.fixture = create_oblique_segmentation_fixture()

    def tearDown(self) -> None:
        slicer.mrmlScene.Clear()
        IsolatedPictologicsSlicerLogic.isolated_cache_root = None
        self.temporary_directory.cleanup()

    def test_oblique_volume_and_shared_linear_transform(self) -> None:
        fixture = self.fixture

        np.testing.assert_array_equal(
            slicer.util.arrayFromVolume(fixture.volume_node), fixture.expected_image
        )
        self.assertEqual(
            fixture.volume_node.GetImageData().GetDimensions(),
            tuple(reversed(ARRAY_SHAPE_KJI)),
        )

        actual_ijk_to_ras = vtk.vtkMatrix4x4()
        fixture.volume_node.GetIJKToRASMatrix(actual_ijk_to_ras)
        np.testing.assert_allclose(
            slicer.util.arrayFromVTKMatrix(actual_ijk_to_ras),
            fixture.expected_ijk_to_ras,
            rtol=0.0,
            atol=1e-12,
        )
        spacing = np.linalg.norm(fixture.expected_ijk_to_ras[:3, :3], axis=0)
        self.assertEqual(len(set(np.round(spacing, decimals=12))), 3)
        self.assertNotEqual(fixture.expected_ijk_to_ras[0, 1], 0.0)
        self.assertNotEqual(fixture.expected_ijk_to_ras[1, 0], 0.0)

        self.assertTrue(fixture.transform_node.IsTransformToWorldLinear())
        np.testing.assert_allclose(
            slicer.util.arrayFromTransformMatrix(fixture.transform_node),
            fixture.expected_transform_to_parent,
            rtol=0.0,
            atol=1e-12,
        )
        self.assertFalse(
            np.allclose(
                fixture.expected_transform_to_parent,
                np.eye(4),
                rtol=0.0,
                atol=1e-12,
            )
        )
        self.assertEqual(
            fixture.volume_node.GetTransformNodeID(), fixture.transform_node.GetID()
        )
        self.assertEqual(
            fixture.segmentation_node.GetTransformNodeID(), fixture.transform_node.GetID()
        )

    def test_cuboid_segment_exports_in_reference_volume_geometry(self) -> None:
        fixture = self.fixture
        self.assertIsNone(
            slicer.mrmlScene.GetNodeByID(fixture.removed_source_labelmap_id)
        )
        segment_ids = PictologicsSlicerLogic.segmentIDs(fixture.segmentation_node)
        self.assertEqual(segment_ids, [fixture.segment_id])
        segment = fixture.segmentation_node.GetSegmentation().GetSegment(
            fixture.segment_id
        )
        self.assertIsNotNone(segment)
        self.assertEqual(segment.GetName(), SEGMENT_NAME)

        reference_role = (
            slicer.vtkMRMLSegmentationNode.GetReferenceImageGeometryReferenceRole()
        )
        reference_node = fixture.segmentation_node.GetNodeReference(reference_role)
        self.assertIsNotNone(reference_node)
        self.assertEqual(reference_node.GetID(), fixture.volume_node.GetID())

        selected_ids = vtk.vtkStringArray()
        selected_ids.InsertNextValue(fixture.segment_id)
        exported_labelmap = slicer.mrmlScene.AddNewNodeByClass(
            "vtkMRMLLabelMapVolumeNode", "Pictologics integration exported mask"
        )
        exported = slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(
            fixture.segmentation_node,
            selected_ids,
            exported_labelmap,
            fixture.volume_node,
        )
        self.assertTrue(exported)
        self.assertIsNotNone(exported_labelmap.GetImageData())

        exported_mask = slicer.util.arrayFromVolume(exported_labelmap)
        np.testing.assert_array_equal(exported_mask > 0, fixture.expected_mask > 0)
        self.assertEqual(int(np.count_nonzero(exported_mask)), 8 * 9 * 10)
        self.assertEqual(
            exported_labelmap.GetImageData().GetDimensions(),
            tuple(reversed(ARRAY_SHAPE_KJI)),
        )

        exported_ijk_to_ras = vtk.vtkMatrix4x4()
        exported_labelmap.GetIJKToRASMatrix(exported_ijk_to_ras)
        np.testing.assert_allclose(
            slicer.util.arrayFromVTKMatrix(exported_ijk_to_ras),
            fixture.expected_ijk_to_ras,
            rtol=0.0,
            atol=1e-12,
        )
        self.assertEqual(
            exported_labelmap.GetTransformNodeID(), fixture.transform_node.GetID()
        )

        # Exporting the segment must not mutate either persistent source node.
        np.testing.assert_array_equal(
            slicer.util.arrayFromVolume(fixture.volume_node), fixture.expected_image
        )
        self.assertEqual(
            fixture.segmentation_node.GetTransformNodeID(), fixture.transform_node.GetID()
        )

    def test_prepare_job_stages_hardened_nifti_and_cleans_scene(self) -> None:
        fixture = self.fixture
        logic = self.logic
        dependency_path = self.cache_root / "dependency-target"
        dependency_path.mkdir(parents=True)

        source_scene_ids = _scene_node_ids()
        source_volume_id = str(fixture.volume_node.GetID())
        source_segmentation_id = str(fixture.segmentation_node.GetID())
        source_transform_id = str(fixture.transform_node.GetID())
        source_transform_matrix = slicer.util.arrayFromTransformMatrix(
            fixture.transform_node
        )
        source_internal_mask = slicer.util.arrayFromSegmentInternalBinaryLabelmap(
            fixture.segmentation_node, fixture.segment_id
        ).copy()
        source_segment_ids = logic.segmentIDs(fixture.segmentation_node)
        source_segment_name = (
            fixture.segmentation_node.GetSegmentation()
            .GetSegment(fixture.segment_id)
            .GetName()
        )
        reference_role = (
            slicer.vtkMRMLSegmentationNode.GetReferenceImageGeometryReferenceRole()
        )
        source_reference_node = fixture.segmentation_node.GetNodeReference(reference_role)
        self.assertIsNotNone(source_reference_node)
        source_reference_id = str(source_reference_node.GetID())

        job = logic.prepareJob(
            inputVolumeNode=fixture.volume_node,
            segmentationNode=fixture.segmentation_node,
            selectedSegmentIDs=[fixture.segment_id],
            includeWholeVolume=True,
            standardConfigurations=["standard_fbn_32"],
            customConfigurationPath=None,
            subjectID=SUBJECT_ID,
            installedVersion="0.5.0",
            dependencyPath=dependency_path,
        )
        work_dir = Path(job["work_dir"])
        image_path = work_dir / "image.nii.gz"
        mask_path = work_dir / "roi-0000.nii.gz"
        manifest_path = work_dir / "job-manifest.json"

        try:
            self.assertTrue(work_dir.is_dir())
            self.assertEqual(work_dir.parent, logic.jobsRoot())
            self.assertEqual(
                {path.name for path in work_dir.iterdir()},
                {
                    ".owner-active",
                    "image.nii.gz",
                    "job-manifest.json",
                    "roi-0000.nii.gz",
                },
            )
            self.assertEqual(
                (work_dir / ".owner-active").read_text(encoding="utf-8"),
                f"pid={os.getpid()}\n",
            )
            for staged_path in (image_path, mask_path, manifest_path):
                with self.subTest(staged_path=staged_path.name):
                    self.assertTrue(staged_path.is_file())
                    self.assertGreater(staged_path.stat().st_size, 0)
            self.assertFalse(Path(job["output_path"]).exists())
            self.assertFalse(Path(job["provenance_path"]).exists())
            self.assertEqual(Path(job["manifest_path"]), manifest_path)
            self.assertEqual(Path(job["output_path"]), work_dir / "results.json")
            self.assertEqual(
                Path(job["provenance_path"]), work_dir / "provenance.json"
            )
            self.assertEqual(Path(job["dependency_path"]), dependency_path.resolve())

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest, job["manifest"])
            self.assertEqual(manifest["schema_version"], 1)
            self.assertEqual(manifest["subject_id"], SUBJECT_ID)
            self.assertEqual(manifest["image"]["path"], str(image_path.resolve()))
            self.assertEqual(manifest["image"]["name"], fixture.volume_node.GetName())
            self.assertEqual(
                manifest["configuration_document"],
                {
                    "standard_configurations": ["standard_fbn_32"],
                    "custom_configuration_path": None,
                    "custom_configuration_sha256": None,
                    "warmup": True,
                },
            )
            self.assertEqual(manifest["pictologics_requirement"], "pictologics==0.5.0")
            self.assertEqual(
                manifest["metadata"],
                {
                    "numba_cache_path": str(logic.privatePaths()["numba_cache"]),
                    "pictologics_version_at_submission": "0.5.0",
                    "input_volume_node_id": source_volume_id,
                },
            )
            self.assertEqual(
                manifest["output"],
                {
                    "results_path": str((work_dir / "results.json").resolve()),
                    "provenance_path": str(
                        (work_dir / "provenance.json").resolve()
                    ),
                },
            )
            self.assertEqual(
                manifest["rois"],
                [
                    {
                        "roi_id": "whole-volume",
                        "roi_name": "Whole volume",
                        "roi_source": "whole-volume",
                        "mask_path": None,
                    },
                    {
                        "roi_id": fixture.segment_id,
                        "roi_name": SEGMENT_NAME,
                        "roi_source": "segmentation",
                        "mask_path": str(mask_path.resolve()),
                        "metadata": {
                            "segmentation_name": str(
                                fixture.segmentation_node.GetName()
                            )
                        },
                    },
                ],
            )

            # prepareJob must remove its clone, exported labelmap, storage, display,
            # and color nodes before returning.
            self.assertEqual(_scene_node_ids(), source_scene_ids)
            self.assertIs(
                slicer.mrmlScene.GetNodeByID(source_volume_id), fixture.volume_node
            )
            self.assertIs(
                slicer.mrmlScene.GetNodeByID(source_segmentation_id),
                fixture.segmentation_node,
            )
            self.assertIs(
                slicer.mrmlScene.GetNodeByID(source_transform_id), fixture.transform_node
            )

            np.testing.assert_array_equal(
                slicer.util.arrayFromVolume(fixture.volume_node), fixture.expected_image
            )
            source_ijk_to_ras = vtk.vtkMatrix4x4()
            fixture.volume_node.GetIJKToRASMatrix(source_ijk_to_ras)
            np.testing.assert_allclose(
                slicer.util.arrayFromVTKMatrix(source_ijk_to_ras),
                fixture.expected_ijk_to_ras,
                rtol=0.0,
                atol=1e-12,
            )
            self.assertEqual(
                fixture.volume_node.GetTransformNodeID(), fixture.transform_node.GetID()
            )
            self.assertEqual(
                fixture.segmentation_node.GetTransformNodeID(),
                fixture.transform_node.GetID(),
            )
            np.testing.assert_allclose(
                slicer.util.arrayFromTransformMatrix(fixture.transform_node),
                source_transform_matrix,
                rtol=0.0,
                atol=1e-12,
            )
            np.testing.assert_array_equal(
                slicer.util.arrayFromSegmentInternalBinaryLabelmap(
                    fixture.segmentation_node, fixture.segment_id
                ),
                source_internal_mask,
            )
            self.assertEqual(
                logic.segmentIDs(fixture.segmentation_node), source_segment_ids
            )
            self.assertEqual(
                fixture.segmentation_node.GetSegmentation()
                .GetSegment(fixture.segment_id)
                .GetName(),
                source_segment_name,
            )
            self.assertEqual(
                fixture.segmentation_node.GetNodeReference(reference_role).GetID(),
                source_reference_id,
            )
            source_mask_in_reference_geometry = (
                slicer.util.arrayFromSegmentBinaryLabelmap(
                    fixture.segmentation_node,
                    fixture.segment_id,
                    fixture.volume_node,
                )
            )
            np.testing.assert_array_equal(
                source_mask_in_reference_geometry > 0, fixture.expected_mask > 0
            )
            self.assertEqual(_scene_node_ids(), source_scene_ids)

            inspection_baseline_ids = _scene_node_ids()
            staged_image = slicer.util.loadVolume(
                str(image_path), {"name": "Staged integration image", "show": False}
            )
            staged_mask = slicer.util.loadVolume(
                str(mask_path),
                {
                    "name": "Staged integration mask",
                    "labelmap": True,
                    "show": False,
                },
            )
            self.assertIsNotNone(staged_image)
            self.assertIsNotNone(staged_mask)
            self.assertIsNone(staged_image.GetParentTransformNode())
            self.assertIsNone(staged_mask.GetParentTransformNode())

            np.testing.assert_array_equal(
                slicer.util.arrayFromVolume(staged_image), fixture.expected_image
            )
            staged_mask_array = slicer.util.arrayFromVolume(staged_mask)
            np.testing.assert_array_equal(
                staged_mask_array > 0, fixture.expected_mask > 0
            )
            self.assertEqual(set(np.unique(staged_mask_array)), {0, 1})
            self.assertEqual(int(np.count_nonzero(staged_mask_array)), 8 * 9 * 10)
            self.assertEqual(
                staged_image.GetImageData().GetDimensions(),
                tuple(reversed(ARRAY_SHAPE_KJI)),
            )
            self.assertEqual(
                staged_mask.GetImageData().GetDimensions(),
                tuple(reversed(ARRAY_SHAPE_KJI)),
            )

            expected_world_ijk_to_ras = (
                fixture.expected_transform_to_parent @ fixture.expected_ijk_to_ras
            )
            staged_image_ijk_to_ras = vtk.vtkMatrix4x4()
            staged_mask_ijk_to_ras = vtk.vtkMatrix4x4()
            staged_image.GetIJKToRASMatrix(staged_image_ijk_to_ras)
            staged_mask.GetIJKToRASMatrix(staged_mask_ijk_to_ras)
            staged_image_geometry = slicer.util.arrayFromVTKMatrix(
                staged_image_ijk_to_ras
            )
            staged_mask_geometry = slicer.util.arrayFromVTKMatrix(staged_mask_ijk_to_ras)
            np.testing.assert_allclose(
                staged_image_geometry,
                expected_world_ijk_to_ras,
                rtol=0.0,
                atol=1e-5,
            )
            np.testing.assert_allclose(
                staged_mask_geometry,
                staged_image_geometry,
                rtol=0.0,
                atol=1e-6,
            )

            _remove_scene_nodes_not_in(inspection_baseline_ids)
            self.assertEqual(_scene_node_ids(), inspection_baseline_ids)
        finally:
            logic.cleanupJob(job)

        self.assertFalse(work_dir.exists())
        self.assertTrue(logic.jobsRoot().is_dir())
        self.assertEqual(list(logic.jobsRoot().iterdir()), [])


if __name__ == "__main__":
    program = unittest.main(exit=False)
    slicer.util.exit(0 if program.result.wasSuccessful() else 1)
