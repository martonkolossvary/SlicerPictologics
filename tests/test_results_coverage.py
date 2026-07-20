from __future__ import annotations

import csv
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "PictologicsSlicer"))

import PictologicsLib.results as results
from PictologicsLib.results import (
    LONG_RESULT_COLUMNS,
    ResultPayloadError,
    build_result_payload,
    export_rows,
    export_rows_csv,
    export_rows_json,
    load_result_payload,
    normalise_result_row,
    rows_to_wide,
    validate_result_payload,
    validate_result_rows,
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
        "feature_key": "mean_Q4LE",
        "ibsi_code": "Q4LE",
        "pictologics_ibsi_code": "Q4LE",
        "pictologics_feature_name": "standard_fbn_32__mean_Q4LE",
        "preprocessing_sequence": "1:resample > 2:discretise",
        "value": 42.5,
        "status": "ok",
        "pictologics_version": "0.5.0",
        "extension_version": "0.1.0",
    }
    row.update(changes)
    if "feature_key" not in changes and "feature_name" in changes:
        row["feature_key"] = (
            f"{row['feature_name']}_{row['pictologics_ibsi_code']}"
        )
    if "pictologics_feature_name" not in changes:
        row["pictologics_feature_name"] = (
            f"{row['configuration']}__{row['feature_key']}"
        )
    return row


class NormaliseValueTests(unittest.TestCase):
    def test_none_returns_none(self) -> None:
        self.assertIsNone(results._normalise_value(None, "field"))

    def test_bool_is_rejected(self) -> None:
        with self.assertRaisesRegex(ResultPayloadError, "real number or null"):
            results._normalise_value(True, "field")

    def test_non_real_is_rejected(self) -> None:
        with self.assertRaisesRegex(ResultPayloadError, "real number or null"):
            results._normalise_value("not-a-number", "field")

    def test_integral_becomes_int(self) -> None:
        value = results._normalise_value(7, "field")
        self.assertIsInstance(value, int)
        self.assertEqual(value, 7)

    def test_infinite_is_rejected(self) -> None:
        with self.assertRaisesRegex(ResultPayloadError, "must not be infinite"):
            results._normalise_value(float("inf"), "field")

    def test_nan_is_kept(self) -> None:
        value = results._normalise_value(float("nan"), "field")
        self.assertTrue(math.isnan(value))


class NormaliseResultRowTests(unittest.TestCase):
    def test_non_mapping_row_uses_row_location_when_index_is_none(self) -> None:
        with self.assertRaisesRegex(ResultPayloadError, r"^row must be an object$"):
            normalise_result_row(["not", "a", "mapping"])

    def test_non_mapping_row_uses_indexed_location(self) -> None:
        with self.assertRaisesRegex(ResultPayloadError, r"^rows\[3\] must be an object$"):
            normalise_result_row(123, index=3)

    def test_missing_columns_are_rejected(self) -> None:
        row = result_row()
        del row["feature_name"]
        with self.assertRaisesRegex(ResultPayloadError, "missing required columns"):
            normalise_result_row(row)

    def test_unknown_columns_are_rejected(self) -> None:
        with self.assertRaisesRegex(ResultPayloadError, "unknown columns"):
            normalise_result_row(result_row(surprise="x"))

    def test_non_string_non_value_field_is_rejected(self) -> None:
        with self.assertRaisesRegex(ResultPayloadError, r"subject_id must be a string"):
            normalise_result_row(result_row(subject_id=123))

    def test_each_empty_required_field_raises(self) -> None:
        cases = {
            "run_id": "run_id must not be empty",
            "timestamp": "timestamp must not be empty",
            "roi_id": "roi_id must not be empty",
            "configuration": "configuration must not be empty",
            "feature_name": "feature_name must not be empty",
            "feature_key": "feature_key must not be empty",
            "pictologics_feature_name": "pictologics_feature_name must not be empty",
            "status": "status must not be empty",
        }
        for field, message in cases.items():
            with self.subTest(field=field):
                with self.assertRaisesRegex(ResultPayloadError, message):
                    normalise_result_row(result_row(**{field: ""}))

    def test_expected_run_id_mismatch_is_rejected(self) -> None:
        with self.assertRaisesRegex(ResultPayloadError, "does not match payload run_id"):
            normalise_result_row(result_row(), expected_run_id="other-run")

    def test_valid_row_is_returned_in_canonical_order(self) -> None:
        normalised = normalise_result_row(result_row(value=7), index=0)
        self.assertEqual(tuple(normalised), LONG_RESULT_COLUMNS)
        self.assertEqual(normalised["value"], 7)


