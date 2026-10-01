"""In-Slicer integration fixture for geometry-sensitive Pictologics tests.

This test deliberately imports Slicer APIs and is registered only with CTest.  It
must not be collected by the normal-Python pytest suite.
"""

from __future__ import annotations

import errno
import json
import math
import os
import platform
import shutil
import struct
import sys
import tempfile
import time
import unittest
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

import numpy as np
import qt
import slicer
import vtk
from PictologicsLib.dependencies import activate_dependency_target, inspect_target
from PictologicsLib.inline_config import (
    ROI_REFINEMENT_DEFAULTS,
    build_inline_configuration_document,
    default_inline_state,
    filter_defaults,
    preset_configuration_document,
)
from PictologicsLib.memory import BYTES_PER_VOXEL, largest_voxel_count
from PictologicsLib.persistence import SNAPSHOT_ATTRIBUTE, WARNING_ATTRIBUTE, decode_values
from PictologicsLib.profiles import build_profile
from PictologicsLib.results import (
    LONG_RESULT_COLUMNS,
    RESULT_PAYLOAD_SCHEMA_VERSION,
    WIDE_ID_COLUMNS,
    load_result_payload,
    validate_result_payload,
)

import PictologicsSlicer as gui_module
from PictologicsSlicer import (
    EXTENSION_VERSION,
    DependencyInstallDeclined,
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


def _qt_with(**replacements: Any) -> SimpleNamespace:
    """Return the qt module with some dialog classes replaced, for dialog tests."""

    names = {name: getattr(qt, name) for name in dir(qt) if not name.startswith("__")}
    return SimpleNamespace(**{**names, **replacements})


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

    def test_results_table_is_visible_after_creating_table_layout(self) -> None:
        layout = slicer.app.layoutManager()
        viewport = None
        if layout is None:
            # --no-main-window still needs real table-view creation, not a mock.
            viewport = qt.QWidget()
            layout = slicer.qSlicerLayoutManager(viewport)
            layout.setMRMLScene(slicer.mrmlScene)
            slicer.app.setLayoutManager(layout)
            self.addCleanup(viewport.deleteLater)
            self.addCleanup(slicer.app.setLayoutManager, None)
        original_layout = layout.layout
        self.addCleanup(layout.setLayout, original_layout)
        layout.setLayout(slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpView)
        first = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", "First results")
        second = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", "Second results")
        for table in (first, second):
            column = vtk.vtkDoubleArray()
            column.SetName("value")
            column.InsertNextValue(42.0)
            table.AddColumn(column)
            self.logic.showTable(table)
            slicer.app.processEvents()
            self.assertEqual(layout.layout, slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpTableView)
            view = layout.tableWidget(0).tableView()
            self.assertEqual(view.mrmlTableNode(), table)
            self.assertEqual(view.mrmlTableNode().GetNumberOfRows(), 1)
            # qMRMLTableModel may also include an editable column-header row.
            self.assertGreaterEqual(view.model().rowCount(), 1)

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

    def _feedback_widget(self):
        # Exercise Slicer's actual, application-owned module widget. A manually
        # created Python-owned top-level widget has different PythonQt teardown.
        with patch.object(gui_module, "PictologicsSlicerLogic", IsolatedPictologicsSlicerLogic):
            widget = slicer.modules.pictologicsslicer.widgetRepresentation().self()
        widget.logic = self.logic
        widget.initializeParameterNode()
        self.addCleanup(widget._handoffActiveJobCleanup, cancel=True)
        widget.ui.inputVolumeSelector.setCurrentNode(self.fixture.volume_node)
        # Whole-volume extraction is off by default; these tests need a runnable region.
        widget.ui.wholeVolumeCheckBox.setChecked(True)
        return widget

    def test_whole_volume_is_off_by_default(self) -> None:
        parameter_node = self.logic.getParameterNode()
        self.logic.setDefaultParameters(parameter_node)
        self.assertEqual(parameter_node.GetParameter(gui_module.PARAM_WHOLE_VOLUME), "false")

    def test_diagnostics_preview_copy_and_inspection_failure_are_privacy_safe(self) -> None:
        widget = self._feedback_widget()
        secret = "PRIVATE-PATIENT-ALICE"
        widget.ui.subjectIdLineEdit.setText(secret)
        widget.ui.statusLabel.setText(f"Worker failed: /Users/{secret}/scan.nrrd")
        widget._diagnosticRun = {"state": "failed", "roi_count": 2, "elapsed_seconds": 7,
                                 "image_name": secret, "roi_name": secret}
        widget._recordDiagnosticOperation("run", "failed", "worker_failed")
        clipboard = Mock()
        with patch.object(qt.QApplication, "clipboard", return_value=clipboard), patch.object(
            widget.logic, "probeDependencyEnvironment", side_effect=AssertionError("No probe")
        ), patch.object(widget.logic, "ensureDependencies", side_effect=AssertionError("No install")):
            widget.ui.refreshDiagnosticsButton.click()
            clipboard.setText.assert_not_called()
            preview = widget.ui.diagnosticsTextEdit.toPlainText()
            self.assertTrue(widget.ui.diagnosticsTextEdit.readOnly)
            self.assertNotIn(secret, preview)
            self.assertNotIn("/Users/", preview)
            report = json.loads(preview)
            self.assertEqual(report["dependency"]["metadata_status"], "missing")
            self.assertEqual(report["last_run"]["roi_count"], 2)
            self.assertEqual(report["last_operation"]["failure_code"], "worker_failed")
            self.assertEqual(report["runtime"]["extension_version"], EXTENSION_VERSION)
            self.assertNotEqual(report["runtime"]["qt_version"], "unknown")
            # A changed state must not silently replace the report being reviewed.
            widget._recordDiagnosticOperation("export", "completed")
            widget.ui.copyDiagnosticsButton.click()
            clipboard.setText.assert_called_once_with(preview)
            with patch.object(widget.logic, "inspectDependencies", side_effect=OSError(secret)):
                widget.ui.refreshDiagnosticsButton.click()
            report = json.loads(widget.ui.diagnosticsTextEdit.toPlainText())
            self.assertEqual(report["dependency"]["metadata_status"], "inspection_failed")
            self.assertNotIn(secret, widget._diagnosticsPreview)
            self.assertEqual(report["last_operation"]["outcome"], "completed")

    def test_diagnostics_distinguishes_metadata_states_without_importing_package(self) -> None:
        widget = self._feedback_widget()
        for status, installed, satisfied, ambiguous in (
            ("compatible", True, True, False), ("incompatible", True, False, False),
            ("ambiguous", True, False, True), ("missing", False, False, False),
        ):
            inspection = SimpleNamespace(installed_version="0.5.1" if installed else None,
                                         installed=installed, satisfied=satisfied, ambiguous=ambiguous)
            with self.subTest(status=status), patch.object(widget.logic, "inspectDependencies", return_value=inspection):
                widget.onRefreshDiagnostics()
                self.assertEqual(json.loads(widget._diagnosticsPreview)["dependency"]["metadata_status"], status)
        self.assertNotIn("pictologics", sys.modules)

    @staticmethod
    def _fake_distribution(target, version):
        metadata = target / f"pictologics-{version}.dist-info" / "METADATA"
        metadata.parent.mkdir(parents=True)
        metadata.write_text(f"Metadata-Version: 2.1\nName: pictologics\nVersion: {version}\n", encoding="utf-8")
        (target / "sentinel.txt").write_text("Test-owned environment", encoding="utf-8")

    @patch("slicer.packaging.pip_install")
    def test_dependency_failures_preserve_active_environment_and_restart_reuses_it(self, installer) -> None:
        # Inject failures only into synthetic candidates. No wheel downloads or
        # changes to the normal Slicer dependency directory occur in this test.
        version = next(iter(self.logic.pictologicsRequirement().specifier)).version
        for phase in ("network", "interrupted", "metadata", "import_probe", "jit_probe", "activation"):
            with self.subTest(phase=phase):
                IsolatedPictologicsSlicerLogic.isolated_cache_root = self.cache_root / phase
                paths = self.logic.privatePaths()
                active = paths["environments_root"] / "previous"
                self._fake_distribution(active, version)
                activate_dependency_target(paths["cache_root"], active)
                pointer_before = paths["active_pointer"].read_bytes()
                files_before = {p.relative_to(active): p.read_bytes() for p in active.rglob("*") if p.is_file()}

                def install(arguments, phase=phase, **kwargs):
                    staging = Path(arguments[arguments.index("--target") + 1])
                    self._fake_distribution(staging, "0.0.0" if phase == "metadata" else version)
                    if phase == "network":
                        raise OSError("Synthetic offline installation")
                    if phase == "interrupted":
                        raise KeyboardInterrupt("Synthetic interruption")

                def probe(target, expected, *, warmup, phase=phase):
                    if phase == "import_probe" and not warmup or phase == "jit_probe" and warmup:
                        raise RuntimeError("Synthetic candidate probe failure")

                replace = os.replace

                def activate_replace(source, destination, phase=phase, paths=paths, replace=replace):
                    if phase == "activation" and Path(destination) == paths["active_pointer"]:
                        raise PermissionError("Synthetic pointer write failure")
                    return replace(source, destination)

                installer.side_effect = install
                with patch.object(slicer.util, "confirmOkCancelDisplay", return_value=True), patch.object(
                    self.logic, "probeDependencyEnvironment", side_effect=probe
                ), patch.object(os, "replace", side_effect=activate_replace), self.assertRaises(
                    (OSError, RuntimeError, ValueError, KeyboardInterrupt)
                ):
                    self.logic.ensureDependencies(forceUpgrade=True)
                self.assertEqual(paths["active_pointer"].read_bytes(), pointer_before)
                self.assertEqual({p.relative_to(active): p.read_bytes() for p in active.rglob("*") if p.is_file()}, files_before)
                self.assertEqual(list(paths["environments_root"].iterdir()), [active])
                self.assertFalse(list(paths["cache_root"].glob(".*.tmp")))
                installer.reset_mock()
                installer.side_effect = AssertionError("Restart must not reinstall")
                restarted = IsolatedPictologicsSlicerLogic()
                self.assertEqual(restarted.ensureDependencies(forceUpgrade=False).target, active)
                installer.assert_not_called()

    @patch("slicer.packaging.pip_install")
    def test_fresh_install_failure_decline_and_retry_recover(self, installer) -> None:
        version = next(iter(self.logic.pictologicsRequirement().specifier)).version
        with patch.object(slicer.util, "confirmOkCancelDisplay", return_value=False), self.assertRaises(DependencyInstallDeclined):
            self.logic.ensureDependencies(forceUpgrade=False)
        installer.assert_not_called()
        installer.side_effect = OSError("Synthetic unavailable network")
        with patch.object(slicer.util, "confirmOkCancelDisplay", return_value=True), self.assertRaises(OSError):
            self.logic.ensureDependencies(forceUpgrade=False)
        paths = self.logic.privatePaths()
        self.assertFalse(paths["active_pointer"].exists())
        self.assertEqual(list(paths["environments_root"].iterdir()), [])

        def install(arguments, **kwargs):
            self._fake_distribution(Path(arguments[arguments.index("--target") + 1]), version)

        installer.side_effect = install
        with patch.object(slicer.util, "confirmOkCancelDisplay", return_value=True), patch.object(
            self.logic, "probeDependencyEnvironment"
        ) as probe:
            inspection = self.logic.ensureDependencies(forceUpgrade=False)
        self.assertTrue(inspection.satisfied)
        self.assertEqual([call.kwargs["warmup"] for call in probe.call_args_list], [False, True])
        self.assertEqual(self.logic.inspectDependencies().target, inspection.target)

    def test_failed_or_invalid_worker_output_preserves_completed_results(self) -> None:
        widget = self._feedback_widget()
        table = self._persistence_table([math.pi, -0.0])
        widget.ui.outputTableSelector.setCurrentNode(table)
        before = table.GetAttribute(SNAPSHOT_ATTRIBUTE)
        history = table.GetAttribute("Pictologics.ProvenanceHistoryJSON")
        for outcome in ("failed", "cancelled", "missing", "malformed", "mismatched"):
            with self.subTest(outcome=outcome):
                work = self.logic.jobsRoot() / f"job-{outcome}"
                work.mkdir(parents=True)
                output = work / "results.json"
                if outcome == "malformed":
                    output.write_text("{incomplete", encoding="utf-8")
                elif outcome == "mismatched":
                    output.write_text(json.dumps({"schema_version": RESULT_PAYLOAD_SCHEMA_VERSION,
                        "run_id": "other", "rows": [], "provenance": {}, "errors": []}), encoding="utf-8")
                node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLCommandLineModuleNode")
                widget._cliNode = node
                widget._activeJob = {"work_dir": str(work), "output_path": str(output),
                    "manifest": {"run_id": "expected", "rois": [{"roi_name": "PRIVATE-NAME"}]},
                    "output_table_id": table.GetID(), "output_table_mtime": self.logic.tableModificationTime(table),
                    "append_results": True}
                widget._startRunFeedback()
                status = node.CompletedWithErrors if outcome == "failed" else node.Cancelled if outcome == "cancelled" else node.Completed
                node.SetStatus(status, False)
                with patch.object(slicer.util, "errorDisplay"):
                    widget.onCliModified(node)
                self.assertEqual(table.GetAttribute(SNAPSHOT_ATTRIBUTE), before)
                self.assertEqual(table.GetAttribute("Pictologics.ProvenanceHistoryJSON"), history)
                self.assertEqual([row["value"] for row in self.logic.rowsFromTable(table)], [math.pi, -0.0])
                self.assertFalse(work.exists())
                self.assertTrue(widget.ui.runButton.enabled)
                self.assertTrue(widget.ui.exportButton.enabled)
                self.assertIsNone(widget._activeJob)
                self.assertIsNone(widget._cliNode)
                widget.onRefreshDiagnostics()
                report = json.loads(widget._diagnosticsPreview)
                expected_code = "worker_failed" if outcome == "failed" else "none" if outcome == "cancelled" else "result_rejected"
                self.assertEqual(report["last_operation"]["failure_code"], expected_code)
                self.assertNotIn("PRIVATE-NAME", widget._diagnosticsPreview)
        # A subsequent successful result can still be appended after these failures.
        self._persistence_table([42.0], table, run="recovery")
        self.assertEqual(len(self.logic.rowsFromTable(table)), 3)

    def test_export_write_failure_preserves_archive_table_and_allows_retry(self) -> None:
        widget = self._feedback_widget()
        table = self._persistence_table([math.pi, -0.0])
        widget.ui.outputTableSelector.setCurrentNode(table)
        archive = self.temporary_directory / "completed.json"
        self.logic.exportTable(table, archive)
        before = archive.read_bytes()
        snapshot = table.GetAttribute(SNAPSHOT_ATTRIBUTE)
        for failure in (PermissionError("Synthetic permission failure"), OSError(errno.ENOSPC, "Synthetic disk full")):
            with self.subTest(failure=type(failure).__name__), patch.object(qt.QFileDialog, "getSaveFileName", return_value=str(archive)), patch.object(
                gui_module.os, "replace", side_effect=failure
            ), patch.object(slicer.util, "errorDisplay"):
                widget.onExport()
            self.assertEqual(archive.read_bytes(), before)
            self.assertEqual(table.GetAttribute(SNAPSHOT_ATTRIBUTE), snapshot)
            self.assertFalse(list(archive.parent.glob(".completed.json.*.tmp")))
            self.assertEqual(widget._diagnosticOperation["failure_code"], "export_failed")
        with patch.object(qt.QFileDialog, "getSaveFileName", return_value=str(archive)):
            widget.onExport()
        self.assertEqual(archive.read_bytes(), before)
        self.assertEqual(widget._diagnosticOperation["outcome"], "completed")

    def test_csv_sidecar_failure_rolls_back_complete_export_set(self) -> None:
        table = self._persistence_table([math.pi])
        root = self.temporary_directory / "archives"
        path = root / "features.csv"
        self.logic.exportTable(table, path)
        before = {p.name: p.read_bytes() for p in root.iterdir()}
        self._persistence_table([42.0], table, run="next")
        snapshot = table.GetAttribute(SNAPSHOT_ATTRIBUTE)
        write_json = self.logic._atomicWriteJSON
        replace = os.replace
        for phase in ("staging", "publication"):
            def failing_json(target, payload, phase=phase):
                if phase == "staging":
                    raise OSError(errno.ENOSPC, "Synthetic sidecar disk full")
                return write_json(target, payload)

            def failing_replace(source, target):
                if Path(target) == root / "features.provenance.json" and Path(source).parent.name == "new":
                    raise PermissionError("Synthetic sidecar publication failure")
                return replace(source, target)

            with self.subTest(phase=phase), patch.object(self.logic, "_atomicWriteJSON", side_effect=failing_json), patch.object(
                os, "replace", side_effect=failing_replace
            ), self.assertRaises(OSError):
                self.logic.exportTable(table, path)
            self.assertEqual({p.name: p.read_bytes() for p in root.iterdir()}, before)
            self.assertEqual(table.GetAttribute(SNAPSHOT_ATTRIBUTE), snapshot)
        self.logic.exportTable(table, path)
        self.assertNotEqual(path.read_bytes(), before[path.name])
        self.assertFalse(list(root.glob(".pictologics-export-*")))

    def test_old_environments_are_removed_once_no_job_runs(self) -> None:
        paths = self.logic.privatePaths()
        old = paths["environments_root"] / "0.5.0-aaaaaaaa"
        active = paths["environments_root"] / "0.5.1-bbbbbbbb"
        for environment in (old, active):
            environment.mkdir(parents=True)
        activate_dependency_target(paths["cache_root"], active)
        job = paths["jobs_root"] / "job-running"
        job.mkdir(parents=True)
        (job / ".owner-active").write_text(f"pid={os.getpid()}\n", encoding="utf-8")

        self.assertEqual(self.logic.removeRetiredEnvironments(), [])
        self.assertTrue(old.is_dir())
        shutil.rmtree(job)
        self.assertEqual(self.logic.removeRetiredEnvironments(), [old.resolve()])
        self.assertFalse(old.exists())
        self.assertTrue(active.is_dir())

    def test_readiness_recovers_and_preserves_run_outcome(self) -> None:
        widget = self._feedback_widget()
        empty = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLScalarVolumeNode", "Empty")
        widget.ui.inputVolumeSelector.setCurrentNode(empty)
        self.assertFalse(widget.ui.runButton.enabled)
        self.assertIn("no image data", widget.ui.readinessLabel.text)
        widget.ui.inputVolumeSelector.setCurrentNode(self.fixture.volume_node)
        self.assertTrue(widget.ui.runButton.enabled)
        self.assertEqual(widget.ui.readinessLabel.text, "Ready: whole volume; 1 preset(s).")
        widget.ui.segmentationSelector.setCurrentNode(self.fixture.segmentation_node)
        self.assertIn("whole volume + 1 segment(s)", widget.ui.readinessLabel.text)
        widget.ui.wholeVolumeCheckBox.setChecked(False)
        self.assertIn("Ready: 1 segment(s)", widget.ui.readinessLabel.text)
        widget.ui.statusLabel.setText("Completed: previous run.")
        widget._updateRunState()
        self.assertEqual(widget.ui.statusLabel.text, "Completed: previous run.")
        widget.ui.inputVolumeSelector.setCurrentNode(empty)
        self.assertIn("no image data", widget.ui.readinessLabel.text)
        self.assertEqual(widget.ui.statusLabel.text, "Completed: previous run.")
        widget.ui.inputVolumeSelector.setCurrentNode(self.fixture.volume_node)
        widget.ui.additionalConfigCombo.setCurrentIndex(1)
        self.assertIn("1 in-app configuration", widget.ui.readinessLabel.text)
        self.assertEqual(widget.ui.statusLabel.textFormat, qt.Qt.PlainText)

    def test_profiles_save_load_copy_and_reject_invalid_settings(self) -> None:
        widget = self._feedback_widget()
        widget.ui.segmentationSelector.setCurrentNode(self.fixture.segmentation_node)
        widget.ui.additionalConfigCombo.setCurrentIndex(1)
        widget.ui.resampleXSpinBox.setValue(2.0)
        widget.ui.discretiseMethodCombo.setCurrentIndex(1)
        widget.ui.discretiseValueSpinBox.setValue(25.5)
        widget.ui.sourceModeCombo.setCurrentIndex(2)
        widget.ui.sentinelValueLineEdit.setText("-3024")
        widget.ui.resegmentGroup.setChecked(True)
        widget.ui.rangeMinLineEdit.setText("-100.25")
        widget.ui.rangeMaxLineEdit.setText("400")
        widget.ui.resegmentTargetCombo.setCurrentIndex(1)
        widget.ui.outlierGroup.setChecked(True)
        widget.ui.outlierSigmaSpinBox.setValue(2.5)
        widget.ui.outlierTargetCombo.setCurrentIndex(2)
        original_state = widget._inlineStateFromGUI()
        original_ids = widget._selectedSegmentIDs()
        destination = self.temporary_directory / "saved.pictologics-profile.json"
        chosen = {"file": destination, "name": "Test profile"}
        dialog_qt = _qt_with(
            QInputDialog=SimpleNamespace(getText=lambda *args: chosen["name"]),
            QFileDialog=SimpleNamespace(getSaveFileName=lambda *args: str(chosen["file"]),
                                        getOpenFileName=lambda *args: str(chosen["file"])),
        )
        with patch.object(gui_module, "qt", dialog_qt), patch.object(slicer.util, "errorDisplay") as errors:
            widget.ui.saveProfileButton.click()
            errors.assert_not_called()
            original_bytes = destination.read_bytes()
            document = json.loads(original_bytes)
            self.assertEqual(document["name"], "Test profile")
            self.assertEqual(document["inline_state"], original_state)
            self.assertNotIn("subject_id", document)
            widget.ui.resampleXSpinBox.setValue(3.0)
            widget.ui.additionalConfigCombo.setCurrentIndex(0)
            widget.ui.loadProfileButton.click()
            self.assertEqual(widget._inlineStateFromGUI(), original_state)
            self.assertEqual(widget._currentAdditionalSource(), "inline")
            self.assertEqual(widget._selectedSegmentIDs(), original_ids)
            self.assertEqual(widget.ui.inputVolumeSelector.currentNode(), self.fixture.volume_node)
            self.assertEqual(widget._storedInlineState(), original_state)
            # A duplicate may not overwrite the source, including canonical-path aliases.
            chosen["name"] = "Test copy"
            widget.ui.duplicateProfileButton.click()
            self.assertTrue(errors.called)
            self.assertEqual(destination.read_bytes(), original_bytes)
            errors.reset_mock()
            chosen["file"] = self.temporary_directory / "copy.pictologics-profile.json"
            widget.ui.duplicateProfileButton.click()
            errors.assert_not_called()
            self.assertEqual(json.loads(chosen["file"].read_text())["name"], "Test copy")
            self.assertEqual(destination.read_bytes(), original_bytes)
            document["inline_state"]["spacing"][0] = 999
            chosen["file"].write_text(json.dumps(document), encoding="utf-8")
            widget.ui.loadProfileButton.click()
            self.assertTrue(errors.called)
            self.assertEqual(widget._inlineStateFromGUI(), original_state)
            # Disabled filter settings also have to be representable without
            # partially applying a profile or silently rounding its parameters.
            for changes in ({"filter_type": "unknown"},
                            {"filter_params": {"sigma_mm": 1.23456, "truncate": 4.0}}):
                errors.reset_mock()
                document["inline_state"] = {**original_state, **changes}
                chosen["file"].write_text(json.dumps(document), encoding="utf-8")
                widget.ui.loadProfileButton.click()
                self.assertTrue(errors.called)
                self.assertEqual(widget._inlineStateFromGUI(), original_state)
                self.assertEqual(widget._storedInlineState(), original_state)
            # Extension normalization must not bypass overwrite confirmation.
            normalized = self.temporary_directory / "normalized.pictologics-profile.json"
            normalized.write_text("keep original", encoding="utf-8")
            chosen["file"] = self.temporary_directory / "normalized"
            with patch.object(slicer.util, "confirmYesNoDisplay", return_value=False) as confirm:
                widget.ui.saveProfileButton.click()
                confirm.assert_called_once()
            self.assertEqual(normalized.read_text(), "keep original")
            widget.ui.additionalConfigCombo.setCurrentIndex(2)
            self.assertFalse(widget.ui.saveProfileButton.enabled)
            self.assertFalse(widget.ui.duplicateProfileButton.enabled)

    def test_results_browser_filters_details_pagination_and_export_are_read_only(self) -> None:
        widget = self._feedback_widget()
        table = None
        for run, value, outcome in (("run-a", 1.25, "ok"), ("run-b", None, "error")):
            row = dict.fromkeys(LONG_RESULT_COLUMNS, "")
            row.update(run_id=run, timestamp="2026-09-22", image_name="Example", roi_id="same-id",
                       roi_name="Same lesion name", roi_source="segmentation", config="test",
                       feature_name="Volume", feature_key="volume_BC2M_10", pictologics_feature_name="test__volume_BC2M_10",
                       ibsi_code="BC2M", pictologics_ibsi_code="BC2M_10", family="ivh", value=value, status=outcome)
            provenance = {"effective_configuration": {"configs": {"test": {"source_mode": "auto", "steps": []}}}}
            payload = {"schema_version": RESULT_PAYLOAD_SCHEMA_VERSION, "run_id": run,
                       "rows": [dict(row) for _ in range(205)], "provenance": provenance, "errors": []}
            table = self.logic.commitRows(table, payload["rows"], append=table is not None,
                                         payload=payload, manifest={"configuration_sha256": f"hash-{run}"})
        widget.ui.outputTableSelector.setCurrentNode(table)
        canonical = self.logic.rowsFromTable(table)
        mtime = self.logic.tableModificationTime(table)
        self.assertTrue(widget.ui.browseResultsButton.enabled)
        widget.onBrowseResults()
        browser = widget._resultsBrowser
        self.assertEqual(browser.table.rowCount, 200)
        self.assertEqual(len(browser.indices), 410)
        browser.next.click()
        self.assertEqual(browser.page, 1)
        browser.next.click()
        self.assertEqual(browser.table.rowCount, 10)
        browser.previous.click()
        self.assertEqual(browser.page, 1)
        browser.filters["status"].setCurrentIndex(browser.filters["status"].findText("error"))
        self.assertEqual(browser.page, 0)
        self.assertEqual(len(browser.indices), 205)
        self.assertIn("SHA-256: hash-run-b", browser.details.toPlainText())
        self.assertNotIn("hash-run-a", browser.details.toPlainText())
        self.assertIn("Value: Not available", browser.details.toPlainText())
        browser.search.setText("bc2m_10")
        self.assertEqual(len(browser.indices), 205)
        browser.search.setText("does-not-exist")
        self.assertEqual(browser.table.rowCount, 0)
        self.assertEqual(browser.details.toPlainText(), "No matching result selected.")
        browser.reset_button.click()
        self.assertEqual(len(browser.indices), 410)
        browser.filters["roi"].setCurrentIndex(2)
        self.assertEqual(len(browser.indices), 205)
        self.assertIn("hash-run-b", browser.details.toPlainText())
        self.assertEqual(self.logic.tableModificationTime(table), mtime)
        self.assertEqual(self.logic.rowsFromTable(table), canonical)
        export_path = self.temporary_directory / "browser-export.json"
        self.logic.exportTable(table, export_path)
        self.assertEqual(len(json.loads(export_path.read_text())["rows"]), 410)
        self.assertEqual(browser.table.editTriggers, qt.QAbstractItemView.NoEditTriggers)
        # Refresh clears stale snapshots, and malformed provenance does not hide rows.
        table.SetAttribute("Pictologics.ProvenanceHistoryJSON", "not-json")
        browser.refresh_button.click()
        self.assertEqual(len(browser.rows), 410)
        self.assertIn("not valid JSON", browser.source.text)
        self.assertIn("Provenance unavailable", browser.details.toPlainText())
        widget.onSceneStartClose()
        self.assertEqual(browser.rows, [])
        self.assertFalse(browser.dialog.visible)

    def _persistence_table(self, values, table=None, run="persistence-a"):
        rows = []
        for index, value in enumerate(values):
            row = dict.fromkeys(LONG_RESULT_COLUMNS, "")
            row.update(run_id=run, timestamp="2026-09-29", image_name="Synthetic precision test",
                       roi_id="synthetic", roi_name="Synthetic ROI", roi_source="segmentation",
                       config="test", family="intensity", feature_name=f"feature_{index}",
                       feature_key=f"feature_{index}_Q4LE", pictologics_feature_name=f"test__feature_{index}_Q4LE",
                       ibsi_code="Q4LE", pictologics_ibsi_code="Q4LE", value=value, status="ok")
            rows.append(row)
        payload = {"schema_version": RESULT_PAYLOAD_SCHEMA_VERSION, "run_id": run, "rows": rows,
                   "provenance": {}, "errors": []}
        table = self.logic.commitRows(table, rows, append=table is not None, payload=payload,
                                      manifest={"configuration_sha256": "synthetic-hash"})
        table.SetName("Persistence test")
        return table

    def test_persistence_scene_roundtrip_keeps_exact_doubles_and_exports(self) -> None:
        values = [206.64972537299272, -math.pi, -0.0, 1.2345678901234567e-100, 1e100, float("nan")]
        table = self._persistence_table(values)
        self.assertTrue(table.GetAttribute(SNAPSHOT_ATTRIBUTE))
        # Export before closing the synthetic scene, too.
        export = self.temporary_directory / "before.json"
        self.logic.exportTable(table, export)
        expected = self.logic.rowsFromTable(table)
        scene = self.temporary_directory / "precision.mrb"
        self.assertTrue(slicer.util.saveScene(str(scene)))
        slicer.mrmlScene.Clear()
        self.assertTrue(slicer.util.loadScene(str(scene)))
        loaded = slicer.mrmlScene.GetFirstNodeByName("Persistence test")
        self.assertIsNone(loaded.GetAttribute(WARNING_ATTRIBUTE))
        actual = loaded.GetTable().GetColumnByName("value")
        self.assertEqual(struct.pack(">6d", *values), struct.pack(">6d", *(actual.GetValue(i) for i in range(6))))
        self.assertEqual(self.logic.rowsFromTable(loaded), expected)
        after = self.temporary_directory / "after.json"
        self.logic.exportTable(loaded, after)
        self.assertEqual(json.loads(after.read_text()), json.loads(export.read_text()))
        # Repeated save/reload must not accumulate quantization error.
        self.assertTrue(slicer.util.saveScene(str(self.temporary_directory / "again.mrb")))
        slicer.mrmlScene.Clear()
        self.assertTrue(slicer.util.loadScene(str(self.temporary_directory / "again.mrb")))
        self.assertEqual(self.logic.rowsFromTable(slicer.mrmlScene.GetFirstNodeByName("Persistence test")), expected)

    def test_persistence_keeps_user_edits_and_appended_runs(self) -> None:
        table = self._persistence_table([math.pi])
        value_index = list(LONG_RESULT_COLUMNS).index("value")
        edited = 123.45678901234567
        table.SetCellText(0, value_index, repr(edited))
        table.SetCellText(0, list(LONG_RESULT_COLUMNS).index("roi_name"), "Edited ROI")
        manager = gui_module._resultPersistence()
        identity, current = manager._contents(table)
        self.assertEqual(decode_values(table.GetAttribute(SNAPSHOT_ATTRIBUTE), identity, current), (edited,))
        self._persistence_table([math.e], table, run="persistence-b")
        expected = self.logic.rowsFromTable(table)
        scene = self.temporary_directory / "edited.mrb"
        self.logic.exportTable(table, self.temporary_directory / "edited-before.json")
        self.assertTrue(slicer.util.saveScene(str(scene)))
        slicer.mrmlScene.Clear()
        self.assertTrue(slicer.util.loadScene(str(scene)))
        loaded = slicer.mrmlScene.GetFirstNodeByName("Persistence test")
        self.assertEqual(self.logic.rowsFromTable(loaded), expected)
        self.assertEqual(len(self.logic.provenanceHistory(loaded)), 2)

    def test_persistence_rejects_corrupt_or_stale_backup_without_partial_restore(self) -> None:
        table = self._persistence_table([math.pi, math.e])
        manager = gui_module._resultPersistence()
        original = table.GetAttribute(SNAPSHOT_ATTRIBUTE)
        for damaged in ("not-json", original.replace('"version":1', '"version":99')):
            table.SetAttribute(SNAPSHOT_ATTRIBUTE, damaged)
            before = self.logic.rowsFromTable(table)
            with self.assertLogs(gui_module.LOGGER, "WARNING"):
                manager._restore(table)
            self.assertEqual(self.logic.rowsFromTable(table), before)
            self.assertIn("left unchanged", table.GetAttribute(WARNING_ATTRIBUTE))
        # A changed row identity is rejected even if rounded numeric values match.
        table.SetCellText(0, list(LONG_RESULT_COLUMNS).index("roi_name"), "Another ROI")
        table.SetAttribute(SNAPSHOT_ATTRIBUTE, original)
        with self.assertLogs(gui_module.LOGGER, "WARNING"):
            manager._restore(table)
        self.assertIn("different table rows", table.GetAttribute(WARNING_ATTRIBUTE))

    def test_persistence_legacy_scene_warns_without_inventing_digits(self) -> None:
        table = self._persistence_table([math.pi])
        table.SetAttribute(SNAPSHOT_ATTRIBUTE, None)
        scene = self.temporary_directory / "legacy.mrb"
        self.logic.exportTable(table, self.temporary_directory / "legacy-before.json")
        self.assertTrue(slicer.util.saveScene(str(scene)))
        slicer.mrmlScene.Clear()
        with self.assertLogs(gui_module.LOGGER, "WARNING"):
            self.assertTrue(slicer.util.loadScene(str(scene)))
        loaded = slicer.mrmlScene.GetFirstNodeByName("Persistence test")
        self.assertEqual(self.logic.rowsFromTable(loaded)[0]["value"], float(format(math.pi, ".6g")))
        self.assertIn("cannot be recovered", loaded.GetAttribute(WARNING_ATTRIBUTE))
        widget = self._feedback_widget()
        widget.ui.outputTableSelector.setCurrentNode(loaded)
        widget.onBrowseResults()
        self.assertIn("cannot be recovered", widget._resultsBrowser.source.text)

    def test_persistence_import_does_not_overwrite_existing_live_edits(self) -> None:
        scene = self.temporary_directory / "other.mrb"
        self.assertTrue(slicer.util.saveScene(str(scene)))
        table = self._persistence_table([206.64972537299272])
        old_snapshot = table.GetAttribute(SNAPSHOT_ATTRIBUTE)
        # Deliberately create the ambiguous case: user chose the rounded value.
        table.SetCellText(0, list(LONG_RESULT_COLUMNS).index("value"), "206.65")
        table.SetAttribute(SNAPSHOT_ATTRIBUTE, old_snapshot)
        self.assertTrue(slicer.util.loadScene(str(scene), {"clear": False}))
        self.assertEqual(self.logic.rowsFromTable(table)[0]["value"], 206.65)

    def test_persistence_plain_mrml_scene_view_restore_and_observer_replacement(self) -> None:
        slicer.mrmlScene.Clear()
        table = self._persistence_table([math.pi])
        expected = self.logic.rowsFromTable(table)
        self.logic.exportTable(table, self.temporary_directory / "plain-before.json")
        self.assertTrue(slicer.util.saveNode(table, str(self.temporary_directory / "table.tsv")))
        scene = self.temporary_directory / "plain.mrml"
        self.assertTrue(slicer.util.saveScene(str(scene)))
        slicer.mrmlScene.Clear()
        # The plain MRML reader returns no node on success (unlike the MRB reader).
        slicer.util.loadScene(str(scene))
        loaded = slicer.mrmlScene.GetFirstNodeByName("Persistence test")
        self.assertIsNotNone(loaded)
        self.assertEqual(self.logic.rowsFromTable(loaded), expected)
        view = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSceneViewNode")
        view.StoreScene()
        old_snapshot = loaded.GetAttribute(SNAPSHOT_ATTRIBUTE)
        loaded.SetCellText(0, list(LONG_RESULT_COLUMNS).index("value"), "3.14159")
        edited = self.logic.rowsFromTable(loaded)
        # Slicer Scene Views exclude table data. Even an ambiguous stale backup
        # must not replace a deliberate edit when only the view is restored.
        loaded.SetAttribute(SNAPSHOT_ATTRIBUTE, old_snapshot)
        self.assertTrue(view.RestoreScene())
        restored = slicer.mrmlScene.GetFirstNodeByName("Persistence test")
        self.assertEqual(self.logic.rowsFromTable(restored), edited)
        manager = gui_module._resultPersistence()
        manager.close()
        slicer.modules._pictologicsResultPersistence = None
        replacement = gui_module._resultPersistence()
        self.assertIsNot(replacement, manager)
        self.assertFalse(manager.nodes)
        self.assertFalse(manager.observers)
        self.assertEqual(len(replacement.nodes), 1)
        restored.SetCellText(0, list(LONG_RESULT_COLUMNS).index("value"), repr(math.e))
        identity, values = replacement._contents(restored)
        self.assertEqual(decode_values(restored.GetAttribute(SNAPSHOT_ATTRIBUTE), identity, values), (math.e,))

    def test_append_with_other_settings_goes_to_a_new_table(self) -> None:
        def payload(run: str, steps: list[dict[str, str]]) -> dict[str, Any]:
            row = dict.fromkeys(LONG_RESULT_COLUMNS, "")
            row.update(run_id=run, timestamp="2026-09-25", image_name="Example", roi_id="1", roi_name="Lesion",
                       roi_source="segmentation", config="in_app", family="morphology", feature_name="volume",
                       feature_key="volume_RNU0", pictologics_feature_name="in_app__volume_RNU0",
                       ibsi_code="RNU0", pictologics_ibsi_code="RNU0", value=1.0, status="ok")
            provenance = {"effective_configuration": {"configs": {"in_app": {"steps": steps}}},
                          "feature_catalog": [{"config": "in_app", "feature_key": "volume_RNU0"}]}
            return {"schema_version": RESULT_PAYLOAD_SCHEMA_VERSION, "run_id": run, "rows": [row],
                    "provenance": provenance, "errors": []}

        def commit(table: Any, result: dict[str, Any]) -> Any:
            return self.logic.commitRows(table, result["rows"], append=True, payload=result,
                                         manifest={"configuration_sha256": result["run_id"]})

        table = commit(None, payload("run-a", [{"step": "extract_features"}]))
        self.assertIs(commit(table, payload("run-b", [{"step": "extract_features"}])), table)
        other = payload("run-c", [{"step": "resample"}, {"step": "extract_features"}])
        with self.assertLogs(gui_module.LOGGER, "WARNING"):
            moved = commit(table, other)
        self.assertIsNot(moved, table)
        self.assertNotEqual(moved.GetName(), table.GetName())
        self.assertEqual((table.GetNumberOfRows(), moved.GetNumberOfRows()), (2, 1))
        self.assertEqual(self.logic.configurationConflicts(table, other), ["in_app"])
        exported = self.logic.exportTable(moved, self.temporary_directory / "features.csv", wide=True)
        self.assertEqual([path.name for path in exported],
                         ["features.csv", "features.provenance.json", "features_catalog.csv"])

    def test_reader_extra_and_scanner_columns(self) -> None:
        volume = self.fixture.volume_node
        self.assertEqual(self.logic.scannerDetails(volume), {})
        image = self.temporary_directory / "image.nii.gz"
        self.assertTrue(slicer.util.saveNode(volume, str(image)))
        (self.temporary_directory / "image.json").write_text(
            json.dumps({"Modality": "CT", "Manufacturer": "SIEMENS", "KVP": 120}), encoding="utf-8")
        loaded = slicer.util.loadVolume(str(image))
        details = self.logic.scannerDetails(loaded)
        self.assertEqual((details["modality"], details["manufacturer"], details["kvp"]), ("CT", "SIEMENS", "120"))
        database = SimpleNamespace(isOpen=True, fileForInstance=lambda uid: "/dicom/1.dcm" if uid == "1.2.3" else "",
                                   fileValue=lambda path, tag: {"0008,0060": "MR", "0018,0087": "3"}.get(tag, ""))
        loaded.SetAttribute("DICOM.instanceUIDs", "1.2.3 1.2.4")
        with patch.object(slicer, "dicomDatabase", database, create=True):
            details = self.logic.scannerDetails(loaded)
        self.assertEqual((details["modality"], details["magnetic_field_strength"]), ("MR", "3"))
        columns = self.logic.resultColumns(loaded, "R1", [("center", "A")])
        self.assertEqual((columns[0], columns[-1]), (("reader", "R1"), ("center", "A")))

        widget = self._feedback_widget()
        widget.ui.inputVolumeSelector.setCurrentNode(loaded)
        self.assertIn("manufacturer: SIEMENS", widget.ui.scannerDetailsLabel.text)
        widget.ui.readerLineEdit.setText("R2")
        widget.ui.extraColumnsTextEdit.setPlainText("center = B")
        self.assertEqual(widget._parameterNode.GetParameter(gui_module.PARAM_READER), "R2")
        self.assertEqual(widget._parameterNode.GetParameter(gui_module.PARAM_EXTRA_COLUMNS), "center = B")
        widget.ui.extraColumnsTextEdit.setPlainText("two__parts = x")
        self.assertIn("cannot be a column name", widget.ui.readinessLabel.text)
        self.assertFalse(widget.ui.runButton.enabled)

        def payload(run: str, extra: dict[str, str]) -> dict[str, Any]:
            row = dict.fromkeys(LONG_RESULT_COLUMNS, "")
            row.update(run_id=run, timestamp="2026-09-26", roi_id="1", config="c", feature_name="f",
                       feature_key="f_X", pictologics_feature_name="c__f_X", value=1.0, status="ok", **extra)
            provenance = {"effective_configuration": {"configs": {"c": {"steps": []}}}}
            return {"schema_version": RESULT_PAYLOAD_SCHEMA_VERSION, "run_id": run, "rows": [row],
                    "provenance": provenance, "errors": []}

        table = None
        for run, extra in (("run-a", {}), ("run-b", {"reader": "R1", "center": "A"})):
            result = payload(run, extra)
            table = self.logic.commitRows(table, result["rows"], append=True, payload=result,
                                         manifest={"configuration_sha256": run})
        rows = self.logic.rowsFromTable(table)
        self.assertEqual([(row["reader"], row["center"]) for row in rows], [("", ""), ("R1", "A")])
        exported = self.logic.exportTable(table, self.temporary_directory / "features.csv", wide=True)
        header = exported[0].read_text(encoding="utf-8").splitlines()[0].split(",")
        self.assertEqual(header[len(WIDE_ID_COLUMNS):][:3], ["reader", "center", "c__f_X"])

    def _write_batch_study(self) -> Path:
        study = self.temporary_directory / "study"
        for name in ("case-b", "case-a"):
            (study / name).mkdir(parents=True)
            self.assertTrue(slicer.util.saveNode(self.fixture.volume_node, str(study / name / "image.nii.gz")))
            self.assertTrue(slicer.util.saveNode(self.fixture.segmentation_node,
                                                 str(study / name / "segmentation.seg.nrrd")))
        (study / "empty").mkdir()
        return study

    def _wait_for_batch_end(self, widget, timeout_seconds: float) -> None:
        deadline = time.monotonic() + timeout_seconds
        while widget._batch is not None:
            if time.monotonic() >= deadline:
                raise TimeoutError("The batch did not finish.")
            _pump_slicer_events()

    def test_batch_runs_each_case_folder_and_cleans_up(self) -> None:
        widget = self._feedback_widget()
        widget.ui.segmentationSelector.setCurrentNode(self.fixture.segmentation_node)
        original_ids = widget._selectedSegmentIDs()
        widget.ui.wholeVolumeCheckBox.setChecked(False)
        widget.ui.subjectIdLineEdit.setText("before")
        widget.ui.batchFolderLineEdit.setText(str(self._write_batch_study()))
        scene_before = _scene_node_ids()
        seen = []

        def fake_run():
            volume = widget.ui.inputVolumeSelector.currentNode()
            seen.append((str(widget.ui.subjectIdLineEdit.text), widget._selectedSegmentIDs(),
                         volume.GetImageData().GetDimensions(), widget.ui.appendResultsCheckBox.checked))
            widget._batch["completed"] += 1

        with patch.object(widget, "onRun", side_effect=fake_run), patch.object(
            slicer.util, "confirmOkCancelDisplay", return_value=True
        ) as confirm, patch.object(slicer.util, "warningDisplay") as warning:
            widget.onRunBatch()
            self._wait_for_batch_end(widget, 30)
        self.assertIn("1 folder(s) are skipped", confirm.call_args.args[0])
        self.assertEqual([case[0] for case in seen], ["case-a", "case-b"])
        self.assertEqual({tuple(case[1]) for case in seen}, {(self.fixture.segment_id,)})
        self.assertEqual({case[2] for case in seen}, {tuple(reversed(ARRAY_SHAPE_KJI))})
        self.assertTrue(all(case[3] for case in seen))
        warning.assert_not_called()
        self.assertEqual(widget.ui.statusLabel.text, "Batch finished: 2 of 2 case(s) added rows.")
        self.assertEqual(widget.ui.subjectIdLineEdit.text, "before")
        self.assertFalse(widget.ui.appendResultsCheckBox.checked)
        self.assertEqual(widget.ui.inputVolumeSelector.currentNode(), self.fixture.volume_node)
        self.assertEqual(widget.ui.segmentationSelector.currentNode(), self.fixture.segmentation_node)
        self.assertEqual(widget._selectedSegmentIDs(), original_ids)
        self.assertEqual(_scene_node_ids() - scene_before, set())
        self.assertTrue(widget.ui.runBatchButton.enabled)
        widget.ui.batchFolderLineEdit.setText(str(self.temporary_directory / "missing"))
        with patch.object(slicer.util, "errorDisplay") as error:
            widget.onRunBatch()
        self.assertIn("study folder that exists", error.call_args.args[0])
        widget.ui.batchFolderLineEdit.setText("")
        with patch.object(slicer.util, "errorDisplay") as error:
            widget.onRunBatch()
        self.assertIn("study folder that exists", error.call_args.args[0])
        widget.ui.batchFolderLineEdit.setText(str(self.temporary_directory))
        with patch.object(gui_module, "find_cases", side_effect=PermissionError("denied")), patch.object(
            slicer.util, "errorDisplay"
        ) as error:
            widget.onRunBatch()
        self.assertIn("Could not read the study folder", error.call_args.args[0])

    def test_batch_load_failure_continues_and_removes_partial_case_nodes(self) -> None:
        widget = self._feedback_widget()
        widget.ui.segmentationSelector.setCurrentNode(self.fixture.segmentation_node)
        widget.ui.wholeVolumeCheckBox.setChecked(False)
        widget.ui.subjectIdLineEdit.setText("original subject")
        widget.ui.batchFolderLineEdit.setText(str(self._write_batch_study()))
        scene_before = _scene_node_ids()
        real_load = slicer.util.loadSegmentation
        seen = []

        def load_segmentation(path):
            if Path(path).parent.name == "case-a":
                raise RuntimeError("synthetic unreadable segmentation")
            return real_load(path)

        def fake_run():
            seen.append(str(widget.ui.subjectIdLineEdit.text))
            widget._batch["completed"] += 1

        with patch.object(slicer.util, "loadSegmentation", side_effect=load_segmentation), patch.object(
            widget, "onRun", side_effect=fake_run
        ), patch.object(slicer.util, "confirmOkCancelDisplay", return_value=True), patch.object(
            slicer.util, "warningDisplay"
        ) as warning:
            widget.onRunBatch()
            self._wait_for_batch_end(widget, 30)
        self.assertEqual(seen, ["case-b"])
        warning.assert_called_once()
        self.assertIn("case-a: Could not load the case files", warning.call_args.args[0])
        self.assertIn("1 of 2 case(s) added rows. 1 case(s) failed", widget.ui.statusLabel.text)
        self.assertEqual(_scene_node_ids() - scene_before, set())
        self.assertEqual(widget.ui.subjectIdLineEdit.text, "original subject")
        self.assertEqual(widget.ui.inputVolumeSelector.currentNode(), self.fixture.volume_node)
        self.assertEqual(widget.ui.segmentationSelector.currentNode(), self.fixture.segmentation_node)

    def test_batch_cancellation_stops_before_loading_next_case(self) -> None:
        widget = self._feedback_widget()
        widget.ui.batchFolderLineEdit.setText(str(self._write_batch_study()))
        scene_before = _scene_node_ids()
        seen = []

        def fake_run():
            seen.append(str(widget.ui.subjectIdLineEdit.text))
            node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLCommandLineModuleNode")
            widget._cliNode = node
            widget._activeJob = {"manifest": {"rois": [{"roi_name": "Synthetic region"}]}}
            widget._startRunFeedback()
            widget._cliObserverTag = node.AddObserver(vtk.vtkCommand.ModifiedEvent, widget.onCliModified)
            node.SetStatus(node.Running)

        with patch.object(widget, "onRun", side_effect=fake_run), patch.object(
            slicer.util, "confirmOkCancelDisplay", return_value=True
        ), patch.object(widget.logic, "cleanupJob"), patch.object(widget, "_acceptCompletedJob") as accept:
            widget.onRunBatch()
            node = widget._cliNode
            widget.onCancel()
            # Exercise actual MRML cancellation events; no worker is launched here.
            node.SetStatus(node.Cancelled)
            self._wait_for_batch_end(widget, 30)
        accept.assert_not_called()
        self.assertEqual(seen, ["case-a"])
        self.assertIn("Batch stopped after 1 of 2 case(s)", widget.ui.statusLabel.text)
        self.assertEqual(_scene_node_ids() - scene_before, set())
        self.assertIsNone(widget._activeJob)
        self.assertFalse(widget._runFeedbackTimer.isActive())

    def test_batch_scene_close_discards_queued_case_and_original_input_restore(self) -> None:
        widget = self._feedback_widget()
        widget.ui.batchFolderLineEdit.setText(str(self._write_batch_study()))
        seen = []

        def fake_run():
            seen.append(str(widget.ui.subjectIdLineEdit.text))
            widget._batch["completed"] += 1

        with patch.object(widget, "onRun", side_effect=fake_run), patch.object(
            slicer.util, "confirmOkCancelDisplay", return_value=True
        ), patch.object(slicer.util, "warningDisplay") as warning:
            widget.onRunBatch()
            self.assertTrue(widget._batch["pending"])
            slicer.mrmlScene.Clear()
            self._wait_for_batch_end(widget, 30)
        self.assertEqual(seen, ["case-a"])
        self.assertIsNone(widget.ui.inputVolumeSelector.currentNode())
        self.assertIsNone(widget.ui.segmentationSelector.currentNode())
        self.assertEqual(slicer.mrmlScene.GetNumberOfNodesByClass("vtkMRMLVolumeNode"), 0)
        warning.assert_not_called()

    def test_memory_warning_allows_crop_fallback_and_rechecks_larger_batch_cases(self) -> None:
        widget = self._feedback_widget()
        widget.ui.cropCheckBox.setChecked(True)
        widget.ui.wholeVolumeCheckBox.setChecked(False)
        widget._batch = {"approvedImageBytes": 0}
        try:
            with patch.object(gui_module, "LARGE_IMAGE_BYTES", 1), patch.object(
                gui_module, "largest_voxel_count", side_effect=[100, 100, 200, 300, 300]
            ) as estimate, patch.object(slicer.util, "confirmOkCancelDisplay", side_effect=[True, True, False, True]) as confirm:
                self.assertTrue(widget._confirmLargeRun())
                self.assertEqual(tuple(estimate.call_args.args[0]),
                                 self.fixture.volume_node.GetImageData().GetDimensions())
                self.assertTrue(widget._confirmLargeRun())
                self.assertEqual(confirm.call_count, 1)
                self.assertTrue(widget._confirmLargeRun())
                self.assertEqual(widget._batch["approvedImageBytes"], 200 * BYTES_PER_VOXEL)
                self.assertFalse(widget._confirmLargeRun())
                self.assertEqual(widget._batch["approvedImageBytes"], 200 * BYTES_PER_VOXEL)
                self.assertTrue(widget._confirmLargeRun())
                self.assertEqual(confirm.call_count, 4)
                self.assertIn("some configurations or axes require the whole scan", confirm.call_args.args[0])
        finally:
            widget._batch = None

    @unittest.skipUnless(
        os.environ.get(RUN_REAL_CLI_TEST_ENV) == "1",
        f"Set {RUN_REAL_CLI_TEST_ENV}=1 to run the existing-dependency CLI gate.",
    )
    def test_real_batch_adds_every_case_to_one_table(self) -> None:
        dependency_path, _ = _qualified_dependency_target(self.logic)
        inspection = inspect_target(dependency_path, self.logic.pictologicsRequirement())
        widget = self._feedback_widget()
        widget.ui.wholeVolumeCheckBox.setChecked(False)
        widget.ui.readerLineEdit.setText("R1")
        widget.ui.batchFolderLineEdit.setText(str(self._write_batch_study()))
        with patch.object(widget.logic, "ensureDependencies", return_value=inspection), patch.object(
            widget.logic, "showTable"
        ), patch.object(slicer.util, "confirmOkCancelDisplay", return_value=True), patch.object(
            slicer.util, "warningDisplay"
        ) as warning:
            widget.onRunBatch()
            self._wait_for_batch_end(widget, 2 * CLI_TIMEOUT_SECONDS)
        warning.assert_not_called()
        self.assertEqual(widget.ui.statusLabel.text, "Batch finished: 2 of 2 case(s) added rows.")
        rows = widget.logic.rowsFromTable(widget.ui.outputTableSelector.currentNode())
        self.assertEqual({row["subject_id"] for row in rows}, {"case-a", "case-b"})
        self.assertEqual({row["reader"] for row in rows}, {"R1"})
        self.assertIn("ok", {row["status"] for row in rows})

    def test_crop_switch_reaches_the_manifest(self) -> None:
        widget = self._feedback_widget()
        widget.ui.cropCheckBox.setChecked(True)
        self.assertEqual(widget._parameterNode.GetParameter(gui_module.PARAM_CROP), "true")
        dependency = self.temporary_directory / "dependency"
        dependency.mkdir()
        job = self.logic.prepareJob(
            inputVolumeNode=self.fixture.volume_node, segmentationNode=self.fixture.segmentation_node,
            selectedSegmentIDs=[self.fixture.segment_id], includeWholeVolume=False,
            standardConfigurations=["standard_fbn_32"], customConfigurationPath=None, subjectID="",
            installedVersion="0.5.1", dependencyPath=dependency, cropToRegion=True)
        self.addCleanup(self.logic.cleanupJob, job)
        self.assertTrue(job["manifest"]["configuration_document"]["crop_to_roi"])

    @unittest.skipUnless(
        os.environ.get(RUN_REAL_CLI_TEST_ENV) == "1",
        f"Set {RUN_REAL_CLI_TEST_ENV}=1 to run the existing-dependency CLI gate.",
    )
    def test_real_crop_keeps_the_values_of_a_whole_scan_run(self) -> None:
        dependency_path, _ = _qualified_dependency_target(self.logic)
        inspection = inspect_target(dependency_path, self.logic.pictologicsRequirement())
        rng = np.random.default_rng(7)
        volume = slicer.util.addVolumeFromArray(rng.normal(100.0, 25.0, (40, 44, 48)).astype(np.float32))
        volume.SetSpacing(1.0, 1.0, 1.3)
        grid = np.indices((40, 44, 48)).astype(float)
        sphere = ((grid[0] - 12) ** 2 + (grid[1] - 30) ** 2 + (grid[2] - 34) ** 2) <= 36
        labelmap = slicer.util.addVolumeFromArray(sphere.astype(np.uint8), nodeClassName="vtkMRMLLabelMapVolumeNode")
        labelmap.SetSpacing(1.0, 1.0, 1.3)
        segmentation = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLSegmentationNode")
        slicer.modules.segmentations.logic().ImportLabelmapToSegmentationNode(labelmap, segmentation)
        tables = {}
        with patch.object(self.logic, "ensureDependencies", return_value=inspection):
            for crop in (False, True):
                tables[crop] = self.logic.process(volume, segmentation, cropToRegion=crop)
        values = {crop: {row["feature_key"]: row["value"] for row in self.logic.rowsFromTable(table)}
                  for crop, table in tables.items()}
        provenance = self.logic.provenanceHistory(tables[True])[0]["provenance"]
        self.assertGreater(provenance["crop_margin_mm"], 0)
        box = provenance["processing_logs"][0]["crop_box"]
        self.assertLess(math.prod(stop - start for start, stop in zip(*box, strict=True)), 40 * 44 * 48 / 4)
        self.assertEqual(values[True].keys(), values[False].keys())
        for key, whole in values[False].items():
            with self.subTest(feature=key):
                cropped = values[True][key]
                self.assertTrue(cropped is whole or math.isclose(cropped, whole, rel_tol=1e-9, abs_tol=1e-9))

    def test_elapsed_roi_feedback_and_cancellation_preserve_terminal_state(self) -> None:
        widget = self._feedback_widget()
        node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLCommandLineModuleNode")
        widget._cliNode = node
        widget._activeJob = {"manifest": {"rois": [
            {"roi_name": "First"}, {"roi_name": "A < B"},
        ]}}
        widget._startRunFeedback()
        widget._runStartedAt -= 65
        widget._cliObserverTag = node.AddObserver(vtk.vtkCommand.ModifiedEvent, widget.onCliModified)
        node.StartContinuousOutputUpdate()
        widget._continuousOutputNode = node
        node.SetStatus(node.Running)
        node.SetOutputText('PICTOLOGICS_ROI {"index":0,"total":2}\n')
        self.assertEqual(widget.ui.statusLabel.text, "Processing ROI 1 of 2: First")
        node.SetOutputText('PICTOLOGICS_ROI {"index":1,"total":2}\n')
        self.assertEqual(widget.ui.statusLabel.text, "Processing ROI 2 of 2: A < B")
        self.assertEqual(widget.ui.elapsedTimeLabel.text, "Elapsed: 00:01:05")
        self.assertTrue(widget._runFeedbackTimer.isActive())
        widget._updateRunState()
        self.assertFalse(widget.ui.runButton.enabled)
        self.assertIn("inputs are locked", widget.ui.readinessLabel.text)
        widget.onCancel()
        self.assertIn("Cancelling", widget.ui.statusLabel.text)
        widget._updateRunFeedback()
        widget._updateRunState()
        self.assertIn("Cancelling", widget.ui.statusLabel.text)
        self.assertFalse(widget.ui.cancelButton.enabled)
        # No worker/staging exists in this test: exercise actual MRML terminal events.
        with patch.object(widget.logic, "cleanupJob"):
            node.SetStatus(node.Cancelled)
        self.assertIn("was cancelled", widget.ui.statusLabel.text)
        self.assertIsNone(widget._runStartedAt)
        self.assertFalse(widget._runFeedbackTimer.isActive())
        self.assertFalse(node.IsContinuousOutputUpdate())
        elapsed = widget.ui.elapsedTimeLabel.text
        widget._updateRunFeedback()
        self.assertEqual(widget.ui.elapsedTimeLabel.text, elapsed)
        self.assertTrue(widget.ui.runButton.enabled)

    def test_large_run_asks_before_anything_starts(self) -> None:
        widget = self._feedback_widget()
        with patch.object(gui_module, "LARGE_IMAGE_BYTES", 0), patch.object(
            slicer.util, "confirmOkCancelDisplay", return_value=False
        ) as confirm, patch.object(widget.logic, "ensureDependencies") as ensure:
            widget.onRun()
        confirm.assert_called_once()
        self.assertIn("GB of memory", confirm.call_args.args[0])
        ensure.assert_not_called()
        self.assertIsNone(widget._activeJob)
        self.assertEqual(widget.ui.statusLabel.text, "The run did not start.")
        with patch.object(gui_module, "LARGE_IMAGE_BYTES", 0), patch.object(
            slicer.util, "confirmOkCancelDisplay", return_value=True
        ), patch.object(
            widget.logic, "ensureDependencies", side_effect=DependencyInstallDeclined("declined")
        ) as ensure:
            widget.onRun()
        ensure.assert_called_once()

    def test_validate_does_the_quick_check_before_pictologics_is_installed(self) -> None:
        widget = self._feedback_widget()
        path = self.temporary_directory / "custom.json"
        path.write_text(json.dumps({"configs": {"mine": {"steps": [{"step": "bogus"}]}}}),
                        encoding="utf-8")
        widget.ui.customConfigPathLineEdit.setText(str(path))
        widget.onValidateConfiguration()
        self.assertTrue(widget.ui.statusLabel.text.startswith("Configuration has 2 issue(s): "))
        self.assertIn("unknown step type 'bogus'", widget.ui.statusLabel.text)

    @unittest.skipUnless(
        os.environ.get(RUN_REAL_CLI_TEST_ENV) == "1",
        f"Set {RUN_REAL_CLI_TEST_ENV}=1 to run the existing-dependency CLI gate.",
    )
    def test_validate_and_memory_estimate_load_yaml_with_pictologics(self) -> None:
        dependency_path, _ = _qualified_dependency_target(self.logic)
        inspection = inspect_target(dependency_path, self.logic.pictologicsRequirement())
        widget = self._feedback_widget()
        widget.ui.additionalConfigCombo.setCurrentIndex(gui_module.ADDITIONAL_SOURCES.index("file"))
        steps = [
            {"step": "resample", "params": {"new_spacing": [0.25, 0.25, 0.25]}},
            {"step": "extract_features", "params": {"families": ["intensity"]}},
        ]
        # JSON text is also YAML, and Slicer's Python has no YAML writer.
        valid = self.temporary_directory / "fine.yaml"
        valid.write_text(json.dumps({"configs": {"yaml_fine": {"steps": steps}}}), encoding="utf-8")
        steps[1]["params"]["bogus"] = 1
        invalid = self.temporary_directory / "unknown-parameter.yml"
        invalid.write_text(json.dumps({"configs": {"yaml_bad": {"steps": steps}}}), encoding="utf-8")
        volume = self.fixture.volume_node
        presets_only = largest_voxel_count(volume.GetImageData().GetDimensions(), volume.GetSpacing(),
                                           [preset_configuration_document("standard_fbn_32")])
        with patch.object(widget.logic, "inspectDependencies", return_value=inspection):
            widget.ui.customConfigPathLineEdit.setText(str(invalid))
            widget.onValidateConfiguration()
            self.assertIn("Pictologics does not accept this file: custom configuration failed "
                          "validation", widget.ui.statusLabel.text)
            self.assertIn("unknown parameter 'bogus'", widget.ui.statusLabel.text)
            widget.ui.customConfigPathLineEdit.setText(str(valid))
            widget.onValidateConfiguration()
            self.assertEqual(widget.ui.statusLabel.text,
                             "Pictologics accepts this file. It holds 1 configuration(s): yaml_fine.")
            # Only the finer YAML resampling is above this limit.
            with patch.object(gui_module, "LARGE_IMAGE_BYTES", presets_only * BYTES_PER_VOXEL), patch.object(
                slicer.util, "confirmOkCancelDisplay", return_value=False
            ) as confirm:
                self.assertFalse(widget._confirmLargeRun())
        confirm.assert_called_once()

    def test_launch_failure_or_decline_stops_elapsed_feedback(self) -> None:
        widget = self._feedback_widget()
        for error in (DependencyInstallDeclined("declined"), RuntimeError("probe failure")):
            with self.subTest(error=type(error).__name__), patch.object(
                widget.logic, "ensureDependencies", side_effect=error
            ), patch.object(slicer.util, "errorDisplay"):
                widget.onRun()
                self.assertIn("run did not start", widget.ui.statusLabel.text.lower())
                self.assertIsNone(widget._runStartedAt)
                self.assertFalse(widget._runFeedbackTimer.isActive())
                self.assertTrue(widget.ui.runButton.enabled)

    def test_cli_failure_stops_elapsed_feedback_and_preserves_error(self) -> None:
        widget = self._feedback_widget()
        node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLCommandLineModuleNode")
        widget._cliNode = node
        widget._activeJob = {"manifest": {"rois": [{"roi_name": "First"}]}}
        widget._startRunFeedback()
        widget._cliObserverTag = node.AddObserver(vtk.vtkCommand.ModifiedEvent, widget.onCliModified)
        with patch.object(widget.logic, "cleanupJob"), patch.object(slicer.util, "errorDisplay"):
            node.SetStatus(node.CompletedWithErrors, False)
            widget._updateRunFeedback()  # Terminal-state fallback without a ModifiedEvent.
        self.assertIn("failed; the output table was not changed", widget.ui.statusLabel.text)
        self.assertFalse(widget._runFeedbackTimer.isActive())
        self.assertIsNone(widget._runStartedAt)
        widget._updateRunFeedback()
        widget._updateRunState()
        self.assertIn("failed; the output table was not changed", widget.ui.statusLabel.text)
        # A subsequent run starts a fresh clock rather than continuing the failed run.
        widget._startRunFeedback()
        self.assertEqual(widget.ui.elapsedTimeLabel.text, "Elapsed: 00:00:00")

    def test_scene_close_and_cleanup_stop_elapsed_feedback(self) -> None:
        widget = self._feedback_widget()
        widget._startRunFeedback()
        widget.onSceneStartClose()
        self.assertFalse(widget._runFeedbackTimer.isActive())
        self.assertIsNone(widget._runStartedAt)
        widget.initializeParameterNode()
        widget.ui.batchFolderLineEdit.setText(str(self._write_batch_study()))
        scene_before = _scene_node_ids()
        seen = []

        def fake_run():
            seen.append(str(widget.ui.subjectIdLineEdit.text))
            widget._batch["completed"] += 1

        with patch.object(widget, "onRun", side_effect=fake_run), patch.object(
            slicer.util, "confirmOkCancelDisplay", return_value=True
        ), patch.object(slicer.util, "warningDisplay"):
            widget.onRunBatch()
            widget._startRunFeedback()
            widget.cleanup()
            # Deliver the already queued callback after teardown.
            _pump_slicer_events()
        self.assertEqual(seen, ["case-a"])
        self.assertIsNone(widget._batch)
        self.assertEqual(_scene_node_ids() - scene_before, set())
        self.assertIsNone(widget._runFeedbackTimer)
        self.assertIsNone(widget._runStartedAt)

    @unittest.skipUnless(
        os.environ.get(RUN_REAL_CLI_TEST_ENV) == "1",
        f"Set {RUN_REAL_CLI_TEST_ENV}=1 to run the existing-dependency CLI gate.",
    )
    def test_real_worker_failure_preserves_table_and_next_run_succeeds(self) -> None:
        dependency_path, _ = _qualified_dependency_target(self.logic)
        widget = self._feedback_widget()
        table = self._persistence_table([math.pi])
        widget.ui.outputTableSelector.setCurrentNode(table)
        widget.ui.appendResultsCheckBox.setChecked(True)
        before = table.GetAttribute(SNAPSHOT_ATTRIBUTE)
        inspection = inspect_target(dependency_path, self.logic.pictologicsRequirement())
        prepare = self.logic.prepareJob

        def prepare_invalid(**kwargs):
            job = prepare(**kwargs)
            document = dict(job["manifest"], schema_version=999)
            Path(job["manifest_path"]).write_text(json.dumps(document), encoding="utf-8")
            return job

        for fail in (True, False):
            with patch.object(self.logic, "ensureDependencies", return_value=inspection), patch.object(
                self.logic, "prepareJob", side_effect=prepare_invalid if fail else prepare
            ), patch.object(self.logic, "showTable"), patch.object(slicer.util, "errorDisplay") as errors:
                widget.onRun()
                node, job = widget._cliNode, widget._activeJob
                self.assertIsNotNone(node)
                self.assertIsNotNone(job)
                try:
                    observation = _wait_for_cli_terminal(node, self.logic, job, timeout_seconds=CLI_TIMEOUT_SECONDS)
                except BaseException:
                    if self.logic.jobWorkerIsAlive(job):
                        self.retain_temporary_directory = True
                        type(self).retained_async_failure = "Recovery-test worker still owns staging."
                    raise
                deadline = time.monotonic() + 5
                while widget._activeJob is not None and time.monotonic() < deadline:
                    _pump_slicer_events()
                self.assertIsNone(widget._activeJob)
                self.assertTrue(widget.ui.runButton.enabled)
                self.assertFalse(widget._runFeedbackTimer.isActive())
                if fail:
                    self.assertTrue(observation.terminal_state.failed)
                    self.assertEqual(table.GetAttribute(SNAPSHOT_ATTRIBUTE), before)
                    self.assertEqual(widget._diagnosticOperation["failure_code"], "worker_failed")
                    errors.assert_called_once()
                else:
                    self.assertFalse(observation.terminal_state.failed)
                    self.assertTrue(observation.terminal_state.completed)
                    self.assertGreater(table.GetNumberOfRows(), 1)
                    self.assertEqual(self.logic.rowsFromTable(table)[0]["value"], math.pi)
                    self.assertEqual(widget._diagnosticRun["state"], "completed")
                    self.assertGreater(widget._diagnosticRun["feature_rows"], 0)
                    errors.assert_not_called()

    @unittest.skipUnless(
        os.environ.get(RUN_REAL_CLI_TEST_ENV) == "1",
        f"Set {RUN_REAL_CLI_TEST_ENV}=1 to run the existing-dependency CLI gate.",
    )
    def test_real_gui_run_reports_roi_and_freezes_elapsed_time(self) -> None:
        dependency_path, _ = _qualified_dependency_target(self.logic)
        widget = self._feedback_widget()
        widget.ui.segmentationSelector.setCurrentNode(self.fixture.segmentation_node)
        profile_path = self.temporary_directory / "real-run.pictologics-profile.json"
        state = default_inline_state()
        state.update(resample=False, resegment=True, range_min=-50.0, range_max=500.0,
                     filter_outliers=True, outlier_sigma=1.0)
        profile_path.write_text(json.dumps(build_profile(
            "Real extraction profile", ["standard_fbn_32"], state
        )), encoding="utf-8")
        dialog_qt = _qt_with(
            QFileDialog=SimpleNamespace(getOpenFileName=lambda *args: str(profile_path)),
        )
        with patch.object(gui_module, "qt", dialog_qt), patch.object(slicer.util, "errorDisplay") as errors:
            widget.onLoadProfile()
            errors.assert_not_called()
        self.assertEqual(widget._currentAdditionalSource(), "inline")
        inspection = inspect_target(dependency_path, widget.logic.pictologicsRequirement())
        messages = []
        update_feedback = widget._updateRunFeedback

        def capture_feedback():
            update_feedback()
            messages.append(str(widget.ui.statusLabel.text))

        with patch.object(widget.logic, "ensureDependencies", return_value=inspection), patch.object(
            widget.logic, "showTable"
        ), patch.object(widget, "_updateRunFeedback", side_effect=capture_feedback):
            widget.onRun()
            cli_node, job = widget._cliNode, widget._activeJob
            self.assertIsNotNone(cli_node)
            self.assertIsNotNone(job)
            try:
                observation = _wait_for_cli_terminal(
                    cli_node, widget.logic, job, timeout_seconds=CLI_TIMEOUT_SECONDS
                )
            except BaseException:
                if widget.logic.jobWorkerIsAlive(job):
                    self.retain_temporary_directory = True
                    type(self).retained_async_failure = "GUI feedback worker still owns staging."
                raise
            self.assertTrue(observation.terminal_state.completed)
            self.assertFalse(observation.terminal_state.failed)
            deadline = time.monotonic() + 5.0
            while widget._activeJob is not None and time.monotonic() < deadline:
                _pump_slicer_events()
        self.assertIsNone(widget._activeJob)
        self.assertIsNone(widget._runStartedAt)
        self.assertFalse(widget._runFeedbackTimer.isActive())
        self.assertFalse(cli_node.IsContinuousOutputUpdate())
        self.assertIn("Processing ROI 1 of 2: Whole volume", messages)
        self.assertIn(f"Processing ROI 2 of 2: {SEGMENT_NAME}", messages)
        self.assertIn("Completed:", widget.ui.statusLabel.text)
        self.assertIn("Ready:", widget.ui.readinessLabel.text)
        self.assertTrue(widget.ui.runButton.enabled)
        self.assertEqual(widget.ui.progressBar.value, 100)
        table = widget.ui.outputTableSelector.currentNode()
        self.assertGreater(table.GetNumberOfRows(), 0)
        roi_names = table.GetTable().GetColumnByName("roi_name")
        self.assertEqual(
            {roi_names.GetValue(index) for index in range(roi_names.GetNumberOfValues())},
            {"Whole volume", SEGMENT_NAME},
        )
        configurations = table.GetTable().GetColumnByName("config")
        self.assertEqual({configurations.GetValue(index) for index in range(configurations.GetNumberOfValues())},
                         {"standard_fbn_32", "in_app"})
        widget.onBrowseResults()
        browser = widget._resultsBrowser
        browser.filters["configuration"].setCurrentIndex(browser.filters["configuration"].findText("in_app"))
        self.assertGreater(len(browser.indices), 0)
        self.assertIn("Configuration: in_app", browser.details.toPlainText())
        self.assertIn("PROCESSING LOG", browser.details.toPlainText())
        self.assertNotIn("No matching processing log", browser.details.toPlainText())
        self.assertIn("resegment", browser.details.toPlainText())
        self.assertIn("filter_outliers", browser.details.toPlainText())
        # Independent numeric check: the GUI-emitted pipeline must refine masks,
        # not clip intensity values or discretise before deciding voxel membership.
        rows = widget.logic.rowsFromTable(table)
        voxel_volume = abs(np.linalg.det((self.fixture.expected_transform_to_parent
                                          @ self.fixture.expected_ijk_to_ras)[:3, :3]))
        for roi_name, mask in (("Whole volume", np.ones_like(self.fixture.expected_mask)),
                               (SEGMENT_NAME, self.fixture.expected_mask)):
            values = self.fixture.expected_image[mask > 0].astype(np.float64)
            values = values[(values >= -50.0) & (values <= 500.0)]
            mean, std = values.mean(), values.std(ddof=0)
            values = values[(values >= mean - std) & (values <= mean + std)]
            actual = {row["feature_key"]: row["value"] for row in rows
                      if row["roi_name"] == roi_name and row["config"] == "in_app"}
            self.assertAlmostEqual(actual["mean_intensity_Q4LE"], float(values.mean()), places=6)
            self.assertAlmostEqual(actual["volume_voxel_counting_YEKZ"],
                                   len(values) * voxel_volume, places=3)
        np.testing.assert_array_equal(slicer.util.arrayFromVolume(self.fixture.volume_node),
                                      self.fixture.expected_image)

    @unittest.skipUnless(
        os.environ.get(RUN_REAL_CLI_TEST_ENV) == "1",
        f"Set {RUN_REAL_CLI_TEST_ENV}=1 to run the existing-dependency CLI gate.",
    )
    def test_scripted_batch_appends_each_case_to_one_table(self) -> None:
        dependency_path, _ = _qualified_dependency_target(self.logic)
        inspection = inspect_target(dependency_path, self.logic.pictologicsRequirement())
        scene_before = _scene_node_ids()
        table = None
        with patch.object(self.logic, "ensureDependencies", return_value=inspection):
            for subject in ("case-1", "case-2"):
                table = self.logic.process(self.fixture.volume_node, self.fixture.segmentation_node,
                                           subjectID=subject, reader="R1", extraColumns={"center": "A"},
                                           outputTable=table)
        rows = self.logic.rowsFromTable(table)
        history = self.logic.provenanceHistory(table, required=True)
        self.assertEqual(len(history), 2)
        self.assertEqual({row["run_id"] for row in rows}, {record["run_id"] for record in history})
        for subject in ("case-1", "case-2"):
            statuses = [row["status"] for row in rows if row["subject_id"] == subject]
            self.assertEqual(len(statuses), len(rows) / 2)
            self.assertIn("ok", statuses)
            self.assertLessEqual(set(statuses), {"ok", "not_computed"})
        self.assertEqual({row["roi_name"] for row in rows}, {SEGMENT_NAME})
        self.assertEqual({row["config"] for row in rows}, {"standard_fbn_32"})
        self.assertEqual({(row["reader"], row["center"], row["modality"]) for row in rows}, {("R1", "A", "")})
        self.assertEqual(_scene_node_ids() - scene_before, {table.GetID()})
        self.assertEqual(list(self.logic.jobsRoot().glob("job-*")), [])

    def test_roi_refinement_controls_validate_persist_and_load_legacy_profiles(self) -> None:
        widget = self._feedback_widget()
        widget.ui.additionalConfigCombo.setCurrentIndex(1)
        self.assertFalse(widget.ui.resegmentGroup.checked)
        self.assertFalse(widget.ui.rangeMinLineEdit.enabled)
        self.assertFalse(widget.ui.outlierGroup.checked)
        widget.ui.resegmentGroup.setChecked(True)
        self.assertTrue(widget.ui.rangeMinLineEdit.enabled)
        self.assertFalse(widget.ui.runButton.enabled)
        self.assertIn("at least one bound", widget.ui.readinessLabel.text)
        widget.ui.rangeMinLineEdit.setText("-50")
        widget.ui.rangeMaxLineEdit.setText("500")
        widget.ui.outlierGroup.setChecked(True)
        widget.ui.outlierSigmaSpinBox.setValue(1.5)
        widget.ui.resegmentTargetCombo.setCurrentIndex(1)
        widget.ui.outlierTargetCombo.setCurrentIndex(2)
        self.assertTrue(widget.ui.runButton.enabled)
        state = widget._inlineStateFromGUI()
        self.assertEqual(widget._storedInlineState(), state)
        steps = build_inline_configuration_document(state)["configs"]["in_app"]["steps"]
        self.assertEqual(steps[1]["params"]["apply_to"], "intensity")
        self.assertEqual(steps[2]["params"]["apply_to"], "morph")
        widget.ui.rangeMinLineEdit.setText("501")
        self.assertFalse(widget.ui.runButton.enabled)
        self.assertIn("must not exceed", widget.ui.readinessLabel.text)
        widget.ui.rangeMinLineEdit.setText("NaN")
        self.assertFalse(widget.ui.runButton.enabled)
        self.assertIn("finite number", widget.ui.readinessLabel.text)
        widget.ui.resegmentGroup.setChecked(False)
        self.assertTrue(widget.ui.runButton.enabled)
        # Previously saved profiles omit these optional controls entirely.
        legacy = build_profile("Legacy", ["standard_fbn_32"], default_inline_state())
        legacy["inline_state"] = {key: value for key, value in legacy["inline_state"].items()
                                  if key not in ROI_REFINEMENT_DEFAULTS}
        legacy_path = self.temporary_directory / "legacy.json"
        legacy_path.write_text(json.dumps(legacy), encoding="utf-8")
        dialog_qt = _qt_with(
            QFileDialog=SimpleNamespace(getOpenFileName=lambda *args: str(legacy_path)))
        with patch.object(gui_module, "qt", dialog_qt), patch.object(slicer.util, "errorDisplay") as errors:
            widget.onLoadProfile()
            errors.assert_not_called()
        self.assertFalse(widget.ui.resegmentGroup.checked)
        self.assertFalse(widget.ui.outlierGroup.checked)
        self.assertEqual(widget._inlineStateFromGUI(), default_inline_state())
        self.assertTrue(widget.ui.runButton.enabled)

    def test_inline_keyboard_edits_preserve_decimals_and_filter_editors(self) -> None:
        widget = self._feedback_widget()
        widget.ui.additionalConfigCombo.setCurrentIndex(1)
        widget.ui.outlierGroup.setChecked(True)

        def type_number(spin, text):
            spin.selectAll()
            for character in text:
                for event_type in (qt.QEvent.KeyPress, qt.QEvent.KeyRelease):
                    event = qt.QKeyEvent(event_type, ord(character), qt.Qt.NoModifier, character)
                    qt.QApplication.sendEvent(spin, event)

        type_number(widget.ui.outlierSigmaSpinBox, "1.5")
        self.assertEqual(widget.ui.outlierSigmaSpinBox.value, 1.5)
        self.assertEqual(widget._storedInlineState()["outlier_sigma"], 1.5)

        widget.ui.filterGroup.setChecked(True)
        parameter = widget._filterParameterWidgets["sigma_mm"]
        type_number(parameter, "2.75")
        self.assertIs(widget._filterParameterWidgets["sigma_mm"], parameter)
        self.assertEqual(parameter.value, 2.75)
        self.assertEqual(widget._storedInlineState()["filter_params"]["sigma_mm"], 2.75)

        # Only our own write-back is suppressed; external scene edits still refresh.
        state = widget._storedInlineState()
        state["outlier_sigma"] = 2.25
        widget._parameterNode.SetParameter(gui_module.PARAM_INLINE_CONFIG, json.dumps(state))
        self.assertEqual(widget.ui.outlierSigmaSpinBox.value, 2.25)

    def test_filter_controls_follow_the_type_and_persist(self) -> None:
        widget = self._feedback_widget()
        widget.ui.additionalConfigCombo.setCurrentIndex(1)
        self.assertFalse(widget.ui.filterGroup.checked)
        widget.ui.filterGroup.setChecked(True)
        for filter_type in gui_module.FILTER_PARAMETERS:
            with self.subTest(filter_type=filter_type):
                widget.ui.filterTypeCombo.setCurrentIndex(widget.ui.filterTypeCombo.findData(filter_type))
                self.assertEqual(widget._inlineStateFromGUI()["filter_params"], filter_defaults(filter_type))
                self.assertTrue(widget.ui.runButton.enabled, widget.ui.readinessLabel.text)
        widget.ui.filterTypeCombo.setCurrentIndex(widget.ui.filterTypeCombo.findData("laws"))
        widget._filterParameterWidgets["kernel"].setText("L5")
        self.assertIn("look like L5E5E5", widget.ui.readinessLabel.text)
        self.assertFalse(widget.ui.runButton.enabled)
        widget._filterParameterWidgets["kernel"].setText("E5L5S5")
        widget.ui.filterBoundaryCombo.setCurrentIndex(widget.ui.filterBoundaryCombo.findText("nearest"))
        state = widget._storedInlineState()
        self.assertEqual((state["filter_type"], state["filter_boundary"]), ("laws", "nearest"))
        self.assertEqual(state["filter_params"]["kernel"], "E5L5S5")
        steps = build_inline_configuration_document(state)["configs"]["in_app"]["steps"]
        self.assertEqual([step["step"] for step in steps], ["resample", "filter", "discretise", "extract_features"])
        widget.updateGUIFromParameterNode()
        self.assertEqual(widget._inlineStateFromGUI(), state)

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
            self.assertEqual({row["config"] for row in rows}, {"standard_fbn_32"})
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
                    == f"{row['config']}__{row['feature_key']}"
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
                            row["config"],
                            row["family"],
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
