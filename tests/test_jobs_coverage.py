"""Standalone statement-coverage tests for ``PictologicsLib.jobs``.

This module is self-contained: on its own it drives every branch in ``jobs.py``,
focusing on the manifest validation error paths and the atomic-write cleanup logic.
"""

from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "PictologicsSlicer"))

from PictologicsLib.jobs import (
    JOB_MANIFEST_SCHEMA_VERSION,
    WHOLE_VOLUME_ROI_ID,
    JobManifestError,
    _canonical_json_bytes,
    _fsync_parent_dir,
    _has_suffix,
    _json_clone,
    _non_empty_string,
    _optional_string,
    _path_text,
    _shape_error,
    _validate_configuration_document,
    _validate_lower_sha256,
    _validate_object_shape,
    _validate_timestamp,
    build_job_manifest,
    load_job_manifest,
    sha256_file,
    sha256_payload,
    validate_job_manifest,
    write_job_manifest,
)


def _valid_manifest(root: Path) -> dict[str, object]:
    """Build a fully-populated, valid manifest exercising every optional field."""

    return build_job_manifest(
        image_path=root / "image.nii.gz",
        rois=[
            {
                "roi_id": "seg-1",
                "roi_name": "Tumour",
                "roi_source": "segmentation",
                "mask_path": root / "mask.nii.gz",
                "metadata": {"segment_id": "Segment_1"},
            }
        ],
        configuration_document={
            "standard_configurations": ["standard_fbn_32"],
            "custom_configuration_path": None,
            "warmup": True,
        },
        metadata={
            "numba_cache_path": root / "numba-cache",
            "pictologics_version_at_submission": "0.5.0",
            "input_volume_node_id": "vtkMRMLScalarVolumeNode1",
        },
        results_path=root / "result.json",
        provenance_path=root / "provenance.json",
        subject_id="patient-001",
        subject_metadata={"age": 40},
        image_name="CT",
        run_id="run-001",
        timestamp="2026-07-18T12:00:00Z",
        extension_version="0.1.0",
        pictologics_requirement="pictologics==0.5.0",
    )