class ValidateResultRowsTests(unittest.TestCase):
    def test_non_iterable_is_rejected(self) -> None:
        with self.assertRaisesRegex(ResultPayloadError, "must be an iterable"):
            validate_result_rows(123)

    def test_string_is_rejected(self) -> None:
        with self.assertRaisesRegex(ResultPayloadError, "must be an iterable"):
            validate_result_rows("rows")

    def test_bytes_is_rejected(self) -> None:
        with self.assertRaisesRegex(ResultPayloadError, "must be an iterable"):
            validate_result_rows(b"rows")

    def test_mapping_is_rejected(self) -> None:
        with self.assertRaisesRegex(ResultPayloadError, "must be an iterable"):
            validate_result_rows({"run_id": "run-001"})

    def test_valid_rows_are_normalised(self) -> None:
        rows = validate_result_rows([result_row()])
        self.assertEqual(len(rows), 1)


class StrictJsonCloneTests(unittest.TestCase):
    def test_non_finite_value_is_rejected(self) -> None:
        with self.assertRaisesRegex(ResultPayloadError, "strict JSON values"):
            results._strict_json_clone({"x": float("nan")}, "provenance")

    def test_valid_value_is_cloned(self) -> None:
        self.assertEqual(
            results._strict_json_clone({"x": [1, 2]}, "provenance"), {"x": [1, 2]}
        )


class ValidatePayloadTests(unittest.TestCase):
    def test_non_mapping_payload_is_rejected(self) -> None:
        with self.assertRaisesRegex(ResultPayloadError, "must be an object"):
            validate_result_payload(["not", "a", "mapping"])

    def test_missing_and_unknown_keys_are_reported_together(self) -> None:
        with self.assertRaisesRegex(
            ResultPayloadError, "missing keys.*unknown keys"
        ):
            validate_result_payload({"surprise": 1})

    def test_missing_keys_only(self) -> None:
        with self.assertRaisesRegex(ResultPayloadError, "missing keys"):
            validate_result_payload({"schema_version": 1})

    def test_schema_version_bool_is_rejected(self) -> None:
        with self.assertRaisesRegex(ResultPayloadError, "Unsupported schema_version"):
            validate_result_payload(
                {"schema_version": True, "run_id": "run-001", "rows": []}
            )

    def test_schema_version_wrong_number_is_rejected(self) -> None:
        with self.assertRaisesRegex(ResultPayloadError, "Unsupported schema_version"):
            validate_result_payload(
                {"schema_version": 2, "run_id": "run-001", "rows": []}
            )

    def test_run_id_must_be_a_non_empty_string(self) -> None:
        with self.assertRaisesRegex(ResultPayloadError, "run_id must be a non-empty"):
            validate_result_payload(
                {"schema_version": 1, "run_id": 123, "rows": []}
            )
        with self.assertRaisesRegex(ResultPayloadError, "run_id must be a non-empty"):
            validate_result_payload(
                {"schema_version": 1, "run_id": "", "rows": []}
            )

    def test_provenance_must_be_a_mapping(self) -> None:
        with self.assertRaisesRegex(ResultPayloadError, "provenance must be an object"):
            validate_result_payload(
                {
                    "schema_version": 1,
                    "run_id": "run-001",
                    "rows": [],
                    "provenance": ["not", "a", "mapping"],
                }
            )

    def test_provenance_mapping_is_cloned(self) -> None:
        normalised = validate_result_payload(
            {
                "schema_version": 1,
                "run_id": "run-001",
                "rows": [],
                "provenance": {"configuration_sha256": "abc"},
            }
        )
        self.assertEqual(normalised["provenance"], {"configuration_sha256": "abc"})

    def test_errors_must_be_a_sequence_of_objects(self) -> None:
        with self.assertRaisesRegex(ResultPayloadError, "errors must be an array"):
            validate_result_payload(
                {
                    "schema_version": 1,
                    "run_id": "run-001",
                    "rows": [],
                    "errors": 123,
                }
            )

    def test_errors_string_is_rejected(self) -> None:
        with self.assertRaisesRegex(ResultPayloadError, "errors must be an array"):
            validate_result_payload(
                {
                    "schema_version": 1,
                    "run_id": "run-001",
                    "rows": [],
                    "errors": "boom",
                }
            )

    def test_error_element_must_be_a_mapping(self) -> None:
        with self.assertRaisesRegex(ResultPayloadError, r"errors\[0\] must be an object"):
            validate_result_payload(
                {
                    "schema_version": 1,
                    "run_id": "run-001",
                    "rows": [],
                    "errors": [123],
                }
            )

    def test_error_mapping_is_cloned(self) -> None:
        normalised = validate_result_payload(
            {
                "schema_version": 1,
                "run_id": "run-001",
                "rows": [],
                "errors": [{"message": "empty mask"}],
            }
        )
        self.assertEqual(normalised["errors"], [{"message": "empty mask"}])


