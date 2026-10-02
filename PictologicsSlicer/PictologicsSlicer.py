"""3D Slicer user interface and orchestration for Pictologics radiomics.

Pictologics is intentionally never imported in this process.  Its dependencies
are installed into an extension-private target and used by PictologicsCLI in a
separate process, protecting Slicer's shared NumPy and Pillow installations.
"""

from __future__ import annotations

import csv
import json
import logging
import math
import os
import platform
import shutil
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import qt
import slicer
import vtk
from PictologicsLib.batch import discover_cases
from PictologicsLib.batch_reports import (
    REPORT_ATTRIBUTE,
    REPORT_COLUMNS,
    REPORT_METADATA_ATTRIBUTE,
    REPORT_SCHEMA_VERSION,
    export_report,
    new_report,
    validate_report,
)
from PictologicsLib.dependencies import (
    activate_dependency_target,
    build_pip_install_args,
    dependency_environment_path,
    dependency_paths,
    inspect_target,
    parse_pictologics_requirement,
    remove_inactive_environments,
)
from PictologicsLib.diagnostics import diagnostics_text
from PictologicsLib.exports import export_file_set
from PictologicsLib.inline_config import (
    FILTER_BOUNDARIES,
    FILTER_PARAMETERS,
    MASK_TARGETS,
    build_inline_configuration_document,
    default_inline_state,
    filter_defaults,
    lint_configuration_document,
    parse_configuration_check,
    preset_configuration_document,
    preset_names,
)
from PictologicsLib.jobs import build_job_manifest, sha256_file, write_job_manifest
from PictologicsLib.memory import BYTES_PER_VOXEL, largest_voxel_count
from PictologicsLib.persistence import (
    SNAPSHOT_ATTRIBUTE,
    WARNING_ATTRIBUTE,
    decode_values,
    encode_values,
    table_identity,
)
from PictologicsLib.profiles import build_profile, validate_profile
from PictologicsLib.progress import current_roi_index, elapsed_text
from PictologicsLib.result_columns import (
    SCANNER_COLUMNS,
    build_result_columns,
    parse_extra_columns,
    scanner_details_from_sidecar,
    scanner_value,
    sidecar_path,
)
from PictologicsLib.results import (
    LONG_RESULT_COLUMNS,
    RESULT_PAYLOAD_SCHEMA_VERSION,
    configuration_conflicts,
    export_rows,
    extra_columns,
    is_result_table_columns,
    load_result_payload,
    rows_to_wide,
    validate_result_payload,
)
from PictologicsLib.staging import job_may_be_running, process_is_alive, read_pid_marker
from PictologicsWidgets.results_browser import ResultsBrowser
from slicer.ScriptedLoadableModule import (
    ScriptedLoadableModule,
    ScriptedLoadableModuleLogic,
    ScriptedLoadableModuleTest,
    ScriptedLoadableModuleWidget,
)
from slicer.util import VTKObservationMixin

LOGGER = logging.getLogger(__name__)

EXTENSION_VERSION = "0.1.0"
# Hardcoded because this process never imports Pictologics. It is kept in lockstep
# with the adopted release by scripts/check_pictologics_api.py (release preflight)
# and enforced per job: the worker rejects any requested standard configuration that
# the installed Pictologics does not expose. Update this on a version bump.
STANDARD_CONFIGURATIONS = (
    "standard_fbn_8",
    "standard_fbn_16",
    "standard_fbn_32",
    "standard_fbs_8",
    "standard_fbs_16",
    "standard_fbs_32",
)
DEFAULT_CONFIGURATION = "standard_fbn_32"
# Ask before a run when one copy of the resampled scan needs more memory than this.
LARGE_IMAGE_BYTES = 1_000_000_000

PARAM_WHOLE_VOLUME = "WholeVolume"
PARAM_SELECTED_SEGMENTS = "SelectedSegments"
PARAM_STANDARD_CONFIGURATIONS = "StandardConfigurations"
PARAM_CUSTOM_CONFIGURATION = "CustomConfigurationPath"
PARAM_SUBJECT_ID = "SubjectID"
PARAM_READER = "Reader"
PARAM_EXTRA_COLUMNS = "ExtraColumns"
PARAM_CROP = "CropToRegion"
PARAM_APPEND_RESULTS = "AppendResults"
PARAM_ADDITIONAL_SOURCE = "AdditionalConfigSource"
PARAM_INLINE_CONFIG = "InlineConfigState"

# Additional-configuration source selector values, aligned with the combo box order.
ADDITIONAL_SOURCES = ("none", "inline", "file")

# Feature-family checkbox wiring for the in-app builder (family -> UI attribute).
FAMILY_CHECKBOXES = (
    ("intensity", "familyIntensityCheckBox"),
    ("morphology", "familyMorphologyCheckBox"),
    ("texture", "familyTextureCheckBox"),
    ("histogram", "familyHistogramCheckBox"),
    ("ivh", "familyIvhCheckBox"),
    ("spatial_intensity", "familySpatialIntensityCheckBox"),
    ("local_intensity", "familyLocalIntensityCheckBox"),
)

FILTER_LABELS = {
    "mean": "Mean",
    "log": "Laplacian of Gaussian (LoG)",
    "laws": "Laws texture energy",
    "gabor": "Gabor",
    "wavelet": "Separable wavelet",
    "simoncelli": "Simoncelli wavelet",
}

REF_INPUT_VOLUME = "InputVolume"
REF_SEGMENTATION = "Segmentation"
REF_OUTPUT_TABLE = "OutputTable"

ITEM_VALUE_ROLE = int(qt.Qt.UserRole)


def _fsync_parent_dir(path: Path) -> None:
    """Persist a rename by fsyncing the destination's directory.

    Directory fsync is unsupported on some platforms (notably Windows), so any
    failure to open/sync the directory is ignored.
    """

    try:
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


class DependencyInstallDeclined(RuntimeError):
    """Raised internally when the user declines the isolated installation."""


_DEFERRED_JOB_CLEANUPS: dict[str, "_DeferredJobCleanup"] = {}


class _DeferredJobCleanup:
    """Keep a cancelled CLI node alive until its worker releases staged inputs."""

    def __init__(self, cliNode, job: dict[str, Any], *, cancel: bool):
        self.key = uuid.uuid4().hex
        self.cliNode = cliNode
        self.job = job
        self.observerTag = None
        self.finished = False
        self.startedAt = time.monotonic()
        _DEFERRED_JOB_CLEANUPS[self.key] = self
        if self.cliNode is not None:
            try:
                self.observerTag = self.cliNode.AddObserver(
                    vtk.vtkCommand.ModifiedEvent, self._onModified
                )
            except RuntimeError:
                self.cliNode = None
        if cancel and self.cliNode is not None:
            try:
                if self.cliNode.IsBusy():
                    self.cliNode.Cancel()
            except RuntimeError:
                pass
        self._poll()

    def _onModified(self, caller=None, event=None):
        self._poll()

    def _poll(self):
        if self.finished:
            return
        try:
            nodeBusy = self.cliNode is not None and self.cliNode.IsBusy()
        except RuntimeError:
            nodeBusy = False
        workerAlive = PictologicsSlicerLogic.jobWorkerIsAlive(self.job)
        if (
            not nodeBusy
            and not workerAlive
            and time.monotonic() - self.startedAt >= 2.0
        ):
            self._finish()
            return
        qt.QTimer.singleShot(500, self._poll)

    def _finish(self):
        if self.finished:
            return
        self.finished = True
        if self.cliNode is not None and self.observerTag is not None:
            try:
                self.cliNode.RemoveObserver(self.observerTag)
            except RuntimeError:
                pass
        try:
            PictologicsSlicerLogic.cleanupJob(self.job)
        finally:
            if self.cliNode is not None:
                try:
                    if self.cliNode.GetScene() == slicer.mrmlScene:
                        slicer.mrmlScene.RemoveNode(self.cliNode)
                except RuntimeError:
                    pass
            self.cliNode = None
            self.observerTag = None
            _DEFERRED_JOB_CLEANUPS.pop(self.key, None)


class _ResultScenePersistence:
    """Keep snapshots current and restore only imported scene tables.

    Slicer's MRB writer does not emit StartSaveEvent. Observe table changes instead
    of relying on a save hook, and never interpret cached values during normal
    browsing/export (which could overwrite a user's subsequent edits).
    """

    def __init__(self):
        self.scene = slicer.mrmlScene
        self.observers = []
        self.nodes = {}
        self.revisions = {}
        self.busy = False
        self.beforeImport = set()
        for event, callback in (
            (self.scene.NodeAddedEvent, self._added),
            (self.scene.NodeRemovedEvent, self._removed),
            (self.scene.StartImportEvent, self._startImport),
            (self.scene.EndImportEvent, self._endImport),
        ):
            self.observers.append(self.scene.AddObserver(event, callback))
        for node in slicer.util.getNodesByClass("vtkMRMLTableNode"):
            self._watch(node)

    def close(self):
        for tag in self.observers:
            self.scene.RemoveObserver(tag)
        for node, tag in self.nodes.values():
            node.RemoveObserver(tag)
        self.observers.clear()
        self.nodes.clear()
        self.revisions.clear()

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def _added(self, caller, event, node):
        if node.IsA("vtkMRMLTableNode"):
            self._watch(node)

    @vtk.calldata_type(vtk.VTK_OBJECT)
    def _removed(self, caller, event, node):
        key = node.GetID()
        if key in self.nodes:
            watched, tag = self.nodes.pop(key)
            watched.RemoveObserver(tag)
            self.revisions.pop(key, None)

    def _watch(self, node):
        key = node.GetID()
        if key not in self.nodes:
            self.nodes[key] = (node, node.AddObserver(vtk.vtkCommand.ModifiedEvent, self._changed))
        self._changed(node)

    @staticmethod
    def _contents(node):
        table = node.GetTable()
        columns = [str(table.GetColumnName(index)) for index in range(table.GetNumberOfColumns())]
        if not is_result_table_columns(columns):
            raise ValueError("The table no longer has the Pictologics result columns")
        text_columns = [name for name in columns if name != "value"]
        text_rows = [[str(table.GetColumnByName(name).GetValue(row)) for name in text_columns]
                     for row in range(table.GetNumberOfRows())]
        values = [float(table.GetColumnByName("value").GetValue(row)) for row in range(table.GetNumberOfRows())]
        return table_identity(text_columns, text_rows), values

    @staticmethod
    def _revision(node):
        table = node.GetTable()
        return (table.GetAddressAsString(""), table.GetMTime())

    @staticmethod
    def _isResult(node):
        return node.GetAttribute("Pictologics.ResultSchemaVersion") == str(RESULT_PAYLOAD_SCHEMA_VERSION)

    def _warning(self, node, message):
        node.SetAttribute(WARNING_ATTRIBUTE, message)
        LOGGER.warning("Pictologics scene persistence: %s", message)

    def _changed(self, node, event=None):
        if self.busy or self.scene.IsImporting() or self.scene.IsRestoring() or self.scene.IsClosing():
            return
        if not self._isResult(node) or self.revisions.get(node.GetID()) == self._revision(node):
            return
        self.busy = True
        try:
            identity, values = self._contents(node)
            node.SetAttribute(SNAPSHOT_ATTRIBUTE, encode_values(values, identity))
        except (ValueError, TypeError) as exc:
            node.SetAttribute(SNAPSHOT_ATTRIBUTE, None)
            self._warning(node, f"Exact-value backup unavailable: {exc}")
        finally:
            self.revisions[node.GetID()] = self._revision(node)
            self.busy = False

    def _startImport(self, caller=None, event=None):
        self.beforeImport = set(self.nodes)

    def _endImport(self, caller=None, event=None):
        # Importing another scene must not restore stale backups into live tables.
        for key, (node, _) in list(self.nodes.items()):
            if key not in self.beforeImport:
                self._restore(node)
        self.beforeImport.clear()

    def _restore(self, node):
        if not self._isResult(node):
            return
        self.busy = True
        try:
            snapshot = node.GetAttribute(SNAPSHOT_ATTRIBUTE)
            if not snapshot:
                self._warning(node, "This older scene has no exact-value backup; previously rounded digits cannot be recovered.")
                return
            identity, current = self._contents(node)
            exact = decode_values(snapshot, identity, current)
            column = node.GetTable().GetColumnByName("value")
            for row, value in enumerate(exact):
                column.SetValue(row, value)
            column.Modified()
            node.GetTable().Modified()
        except (ValueError, TypeError) as exc:
            self._warning(node, f"Exact values were not restored; the loaded table was left unchanged: {exc}")
        finally:
            self.revisions[node.GetID()] = self._revision(node)
            self.busy = False


def _resultPersistence():
    previous = getattr(slicer.modules, "_pictologicsResultPersistence", None)
    if not isinstance(previous, _ResultScenePersistence) or previous.scene != slicer.mrmlScene:
        if previous is not None:
            previous.close()
        previous = _ResultScenePersistence()
        slicer.modules._pictologicsResultPersistence = previous
    return previous


class PictologicsSlicer(ScriptedLoadableModule):
    """Module metadata shown by Slicer."""

    def __init__(self, parent):
        super().__init__(parent)
        _resultPersistence()
        self.parent.title = "Pictologics"
        self.parent.categories = ["Informatics"]
        # Override Slicer's SVG-first discovery in source checkouts containing the old icon.
        self.parent.icon = qt.QIcon(self.resourcePath("Icons/PictologicsSlicer.png"))
        self.parent.dependencies = ["Segmentations", "Tables"]
        self.parent.contributors = ["Márton Kolossváry"]
        self.parent.helpText = (
            "Run Pictologics radiomics on a scalar volume, the whole volume, "
            "and/or independently selected segments. Computation runs in a "
            "cancellable background CLI process with isolated dependencies. "
            'See the <a href="https://github.com/martonkolossvary/SlicerPictologics#readme">'
            "documentation</a> for a tutorial."
        )
        self.parent.acknowledgementText = (
            "This extension uses the open-source Pictologics radiomics package."
        )


