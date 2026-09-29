from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "PictologicsSlicer"))

from PictologicsLib.batch import BatchCase, find_cases


class FindCasesTests(unittest.TestCase):
    def test_each_subfolder_with_one_image_and_segmentation_is_a_case(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            layout = {
                "case-2": ["image.nii.gz", "segmentation.seg.nrrd"],
                "case-1": ["image.nii.gz", "lesion.nii.gz", "notes.txt"],
                "no-image": ["segmentation.seg.nrrd"],
                "two-masks": ["image.nii.gz", "a.nii.gz", "b.nii.gz"],
                ".hidden": ["image.nii.gz"],
            }
            for name, files in layout.items():
                (root / name).mkdir()
                for file_name in files:
                    (root / name / file_name).touch()
            (root / "loose.nii.gz").touch()

            cases, skipped = find_cases(root, "image.nii.gz", "*.nii.gz")
            self.assertEqual([case.name for case in cases], ["case-1"])
            self.assertEqual(cases[0].segmentation, root / "case-1" / "lesion.nii.gz")
            self.assertEqual(skipped[0], "case-2: 0 files match '*.nii.gz'")
            self.assertEqual(len(skipped), 3)

            cases, skipped = find_cases(root, "image.nii.gz", "")
            self.assertEqual(
                cases[:2],
                [
                    BatchCase("case-1", root / "case-1" / "image.nii.gz", None),
                    BatchCase("case-2", root / "case-2" / "image.nii.gz", None),
                ],
            )
            self.assertEqual(skipped, ["no-image: 0 files match 'image.nii.gz'"])


if __name__ == "__main__":
    unittest.main()
