from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "PictologicsSlicer"))

from PictologicsLib.result_columns import (
    SCANNER_COLUMNS,
    build_result_columns,
    check_extra_columns,
    parse_extra_columns,
    scanner_details_from_sidecar,
    scanner_value,
    sidecar_path,
)


class ScannerDetailTests(unittest.TestCase):
    def test_values_become_text(self) -> None:
        self.assertEqual(scanner_value(None), "")
        self.assertEqual(scanner_value(" SIEMENS "), "SIEMENS")
        self.assertEqual(scanner_value(1.25), "1.25")
        self.assertEqual(scanner_value(["Br40", 3]), "Br40\\3")

    def test_dcm2niix_file_gives_every_scanner_column(self) -> None:
        details = scanner_details_from_sidecar(
            {"Modality": "CT", "ManufacturersModelName": "SOMATOM Force", "SliceThickness": 1}
        )
        self.assertEqual(list(details), [column for column, _, _ in SCANNER_COLUMNS])
        self.assertEqual(
            (details["modality"], details["manufacturer_model_name"], details["slice_thickness"]),
            ("CT", "SOMATOM Force", "1"),
        )
        self.assertEqual(details["manufacturer"], "")

    def test_sidecar_is_next_to_a_nifti_image_only(self) -> None:
        self.assertEqual(sidecar_path("/data/case/image.nii.gz"), Path("/data/case/image.json"))
        self.assertEqual(sidecar_path("/data/case/IMAGE.NII"), Path("/data/case/IMAGE.json"))
        self.assertIsNone(sidecar_path("/data/case/image.nrrd"))


class ExtraColumnTests(unittest.TestCase):
    def test_lines_give_ordered_pairs(self) -> None:
        self.assertEqual(
            parse_extra_columns("center = A\n\n  phase=arterial  \nnote = a = b\n"),
            [("center", "A"), ("phase", "arterial"), ("note", "a = b")],
        )

    def test_bad_lines_and_names_are_refused(self) -> None:
        cases = {
            "center": "line 1: write name = value",
            "reader = R2": "Reader field",
            "two__parts = x": "cannot be a column name",
            "value = 1": "cannot be a column name",
            "center = A\ncenter = B": "more than once",
        }
        for text, message in cases.items():
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, message):
                parse_extra_columns(text)
        with self.assertRaisesRegex(ValueError, "must be text"):
            check_extra_columns([("center", 1)])  # type: ignore[list-item]

    def test_reader_then_scanner_then_user_columns(self) -> None:
        columns = build_result_columns(
            " R1 ", {"modality": "CT", "kvp": "120"}, [("center", "A"), ("kvp", "100")]
        )
        names = [name for name, _ in columns]
        self.assertEqual(names[0], "reader")
        self.assertEqual(names[1 : 1 + len(SCANNER_COLUMNS)], [column for column, _, _ in SCANNER_COLUMNS])
        self.assertEqual(names[-1], "center")
        values = dict(columns)
        self.assertEqual((values["reader"], values["modality"], values["kvp"]), ("R1", "CT", "100"))
        self.assertEqual(values["manufacturer"], "")


if __name__ == "__main__":
    unittest.main()
