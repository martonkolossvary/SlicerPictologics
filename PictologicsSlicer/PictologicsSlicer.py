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
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Iterable, Sequence

import qt
import slicer
import vtk
from PictologicsLib.dependencies import (
    activate_dependency_target,
    build_pip_install_args,
    dependency_environment_path,
    dependency_paths,
    inspect_target,
    parse_pictologics_requirement,
)
from PictologicsLib.inline_config import (
    build_inline_configuration_document,
    default_inline_state,
    lint_configuration_document,
    preset_configuration_document,
    preset_names,
)
from PictologicsLib.jobs import build_job_manifest, sha256_file, write_job_manifest
from PictologicsLib.results import (
    LONG_RESULT_COLUMNS,
    RESULT_PAYLOAD_SCHEMA_VERSION,
    export_rows,
    load_result_payload,
    rows_to_wide,
    validate_result_payload,
)
from PictologicsLib.staging import process_is_alive, read_pid_marker
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

PARAM_WHOLE_VOLUME = "WholeVolume"
PARAM_SELECTED_SEGMENTS = "SelectedSegments"
PARAM_STANDARD_CONFIGURATIONS = "StandardConfigurations"
PARAM_CUSTOM_CONFIGURATION = "CustomConfigurationPath"
PARAM_SUBJECT_ID = "SubjectID"
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