class HashHelperTests(unittest.TestCase):
    def test_sha256_payload_success_and_non_serialisable(self) -> None:
        self.assertEqual(len(sha256_payload({"a": 1})), 64)
        with self.assertRaisesRegex(JobManifestError, "canonical JSON"):
            sha256_payload(object())

    def test_canonical_json_bytes_directly(self) -> None:
        self.assertEqual(_canonical_json_bytes({"a": 1}), b'{"a":1}')
        with self.assertRaises(JobManifestError):
            _canonical_json_bytes(float("nan"))

    def test_sha256_file_chunking_and_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "value.bin")
            path.write_bytes(b"abc")
            self.assertEqual(
                sha256_file(path),
                "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            )
            self.assertEqual(sha256_file(path), sha256_file(path, chunk_size=2))
            with self.assertRaises(ValueError):
                sha256_file(path, chunk_size=0)


class SmallHelperTests(unittest.TestCase):
    def test_non_empty_string(self) -> None:
        self.assertEqual(_non_empty_string("ok", "f"), "ok")
        with self.assertRaises(JobManifestError):
            _non_empty_string("   ", "f")
        with self.assertRaises(JobManifestError):
            _non_empty_string(123, "f")

    def test_optional_string(self) -> None:
        self.assertEqual(_optional_string("", "f"), "")
        with self.assertRaises(JobManifestError):
            _optional_string(123, "f")

    def test_has_suffix(self) -> None:
        self.assertTrue(_has_suffix("A.NII.GZ", (".nii", ".nii.gz")))
        self.assertFalse(_has_suffix("a.txt", (".nii", ".nii.gz")))

    def test_path_text_variants(self) -> None:
        self.assertTrue(_path_text("~/x.nii.gz", "f").endswith("x.nii.gz"))
        with self.assertRaisesRegex(JobManifestError, "non-empty local path"):
            _path_text("   ", "f")
        with self.assertRaisesRegex(JobManifestError, "not a valid local path"):
            _path_text("bad\x00path", "f")

    def test_json_clone_success_and_rejection(self) -> None:
        self.assertEqual(_json_clone({"b": 2, "a": 1}, "f"), {"a": 1, "b": 2})
        with self.assertRaisesRegex(JobManifestError, "finite JSON"):
            _json_clone(float("nan"), "f")
        with self.assertRaisesRegex(JobManifestError, "finite JSON"):
            _json_clone(object(), "f")

    def test_shape_error_reports_missing_and_unknown(self) -> None:
        error = _shape_error(
            "obj",
            {"present", "extra"},
            required=frozenset({"present", "wanted"}),
            allowed=frozenset({"present", "wanted"}),
        )
        message = str(error)
        self.assertIn("missing keys: wanted", message)
        self.assertIn("unknown keys: extra", message)

    def test_validate_object_shape_pass_and_fail(self) -> None:
        _validate_object_shape(
            {"a": 1}, "f", required=frozenset({"a"}), allowed=frozenset({"a", "b"})
        )
        with self.assertRaises(JobManifestError):
            _validate_object_shape(
                {"b": 1}, "f", required=frozenset({"a"}), allowed=frozenset({"a"})
            )

    def test_validate_lower_sha256(self) -> None:
        digest = "0" * 64
        self.assertEqual(_validate_lower_sha256(digest, "f"), digest)
        with self.assertRaises(JobManifestError):
            _validate_lower_sha256("abc", "f")
        with self.assertRaises(JobManifestError):
            _validate_lower_sha256("g" * 64, "f")

    def test_validate_timestamp(self) -> None:
        self.assertEqual(
            _validate_timestamp("2026-07-18T12:00:00Z"), "2026-07-18T12:00:00Z"
        )
        with self.assertRaisesRegex(JobManifestError, "non-empty"):
            _validate_timestamp("")
        with self.assertRaisesRegex(JobManifestError, "ISO 8601"):
            _validate_timestamp("not-a-date")
        with self.assertRaisesRegex(JobManifestError, "include a timezone"):
            _validate_timestamp("2026-07-18T12:00:00")
        with self.assertRaisesRegex(JobManifestError, "date-time"):
            _validate_timestamp("2026-07-18 12:00:00+00:00")


class ConfigurationDocumentTests(unittest.TestCase):
    def test_valid_standard_and_custom_documents(self) -> None:
        standard = {
            "standard_configurations": ["standard_a"],
            "custom_configuration_path": None,
            "warmup": True,
        }
        self.assertIs(_validate_configuration_document(standard), standard)
        custom = {
            "standard_configurations": [],
            "custom_configuration_path": "config.yaml",
            "custom_configuration_sha256": "a" * 64,
            "warmup": False,
        }
        self.assertIs(_validate_configuration_document(custom), custom)

    def test_every_rejection_path(self) -> None:
        base = {
            "standard_configurations": ["standard_a"],
            "custom_configuration_path": None,
            "warmup": True,
        }
        cases = [
            ("must be an object", ["not", "a", "dict"]),
            ("invalid shape", {**base, "unexpected": 1}),
            (
                "must be an array",
                {**base, "standard_configurations": "nope"},
            ),
            (
                "must start",
                {**base, "standard_configurations": ["not_standard"]},
            ),
            (
                "Duplicate standard",
                {**base, "standard_configurations": ["standard_a", "standard_a"]},
            ),
            (
                "must be a string or null",
                {**base, "custom_configuration_path": 123},
            ),
            (
                "must end in",
                {**base, "custom_configuration_path": "config.txt"},
            ),
            (
                "must select a standard or custom",
                {
                    "standard_configurations": [],
                    "custom_configuration_path": None,
                    "warmup": True,
                },
            ),
            ("must be a boolean", {**base, "warmup": "yes"}),
            (
                "must be a lowercase SHA-256",
                {**base, "custom_configuration_sha256": "nothex"},
            ),
            (
                "requires custom_configuration_path",
                {**base, "custom_configuration_sha256": "a" * 64},
            ),
        ]
        for pattern, document in cases:
            with self.subTest(pattern=pattern):
                with self.assertRaisesRegex(JobManifestError, pattern):
                    _validate_configuration_document(document)


class BuilderTests(unittest.TestCase):
    @staticmethod
    def _config() -> dict[str, object]:
        return {
            "standard_configurations": ["standard_fbn_32"],
            "custom_configuration_path": None,
            "warmup": True,
        }

    @staticmethod
    def _metadata(root: Path) -> dict[str, object]:
        return {"numba_cache_path": root / "numba-cache"}

    def test_full_manifest_round_trips_defaults_and_explicit_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            explicit = _valid_manifest(root)
            self.assertEqual(explicit["schema_version"], JOB_MANIFEST_SCHEMA_VERSION)
            self.assertEqual(explicit["run_id"], "run-001")
            self.assertEqual(explicit["image"]["name"], "CT")
            self.assertEqual(explicit["subject_metadata"], {"age": 40})

            # Defaults exercise the uuid run-id, UTC timestamp, and image-name fallback.
            defaulted = build_job_manifest(
                image_path=root / "scan.nii",
                rois=[],
                whole_volume=True,
                configuration_document=self._config(),
                metadata=self._metadata(root),
                results_path=root / "result.json",
            )
            self.assertTrue(defaulted["run_id"])
            self.assertTrue(defaulted["timestamp"].endswith("Z"))
            self.assertEqual(defaulted["image"]["name"], "scan.nii")
            self.assertEqual(defaulted["rois"][0]["roi_source"], WHOLE_VOLUME_ROI_ID)

    def test_results_and_output_path_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            common = {
                "image_path": root / "image.nii.gz",
                "rois": [],
                "whole_volume": True,
                "configuration_document": self._config(),
                "metadata": self._metadata(root),
            }
            # output_path only (else-branch of the results/output selection).
            from_output = build_job_manifest(**common, output_path=root / "r.json")
            self.assertTrue(from_output["output"]["results_path"].endswith("r.json"))
            # Matching results_path and output_path are accepted.
            build_job_manifest(
                **common,
                results_path=root / "r.json",
                output_path=root / "r.json",
            )
            with self.assertRaisesRegex(JobManifestError, "different paths"):
                build_job_manifest(
                    **common,
                    results_path=root / "a.json",
                    output_path=root / "b.json",
                )
            with self.assertRaisesRegex(JobManifestError, "results_path is required"):
                build_job_manifest(**common)

    def test_custom_configuration_pathlike_is_normalised(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = build_job_manifest(
                image_path=root / "image.nii.gz",
                rois=[],
                whole_volume=True,
                configuration_document={
                    "standard_configurations": [],
                    "custom_configuration_path": root / "config.yaml",
                    "warmup": False,
                },
                metadata=self._metadata(root),
                results_path=root / "result.json",
            )
        self.assertTrue(
            manifest["configuration_document"]["custom_configuration_path"].endswith(
                "config.yaml"
            )
        )

    def test_roi_normalisation_rejections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            common = {
                "image_path": root / "image.nii.gz",
                "configuration_document": self._config(),
                "metadata": self._metadata(root),
                "results_path": root / "result.json",
            }
            with self.assertRaisesRegex(JobManifestError, "local path or null"):
                build_job_manifest(
                    **common,
                    rois=[
                        {"roi_id": "r", "roi_name": "R", "mask_path": 123},
                    ],
                )
            with self.assertRaisesRegex(JobManifestError, r"rois\[0\].metadata"):
                build_job_manifest(
                    **common,
                    rois=[
                        {
                            "roi_id": "r",
                            "roi_name": "R",
                            "mask_path": root / "m.nii.gz",
                            "metadata": ["not", "a", "map"],
                        },
                    ],
                )
            with self.assertRaisesRegex(JobManifestError, "mask_path is required"):
                build_job_manifest(
                    **common,
                    rois=[{"roi_id": "r", "roi_name": "R", "roi_source": "segmentation"}],
                )

    def test_builder_argument_and_type_rejections(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            good_roi = {
                "roi_id": "r",
                "roi_name": "R",
                "roi_source": "segmentation",
                "mask_path": root / "m.nii.gz",
            }
            results = {"results_path": root / "result.json"}
            with self.assertRaisesRegex(JobManifestError, "sequence of objects"):
                build_job_manifest(
                    image_path=root / "i.nii.gz",
                    rois="not-a-sequence",
                    configuration_document=self._config(),
                    metadata=self._metadata(root),
                    **results,
                )
            with self.assertRaisesRegex(JobManifestError, "whole_volume cannot"):
                build_job_manifest(
                    image_path=root / "i.nii.gz",
                    rois=[good_roi],
                    whole_volume=True,
                    configuration_document=self._config(),
                    metadata=self._metadata(root),
                    **results,
                )
            with self.assertRaisesRegex(JobManifestError, r"rois\[0\] must be an object"):
                build_job_manifest(
                    image_path=root / "i.nii.gz",
                    rois=[123],
                    configuration_document=self._config(),
                    metadata=self._metadata(root),
                    **results,
                )
            with self.assertRaisesRegex(
                JobManifestError, "configuration_document must be an object"
            ):
                build_job_manifest(
                    image_path=root / "i.nii.gz",
                    rois=[good_roi],
                    configuration_document=123,
                    metadata=self._metadata(root),
                    **results,
                )
            with self.assertRaisesRegex(JobManifestError, "metadata must be an object"):
                build_job_manifest(
                    image_path=root / "i.nii.gz",
                    rois=[good_roi],
                    configuration_document=self._config(),
                    metadata=123,
                    **results,
                )
            with self.assertRaisesRegex(JobManifestError, "numba_cache_path is required"):
                build_job_manifest(
                    image_path=root / "i.nii.gz",
                    rois=[good_roi],
                    configuration_document=self._config(),
                    metadata={},
                    **results,
                )
            with self.assertRaisesRegex(
                JobManifestError, "numba_cache_path must be a local path"
            ):
                build_job_manifest(
                    image_path=root / "i.nii.gz",
                    rois=[good_roi],
                    configuration_document=self._config(),
                    metadata={"numba_cache_path": 123},
                    **results,
                )
            with self.assertRaisesRegex(
                JobManifestError, "image_path is not a valid local path"
            ):
                build_job_manifest(
                    image_path="bad\x00image.nii.gz",
                    rois=[good_roi],
                    configuration_document=self._config(),
                    metadata=self._metadata(root),
                    **results,
                )
            with self.assertRaisesRegex(
                JobManifestError, "subject_metadata must be an object"
            ):
                build_job_manifest(
                    image_path=root / "i.nii.gz",
                    rois=[good_roi],
                    configuration_document=self._config(),
                    metadata=self._metadata(root),
                    subject_metadata=123,
                    **results,
                )


class ValidateManifestTampers(unittest.TestCase):
    def _tampered(self, root: Path, mutate) -> dict[str, object]:
        manifest = copy.deepcopy(_valid_manifest(root))
        mutate(manifest)
        return manifest

    def test_valid_base_passes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = _valid_manifest(Path(directory))
            self.assertEqual(validate_job_manifest(manifest), manifest)

    def test_non_mapping_payload(self) -> None:
        with self.assertRaisesRegex(JobManifestError, "must be an object"):
            validate_job_manifest(["not", "a", "map"])

    def test_optional_pictologics_version_may_be_null(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = copy.deepcopy(_valid_manifest(root))
            manifest["metadata"]["pictologics_version_at_submission"] = None
            self.assertEqual(
                validate_job_manifest(manifest)["metadata"][
                    "pictologics_version_at_submission"
                ],
                None,
            )

    def test_all_rejection_paths(self) -> None:
        def mut(field_path, value):
            def _apply(manifest):
                target = manifest
                for key in field_path[:-1]:
                    target = target[key]
                target[field_path[-1]] = value

            return _apply

        def delete(field_path):
            def _apply(manifest):
                target = manifest
                for key in field_path[:-1]:
                    target = target[key]
                del target[field_path[-1]]

            return _apply

        def combine(*mutators):
            def _apply(manifest):
                for mutator in mutators:
                    mutator(manifest)

            return _apply

        cases = [
            ("invalid shape", combine(delete(["metadata"]), mut(["extra"], 1))),
            ("Unsupported schema_version", mut(["schema_version"], 2)),
            ("Unsupported schema_version", mut(["schema_version"], True)),
            ("run_id must be", mut(["run_id"], "")),
            ("timestamp must be ISO", mut(["timestamp"], "not-a-date")),
            ("subject_id must be a string", mut(["subject_id"], 123)),
            ("extension_version must be a string", mut(["extension_version"], 123)),
            (
                "pictologics_requirement must be a string",
                mut(["pictologics_requirement"], 123),
            ),
            ("image must be an object", mut(["image"], 123)),
            ("image has an invalid shape", delete(["image", "name"])),
            ("image.path must be a non-empty", mut(["image", "path"], "")),
            ("image.path must end in", mut(["image", "path"], "scan.txt")),
            ("image.name must be a non-empty", mut(["image", "name"], "")),
            ("rois must contain at least one", mut(["rois"], [])),
            ("rois must contain at least one", mut(["rois"], "not-a-list")),
            (r"rois\[0\] must be an object", mut(["rois", 0], 123)),
            (r"rois\[0\] has an invalid shape", delete(["rois", 0, "roi_name"])),
            (r"rois\[0\]\.roi_id must be", mut(["rois", 0, "roi_id"], "")),
            (r"rois\[0\]\.mask_path must be null", mut(["rois", 0, "roi_source"], WHOLE_VOLUME_ROI_ID)),
            (r"rois\[0\]\.mask_path is required", mut(["rois", 0, "mask_path"], None)),
            (r"rois\[0\]\.mask_path must end in", mut(["rois", 0, "mask_path"], "mask.txt")),
            (r"rois\[0\]\.metadata must be an object", mut(["rois", 0, "metadata"], 123)),
            (
                "configuration_sha256 does not match",
                mut(["configuration_document", "warmup"], False),
            ),
            (
                "configuration_sha256 must be a lowercase",
                mut(["configuration_sha256"], "nothex"),
            ),
            ("output must be an object", mut(["output"], 123)),
            ("output has an invalid shape", delete(["output", "results_path"])),
            ("output.results_path must be a non-empty", mut(["output", "results_path"], "")),
            ("output.results_path must end in", mut(["output", "results_path"], "r.txt")),
            ("output.provenance_path must be a non-empty", mut(["output", "provenance_path"], "")),
            ("output.provenance_path must end in", mut(["output", "provenance_path"], "p.txt")),
            ("metadata must be an object", mut(["metadata"], 123)),
            ("metadata has an invalid shape", delete(["metadata", "numba_cache_path"])),
            (
                "metadata.numba_cache_path must be a non-empty",
                mut(["metadata", "numba_cache_path"], ""),
            ),
            (
                "pictologics_version_at_submission must be a string",
                mut(["metadata", "pictologics_version_at_submission"], 123),
            ),
            (
                "input_volume_node_id must be a string",
                mut(["metadata", "input_volume_node_id"], 123),
            ),
            ("Duplicate ROI id", None),  # handled specially below
            ("subject_metadata must be an object", mut(["subject_metadata"], 123)),
            ("provenance_path must differ", None),  # handled specially below
        ]

        for pattern, mutator in cases:
            with self.subTest(pattern=pattern), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                if pattern == "Duplicate ROI id":
                    manifest = copy.deepcopy(_valid_manifest(root))
                    manifest["rois"].append(copy.deepcopy(manifest["rois"][0]))
                elif pattern == "provenance_path must differ":
                    manifest = copy.deepcopy(_valid_manifest(root))
                    manifest["output"]["provenance_path"] = manifest["output"][
                        "results_path"
                    ]
                else:
                    manifest = self._tampered(root, mutator)
                with self.assertRaisesRegex(JobManifestError, pattern):
                    validate_job_manifest(manifest)


class WriteAndLoadTests(unittest.TestCase):
    def test_write_then_load_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = _valid_manifest(root)
            path = write_job_manifest(root / "nested" / "job.json", manifest)
            self.assertTrue(path.is_file())
            self.assertEqual(load_job_manifest(path), manifest)

    def test_write_cleanup_when_replace_and_unlink_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = _valid_manifest(root)
            with (
                mock.patch(
                    "PictologicsLib.jobs.os.replace", side_effect=OSError("no replace")
                ),
                mock.patch(
                    "PictologicsLib.jobs.Path.unlink", side_effect=OSError("no unlink")
                ),
                self.assertRaises(OSError),
            ):
                write_job_manifest(root / "job.json", manifest)

    def test_fsync_parent_dir_all_branches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "file.txt")
            path.write_text("x", encoding="utf-8")
            _fsync_parent_dir(path)
            with mock.patch("PictologicsLib.jobs.os.open", side_effect=OSError):
                _fsync_parent_dir(path)
            with mock.patch("PictologicsLib.jobs.os.fsync", side_effect=OSError):
                _fsync_parent_dir(path)

    def test_load_error_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            missing = root / "missing.json"
            with self.assertRaisesRegex(JobManifestError, "Unable to read"):
                load_job_manifest(missing)

            with self.assertRaisesRegex(JobManifestError, "Unable to read"):
                load_job_manifest(root)  # a directory is not a regular file

            bad_json = root / "bad.json"
            bad_json.write_text("{not json", encoding="utf-8")
            with self.assertRaisesRegex(JobManifestError, "Unable to read"):
                load_job_manifest(bad_json)

    def test_load_non_utf8_propagates_decode_error(self) -> None:
        # The reader only wraps OSError/JSONDecodeError; a UTF-8 decoding failure
        # surfaces the underlying UnicodeDecodeError unchanged.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "latin1.json")
            path.write_bytes(b"\xff\xfe not utf8")
            with self.assertRaises(UnicodeDecodeError):
                load_job_manifest(path)


if __name__ == "__main__":
    unittest.main()
