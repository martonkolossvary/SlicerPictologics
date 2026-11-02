"""Privacy is an allowlist contract, not a best-effort log redactor."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "PictologicsSlicer"))

from PictologicsLib.diagnostics import RECOVERY, build_diagnostics, diagnostics_text  # noqa: E402


def sections():
    return {
        "runtime": {"extension_version": "0.1.0", "slicer_version": "5.12.4",
                    "slicer_revision": "4e21c19", "python_version": "3.12.10", "qt_version": "5.15.18",
                    "os": "Darwin", "process_architecture": "x86_64"},
        "dependency": {"adopted_version": "0.5.1", "installed_version": "0.5.1",
                       "metadata_status": "compatible"},
        "operation": {"kind": "run", "outcome": "failed", "failure_code": "worker_failed"},
        "run": {"state": "failed", "roi_count": 2, "feature_rows": 340, "elapsed_seconds": 45},
    }


class DiagnosticsTest(unittest.TestCase):
    def test_report_contains_only_explicit_technical_fields(self):
        source = sections()
        report = build_diagnostics(**source)
        self.assertEqual(report["runtime"], source["runtime"])
        self.assertEqual(report["dependency"], source["dependency"])
        self.assertEqual(report["last_run"], source["run"])
        self.assertEqual(report["last_operation"]["recovery"], RECOVERY["worker_failed"])
        self.assertIn("not an import/API/JIT test", report["scope"])
        self.assertEqual(json.loads(diagnostics_text(**source)), report)
        self.assertEqual(sections(), source)

    def test_arbitrary_fields_and_injected_strings_never_reach_report(self):
        for secret in (
            "/Users/Private Patient/scans/CT.nii.gz", r"C:\Patients\Alice\scan.nrrd",
            "patient@example.org", "<script>Patient</script>", "0.5.1+PatientName",
            "5.12.4\nPatientName", "x86_64-custom-hostname", "Linux-private-clinic",
        ):
            with self.subTest(secret=secret):
                source = sections()
                for values in source.values():
                    for key in list(values):
                        values[key] = secret
                    values.update(subject_id=secret, image_name=secret, roi_name=secret,
                                  traceback=secret, log=secret, path=secret, DICOM={"PatientName": secret})
                text = diagnostics_text(**source)
                self.assertNotIn(secret, text)
                self.assertNotIn('DICOM"', text)
                report = json.loads(text)
                self.assertEqual(report["dependency"]["metadata_status"], "inspection_failed")
                self.assertEqual(report["runtime"]["slicer_revision"], "unknown")
                self.assertIsNone(report["last_run"]["roi_count"])

    def test_counts_reject_invalid_types_and_nonfinite_numbers(self):
        for value in (None, True, False, -1, 1_000_000_001, 2.5, float("nan"), float("inf"), {}, [], "2"):
            with self.subTest(value=value):
                source = sections()
                source["run"] = dict.fromkeys(("roi_count", "feature_rows", "elapsed_seconds"), value)
                report = json.loads(diagnostics_text(**source))
                self.assertEqual(report["last_run"], {
                    "state": "not_started", "roi_count": None, "feature_rows": None, "elapsed_seconds": None,
                })

    def test_missing_fields_fail_closed_and_each_failure_has_static_recovery(self):
        source = dict.fromkeys(("runtime", "dependency", "operation", "run"), {})
        report = build_diagnostics(**source)
        self.assertEqual(report["last_operation"]["failure_code"], "none")
        self.assertEqual(report["runtime"]["python_version"], "unknown")
        for code, message in RECOVERY.items():
            source["operation"] = {"failure_code": code}
            self.assertEqual(build_diagnostics(**source)["last_operation"]["recovery"], message)

    def test_known_preview_version_forms_are_preserved(self):
        for version in ("5.13.0", "5.13.0.dev1", "0.6.0rc1", "3.13.0b2", "3.13.0a1"):
            with self.subTest(version=version):
                source = sections()
                source["runtime"]["slicer_version"] = version
                self.assertEqual(build_diagnostics(**source)["runtime"]["slicer_version"], version)


if __name__ == "__main__":
    unittest.main()
