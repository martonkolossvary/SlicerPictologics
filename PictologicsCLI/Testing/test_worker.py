"""Standard-library tests for the standalone Pictologics CLI worker."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import types
import unittest
import warnings
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest import mock


CLI_DIR = Path(__file__).resolve().parents[1]
WORKER_PATH = CLI_DIR / "PictologicsCLI.py"

SPEC = importlib.util.spec_from_file_location("pictologics_cli_worker", WORKER_PATH)
assert SPEC is not None and SPEC.loader is not None
worker = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = worker
SPEC.loader.exec_module(worker)


class FakeCatalog:
    def __init__(self, records: list[dict[str, object]]) -> None:
        self.records = records

    def to_dict(self, orient: str = "records") -> list[dict[str, object]]:
        if orient != "records":
            raise ValueError(orient)
        return [dict(record) for record in self.records]


class FakePipeline:
    catalog_record = {
        "config": "standard_fbn_32",
        "feature_key": "joint_entropy_TU9B",
        "feature_name": "joint_entropy",
        "ibsi_code": "TU9B",
        "family": "glcm",
    }

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
    def load_configs(
        cls,
        file_path: object,
        validate: bool = False,
        load_standard: bool = False,
    ) -> "FakePipeline":
        del load_standard
        # Mirror Pictologics: validate=True only *warns* on malformed configs.
        text = Path(str(file_path)).read_text(encoding="utf-8")
        if validate and "trigger-warning" in text:
            warnings.warn(
                "Config 'custom_a' step 0: unknown parameter 'bogus'",
                UserWarning,
                stacklevel=2,
            )
        return cls()

    def merge_configs(self, other: object, overwrite: bool = False) -> "FakePipeline":
        del other, overwrite
        return self

    def clear_log(self) -> None:
        self._log.clear()

    def run(
        self,
        image: object,
        mask: object,
        *,
        subject_id: str,
        config_names: list[str],
    ) -> dict[str, dict[str, float]]:
        self.run_calls.append((image, mask, subject_id, tuple(config_names)))
        self._log = [
            {"config_name": "standard_fbn_32", "status": "completed", "detail": "saved"}
        ]
        return {"standard_fbn_32": {"joint_entropy_TU9B": 4.25}}


class FakePictologics:
    __version__ = "9.8.7"
    RadiomicsPipeline = FakePipeline
    load_calls: list[tuple[str, object | None]] = []

    @classmethod
    def load_image(
        cls, path: str, reference_image: object | None = None
    ) -> dict[str, object]:
        cls.load_calls.append((path, reference_image))
        if Path(path).name == "bad-mask.nii.gz":
            raise ValueError("broken mask")
        return {"path": path, "reference": reference_image}


def make_manifest_payload(
    root: Path,
    *,
    rois: list[dict[str, object]] | None = None,
    custom_configuration_path: str | None = None,
) -> dict[str, object]:
    configuration_document = {
        "standard_configurations": ["standard_fbn_32"],
        "custom_configuration_path": custom_configuration_path,
        "custom_configuration_sha256": (
            worker.file_sha256(root / custom_configuration_path)
            if custom_configuration_path is not None
            else None
        ),
        "warmup": True,
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
    return {
        "schema_version": 1,
        "run_id": "run-123",
        "timestamp": "2026-07-18T14:00:00Z",
        "subject_id": "subject-7",
        "subject_metadata": {"cohort": "test"},
        "image": {"path": str(root / "image.nii.gz"), "name": "image"},
        "rois": rois,
        "configuration_document": configuration_document,
        "configuration_sha256": worker.configuration_sha256(configuration_document),
        "output": {
            "results_path": str(root / "results.json"),
            "provenance_path": str(root / "provenance.json"),
        },
        "extension_version": "0.1.0",
        "pictologics_requirement": "pictologics==0.5.0",
        "metadata": {
            "numba_cache_path": str(root / "numba-cache"),
            "pictologics_version_at_submission": "0.5.0",
            "input_volume_node_id": "vtkMRMLScalarVolumeNode1",
        },
    }


class ManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "image.nii.gz").touch()
        (self.root / "mask.nii.gz").touch()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_validate_canonical_manifest_and_relative_custom_config(self) -> None:
        (self.root / "custom-configuration.yaml").write_text(
            "schema_version: '1.0'\nconfigs: {}\n", encoding="utf-8"
        )
        payload = make_manifest_payload(
            self.root, custom_configuration_path="custom-configuration.yaml"
        )
        manifest = worker.validate_manifest(payload, base_dir=self.root)

        self.assertEqual(manifest.run_id, "run-123")
        self.assertEqual(
            manifest.custom_configuration_path,
            (self.root / "custom-configuration.yaml").resolve(),
        )
        self.assertEqual(
            manifest.configuration_document["custom_configuration_path"],
            "custom-configuration.yaml",
        )
        self.assertEqual(manifest.rois[0].metadata["segment_color"], "#ff0000")
        self.assertEqual(
            manifest.provenance_path, (self.root / "provenance.json").resolve()
        )

    def test_rejects_unknown_keys_and_hash_drift(self) -> None:
        payload = make_manifest_payload(self.root)
        payload["surprise"] = True
        with self.assertRaisesRegex(
            worker.ManifestValidationError, "unknown keys: surprise"
        ):
            worker.validate_manifest(payload, base_dir=self.root)

        payload = make_manifest_payload(self.root)
        payload["configuration_document"]["warmup"] = False
        with self.assertRaisesRegex(worker.ManifestValidationError, "does not match"):
            worker.validate_manifest(payload, base_dir=self.root)

    def test_null_mask_is_reserved_for_whole_volume(self) -> None:
        payload = make_manifest_payload(
            self.root,
            rois=[
                {
                    "roi_id": "bad",
                    "roi_name": "Bad",
                    "roi_source": "segmentation",
                    "mask_path": None,
                }
            ],
        )
        with self.assertRaisesRegex(worker.ManifestValidationError, "may be null only"):
            worker.validate_manifest(payload, base_dir=self.root)

    def test_load_manifest_reports_invalid_json(self) -> None:
        path = self.root / "job.json"
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaisesRegex(worker.ManifestValidationError, "line 1"):
            worker.load_manifest(path)


class RuntimeIsolationTests(unittest.TestCase):
    def test_dependency_target_is_first_and_other_site_packages_are_removed(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dependency_path = Path(directory)
            isolated = worker.isolate_dependency_path(
                dependency_path,
                search_path=[
                    "/python/stdlib",
                    "/global/lib/python/site-packages",
                    "/debian/dist-packages",
                    str(dependency_path),
                    "",
                ],
            )
        self.assertEqual(isolated[0], str(dependency_path.resolve()))
        self.assertEqual(isolated[1:], ["/python/stdlib", ""])

    def test_environment_suppresses_import_warmup_and_sets_numba_cache(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "image.nii.gz").touch()
            (root / "mask.nii.gz").touch()
            manifest = worker.validate_manifest(
                make_manifest_payload(root), base_dir=root
            )
            with mock.patch.dict(os.environ, {}, clear=True):
                worker.configure_environment(manifest)
                self.assertEqual(os.environ["PICTOLOGICS_DISABLE_WARMUP"], "1")
                self.assertEqual(
                    os.environ["NUMBA_CACHE_DIR"], str((root / "numba-cache").resolve())
                )
                self.assertTrue((root / "numba-cache").is_dir())

    def test_explicit_warmup_is_reenabled_after_private_import(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            dependency_path = Path(directory)
            warmup = mock.Mock()
            module = types.SimpleNamespace(
                __file__=str(dependency_path / "pictologics" / "__init__.py"),
                warmup_jit=warmup,
            )
            with mock.patch.object(
                worker.importlib, "import_module", return_value=module
            ):
                with mock.patch.dict(
                    os.environ, {"PICTOLOGICS_DISABLE_WARMUP": "1"}, clear=True
                ):
                    result = worker.import_private_pictologics(
                        dependency_path, warmup=True
                    )
                    self.assertIs(result, module)
                    self.assertEqual(os.environ["PICTOLOGICS_DISABLE_WARMUP"], "0")
            warmup.assert_called_once_with()

    def test_runtime_version_must_match_exact_submitted_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "image.nii.gz").touch()
            (root / "mask.nii.gz").touch()
            manifest = worker.validate_manifest(
                make_manifest_payload(root), base_dir=root
            )
            matching = types.SimpleNamespace(__version__="0.5.0")
            self.assertEqual(worker.verify_runtime_version(manifest, matching), "0.5.0")
            with self.assertRaisesRegex(
                worker.WorkerSetupError, "changed after submission"
            ):
                worker.verify_runtime_version(
                    manifest, types.SimpleNamespace(__version__="0.5.1")
                )


class ExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "image.nii.gz").touch()
        (self.root / "bad-mask.nii.gz").touch()
        FakePictologics.load_calls = []

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_multiple_rois_progress_mapping_and_nonfatal_failure(self) -> None:
        rois = [
            {
                "roi_id": "whole-volume",
                "roi_name": "Whole volume",
                "roi_source": "whole-volume",
                "mask_path": None,
            },
            {
                "roi_id": "bad",
                "roi_name": "Bad mask",
                "roi_source": "segmentation",
                "mask_path": str(self.root / "bad-mask.nii.gz"),
            },
        ]
        manifest = worker.validate_manifest(
            make_manifest_payload(self.root, rois=rois), base_dir=self.root
        )
        progress_stream = io.StringIO()
        payload = worker.execute_job(
            manifest,
            FakePictologics,
            self.root / "private-packages",
            progress=worker.ProgressReporter(progress_stream),
        )

        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["run_id"], "run-123")
        self.assertEqual(len(payload["rows"]), 2)
        first, second = payload["rows"]
        self.assertEqual(tuple(first), worker.LONG_ROW_COLUMNS)
        self.assertEqual(first["feature_family"], "glcm")
        self.assertEqual(first["feature_name"], "joint_entropy")
        self.assertEqual(first["ibsi_code"], "TU9B")
        self.assertEqual(first["value"], 4.25)
        self.assertEqual(first["status"], "ok")
        self.assertIsNone(second["value"])
        self.assertEqual(second["status"], "error")
        self.assertEqual(len(payload["errors"]), 1)
        self.assertIn("broken mask", payload["errors"][0]["error"])
        self.assertEqual(len(payload["provenance"]["processing_logs"]), 2)
        self.assertIn(
            "<filter-progress>1.000000</filter-progress>", progress_stream.getvalue()
        )
        self.assertEqual(len(FakePictologics.load_calls), 2)  # image + failed mask

    def test_custom_configuration_validation_warnings_are_fatal(self) -> None:
        custom = self.root / "custom-configuration.yaml"
        custom.write_text("# trigger-warning\nconfigs: {}\n", encoding="utf-8")
        manifest = worker.validate_manifest(
            make_manifest_payload(
                self.root,
                rois=[
                    {
                        "roi_id": "whole-volume",
                        "roi_name": "Whole volume",
                        "roi_source": "whole-volume",
                        "mask_path": None,
                    }
                ],
                custom_configuration_path="custom-configuration.yaml",
            ),
            base_dir=self.root,
        )
        with self.assertRaisesRegex(worker.WorkerSetupError, "failed validation"):
            worker.create_pipeline(FakePictologics, manifest)

    def test_atomic_json_is_strict_and_leaves_no_temporary_file(self) -> None:
        output = self.root / "output.json"
        worker.atomic_write_json(output, {"finite": 1.0, "nan": float("nan")})
        self.assertEqual(
            json.loads(output.read_text(encoding="utf-8")), {"finite": 1.0, "nan": None}
        )
        self.assertEqual(list(self.root.glob(".output.json.*.tmp")), [])


class CLIScaffoldTests(unittest.TestCase):
    def test_xml_and_cmake_match_scripted_cli_contract(self) -> None:
        root = ET.parse(CLI_DIR / "PictologicsCLI.xml").getroot()
        parameters = {
            element.findtext("name"): element
            for element in root.findall(".//parameters/*")
            if element.find("name") is not None
        }
        self.assertEqual(parameters["jobManifest"].findtext("index"), "0")
        self.assertEqual(parameters["dependencyPath"].findtext("index"), "1")
        self.assertEqual(parameters["outputResults"].findtext("index"), "2")
        self.assertEqual(parameters["outputResults"].findtext("channel"), "output")

        cmake = (CLI_DIR / "CMakeLists.txt").read_text(encoding="utf-8")
        self.assertIn("SlicerMacroBuildScriptedCLI", cmake)
        self.assertIn("NAME PictologicsCLI", cmake)
        self.assertTrue(
            WORKER_PATH.read_text(encoding="utf-8").startswith(
                "#!/usr/bin/env python-real"
            )
        )

    def test_main_returns_nonzero_with_helpful_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "job.json"
            manifest_path.write_text("{}", encoding="utf-8")
            errors = io.StringIO()
            return_code = worker.main(
                [str(manifest_path), str(root), str(root / "output.json")],
                stdout=io.StringIO(),
                stderr=errors,
            )
        self.assertNotEqual(return_code, 0)
        self.assertIn("missing keys", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
