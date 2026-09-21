"""In-Slicer integration fixture for geometry-sensitive Pictologics tests.

This test deliberately imports Slicer APIs and is registered only with CTest.  It
must not be collected by the normal-Python pytest suite.
"""

from __future__ import annotations

import json
import math
import os
import platform
import shutil
import sys
import tempfile
import time
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import qt
import slicer
import vtk
from PictologicsLib.dependencies import inspect_target
from PictologicsLib.results import (
    LONG_RESULT_COLUMNS,
    RESULT_PAYLOAD_SCHEMA_VERSION,
    load_result_payload,
    validate_result_payload,
)

from PictologicsSlicer import (
    EXTENSION_VERSION,
    PictologicsSlicerLogic,
    PictologicsSlicerWidget,
)

ARRAY_SHAPE_KJI = (14, 16, 18)
SEGMENT_NAME = "Central cuboid"
SUBJECT_ID = "pictologics-integration-subject"
RUN_REAL_CLI_TEST_ENV = "SLICERPICTOLOGICS_RUN_REAL_CLI_TEST"
TEST_DEPENDENCY_PATH_ENV = "SLICERPICTOLOGICS_TEST_DEPENDENCY_PATH"
CLI_TIMEOUT_SECONDS = 10 * 60
CLI_CANCELLATION_GRACE_SECONDS = 60


class IsolatedPictologicsSlicerLogic(PictologicsSlicerLogic):
    """Redirect persistent and cache state into a test-owned directory."""

    isolated_cache_root: Path | None = None

    @classmethod
    def dependencyRoot(cls) -> Path:
        if cls.isolated_cache_root is None:
            raise RuntimeError("The integration-test cache root has not been configured.")
        return cls.isolated_cache_root / "persistent-data"


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


@dataclass(frozen=True)
class CliTerminalState:
    status: int
    status_text: str
    error_text: str
    failed: bool
    cancelled: bool
    completed: bool


@dataclass(frozen=True)
class CliRunObservation:
    terminal_state: CliTerminalState
    worker_pids: frozenset[int]


def _matrix4x4(values: np.ndarray) -> vtk.vtkMatrix4x4:
    matrix = vtk.vtkMatrix4x4()
    slicer.util.updateVTKMatrixFromArray(matrix, values)
    return matrix


def _scene_node_ids() -> set[str]:
    return {
        str(node.GetID())
        for index in range(slicer.mrmlScene.GetNumberOfNodes())
        if (node := slicer.mrmlScene.GetNthNode(index)) is not None and node.GetID() is not None
    }


def _remove_scene_nodes_not_in(baseline_ids: set[str]) -> None:
    nodes = [
        slicer.mrmlScene.GetNthNode(index) for index in range(slicer.mrmlScene.GetNumberOfNodes())
    ]
    for node in reversed(nodes):
        if (
            node is not None
            and node.GetID() is not None
            and str(node.GetID()) not in baseline_ids
            and node.GetScene() == slicer.mrmlScene
        ):
            slicer.mrmlScene.RemoveNode(node)


def _pictologics_modules_in_main_process() -> set[str]:
    return {
        name for name in sys.modules if name == "pictologics" or name.startswith("pictologics.")
    }


def _qualified_dependency_target(logic: PictologicsSlicerLogic) -> tuple[Path, str]:
    requirement = logic.pictologicsRequirement()
    explicit_path = os.environ.get(TEST_DEPENDENCY_PATH_ENV, "").strip()
    if explicit_path:
        inspection = inspect_target(explicit_path, requirement)
        source = f"{TEST_DEPENDENCY_PATH_ENV}={explicit_path}"
    else:
        production_logic = PictologicsSlicerLogic()
        inspection = production_logic.inspectDependencies()
        source = f"active extension target {inspection.target}"

    if not inspection.satisfied or inspection.ambiguous or inspection.installed_version is None:
        versions = ", ".join(inspection.installed_versions) or "none"
        raise RuntimeError(
            f"{RUN_REAL_CLI_TEST_ENV}=1 requires one existing private {requirement} "
            f"environment, but {source} contains: {versions}. This test never installs "
            "or downloads dependencies."
        )
    return inspection.target, inspection.installed_version


