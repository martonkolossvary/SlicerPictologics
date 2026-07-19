from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "PictologicsSlicer"))

from PictologicsLib.jobs import (
    JOB_MANIFEST_SCHEMA_VERSION,
    JobManifestError,
    build_job_manifest,
    load_job_manifest,
    sha256_file,
    sha256_payload,
    validate_job_manifest,
    write_job_manifest,
)


class JobManifestTests(unittest.TestCase):
    @staticmethod
    def _configuration() -> dict[str, object]:
        return {
            "standard_configurations": ["standard_fbn_32"],
            "custom_configuration_path": None,
            "warmup": True,
        }

    @staticmethod
    def _metadata(root: Path) -> dict[str, object]:
        return {
            "numba_cache_path": root / "numba-cache",
            "pictologics_version_at_submission": "0.5.0",
            "input_volume_node_id": "vtkMRMLScalarVolumeNode1",
        }

    def _build_masked_manifest(self, root: Path) -> dict[str, object]:
        return build_job_manifest(
            image_path=root / "image.nii.gz",
            rois=[
                {
                    "id": "segment-1",
                    "name": "Tumour",
                    "source": "segmentation",
                    "path": root / "mask.nii.gz",
                    "metadata": {"segment_id": "Segment_1"},
                }
            ],
            configuration_document=self._configuration(),
            metadata=self._metadata(root),
            output_path=root / "result.json",
            provenance_path=root / "provenance.json",
            subject_id="patient-001",
            image_name="CT",
            run_id="run-001",
            timestamp="2026-07-18T12:00:00Z",
            extension_version="0.1.0",
            pictologics_requirement="pictologics==0.5.0",
        )

    def test_builder_returns_versioned_normalised_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self._build_masked_manifest(root)

        self.assertEqual(manifest["schema_version"], JOB_MANIFEST_SCHEMA_VERSION)
        self.assertEqual(manifest["run_id"], "run-001")
        self.assertEqual(manifest["image"]["name"], "CT")
        self.assertEqual(manifest["rois"][0]["roi_id"], "segment-1")
        self.assertEqual(
            manifest["rois"][0]["mask_path"], str((root / "mask.nii.gz").resolve())
        )
        self.assertEqual(
            manifest["configuration_sha256"],
            sha256_payload(manifest["configuration_document"]),
        )

    def test_whole_volume_is_an_explicit_null_mask_roi(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = build_job_manifest(
                image_path=root / "image.nii.gz",
                rois=[],
                whole_volume=True,
                configuration_document=self._configuration(),
                metadata=self._metadata(root),
                results_path=root / "result.json",
            )

        self.assertEqual(len(manifest["rois"]), 1)
        self.assertEqual(manifest["rois"][0]["roi_source"], "whole-volume")
        self.assertIsNone(manifest["rois"][0]["mask_path"])

    def test_write_load_and_file_hash_are_stable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self._build_masked_manifest(root)
            path = write_job_manifest(root / "nested" / "job.json", manifest)
            loaded = load_job_manifest(path)

            self.assertEqual(loaded, manifest)
            self.assertEqual(len(sha256_file(path)), 64)
            self.assertEqual(sha256_file(path), sha256_file(path, chunk_size=7))
            parsed_directly = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(parsed_directly["run_id"], "run-001")

    def test_validator_rejects_tampered_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            manifest = self._build_masked_manifest(Path(directory))
            manifest["configuration_document"]["warmup"] = False
            with self.assertRaisesRegex(JobManifestError, "does not match"):
                validate_job_manifest(manifest)

    def test_validator_rejects_duplicate_roi_ids_and_missing_masks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self._build_masked_manifest(root)
            duplicate = dict(manifest["rois"][0])
            manifest["rois"].append(duplicate)
            with self.assertRaisesRegex(JobManifestError, "Duplicate ROI"):
                validate_job_manifest(manifest)

            manifest = self._build_masked_manifest(root)
            manifest["rois"][0]["mask_path"] = None
            with self.assertRaisesRegex(JobManifestError, "mask_path is required"):
                validate_job_manifest(manifest)

    def test_builder_rejects_no_roi_and_non_json_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            common = {
                "image_path": root / "image.nii.gz",
                "results_path": root / "result.json",
                "metadata": self._metadata(root),
            }
            with self.assertRaisesRegex(JobManifestError, "at least one ROI"):
                build_job_manifest(
                    **common,
                    rois=[],
                    configuration_document=self._configuration(),
                )
            with self.assertRaisesRegex(JobManifestError, "finite JSON"):
                build_job_manifest(
                    **common,
                    rois=[
                        {
                            "roi_id": "roi",
                            "roi_name": "ROI",
                            "roi_source": "segmentation",
                            "mask_path": root / "mask.nii.gz",
                        }
                    ],
                    configuration_document={
                        "standard_configurations": ["standard_fbn_32"],
                        "custom_configuration_path": None,
                        "warmup": True,
                        "custom_configuration_sha256": float("nan"),
                    },
                )

    def test_configuration_and_metadata_shapes_are_versioned(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            common = {
                "image_path": root / "image.nii.gz",
                "rois": [],
                "whole_volume": True,
                "results_path": root / "result.json",
            }
            with self.assertRaisesRegex(JobManifestError, "unknown keys"):
                build_job_manifest(
                    **common,
                    configuration_document={**self._configuration(), "future": True},
                    metadata=self._metadata(root),
                )
            with self.assertRaisesRegex(JobManifestError, "unknown keys"):
                build_job_manifest(
                    **common,
                    configuration_document=self._configuration(),
                    metadata={**self._metadata(root), "future": True},
                )
            with self.assertRaisesRegex(JobManifestError, "numba_cache_path"):
                build_job_manifest(
                    **common,
                    configuration_document=self._configuration(),
                    metadata={},
                )

    def test_custom_configuration_hash_is_covered_by_manifest_hash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            custom_path = root / "custom.yaml"
            custom_path.write_text("configurations: {}\n", encoding="utf-8")
            custom_hash = sha256_file(custom_path)
            configuration = {
                "standard_configurations": [],
                "custom_configuration_path": custom_path,
                "custom_configuration_sha256": custom_hash,
                "warmup": False,
            }
            manifest = build_job_manifest(
                image_path=root / "image.nii.gz",
                rois=[],
                whole_volume=True,
                configuration_document=configuration,
                metadata=self._metadata(root),
                results_path=root / "result.json",
            )

        self.assertEqual(
            manifest["configuration_document"]["custom_configuration_sha256"],
            custom_hash,
        )


class HashTests(unittest.TestCase):
    def test_sha256_file_known_value_and_chunk_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "value.bin")
            path.write_bytes(b"abc")
            self.assertEqual(
                sha256_file(path),
                "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
            )
            with self.assertRaises(ValueError):
                sha256_file(path, chunk_size=0)


if __name__ == "__main__":
    unittest.main()