class PictologicsSlicerWidget(ScriptedLoadableModuleWidget, VTKObservationMixin):
    """Slicer-facing controller; computation is delegated to PictologicsCLI."""

    def __init__(self, parent=None):
        ScriptedLoadableModuleWidget.__init__(self, parent)
        VTKObservationMixin.__init__(self)
        self.logic: PictologicsSlicerLogic | None = None
        self._parameterNode = None
        self._updatingGUIFromParameterNode = False
        self._updatingParameterNodeFromGUI = False
        self._activeJob: dict[str, Any] | None = None
        self._cliNode = None
        self._cliObserverTag = None
        self._finishingJob = False
        self._dependencyOperationInProgress = False
        self._cliProgressIndeterminate = False
        self._runStartedAt: float | None = None
        self._runFeedbackTimer = None
        self._cancelRequested = False
        self._continuousOutputNode = None
        self._lastPayload: dict[str, Any] | None = None
        self._resultsBrowser = None
        self._tableOperationInProgress = False
        self._sceneGeneration = 0
        self._profilePath: Path | None = None
        self._profileName = "Radiomics profile"
        self._filterParameterWidgets: dict[str, Any] = {}
        # A running batch: its cases, the current index, the loaded nodes, and failures.
        self._batch: dict[str, Any] | None = None
        # Session-only, structured facts. Never store exception text or scene names.
        self._diagnosticOperation: dict[str, Any] = {}
        self._diagnosticRun: dict[str, Any] = {}
        self._diagnosticsPreview = ""

    def setup(self):
        ScriptedLoadableModuleWidget.setup(self)

        uiWidget = slicer.util.loadUI(self.resourcePath("UI/PictologicsSlicer.ui"))
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)
        # Names from user data must remain plain text, including strings with < >.
        for label in (self.ui.readinessLabel, self.ui.statusLabel, self.ui.scannerDetailsLabel):
            label.setTextFormat(qt.Qt.PlainText)
        self.ui.elapsedTimeLabel.hide()
        self._runFeedbackTimer = qt.QTimer(uiWidget)
        self._runFeedbackTimer.setInterval(1000)
        self._runFeedbackTimer.connect("timeout()", self._updateRunFeedback)
        uiWidget.setMRMLScene(slicer.mrmlScene)
        # Do not depend on Designer signal wiring for scene propagation.
        for selector in (
            self.ui.inputVolumeSelector,
            self.ui.segmentationSelector,
            self.ui.outputTableSelector,
        ):
            selector.setMRMLScene(slicer.mrmlScene)

        self.logic = PictologicsSlicerLogic()
        try:
            removed = self.logic.purgeStaleJobs()
            if removed:
                LOGGER.info(
                    "Removed %d stale Pictologics staging directorie(s)", removed
                )
        except Exception:
            LOGGER.exception("Could not purge stale Pictologics staging directories")
        self.logic.removeRetiredEnvironments()
        self._populateStandardConfigurations()
        for filterType in FILTER_PARAMETERS:
            self.ui.filterTypeCombo.addItem(FILTER_LABELS[filterType], filterType)
        for boundary in FILTER_BOUNDARIES:
            self.ui.filterBoundaryCombo.addItem(boundary)
        self._filterParametersLayout = qt.QFormLayout(self.ui.filterParametersWidget)
        self._filterParametersLayout.setContentsMargins(0, 0, 0, 0)
        self.ui.filterTypeCombo.setCurrentIndex(self.ui.filterTypeCombo.findData("log"))
        self._buildFilterParameters("log", {})
        self._connectSignals()
        self._refreshBatchReports()

        self.addObserver(
            slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose
        )
        self.addObserver(
            slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose
        )
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndImportEvent, self._refreshBatchReports)
        self.addObserver(slicer.mrmlScene, slicer.mrmlScene.EndRestoreEvent, self._refreshBatchReports)
        self.initializeParameterNode()
        self.refreshPackageStatus()

    def cleanup(self):
        self._sceneGeneration += 1
        # A singleShot callback may already be queued between batch cases. Make
        # it inert before detaching the UI; workers use staged files, not these nodes.
        if self._batch is not None:
            self._markBatchInterrupted()
        self._removeBatchNodes()
        self._batch = None
        if self._resultsBrowser is not None:
            self._resultsBrowser.close()
        self._stopRunFeedback()
        self.setParameterNode(None)
        self._handoffActiveJobCleanup(cancel=True)
        self.removeObservers()
        if self._runFeedbackTimer is not None:
            # Break the Qt signal -> Python widget -> C++ parent ownership cycle
            # before the module's widgets are destroyed.
            self._runFeedbackTimer.disconnect("timeout()", self._updateRunFeedback)
            self._runFeedbackTimer = None

    def enter(self):
        self.initializeParameterNode()
        self._refreshBatchReports()
        if self.logic is not None:
            try:
                self.logic.purgeStaleJobs()
            except Exception:
                LOGGER.exception(
                    "Could not purge stale Pictologics staging directories"
                )
            self.logic.removeRetiredEnvironments()
        self.refreshPackageStatus()
        self._updateRunState()

    def exit(self):
        self.updateParameterNodeFromGUI()

    def _connectSignals(self):
        self.ui.inputVolumeSelector.connect(
            "currentNodeChanged(vtkMRMLNode*)", self.onControlsChanged
        )
        self.ui.inputVolumeSelector.connect(
            "currentNodeChanged(vtkMRMLNode*)", self._updateScannerDetails
        )
        self.ui.readerLineEdit.connect("textChanged(QString)", self.onControlsChanged)
        self.ui.extraColumnsTextEdit.connect("textChanged()", self.onControlsChanged)
        self.ui.segmentationSelector.connect(
            "currentNodeChanged(vtkMRMLNode*)", self.onSegmentationChanged
        )
        self.ui.outputTableSelector.connect(
            "currentNodeChanged(vtkMRMLNode*)", self.onControlsChanged
        )
        self.ui.wholeVolumeCheckBox.connect("toggled(bool)", self.onControlsChanged)
        self.ui.cropCheckBox.connect("toggled(bool)", self.onControlsChanged)
        self.ui.appendResultsCheckBox.connect("toggled(bool)", self.onControlsChanged)
        self.ui.segmentListWidget.connect(
            "itemChanged(QListWidgetItem*)", self.onControlsChanged
        )
        self.ui.standardConfigListWidget.connect(
            "itemChanged(QListWidgetItem*)", self.onControlsChanged
        )
        self.ui.customConfigPathLineEdit.connect(
            "textChanged(QString)", self.onControlsChanged
        )
        self.ui.subjectIdLineEdit.connect(
            "textChanged(QString)", self.onControlsChanged
        )
        self.ui.additionalConfigCombo.connect(
            "currentIndexChanged(int)", self.onAdditionalSourceChanged
        )
        for _family, attribute in FAMILY_CHECKBOXES:
            getattr(self.ui, attribute).connect("toggled(bool)", self.onControlsChanged)
        self.ui.resampleCheckBox.connect("toggled(bool)", self.onControlsChanged)
        self.ui.resegmentGroup.connect("toggled(bool)", self.onControlsChanged)
        self.ui.filterGroup.connect("toggled(bool)", self.onControlsChanged)
        self.ui.filterTypeCombo.connect("currentIndexChanged(int)", self.onFilterTypeChanged)
        self.ui.filterBoundaryCombo.connect("currentIndexChanged(int)", self.onControlsChanged)
        self.ui.outlierGroup.connect("toggled(bool)", self.onControlsChanged)
        for control in (self.ui.rangeMinLineEdit, self.ui.rangeMaxLineEdit):
            control.connect("textChanged(QString)", self.onControlsChanged)
        for combo in (self.ui.resegmentTargetCombo, self.ui.outlierTargetCombo):
            combo.connect("currentIndexChanged(int)", self.onControlsChanged)
        for spin in (
            self.ui.resampleXSpinBox,
            self.ui.resampleYSpinBox,
            self.ui.resampleZSpinBox,
            self.ui.discretiseValueSpinBox,
            self.ui.outlierSigmaSpinBox,
        ):
            spin.connect("valueChanged(double)", self.onControlsChanged)
        self.ui.interpolationCombo.connect(
            "currentIndexChanged(int)", self.onControlsChanged
        )
        self.ui.discretiseCheckBox.connect("toggled(bool)", self.onControlsChanged)
        self.ui.discretiseMethodCombo.connect(
            "currentIndexChanged(int)", self.onControlsChanged
        )
        self.ui.sourceModeCombo.connect(
            "currentIndexChanged(int)", self.onControlsChanged
        )
        self.ui.sentinelValueLineEdit.connect(
            "textChanged(QString)", self.onControlsChanged
        )
        self.ui.newFromPresetButton.connect("clicked()", self.onNewFromPreset)
        self.ui.validateConfigButton.connect("clicked()", self.onValidateConfiguration)
        self.ui.browseConfigButton.connect("clicked()", self.onBrowseConfiguration)
        self.ui.updatePackageButton.connect("clicked()", self.onUpdatePackage)
        self.ui.refreshDiagnosticsButton.connect("clicked()", self.onRefreshDiagnostics)
        self.ui.copyDiagnosticsButton.connect("clicked()", self.onCopyDiagnostics)
        self.ui.runButton.connect("clicked()", self.onRun)
        self.ui.batchBrowseButton.connect("clicked()", self.onBrowseBatchFolder)
        self.ui.runBatchButton.connect("clicked()", self.onRunBatch)
        self.ui.viewBatchReportButton.connect("clicked()", self.onViewBatchReport)
        self.ui.exportBatchReportButton.connect("clicked()", self.onExportBatchReport)
        self.ui.batchReportCombo.connect("currentIndexChanged(int)", lambda _index: self._updateRunState())
        self.ui.cancelButton.connect("clicked()", self.onCancel)
        self.ui.exportButton.connect("clicked()", self.onExport)
        self.ui.browseResultsButton.connect("clicked()", self.onBrowseResults)
        self.ui.saveProfileButton.connect("clicked()", self.onSaveProfile)
        self.ui.loadProfileButton.connect("clicked()", self.onLoadProfile)
        self.ui.duplicateProfileButton.connect("clicked()", self.onDuplicateProfile)

    def _populateStandardConfigurations(self):
        self.ui.standardConfigListWidget.blockSignals(True)
        self.ui.standardConfigListWidget.clear()
        for configuration in STANDARD_CONFIGURATIONS:
            item = qt.QListWidgetItem(configuration)
            item.setData(ITEM_VALUE_ROLE, configuration)
            item.setFlags(item.flags() | qt.Qt.ItemIsUserCheckable)
            item.setCheckState(
                qt.Qt.Checked
                if configuration == DEFAULT_CONFIGURATION
                else qt.Qt.Unchecked
            )
            self.ui.standardConfigListWidget.addItem(item)
        self.ui.standardConfigListWidget.blockSignals(False)

    def initializeParameterNode(self):
        if self.logic is None:
            return
        parameterNode = self.logic.getParameterNode()
        self.logic.setDefaultParameters(parameterNode)
        self.setParameterNode(parameterNode)

    def setParameterNode(self, parameterNode):
        if parameterNode is self._parameterNode:
            return
        if self._parameterNode is not None:
            self.removeObserver(
                self._parameterNode,
                vtk.vtkCommand.ModifiedEvent,
                self.updateGUIFromParameterNode,
            )
        self._parameterNode = parameterNode
        if self._parameterNode is not None:
            self.addObserver(
                self._parameterNode,
                vtk.vtkCommand.ModifiedEvent,
                self.updateGUIFromParameterNode,
            )
        self.updateGUIFromParameterNode()

    def onSceneStartClose(self, caller=None, event=None):
        self._sceneGeneration += 1
        if self._resultsBrowser is not None:
            self._resultsBrowser.close()
        self._profilePath = None
        self._profileName = "Radiomics profile"
        self.ui.profileStatusLabel.setText("Profiles contain settings only; no patient data.")
        self._stopRunFeedback()
        if self._batch is not None:
            self._markBatchInterrupted()
            self._batch["stopped"] = True
            self._batch["scene_closing"] = True
            self._batch["nodes"] = []
            self._batch["restore"] = None
        if self._activeJob is not None:
            # A CLI result belongs to the scene in which it was submitted. Never
            # let a late completion write patient A's rows into a newly loaded scene.
            self._activeJob["discard_results"] = True
            self._cancelRequested = True
            self.ui.statusLabel.setText("Scene closing; discarding this run's results.")
            if self._nodeIsBusy(self._cliNode):
                self._cliNode.Cancel()
        self.setParameterNode(None)
        self._refreshBatchReports()

    def onSceneEndClose(self, caller=None, event=None):
        self._refreshBatchReports()
        if self._activeJob is not None and self._activeJob.get("discard_results"):
            try:
                cliStillObserved = (
                    self._cliNode is not None
                    and self._cliNode.GetScene() == slicer.mrmlScene
                )
            except RuntimeError:
                cliStillObserved = False
            if not cliStillObserved:
                # Scene clearing may remove the CLI node before it emits its final
                # status. A cleanup-only observer retains the node/job until the
                # worker process releases the staged image and masks.
                LOGGER.warning(
                    "Discarded Pictologics job after scene close; deferring cleanup of %s",
                    self._activeJob.get("work_dir"),
                )
                self._handoffActiveJobCleanup(cancel=True)
        if self.parent.isEntered:
            self.initializeParameterNode()

    @staticmethod
    def _jsonList(value: str) -> list[str]:
        try:
            parsed = json.loads(value or "[]")
        except (TypeError, ValueError):
            return []
        return [str(item) for item in parsed] if isinstance(parsed, list) else []

    def updateGUIFromParameterNode(self, caller=None, event=None):
        if (
            self._parameterNode is None
            or not hasattr(self, "ui")
            or self._updatingParameterNodeFromGUI
        ):
            return
        self._updatingGUIFromParameterNode = True
        try:
            self.ui.inputVolumeSelector.setCurrentNode(
                self._parameterNode.GetNodeReference(REF_INPUT_VOLUME)
            )
            self.ui.segmentationSelector.setCurrentNode(
                self._parameterNode.GetNodeReference(REF_SEGMENTATION)
            )
            self.ui.outputTableSelector.setCurrentNode(
                self._parameterNode.GetNodeReference(REF_OUTPUT_TABLE)
            )
            self.ui.wholeVolumeCheckBox.setChecked(
                self._parameterNode.GetParameter(PARAM_WHOLE_VOLUME) == "true"
            )
            self.ui.appendResultsCheckBox.setChecked(
                self._parameterNode.GetParameter(PARAM_APPEND_RESULTS) == "true"
            )
            self.ui.cropCheckBox.setChecked(self._parameterNode.GetParameter(PARAM_CROP) == "true")
            self.ui.customConfigPathLineEdit.setText(
                self._parameterNode.GetParameter(PARAM_CUSTOM_CONFIGURATION)
            )
            self.ui.subjectIdLineEdit.setText(
                self._parameterNode.GetParameter(PARAM_SUBJECT_ID)
            )
            self.ui.readerLineEdit.setText(self._parameterNode.GetParameter(PARAM_READER))
            extraText = self._parameterNode.GetParameter(PARAM_EXTRA_COLUMNS)
            # Setting the same text again would move the cursor while the user types.
            if str(self.ui.extraColumnsTextEdit.toPlainText()) != extraText:
                self.ui.extraColumnsTextEdit.setPlainText(extraText)

            selectedConfigurations = set(
                self._jsonList(
                    self._parameterNode.GetParameter(PARAM_STANDARD_CONFIGURATIONS)
                )
            )
            self.ui.standardConfigListWidget.blockSignals(True)
            for index in range(self.ui.standardConfigListWidget.count):
                item = self.ui.standardConfigListWidget.item(index)
                item.setCheckState(
                    qt.Qt.Checked
                    if str(item.data(ITEM_VALUE_ROLE)) in selectedConfigurations
                    else qt.Qt.Unchecked
                )
            self.ui.standardConfigListWidget.blockSignals(False)

            selectedSegments = set(
                self._jsonList(
                    self._parameterNode.GetParameter(PARAM_SELECTED_SEGMENTS)
                )
            )
            self._rebuildSegmentList(selectedSegments)

            source = self._parameterNode.GetParameter(PARAM_ADDITIONAL_SOURCE) or "none"
            self.ui.additionalConfigCombo.setCurrentIndex(
                ADDITIONAL_SOURCES.index(source)
                if source in ADDITIONAL_SOURCES
                else 0
            )
            self._applyInlineState(self._storedInlineState())
            self._updateConfigVisibility()
        finally:
            self._updatingGUIFromParameterNode = False
        self._updateScannerDetails()
        self._updateRunState()

    def updateParameterNodeFromGUI(self):
        if (
            self._parameterNode is None
            or self._updatingGUIFromParameterNode
            or self._updatingParameterNodeFromGUI
        ):
            return
        wasModified = self._parameterNode.StartModify()
        # Keep the live editor intact while persisting its own changes. Replaying
        # them through updateGUIFromParameterNode reformats a partially typed
        # decimal and rebuilds dynamic filter widgets beneath the user's cursor.
        self._updatingParameterNodeFromGUI = True
        try:
            self._parameterNode.SetNodeReferenceID(
                REF_INPUT_VOLUME,
                self._nodeID(self.ui.inputVolumeSelector.currentNode()),
            )
            self._parameterNode.SetNodeReferenceID(
                REF_SEGMENTATION,
                self._nodeID(self.ui.segmentationSelector.currentNode()),
            )
            self._parameterNode.SetNodeReferenceID(
                REF_OUTPUT_TABLE,
                self._nodeID(self.ui.outputTableSelector.currentNode()),
            )
            self._parameterNode.SetParameter(
                PARAM_WHOLE_VOLUME,
                "true" if self.ui.wholeVolumeCheckBox.checked else "false",
            )
            self._parameterNode.SetParameter(
                PARAM_APPEND_RESULTS,
                "true" if self.ui.appendResultsCheckBox.checked else "false",
            )
            self._parameterNode.SetParameter(
                PARAM_CROP, "true" if self.ui.cropCheckBox.checked else "false"
            )
            self._parameterNode.SetParameter(
                PARAM_CUSTOM_CONFIGURATION,
                str(self.ui.customConfigPathLineEdit.text).strip(),
            )
            self._parameterNode.SetParameter(
                PARAM_SUBJECT_ID, str(self.ui.subjectIdLineEdit.text).strip()
            )
            self._parameterNode.SetParameter(PARAM_READER, str(self.ui.readerLineEdit.text))
            self._parameterNode.SetParameter(
                PARAM_EXTRA_COLUMNS, str(self.ui.extraColumnsTextEdit.toPlainText())
            )
            self._parameterNode.SetParameter(
                PARAM_SELECTED_SEGMENTS,
                json.dumps(self._selectedSegmentIDs(), separators=(",", ":")),
            )
            self._parameterNode.SetParameter(
                PARAM_STANDARD_CONFIGURATIONS,
                json.dumps(self._selectedConfigurations(), separators=(",", ":")),
            )
            self._parameterNode.SetParameter(
                PARAM_ADDITIONAL_SOURCE, self._currentAdditionalSource()
            )
            self._parameterNode.SetParameter(
                PARAM_INLINE_CONFIG,
                json.dumps(self._inlineStateFromGUI(), separators=(",", ":")),
            )
        finally:
            try:
                self._parameterNode.EndModify(wasModified)
            finally:
                self._updatingParameterNodeFromGUI = False

    @staticmethod
    def _nodeID(node) -> str | None:
        return node.GetID() if node is not None else None

    def onControlsChanged(self, *args):
        if self._updatingGUIFromParameterNode:
            return
        self.updateParameterNodeFromGUI()
        self._updateRunState()

    def onAdditionalSourceChanged(self, *args):
        if self._updatingGUIFromParameterNode:
            return
        self.updateParameterNodeFromGUI()
        self._updateConfigVisibility()
        self._updateRunState()

    def _currentAdditionalSource(self) -> str:
        index = int(self.ui.additionalConfigCombo.currentIndex)
        if 0 <= index < len(ADDITIONAL_SOURCES):
            return ADDITIONAL_SOURCES[index]
        return "none"

    def _updateConfigVisibility(self):
        source = self._currentAdditionalSource()
        self.ui.inlineConfigGroup.setVisible(source == "inline")
        self.ui.customFileWidget.setVisible(source == "file")

    @staticmethod
    def _setComboText(combo, text):
        index = combo.findText(str(text))
        combo.setCurrentIndex(index if index >= 0 else 0)

    def _storedInlineState(self) -> dict[str, Any]:
        raw = (
            self._parameterNode.GetParameter(PARAM_INLINE_CONFIG)
            if self._parameterNode is not None
            else ""
        )
        try:
            stored = json.loads(raw) if raw else {}
        except (TypeError, ValueError):
            stored = {}
        state = default_inline_state()
        if isinstance(stored, dict):
            state.update(stored)
        return state

    def _inlineStateFromGUI(self) -> dict[str, Any]:
        families = [
            family
            for family, attribute in FAMILY_CHECKBOXES
            if getattr(self.ui, attribute).checked
        ]
        sentinel_text = str(self.ui.sentinelValueLineEdit.text).strip()
        return {
            "families": families,
            "resample": bool(self.ui.resampleCheckBox.checked),
            "spacing": [
                float(self.ui.resampleXSpinBox.value),
                float(self.ui.resampleYSpinBox.value),
                float(self.ui.resampleZSpinBox.value),
            ],
            "interpolation": str(self.ui.interpolationCombo.currentText),
            "discretise": bool(self.ui.discretiseCheckBox.checked),
            "discretise_method": str(self.ui.discretiseMethodCombo.currentText),
            "discretise_value": float(self.ui.discretiseValueSpinBox.value),
            "source_mode": str(self.ui.sourceModeCombo.currentText),
            "sentinel_value": sentinel_text or None,
            "resegment": bool(self.ui.resegmentGroup.checked),
            "range_min": str(self.ui.rangeMinLineEdit.text).strip() or None,
            "range_max": str(self.ui.rangeMaxLineEdit.text).strip() or None,
            "resegment_apply_to": MASK_TARGETS[self.ui.resegmentTargetCombo.currentIndex],
            "filter_outliers": bool(self.ui.outlierGroup.checked),
            "outlier_sigma": float(self.ui.outlierSigmaSpinBox.value),
            "outlier_apply_to": MASK_TARGETS[self.ui.outlierTargetCombo.currentIndex],
            "filter": bool(self.ui.filterGroup.checked),
            "filter_type": self._currentFilterType(),
            "filter_boundary": str(self.ui.filterBoundaryCombo.currentText),
            "filter_params": self._filterParametersFromGUI(),
        }

    def _currentFilterType(self) -> str:
        return str(self.ui.filterTypeCombo.itemData(self.ui.filterTypeCombo.currentIndex))

    def _filterParametersFromGUI(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for name, kind, _, _ in FILTER_PARAMETERS[self._currentFilterType()]:
            widget = self._filterParameterWidgets[name]
            if kind == "int":
                values[name] = int(widget.value)
            elif kind == "float":
                values[name] = float(widget.value)
            elif kind == "bool":
                values[name] = bool(widget.checked)
            elif kind == "choice":
                values[name] = str(widget.currentText)
            else:
                values[name] = str(widget.text).strip()
        return values

    def _buildFilterParameters(self, filterType: str, values: dict[str, Any]):
        """Show one control for each parameter of *filterType*, set to *values*."""

        layout = self._filterParametersLayout
        while layout.count():
            widget = layout.takeAt(0).widget()
            if widget is not None:
                widget.deleteLater()
        self._filterParameterWidgets = {}
        for name, kind, default, limits in FILTER_PARAMETERS[filterType]:
            value = values.get(name, default)
            if kind in ("int", "float"):
                widget = qt.QSpinBox() if kind == "int" else qt.QDoubleSpinBox()
                if kind == "float":
                    widget.setDecimals(4)
                widget.setRange(limits[0], limits[1])
                widget.setValue(value)
                widget.connect("valueChanged(double)" if kind == "float" else "valueChanged(int)",
                               self.onControlsChanged)
            elif kind == "bool":
                widget = qt.QCheckBox()
                widget.setChecked(bool(value))
                widget.connect("toggled(bool)", self.onControlsChanged)
            elif kind == "choice":
                widget = qt.QComboBox()
                widget.addItems(list(limits))
                widget.setCurrentIndex(max(widget.findText(str(value)), 0))
                widget.connect("currentIndexChanged(int)", self.onControlsChanged)
            else:
                widget = qt.QLineEdit(str(value))
                widget.connect("textChanged(QString)", self.onControlsChanged)
            label = name.replace("_mm", " (mm)").replace("_", " ").capitalize()
            if name in ("theta", "delta_theta"):
                label += " (radians)"
            layout.addRow(f"{label}:", widget)
            self._filterParameterWidgets[name] = widget

    def onFilterTypeChanged(self, *args):
        if self._updatingGUIFromParameterNode:
            return
        filterType = self._currentFilterType()
        self._buildFilterParameters(filterType, filter_defaults(filterType))
        self.onControlsChanged()

    def _applyInlineState(self, state: dict[str, Any]):
        families = set(state.get("families", []))
        for family, attribute in FAMILY_CHECKBOXES:
            getattr(self.ui, attribute).setChecked(family in families)
        self.ui.resampleCheckBox.setChecked(bool(state.get("resample", True)))
        spacing = state.get("spacing", [0.5, 0.5, 0.5])
        if isinstance(spacing, (list, tuple)) and len(spacing) == 3:
            self.ui.resampleXSpinBox.setValue(float(spacing[0]))
            self.ui.resampleYSpinBox.setValue(float(spacing[1]))
            self.ui.resampleZSpinBox.setValue(float(spacing[2]))
        self._setComboText(
            self.ui.interpolationCombo, state.get("interpolation", "linear")
        )
        self.ui.discretiseCheckBox.setChecked(bool(state.get("discretise", True)))
        self._setComboText(
            self.ui.discretiseMethodCombo, state.get("discretise_method", "FBN")
        )
        self.ui.discretiseValueSpinBox.setValue(
            float(state.get("discretise_value", 32.0))
        )
        self._setComboText(self.ui.sourceModeCombo, state.get("source_mode", "full_image"))
        sentinel = state.get("sentinel_value")
        self.ui.sentinelValueLineEdit.setText("" if sentinel is None else str(sentinel))
        self.ui.resegmentGroup.setChecked(bool(state.get("resegment", False)))
        self.ui.outlierGroup.setChecked(bool(state.get("filter_outliers", False)))
        for key, edit in (("range_min", self.ui.rangeMinLineEdit), ("range_max", self.ui.rangeMaxLineEdit)):
            value = state.get(key)
            edit.setText("" if value is None else str(value))
        self.ui.outlierSigmaSpinBox.setValue(float(state.get("outlier_sigma", 3.0)))
        for key, combo in (("resegment_apply_to", self.ui.resegmentTargetCombo),
                           ("outlier_apply_to", self.ui.outlierTargetCombo)):
            target = state.get(key, "both")
            combo.setCurrentIndex(MASK_TARGETS.index(target) if target in MASK_TARGETS else 0)
        self.ui.filterGroup.setChecked(bool(state.get("filter", False)))
        filterType = state.get("filter_type")
        filterType = filterType if filterType in FILTER_PARAMETERS else "log"
        wasBlocked = self.ui.filterTypeCombo.blockSignals(True)
        self.ui.filterTypeCombo.setCurrentIndex(self.ui.filterTypeCombo.findData(filterType))
        self.ui.filterTypeCombo.blockSignals(wasBlocked)
        self._setComboText(self.ui.filterBoundaryCombo, state.get("filter_boundary", "default"))
        params = state.get("filter_params")
        self._buildFilterParameters(filterType, params if isinstance(params, dict) else {})

    def onSegmentationChanged(self, node=None):
        if self._updatingGUIFromParameterNode:
            return
        segmentationNode = self.ui.segmentationSelector.currentNode()
        selectedIDs = (
            set(self.logic.segmentIDs(segmentationNode)) if segmentationNode else set()
        )
        self._rebuildSegmentList(selectedIDs)
        self.updateParameterNodeFromGUI()
        self._updateRunState()

    def _rebuildSegmentList(self, checkedIDs: set[str]):
        segmentationNode = self.ui.segmentationSelector.currentNode()
        self.ui.segmentListWidget.blockSignals(True)
        self.ui.segmentListWidget.clear()
        if segmentationNode is not None:
            segmentation = segmentationNode.GetSegmentation()
            for segmentID in self.logic.segmentIDs(segmentationNode):
                segment = segmentation.GetSegment(segmentID)
                name = segment.GetName() if segment is not None else segmentID
                item = qt.QListWidgetItem(name)
                item.setData(ITEM_VALUE_ROLE, segmentID)
                item.setToolTip(segmentID)
                item.setFlags(item.flags() | qt.Qt.ItemIsUserCheckable)
                item.setCheckState(
                    qt.Qt.Checked if segmentID in checkedIDs else qt.Qt.Unchecked
                )
                self.ui.segmentListWidget.addItem(item)
        self.ui.segmentListWidget.blockSignals(False)

    def _checkedValues(self, listWidget) -> list[str]:
        values = []
        for index in range(listWidget.count):
            item = listWidget.item(index)
            if item.checkState() == qt.Qt.Checked:
                values.append(str(item.data(ITEM_VALUE_ROLE)))
        return values

    def _selectedSegmentIDs(self) -> list[str]:
        return self._checkedValues(self.ui.segmentListWidget)

    def _selectedConfigurations(self) -> list[str]:
        return self._checkedValues(self.ui.standardConfigListWidget)

    def _updateScannerDetails(self, *args):
        volume = self.ui.inputVolumeSelector.currentNode()
        details = self.logic.scannerDetails(volume) if volume is not None and self.logic else {}
        found = [f"{name.replace('_', ' ')}: {value}" for name, value in details.items() if value]
        self.ui.scannerDetailsLabel.setText(
            "; ".join(found)
            if found
            else "None found. They come from DICOM, or from a dcm2niix JSON file next to a "
            "NIfTI image. You can add them as extra columns."
        )

    def _validationError(self) -> str | None:
        inputVolume = self.ui.inputVolumeSelector.currentNode()
        if inputVolume is None:
            return "Select an input scalar volume."
        if inputVolume.GetImageData() is None:
            return "The selected input volume has no image data."
        error = self._settingsError()
        if error:
            return error

        hasSegments = bool(self._selectedSegmentIDs())
        if not self.ui.wholeVolumeCheckBox.checked and not hasSegments:
            return "Analyze the whole volume or select at least one segment."
        if hasSegments and self.ui.segmentationSelector.currentNode() is None:
            return "Select a segmentation for the checked segments."
        return None

    def _settingsError(self) -> str | None:
        """Return a problem of the configuration or column settings, for runs and batches."""

        source = self._currentAdditionalSource()
        if source == "file":
            customPath = str(self.ui.customConfigPathLineEdit.text).strip()
            if not customPath:
                return "Choose a custom configuration file, or change the source."
            path = Path(customPath).expanduser()
            if not path.is_file():
                return "The custom configuration file does not exist."
            if path.suffix.lower() not in (".yaml", ".yml", ".json"):
                return "The custom configuration must be YAML or JSON."
        elif source == "inline":
            try:
                build_inline_configuration_document(self._inlineStateFromGUI())
            except ValueError as exc:
                return str(exc)
        if not self._selectedConfigurations() and source == "none":
            return "Select at least one preset, or add an in-app or file configuration."

        try:
            parse_extra_columns(str(self.ui.extraColumnsTextEdit.toPlainText()))
        except ValueError as exc:
            return str(exc)
        return None

    def _updateRunState(self):
        if not hasattr(self, "ui"):
            return
        cliBusy = self._nodeIsBusy(self._cliNode)
        busy = (
            cliBusy
            or self._activeJob is not None
            or self._dependencyOperationInProgress
            or self._batch is not None
            or self._tableOperationInProgress
        )
        error = self._validationError()
        for control in (
            self.ui.inputVolumeSelector,
            self.ui.segmentationSelector,
            self.ui.wholeVolumeCheckBox,
            self.ui.segmentListWidget,
            self.ui.subjectIdLineEdit,
            self.ui.standardConfigListWidget,
            self.ui.additionalConfigCombo,
            self.ui.inlineConfigGroup,
            self.ui.customFileWidget,
            self.ui.outputTableSelector,
            self.ui.appendResultsCheckBox,
            self.ui.exportWideCheckBox,
            self.ui.loadProfileButton,
            self.ui.readerLineEdit,
            self.ui.extraColumnsTextEdit,
            self.ui.cropCheckBox,
            self.ui.batchFolderLineEdit,
            self.ui.batchBrowseButton,
            self.ui.batchImagePatternLineEdit,
            self.ui.batchSegmentationPatternLineEdit,
            self.ui.runBatchButton,
        ):
            control.setEnabled(not busy)
        self.ui.runButton.setEnabled(not busy and error is None)
        self.ui.cancelButton.setEnabled(cliBusy and not self._cancelRequested and not self._tableOperationInProgress)
        self.ui.updatePackageButton.setEnabled(not busy)
        tableNode = self.ui.outputTableSelector.currentNode()
        self.ui.saveProfileButton.setEnabled(not busy and self._currentAdditionalSource() != "file")
        self.ui.duplicateProfileButton.setEnabled(not busy and self._currentAdditionalSource() != "file")
        self.ui.exportButton.setEnabled(
            not busy
            and tableNode is not None
            and tableNode.GetTable() is not None
            and tableNode.GetTable().GetNumberOfRows() > 0
        )
        self.ui.browseResultsButton.setEnabled(self.ui.exportButton.enabled)
        reportNode = self._selectedBatchReportNode()
        reportEnabled = not busy and reportNode is not None
        self.ui.batchReportCombo.setEnabled(not busy and self.ui.batchReportCombo.count > 0)
        self.ui.viewBatchReportButton.setEnabled(reportEnabled)
        self.ui.exportBatchReportButton.setEnabled(reportEnabled)
        if self._tableOperationInProgress:
            self.ui.readinessLabel.setText("Result-table operation in progress; controls are locked.")
        elif busy:
            self.ui.readinessLabel.setText("Run or package operation in progress; inputs are locked.")
        elif error:
            self.ui.readinessLabel.setText(error)
        else:
            segmentCount = len(self._selectedSegmentIDs())
            regionParts = []
            if self.ui.wholeVolumeCheckBox.checked:
                regionParts.append("whole volume")
            if segmentCount:
                regionParts.append(f"{segmentCount} segment(s)")
            configParts = []
            presets = self._selectedConfigurations()
            if presets:
                configParts.append(f"{len(presets)} preset(s)")
            source = self._currentAdditionalSource()
            if source == "inline":
                configParts.append("1 in-app configuration")
            elif source == "file":
                # A file may define several configurations; do not guess its count.
                configParts.append("custom file (validated by worker)")
            self.ui.readinessLabel.setText(
                f"Ready: {' + '.join(regionParts)}; {' + '.join(configParts)}."
            )

    def _batchReportNodes(self):
        nodes = []
        for index in range(slicer.mrmlScene.GetNumberOfNodesByClass("vtkMRMLTableNode")):
            node = slicer.mrmlScene.GetNthNodeByClass(index, "vtkMRMLTableNode")
            if node is not None and node.GetAttribute(REPORT_ATTRIBUTE) == REPORT_SCHEMA_VERSION:
                nodes.append(node)
        return nodes

    def _refreshBatchReports(self, caller=None, event=None, *, selected_id=None):
        if not hasattr(self, "ui"):
            return
        combo = self.ui.batchReportCombo
        current = selected_id or (str(combo.itemData(combo.currentIndex)) if combo.currentIndex >= 0 else "")
        combo.blockSignals(True)
        combo.clear()
        nodes = self._batchReportNodes()
        for node in reversed(nodes):
            # Slicer's generic TSV writer does not escape embedded newlines/tabs.
            # Locked report tables are a view; restore their authoritative JSON
            # rows after import (and when the module first opens on a saved scene).
            try:
                metadata = json.loads(str(node.GetAttribute(REPORT_METADATA_ATTRIBUTE) or "{}"))
                if isinstance(metadata, dict) and "rows" in metadata:
                    self._writeBatchReportTable(node, validate_report(metadata))
                    node.SetLocked(True)
            except (ValueError, TypeError):
                LOGGER.warning("A saved batch report has invalid metadata; it was left unchanged.")
            combo.addItem(str(node.GetName()), node.GetID())
        index = combo.findData(current) if current else 0
        if combo.count:
            combo.setCurrentIndex(max(0, index))
        combo.blockSignals(False)
        if hasattr(self, "ui"):
            self._updateRunState()

    def _selectedBatchReportNode(self):
        if not hasattr(self, "ui") or self.ui.batchReportCombo.currentIndex < 0:
            return None
        node_id = str(self.ui.batchReportCombo.itemData(self.ui.batchReportCombo.currentIndex))
        node = slicer.mrmlScene.GetNodeByID(node_id) if node_id else None
        return node if node is not None and node.GetAttribute(REPORT_ATTRIBUTE) == REPORT_SCHEMA_VERSION else None

    def _reportDocument(self, node):
        if node is None or node.GetAttribute(REPORT_ATTRIBUTE) != REPORT_SCHEMA_VERSION:
            raise ValueError("The selected batch report is unavailable or has an unsupported schema.")
        try:
            metadata = json.loads(str(node.GetAttribute(REPORT_METADATA_ATTRIBUTE) or "{}"))
        except json.JSONDecodeError as exc:
            raise ValueError("The batch report metadata is not valid JSON.") from exc
        if not isinstance(metadata, dict):
            raise ValueError("The batch report metadata must be a JSON object.")
        if "rows" not in metadata:
            # Backward compatibility for older reports without JSON row storage.
            # Do not silently fall back if an existing JSON snapshot is invalid.
            table = node.GetTable()
            if table is None:
                raise ValueError("The batch report table is missing.")
            columns = {str(table.GetColumnName(index)): index for index in range(table.GetNumberOfColumns())}
            if not set(REPORT_COLUMNS).issubset(columns):
                raise ValueError("The batch report is missing required columns.")
            rows = []
            for row_index in range(table.GetNumberOfRows()):
                rows.append({name: str(table.GetValue(row_index, columns[name]).ToString()) for name in REPORT_COLUMNS})
            metadata["rows"] = rows
        document = validate_report(metadata)
        owned = self._batch is not None and self._batch.get("report_node") is node
        if document["state"] == "running" and not owned:
            for row in document["rows"]:
                if row["status"] == "running":
                    row["status"] = "interrupted"
                    row["reason"] = "The Slicer session ended while this case was running."
                elif row["status"] == "not_started":
                    row["reason"] = "The Slicer session ended before this case started."
            document["state"] = "interrupted"
            # The actual interruption time is unknown after recovery.
            document["finished_at"] = ""
            self._syncBatchReport(document, node)
        return document

    def _createBatchReport(self, cases, skipped):
        document = new_report(
            [case.name for case in cases],
            [(item.name, item.reason) for item in skipped],
        )
        document["batch_id"] = uuid.uuid4().hex
        document["started_at"] = datetime.now(timezone.utc).isoformat()
        node = slicer.mrmlScene.AddNewNodeByClass("vtkMRMLTableNode", f"Pictologics batch report {document['batch_id'][:8]}")
        node.SetHideFromEditors(True)
        node.SetAttribute(REPORT_ATTRIBUTE, REPORT_SCHEMA_VERSION)
        node.SetAttribute(REPORT_METADATA_ATTRIBUTE, json.dumps(document, sort_keys=True, allow_nan=False))
        node.SetLocked(True)
        self._writeBatchReportTable(node, document)
        self._refreshBatchReports(selected_id=node.GetID())
        return node, document

    @staticmethod
    def _writeBatchReportTable(node, document):
        table = node.GetTable()
        table.Initialize()
        for name in REPORT_COLUMNS:
            array = vtk.vtkStringArray()
            array.SetName(name)
            table.AddColumn(array)
        for row in document["rows"]:
            row_index = table.InsertNextBlankRow()
            for column, name in enumerate(REPORT_COLUMNS):
                table.SetValue(row_index, column, str(row.get(name, "")))
        table.Modified()
        node.Modified()

    def _syncBatchReport(self, document, node):
        # Keep the original node object: scene reloads may reuse an old MRML ID.
        if node is None or node.GetScene() != slicer.mrmlScene:
            return
        modifying = node.StartModify()
        try:
            self._writeBatchReportTable(node, document)
            node.SetAttribute(REPORT_METADATA_ATTRIBUTE, json.dumps(document, sort_keys=True, allow_nan=False))
            node.SetLocked(True)
        finally:
            node.EndModify(modifying)

    def _reportBatchCase(self, status, *, reason="", row_count=None, roi_count=None, run_id=None, result_table=None):
        batch = self._batch
        if not batch or not batch.get("report"):
            return
        index = batch.get("report_index", {}).get(batch.get("index"))
        if index is None:
            return
        row = batch["report"]["rows"][index]
        row.update(status=status, reason=str(reason))
        if run_id is not None:
            row["run_id"] = str(run_id)
        if result_table is not None:
            row["result_table"] = str(result_table)
        if row_count is not None:
            row["row_count"] = int(row_count)
        if roi_count is not None:
            row["roi_count"] = int(roi_count)
        row["elapsed_seconds"] = max(0.0, time.monotonic() - batch.get("case_started", time.monotonic()))
        self._syncBatchReport(batch["report"], batch["report_node"])

    def _markBatchInterrupted(self):
        batch = self._batch
        if not batch or not batch.get("report"):
            return
        if (
            0 <= batch["index"] < len(batch["cases"])
            and batch["report"]["rows"][batch["index"]]["status"] == "running"
        ):
            self._reportBatchCase("interrupted", reason="Batch interrupted before this case finished.")
        for row in batch["report"]["rows"]:
            if row["status"] == "running":
                row["status"] = "interrupted"
                row["reason"] = "Scene closed while this case was running."
            elif row["status"] == "not_started":
                row["reason"] = "Batch stopped before this case started."
        batch["report"]["state"] = "interrupted"
        batch["report"]["finished_at"] = datetime.now(timezone.utc).isoformat()
        self._syncBatchReport(batch["report"], batch["report_node"])

    def onViewBatchReport(self):
        node = self._selectedBatchReportNode()
        if node is None or self._batch is not None or self._tableOperationInProgress:
            return
        try:
            document = self._reportDocument(node)
            node.SetLocked(True)
            self.logic.showTable(node)
            self.ui.statusLabel.setText(f"Showing {len(document['rows']):,} cases from {node.GetName()}.")
        except Exception as exc:
            slicer.util.errorDisplay(str(exc), windowTitle="Pictologics batch report")

    def onExportBatchReport(self):
        node = self._selectedBatchReportNode()
        if node is None or self._batch is not None or self._tableOperationInProgress:
            return
        selected = qt.QFileDialog.getSaveFileName(self.parent, "Export batch report", "batch-report.json", "JSON (*.json);;CSV (*.csv)")
        selected = self._dialogPath(selected)
        if not selected:
            return
        path = Path(selected).expanduser()
        if not path.suffix:
            path = path.with_suffix(".json")
            if path.exists() and not slicer.util.confirmYesNoDisplay(f"Replace {path}?", windowTitle="Export batch report"):
                return
        try:
            with self._tableOperation(f"Exporting {node.GetNumberOfRows():,} batch-case records…", node):
                document = self._reportDocument(node)
                export_report(document, path)
            self.ui.statusLabel.setText(f"Batch report exported to {path.name}.")
        except Exception as exc:
            slicer.util.errorDisplay(str(exc), windowTitle="Pictologics batch report")

    def onBrowseResults(self):
        if self._tableOperationInProgress:
            return
        if self._resultsBrowser is None:
            self._resultsBrowser = ResultsBrowser(self.parent, self._refreshResultsBrowser)
        if self._refreshResultsBrowser():
            self._resultsBrowser.dialog.show()
            self._resultsBrowser.dialog.raise_()

    def _refreshResultsBrowser(self):
        if self._tableOperationInProgress:
            return False
        table = self.ui.outputTableSelector.currentNode()
        try:
            if table is None:
                raise ValueError("Select a Pictologics results table first.")
            count = table.GetNumberOfRows()
            with self._tableOperation(f"Opening {count:,} result rows…", table):
                rows = self.logic.rowsFromTable(table)
                warning = ""
                try:
                    history = self.logic.provenanceHistory(table)
                except ValueError as exc:
                    history, warning = [], str(exc)
                warning = " ".join(part for part in (warning, table.GetAttribute(WARNING_ATTRIBUTE)) if part)
                self._resultsBrowser.set_data(table.GetName(), rows, history, warning)
            self.ui.statusLabel.setText(f"Opened {len(rows):,} result rows for browsing.")
            return True
        except Exception as exc:
            self._resultsBrowser.set_data("Unavailable", [], [], str(exc))
            slicer.util.errorDisplay(str(exc), windowTitle="Pictologics results")
            return False

    @contextmanager
    def _tableOperation(self, message, table=None):
        """Paint feedback before synchronous work, with a reentrancy/scene guard."""
        if self._tableOperationInProgress:
            raise RuntimeError("A result-table operation is already in progress.")
        generation = self._sceneGeneration
        self._tableOperationInProgress = True
        browser = self._resultsBrowser
        previousSource = str(browser.source.text) if browser is not None else ""
        previousStatus = str(self.ui.statusLabel.text)
        self.ui.statusLabel.setText(message)
        if browser is not None:
            browser.source.setText(message)
            browser.dialog.setEnabled(False)
        try:
            self._updateRunState()
            with slicer.util.WaitCursor():
                # Timers/scene callbacks can still run here; user input is excluded.
                slicer.app.processEvents(qt.QEventLoop.ExcludeUserInputEvents)
                if generation != self._sceneGeneration or (table is not None and table.GetScene() != slicer.mrmlScene):
                    raise RuntimeError("The scene changed; the table operation was stopped.")
                yield
        finally:
            self._tableOperationInProgress = False
            if browser is not None:
                browser.dialog.setEnabled(True)
                if generation == self._sceneGeneration and str(browser.source.text) == message:
                    browser.source.setText(previousSource)
            if generation == self._sceneGeneration and str(self.ui.statusLabel.text) == message:
                self.ui.statusLabel.setText(previousStatus)
            self._updateRunState()

    def onSaveProfile(self):
        self._saveProfile(copyProfile=False)

    def onDuplicateProfile(self):
        self._saveProfile(copyProfile=True)

    def _saveProfile(self, *, copyProfile: bool):
        if self._dependencyOperationInProgress or self._activeJob is not None:
            return
        try:
            if self._currentAdditionalSource() == "file":
                raise ValueError("Profiles support presets and in-app settings. Custom YAML/JSON files are already reusable.")
            suggested = self._profileName + (" copy" if copyProfile else "")
            answer = qt.QInputDialog.getText(self.parent, "Save configuration profile", "Profile name:", qt.QLineEdit.Normal, suggested)
            if isinstance(answer, (tuple, list)) and len(answer) > 1 and not answer[1]:
                return
            name = self._dialogPath(answer)
            if not name:
                return
            document = build_profile(name, self._selectedConfigurations(),
                                     self._inlineStateFromGUI() if self._currentAdditionalSource() == "inline" else None)
            suggestedPath = str(self._profilePath) if self._profilePath and not copyProfile else "profile-copy.pictologics-profile.json" if copyProfile else "profile.pictologics-profile.json"
            selected = self._dialogPath(qt.QFileDialog.getSaveFileName(
                self.parent, "Save configuration profile", suggestedPath,
                "Pictologics settings profile (*.pictologics-profile.json)",
            ))
            if not selected:
                return
            destination = Path(selected)
            if destination.suffix.lower() != ".json":
                destination = destination.with_name(destination.name + ".pictologics-profile.json")
            if copyProfile and self._profilePath and destination.resolve() == self._profilePath.resolve():
                raise ValueError("Choose a different file for the duplicate; the original profile was not changed.")
            if str(destination) != selected and destination.exists() and not slicer.util.confirmYesNoDisplay(
                f"Replace the existing profile {destination.name}?", windowTitle="Save profile"
            ):
                return
            self.logic._atomicWriteJSON(destination, document)
            self._profilePath, self._profileName = destination, document["name"]
            self.ui.profileStatusLabel.setText(f"Saved {document['name']}. Save again after changing settings.")
        except Exception as exc:
            slicer.util.errorDisplay(str(exc), windowTitle="Could not save profile")

    def onLoadProfile(self):
        if self._dependencyOperationInProgress or self._activeJob is not None:
            return
        selected = self._dialogPath(qt.QFileDialog.getOpenFileName(
            self.parent, "Load configuration profile", str(self._profilePath or ""),
            "Pictologics settings profile (*.pictologics-profile.json);;JSON (*.json)",
        ))
        if not selected:
            return
        try:
            # Complete validation before changing a single control or parameter.
            document = validate_profile(json.loads(Path(selected).read_text(encoding="utf-8")))
            self._updatingGUIFromParameterNode = True
            try:
                self.ui.additionalConfigCombo.setCurrentIndex(1 if document["inline_state"] is not None else 0)
                if document["inline_state"] is not None:
                    self._applyInlineState(document["inline_state"])
                for index in range(self.ui.standardConfigListWidget.count):
                    item = self.ui.standardConfigListWidget.item(index)
                    item.setCheckState(qt.Qt.Checked if str(item.data(ITEM_VALUE_ROLE)) in document["presets"] else qt.Qt.Unchecked)
                self._updateConfigVisibility()
            finally:
                self._updatingGUIFromParameterNode = False
            self.updateParameterNodeFromGUI()
            self._updateRunState()
            self._profilePath, self._profileName = Path(selected), document["name"]
            self.ui.profileStatusLabel.setText(f"Loaded {document['name']}. Save again after changing settings.")
        except Exception as exc:
            slicer.util.errorDisplay(str(exc), windowTitle="Could not load profile")

    def onBrowseConfiguration(self):
        selected = qt.QFileDialog.getOpenFileName(
            slicer.util.mainWindow(),
            "Select Pictologics configuration",
            str(Path(str(self.ui.customConfigPathLineEdit.text)).parent)
            if str(self.ui.customConfigPathLineEdit.text).strip()
            else "",
            "Pictologics configuration (*.yaml *.yml *.json)",
        )
        selected = self._dialogPath(selected)
        if selected:
            self.ui.customConfigPathLineEdit.setText(selected)

    def onNewFromPreset(self):
        presets = list(preset_names())
        chosen = qt.QInputDialog.getItem(
            slicer.util.mainWindow(),
            "New configuration from preset",
            "Start from which standard preset?",
            presets,
            presets.index(DEFAULT_CONFIGURATION) if DEFAULT_CONFIGURATION in presets else 0,
            False,
        )
        if not chosen:
            return
        selected = self._dialogPath(
            qt.QFileDialog.getSaveFileName(
                slicer.util.mainWindow(),
                "Save starter configuration",
                f"{chosen}.json",
                "JSON (*.json)",
            )
        )
        if not selected:
            return
        path = Path(selected)
        if path.suffix.lower() != ".json":
            path = path.with_suffix(".json")
        try:
            document = preset_configuration_document(str(chosen))
            path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        except Exception as exc:
            slicer.util.errorDisplay(str(exc), windowTitle="Pictologics")
            return
        self.ui.customConfigPathLineEdit.setText(str(path))
        self.ui.statusLabel.setText(
            f"Wrote an editable starter configuration to {path}."
        )

    def onValidateConfiguration(self):
        customPath = str(self.ui.customConfigPathLineEdit.text).strip()
        if not customPath:
            slicer.util.errorDisplay(
                "Choose a configuration file to validate.", windowTitle="Pictologics"
            )
            return
        path = Path(customPath).expanduser()
        if not path.is_file():
            slicer.util.errorDisplay(
                "The custom configuration file does not exist.",
                windowTitle="Pictologics",
            )
            return
        self.ui.statusLabel.setText("Checking the configuration file with Pictologics…")
        slicer.app.processEvents()
        try:
            with slicer.util.WaitCursor():
                check = self.logic.checkConfigurationFile(path)
        except Exception as exc:
            LOGGER.exception("Could not check the configuration file")
            self.ui.statusLabel.setText(f"Could not check the configuration file: {exc}")
            return
        if check is not None:
            if check["valid"]:
                names = check["configurations"]
                self.ui.statusLabel.setText(
                    f"Pictologics accepts this file. It holds {len(names)} "
                    f"configuration(s): {', '.join(names)}."
                )
            else:
                self.ui.statusLabel.setText(
                    f"Pictologics does not accept this file: {check['error']}"
                )
            return
        # Pictologics is not installed yet: do the quick structural check only.
        try:
            document = self._parseConfigurationFile(path)
        except ValueError as exc:
            self.ui.statusLabel.setText(f"Configuration is not valid: {exc}")
            return
        if document is None:
            self.ui.statusLabel.setText(
                "Pictologics is not installed yet, so a YAML file cannot be checked. "
                "The first run installs Pictologics and checks the file."
            )
            return
        issues = lint_configuration_document(document)
        if issues:
            self.ui.statusLabel.setText(
                f"Configuration has {len(issues)} issue(s): " + "; ".join(issues[:5])
            )
        else:
            self.ui.statusLabel.setText(
                "The file passed the quick structural check. Pictologics is not "
                "installed yet; the first run installs it and checks the file."
            )

    @staticmethod
    def _parseConfigurationFile(path: Path):
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".json":
            try:
                return json.loads(text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON ({exc})") from exc
        try:
            import yaml
        except ImportError:
            return None
        try:
            return yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError(f"invalid YAML ({exc})") from exc

    @staticmethod
    def _dialogPath(result) -> str:
        if isinstance(result, (tuple, list)):
            return str(result[0]) if result else ""
        return str(result or "")

    def refreshPackageStatus(self):
        if self.logic is None or not hasattr(self, "ui"):
            return
        try:
            inspection = self.logic.inspectDependencies()
            requirement = self.logic.pictologicsRequirement()
            if inspection.satisfied:
                detail = f"Isolated Pictologics {inspection.installed_version} satisfies {requirement}."
            elif inspection.installed:
                versions = ", ".join(inspection.installed_versions)
                detail = (
                    f"Isolated Pictologics {versions} does not satisfy {requirement}."
                )
            else:
                detail = f"Pictologics {requirement} is not installed in the extension-private environment."
            if inspection.ambiguous:
                detail += " Multiple installed distributions were found; reinstall before running."
            self.ui.packageVersionLabel.setText(detail)
        except Exception as exc:  # package status must never break module entry
            self.ui.packageVersionLabel.setText(
                f"Could not inspect the isolated package: {exc}"
            )

    def onUpdatePackage(self):
        if self._tableOperationInProgress:
            return
        if self._dependencyOperationInProgress:
            self.ui.statusLabel.setText(
                "A Pictologics dependency operation is already in progress."
            )
            return
        if self._nodeIsBusy(self._cliNode):
            self.ui.statusLabel.setText("Pictologics is already running.")
            return
        self._dependencyOperationInProgress = True
        self._recordDiagnosticOperation("dependency_update", "in_progress")
        self._updateRunState()
        try:
            self.ui.statusLabel.setText(
                "Updating the isolated Pictologics environment…"
            )
            slicer.app.processEvents()
            self.logic.ensureDependencies(forceUpgrade=True)
            self.ui.statusLabel.setText("The adopted Pictologics release is installed.")
            self._recordDiagnosticOperation("dependency_update", "completed")
        except DependencyInstallDeclined:
            self._recordDiagnosticOperation("dependency_update", "cancelled")
            self.ui.statusLabel.setText(
                "Package update was cancelled; no files were changed."
            )
        except Exception as exc:
            self._recordDiagnosticOperation("dependency_update", "failed", "dependency_install_failed")
            LOGGER.exception("Pictologics dependency update failed")
            slicer.util.errorDisplay(
                str(exc), windowTitle="Pictologics package update failed"
            )
            self.ui.statusLabel.setText("Package update failed.")
        finally:
            self._dependencyOperationInProgress = False
            self.refreshPackageStatus()
            self._updateRunState()

    def _recordDiagnosticOperation(self, kind: str, outcome: str, code: str = "none"):
        self._diagnosticOperation = {"kind": kind, "outcome": outcome, "failure_code": code}
        if kind == "run" and outcome != "in_progress":
            self._diagnosticRun["state"] = outcome

    def onRefreshDiagnostics(self):
        # Metadata inspection only: no dependency imports, probes, installs or network.
        dependency = {"metadata_status": "inspection_failed"}
        try:
            requirement = self.logic.pictologicsRequirement()
            dependency["adopted_version"] = next(iter(requirement.specifier)).version
            inspection = self.logic.inspectDependencies()
            dependency["installed_version"] = inspection.installed_version
            dependency["metadata_status"] = (
                "ambiguous" if inspection.ambiguous else
                "compatible" if inspection.satisfied else
                "incompatible" if inspection.installed else "missing"
            )
        except Exception:
            # An inspection error can contain paths or identifiers. Do not copy it.
            pass
        run = dict(self._diagnosticRun)
        if self._runStartedAt is not None:
            run["elapsed_seconds"] = max(0, int(time.monotonic() - self._runStartedAt))
        self._diagnosticsPreview = diagnostics_text(
            runtime={
                "extension_version": EXTENSION_VERSION,
                "slicer_version": slicer.app.applicationVersion,
                "slicer_revision": slicer.app.repositoryRevision,
                "python_version": platform.python_version(),
                "qt_version": qt.qVersion(),
                "os": platform.system(),
                "process_architecture": platform.machine(),
            },
            dependency=dependency, operation=self._diagnosticOperation, run=run,
        )
        self.ui.diagnosticsTextEdit.setPlainText(self._diagnosticsPreview)
        self.ui.copyDiagnosticsButton.setEnabled(True)
        self.ui.diagnosticsStatusLabel.setText("Preview refreshed. Review it before copying; nothing has been uploaded.")

    def onCopyDiagnostics(self):
        if self._diagnosticsPreview:
            # Copy exactly the previewed snapshot, never silently regenerate it.
            qt.QApplication.clipboard().setText(self._diagnosticsPreview)
            self.ui.diagnosticsStatusLabel.setText("Preview copied to the clipboard. Share it only where you choose.")

    def onRun(self):
        if self._tableOperationInProgress:
            return
        if self._dependencyOperationInProgress:
            self.ui.statusLabel.setText(
                "A Pictologics dependency operation is already in progress."
            )
            return
        if self._nodeIsBusy(self._cliNode):
            self.ui.statusLabel.setText("Pictologics is already running.")
            return
        error = self._validationError()
        if error:
            self._diagnosticRun = {}
            self._recordDiagnosticOperation("run", "failed", "run_start_failed")
            self._reportRunError(error, "Pictologics")
            return
        if not self._confirmLargeRun():
            self._diagnosticRun = {}
            self._recordDiagnosticOperation("run", "cancelled")
            self.ui.statusLabel.setText("The run did not start.")
            if self._batch is not None:
                self._batch["stopped"] = True
            return
        # pip_install and the dependency probes process Qt events while they run.
        # Mark the entire launch path busy before the first processEvents() call so a
        # queued Run/Update click cannot start a second 500+ MB installation.
        self._dependencyOperationInProgress = True
        self._startRunFeedback()
        self._restoreCliProgress(0)
        self._updateRunState()
        try:
            self.updateParameterNodeFromGUI()
            self.ui.statusLabel.setText(
                "Checking the isolated Pictologics environment…"
            )
            slicer.app.processEvents()
            inspection = self.logic.ensureDependencies(forceUpgrade=False)
            self.refreshPackageStatus()

            source = self._currentAdditionalSource()
            customConfigurationPath = None
            inlineConfigurationDocument = None
            if source == "file":
                customConfigurationPath = (
                    str(self.ui.customConfigPathLineEdit.text).strip() or None
                )
            elif source == "inline":
                inlineConfigurationDocument = build_inline_configuration_document(
                    self._inlineStateFromGUI()
                )

            self.ui.statusLabel.setText("Preparing NIfTI image and ROI inputs…")
            slicer.app.processEvents()
            self._activeJob = self.logic.prepareJob(
                inputVolumeNode=self.ui.inputVolumeSelector.currentNode(),
                segmentationNode=self.ui.segmentationSelector.currentNode(),
                selectedSegmentIDs=self._selectedSegmentIDs(),
                includeWholeVolume=bool(self.ui.wholeVolumeCheckBox.checked),
                standardConfigurations=self._selectedConfigurations(),
                customConfigurationPath=customConfigurationPath,
                inlineConfigurationDocument=inlineConfigurationDocument,
                subjectID=str(self.ui.subjectIdLineEdit.text).strip(),
                installedVersion=inspection.installed_version or "",
                dependencyPath=inspection.target,
                cropToRegion=bool(self.ui.cropCheckBox.checked),
                resultColumns=self.logic.resultColumns(
                    self.ui.inputVolumeSelector.currentNode(),
                    str(self.ui.readerLineEdit.text),
                    parse_extra_columns(str(self.ui.extraColumnsTextEdit.toPlainText())),
                ),
            )
            outputTable = self.ui.outputTableSelector.currentNode()
            self._activeJob.update(
                {
                    "output_table_id": outputTable.GetID() if outputTable else None,
                    "output_table_mtime": self.logic.tableModificationTime(outputTable),
                    "append_results": bool(self.ui.appendResultsCheckBox.checked),
                    "discard_results": False,
                }
            )
            self._reportBatchCase(
                "running", run_id=self._activeJob["manifest"]["run_id"],
                roi_count=len(self._activeJob["manifest"]["rois"]),
            )
            self._cliNode = self.logic.startJob(self._activeJob)
            self._cliNode.StartContinuousOutputUpdate()
            self._continuousOutputNode = self._cliNode
            self._cliObserverTag = self._cliNode.AddObserver(
                vtk.vtkCommand.ModifiedEvent, self.onCliModified
            )
            self._beginCliProgress(len(self._activeJob["manifest"]["rois"]))
            self._diagnosticRun.update(state="running", roi_count=len(self._activeJob["manifest"]["rois"]))
            self.ui.statusLabel.setText("Starting Pictologics worker…")
            self._updateRunState()
            # Handle a setup failure that completed between cli.run() and observer
            # registration; no later ModifiedEvent is guaranteed in that race.
            self.onCliModified(self._cliNode)
        except DependencyInstallDeclined:
            self._recordDiagnosticOperation("run", "cancelled")
            self._reportBatchCase("cancelled", reason="Dependency installation was declined.")
            self.ui.statusLabel.setText(
                "Pictologics installation was cancelled; the run did not start."
            )
            if self._batch is not None:
                self._batch["stopped"] = True
        except Exception as exc:
            self._recordDiagnosticOperation("run", "failed", "run_start_failed")
            LOGGER.exception("Could not start Pictologics")
            if self._activeJob:
                self.logic.cleanupJob(self._activeJob)
            self._activeJob = None
            self._detachCliObserver(removeNode=True)
            self._reportRunError(str(exc), "Could not start Pictologics")
            self.ui.statusLabel.setText("The run did not start.")
        finally:
            self._dependencyOperationInProgress = False
            if self._activeJob is None:
                self._stopRunFeedback()
            self._updateRunState()

    def _confirmLargeRun(self) -> bool:
        """Ask before a run whose resampled scan needs a lot of memory."""

        volume = self.ui.inputVolumeSelector.currentNode()
        documents = [
            preset_configuration_document(name) for name in self._selectedConfigurations()
        ]
        source = self._currentAdditionalSource()
        if source == "inline":
            documents.append(build_inline_configuration_document(self._inlineStateFromGUI()))
        elif source == "file":
            path = Path(str(self.ui.customConfigPathLineEdit.text).strip()).expanduser()
            try:
                document = self._parseConfigurationFile(path)
                if document is None:
                    # Slicer has no YAML reader, so the worker reads the file.
                    with slicer.util.WaitCursor():
                        check = self.logic.checkConfigurationFile(path)
                    document = check["document"] if check and check["valid"] else None
            except Exception:
                # The worker reports a file that it cannot load when the run starts.
                LOGGER.debug("Could not read the configuration file", exc_info=True)
                document = None
            if isinstance(document, dict):
                documents.append(document)
        cropped = bool(self.ui.cropCheckBox.checked) and not self.ui.wholeVolumeCheckBox.checked
        # Cropping can fall back to a whole image/axis, and filter margins may be
        # large. Do not suppress a safety warning using an optimistic ROI box.
        dimensions = volume.GetImageData().GetDimensions()
        voxels = largest_voxel_count(dimensions, volume.GetSpacing(), documents)
        size = voxels * BYTES_PER_VOXEL
        if size <= LARGE_IMAGE_BYTES or (
            self._batch is not None and size <= self._batch["approvedImageBytes"]
        ):
            return True
        advice = (
            " Cropping may reduce memory, but some configurations or axes require the whole scan."
            if cropped else " Cropping around each region may reduce memory."
        )
        accepted = bool(
            slicer.util.confirmOkCancelDisplay(
                "Without an effective crop, Pictologics resamples the whole scan for each region, to about "
                f"{voxels / 1e6:,.0f} million voxels. One copy of that image needs "
                f"about {size / 1e9:.1f} GB of memory, and Pictologics keeps several "
                f"copies. The run can be slow or run out of memory.{advice}\n\nContinue?",
                windowTitle="Large Pictologics run",
            )
        )
        if accepted and self._batch is not None:
            self._batch["approvedImageBytes"] = size
        return accepted

    def onBrowseBatchFolder(self):
        folder = qt.QFileDialog.getExistingDirectory(
            slicer.util.mainWindow(),
            "Select the study folder",
            str(self.ui.batchFolderLineEdit.text).strip(),
        )
        if folder:
            self.ui.batchFolderLineEdit.setText(str(folder))

    def onRunBatch(self):
        """Run every case folder of the study folder, one after the other."""

        if self._batch is not None or self._activeJob is not None or self._tableOperationInProgress:
            return
        segmentationPattern = str(self.ui.batchSegmentationPatternLineEdit.text).strip()
        error = self._settingsError()
        if not error and not segmentationPattern and not self.ui.wholeVolumeCheckBox.checked:
            error = "Give a segmentation file name, or analyze the whole volume."
        folderText = str(self.ui.batchFolderLineEdit.text).strip()
        folder = Path(folderText).expanduser()
        if not error and (not folderText or not folder.is_dir()):
            error = "Choose a study folder that exists."
        if not error:
            try:
                cases, skipped = discover_cases(
                    folder, str(self.ui.batchImagePatternLineEdit.text).strip(), segmentationPattern
                )
                if not cases:
                    error = "No case folder has the image and segmentation files."
            except OSError as exc:
                error = f"Could not read the study folder: {exc}"
        if error:
            slicer.util.errorDisplay(error, windowTitle="Pictologics batch")
            return
        message = (
            f"Run {len(cases)} case(s) from {folder}? The rows of every case go into the "
            "results table."
        )
        if skipped:
            message += f"\n\n{len(skipped)} folder(s) are skipped:\n" + "\n".join(f"{item.name}: {item.reason}" for item in skipped[:10])
        if not slicer.util.confirmOkCancelDisplay(message, windowTitle="Pictologics batch"):
            return
        reportNode, reportDocument = self._createBatchReport(cases, skipped)
        self._batch = {
            "cases": cases,
            "index": -1,
            "nodes": [],
            "completed": 0,
            "failed": [],
            "stopped": False,
            "approvedImageBytes": 0,
            "pending": False,
            "report": reportDocument,
            "report_node": reportNode,
            "report_index": {index: index for index in range(len(cases))},
            "case_started": time.monotonic(),
            "scene_closing": False,
            "restore": {
                "subject": str(self.ui.subjectIdLineEdit.text),
                "append": bool(self.ui.appendResultsCheckBox.checked),
                "volume": self.ui.inputVolumeSelector.currentNodeID,
                "segmentation": self.ui.segmentationSelector.currentNodeID,
                "segments": self._selectedSegmentIDs(),
            },
        }
        self.ui.appendResultsCheckBox.setChecked(True)
        self._startNextBatchCase()

    def _batchCaseText(self) -> str:
        if self._batch is None or not 0 <= self._batch["index"] < len(self._batch["cases"]):
            return ""
        case = self._batch["cases"][self._batch["index"]]
        return f"Case {self._batch['index'] + 1} of {len(self._batch['cases'])} ({case.name}). "

    def _reportRunError(self, message: str, title: str):
        """Show a run error, or keep it for the summary at the end of a batch."""

        if self._batch is None:
            slicer.util.errorDisplay(message, windowTitle=title)
            return
        case = self._batch["cases"][self._batch["index"]]
        LOGGER.error("Batch case %s: %s", case.name, message)
        self._batch["failed"].append(f"{case.name}: {message}")
        self._reportBatchCase("failed", reason=message)

    def _removeBatchNodes(self):
        for node in self._batch["nodes"] if self._batch is not None else []:
            if node.GetScene() == slicer.mrmlScene:
                slicer.mrmlScene.RemoveNode(node)
        if self._batch is not None:
            self._batch["nodes"] = []

    def _scheduleNextBatchCase(self):
        if self._batch is not None and not self._batch["pending"]:
            self._batch["pending"] = True
            qt.QTimer.singleShot(0, self._startNextBatchCase)

    def _startNextBatchCase(self):
        batch = self._batch
        if batch is None or self._activeJob is not None:
            return
        batch["pending"] = False
        self._removeBatchNodes()
        batch["index"] += 1
        if batch["stopped"] or batch["index"] >= len(batch["cases"]):
            self._finishBatch()
            return
        case = batch["cases"][batch["index"]]
        batch["case_started"] = time.monotonic()
        self._reportBatchCase("running")
        try:
            volume = slicer.util.loadVolume(str(case.image), {"show": False})
            batch["nodes"].append(volume)
            segmentation = None
            if case.segmentation is not None:
                segmentation = slicer.util.loadSegmentation(str(case.segmentation))
                batch["nodes"].append(segmentation)
        except Exception as exc:
            self._reportRunError(f"Could not load the case files: {exc}", "Pictologics batch")
            self._scheduleNextBatchCase()
            return
        self.ui.inputVolumeSelector.setCurrentNode(volume)
        # Selecting the segmentation checks every one of its segments.
        self.ui.segmentationSelector.setCurrentNode(segmentation)
        self.ui.subjectIdLineEdit.setText(case.name)
        self.onRun()
        if self._batch is batch and self._activeJob is None:
            if batch["report"]["rows"][batch["index"]]["status"] == "running":
                if batch["stopped"]:
                    self._reportBatchCase("cancelled", reason="Run did not start.")
                else:
                    self._reportRunError("The case ended without a confirmed result.", "Pictologics batch")
            self._scheduleNextBatchCase()

    def _finishBatch(self):
        batch, self._batch = self._batch, None
        if batch.get("report"):
            for row in batch["report"]["rows"]:
                if row["status"] == "not_started":
                    row["reason"] = (
                        "Batch stopped before this case started."
                        if batch["stopped"]
                        else "Case was not reached."
                    )
            batch["report"]["state"] = (
                "interrupted" if batch.get("scene_closing")
                else ("stopped" if batch["stopped"] else "finished")
            )
            batch["report"]["finished_at"] = datetime.now(timezone.utc).isoformat()
            self._syncBatchReport(batch["report"], batch["report_node"])
            self._refreshBatchReports()
        restore = batch["restore"]
        if restore is not None and not batch.get("scene_closing"):
            self.ui.inputVolumeSelector.setCurrentNode(slicer.mrmlScene.GetNodeByID(restore["volume"]))
            self.ui.segmentationSelector.setCurrentNode(slicer.mrmlScene.GetNodeByID(restore["segmentation"]))
            self._rebuildSegmentList(set(restore["segments"]))
            self.ui.subjectIdLineEdit.setText(restore["subject"])
            self.ui.appendResultsCheckBox.setChecked(restore["append"])
            self.updateParameterNodeFromGUI()
        summary = f"Batch finished: {batch['completed']} of {len(batch['cases'])} case(s) added rows."
        if batch["stopped"]:
            summary = f"Batch stopped after {batch['index']} of {len(batch['cases'])} case(s). " + summary
        if batch["failed"]:
            summary += f" {len(batch['failed'])} case(s) failed."
            slicer.util.warningDisplay(
                "\n".join(batch["failed"][:20]), windowTitle="Pictologics batch problems"
            )
        self.ui.statusLabel.setText(summary)
        self._updateRunState()

    def onCancel(self):
        if self._nodeIsBusy(self._cliNode):
            self._cancelRequested = True
            self.ui.statusLabel.setText("Cancelling Pictologics…")
            self.ui.cancelButton.setEnabled(False)
            # Cancel may synchronously deliver a terminal event; set feedback first.
            self._cliNode.Cancel()

    def _startRunFeedback(self):
        self._runStartedAt = time.monotonic()
        self._diagnosticRun = {"state": "starting", "elapsed_seconds": 0}
        self._recordDiagnosticOperation("run", "in_progress")
        self._cancelRequested = False
        self.ui.elapsedTimeLabel.show()
        self._updateRunFeedback()
        self._runFeedbackTimer.start()

    def _stopRunFeedback(self):
        if self._runFeedbackTimer is not None:
            self._runFeedbackTimer.stop()
        if self._runStartedAt is not None:
            self.ui.elapsedTimeLabel.setText(elapsed_text(time.monotonic() - self._runStartedAt))
            self._diagnosticRun["elapsed_seconds"] = max(0, int(time.monotonic() - self._runStartedAt))
        self._runStartedAt = None

    def _updateRunFeedback(self):
        if self._runStartedAt is not None:
            self.ui.elapsedTimeLabel.setText(elapsed_text(time.monotonic() - self._runStartedAt))
        if (
            self._activeJob is None
            or self._cliNode is None
            or self._finishingJob
        ):
            return
        if not self._nodeIsBusy(self._cliNode):
            # Also sample terminal state on the timer: a CLI can finish between
            # event delivery and observer registration, or coalesce notifications.
            self.onCliModified(self._cliNode)
            return
        if self._cancelRequested or self._activeJob.get("discard_results"):
            return
        if self._cliProgressPercent(self._cliNode) >= 100:
            self.ui.statusLabel.setText("Finalizing worker output…")
            return
        rois = self._activeJob["manifest"]["rois"]
        index = current_roi_index(str(self._cliNode.GetOutputText() or ""), len(rois))
        if index is not None:
            self.ui.statusLabel.setText(
                f"{self._batchCaseText()}Processing ROI {index + 1} of {len(rois)}: "
                f"{rois[index]['roi_name']}"
            )

    def _beginCliProgress(self, roiCount: int):
        # The current worker reports completed ROI boundaries. A single ROI has
        # no truthful intermediate percentage, so show Qt's animated busy indicator.
        self._cliProgressIndeterminate = roiCount <= 1
        if self._cliProgressIndeterminate:
            self.ui.progressBar.setTextVisible(False)
            self.ui.progressBar.setRange(0, 0)
        else:
            self._restoreCliProgress(0)

    def _restoreCliProgress(self, value: int):
        self.ui.progressBar.setRange(0, 100)
        self.ui.progressBar.setTextVisible(True)
        self.ui.progressBar.setValue(max(0, min(100, int(value))))
        self._cliProgressIndeterminate = False

    @staticmethod
    def _cliProgressPercent(cliNode) -> int:
        # The worker emits fractions, but vtkMRMLCommandLineModuleNode.GetProgress
        # already returns an integer percentage. qSlicerCLIProgressBar reads the
        # underlying ProcessInformation fraction directly, so its scaling differs.
        return max(0, min(100, int(round(float(cliNode.GetProgress())))))

    def onCliModified(self, cliNode, event=None):
        if cliNode is not self._cliNode or self._finishingJob:
            return
        if not self._cliProgressIndeterminate:
            try:
                self.ui.progressBar.setValue(self._cliProgressPercent(cliNode))
            except (TypeError, ValueError, OverflowError):
                pass

        if cliNode.IsBusy():
            self._updateRunFeedback()
            return

        status = int(cliNode.GetStatus())
        statusText = str(cliNode.GetStatusString() or "")
        failed = bool(status & int(cliNode.ErrorsMask))
        cancelled = "cancel" in statusText.lower()
        completed = "completed" in statusText.lower()
        if not (failed or cancelled or completed):
            # The immediate post-observer check can briefly see Idle before the CLI
            # scheduler marks the node busy. Wait for a terminal ModifiedEvent.
            return

        self._finishingJob = True
        # Stop a single-ROI busy animation on every terminal path. Success sets 100
        # only after the atomic result has been validated and committed.
        self._restoreCliProgress(0)
        try:
            if self._activeJob and self._activeJob.get("discard_results"):
                self._recordDiagnosticOperation("run", "discarded")
                self.ui.statusLabel.setText(
                    "The scene changed while Pictologics was running; its results were discarded."
                )
                return
            if failed or cancelled:
                errorText = str(cliNode.GetErrorText() or "").strip()
                if cancelled:
                    self._recordDiagnosticOperation("run", "cancelled")
                    self._reportBatchCase("cancelled", reason="User cancelled the case.")
                    self.ui.statusLabel.setText(
                        "Pictologics was cancelled; the output table was not changed."
                    )
                else:
                    self._recordDiagnosticOperation("run", "failed", "worker_failed")
                    message = (
                        errorText or f"Pictologics CLI ended with status: {statusText}"
                    )
                    LOGGER.error("Pictologics CLI failed: %s", message)
                    self._reportRunError(message, "Pictologics failed")
                    self.ui.statusLabel.setText(
                        "Pictologics failed; the output table was not changed."
                    )
            else:
                with self._tableOperation("Validating and loading results…"):
                    self._acceptCompletedJob()
        except Exception as exc:
            self._recordDiagnosticOperation("run", "failed", "result_rejected")
            LOGGER.exception("Could not commit Pictologics results")
            self._reportRunError(str(exc), "Could not load Pictologics results")
            self.ui.statusLabel.setText(
                "Results were not committed; the previous table is unchanged."
            )
        finally:
            self._stopRunFeedback()
            if self._activeJob:
                self.logic.cleanupJob(self._activeJob)
            self._activeJob = None
            self._detachCliObserver(removeNode=True)
            self._finishingJob = False
            self._updateRunState()
            if self._batch is not None:
                if cancelled:
                    self._batch["stopped"] = True
                self._scheduleNextBatchCase()

    def _acceptCompletedJob(self):
        if not self._activeJob:
            raise RuntimeError("The completed CLI has no active job metadata.")
        outputPath = Path(self._activeJob["output_path"])
        if not outputPath.is_file():
            raise RuntimeError(
                "Pictologics completed without creating its atomic result file."
            )
        payload = validate_result_payload(load_result_payload(outputPath))
        if payload["run_id"] != self._activeJob["manifest"]["run_id"]:
            raise RuntimeError("The result run ID does not match the submitted job.")
        okCount = sum(row["status"] == "ok" for row in payload["rows"])
        if not payload["rows"] or okCount == 0:
            statuses = sorted({row["status"] for row in payload["rows"]}) or ["no rows"]
            raise RuntimeError(
                "Pictologics produced no successful feature values "
                f"(statuses: {', '.join(statuses)}); the output table was not changed."
            )

        outputTableID = self._activeJob.get("output_table_id")
        tableNode = (
            slicer.mrmlScene.GetNodeByID(outputTableID) if outputTableID else None
        )
        if outputTableID and tableNode is None:
            raise RuntimeError(
                "The selected output table was removed while Pictologics was running; "
                "results were not committed."
            )
        if self.logic.tableModificationTime(tableNode) != self._activeJob.get(
            "output_table_mtime"
        ):
            raise RuntimeError(
                "The selected output table changed while Pictologics was running; "
                "results were not committed to avoid overwriting newer data."
            )

        selectedTable = tableNode
        self.ui.statusLabel.setText(f"Loading {len(payload['rows']):,} result rows into the table…")
        self.ui.statusLabel.repaint()
        tableNode = self.logic.commitRows(
            tableNode,
            payload["rows"],
            append=bool(self._activeJob.get("append_results")),
            payload=payload,
            manifest=self._activeJob["manifest"],
        )
        moved = ""
        if selectedTable is not None and tableNode is not selectedTable:
            names = ", ".join(self.logic.configurationConflicts(selectedTable, payload))
            moved = (
                f" {selectedTable.GetName()} holds {names} with other settings, so the "
                "results went to a new table."
            )
        self._lastPayload = payload
        errorCount = len(payload.get("errors", []))
        nonOkCount = len(payload["rows"]) - okCount
        if self._batch is not None:
            self._batch["completed"] += 1
            self._reportBatchCase(
                "partial" if errorCount or nonOkCount else "completed",
                row_count=len(payload["rows"]),
                roi_count=len(self._activeJob["manifest"].get("rois", [])),
                run_id=payload["run_id"],
                result_table=tableNode.GetName(),
                reason=(f"{errorCount} ROI error(s), {nonOkCount} non-success row(s)." if errorCount or nonOkCount else ""),
            )
        self.ui.outputTableSelector.setCurrentNode(tableNode)
        self.updateParameterNodeFromGUI()
        self._restoreCliProgress(100)
        self._diagnosticRun["feature_rows"] = len(payload["rows"])
        self._recordDiagnosticOperation(
            "run", "partial" if errorCount or nonOkCount else "completed",
            "partial_results" if errorCount or nonOkCount else "none",
        )
        if errorCount or nonOkCount:
            self.ui.statusLabel.setText(
                f"Completed with {errorCount} ROI error(s) and {nonOkCount} non-success "
                f"feature row(s): {len(payload['rows'])} rows committed to "
                f"{tableNode.GetName()}.{moved}"
            )
        else:
            self.ui.statusLabel.setText(
                f"Completed: {len(payload['rows'])} feature rows committed to "
                f"{tableNode.GetName()}.{moved}"
            )
        self.logic.showTable(tableNode)

    def _detachCliObserver(self, *, removeNode: bool):
        node = self._cliNode
        if node is not None and self._cliObserverTag is not None:
            try:
                node.RemoveObserver(self._cliObserverTag)
            except RuntimeError:
                pass
        self._cliObserverTag = None
        self._cliNode = None
        if self._continuousOutputNode is not None:
            try:
                self._continuousOutputNode.EndContinuousOutputUpdate()
            except RuntimeError:
                pass
            self._continuousOutputNode = None
        if removeNode and node is not None:
            try:
                if node.GetScene() == slicer.mrmlScene:
                    slicer.mrmlScene.RemoveNode(node)
            except RuntimeError:
                pass

    @staticmethod
    def _nodeIsBusy(node) -> bool:
        if node is None:
            return False
        try:
            return bool(node.IsBusy())
        except RuntimeError:
            return False

    def _handoffActiveJobCleanup(self, *, cancel: bool):
        """Detach UI callbacks and transfer a running job to cleanup-only polling."""

        self._stopRunFeedback()
        job = self._activeJob
        node = self._cliNode
        if job is not None:
            self._recordDiagnosticOperation("run", "discarded")
            job["discard_results"] = True
        # Prevent a synchronous Cancel()/ModifiedEvent race from entering UI result
        # handling while the widget is being destroyed.
        self._finishingJob = True
        try:
            self._detachCliObserver(removeNode=False)
            self._activeJob = None
            if job is not None:
                try:
                    (Path(job["work_dir"]) / ".owner-active").unlink(missing_ok=True)
                except (KeyError, OSError, TypeError):
                    pass
                try:
                    _DeferredJobCleanup(node, job, cancel=cancel)
                except Exception:
                    # Never let module/scene teardown fail. PID-aware stale recovery
                    # remains available if a cleanup-only observer cannot be created.
                    LOGGER.exception(
                        "Could not schedule deferred Pictologics job cleanup"
                    )
            elif node is not None and cancel:
                try:
                    if node.IsBusy():
                        node.Cancel()
                except RuntimeError:
                    pass
        finally:
            if hasattr(self, "ui"):
                self._restoreCliProgress(0)
            self._finishingJob = False

    def onExport(self):
        if self._tableOperationInProgress:
            return
        tableNode = self.ui.outputTableSelector.currentNode()
        if tableNode is None or tableNode.GetTable().GetNumberOfRows() == 0:
            slicer.util.errorDisplay(
                "There are no result rows to export.", windowTitle="Pictologics"
            )
            return
        selected = qt.QFileDialog.getSaveFileName(
            slicer.util.mainWindow(),
            "Export Pictologics results",
            f"{tableNode.GetName()}.csv",
            "CSV (*.csv);;JSON (*.json)",
        )
        selected = self._dialogPath(selected)
        if not selected:
            return
        path = Path(selected)
        if not path.suffix:
            path = path.with_suffix(".csv")
        if path.suffix.lower() not in (".csv", ".json"):
            slicer.util.errorDisplay(
                "Choose a .csv or .json filename.", windowTitle="Pictologics"
            )
            return
        try:
            wide = bool(self.ui.exportWideCheckBox.checked)
            with self._tableOperation(f"Exporting {tableNode.GetNumberOfRows():,} result rows to {path.suffix[1:].upper()}…", tableNode):
                rows = self.logic.rowsFromTable(tableNode)
                exportedPaths = self.logic.exportTable(tableNode, path, rows=rows, wide=wide)
            self._recordDiagnosticOperation("export", "completed")
            destinations = ", ".join(str(item) for item in exportedPaths)
            layout = "wide" if wide else "long"
            self.ui.statusLabel.setText(
                f"Exported {len(rows)} rows ({layout} layout) and provenance to "
                f"{destinations}."
            )
        except Exception as exc:
            self._recordDiagnosticOperation("export", "failed", "export_failed")
            LOGGER.exception("Pictologics export failed")
            slicer.util.errorDisplay(str(exc), windowTitle="Pictologics export failed")
            self.ui.statusLabel.setText("Export failed; results remain in the table. Check the output folder and retry.")


class PictologicsSlicerLogic(ScriptedLoadableModuleLogic):
    """Dependency, data-conversion, CLI, and atomic table orchestration."""

    def __init__(self, parent=None):
        super().__init__(parent)
        _resultPersistence()

    def setDefaultParameters(self, parameterNode):
        if not parameterNode.GetParameter(PARAM_WHOLE_VOLUME):
            # Off by default: the presets resample the entire scan for a whole-volume
            # region, which can need several gigabytes of memory for a large CT.
            parameterNode.SetParameter(PARAM_WHOLE_VOLUME, "false")
        if not parameterNode.GetParameter(PARAM_APPEND_RESULTS):
            parameterNode.SetParameter(PARAM_APPEND_RESULTS, "false")
        if not parameterNode.GetParameter(PARAM_SELECTED_SEGMENTS):
            parameterNode.SetParameter(PARAM_SELECTED_SEGMENTS, "[]")
        if not parameterNode.GetParameter(PARAM_STANDARD_CONFIGURATIONS):
            parameterNode.SetParameter(
                PARAM_STANDARD_CONFIGURATIONS, json.dumps([DEFAULT_CONFIGURATION])
            )
        if not parameterNode.GetParameter(PARAM_ADDITIONAL_SOURCE):
            parameterNode.SetParameter(PARAM_ADDITIONAL_SOURCE, "none")
        if not parameterNode.GetParameter(PARAM_INLINE_CONFIG):
            parameterNode.SetParameter(
                PARAM_INLINE_CONFIG, json.dumps(default_inline_state())
            )

    @staticmethod
    def segmentIDs(segmentationNode) -> list[str]:
        if segmentationNode is None or segmentationNode.GetSegmentation() is None:
            return []
        ids = vtk.vtkStringArray()
        segmentationNode.GetSegmentation().GetSegmentIDs(ids)
        return [str(ids.GetValue(index)) for index in range(ids.GetNumberOfValues())]

    @staticmethod
    def requirementsPath() -> Path:
        return Path(__file__).resolve().with_name("requirements-pictologics.txt")

    @staticmethod
    def constraintsPath() -> Path:
        return Path(__file__).resolve().with_name("constraints-pictologics.txt")

    def pictologicsRequirement(self):
        return parse_pictologics_requirement(self.requirementsPath())

    @staticmethod
    def dependencyRoot() -> Path:
        """Return durable, runtime-scoped storage for private Python packages.

        ``slicer.app.cachePath`` is managed by Slicer's size-limited I/O cache and may
        be pruned at any time.  QStandardPaths' local application-data location is
        persistent and non-roaming, which is appropriate for the large private wheel
        environment.  The compatibility suffix prevents reuse across incompatible
        Slicer Python or CPU runtimes.
        """

        applicationData = str(
            qt.QStandardPaths.writableLocation(
                qt.QStandardPaths.AppLocalDataLocation
            )
        ).strip()
        if not applicationData:
            settingsPath = str(slicer.app.slicerUserSettingsFilePath).strip()
            if not settingsPath:
                raise RuntimeError(
                    "Slicer did not provide a persistent per-user data location."
                )
            applicationData = str(Path(settingsPath).parent / "application-data")

        components = (
            f"slicer-{int(slicer.app.majorVersion)}.{int(slicer.app.minorVersion)}",
            sys.implementation.cache_tag
            or f"python-{sys.version_info.major}.{sys.version_info.minor}",
            platform.machine() or "unknown-architecture",
        )
        runtimeTag = "-".join(
            "".join(
                character if character.isalnum() or character in "._-" else "_"
                for character in component
            )
            for component in components
        )
        return Path(applicationData) / "SlicerPictologics" / runtimeTag

    @classmethod
    def jobsRoot(cls) -> Path:
        # Job cleanup must remain available even if the independent dependency
        # environment pointer is damaged.
        return cls.dependencyRoot() / "jobs"

    @classmethod
    def privatePaths(cls) -> dict[str, Path]:
        return dependency_paths(cls.dependencyRoot())

    def inspectDependencies(self):
        paths = self.privatePaths()
        return inspect_target(paths["dependency_target"], self.pictologicsRequirement())

    def ensureDependencies(self, *, forceUpgrade: bool):
        requirement = self.pictologicsRequirement()
        paths = self.privatePaths()
        target = paths["dependency_target"]
        paths["cache_root"].mkdir(parents=True, exist_ok=True)
        paths["environments_root"].mkdir(parents=True, exist_ok=True)
        paths["numba_cache"].mkdir(parents=True, exist_ok=True)
        before = inspect_target(target, requirement)
        if before.satisfied and not before.ambiguous and not forceUpgrade:
            return before

        developmentSource = os.environ.get("PICTOLOGICS_DEV_SOURCE", "").strip()
        if developmentSource:
            sourceDescription = f"Development source: {developmentSource}"
        else:
            sourceDescription = "Source: Python package index (network access required)"
        action = "updated" if forceUpgrade or before.installed else "installed"
        message = (
            f"Pictologics must be {action} in an extension-private Python folder:\n\n"
            f"{paths['environments_root']}\n\nRequirement: {requirement}\n"
            f"{sourceDescription}\n\n"
            "This does not modify Slicer's shared Python packages. Continue?"
        )
        if not slicer.util.confirmOkCancelDisplay(
            message, windowTitle="Install isolated Pictologics"
        ):
            raise DependencyInstallDeclined()

        from slicer import packaging

        # Resolve into a fresh immutable environment. A failed pip operation cannot
        # damage the active worker environment, and already-running workers retain
        # their exact dependency path when a new environment is activated.
        staging = Path(
            tempfile.mkdtemp(prefix=".installing-", dir=paths["environments_root"])
        )
        published: Path | None = None
        activated = False
        try:
            arguments = build_pip_install_args(
                requirement,
                staging,
                dev_source=developmentSource or None,
                force_upgrade=False,
                constraints=self.constraintsPath(),
            )
            packaging.pip_install(
                arguments, show_progress=True, requester="Pictologics"
            )
            stagedInspection = inspect_target(staging, requirement)
            if not stagedInspection.satisfied or stagedInspection.ambiguous:
                versions = ", ".join(stagedInspection.installed_versions) or "none"
                raise RuntimeError(
                    "The staged private installation is not a single compatible "
                    f"Pictologics distribution. Found: {versions}; required: {requirement}."
                )

            expectedVersion = stagedInspection.installed_version or ""
            self.probeDependencyEnvironment(staging, expectedVersion, warmup=False)
            environmentBase = dependency_environment_path(
                paths["cache_root"], expectedVersion
            )
            # A short suffix keeps the deepest package files within Windows' path limit.
            published = environmentBase.with_name(
                f"{environmentBase.name}-{uuid.uuid4().hex[:8]}"
            )
            staging.rename(published)
            # Run the full JIT probe after relocation but before activation: Numba
            # cache discovery can depend on a module's final filesystem location.
            self.probeDependencyEnvironment(published, expectedVersion, warmup=True)
            activate_dependency_target(paths["cache_root"], published)
            activated = True
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
            if published is not None and published.exists() and not activated:
                shutil.rmtree(published, ignore_errors=True)

        # Return the environment this invocation activated, not a newly read pointer:
        # another Slicer instance may legitimately activate a different immutable
        # version between these two operations.
        if published is None:  # defensive: all successful install paths publish
            raise RuntimeError("The private dependency environment was not published.")
        after = inspect_target(published, requirement)
        if not after.satisfied or after.ambiguous:
            versions = ", ".join(after.installed_versions) or "none"
            raise RuntimeError(
                f"The isolated installation did not produce one compatible Pictologics "
                f"distribution. Found: {versions}; required: {requirement}."
            )
        self.removeRetiredEnvironments()
        return after

    @staticmethod
    def dependencyProbePath() -> Path:
        return (
            Path(__file__).resolve().parent / "PictologicsLib" / "dependency_probe.py"
        )

    def _launchPythonSlicer(self, arguments: Sequence[str]):
        """Start a fresh PythonSlicer process for the private Pictologics folder."""

        pythonSlicer = shutil.which("PythonSlicer")
        if not pythonSlicer:
            raise RuntimeError(
                "PythonSlicer was not found; the private Pictologics environment "
                "cannot be validated safely."
            )
        return slicer.util.launchConsoleProcess(
            [pythonSlicer, *arguments],
            useStartupEnvironment=False,
            updateEnvironment={
                "NUMBA_CACHE_DIR": str(self.privatePaths()["numba_cache"]),
                "PICTOLOGICS_DISABLE_WARMUP": "1",
                "PYTHONNOUSERSITE": "1",
            },
        )

    def checkConfigurationFile(self, path: Path) -> dict[str, Any] | None:
        """Load a custom configuration file with Pictologics, as a run loads it.

        Return None when the adopted Pictologics release is not installed yet.
        """

        inspection = self.inspectDependencies()
        if not inspection.satisfied or inspection.ambiguous:
            return None
        process = self._launchPythonSlicer(
            [
                str(slicer.modules.pictologicscli.path),
                "--check-configuration",
                str(path),
                str(inspection.target),
            ]
        )
        output, _ = process.communicate()
        return parse_configuration_check(output)

    def probeDependencyEnvironment(
        self, target: Path, expectedVersion: str, *, warmup: bool
    ) -> None:
        """Validate a candidate in a fresh PythonSlicer interpreter."""

        command = [str(self.dependencyProbePath()), str(target), expectedVersion]
        if not warmup:
            command.append("--skip-warmup")
        process = self._launchPythonSlicer(command)
        try:
            slicer.util.logProcessOutput(process)
        except Exception as exc:
            raise RuntimeError(
                "The newly installed private Pictologics environment failed its "
                "import/API/JIT probe; the previous environment remains active."
            ) from exc

    @staticmethod
    def scannerDetails(volumeNode) -> dict[str, str]:
        """Read the scanner details of a volume from DICOM or a dcm2niix JSON file.

        Return an empty dictionary when neither source is available.
        """

        instanceUIDs = str(volumeNode.GetAttribute("DICOM.instanceUIDs") or "").split()
        database = getattr(slicer, "dicomDatabase", None)
        filePath = (
            database.fileForInstance(instanceUIDs[0])
            if instanceUIDs and database is not None and database.isOpen
            else ""
        )
        if filePath:
            return {
                column: scanner_value(database.fileValue(filePath, tag))
                for column, tag, _ in SCANNER_COLUMNS
            }
        storage = volumeNode.GetStorageNode()
        sidecar = sidecar_path(str(storage.GetFileName() or "")) if storage else None
        if sidecar is None or not sidecar.is_file():
            return {}
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            LOGGER.warning("Could not read the scanner details in %s", sidecar)
            return {}
        return scanner_details_from_sidecar(data) if isinstance(data, dict) else {}

    def resultColumns(
        self, volumeNode, reader: str, extraColumns: Sequence[tuple[str, str]]
    ) -> list[tuple[str, str]]:
        """Return the reader, scanner, and user columns that every row of a run gets."""

        return build_result_columns(reader, self.scannerDetails(volumeNode), extraColumns)

    def prepareJob(
        self,
        *,
        inputVolumeNode,
        segmentationNode,
        selectedSegmentIDs: Sequence[str],
        includeWholeVolume: bool,
        standardConfigurations: Sequence[str],
        customConfigurationPath: str | None,
        subjectID: str,
        installedVersion: str,
        dependencyPath: Path,
        inlineConfigurationDocument: dict[str, Any] | None = None,
        resultColumns: Sequence[tuple[str, str]] | None = None,
        cropToRegion: bool = False,
    ) -> dict[str, Any]:
        self.purgeStaleJobs()
        jobsRoot = self.jobsRoot()
        jobsRoot.mkdir(parents=True, exist_ok=True)
        workDir = Path(tempfile.mkdtemp(prefix="job-", dir=jobsRoot))
        sceneNodes: list[Any] = []
        try:
            (workDir / ".owner-active").write_text(
                f"pid={os.getpid()}\n", encoding="utf-8"
            )
            imagePath = workDir / "image.nii.gz"
            clone = self._cloneAndHardenVolume(inputVolumeNode)
            # CloneVolume creates a private display node but may reference a shared
            # scene color node. Remove the former, never the latter.
            sceneNodes.extend(self._temporaryNodeFamily(clone, includeColor=False))
            if not slicer.util.saveNode(clone, str(imagePath)):
                raise RuntimeError("Slicer could not save the input volume as NIfTI.")
            if clone.GetStorageNode() is not None:
                sceneNodes.append(clone.GetStorageNode())

            rois: list[dict[str, Any]] = []
            if includeWholeVolume:
                rois.append(
                    {
                        "roi_id": "whole-volume",
                        "roi_name": "Whole volume",
                        "roi_source": "whole-volume",
                        "mask_path": None,
                    }
                )
            if selectedSegmentIDs:
                if segmentationNode is None:
                    raise ValueError(
                        "A segmentation is required for selected segment ROIs."
                    )
                segmentationTransform = segmentationNode.GetParentTransformNode()
                if (
                    segmentationTransform is not None
                    and not segmentationTransform.IsTransformToWorldLinear()
                ):
                    raise ValueError(
                        "The segmentation is under a non-linear transform. Resample it "
                        "into the input volume geometry before running Pictologics."
                    )
                knownIDs = set(self.segmentIDs(segmentationNode))
                unknown = [
                    segmentID
                    for segmentID in selectedSegmentIDs
                    if segmentID not in knownIDs
                ]
                if unknown:
                    raise ValueError(
                        f"Selected segment IDs no longer exist: {', '.join(unknown)}"
                    )
                for index, segmentID in enumerate(selectedSegmentIDs):
                    maskPath = workDir / f"roi-{index:04d}.nii.gz"
                    labelmap = slicer.mrmlScene.AddNewNodeByClass(
                        "vtkMRMLLabelMapVolumeNode", f"Pictologics-ROI-{index:04d}"
                    )
                    sceneNodes.append(labelmap)
                    ids = vtk.vtkStringArray()
                    ids.InsertNextValue(segmentID)
                    success = slicer.modules.segmentations.logic().ExportSegmentsToLabelmapNode(
                        segmentationNode, ids, labelmap, clone
                    )
                    if not success or labelmap.GetImageData() is None:
                        raise RuntimeError(
                            f"Could not export segment {segmentID} in image geometry."
                        )
                    # ExportSegmentsToLabelmapNode creates a labelmap-specific display
                    # and user color table. Both are temporary for this conversion.
                    sceneNodes.extend(
                        self._temporaryNodeFamily(labelmap, includeColor=True)[1:]
                    )
                    scalarRange = labelmap.GetImageData().GetScalarRange()
                    if scalarRange[1] <= 0:
                        raise ValueError(
                            f"Segment {segmentID} is empty in the input image geometry."
                        )
                    if not slicer.util.saveNode(labelmap, str(maskPath)):
                        raise RuntimeError(
                            f"Slicer could not save the mask for segment {segmentID}."
                        )
                    if labelmap.GetStorageNode() is not None:
                        sceneNodes.append(labelmap.GetStorageNode())
                    segment = segmentationNode.GetSegmentation().GetSegment(segmentID)
                    rois.append(
                        {
                            "roi_id": segmentID,
                            "roi_name": str(
                                segment.GetName() if segment else segmentID
                            ),
                            "roi_source": "segmentation",
                            "mask_path": str(maskPath),
                            "metadata": {
                                "segmentation_name": str(segmentationNode.GetName())
                            },
                        }
                    )
            if not rois:
                raise ValueError("No whole-volume or segment ROI was selected.")

            customCopyName = None
            customDigest = None
            if inlineConfigurationDocument is not None:
                # The in-app builder emits a JSON document; the worker loads it via the
                # same load_configs path used for user-provided custom files.
                destination = workDir / "custom-configuration.json"
                destination.write_text(
                    json.dumps(inlineConfigurationDocument, indent=2) + "\n",
                    encoding="utf-8",
                )
                customCopyName = destination.name
                customDigest = sha256_file(destination)
            elif customConfigurationPath:
                source = Path(customConfigurationPath).expanduser().resolve()
                if not source.is_file():
                    raise FileNotFoundError(f"Custom configuration not found: {source}")
                suffix = ".json" if source.suffix.lower() == ".json" else ".yaml"
                destination = workDir / f"custom-configuration{suffix}"
                shutil.copy2(source, destination)
                customCopyName = destination.name
                customDigest = sha256_file(destination)

            configurationDocument = {
                "standard_configurations": list(standardConfigurations),
                "custom_configuration_path": customCopyName,
                "custom_configuration_sha256": customDigest,
                "warmup": True,
            }
            if cropToRegion:
                configurationDocument["crop_to_roi"] = True
            outputPath = workDir / "results.json"
            provenancePath = workDir / "provenance.json"
            paths = self.privatePaths()
            requirement = self.pictologicsRequirement()
            manifest = build_job_manifest(
                image_path=str(imagePath),
                image_name=str(inputVolumeNode.GetName()),
                rois=rois,
                configuration_document=configurationDocument,
                results_path=str(outputPath),
                provenance_path=str(provenancePath),
                subject_id=subjectID,
                result_columns=resultColumns,
                extension_version=EXTENSION_VERSION,
                pictologics_requirement=str(requirement),
                metadata={
                    "numba_cache_path": str(paths["numba_cache"]),
                    "pictologics_version_at_submission": installedVersion,
                    "input_volume_node_id": str(inputVolumeNode.GetID()),
                },
            )
            manifestPath = workDir / "job-manifest.json"
            write_job_manifest(manifestPath, manifest)
            return {
                "work_dir": workDir,
                "manifest_path": manifestPath,
                "output_path": outputPath,
                "provenance_path": provenancePath,
                "dependency_path": Path(dependencyPath).resolve(strict=False),
                "manifest": manifest,
            }
        except Exception:
            shutil.rmtree(workDir, ignore_errors=True)
            raise
        finally:
            self._removeTemporaryNodes(sceneNodes)

    @staticmethod
    def _cloneAndHardenVolume(inputVolumeNode):
        name = f"Pictologics-Input-{inputVolumeNode.GetID()}"
        volumesLogic = slicer.modules.volumes.logic()
        try:
            clone = volumesLogic.CloneVolume(inputVolumeNode, name)
        except TypeError:
            clone = volumesLogic.CloneVolume(slicer.mrmlScene, inputVolumeNode, name)
        if clone is None:
            raise RuntimeError("Slicer could not clone the input volume.")
        parentTransform = clone.GetParentTransformNode()
        if parentTransform is not None:
            if not parentTransform.IsTransformToWorldLinear():
                display = clone.GetDisplayNode()
                slicer.mrmlScene.RemoveNode(clone)
                if display is not None and display.GetScene() == slicer.mrmlScene:
                    slicer.mrmlScene.RemoveNode(display)
                raise ValueError(
                    "The input volume is under a non-linear transform. Resample the volume "
                    "into a fixed geometry before running Pictologics."
                )
            clone.HardenTransform()
        return clone

    @staticmethod
    def _temporaryNodeFamily(node, *, includeColor: bool) -> list[Any]:
        family = [node]
        if node is None:
            return family
        display = node.GetDisplayNode() if hasattr(node, "GetDisplayNode") else None
        if display is not None:
            family.append(display)
            if includeColor:
                color = (
                    display.GetColorNode() if hasattr(display, "GetColorNode") else None
                )
                if color is not None:
                    family.append(color)
        return family

    @staticmethod
    def _removeTemporaryNodes(nodes: Iterable[Any]):
        seen = set()
        for node in reversed(list(nodes)):
            if node is None:
                continue
            identity = id(node)
            if identity in seen:
                continue
            seen.add(identity)
            try:
                if node.GetScene() == slicer.mrmlScene:
                    slicer.mrmlScene.RemoveNode(node)
            except RuntimeError:
                pass

    @staticmethod
    def startJob(job: dict[str, Any], *, wait: bool = False):
        cliModule = getattr(slicer.modules, "pictologicscli", None)
        if cliModule is None:
            raise RuntimeError(
                "PictologicsCLI is unavailable. Rebuild/reinstall the extension with its "
                "PictologicsCLI submodule enabled."
            )
        parameters = {
            "jobManifest": str(job["manifest_path"]),
            "dependencyPath": str(job["dependency_path"]),
            "outputResults": str(job["output_path"]),
        }
        return slicer.cli.run(cliModule, None, parameters, wait_for_completion=wait)

    @classmethod
    def cleanupJob(cls, job: dict[str, Any]):
        """Remove only a job directory owned by this extension's private data."""

        workDir = Path(job.get("work_dir", "")).resolve(strict=False)
        jobsRoot = cls.jobsRoot().resolve(strict=False)
        if (
            workDir.parent == jobsRoot
            and workDir.name.startswith("job-")
            and workDir.is_dir()
            and not workDir.is_symlink()
        ):
            shutil.rmtree(workDir, ignore_errors=True)

    def process(
        self,
        inputVolumeNode,
        segmentationNode=None,
        *,
        segmentIDs: Sequence[str] | None = None,
        includeWholeVolume: bool = False,
        standardConfigurations: Sequence[str] = (DEFAULT_CONFIGURATION,),
        customConfigurationPath: str | None = None,
        subjectID: str = "",
        reader: str = "",
        extraColumns: dict[str, str] | None = None,
        cropToRegion: bool = False,
        outputTable=None,
    ):
        """Run Pictologics to the end and return the results table (for scripts).

        Slicer waits until the worker stops. The new rows go after the rows that are
        in ``outputTable``; with no table, a new table is made. By default, every
        segment of the segmentation is a region. ``reader`` and ``extraColumns``
        become text columns of every row, after the scanner details.
        """

        inspection = self.ensureDependencies(forceUpgrade=False)
        job = self.prepareJob(
            inputVolumeNode=inputVolumeNode,
            segmentationNode=segmentationNode,
            selectedSegmentIDs=(
                self.segmentIDs(segmentationNode) if segmentIDs is None else segmentIDs
            ),
            includeWholeVolume=includeWholeVolume,
            standardConfigurations=standardConfigurations,
            customConfigurationPath=customConfigurationPath,
            subjectID=subjectID,
            installedVersion=inspection.installed_version or "",
            dependencyPath=inspection.target,
            resultColumns=self.resultColumns(
                inputVolumeNode, reader, list((extraColumns or {}).items())
            ),
            cropToRegion=cropToRegion,
        )
        cliNode = None
        try:
            cliNode = self.startJob(job, wait=True)
            if cliNode.GetStatus() & cliNode.ErrorsMask:
                raise RuntimeError(
                    str(cliNode.GetErrorText() or "").strip()
                    or f"Pictologics CLI ended with status: {cliNode.GetStatusString()}"
                )
            payload = load_result_payload(job["output_path"])
            if payload["run_id"] != job["manifest"]["run_id"]:
                raise RuntimeError("The result run ID does not match the submitted job.")
            return self.commitRows(
                outputTable,
                payload["rows"],
                append=True,
                payload=payload,
                manifest=job["manifest"],
            )
        finally:
            if cliNode is not None:
                slicer.mrmlScene.RemoveNode(cliNode)
            self.cleanupJob(job)

    @staticmethod
    def _markerPID(marker: Path) -> int | None:
        return read_pid_marker(marker)

    @staticmethod
    def processIsAlive(pid: int) -> bool:
        return process_is_alive(pid)

    @classmethod
    def jobWorkerIsAlive(cls, job: dict[str, Any]) -> bool:
        workDir = Path(job.get("work_dir", "")).resolve(strict=False)
        marker = workDir / ".worker-active"
        pid = cls._markerPID(marker)
        return pid is not None and cls.processIsAlive(pid)

    @classmethod
    def purgeStaleJobs(
        cls,
        *,
        minimumAgeSeconds: float = 60 * 60,
        abandonedWorkerAgeSeconds: float = 7 * 24 * 60 * 60,
        now: float | None = None,
    ) -> int:
        """Recover abandoned image/mask staging directories on module startup.

        The GUI and worker write PID markers, which protect jobs owned by another live
        Slicer/worker process. Unparseable recent markers are retained for seven days;
        dead-owner staging is eligible after one hour. Normal completion, failure,
        cancellation, and module teardown remove staging as soon as the worker exits.
        """

        jobsRoot = cls.jobsRoot().resolve(strict=False)
        jobsRoot.mkdir(parents=True, exist_ok=True)
        currentTime = time.time() if now is None else float(now)
        removed = 0
        for candidate in jobsRoot.iterdir():
            if (
                not candidate.name.startswith("job-")
                or not candidate.is_dir()
                or candidate.is_symlink()
            ):
                continue
            try:
                age = currentTime - candidate.stat().st_mtime
                if age < minimumAgeSeconds:
                    continue
                retainForMarker = False
                for markerName in (".owner-active", ".worker-active"):
                    marker = candidate / markerName
                    if not marker.is_file():
                        continue
                    markerPID = cls._markerPID(marker)
                    if markerPID is not None and cls.processIsAlive(markerPID):
                        retainForMarker = True
                        break
                    markerAge = currentTime - marker.stat().st_mtime
                    if markerPID is None and markerAge < abandonedWorkerAgeSeconds:
                        retainForMarker = True
                        break
                if retainForMarker:
                    continue
                shutil.rmtree(candidate)
                removed += 1
            except FileNotFoundError:
                continue
            except OSError:
                LOGGER.exception(
                    "Could not remove stale Pictologics job directory %s", candidate
                )
        return removed

    def removeRetiredEnvironments(self) -> list[Path]:
        """Delete the package versions that the active pointer no longer selects.

        A running job (also in another Slicer instance) may still use an older version,
        so deletion then waits; module entry and the next installation try again.
        Cleanup problems are logged and never stop a run.
        """

        try:
            paths = self.privatePaths()
            if job_may_be_running(paths["jobs_root"]):
                return []
            removed = remove_inactive_environments(paths["cache_root"])
        except Exception:
            LOGGER.exception("Could not remove old Pictologics environments")
            return []
        for path in removed:
            LOGGER.info("Removed old Pictologics environment %s", path)
        return removed

    def commitRows(
        self,
        tableNode,
        rows: Sequence[dict[str, Any]],
        *,
        append: bool,
        payload: dict[str, Any],
        manifest: dict[str, Any],
    ):
        normalized = validate_result_payload(
            {
                "schema_version": payload["schema_version"],
                "run_id": payload["run_id"],
                "rows": list(rows),
                "provenance": payload.get("provenance", {}),
                "errors": payload.get("errors", []),
            }
        )
        candidate = vtk.vtkTable()
        if (
            append
            and tableNode is not None
            and tableNode.GetTable().GetNumberOfColumns() > 0
        ):
            existing = tableNode.GetTable()
            existingNames = tuple(
                str(existing.GetColumnName(index))
                for index in range(existing.GetNumberOfColumns())
            )
            if not is_result_table_columns(existingNames):
                raise ValueError(
                    "Append was requested, but the selected table does not have the "
                    "Pictologics long-form schema."
                )
            if tableNode.GetAttribute("Pictologics.ResultSchemaVersion") != str(
                RESULT_PAYLOAD_SCHEMA_VERSION
            ):
                raise ValueError(
                    "Append was requested, but the selected table is not marked as a "
                    "versioned Pictologics result table."
                )
            conflicts = self.configurationConflicts(tableNode, payload)
            if conflicts:
                # One column must keep one meaning, so these rows go to a new table.
                LOGGER.warning(
                    "Table %s holds configuration(s) %s with other settings; the new "
                    "results go to a new table.",
                    tableNode.GetName(),
                    ", ".join(conflicts),
                )
                tableNode = None
                append = False
        if append and tableNode is not None and tableNode.GetTable().GetNumberOfColumns() > 0:
            candidate.DeepCopy(tableNode.GetTable())
        else:
            for columnName in LONG_RESULT_COLUMNS:
                column = (
                    vtk.vtkDoubleArray()
                    if columnName == "value"
                    else vtk.vtkStringArray()
                )
                column.SetName(columnName)
                candidate.AddColumn(column)
        # A new extra column gets empty text in the rows that are already there.
        for columnName in extra_columns(normalized["rows"]):
            if candidate.GetColumnByName(columnName) is None:
                column = vtk.vtkStringArray()
                column.SetName(columnName)
                column.SetNumberOfValues(candidate.GetNumberOfRows())
                candidate.AddColumn(column)

        columnNames = [
            str(candidate.GetColumnName(index))
            for index in range(candidate.GetNumberOfColumns())
        ]
        for row in normalized["rows"]:
            for columnName in columnNames:
                column = candidate.GetColumnByName(columnName)
                value = row.get(columnName, "")
                if columnName == "value":
                    column.InsertNextValue(
                        float("nan") if value is None else float(value)
                    )
                else:
                    column.InsertNextValue(str(value))

        provenance = payload.get("provenance", {})
        errors = payload.get("errors", [])
        runRecord = {
            "run_id": str(payload["run_id"]),
            "configuration_sha256": str(manifest["configuration_sha256"]),
            "provenance": provenance,
            "errors": errors,
        }
        if (
            append
            and tableNode is not None
            and tableNode.GetTable().GetNumberOfRows() > 0
        ):
            provenanceHistory = self.provenanceHistory(tableNode, required=True)
            if any(
                record.get("run_id") == payload["run_id"]
                for record in provenanceHistory
            ):
                raise ValueError(
                    f"Run {payload['run_id']} is already present in the table."
                )
            provenanceHistory.append(runRecord)
        else:
            provenanceHistory = [runRecord]

        attributeValues = {
            WARNING_ATTRIBUTE: tableNode.GetAttribute(WARNING_ATTRIBUTE) if append and tableNode is not None else None,
            "Pictologics.ResultSchemaVersion": str(payload["schema_version"]),
            "Pictologics.LastRunID": str(payload["run_id"]),
            "Pictologics.ConfigurationSHA256": str(manifest["configuration_sha256"]),
            "SlicerPictologics.ExtensionVersion": EXTENSION_VERSION,
            "Pictologics.ProvenanceJSON": json.dumps(
                provenance, sort_keys=True, separators=(",", ":")
            ),
            "Pictologics.ErrorsJSON": json.dumps(
                errors, sort_keys=True, separators=(",", ":")
            ),
            "Pictologics.ProvenanceHistoryJSON": json.dumps(
                provenanceHistory, sort_keys=True, separators=(",", ":")
            ),
        }

        created = False
        if tableNode is None:
            tableNode = slicer.mrmlScene.AddNewNodeByClass(
                "vtkMRMLTableNode",
                slicer.mrmlScene.GenerateUniqueName("Pictologics Results"),
            )
            created = True
        previousTable = vtk.vtkTable()
        previousTable.DeepCopy(tableNode.GetTable())
        previousAttributes = {
            name: tableNode.GetAttribute(name) for name in attributeValues
        }
        try:
            wasModified = tableNode.StartModify()
            try:
                tableNode.GetTable().DeepCopy(candidate)
                for name, value in attributeValues.items():
                    tableNode.SetAttribute(name, value)
                tableNode.GetTable().Modified()
            finally:
                tableNode.EndModify(wasModified)
        except Exception:
            if created and tableNode.GetScene() == slicer.mrmlScene:
                slicer.mrmlScene.RemoveNode(tableNode)
            elif not created:
                rollbackModified = tableNode.StartModify()
                try:
                    tableNode.GetTable().DeepCopy(previousTable)
                    for name, value in previousAttributes.items():
                        tableNode.SetAttribute(name, value)
                    tableNode.GetTable().Modified()
                finally:
                    tableNode.EndModify(rollbackModified)
            raise
        return tableNode

    def configurationConflicts(self, tableNode, payload: dict[str, Any]) -> list[str]:
        """Return the names that the table already holds with other settings."""

        if tableNode is None or tableNode.GetTable().GetNumberOfRows() == 0:
            return []
        return configuration_conflicts(
            self.provenanceHistory(tableNode, required=True), payload.get("provenance", {})
        )

    @staticmethod
    def tableModificationTime(tableNode) -> int | None:
        if tableNode is None:
            return None
        table = tableNode.GetTable()
        return max(int(tableNode.GetMTime()), int(table.GetMTime()) if table else 0)

    @staticmethod
    def rowsFromTable(tableNode) -> list[dict[str, Any]]:
        table = tableNode.GetTable()
        names = tuple(
            str(table.GetColumnName(index))
            for index in range(table.GetNumberOfColumns())
        )
        if not is_result_table_columns(names):
            raise ValueError(
                "The selected table is not a Pictologics long-form result table."
            )
        rows: list[dict[str, Any]] = []
        for rowIndex in range(table.GetNumberOfRows()):
            row: dict[str, Any] = {}
            for columnName in names:
                column = table.GetColumnByName(columnName)
                value = column.GetValue(rowIndex)
                if columnName == "value":
                    number = float(value)
                    row[columnName] = None if math.isnan(number) else number
                else:
                    row[columnName] = str(value)
            rows.append(row)
        return rows

    @staticmethod
    def provenanceHistory(tableNode, *, required: bool = False) -> list[dict[str, Any]]:
        text = tableNode.GetAttribute("Pictologics.ProvenanceHistoryJSON")
        if not text:
            if required:
                raise ValueError(
                    "The selected append table has no per-run provenance history."
                )
            return []
        try:
            history = json.loads(text)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "The table's provenance history is not valid JSON."
            ) from exc
        if not isinstance(history, list) or not all(
            isinstance(record, dict) and isinstance(record.get("run_id"), str)
            for record in history
        ):
            raise ValueError("The table's provenance history has an invalid shape.")
        return history

    _DICTIONARY_LEADING_COLUMNS = (
        "config",
        "feature_key",
        "feature_name",
        "ibsi_code",
        "pictologics_ibsi_code",
        "pictologics_feature_name",
        "family",
        "family_group",
        "preprocessing_sequence",
    )

    @classmethod
    def featureDictionary(cls, history: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
        """Deduplicated Pictologics ``describe_features()`` catalog for the table.

        The worker records the feature catalog in each run's provenance; this lifts it
        to a single data dictionary covering every configuration present in the table
        (deduplicated by ``config`` + ``feature_key``), the Slicer-side equivalent of
        ``describe_features().to_csv(...)``.
        """

        collected: dict[tuple[str, str], dict[str, Any]] = {}
        for record in history:
            provenance = record.get("provenance")
            if not isinstance(provenance, dict):
                continue
            catalog = provenance.get("feature_catalog")
            if not isinstance(catalog, list):
                continue
            for entry in catalog:
                if not isinstance(entry, dict):
                    continue
                key = (str(entry.get("config", "")), str(entry.get("feature_key", "")))
                collected.setdefault(key, entry)
        return [collected[key] for key in sorted(collected)]

    @staticmethod
    def _dictionaryColumns(rows: Sequence[dict[str, Any]]) -> list[str]:
        leading = PictologicsSlicerLogic._DICTIONARY_LEADING_COLUMNS
        seen = set(leading)
        extra = sorted({key for row in rows for key in row if key not in seen})
        present_leading = [
            name for name in leading if any(name in row for row in rows)
        ]
        return [*present_leading, *extra]

    def exportTable(
        self,
        tableNode,
        path: Path,
        *,
        rows: Sequence[dict[str, Any]] | None = None,
        wide: bool = False,
    ) -> list[Path]:
        exportedRows = list(rows) if rows is not None else self.rowsFromTable(tableNode)
        history = self.provenanceHistory(tableNode, required=True)
        dictionaryRows = self.featureDictionary(history)
        if path.suffix.lower() == ".json":
            bundle = {
                "schema_version": RESULT_PAYLOAD_SCHEMA_VERSION,
                "table_name": str(tableNode.GetName()),
                "layout": "wide" if wide else "long",
                "rows": rows_to_wide(exportedRows) if wide else exportedRows,
                "feature_dictionary": dictionaryRows,
                "provenance_history": history,
            }
            self._atomicWriteJSON(path, bundle)
            return [path]

        def writeSet(stagedPath: Path) -> list[Path]:
            export_rows(exportedRows, stagedPath, wide=wide)
            exportedPaths = [stagedPath]
            provenancePath = stagedPath.with_name(f"{stagedPath.stem}.provenance.json")
            self._atomicWriteJSON(
                provenancePath,
                {
                    "schema_version": RESULT_PAYLOAD_SCHEMA_VERSION,
                    "table_name": str(tableNode.GetName()),
                    "provenance_history": history,
                },
            )
            exportedPaths.append(provenancePath)
            if dictionaryRows:
                # eigenradiomics finds features_catalog.csv next to features.csv.
                dictionaryPath = stagedPath.with_name(f"{stagedPath.stem}_catalog.csv")
                self._atomicWriteCSV(dictionaryPath, dictionaryRows, self._dictionaryColumns(dictionaryRows))
                exportedPaths.append(dictionaryPath)
            return exportedPaths

        return export_file_set(path, writeSet)

    @staticmethod
    def _atomicWriteJSON(path: Path, payload: dict[str, Any]):
        destination = path.expanduser().resolve(strict=False)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporaryName: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporaryName = stream.name
                json.dump(
                    payload, stream, ensure_ascii=False, indent=2, allow_nan=False
                )
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporaryName, destination)
            temporaryName = None
            _fsync_parent_dir(destination)
        finally:
            if temporaryName:
                try:
                    Path(temporaryName).unlink(missing_ok=True)
                except OSError:
                    pass

    @staticmethod
    def _atomicWriteCSV(
        path: Path, rows: Sequence[dict[str, Any]], columns: Sequence[str]
    ):
        destination = path.expanduser().resolve(strict=False)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporaryName: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporaryName = stream.name
                writer = csv.DictWriter(
                    stream,
                    fieldnames=list(columns),
                    extrasaction="ignore",
                    restval="",
                    lineterminator="\n",
                )
                writer.writeheader()
                writer.writerows(rows)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporaryName, destination)
            temporaryName = None
            _fsync_parent_dir(destination)
        finally:
            if temporaryName:
                try:
                    Path(temporaryName).unlink(missing_ok=True)
                except OSError:
                    pass

    @staticmethod
    def showTable(tableNode):
        try:
            # Create the table view before propagating its selection. A newly
            # created view does not inherit an earlier propagation.
            slicer.app.layoutManager().setLayout(
                slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpTableView
            )
            selectionNode = slicer.app.applicationLogic().GetSelectionNode()
            selectionNode.SetReferenceActiveTableID(tableNode.GetID())
            slicer.app.applicationLogic().PropagateTableSelection()
        except Exception:
            LOGGER.debug("Could not switch to a table layout", exc_info=True)


class PictologicsSlicerTest(ScriptedLoadableModuleTest):
    """Small smoke test; pure support-library tests contain the detailed cases."""

    def setUp(self):
        slicer.mrmlScene.Clear()

    def runTest(self):
        self.setUp()
        self.test_contractFilesAndDefaults()

    def test_contractFilesAndDefaults(self):
        self.delayDisplay("Checking Pictologics extension contracts")
        logic = PictologicsSlicerLogic()
        requirement = logic.pictologicsRequirement()
        self.assertEqual(requirement.name.lower(), "pictologics")
        self.assertIn("standard_fbn_32", STANDARD_CONFIGURATIONS)
        self.assertEqual(
            tuple(LONG_RESULT_COLUMNS)[-2:],
            ("pictologics_version", "extension_version"),
        )
        self.delayDisplay("Pictologics contract smoke test passed")
