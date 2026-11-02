from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "PictologicsSlicer"))

from PictologicsLib.inline_config import (
    build_inline_configuration_document,
    default_inline_state,
    preset_configuration_document,
)
from PictologicsLib.memory import BYTES_PER_VOXEL, largest_voxel_count, resampled_voxel_count

# A typical CT: 512 x 512 x 300 voxels of 0.7 x 0.7 x 1.0 mm.
CT = ((512, 512, 300), (0.7, 0.7, 1.0))
CT_AT_HALF_MM = 717 * 717 * 600


def resample(spacing: object) -> dict[str, object]:
    return {"step": "resample", "params": {"new_spacing": spacing}}


class ResampledVoxelCountTests(unittest.TestCase):
    def test_counts_round_like_pictologics(self) -> None:
        # 512 x 0.7 / 0.5 = 716.8, which becomes 717 voxels.
        self.assertEqual(resampled_voxel_count((512, 1, 1), (0.7, 1.0, 1.0), (0.5, 1.0, 1.0)), 717)
        # 3 x 0.1 / 0.1 is 3.0000000000000004 in floating point; it stays 3 voxels.
        self.assertEqual(resampled_voxel_count((3, 1, 1), (0.1, 1.0, 1.0), (0.1, 1.0, 1.0)), 3)


class LargestVoxelCountTests(unittest.TestCase):
    def test_presets_resample_the_whole_scan(self) -> None:
        voxels = largest_voxel_count(*CT, [preset_configuration_document("standard_fbn_32")])
        self.assertEqual(voxels, CT_AT_HALF_MM)
        self.assertGreater(voxels * BYTES_PER_VOXEL, 2e9)

    def test_no_resampling_keeps_the_scan_grid(self) -> None:
        state = default_inline_state()
        state["resample"] = False
        document = build_inline_configuration_document(state)
        self.assertEqual(largest_voxel_count(*CT, [document]), 512 * 512 * 300)
        self.assertEqual(largest_voxel_count(*CT, []), 512 * 512 * 300)

    def test_the_finest_spacing_of_all_documents_counts(self) -> None:
        coarse = {"configs": {"coarse": {"steps": [resample([1.0, 1.0, 1.0])]}}}
        fine = {"configs": {"fine": [resample([0.5, 0.5, 0.5])]}}
        self.assertEqual(largest_voxel_count(*CT, [coarse, fine]), CT_AT_HALF_MM)

    def test_invalid_entries_are_skipped(self) -> None:
        document = {
            "configs": {
                "text_steps": {"steps": "resample"},
                "scalar": 5,
                "odd": [
                    "not a step",
                    {"step": "discretise", "params": {"n_bins": 8}},
                    {"step": "resample"},
                    resample(["a", 1, 1]),
                    resample([0.5, 0.5]),
                    resample([0.0, 0.5, 0.5]),
                    resample([float("nan"), 0.5, 0.5]),
                ],
            }
        }
        self.assertEqual(
            largest_voxel_count(*CT, [document, {"configs": []}]), 512 * 512 * 300
        )


if __name__ == "__main__":
    unittest.main()