class BuildPayloadTests(unittest.TestCase):
    def test_build_with_provenance_and_errors(self) -> None:
        payload = build_result_payload(
            run_id="run-001",
            rows=[result_row()],
            provenance={"configuration_sha256": "abc"},
            errors=[{"message": "note"}],
        )
        self.assertEqual(payload["provenance"], {"configuration_sha256": "abc"})
        self.assertEqual(payload["errors"], [{"message": "note"}])

    def test_build_without_optional_fields(self) -> None:
        payload = build_result_payload(run_id="run-001", rows=[result_row()])
        self.assertNotIn("provenance", payload)
        self.assertNotIn("errors", payload)


class JsonSafeTests(unittest.TestCase):
    def test_non_finite_float_becomes_none(self) -> None:
        self.assertIsNone(results._json_safe(float("inf")))
        self.assertIsNone(results._json_safe(float("nan")))

    def test_finite_float_passes_through(self) -> None:
        self.assertEqual(results._json_safe(1.5), 1.5)

    def test_mapping_is_recursed(self) -> None:
        self.assertEqual(
            results._json_safe({1: float("nan"), "b": 2}), {"1": None, "b": 2}
        )

    def test_list_and_tuple_are_recursed(self) -> None:
        self.assertEqual(results._json_safe([1, (2, 3)]), [1, [2, 3]])

    def test_other_values_pass_through(self) -> None:
        self.assertEqual(results._json_safe("text"), "text")


class RowsToWideTests(unittest.TestCase):
    def test_grouping_produces_feature_columns(self) -> None:
        rows = [
            result_row(configuration="std_a", feature_name="mean", value=1.0),
            result_row(configuration="std_b", feature_name="mean", value=2.0),
        ]
        wide = rows_to_wide(rows)
        self.assertEqual(len(wide), 1)
        self.assertEqual(wide[0]["std_a__mean_Q4LE"], 1.0)
        self.assertEqual(wide[0]["std_b__mean_Q4LE"], 2.0)
        self.assertEqual(wide[0]["status"], "ok")

    def test_multiple_statuses_are_joined(self) -> None:
        rows = [
            result_row(feature_name="mean", value=1.0, status="ok"),
            result_row(feature_name="max", value=2.0, status="error"),
        ]
        wide = rows_to_wide(rows)
        self.assertEqual(len(wide), 1)
        self.assertEqual(wide[0]["status"], "ok;error")

    def test_collision_is_rejected(self) -> None:
        rows = [
            result_row(configuration="std_a", feature_name="mean", value=1.0),
            result_row(configuration="std_a", feature_name="mean", value=2.0),
        ]
        with self.assertRaisesRegex(ResultPayloadError, "Wide export collision"):
            rows_to_wide(rows)


