from __future__ import annotations

import csv
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "PictologicsSlicer"))

from PictologicsLib.results import (
    LONG_RESULT_COLUMNS,
    ResultPayloadError,
    build_result_payload,
    export_rows,
    load_result_payload,
    rows_to_wide,
    validate_result_payload,
    write_result_payload,
)


def result_row(**changes: object) -> dict[str, object]:
    row: dict[str, object] = {
        "run_id": "run-001",
        "timestamp": "2026-07-18T12:00:00Z",
        "subject_id": "patient-001",
        "image_name": "CT",
        "roi_source": "segmentation",
        "roi_id": "segment-1",
        "roi_name": "Tumour",
        "configuration": "standard_fbn_32",
        "feature_family": "intensity",
        "feature_name": "mean",
        "ibsi_code": "Q4LE",
        "value": 42.5,
        "status": "ok",
        "pictologics_version": "0.5.0",
        "extension_version": "0.1.0",
    }
    row.update(changes)
    return row


class ResultValidationTests(unittest.TestCase):
    def test_long_columns_are_the_fixed_table_contract(self) -> None:
        self.assertEqual(
            LONG_RESULT_COLUMNS,
            (
                "run_id",
                "timestamp",
                "subject_id",
                "image_name",
                "roi_source",
                "roi_id",
                "roi_name",
                "configuration",
                "feature_family",
                "feature_name",
                "ibsi_code",
                "value",
                "status",
                "pictologics_version",
                "extension_version",
            ),
        )

    def test_build_and_validate_payload_normalises_rows(self) -> None:
        source_row = result_row(value=7)
        payload = build_result_payload(
            run_id="run-001",
            rows=[source_row],
            provenance={"configuration_sha256": "abc"},
            errors=[],
        )
        source_row["value"] = 99

        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["rows"][0]["value"], 7)
        self.assertEqual(tuple(payload["rows"][0]), LONG_RESULT_COLUMNS)

    def test_nan_failure_value_is_valid_but_infinity_is_not(self) -> None:
        payload = build_result_payload(
            run_id="run-001",
            rows=[result_row(value=float("nan"), status="error")],
        )
        self.assertTrue(math.isnan(payload["rows"][0]["value"]))

        with self.assertRaisesRegex(ResultPayloadError, "must not be infinite"):
            build_result_payload(
                run_id="run-001", rows=[result_row(value=float("inf"))]
            )

    def test_missing_column_and_mismatched_run_id_are_rejected(self) -> None:
        missing = result_row()
        del missing["feature_name"]
        with self.assertRaisesRegex(ResultPayloadError, "missing required"):
            build_result_payload(run_id="run-001", rows=[missing])

        payload = {
            "schema_version": 1,
            "run_id": "another-run",
            "rows": [result_row()],
        }
        with self.assertRaisesRegex(ResultPayloadError, "does not match"):
            validate_result_payload(payload)

    def test_versioned_payload_and_row_reject_unknown_fields(self) -> None:
        with self.assertRaisesRegex(ResultPayloadError, "unknown keys"):
            validate_result_payload(
                {
                    "schema_version": 1,
                    "run_id": "run-001",
                    "rows": [result_row()],
                    "future": True,
                }
            )
        with self.assertRaisesRegex(ResultPayloadError, "unknown columns"):
            build_result_payload(
                run_id="run-001",
                rows=[result_row(future="value")],
            )


class ResultExportTests(unittest.TestCase):
    def test_csv_export_has_deterministic_columns(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = export_rows([result_row()], Path(directory, "results.csv"))
            with destination.open("r", encoding="utf-8", newline="") as stream:
                exported = list(csv.DictReader(stream))

        self.assertEqual(tuple(exported[0]), LONG_RESULT_COLUMNS)
        self.assertEqual(exported[0]["value"], "42.5")
        self.assertEqual(exported[0]["roi_name"], "Tumour")

    def test_json_export_is_strict_and_maps_nan_to_null(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = export_rows(
                [result_row(value=float("nan"), status="error")],
                Path(directory, "results.json"),
            )
            text = destination.read_text(encoding="utf-8")
            exported = json.loads(text)

        self.assertNotIn("NaN", text)
        self.assertIsNone(exported[0]["value"])

    def test_csv_export_maps_nan_to_empty_cell(self) -> None:
        # CSV must agree with the strict-JSON export: a NaN failure sentinel becomes
        # an empty field, never the literal string "nan".
        with tempfile.TemporaryDirectory() as directory:
            destination = export_rows(
                [result_row(value=float("nan"), status="error")],
                Path(directory, "results.csv"),
            )
            text = destination.read_text(encoding="utf-8")
            with destination.open("r", encoding="utf-8", newline="") as stream:
                exported = list(csv.DictReader(stream))

        self.assertNotIn("nan", text.lower())
        self.assertEqual(exported[0]["value"], "")

    def test_wide_rows_have_one_row_per_roi_and_configuration_feature_columns(
        self,
    ) -> None:
        rows = [
            result_row(configuration="standard_a", feature_name="mean", value=1.0),
            result_row(configuration="standard_b", feature_name="mean", value=2.0),
        ]

        wide = rows_to_wide(rows)

        self.assertEqual(len(wide), 1)
        self.assertEqual(wide[0]["standard_a__mean"], 1.0)
        self.assertEqual(wide[0]["standard_b__mean"], 2.0)
        self.assertEqual(wide[0]["status"], "ok")

    def test_payload_write_and_load_round_trip(self) -> None:
        payload = build_result_payload(
            run_id="run-001",
            rows=[result_row(value=None, status="error")],
            errors=[{"roi_id": "segment-1", "message": "empty mask"}],
        )
        with tempfile.TemporaryDirectory() as directory:
            path = write_result_payload(
                Path(directory, "nested", "result.json"), payload
            )
            loaded = load_result_payload(path)

        self.assertEqual(loaded, payload)

    def test_export_rejects_unknown_extension(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "csv.*json"):
                export_rows([result_row()], Path(directory, "results.txt"))


if __name__ == "__main__":
    unittest.main()
