"""Standalone statement-coverage tests for the Pictologics CLI worker.

This module is self-contained: run alone it brings ``PictologicsCLI.py`` to
100% statement coverage.  It reuses the loading pattern and fakes from
``test_worker.py`` but does not depend on that module.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import runpy
import sys
import tempfile
import types
import unittest
import warnings
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock


os.environ.setdefault("PICTOLOGICS_DISABLE_WARMUP", "1")
os.environ.setdefault("NUMBA_CACHE_DIR", tempfile.mkdtemp(prefix="numba-cache-cov-"))

CLI_DIR = Path(__file__).resolve().parents[1]
WORKER_PATH = CLI_DIR / "PictologicsCLI.py"

SPEC = importlib.util.spec_from_file_location("pictologics_cli_worker_cov", WORKER_PATH)
assert SPEC is not None and SPEC.loader is not None
worker = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = worker
SPEC.loader.exec_module(worker)


CATALOG_RECORD = {
    "config": "standard_fbn_32",
    "feature_key": "joint_entropy_TU9B",
    "feature_name": "joint_entropy",
    "ibsi_code": "TU9B",
    "family": "glcm",
    "preprocessing_sequence": "1:resample > 2:discretise",
}


class FakeCatalog:
    def __init__(self, records: list[dict[str, object]]) -> None:
        self.records = records

    def to_dict(self, orient: str = "records") -> list[dict[str, object]]:
        if orient != "records":
            raise ValueError(orient)
        return [dict(record) for record in self.records]


class FakePipeline:
    catalog_record = CATALOG_RECORD

    def __init__(self) -> None:
        self._log: list[dict[str, object]] = []
        self.run_calls: list[tuple[object, object, str, tuple[str, ...]]] = []

    def get_all_standard_config_names(self) -> list[str]:
        return ["standard_fbn_32"]

    def list_configs(self) -> list[str]:
        return ["standard_fbn_32"]

    def describe_features(self) -> FakeCatalog:
        return FakeCatalog([self.catalog_record])

    def to_dict(self, config_names: list[str]) -> dict[str, object]:
        return {"configs": list(config_names)}

    @classmethod
    def load_configs(cls, file_path, validate=False, load_standard=False):
        del load_standard
        text = Path(str(file_path)).read_text(encoding="utf-8")
        if validate and "trigger-warning" in text:
            warnings.warn("Config 'custom_a' bad param", UserWarning, stacklevel=2)
        return cls()

    def merge_configs(self, other, overwrite=False):
        del other, overwrite
        return self

    def clear_log(self) -> None:
        self._log.clear()

    def run(self, image, mask, *, subject_id, config_names):
        self.run_calls.append((image, mask, subject_id, tuple(config_names)))
        self._log = [
            {"config_name": "standard_fbn_32", "status": "completed", "detail": "ok"}
        ]
        return {"standard_fbn_32": {"joint_entropy_TU9B": 4.25}}


class FakePictologics:
    __version__ = "9.8.7"
    RadiomicsPipeline = FakePipeline
    load_calls: list[tuple[str, object | None]] = []

    @classmethod
    def load_image(cls, path, reference_image=None):
        cls.load_calls.append((path, reference_image))
        if Path(path).name == "bad-mask.nii.gz":
            raise ValueError("broken mask")
        return {"path": path, "reference": reference_image}


def pic(pipeline_cls):
    return types.SimpleNamespace(
        RadiomicsPipeline=pipeline_cls,
        __version__="9.8.7",
        load_image=FakePictologics.load_image,
    )


def make_payload(root, *, rois=None, custom_configuration_path=None, provenance=True):
    config_doc = {
        "standard_configurations": ["standard_fbn_32"],
        "custom_configuration_path": custom_configuration_path,
        "custom_configuration_sha256": (
            worker.file_sha256(root / custom_configuration_path)
            if custom_configuration_path is not None
            else None
        ),
        "warmup": False,
    }
    if rois is None:
        rois = [
            {
                "roi_id": "segment-1",
                "roi_name": "Tumor",
                "roi_source": "segmentation",
                "mask_path": str(root / "mask.nii.gz"),
                "metadata": {"segment_color": "#ff0000"},
            }
        ]
    output = {"results_path": str(root / "results.json")}
    if provenance:
        output["provenance_path"] = str(root / "provenance.json")
    return {
        "schema_version": 1,
        "run_id": "run-123",
        "timestamp": "2026-07-18T14:00:00Z",
        "subject_id": "subject-7",
        "subject_metadata": {"cohort": "test"},
        "image": {"path": str(root / "image.nii.gz"), "name": "image"},
        "rois": rois,
        "configuration_document": config_doc,
        "configuration_sha256": worker.configuration_sha256(config_doc),
        "output": output,
        "extension_version": "0.1.0",
        "pictologics_requirement": "pictologics==9.8.7",
        "metadata": {
            "numba_cache_path": str(root / "numba-cache"),
            "pictologics_version_at_submission": "9.8.7",
            "input_volume_node_id": "vtkMRMLScalarVolumeNode1",
        },
    }


def finalize(payload):
    payload["configuration_sha256"] = worker.configuration_sha256(
        payload["configuration_document"]
    )
    return payload


def make_manifest(
    root,
    *,
    standard=("standard_fbn_32",),
    custom_path=None,
    custom_hash=None,
    rois=None,
    requirement="pictologics==9.8.7",
    submitted="9.8.7",
    warmup=False,
    provenance=True,
):
    if rois is None:
        rois = (
            worker.ROIManifest(
                "segment-1", "Tumor", "segmentation", root / "mask.nii.gz", {"c": "#f"}
            ),
        )
    config_doc = {
        "standard_configurations": list(standard),
        "custom_configuration_path": (str(custom_path) if custom_path else None),
        "custom_configuration_sha256": custom_hash,
        "warmup": warmup,
    }
    metadata = {
        "numba_cache_path": str(root / "numba-cache"),
        "pictologics_version_at_submission": submitted,
    }
    return worker.JobManifest(
        schema_version=1,
        run_id="run-123",
        timestamp="2026-07-18T14:00:00Z",
        extension_version="0.1.0",
        subject_id="subject-7",
        image_name="image",
        image_path=root / "image.nii.gz",
        rois=tuple(rois),
        configuration_document=config_doc,
        configuration_sha256="0" * 64,
        standard_configurations=tuple(standard),
        custom_configuration_path=custom_path,
        custom_configuration_sha256=custom_hash,
        warmup=warmup,
        results_path=root / "results.json",
        provenance_path=(root / "provenance.json") if provenance else None,
        numba_cache_path=root / "numba-cache",
        pictologics_requirement=requirement,
        metadata=metadata,
        subject_metadata={"cohort": "t"},
    )


class ValidateManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "image.nii.gz").touch()
        (self.root / "mask.nii.gz").touch()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _err(self, payload, pattern):
        with self.assertRaisesRegex(worker.ManifestValidationError, pattern):
            worker.validate_manifest(payload, base_dir=self.root)

    def test_root_not_object(self):
        self._err([], "root must be a JSON object")

    def test_nonfinite_json(self):
        payload = make_payload(self.root)
        payload["subject_metadata"] = {"bad": float("nan")}
        self._err(payload, "finite JSON")

    def test_missing_and_unknown_keys(self):
        payload = make_payload(self.root)
        del payload["run_id"]
        payload["surprise"] = True
        self._err(payload, "missing keys: run_id; unknown keys: surprise")

    def test_schema_version(self):
        payload = make_payload(self.root)
        payload["schema_version"] = 2
        self._err(payload, "must be integer 1")

    def test_run_id_not_string(self):
        payload = make_payload(self.root)
        payload["run_id"] = 123
        self._err(payload, "'run_id' must be a string")

    def test_run_id_empty(self):
        payload = make_payload(self.root)
        payload["run_id"] = "   "
        self._err(payload, "'run_id' must not be empty")

    def test_timestamp_bad_iso(self):
        payload = make_payload(self.root)
        payload["timestamp"] = "not-a-date"
        self._err(payload, "ISO-8601")

    def test_timestamp_no_timezone(self):
        payload = make_payload(self.root)
        payload["timestamp"] = "2026-07-18"
        self._err(payload, "ISO-8601")

    def test_image_not_object(self):
        payload = make_payload(self.root)
        payload["image"] = []
        self._err(payload, "'image' must be an object")

    def test_image_bad_keys(self):
        payload = make_payload(self.root)
        payload["image"] = {"path": str(self.root / "image.nii.gz"), "extra": 1}
        self._err(payload, "invalid shape .*missing keys: name.*unknown keys: extra")

    def test_image_bad_suffix(self):
        payload = make_payload(self.root)
        payload["image"]["path"] = str(self.root / "image.txt")
        self._err(payload, "must point to a .nii")

    def test_image_missing_file(self):
        payload = make_payload(self.root)
        payload["image"]["path"] = str(self.root / "missing.nii.gz")
        self._err(payload, "does not exist")

    def test_image_is_directory(self):
        (self.root / "imgdir.nii.gz").mkdir()
        payload = make_payload(self.root)
        payload["image"]["path"] = str(self.root / "imgdir.nii.gz")
        self._err(payload, "must be a file")

    def test_rois_empty(self):
        payload = make_payload(self.root, rois=[])
        self._err(payload, "non-empty array")

    def test_roi_not_object(self):
        payload = make_payload(self.root, rois=[123])
        self._err(payload, r"rois\[0\]' must be an object")

    def test_roi_duplicate_id(self):
        roi = {
            "roi_id": "dup",
            "roi_name": "n",
            "roi_source": "whole-volume",
            "mask_path": None,
        }
        payload = make_payload(self.root, rois=[roi, dict(roi)])
        self._err(payload, "duplicate ROI id")

    def test_mask_null_non_whole(self):
        payload = make_payload(
            self.root,
            rois=[
                {
                    "roi_id": "a",
                    "roi_name": "n",
                    "roi_source": "segmentation",
                    "mask_path": None,
                }
            ],
        )
        self._err(payload, "may be null only")

    def test_mask_set_for_whole_volume(self):
        payload = make_payload(
            self.root,
            rois=[
                {
                    "roi_id": "a",
                    "roi_name": "n",
                    "roi_source": "whole-volume",
                    "mask_path": str(self.root / "mask.nii.gz"),
                }
            ],
        )
        self._err(payload, "must be null for whole volume")

    def test_mask_bad_suffix(self):
        payload = make_payload(
            self.root,
            rois=[
                {
                    "roi_id": "a",
                    "roi_name": "n",
                    "roi_source": "segmentation",
                    "mask_path": str(self.root / "mask.txt"),
                }
            ],
        )
        self._err(payload, "must point to a .nii")

    def test_mask_missing_file(self):
        payload = make_payload(
            self.root,
            rois=[
                {
                    "roi_id": "a",
                    "roi_name": "n",
                    "roi_source": "segmentation",
                    "mask_path": str(self.root / "missing.nii.gz"),
                }
            ],
        )
        self._err(payload, "does not exist")

    def test_roi_metadata_not_object(self):
        payload = make_payload(
            self.root,
            rois=[
                {
                    "roi_id": "a",
                    "roi_name": "n",
                    "roi_source": "whole-volume",
                    "mask_path": None,
                    "metadata": "nope",
                }
            ],
        )
        self._err(payload, "metadata' must be an object")

    def test_config_doc_not_object(self):
        payload = make_payload(self.root)
        payload["configuration_document"] = []
        self._err(payload, "'configuration_document' must be an object")

    def test_config_sha_bad_format(self):
        payload = make_payload(self.root)
        payload["configuration_sha256"] = "not-a-hash"
        self._err(payload, "lowercase SHA-256 digest")

    def test_config_sha_mismatch(self):
        payload = make_payload(self.root)
        payload["configuration_sha256"] = "0" * 64
        self._err(payload, "does not match configuration_document")

    def test_standard_configs_not_array(self):
        payload = make_payload(self.root)
        payload["configuration_document"]["standard_configurations"] = "nope"
        finalize(payload)
        self._err(payload, "must be an array")

    def test_standard_config_bad_name(self):
        payload = make_payload(self.root)
        payload["configuration_document"]["standard_configurations"] = ["weird"]
        finalize(payload)
        self._err(payload, "must name a standard_ configuration")

    def test_standard_config_duplicate(self):
        payload = make_payload(self.root)
        payload["configuration_document"]["standard_configurations"] = [
            "standard_a",
            "standard_a",
        ]
        finalize(payload)
        self._err(payload, "duplicate standard configuration")

    def test_custom_path_bad_suffix(self):
        payload = make_payload(self.root)
        payload["configuration_document"]["custom_configuration_path"] = "config.txt"
        finalize(payload)
        self._err(payload, "must point to JSON or YAML")

    def test_custom_path_missing_file(self):
        payload = make_payload(self.root)
        payload["configuration_document"]["custom_configuration_path"] = "config.json"
        finalize(payload)
        self._err(payload, "does not exist")

    def test_custom_sha_bad_format(self):
        (self.root / "cfg.json").write_text("{}", encoding="utf-8")
        payload = make_payload(self.root)
        payload["configuration_document"]["custom_configuration_path"] = "cfg.json"
        payload["configuration_document"]["custom_configuration_sha256"] = "xyz"
        finalize(payload)
        self._err(payload, "must be null or a lowercase SHA-256")

    def test_custom_sha_without_path(self):
        payload = make_payload(self.root)
        payload["configuration_document"]["custom_configuration_path"] = None
        payload["configuration_document"]["custom_configuration_sha256"] = "0" * 64
        finalize(payload)
        self._err(payload, "must be null when custom_configuration_path is null")

    def test_custom_sha_mismatch_file(self):
        (self.root / "cfg.json").write_text("content", encoding="utf-8")
        payload = make_payload(self.root)
        payload["configuration_document"]["custom_configuration_path"] = "cfg.json"
        payload["configuration_document"]["custom_configuration_sha256"] = "0" * 64
        finalize(payload)
        self._err(payload, "does not match\n?.*custom configuration file")

    def test_no_configuration_selected(self):
        payload = make_payload(self.root)
        payload["configuration_document"]["standard_configurations"] = []
        payload["configuration_document"]["custom_configuration_path"] = None
        payload["configuration_document"]["custom_configuration_sha256"] = None
        finalize(payload)
        self._err(payload, "must select a standard configuration or provide a custom")

    def test_warmup_not_bool(self):
        payload = make_payload(self.root)
        payload["configuration_document"]["warmup"] = "yes"
        finalize(payload)
        self._err(payload, "warmup' must be a boolean")

    def test_output_not_object(self):
        payload = make_payload(self.root)
        payload["output"] = []
        self._err(payload, "'output' must be an object")

    def test_results_path_bad_suffix(self):
        payload = make_payload(self.root)
        payload["output"]["results_path"] = str(self.root / "results.txt")
        self._err(payload, "must end in .json")

    def test_results_path_is_directory(self):
        (self.root / "resdir.json").mkdir()
        payload = make_payload(self.root)
        payload["output"]["results_path"] = str(self.root / "resdir.json")
        self._err(payload, "is a directory")

    def test_provenance_bad_suffix(self):
        payload = make_payload(self.root)
        payload["output"]["provenance_path"] = str(self.root / "prov.txt")
        self._err(payload, "provenance_path' must end in .json")

    def test_provenance_equals_results(self):
        payload = make_payload(self.root)
        payload["output"]["provenance_path"] = str(self.root / "results.json")
        self._err(payload, "must differ from output.results_path")

    def test_provenance_is_directory(self):
        (self.root / "provdir.json").mkdir()
        payload = make_payload(self.root)
        payload["output"]["provenance_path"] = str(self.root / "provdir.json")
        self._err(payload, "provenance_path' is a directory")

    def test_metadata_not_object(self):
        payload = make_payload(self.root)
        payload["metadata"] = []
        self._err(payload, "'metadata' must be an object")

    def test_metadata_submitted_version_bad(self):
        payload = make_payload(self.root)
        payload["metadata"]["pictologics_version_at_submission"] = 123
        self._err(payload, "pictologics_version_at_submission' must be a string or null")

    def test_metadata_node_id_bad(self):
        payload = make_payload(self.root)
        payload["metadata"]["input_volume_node_id"] = 123
        self._err(payload, "input_volume_node_id' must be a string")

    def test_numba_cache_not_directory(self):
        (self.root / "cachefile").write_text("x", encoding="utf-8")
        payload = make_payload(self.root)
        payload["metadata"]["numba_cache_path"] = str(self.root / "cachefile")
        self._err(payload, "exists but is not a directory")

    def test_subject_metadata_not_object(self):
        payload = make_payload(self.root)
        payload["subject_metadata"] = []
        self._err(payload, "'subject_metadata' must be an object")

    def test_valid_full_manifest(self):
        (self.root / "custom.yaml").write_text("configs: {}\n", encoding="utf-8")
        payload = make_payload(self.root, custom_configuration_path="custom.yaml")
        manifest = worker.validate_manifest(payload, base_dir=self.root)
        self.assertEqual(manifest.run_id, "run-123")
        self.assertEqual(
            manifest.custom_configuration_path,
            (self.root / "custom.yaml").resolve(),
        )
        self.assertEqual(manifest.provenance_path, (self.root / "provenance.json").resolve())
        self.assertEqual(manifest.rois[0].metadata["segment_color"], "#ff0000")
        self.assertEqual(manifest.subject_metadata, {"cohort": "test"})

    def test_valid_base_dir_none_and_no_provenance(self):
        payload = make_payload(
            self.root,
            provenance=False,
            rois=[
                {
                    "roi_id": "w",
                    "roi_name": "Whole",
                    "roi_source": "whole-volume",
                    "mask_path": None,
                }
            ],
        )
        payload["image"]["path"] = str(self.root / "image.nii.gz")
        manifest = worker.validate_manifest(payload, base_dir=None, check_paths=False)
        self.assertIsNone(manifest.provenance_path)
        self.assertIsNone(manifest.rois[0].mask_path)


class LoadManifestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "image.nii.gz").touch()
        (self.root / "mask.nii.gz").touch()

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing(self):
        with self.assertRaisesRegex(worker.ManifestValidationError, "does not exist"):
            worker.load_manifest(self.root / "nope.json")

    def test_not_a_file(self):
        (self.root / "dir.json").mkdir()
        with self.assertRaisesRegex(worker.ManifestValidationError, "must be a file"):
            worker.load_manifest(self.root / "dir.json")

    def test_bad_suffix(self):
        (self.root / "job.txt").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(worker.ManifestValidationError, "must end in .json"):
            worker.load_manifest(self.root / "job.txt")

    def test_invalid_json(self):
        path = self.root / "job.json"
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaisesRegex(worker.ManifestValidationError, "line 1"):
            worker.load_manifest(path)

    def test_non_utf8(self):
        path = self.root / "job.json"
        path.write_bytes(b"\xff\xfe\x00bad")
        with self.assertRaisesRegex(worker.ManifestValidationError, "must be UTF-8"):
            worker.load_manifest(path)

    def test_oserror_on_read(self):
        path = self.root / "job.json"
        path.write_text("{}", encoding="utf-8")
        with mock.patch.object(worker.Path, "open", side_effect=OSError("boom")):
            with self.assertRaisesRegex(
                worker.ManifestValidationError, "cannot read job manifest"
            ):
                worker.load_manifest(path)

    def test_success(self):
        path = self.root / "job.json"
        path.write_text(json.dumps(make_payload(self.root)), encoding="utf-8")
        manifest = worker.load_manifest(path)
        self.assertEqual(manifest.run_id, "run-123")


class IsolationTests(unittest.TestCase):
    def test_side_effect_free(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            isolated = worker.isolate_dependency_path(
                target,
                search_path=[
                    "/python/stdlib",
                    "/global/lib/python/site-packages",
                    "/debian/dist-packages",
                    str(target),
                    "a\x00b",
                    "",
                ],
            )
        self.assertEqual(
            isolated, [str(target.resolve()), "/python/stdlib", "a\x00b", ""]
        )

    def test_target_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                worker.DependencyIsolationError, "does not exist"
            ):
                worker.isolate_dependency_path(Path(directory) / "nope")

    def test_target_not_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "file"
            target.write_text("x", encoding="utf-8")
            with self.assertRaisesRegex(
                worker.DependencyIsolationError, "not a directory"
            ):
                worker.isolate_dependency_path(target)

    def test_mutates_sys_path(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            saved = list(sys.path)
            try:
                result = worker.isolate_dependency_path(target)
                self.assertEqual(result[0], str(target.resolve()))
                self.assertEqual(sys.path[0], str(target.resolve()))
            finally:
                sys.path[:] = saved

    def test_is_site_package_empty(self):
        self.assertFalse(worker._is_site_package_entry(""))

    def test_is_site_package_true(self):
        self.assertTrue(worker._is_site_package_entry("/x/site-packages/y"))

    def test_is_site_package_exception(self):
        with mock.patch.object(worker, "Path", side_effect=TypeError("boom")):
            self.assertFalse(worker._is_site_package_entry("something"))

    def test_configure_environment_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = make_manifest(root)
            with mock.patch.dict(os.environ, {}, clear=True):
                worker.configure_environment(manifest)
                self.assertEqual(os.environ["PICTOLOGICS_DISABLE_WARMUP"], "1")
                self.assertEqual(
                    os.environ["NUMBA_CACHE_DIR"], str(root / "numba-cache")
                )
                self.assertTrue((root / "numba-cache").is_dir())

    def test_configure_environment_mkdir_error(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = make_manifest(Path(directory))
            with mock.patch.object(worker.Path, "mkdir", side_effect=OSError("boom")):
                with self.assertRaisesRegex(
                    worker.WorkerSetupError, "cannot create Numba cache directory"
                ):
                    worker.configure_environment(manifest)


class ImportPrivateTests(unittest.TestCase):
    def _target_with_pkg(self, directory):
        target = Path(directory)
        init = target / "pictologics" / "__init__.py"
        init.parent.mkdir(parents=True, exist_ok=True)
        init.write_text("", encoding="utf-8")
        return target, init

    def test_import_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(
                worker.importlib, "import_module", side_effect=ImportError("nope")
            ):
                with self.assertRaisesRegex(
                    worker.WorkerSetupError, "cannot import Pictologics"
                ):
                    worker.import_private_pictologics(Path(directory), warmup=False)

    def test_no_filesystem_origin(self):
        with tempfile.TemporaryDirectory() as directory:
            module = types.SimpleNamespace(__file__=None)
            with mock.patch.object(
                worker.importlib, "import_module", return_value=module
            ):
                with self.assertRaisesRegex(
                    worker.DependencyIsolationError, "no filesystem origin"
                ):
                    worker.import_private_pictologics(Path(directory), warmup=False)

    def test_origin_outside_target(self):
        with tempfile.TemporaryDirectory() as directory:
            target, _ = self._target_with_pkg(directory)
            module = types.SimpleNamespace(
                __file__="/elsewhere/pictologics/__init__.py"
            )
            with mock.patch.object(
                worker.importlib, "import_module", return_value=module
            ):
                with self.assertRaisesRegex(
                    worker.DependencyIsolationError, "outside the private"
                ):
                    worker.import_private_pictologics(target, warmup=False)

    def test_no_warmup_returns_module(self):
        with tempfile.TemporaryDirectory() as directory:
            target, init = self._target_with_pkg(directory)
            module = types.SimpleNamespace(__file__=str(init))
            with mock.patch.object(
                worker.importlib, "import_module", return_value=module
            ):
                result = worker.import_private_pictologics(target, warmup=False)
            self.assertIs(result, module)

    def test_warmup_not_callable(self):
        with tempfile.TemporaryDirectory() as directory:
            target, init = self._target_with_pkg(directory)
            module = types.SimpleNamespace(__file__=str(init))
            with mock.patch.object(
                worker.importlib, "import_module", return_value=module
            ):
                with self.assertRaisesRegex(
                    worker.WorkerSetupError, "does not expose warmup_jit"
                ):
                    worker.import_private_pictologics(target, warmup=True)

    def test_warmup_success(self):
        with tempfile.TemporaryDirectory() as directory:
            target, init = self._target_with_pkg(directory)
            warmup = mock.Mock()
            module = types.SimpleNamespace(__file__=str(init), warmup_jit=warmup)
            with mock.patch.object(
                worker.importlib, "import_module", return_value=module
            ):
                with mock.patch.dict(
                    os.environ, {"PICTOLOGICS_DISABLE_WARMUP": "1"}, clear=False
                ):
                    result = worker.import_private_pictologics(target, warmup=True)
                    self.assertIs(result, module)
                    self.assertEqual(os.environ["PICTOLOGICS_DISABLE_WARMUP"], "0")
            warmup.assert_called_once_with()

    def test_warmup_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            target, init = self._target_with_pkg(directory)
            warmup = mock.Mock(side_effect=RuntimeError("boom"))
            module = types.SimpleNamespace(__file__=str(init), warmup_jit=warmup)
            with mock.patch.object(
                worker.importlib, "import_module", return_value=module
            ):
                with mock.patch.dict(os.environ, {}, clear=False):
                    with self.assertRaisesRegex(
                        worker.WorkerSetupError, "JIT warmup failed"
                    ):
                        worker.import_private_pictologics(target, warmup=True)


class VerifyVersionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_exact_requirement(self):
        manifest = make_manifest(self.root, requirement="not-a-req")
        with self.assertRaisesRegex(
            worker.WorkerSetupError, "does not contain an exact"
        ):
            worker.verify_runtime_version(
                manifest, types.SimpleNamespace(__version__="9.8.7")
            )

    def test_submitted_mismatch(self):
        manifest = make_manifest(
            self.root, requirement="pictologics==1.2.3", submitted="9.9.9"
        )
        with self.assertRaisesRegex(
            worker.WorkerSetupError, "submitted Pictologics version does not match"
        ):
            worker.verify_runtime_version(
                manifest, types.SimpleNamespace(__version__="1.2.3")
            )

    def test_imported_mismatch(self):
        manifest = make_manifest(
            self.root, requirement="pictologics==1.2.3", submitted="1.2.3"
        )
        with self.assertRaisesRegex(
            worker.WorkerSetupError, "changed after submission"
        ):
            worker.verify_runtime_version(
                manifest, types.SimpleNamespace(__version__="1.2.4")
            )

    def test_success(self):
        manifest = make_manifest(
            self.root, requirement="pictologics==1.2.3", submitted="1.2.3"
        )
        self.assertEqual(
            worker.verify_runtime_version(
                manifest, types.SimpleNamespace(__version__="1.2.3")
            ),
            "1.2.3",
        )


class CatalogTests(unittest.TestCase):
    def test_pictologics_identity_is_added_to_catalog(self):
        feature_key = "volume_at_intensity_fraction_0.10_BC2M_10"
        records = worker._catalog_to_records(
            [
                {
                    "config": "standard_fbn_32",
                    "feature_key": feature_key,
                    "feature_name": "volume_at_intensity_fraction_0.10",
                    "ibsi_code": "BC2M",
                }
            ]
        )
        self.assertEqual(records[0]["pictologics_ibsi_code"], "BC2M_10")
        self.assertEqual(
            records[0]["pictologics_feature_name"],
            f"standard_fbn_32__{feature_key}",
        )

    def test_non_string_optional_identity_metadata_falls_back(self):
        records = worker._catalog_to_records(
            [
                {
                    "config": "c",
                    "feature_key": "custom_feature",
                    "feature_name": None,
                    "ibsi_code": None,
                }
            ]
        )
        self.assertEqual(records[0]["pictologics_ibsi_code"], "")
        self.assertEqual(
            records[0]["pictologics_feature_name"], "c__custom_feature"
        )

    def test_list_input(self):
        records = worker._catalog_to_records(
            [{"config": "c", "feature_key": "k", "extra": 1}]
        )
        self.assertEqual(records[0]["config"], "c")

    def test_to_dict_records(self):
        records = worker._catalog_to_records(
            FakeCatalog([{"config": "c", "feature_key": "k"}])
        )
        self.assertEqual(records[0]["feature_key"], "k")

    def test_to_dict_typeerror_fallback(self):
        class PosCatalog:
            def to_dict(self, mode):
                assert mode == "records"
                return [{"config": "c", "feature_key": "k"}]

        records = worker._catalog_to_records(PosCatalog())
        self.assertEqual(records[0]["config"], "c")

    def test_not_tabular(self):
        with self.assertRaisesRegex(
            worker.WorkerSetupError, "did not return a tabular catalog"
        ):
            worker._catalog_to_records(5)

    def test_records_not_list(self):
        class DictCatalog:
            def to_dict(self, orient="records"):
                return {"not": "list"}

        with self.assertRaisesRegex(
            worker.WorkerSetupError, "could not be converted to records"
        ):
            worker._catalog_to_records(DictCatalog())

    def test_row_not_mapping(self):
        with self.assertRaisesRegex(
            worker.WorkerSetupError, "row 0 is not an object"
        ):
            worker._catalog_to_records([1])

    def test_row_missing_string_keys(self):
        with self.assertRaisesRegex(
            worker.WorkerSetupError, "lacks string 'config' or 'feature_key'"
        ):
            worker._catalog_to_records([{"config": "c"}])


class CreatePipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_standard_success(self):
        manifest = make_manifest(self.root)
        bundle = worker.create_pipeline(FakePictologics, manifest)
        self.assertEqual(bundle.selected_configurations, ("standard_fbn_32",))
        self.assertEqual(len(bundle.catalog_records), 1)
        self.assertEqual(bundle.configuration_document, {"configs": ["standard_fbn_32"]})

    def test_pipeline_init_error(self):
        class InitError(FakePipeline):
            def __init__(self):
                raise RuntimeError("init boom")

        manifest = make_manifest(self.root)
        with self.assertRaisesRegex(worker.WorkerSetupError, "cannot initialize"):
            worker.create_pipeline(pic(InitError), manifest)

    def test_enumerate_error(self):
        class EnumError(FakePipeline):
            def get_all_standard_config_names(self):
                raise RuntimeError("enum boom")

        manifest = make_manifest(self.root)
        with self.assertRaisesRegex(
            worker.WorkerSetupError, "cannot enumerate standard configurations"
        ):
            worker.create_pipeline(pic(EnumError), manifest)

    def test_missing_standard(self):
        manifest = make_manifest(self.root, standard=("standard_missing",))
        with self.assertRaisesRegex(worker.WorkerSetupError, "are unavailable"):
            worker.create_pipeline(FakePictologics, manifest)

    def test_no_configs_selected(self):
        manifest = make_manifest(self.root, standard=(), custom_path=None)
        with self.assertRaisesRegex(
            worker.WorkerSetupError, "no configurations were selected"
        ):
            worker.create_pipeline(FakePictologics, manifest)

    def test_describe_reraises_cli_error(self):
        class DescribeBad(FakePipeline):
            def describe_features(self):
                return 5

        manifest = make_manifest(self.root)
        with self.assertRaisesRegex(
            worker.WorkerSetupError, "did not return a tabular catalog"
        ):
            worker.create_pipeline(pic(DescribeBad), manifest)

    def test_describe_generic_error(self):
        class DescribeError(FakePipeline):
            def describe_features(self):
                raise ValueError("desc boom")

        manifest = make_manifest(self.root)
        with self.assertRaisesRegex(
            worker.WorkerSetupError, "cannot describe configured features"
        ):
            worker.create_pipeline(pic(DescribeError), manifest)

    def test_empty_configs(self):
        class EmptyConfigs(FakePipeline):
            def describe_features(self):
                return FakeCatalog(
                    [
                        {
                            "config": "OTHER",
                            "feature_key": "k",
                            "feature_name": "n",
                            "ibsi_code": "",
                            "family": "f",
                        }
                    ]
                )

        manifest = make_manifest(self.root)
        with self.assertRaisesRegex(
            worker.WorkerSetupError, "describe no features"
        ):
            worker.create_pipeline(pic(EmptyConfigs), manifest)

    def test_to_dict_error(self):
        class ToDictError(FakePipeline):
            def to_dict(self, config_names):
                raise RuntimeError("todict boom")

        manifest = make_manifest(self.root)
        with self.assertRaisesRegex(
            worker.WorkerSetupError, "cannot serialize effective configurations"
        ):
            worker.create_pipeline(pic(ToDictError), manifest)

    def test_custom_success(self):
        class CustomPipeline(FakePipeline):
            @classmethod
            def load_configs(cls, file_path, validate=False, load_standard=False):
                inst = cls()
                inst._custom = True
                return inst

            def list_configs(self):
                if getattr(self, "_custom", False):
                    return ["custom_a"]
                return ["standard_fbn_32"]

            def describe_features(self):
                return FakeCatalog(
                    [
                        CATALOG_RECORD,
                        {
                            "config": "custom_a",
                            "feature_key": "foo_AB12",
                            "feature_name": "foo",
                            "ibsi_code": "AB12",
                            "family": "custom",
                        },
                    ]
                )

        manifest = make_manifest(self.root, custom_path=self.root / "custom.yaml")
        bundle = worker.create_pipeline(pic(CustomPipeline), manifest)
        self.assertEqual(
            bundle.selected_configurations, ("standard_fbn_32", "custom_a")
        )

    def test_custom_load_error(self):
        class LoadError(FakePipeline):
            @classmethod
            def load_configs(cls, file_path, validate=False, load_standard=False):
                raise RuntimeError("load boom")

        manifest = make_manifest(self.root, custom_path=self.root / "custom.yaml")
        with self.assertRaisesRegex(
            worker.WorkerSetupError, "cannot load custom configuration"
        ):
            worker.create_pipeline(pic(LoadError), manifest)

    def test_custom_validation_warning(self):
        custom = self.root / "custom.yaml"
        custom.write_text("# trigger-warning\n", encoding="utf-8")
        manifest = make_manifest(self.root, custom_path=custom)
        with self.assertRaisesRegex(worker.WorkerSetupError, "failed validation"):
            worker.create_pipeline(FakePictologics, manifest)

    def test_custom_empty_names(self):
        class EmptyCustom(FakePipeline):
            @classmethod
            def load_configs(cls, file_path, validate=False, load_standard=False):
                inst = cls()
                inst._empty = True
                return inst

            def list_configs(self):
                return [] if getattr(self, "_empty", False) else ["standard_fbn_32"]

        manifest = make_manifest(self.root, custom_path=self.root / "custom.yaml")
        with self.assertRaisesRegex(
            worker.WorkerSetupError, "contains no configurations"
        ):
            worker.create_pipeline(pic(EmptyCustom), manifest)

    def test_custom_collision(self):
        custom = self.root / "custom.yaml"
        custom.write_text("configs: {}\n", encoding="utf-8")
        manifest = make_manifest(self.root, custom_path=custom)
        with self.assertRaisesRegex(worker.WorkerSetupError, "collide"):
            worker.create_pipeline(FakePictologics, manifest)

    def test_custom_duplicate_names(self):
        class DupCustom(FakePipeline):
            @classmethod
            def load_configs(cls, file_path, validate=False, load_standard=False):
                inst = cls()
                inst._dup = True
                return inst

            def list_configs(self):
                if getattr(self, "_dup", False):
                    return ["custom_a", "custom_a"]
                return ["standard_fbn_32"]

        manifest = make_manifest(self.root, custom_path=self.root / "custom.yaml")
        with self.assertRaisesRegex(
            worker.WorkerSetupError, "duplicate names"
        ):
            worker.create_pipeline(pic(DupCustom), manifest)

    def test_custom_merge_error(self):
        class MergeError(FakePipeline):
            @classmethod
            def load_configs(cls, file_path, validate=False, load_standard=False):
                inst = cls()
                inst._custom = True
                return inst

            def list_configs(self):
                return ["custom_a"] if getattr(self, "_custom", False) else ["standard_fbn_32"]

            def merge_configs(self, other, overwrite=False):
                raise RuntimeError("merge boom")

        manifest = make_manifest(self.root, custom_path=self.root / "custom.yaml")
        with self.assertRaisesRegex(
            worker.WorkerSetupError, "cannot register custom configurations"
        ):
            worker.create_pipeline(pic(MergeError), manifest)


class ExecuteJobTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "image.nii.gz").touch()
        (self.root / "mask.nii.gz").touch()
        (self.root / "bad-mask.nii.gz").touch()
        FakePictologics.load_calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def _manifest(self, rois):
        payload = make_payload(self.root, rois=rois)
        return worker.validate_manifest(payload, base_dir=self.root)

    def test_success_and_nonfatal_failure(self):
        manifest = self._manifest(
            [
                {
                    "roi_id": "whole",
                    "roi_name": "Whole",
                    "roi_source": "whole-volume",
                    "mask_path": None,
                },
                {
                    "roi_id": "seg",
                    "roi_name": "Seg",
                    "roi_source": "segmentation",
                    "mask_path": str(self.root / "bad-mask.nii.gz"),
                    "metadata": {"c": "#f00"},
                },
            ]
        )
        stream = io.StringIO()
        payload = worker.execute_job(
            manifest,
            FakePictologics,
            self.root / "private",
            progress=worker.ProgressReporter(stream),
        )
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(len(payload["rows"]), 2)
        first, second = payload["rows"]
        self.assertEqual(tuple(first), worker.LONG_ROW_COLUMNS)
        self.assertEqual(first["status"], "ok")
        self.assertEqual(first["value"], 4.25)
        self.assertEqual(first["feature_key"], "joint_entropy_TU9B")
        self.assertEqual(first["pictologics_ibsi_code"], "TU9B")
        self.assertEqual(
            first["pictologics_feature_name"],
            "standard_fbn_32__joint_entropy_TU9B",
        )
        self.assertEqual(
            first["preprocessing_sequence"], "1:resample > 2:discretise"
        )
        self.assertIsNone(second["value"])
        self.assertEqual(second["status"], "error")
        self.assertEqual(len(payload["errors"]), 1)
        self.assertIn("broken mask", payload["errors"][0]["error"])
        self.assertIn("<filter-progress>0.500000</filter-progress>", stream.getvalue())
        self.assertIn("<filter-progress>1.000000</filter-progress>", stream.getvalue())

    def test_run_returns_non_mapping(self):
        class NonMapping(FakePipeline):
            def run(self, image, mask, *, subject_id, config_names):
                return ["not-a-mapping"]

        manifest = self._manifest(
            [
                {
                    "roi_id": "whole",
                    "roi_name": "Whole",
                    "roi_source": "whole-volume",
                    "mask_path": None,
                }
            ]
        )
        payload = worker.execute_job(manifest, pic(NonMapping), self.root / "private")
        self.assertEqual(len(payload["errors"]), 1)
        self.assertIn("configuration mapping", payload["errors"][0]["error"])

    def test_image_load_fatal(self):
        class FailImage:
            RadiomicsPipeline = FakePipeline
            __version__ = "9.8.7"

            @staticmethod
            def load_image(path, reference_image=None):
                raise RuntimeError("image boom")

        manifest = self._manifest(
            [
                {
                    "roi_id": "whole",
                    "roi_name": "Whole",
                    "roi_source": "whole-volume",
                    "mask_path": None,
                }
            ]
        )
        with self.assertRaisesRegex(
            worker.JobExecutionError, "cannot load NIfTI image"
        ):
            worker.execute_job(manifest, FailImage, self.root / "private")


class BuildLongRowsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        rec1 = dict(CATALOG_RECORD)
        rec2 = {
            "config": "standard_two",
            "feature_key": "other_XY12",
            "feature_name": "other",
            "ibsi_code": "XY12",
            "family": "stat",
        }
        self.bundle = worker.PipelineBundle(
            pipeline=None,
            selected_configurations=("standard_fbn_32", "standard_two"),
            catalog_records=(rec1, rec2),
            catalog_by_config={
                "standard_fbn_32": (rec1,),
                "standard_two": (rec2,),
            },
            configuration_document={},
        )
        self.manifest = make_manifest(self.root)
        self.roi = self.manifest.rois[0]
        self.results = {
            "standard_fbn_32": {
                "joint_entropy_TU9B": 4.25,
                "extra_ZZ99": 1.0,
                "plainname": 2.0,
            }
        }
        self.log = [{"config_name": "standard_fbn_32", "status": "completed"}]

    def tearDown(self):
        self.tmp.cleanup()

    def test_fallback_and_absent_config(self):
        rows = worker.build_long_rows(
            self.manifest,
            self.roi,
            self.bundle,
            self.results,
            self.log,
            pictologics_version="9.8.7",
        )
        by_name = {(r["configuration"], r["feature_name"]): r for r in rows}
        self.assertEqual(by_name[("standard_fbn_32", "joint_entropy")]["status"], "ok")
        extra = by_name[("standard_fbn_32", "extra")]
        self.assertEqual(extra["ibsi_code"], "ZZ99")
        self.assertEqual(extra["pictologics_ibsi_code"], "ZZ99")
        self.assertEqual(
            extra["pictologics_feature_name"], "standard_fbn_32__extra_ZZ99"
        )
        self.assertEqual(extra["preprocessing_sequence"], "")
        self.assertEqual(extra["feature_family"], "unknown")
        plain = by_name[("standard_fbn_32", "plainname")]
        self.assertEqual(plain["ibsi_code"], "")
        self.assertEqual(plain["pictologics_ibsi_code"], "")
        absent = by_name[("standard_two", "other")]
        self.assertEqual(absent["status"], "error")
        self.assertIsNone(absent["value"])

    def test_column_order_assertion(self):
        with mock.patch.object(worker, "LONG_ROW_COLUMNS", ("wrong",)):
            with self.assertRaises(AssertionError):
                worker.build_long_rows(
                    self.manifest,
                    self.roi,
                    self.bundle,
                    self.results,
                    self.log,
                    pictologics_version="9.8.7",
                )


class SmallFunctionTests(unittest.TestCase):
    def test_utc_now(self):
        self.assertIn("T", worker._utc_now())

    def test_configuration_sha256_error(self):
        with self.assertRaisesRegex(
            worker.ManifestValidationError, "not canonical JSON"
        ):
            worker.configuration_sha256({"bad": {1, 2, 3}})

    def test_file_sha256_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                worker.ManifestValidationError, "cannot hash custom configuration"
            ):
                worker.file_sha256(Path(directory) / "nope.bin")

    def test_copy_processing_log_getter(self):
        class LogPipe:
            def get_processing_log(self):
                return [{"a": 1}]

        self.assertEqual(worker._copy_processing_log(LogPipe()), [{"a": 1}])

    def test_copy_processing_log_none(self):
        class NonePipe:
            def get_processing_log(self):
                return None

        self.assertEqual(worker._copy_processing_log(NonePipe()), [])

    def test_copy_processing_log_not_list(self):
        class BadPipe:
            def get_processing_log(self):
                return "not-a-list"

        with self.assertRaisesRegex(
            worker.JobExecutionError, "processing log is not a list"
        ):
            worker._copy_processing_log(BadPipe())

    def test_copy_processing_log_fallback_attr(self):
        class AttrPipe:
            _log = [{"b": 2}]

        self.assertEqual(worker._copy_processing_log(AttrPipe()), [{"b": 2}])

    def test_processing_statuses(self):
        entries = [
            {"config_name": "a", "status": "ok"},
            {"config_name": 1, "status": "x"},
            {"nope": True},
        ]
        self.assertEqual(worker._processing_statuses(entries), {"a": "ok"})

    def test_series_to_mapping(self):
        self.assertEqual(worker._series_to_mapping(None), {})
        self.assertEqual(worker._series_to_mapping({"a": 1}), {"a": 1})

        class ItemsObj:
            def items(self):
                return [("a", 1)]

        self.assertEqual(worker._series_to_mapping(ItemsObj()), {"a": 1})
        with self.assertRaisesRegex(
            worker.JobExecutionError, "unsupported feature result type"
        ):
            worker._series_to_mapping(5)

    def test_feature_value(self):
        self.assertIsNone(worker._feature_value(None))
        self.assertEqual(worker._feature_value(4.25), 4.25)
        self.assertIsNone(worker._feature_value(float("nan")))
        self.assertIsNone(worker._feature_value("not-a-number"))

        class NpLike:
            def item(self):
                return 7

        self.assertEqual(worker._feature_value(NpLike()), 7.0)

        class BadItem:
            def item(self):
                raise TypeError("no")

        self.assertIsNone(worker._feature_value(BadItem()))

    def test_fallback_feature_identity(self):
        self.assertEqual(
            worker._fallback_feature_identity("joint_entropy_TU9B"),
            ("joint_entropy", "TU9B", "TU9B"),
        )
        self.assertEqual(
            worker._fallback_feature_identity(
                "volume_at_intensity_fraction_0.10_BC2M_10"
            ),
            ("volume_at_intensity_fraction_0.10", "BC2M", "BC2M_10"),
        )
        self.assertEqual(
            worker._fallback_feature_identity("x_ABC"), ("x", "ABC", "ABC")
        )
        self.assertEqual(
            worker._fallback_feature_identity("plain"), ("plain", "", "")
        )
        self.assertEqual(
            worker._fallback_feature_identity("a_bc"), ("a_bc", "", "")
        )

    def test_pictologics_identity_helpers_fall_back_cleanly(self):
        self.assertEqual(
            worker._pictologics_ibsi_code("custom_feature", "custom_feature", ""),
            "",
        )
        self.assertEqual(
            worker._pictologics_ibsi_code("name_", "name", "AB12"), "AB12"
        )
        self.assertEqual(
            worker._pictologics_feature_name("config", "mean_Q4LE"),
            "config__mean_Q4LE",
        )

    def test_row_status(self):
        self.assertEqual(worker._row_status("completed", present=True, value=1.0), "ok")
        self.assertEqual(
            worker._row_status("ok", present=False, value=None), "not_computed"
        )
        self.assertEqual(
            worker._row_status("completed", present=True, value=None), "not_computed"
        )
        self.assertEqual(worker._row_status("failed", present=True, value=1.0), "failed")
        self.assertEqual(worker._row_status("", present=True, value=1.0), "error")

    def test_progress_reporter_default_stream(self):
        reporter = worker.ProgressReporter()
        self.assertIs(reporter.stream, sys.stdout)

    def test_json_safe_scalars(self):
        self.assertIsNone(worker._json_safe(None))
        self.assertEqual(worker._json_safe("s"), "s")
        self.assertEqual(worker._json_safe(True), True)
        self.assertEqual(worker._json_safe(5), 5)
        self.assertEqual(worker._json_safe(1.5), 1.5)
        self.assertIsNone(worker._json_safe(float("inf")))

    def test_json_safe_path_and_datetime(self):
        self.assertEqual(worker._json_safe(Path("/a/b")), str(Path("/a/b")))
        dt = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
        self.assertEqual(worker._json_safe(dt), dt.isoformat())

    def test_json_safe_containers(self):
        self.assertEqual(worker._json_safe({1: "x", "y": 2}), {"1": "x", "y": 2})
        self.assertEqual(worker._json_safe([1, "a"]), [1, "a"])
        self.assertEqual(worker._json_safe((1, 2)), [1, 2])
        self.assertEqual(sorted(worker._json_safe({1, 2, 3})), [1, 2, 3])

    def test_json_safe_dataclass(self):
        roi = worker.ROIManifest(
            "r", "n", "segmentation", Path("/m.nii.gz"), {"k": 1}
        )
        result = worker._json_safe(roi)
        self.assertEqual(result["mask_path"], str(Path("/m.nii.gz")))
        self.assertEqual(result["metadata"], {"k": 1})

    def test_json_safe_item_and_fallback(self):
        class NpLike:
            def item(self):
                return 3

        self.assertEqual(worker._json_safe(NpLike()), 3)

        class BadItem:
            def item(self):
                raise ValueError("no")

        self.assertIsInstance(worker._json_safe(BadItem()), str)
        self.assertIsInstance(worker._json_safe(object()), str)

    def test_fsync_parent_dir_open_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(worker.os, "open", side_effect=OSError("boom")):
                self.assertIsNone(
                    worker._fsync_parent_dir(Path(directory) / "file")
                )

    def test_fsync_parent_dir_fsync_error(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(worker.os, "fsync", side_effect=OSError("boom")):
                self.assertIsNone(
                    worker._fsync_parent_dir(Path(directory) / "file")
                )


class AtomicWriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_success(self):
        output = self.root / "out.json"
        worker.atomic_write_json(
            output, {"finite": 1.0, "nan": float("nan"), "inf": float("inf")}
        )
        self.assertEqual(
            json.loads(output.read_text(encoding="utf-8")),
            {"finite": 1.0, "nan": None, "inf": None},
        )
        self.assertEqual(list(self.root.glob(".out.json.*.tmp")), [])

    def test_bad_suffix(self):
        with self.assertRaisesRegex(
            worker.PictologicsCLIError, "must end in .json"
        ):
            worker.atomic_write_json(self.root / "out.txt", {})

    def test_directory_target(self):
        (self.root / "out.json").mkdir()
        with self.assertRaisesRegex(worker.PictologicsCLIError, "is a directory"):
            worker.atomic_write_json(self.root / "out.json", {})

    def test_mkdir_error(self):
        with mock.patch.object(worker.Path, "mkdir", side_effect=OSError("boom")):
            with self.assertRaisesRegex(
                worker.PictologicsCLIError, "cannot create output directory"
            ):
                worker.atomic_write_json(self.root / "out.json", {})

    def test_fdopen_error_closes_fd(self):
        with mock.patch.object(worker.os, "fdopen", side_effect=OSError("boom")):
            with self.assertRaisesRegex(
                worker.PictologicsCLIError, "cannot atomically write JSON"
            ):
                worker.atomic_write_json(self.root / "out.json", {"a": 1})
        self.assertEqual(list(self.root.glob(".out.json.*.tmp")), [])

    def test_replace_error_and_unlink_missing(self):
        with mock.patch.object(worker.os, "replace", side_effect=OSError("boom")):
            with mock.patch.object(
                worker.os, "unlink", side_effect=FileNotFoundError("gone")
            ):
                with self.assertRaisesRegex(
                    worker.PictologicsCLIError, "cannot atomically write JSON"
                ):
                    worker.atomic_write_json(self.root / "out.json", {"a": 1})


class RunCliTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "image.nii.gz").touch()
        (self.root / "mask.nii.gz").touch()
        self.manifest_path = self.root / "job.json"
        self.manifest_path.write_text(
            json.dumps(make_payload(self.root)), encoding="utf-8"
        )

    def tearDown(self):
        self.tmp.cleanup()

    def _args(self, output=None):
        return types.SimpleNamespace(
            jobManifest=str(self.manifest_path),
            dependencyPath=str(self.root / "dep"),
            outputResults=str(output if output is not None else self.root / "results.json"),
        )

    def test_marker_write_error(self):
        with mock.patch.object(
            worker.Path, "write_text", side_effect=OSError("boom")
        ):
            with self.assertRaisesRegex(
                worker.PictologicsCLIError, "cannot create worker activity marker"
            ):
                worker.run_cli(self._args(), stdout=io.StringIO())

    def test_output_bad_suffix(self):
        with self.assertRaisesRegex(
            worker.PictologicsCLIError, "outputResults filename must end in .json"
        ):
            worker.run_cli(self._args(output=self.root / "out.txt"), stdout=io.StringIO())

    def test_output_mismatch(self):
        with self.assertRaisesRegex(
            worker.ManifestValidationError, "does not match manifest"
        ):
            worker.run_cli(
                self._args(output=self.root / "other.json"), stdout=io.StringIO()
            )

    def test_unlink_filenotfound(self):
        with mock.patch.object(
            worker.Path, "unlink", side_effect=FileNotFoundError("gone")
        ):
            with self.assertRaises(worker.PictologicsCLIError):
                worker.run_cli(
                    self._args(output=self.root / "out.txt"), stdout=io.StringIO()
                )

    def test_unlink_oserror(self):
        with mock.patch.object(worker.Path, "unlink", side_effect=OSError("boom")):
            with self.assertRaises(worker.PictologicsCLIError):
                worker.run_cli(
                    self._args(output=self.root / "out.txt"), stdout=io.StringIO()
                )


class MainTests(unittest.TestCase):
    def test_main_success(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "image.nii.gz").touch()
            (root / "mask.nii.gz").touch()
            manifest_path = root / "job.json"
            manifest_path.write_text(
                json.dumps(make_payload(root)), encoding="utf-8"
            )
            FakePictologics.load_calls = []
            with mock.patch.dict(os.environ, {}, clear=False), mock.patch.object(
                worker, "isolate_dependency_path"
            ) as iso, mock.patch.object(
                worker, "import_private_pictologics", return_value=FakePictologics
            ):
                rc = worker.main(
                    [
                        str(manifest_path),
                        str(root / "dep"),
                        str(root / "results.json"),
                    ],
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                )
            self.assertEqual(rc, 0)
            self.assertTrue((root / "results.json").is_file())
            self.assertTrue((root / "provenance.json").is_file())
            iso.assert_called_once()

    def test_main_pictologics_error_returns_2(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "job.json"
            manifest_path.write_text("{}", encoding="utf-8")
            errors = io.StringIO()
            rc = worker.main(
                [str(manifest_path), str(root), str(root / "out.json")],
                stdout=io.StringIO(),
                stderr=errors,
            )
        self.assertEqual(rc, 2)
        self.assertIn("PictologicsCLI error", errors.getvalue())

    def test_main_as_script_entrypoint(self):
        argv = [
            "PictologicsCLI.py",
            "/nonexistent/job.json",
            "/nonexistent/dep",
            "/nonexistent/out.json",
        ]
        with mock.patch.object(sys, "argv", argv):
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as ctx:
                    runpy.run_path(str(WORKER_PATH), run_name="__main__")
        self.assertEqual(ctx.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