class PictologicsSlicer(ScriptedLoadableModule):
    """Module metadata shown by Slicer."""

    def __init__(self, parent):
        super().__init__(parent)
        self.parent.title = "Pictologics"
        self.parent.categories = ["Informatics"]
        self.parent.dependencies = ["Segmentations", "Tables"]
        self.parent.contributors = ["Pictologics contributors"]
        self.parent.helpText = (
            "Run Pictologics radiomics on a scalar volume, the whole volume, "
            "and/or independently selected segments. Computation runs in a "
            "cancellable background CLI process with isolated dependencies."
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
        self._activeJob: dict[str, Any] | None = None
        self._cliNode = None
        self._cliObserverTag = None
        self._finishingJob = False
        self._lastPayload: dict[str, Any] | None = None

    def setup(self):
        ScriptedLoadableModuleWidget.setup(self)

        uiWidget = slicer.util.loadUI(self.resourcePath("UI/PictologicsSlicer.ui"))
        self.layout.addWidget(uiWidget)
        self.ui = slicer.util.childWidgetVariables(uiWidget)
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
        self._populateStandardConfigurations()
        self._connectSignals()

        self.addObserver(
            slicer.mrmlScene, slicer.mrmlScene.StartCloseEvent, self.onSceneStartClose
        )
        self.addObserver(
            slicer.mrmlScene, slicer.mrmlScene.EndCloseEvent, self.onSceneEndClose
        )
        self.initializeParameterNode()
        self.refreshPackageStatus()

    def cleanup(self):
        self.setParameterNode(None)
        self._handoffActiveJobCleanup(cancel=True)
        self.removeObservers()

    def enter(self):
        self.initializeParameterNode()
        if self.logic is not None:
            try:
                self.logic.purgeStaleJobs()
            except Exception:
                LOGGER.exception(
                    "Could not purge stale Pictologics staging directories"
                )
        self.refreshPackageStatus()
        self._updateRunState()

    def exit(self):
        self.updateParameterNodeFromGUI()

    def _connectSignals(self):
        self.ui.inputVolumeSelector.connect(
            "currentNodeChanged(vtkMRMLNode*)", self.onControlsChanged
        )
        self.ui.segmentationSelector.connect(
            "currentNodeChanged(vtkMRMLNode*)", self.onSegmentationChanged
        )
        self.ui.outputTableSelector.connect(
            "currentNodeChanged(vtkMRMLNode*)", self.onControlsChanged
        )
        self.ui.wholeVolumeCheckBox.connect("toggled(bool)", self.onControlsChanged)
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
        for spin in (
            self.ui.resampleXSpinBox,
            self.ui.resampleYSpinBox,
            self.ui.resampleZSpinBox,
            self.ui.discretiseValueSpinBox,
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
        self.ui.runButton.connect("clicked()", self.onRun)
        self.ui.cancelButton.connect("clicked()", self.onCancel)
        self.ui.exportButton.connect("clicked()", self.onExport)

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
        if self._activeJob is not None:
            # A CLI result belongs to the scene in which it was submitted. Never
            # let a late completion write patient A's rows into a newly loaded scene.
            self._activeJob["discard_results"] = True
            if self._nodeIsBusy(self._cliNode):
                self._cliNode.Cancel()
        self.setParameterNode(None)

    def onSceneEndClose(self, caller=None, event=None):
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
        if self._parameterNode is None or not hasattr(self, "ui"):
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
            self.ui.customConfigPathLineEdit.setText(
                self._parameterNode.GetParameter(PARAM_CUSTOM_CONFIGURATION)
            )
            self.ui.subjectIdLineEdit.setText(
                self._parameterNode.GetParameter(PARAM_SUBJECT_ID)
            )

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
        self._updateRunState()

    def updateParameterNodeFromGUI(self):
        if self._parameterNode is None or self._updatingGUIFromParameterNode:
            return
        wasModified = self._parameterNode.StartModify()
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
                PARAM_CUSTOM_CONFIGURATION,
                str(self.ui.customConfigPathLineEdit.text).strip(),
            )
            self._parameterNode.SetParameter(
                PARAM_SUBJECT_ID, str(self.ui.subjectIdLineEdit.text).strip()
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
            self._parameterNode.EndModify(wasModified)

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
        }

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

    def _validationError(self) -> str | None:
        inputVolume = self.ui.inputVolumeSelector.currentNode()
        if inputVolume is None:
            return "Select an input scalar volume."
        if inputVolume.GetImageData() is None:
            return "The selected input volume has no image data."

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

        hasSegments = bool(self._selectedSegmentIDs())
        if not self.ui.wholeVolumeCheckBox.checked and not hasSegments:
            return "Analyze the whole volume or select at least one segment."
        if hasSegments and self.ui.segmentationSelector.currentNode() is None:
            return "Select a segmentation for the checked segments."
        return None

    def _updateRunState(self):
        if not hasattr(self, "ui"):
            return
        busy = self._nodeIsBusy(self._cliNode)
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
        ):
            control.setEnabled(not busy)
        self.ui.runButton.setEnabled(not busy and error is None)
        self.ui.cancelButton.setEnabled(busy)
        self.ui.updatePackageButton.setEnabled(not busy)
        tableNode = self.ui.outputTableSelector.currentNode()
        self.ui.exportButton.setEnabled(
            not busy
            and tableNode is not None
            and tableNode.GetTable() is not None
            and tableNode.GetTable().GetNumberOfRows() > 0
        )
        if not busy and error:
            self.ui.statusLabel.setText(error)

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
        try:
            document = self._parseConfigurationFile(path)
        except ValueError as exc:
            self.ui.statusLabel.setText(f"Configuration is not valid: {exc}")
            return
        if document is None:
            self.ui.statusLabel.setText(
                "Loaded a YAML file; structural pre-check needs PyYAML. The worker "
                "validates it authoritatively at run time."
            )
            return
        issues = lint_configuration_document(document)
        if issues:
            self.ui.statusLabel.setText(
                f"Configuration has {len(issues)} issue(s): " + "; ".join(issues[:5])
            )
        else:
            self.ui.statusLabel.setText(
                "Configuration passed the structural pre-check. The worker validates "
                "it authoritatively at run time."
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
        try:
            self.ui.statusLabel.setText(
                "Updating the isolated Pictologics environment…"
            )
            slicer.app.processEvents()
            self.logic.ensureDependencies(forceUpgrade=True)
            self.refreshPackageStatus()
            self.ui.statusLabel.setText("The adopted Pictologics release is installed.")
        except DependencyInstallDeclined:
            self.ui.statusLabel.setText(
                "Package update was cancelled; no files were changed."
            )
        except Exception as exc:
            LOGGER.exception("Pictologics dependency update failed")
            slicer.util.errorDisplay(
                str(exc), windowTitle="Pictologics package update failed"
            )
            self.ui.statusLabel.setText("Package update failed.")
        finally:
            self._updateRunState()

    def onRun(self):
        error = self._validationError()
        if error:
            slicer.util.errorDisplay(error, windowTitle="Pictologics")
            return
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
            self._cliNode = self.logic.startJob(self._activeJob)
            self._cliObserverTag = self._cliNode.AddObserver(
                vtk.vtkCommand.ModifiedEvent, self.onCliModified
            )
            self.ui.progressBar.setValue(0)
            self.ui.statusLabel.setText("Pictologics is running in the background…")
            self._updateRunState()
            # Handle a setup failure that completed between cli.run() and observer
            # registration; no later ModifiedEvent is guaranteed in that race.
            self.onCliModified(self._cliNode)
        except DependencyInstallDeclined:
            self.ui.statusLabel.setText(
                "Pictologics installation was cancelled; the run did not start."
            )
        except Exception as exc:
            LOGGER.exception("Could not start Pictologics")
            if self._activeJob:
                self.logic.cleanupJob(self._activeJob)
            self._activeJob = None
            self._detachCliObserver(removeNode=True)
            slicer.util.errorDisplay(
                str(exc), windowTitle="Could not start Pictologics"
            )
            self.ui.statusLabel.setText("The run did not start.")
        finally:
            self._updateRunState()

    def onCancel(self):
        if self._nodeIsBusy(self._cliNode):
            self._cliNode.Cancel()
            self.ui.statusLabel.setText("Cancelling Pictologics…")
            self.ui.cancelButton.setEnabled(False)

    def onCliModified(self, cliNode, event=None):
        if cliNode is not self._cliNode or self._finishingJob:
            return
        try:
            # cliNode.GetProgress() returns the worker's <filter-progress> value as a
            # fraction in [0, 1]; the QProgressBar range is 0-100.
            progress = int(round(float(cliNode.GetProgress()) * 100.0))
            self.ui.progressBar.setValue(max(0, min(100, progress)))
        except (TypeError, ValueError):
            pass

        if cliNode.IsBusy():
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
        try:
            if self._activeJob and self._activeJob.get("discard_results"):
                self.ui.statusLabel.setText(
                    "The scene changed while Pictologics was running; its results were discarded."
                )
                return
            if failed or cancelled:
                errorText = str(cliNode.GetErrorText() or "").strip()
                if cancelled:
                    self.ui.statusLabel.setText(
                        "Pictologics was cancelled; the output table was not changed."
                    )
                else:
                    message = (
                        errorText or f"Pictologics CLI ended with status: {statusText}"
                    )
                    LOGGER.error("Pictologics CLI failed: %s", message)
                    slicer.util.errorDisplay(message, windowTitle="Pictologics failed")
                    self.ui.statusLabel.setText(
                        "Pictologics failed; the output table was not changed."
                    )
            else:
                self._acceptCompletedJob()
        except Exception as exc:
            LOGGER.exception("Could not commit Pictologics results")
            slicer.util.errorDisplay(
                str(exc), windowTitle="Could not load Pictologics results"
            )
            self.ui.statusLabel.setText(
                "Results were not committed; the previous table is unchanged."
            )
        finally:
            if self._activeJob:
                self.logic.cleanupJob(self._activeJob)
            self._activeJob = None
            self._detachCliObserver(removeNode=True)
            self._finishingJob = False
            self._updateRunState()

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

        tableNode = self.logic.commitRows(
            tableNode,
            payload["rows"],
            append=bool(self._activeJob.get("append_results")),
            payload=payload,
            manifest=self._activeJob["manifest"],
        )
        self._lastPayload = payload
        self.ui.outputTableSelector.setCurrentNode(tableNode)
        self.updateParameterNodeFromGUI()
        self.ui.progressBar.setValue(100)
        errorCount = len(payload.get("errors", []))
        nonOkCount = len(payload["rows"]) - okCount
        if errorCount or nonOkCount:
            self.ui.statusLabel.setText(
                f"Completed with {errorCount} ROI error(s) and {nonOkCount} non-success "
                f"feature row(s): {len(payload['rows'])} rows committed to "
                f"{tableNode.GetName()}."
            )
        else:
            self.ui.statusLabel.setText(
                f"Completed: {len(payload['rows'])} feature rows committed to "
                f"{tableNode.GetName()}."
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

        job = self._activeJob
        node = self._cliNode
        if job is not None:
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
            self._finishingJob = False

    def onExport(self):
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
            rows = self.logic.rowsFromTable(tableNode)
            wide = bool(self.ui.exportWideCheckBox.checked)
            exportedPaths = self.logic.exportTable(tableNode, path, rows=rows, wide=wide)
            destinations = ", ".join(str(item) for item in exportedPaths)
            layout = "wide" if wide else "long"
            self.ui.statusLabel.setText(
                f"Exported {len(rows)} rows ({layout} layout) and provenance to "
                f"{destinations}."
            )
        except Exception as exc:
            LOGGER.exception("Pictologics export failed")
            slicer.util.errorDisplay(str(exc), windowTitle="Pictologics export failed")


class PictologicsSlicerLogic(ScriptedLoadableModuleLogic):
    """Dependency, data-conversion, CLI, and atomic table orchestration."""

    def setDefaultParameters(self, parameterNode):
        if not parameterNode.GetParameter(PARAM_WHOLE_VOLUME):
            parameterNode.SetParameter(PARAM_WHOLE_VOLUME, "true")
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

    def pictologicsRequirement(self):
        return parse_pictologics_requirement(self.requirementsPath())

    @staticmethod
    def cacheRoot() -> Path:
        return Path(str(slicer.app.cachePath)) / "SlicerPictologics"

    @classmethod
    def jobsRoot(cls) -> Path:
        # Job cleanup must remain available even if the independent dependency
        # environment pointer is damaged.
        return cls.cacheRoot() / "jobs"

    @classmethod
    def privatePaths(cls) -> dict[str, Path]:
        return dependency_paths(cls.cacheRoot())

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
        action = "update" if forceUpgrade or before.installed else "install"
        message = (
            f"Pictologics must be {action}d in an extension-private Python folder:\n\n"
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
            published = environmentBase.with_name(
                f"{environmentBase.name}-{uuid.uuid4().hex}"
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
        return after

    @staticmethod
    def dependencyProbePath() -> Path:
        return (
            Path(__file__).resolve().parent / "PictologicsLib" / "dependency_probe.py"
        )

    def probeDependencyEnvironment(
        self, target: Path, expectedVersion: str, *, warmup: bool
    ) -> None:
        """Validate a candidate in a fresh PythonSlicer interpreter."""

        pythonSlicer = shutil.which("PythonSlicer")
        if not pythonSlicer:
            raise RuntimeError(
                "PythonSlicer was not found; the private Pictologics environment "
                "cannot be validated safely."
            )
        command = [
            pythonSlicer,
            str(self.dependencyProbePath()),
            str(target),
            expectedVersion,
        ]
        if not warmup:
            command.append("--skip-warmup")
        process = slicer.util.launchConsoleProcess(
            command,
            useStartupEnvironment=False,
            updateEnvironment={
                "NUMBA_CACHE_DIR": str(self.privatePaths()["numba_cache"]),
                "PICTOLOGICS_DISABLE_WARMUP": "1",
                "PYTHONNOUSERSITE": "1",
            },
        )
        try:
            slicer.util.logProcessOutput(process)
        except Exception as exc:
            raise RuntimeError(
                "The newly installed private Pictologics environment failed its "
                "import/API/JIT probe; the previous environment remains active."
            ) from exc

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
    def startJob(job: dict[str, Any]):
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
        return slicer.cli.run(cliModule, None, parameters, wait_for_completion=False)

    @classmethod
    def cleanupJob(cls, job: dict[str, Any]):
        """Remove only a job directory owned by this extension cache."""

        workDir = Path(job.get("work_dir", "")).resolve(strict=False)
        jobsRoot = cls.jobsRoot().resolve(strict=False)
        if (
            workDir.parent == jobsRoot
            and workDir.name.startswith("job-")
            and workDir.is_dir()
            and not workDir.is_symlink()
        ):
            shutil.rmtree(workDir, ignore_errors=True)

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
            if existingNames != tuple(LONG_RESULT_COLUMNS):
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
            candidate.DeepCopy(existing)
        else:
            for columnName in LONG_RESULT_COLUMNS:
                column = (
                    vtk.vtkDoubleArray()
                    if columnName == "value"
                    else vtk.vtkStringArray()
                )
                column.SetName(columnName)
                candidate.AddColumn(column)

        for row in normalized["rows"]:
            for columnName in LONG_RESULT_COLUMNS:
                column = candidate.GetColumnByName(columnName)
                value = row[columnName]
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
                "vtkMRMLTableNode", "Pictologics Results"
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
        if names != tuple(LONG_RESULT_COLUMNS):
            raise ValueError(
                "The selected table is not a Pictologics long-form result table."
            )
        rows: list[dict[str, Any]] = []
        for rowIndex in range(table.GetNumberOfRows()):
            row: dict[str, Any] = {}
            for columnName in LONG_RESULT_COLUMNS:
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
        "family",
        "family_group",
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

        export_rows(exportedRows, path, wide=wide)
        exportedPaths = [path]
        provenancePath = path.with_name(f"{path.stem}.provenance.json")
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
            dictionaryPath = path.with_name(f"{path.stem}.dictionary.csv")
            self._atomicWriteCSV(
                dictionaryPath,
                dictionaryRows,
                self._dictionaryColumns(dictionaryRows),
            )
            exportedPaths.append(dictionaryPath)
        return exportedPaths

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
            selectionNode = slicer.app.applicationLogic().GetSelectionNode()
            selectionNode.SetReferenceActiveTableID(tableNode.GetID())
            slicer.app.applicationLogic().PropagateTableSelection()
            slicer.app.layoutManager().setLayout(
                slicer.vtkMRMLLayoutNode.SlicerLayoutFourUpTableView
            )
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