def _cli_terminal_state(cli_node) -> CliTerminalState | None:
    status = int(cli_node.GetStatus())
    status_text = str(cli_node.GetStatusString() or "")
    failed = bool(status & int(cli_node.ErrorsMask))
    cancelled = status == int(cli_node.Cancelled)
    completed = bool(status & int(cli_node.Completed))
    if not (failed or cancelled or completed):
        return None
    return CliTerminalState(
        status=status,
        status_text=status_text,
        error_text=str(cli_node.GetErrorText() or "").strip(),
        failed=failed,
        cancelled=cancelled,
        completed=completed,
    )


def _pump_slicer_events() -> None:
    slicer.app.processEvents(qt.QEventLoop.ExcludeUserInputEvents)
    time.sleep(0.01)


def _worker_marker_pid(logic: PictologicsSlicerLogic, job: dict[str, Any]) -> int | None:
    return logic._markerPID(Path(job["work_dir"]) / ".worker-active")


def _wait_for_worker_release(
    logic: PictologicsSlicerLogic,
    job: dict[str, Any],
    *,
    timeout_seconds: float,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while logic.jobWorkerIsAlive(job):
        if time.monotonic() >= deadline:
            raise TimeoutError(
                "Pictologics worker did not release its staging directory after the "
                "CLI reached a terminal state."
            )
        _pump_slicer_events()


def _wait_for_cli_terminal(
    cli_node,
    logic: PictologicsSlicerLogic,
    job: dict[str, Any],
    *,
    timeout_seconds: float,
) -> CliRunObservation:
    """Wait for the asynchronous CLI while closing observer and launch races."""

    terminal_state: list[CliTerminalState] = []
    worker_pids: set[int] = set()

    def sample() -> None:
        pid = _worker_marker_pid(logic, job)
        if pid is not None and logic.processIsAlive(pid):
            worker_pids.add(pid)
        state = _cli_terminal_state(cli_node)
        if state is not None:
            terminal_state[:] = [state]

    def on_modified(caller=None, event=None) -> None:
        del caller, event
        sample()

    observer_tag = cli_node.AddObserver(vtk.vtkCommand.ModifiedEvent, on_modified)
    timed_out = False
    try:
        # The process may finish between startJob() and observer registration.
        sample()
        deadline = time.monotonic() + timeout_seconds
        while not terminal_state:
            if time.monotonic() >= deadline:
                timed_out = True
                break
            _pump_slicer_events()
            sample()

        if timed_out:
            if cli_node.IsBusy():
                cli_node.Cancel()
            cancelled_at = time.monotonic()
            cancel_deadline = cancelled_at + CLI_CANCELLATION_GRACE_SECONDS
            while time.monotonic() < cancel_deadline:
                _pump_slicer_events()
                sample()
                released = not logic.jobWorkerIsAlive(job)
                if (
                    terminal_state
                    and not cli_node.IsBusy()
                    and released
                    and time.monotonic() - cancelled_at >= 2.0
                ):
                    break
            raise TimeoutError(
                f"Pictologics CLI exceeded {timeout_seconds:.0f} seconds and was cancelled."
            )
    finally:
        cli_node.RemoveObserver(observer_tag)

    _wait_for_worker_release(
        logic,
        job,
        timeout_seconds=CLI_CANCELLATION_GRACE_SECONDS,
    )
    return CliRunObservation(
        terminal_state=terminal_state[0],
        worker_pids=frozenset(worker_pids),
    )


def _ensure_cli_released(cli_node, logic, job: dict[str, Any]) -> None:
    state = _cli_terminal_state(cli_node)
    if state is not None and not logic.jobWorkerIsAlive(job):
        return
    if cli_node.IsBusy():
        cli_node.Cancel()
    cancelled_at = time.monotonic()
    deadline = cancelled_at + CLI_CANCELLATION_GRACE_SECONDS
    while time.monotonic() < deadline:
        _pump_slicer_events()
        state = _cli_terminal_state(cli_node)
        if (
            state is not None
            and not cli_node.IsBusy()
            and not logic.jobWorkerIsAlive(job)
            and time.monotonic() - cancelled_at >= 2.0
        ):
            return
    raise TimeoutError(
        "Could not observe terminal CLI state and worker release after cancellation."
    )


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
            f"Expected one imported segment, but Slicer created {len(segment_ids)}: {segment_ids}"
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

    # Class-scoped on purpose: if the opt-in async CLI test cannot prove its worker was
    # released, every later test in this shared Slicer process is skipped so it cannot
    # interfere with a still-running worker that owns its staging directory.
    retained_async_failure: str | None = None

    def setUp(self) -> None:
        if type(self).retained_async_failure is not None:
            self.skipTest(type(self).retained_async_failure)
        slicer.mrmlScene.Clear()
        self.retain_temporary_directory = False
        # A manual temporary root can be deliberately retained if a timed-out worker
        # still owns its staged inputs; TemporaryDirectory's finalizer cannot.
        self.temporary_directory = Path(tempfile.mkdtemp(prefix="SlicerPictologics-integration-"))
        self.addCleanup(self._cleanup_test_state)
        self.cache_root = self.temporary_directory / "extension-cache"
        IsolatedPictologicsSlicerLogic.isolated_cache_root = self.cache_root
        self.logic = IsolatedPictologicsSlicerLogic()
        self.fixture = create_oblique_segmentation_fixture()

    def _cleanup_test_state(self) -> None:
        IsolatedPictologicsSlicerLogic.isolated_cache_root = None
        if self.retain_temporary_directory:
            return
        slicer.mrmlScene.Clear()
        shutil.rmtree(self.temporary_directory, ignore_errors=True)

    def test_dependency_root_is_persistent_and_runtime_scoped(self) -> None:
        dependency_root = PictologicsSlicerLogic.dependencyRoot().resolve()
        application_data = Path(
            str(
                qt.QStandardPaths.writableLocation(
                    qt.QStandardPaths.AppLocalDataLocation
                )
            )
        ).resolve()
        managed_cache = Path(str(slicer.app.cachePath)).resolve()

        self.assertTrue(dependency_root.is_relative_to(application_data))
        self.assertFalse(dependency_root.is_relative_to(managed_cache))
        self.assertIn("SlicerPictologics", dependency_root.parts)
        self.assertIn(sys.implementation.cache_tag, dependency_root.name)
        self.assertIn(platform.machine(), dependency_root.name)

    def test_module_identity_and_approved_icon(self) -> None:
        module = slicer.modules.pictologicsslicer
        self.assertIsNotNone(getattr(slicer.modules, "pictologicscli", None))
        self.assertEqual(module.title, "Pictologics")
        self.assertEqual(list(module.categories), ["Informatics"])
        icon_path = Path(module.path).parent / "Resources/Icons/PictologicsSlicer.png"
        expected = qt.QIcon(str(icon_path))
        self.assertFalse(expected.isNull())
        self.assertFalse(module.icon.isNull())
        # Verify the actual discovered module, not just that the PNG can be decoded.
        # This also catches accidental reversion to Slicer's SVG-first lookup.
        for size in (16, 32, 128, 256):
            with self.subTest(size=size):
                actual_image = module.icon.pixmap(size, size).toImage()
                expected_image = expected.pixmap(size, size).toImage()
                self.assertEqual(actual_image.size(), expected_image.size())
                for y in range(0, size, max(1, size // 32)):
                    for x in range(0, size, max(1, size // 32)):
                        self.assertEqual(actual_image.pixel(x, y), expected_image.pixel(x, y))
                self.assertEqual((int(actual_image.pixel(0, 0)) >> 24) & 0xFF, 0)

    def test_cli_progress_preserves_slicer_percentages(self) -> None:
        class ProgressNode:
            def __init__(self, percentage: int):
                self.percentage = percentage

            def GetProgress(self) -> int:
                return self.percentage

        for percentage in (0, 1, 25, 50, 75, 100):
            with self.subTest(percentage=percentage):
                self.assertEqual(
                    PictologicsSlicerWidget._cliProgressPercent(ProgressNode(percentage)),
                    percentage,
                )

        class ProgressUI:
            def __init__(self) -> None:
                self.progressBar = qt.QProgressBar()

        class ProgressHarness:
            _beginCliProgress = PictologicsSlicerWidget._beginCliProgress
            _restoreCliProgress = PictologicsSlicerWidget._restoreCliProgress

            def __init__(self) -> None:
                self.ui = ProgressUI()
                self._cliProgressIndeterminate = False

        harness = ProgressHarness()
        harness._beginCliProgress(1)
        self.assertEqual(harness.ui.progressBar.minimum, 0)
        self.assertEqual(harness.ui.progressBar.maximum, 0)
        self.assertTrue(harness._cliProgressIndeterminate)

        harness._restoreCliProgress(100)
        self.assertEqual(harness.ui.progressBar.minimum, 0)
        self.assertEqual(harness.ui.progressBar.maximum, 100)
        self.assertEqual(harness.ui.progressBar.value, 100)
        self.assertFalse(harness._cliProgressIndeterminate)

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
        self.assertEqual(fixture.volume_node.GetTransformNodeID(), fixture.transform_node.GetID())
        self.assertEqual(
            fixture.segmentation_node.GetTransformNodeID(), fixture.transform_node.GetID()
        )

    def test_cuboid_segment_exports_in_reference_volume_geometry(self) -> None:
        fixture = self.fixture
        self.assertIsNone(slicer.mrmlScene.GetNodeByID(fixture.removed_source_labelmap_id))
        segment_ids = PictologicsSlicerLogic.segmentIDs(fixture.segmentation_node)
        self.assertEqual(segment_ids, [fixture.segment_id])
        segment = fixture.segmentation_node.GetSegmentation().GetSegment(fixture.segment_id)
        self.assertIsNotNone(segment)
        self.assertEqual(segment.GetName(), SEGMENT_NAME)

        reference_role = slicer.vtkMRMLSegmentationNode.GetReferenceImageGeometryReferenceRole()
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
        self.assertEqual(exported_labelmap.GetTransformNodeID(), fixture.transform_node.GetID())

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
        requirement = logic.pictologicsRequirement()
        pinned_version = str(next(iter(requirement.specifier)).version)

        source_scene_ids = _scene_node_ids()
        source_volume_id = str(fixture.volume_node.GetID())
        source_segmentation_id = str(fixture.segmentation_node.GetID())
        source_transform_id = str(fixture.transform_node.GetID())
        source_transform_matrix = slicer.util.arrayFromTransformMatrix(fixture.transform_node)
        source_internal_mask = slicer.util.arrayFromSegmentInternalBinaryLabelmap(
            fixture.segmentation_node, fixture.segment_id
        ).copy()
        source_segment_ids = logic.segmentIDs(fixture.segmentation_node)
        source_segment_name = (
            fixture.segmentation_node.GetSegmentation().GetSegment(fixture.segment_id).GetName()
        )
        reference_role = slicer.vtkMRMLSegmentationNode.GetReferenceImageGeometryReferenceRole()
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
            installedVersion=pinned_version,
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
            self.assertEqual(Path(job["provenance_path"]), work_dir / "provenance.json")
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
            self.assertEqual(manifest["pictologics_requirement"], str(requirement))
            self.assertEqual(
                manifest["metadata"],
                {
                    "numba_cache_path": str(logic.privatePaths()["numba_cache"]),
                    "pictologics_version_at_submission": pinned_version,
                    "input_volume_node_id": source_volume_id,
                },
            )
            self.assertEqual(
                manifest["output"],
                {
                    "results_path": str((work_dir / "results.json").resolve()),
                    "provenance_path": str((work_dir / "provenance.json").resolve()),
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
                        "metadata": {"segmentation_name": str(fixture.segmentation_node.GetName())},
                    },
                ],
            )

            # prepareJob must remove its clone, exported labelmap, storage, display,
            # and color nodes before returning.
            self.assertEqual(_scene_node_ids(), source_scene_ids)
            self.assertIs(slicer.mrmlScene.GetNodeByID(source_volume_id), fixture.volume_node)
            self.assertIs(
                slicer.mrmlScene.GetNodeByID(source_segmentation_id),
                fixture.segmentation_node,
            )
            self.assertIs(slicer.mrmlScene.GetNodeByID(source_transform_id), fixture.transform_node)

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
            self.assertEqual(logic.segmentIDs(fixture.segmentation_node), source_segment_ids)
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
            source_mask_in_reference_geometry = slicer.util.arrayFromSegmentBinaryLabelmap(
                fixture.segmentation_node,
                fixture.segment_id,
                fixture.volume_node,
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
            # loadVolume never attaches a parent transform, so these are only sanity
            # checks; the actual transform hardening is verified by the IJKToRAS matrix
            # equality against (transform_to_parent @ ijk_to_ras) below.
            self.assertIsNone(staged_image.GetParentTransformNode())
            self.assertIsNone(staged_mask.GetParentTransformNode())

            np.testing.assert_array_equal(
                slicer.util.arrayFromVolume(staged_image), fixture.expected_image
            )
            staged_mask_array = slicer.util.arrayFromVolume(staged_mask)
            np.testing.assert_array_equal(staged_mask_array > 0, fixture.expected_mask > 0)
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
            staged_image_geometry = slicer.util.arrayFromVTKMatrix(staged_image_ijk_to_ras)
            staged_mask_geometry = slicer.util.arrayFromVTKMatrix(staged_mask_ijk_to_ras)
            np.testing.assert_allclose(
                staged_image_geometry,
                expected_world_ijk_to_ras,
                rtol=0.0,
                # NIfTI stores geometry as float32; ~12 mm translations lose ~1e-6
                # absolute precision, so keep a float32-safe tolerance.
                atol=1e-4,
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

    @unittest.skipUnless(
        os.environ.get(RUN_REAL_CLI_TEST_ENV) == "1",
        f"Set {RUN_REAL_CLI_TEST_ENV}=1 to run the existing-dependency CLI gate.",
    )
    def test_real_async_cli_result_validation_and_table_commit(self) -> None:
        fixture = self.fixture
        logic = self.logic
        dependency_path, installed_version = _qualified_dependency_target(logic)
        source_scene_ids = _scene_node_ids()
        imported_modules_before = _pictologics_modules_in_main_process()
        self.assertEqual(
            imported_modules_before,
            set(),
            "Pictologics was already imported in Slicer's main Python interpreter.",
        )

        job: dict[str, Any] | None = None
        cli_node = None
        table_node = None
        cli_node_id: str | None = None
        table_node_id: str | None = None
        work_dir: Path | None = None
        cleanup_failures: list[str] = []
        previous_bytecode_setting = os.environ.get("PYTHONDONTWRITEBYTECODE")
        os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
        try:
            job = logic.prepareJob(
                inputVolumeNode=fixture.volume_node,
                segmentationNode=fixture.segmentation_node,
                selectedSegmentIDs=[fixture.segment_id],
                includeWholeVolume=True,
                standardConfigurations=["standard_fbn_32"],
                customConfigurationPath=None,
                subjectID=SUBJECT_ID,
                installedVersion=installed_version,
                dependencyPath=dependency_path,
            )
            work_dir = Path(job["work_dir"])
            self.assertEqual(_scene_node_ids(), source_scene_ids)

            cli_node = logic.startJob(job)
            self.assertIsNotNone(cli_node)
            cli_node_id = str(cli_node.GetID())
            self.assertIn(cli_node_id, _scene_node_ids())

            observation = _wait_for_cli_terminal(
                cli_node,
                logic,
                job,
                timeout_seconds=CLI_TIMEOUT_SECONDS,
            )
            terminal = observation.terminal_state
            self.assertTrue(
                terminal.completed,
                f"CLI did not complete: {terminal.status_text} ({terminal.status})",
            )
            self.assertFalse(
                terminal.failed,
                f"CLI failed: {terminal.status_text}: {terminal.error_text}",
            )
            self.assertFalse(terminal.cancelled)
            self.assertFalse(cli_node.IsBusy())
            self.assertTrue(
                observation.worker_pids,
                "Never observed a live worker PID; cannot confirm the extraction ran "
                "in a separate process from Slicer.",
            )
            for worker_pid in observation.worker_pids:
                self.assertGreater(worker_pid, 0)
                self.assertNotEqual(worker_pid, os.getpid())

            result_path = Path(job["output_path"])
            provenance_path = Path(job["provenance_path"])
            self.assertTrue(result_path.is_file())
            self.assertTrue(provenance_path.is_file())
            # The worker must have released the job (its PID is gone); its marker file
            # is removed best-effort, so assert the semantic release, not the file.
            self.assertFalse(logic.jobWorkerIsAlive(job))
            self.assertTrue((work_dir / ".owner-active").is_file())
            self.assertEqual(list(work_dir.glob(".results.json.*.tmp")), [])
            self.assertEqual(list(work_dir.glob(".provenance.json.*.tmp")), [])

            payload = validate_result_payload(load_result_payload(result_path))
            self.assertEqual(payload["schema_version"], RESULT_PAYLOAD_SCHEMA_VERSION)
            self.assertEqual(payload["run_id"], job["manifest"]["run_id"])
            self.assertEqual(payload.get("errors"), [])
            self.assertTrue(payload["rows"])

            sidecar = json.loads(provenance_path.read_text(encoding="utf-8"))
            self.assertEqual(
                sidecar,
                {
                    "schema_version": RESULT_PAYLOAD_SCHEMA_VERSION,
                    "run_id": payload["run_id"],
                    "provenance": payload["provenance"],
                    "errors": payload["errors"],
                },
            )

            provenance = payload["provenance"]
            self.assertEqual(provenance["input_manifest"], job["manifest"])
            self.assertEqual(Path(provenance["dependency_path"]), dependency_path.resolve())
            self.assertEqual(
                provenance["numba_cache_path"],
                job["manifest"]["metadata"]["numba_cache_path"],
            )
            self.assertEqual(
                provenance["configuration_sha256"],
                job["manifest"]["configuration_sha256"],
            )
            run_metadata = provenance["run_metadata"]
            self.assertEqual(run_metadata["subject_id"], SUBJECT_ID)
            self.assertEqual(run_metadata["image_name"], fixture.volume_node.GetName())
            self.assertEqual(run_metadata["extension_version"], EXTENSION_VERSION)
            self.assertEqual(run_metadata["pictologics_version"], installed_version)
            self.assertEqual(
                run_metadata["pictologics_requirement"],
                str(logic.pictologicsRequirement()),
            )

            effective_configuration = provenance["effective_configuration"]
            self.assertEqual(set(effective_configuration["configs"]), {"standard_fbn_32"})
            self.assertEqual(effective_configuration["pictologics_version"], installed_version)
            feature_catalog = provenance["feature_catalog"]
            self.assertTrue(feature_catalog)
            self.assertEqual(
                {record["config"] for record in feature_catalog},
                {"standard_fbn_32"},
            )
            processing_logs = provenance["processing_logs"]
            self.assertEqual(
                [record["roi_id"] for record in processing_logs],
                ["whole-volume", fixture.segment_id],
            )

            rows = payload["rows"]
            self.assertEqual(
                {row["roi_id"] for row in rows},
                {"whole-volume", fixture.segment_id},
            )
            self.assertEqual({row["configuration"] for row in rows}, {"standard_fbn_32"})
            self.assertEqual({row["pictologics_version"] for row in rows}, {installed_version})
            self.assertEqual({row["extension_version"] for row in rows}, {EXTENSION_VERSION})
            self.assertEqual({row["subject_id"] for row in rows}, {SUBJECT_ID})
            self.assertEqual(
                {row["image_name"] for row in rows},
                {str(fixture.volume_node.GetName())},
            )
            self.assertEqual(
                {
                    row["pictologics_ibsi_code"]
                    for row in rows
                    if row["ibsi_code"] == "BC2M"
                },
                {"BC2M_10", "BC2M_90"},
            )
            self.assertTrue(
                all(
                    row["pictologics_feature_name"]
                    == f"{row['configuration']}__{row['feature_key']}"
                    for row in rows
                )
            )

            catalog_identities = {
                (
                    record["config"],
                    str(record.get("family", "unknown")),
                    str(record.get("feature_name", record["feature_key"])),
                    str(record["feature_key"]),
                    str(record.get("ibsi_code", "")),
                    str(record.get("pictologics_ibsi_code", "")),
                    str(record.get("pictologics_feature_name", "")),
                    str(record.get("preprocessing_sequence") or ""),
                )
                for record in feature_catalog
            }
            rows_by_roi = {
                roi_id: [row for row in rows if row["roi_id"] == roi_id]
                for roi_id in ("whole-volume", fixture.segment_id)
            }
            for roi_id, roi_rows in rows_by_roi.items():
                with self.subTest(roi_id=roi_id):
                    self.assertGreaterEqual(len(roi_rows), len(feature_catalog))
                    self.assertTrue(
                        any(
                            row["status"] == "ok"
                            and row["value"] is not None
                            and math.isfinite(float(row["value"]))
                            for row in roi_rows
                        )
                    )
                    row_identities = {
                        (
                            row["configuration"],
                            row["feature_family"],
                            row["feature_name"],
                            row["feature_key"],
                            row["ibsi_code"],
                            row["pictologics_ibsi_code"],
                            row["pictologics_feature_name"],
                            row["preprocessing_sequence"],
                        )
                        for row in roi_rows
                    }
                    self.assertTrue(catalog_identities.issubset(row_identities))

            # The mask must actually constrain the ROI: the whole-volume region and the
            # smaller cuboid segment cannot yield identical features, or the worker
            # ignored the mask. (Numerical worker-vs-Pictologics parity is covered
            # out-of-process by scripts/geometry_parity_check.py; Pictologics cannot be
            # imported into Slicer's interpreter here without breaking NumPy isolation,
            # as asserted above.)
            def _finite_values(target_roi: str) -> dict[str, float]:
                return {
                    row["feature_key"]: float(row["value"])
                    for row in rows
                    if row["roi_id"] == target_roi
                    and row["status"] == "ok"
                    and row["value"] is not None
                    and math.isfinite(float(row["value"]))
                }

            whole_volume_values = _finite_values("whole-volume")
            segment_values = _finite_values(fixture.segment_id)
            shared_feature_keys = set(whole_volume_values) & set(segment_values)
            self.assertTrue(shared_feature_keys)
            self.assertTrue(
                any(
                    not math.isclose(
                        whole_volume_values[key],
                        segment_values[key],
                        rel_tol=1e-6,
                        abs_tol=1e-9,
                    )
                    for key in shared_feature_keys
                ),
                "Whole-volume and segment ROIs produced identical feature values; the "
                "segmentation mask was not applied.",
            )

            table_node = logic.commitRows(
                None,
                rows,
                append=False,
                payload=payload,
                manifest=job["manifest"],
            )
            table_node_id = str(table_node.GetID())
            table = table_node.GetTable()
            self.assertEqual(
                tuple(
                    str(table.GetColumnName(index)) for index in range(table.GetNumberOfColumns())
                ),
                tuple(LONG_RESULT_COLUMNS),
            )
            self.assertEqual(table.GetNumberOfRows(), len(rows))
            for column_name in LONG_RESULT_COLUMNS:
                column = table.GetColumnByName(column_name)
                expected_type = "vtkDoubleArray" if column_name == "value" else "vtkStringArray"
                self.assertTrue(column.IsA(expected_type))
            self.assertEqual(logic.rowsFromTable(table_node), rows)

            self.assertEqual(
                table_node.GetAttribute("Pictologics.ResultSchemaVersion"),
                str(RESULT_PAYLOAD_SCHEMA_VERSION),
            )
            self.assertEqual(table_node.GetAttribute("Pictologics.LastRunID"), payload["run_id"])
            self.assertEqual(
                table_node.GetAttribute("Pictologics.ConfigurationSHA256"),
                job["manifest"]["configuration_sha256"],
            )
            self.assertEqual(
                table_node.GetAttribute("SlicerPictologics.ExtensionVersion"),
                EXTENSION_VERSION,
            )
            self.assertEqual(
                json.loads(table_node.GetAttribute("Pictologics.ProvenanceJSON")),
                provenance,
            )
            self.assertEqual(json.loads(table_node.GetAttribute("Pictologics.ErrorsJSON")), [])
            expected_run_record = {
                "run_id": payload["run_id"],
                "configuration_sha256": job["manifest"]["configuration_sha256"],
                "provenance": provenance,
                "errors": [],
            }
            history = logic.provenanceHistory(table_node, required=True)
            self.assertEqual(history, [expected_run_record])
            self.assertEqual(
                logic.featureDictionary(history),
                sorted(
                    feature_catalog,
                    key=lambda record: (record["config"], record["feature_key"]),
                ),
            )
            self.assertEqual(_pictologics_modules_in_main_process(), imported_modules_before)
        finally:
            active_exception = sys.exc_info()[1]
            worker_retained = False
            if cli_node is not None and job is not None:
                release_failed = False
                try:
                    _ensure_cli_released(cli_node, logic, job)
                except Exception as exc:
                    release_failed = True
                    cleanup_failures.append(str(exc))
                try:
                    cli_busy = bool(cli_node.IsBusy())
                except RuntimeError:
                    cli_busy = release_failed
                if release_failed or cli_busy or logic.jobWorkerIsAlive(job):
                    worker_retained = True
                    retained_message = (
                        "An asynchronous Pictologics job could not be proven released; "
                        "its CLI node and staging directory were retained at "
                        f"{job['work_dir']}. Remove that directory only after the "
                        "worker exits."
                    )
                    cleanup_failures.append(retained_message)
                    self.retain_temporary_directory = True
                    type(self).retained_async_failure = retained_message
                else:
                    try:
                        if cli_node.GetScene() == slicer.mrmlScene:
                            slicer.mrmlScene.RemoveNode(cli_node)
                    except RuntimeError:
                        pass
            if table_node is not None:
                try:
                    if table_node.GetScene() == slicer.mrmlScene:
                        slicer.mrmlScene.RemoveNode(table_node)
                except RuntimeError:
                    pass
            if job is not None and not worker_retained:
                try:
                    logic.cleanupJob(job)
                except Exception as exc:
                    cleanup_failures.append(f"Could not remove job staging: {exc}")
            if previous_bytecode_setting is None:
                os.environ.pop("PYTHONDONTWRITEBYTECODE", None)
            else:
                os.environ["PYTHONDONTWRITEBYTECODE"] = previous_bytecode_setting
            if cleanup_failures:
                cleanup_message = "; ".join(cleanup_failures)
                if active_exception is not None:
                    note = f"Step 4 cleanup: {cleanup_message}"
                    add_note = getattr(active_exception, "add_note", None)
                    if callable(add_note):
                        add_note(note)
                    else:  # Python < 3.11 has no Exception.add_note
                        print(note, file=sys.stderr)
                else:
                    self.fail(cleanup_message)

        self.assertIsNotNone(work_dir)
        self.assertFalse(work_dir.exists())
        self.assertEqual(list(logic.jobsRoot().glob("job-*")), [])
        if cli_node_id is not None:
            self.assertIsNone(slicer.mrmlScene.GetNodeByID(cli_node_id))
        if table_node_id is not None:
            self.assertIsNone(slicer.mrmlScene.GetNodeByID(table_node_id))
        self.assertEqual(_scene_node_ids(), source_scene_ids)
        self.assertEqual(_pictologics_modules_in_main_process(), imported_modules_before)


if __name__ == "__main__":
    program = unittest.main(exit=False)
    slicer.util.exit(0 if program.result.wasSuccessful() else 1)
