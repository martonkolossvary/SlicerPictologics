from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "PictologicsSlicer"))

from PictologicsLib.batch_reports import export_report, new_report, validate_report


class BatchReportTests(unittest.TestCase):
    def test_case_names_preserve_spaces_colons_and_unicode(self) -> None:
        report = new_report(["case", " case "], [("case: α", "No matching image")])
        self.assertEqual([row["case_name"] for row in validate_report(report)["rows"]],
                         ["case", " case ", "case: α"])

    def test_report_preserves_outcomes_and_exports_json_and_csv(self) -> None:
        report = new_report(["case-a", "case-b"], [("case-c", "ambiguous image")])
        report["state"] = "finished"
        report["rows"][0].update({"status": "completed", "elapsed_seconds": 1.5, "roi_count": 2, "row_count": 40})
        report["rows"][1].update({"status": "failed", "reason": "unreadable mask"})
        normalized = validate_report(report)
        self.assertEqual(normalized["rows"][2]["status"], "skipped")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            json_path = export_report(normalized, root / "report.json")
            csv_path = export_report(normalized, root / "report.csv")
            self.assertEqual(json.loads(json_path.read_text())["rows"][0]["row_count"], 40)
            self.assertIn("case_name,status", csv_path.read_text())

    def test_validation_rejects_duplicate_cases_and_nonfinite_counts(self) -> None:
        report = new_report(["case-a"])
        report["rows"].append(dict(report["rows"][0]))
        with self.assertRaises(ValueError):
            validate_report(report)
        report = new_report(["case-a"])
        report["rows"][0]["elapsed_seconds"] = "nan"
        with self.assertRaises(ValueError):
            validate_report(report)

    def test_validation_rejects_malformed_documents(self) -> None:
        invalid_documents = [
            None,
            {"schema_version": "2", "state": "finished", "rows": []},
            {"schema_version": "1", "state": "unknown", "rows": []},
            {"schema_version": "1", "state": "finished"},
            {"schema_version": "1", "state": "finished", "rows": [None]},
        ]
        for document in invalid_documents:
            with self.subTest(document=document), self.assertRaises(ValueError):
                validate_report(document)
        report = new_report(["case-a"])
        report["rows"][0]["roi_count"] = 1.5
        with self.assertRaises(ValueError):
            validate_report(report)
        report["rows"][0]["roi_count"] = "not-a-number"
        with self.assertRaises(ValueError):
            validate_report(report)

    def test_export_rejects_unknown_suffix_and_cleans_up_failed_replace(self) -> None:
        report = new_report(["case-a"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                export_report(report, root / "report.txt")
            with patch("PictologicsLib.batch_reports.os.replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    export_report(report, root / "report.json")
            with patch("PictologicsLib.batch_reports.os.replace", side_effect=OSError("disk full")), patch.object(
                Path, "unlink", side_effect=OSError("locked")
            ):
                with self.assertRaises(OSError):
                    export_report(report, root / "locked.json")
if __name__ == "__main__":
    unittest.main()