class FsyncParentDirTests(unittest.TestCase):
    def test_success_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            # Should not raise when the parent directory exists.
            results._fsync_parent_dir(Path(directory, "file.txt"))

    def test_open_oserror_returns_early(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(results.os, "open", side_effect=OSError("boom")):
                results._fsync_parent_dir(Path(directory, "file.txt"))

    def test_fsync_oserror_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(results.os, "fsync", side_effect=OSError("boom")):
                results._fsync_parent_dir(Path(directory, "file.txt"))


class ExportCsvTests(unittest.TestCase):
    def test_long_export(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = export_rows_csv([result_row()], Path(directory, "long.csv"))
            with destination.open("r", encoding="utf-8", newline="") as stream:
                exported = list(csv.DictReader(stream))
        self.assertEqual(tuple(exported[0]), LONG_RESULT_COLUMNS)

    def test_wide_export(self) -> None:
        rows = [
            result_row(configuration="std_a", feature_name="mean", value=1.0),
            result_row(configuration="std_b", feature_name="glcm", value=2.0),
        ]
        with tempfile.TemporaryDirectory() as directory:
            destination = export_rows_csv(rows, Path(directory, "wide.csv"), wide=True)
            with destination.open("r", encoding="utf-8", newline="") as stream:
                exported = list(csv.DictReader(stream))
        self.assertEqual(len(exported), 1)
        self.assertEqual(exported[0]["std_a__mean_Q4LE"], "1.0")
        self.assertEqual(exported[0]["std_b__glcm_Q4LE"], "2.0")

    def test_unlink_oserror_in_finally_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(Path, "unlink", side_effect=OSError("boom")):
                destination = export_rows_csv(
                    [result_row()], Path(directory, "guard.csv")
                )
            self.assertTrue(destination.exists())


class ExportJsonTests(unittest.TestCase):
    def test_long_export(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = export_rows_json([result_row()], Path(directory, "long.json"))
            exported = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(exported[0]["value"], 42.5)

    def test_wide_export(self) -> None:
        rows = [
            result_row(configuration="std_a", feature_name="mean", value=1.0),
            result_row(configuration="std_b", feature_name="glcm", value=2.0),
        ]
        with tempfile.TemporaryDirectory() as directory:
            destination = export_rows_json(rows, Path(directory, "wide.json"), wide=True)
            exported = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(len(exported), 1)
        self.assertEqual(exported[0]["std_a__mean_Q4LE"], 1.0)

    def test_unlink_oserror_in_finally_is_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(Path, "unlink", side_effect=OSError("boom")):
                destination = export_rows_json(
                    [result_row()], Path(directory, "guard.json")
                )
            self.assertTrue(destination.exists())


class ExportRowsDispatchTests(unittest.TestCase):
    def test_csv_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = export_rows([result_row()], Path(directory, "out.csv"))
        self.assertEqual(destination.suffix, ".csv")

    def test_json_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            destination = export_rows(
                [result_row()], Path(directory, "out.dat"), format="json"
            )
        self.assertEqual(destination.suffix, ".dat")

    def test_unknown_format_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "csv.*json"):
                export_rows([result_row()], Path(directory, "out.txt"))


class PayloadFileTests(unittest.TestCase):
    def test_write_and_load_round_trip(self) -> None:
        payload = build_result_payload(
            run_id="run-001",
            rows=[result_row(value=None, status="error")],
            errors=[{"roi_id": "segment-1", "message": "empty mask"}],
        )
        with tempfile.TemporaryDirectory() as directory:
            path = write_result_payload(Path(directory, "nested", "result.json"), payload)
            loaded = load_result_payload(path)
        self.assertEqual(loaded, payload)

    def test_write_unlink_oserror_in_finally_is_ignored(self) -> None:
        payload = build_result_payload(run_id="run-001", rows=[result_row()])
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(Path, "unlink", side_effect=OSError("boom")):
                destination = write_result_payload(
                    Path(directory, "guard.json"), payload
                )
            self.assertTrue(destination.exists())

    def test_load_missing_file_raises(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ResultPayloadError, "Unable to read"):
                load_result_payload(Path(directory, "missing.json"))

    def test_load_invalid_json_raises(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            bad = Path(directory, "bad.json")
            bad.write_text("{not valid json", encoding="utf-8")
            with self.assertRaisesRegex(ResultPayloadError, "Unable to read"):
                load_result_payload(bad)


if __name__ == "__main__":
    unittest.main()
