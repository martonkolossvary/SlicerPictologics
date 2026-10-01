"""The optional benchmark's fixture and sampling contract, without Slicer."""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

SPEC = importlib.util.spec_from_file_location(
    "workload_support", Path(__file__).resolve().parents[1] / "scripts/workload_support.py"
)
support = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(support)


@patch.object(support.os, "name", "posix")
class WorkloadSupportTests(unittest.TestCase):
    def test_public_sample_checksums_are_pinned(self):
        self.assertEqual(set(support.SAMPLES), {"CTLiver", "MRHead"})
        for sample in support.SAMPLES.values():
            self.assertRegex(sample["sha256"], r"^[a-f0-9]{64}$")
        self.assertIn("CC BY-SA 4.0", support.SAMPLES["CTLiver"]["source"])

    def test_masks_are_two_disjoint_nonempty_deterministic_rois(self):
        for sample in support.SAMPLES:
            with self.subTest(sample=sample):
                masks, centres = support.demonstration_masks((48, 64, 64), (1.4, 1.4, 1.4), sample=sample)
                self.assertEqual(len(masks), 2)
                self.assertEqual(len(centres), 2)
                self.assertFalse(np.any(masks[0] & masks[1]))
                repeated, _ = support.demonstration_masks((48, 64, 64), (1.4, 1.4, 1.4), sample=sample)
                for mask, again in zip(masks, repeated, strict=True):
                    self.assertEqual(mask.dtype, np.uint8)
                    self.assertEqual(mask.shape, (48, 64, 64))
                    self.assertGreater(int(mask.sum()), 8)
                    np.testing.assert_array_equal(mask, again)

    def test_fixture_rejects_invalid_geometry_and_unknown_data(self):
        for shape, spacing in [((16, 16), (1, 1, 1)), ((4, 64, 64), (1, 1, 1)),
                               ((32, 32, 32), (1, 1, 0)), ((32, 32, 32), (1, float("nan"), 1))]:
            with self.subTest(shape=shape, spacing=spacing), self.assertRaises(ValueError):
                support.demonstration_masks(shape, spacing)
        with self.assertRaises(ValueError):
            support.demonstration_masks((32, 32, 32), (1, 1, 1), sample="private-data")

    def test_rss_selects_only_root_descendants_and_excludes_sampler(self):
        text = "12 10 30\n10 1 100\n11 10 20\n13 12 40\n14 1 999\n15 10 200\nbad row\n0 0 4\n20 1 -2"
        self.assertEqual(support.process_tree_rss(text, 10, excluded_pid=15), (100 * 1024, 90 * 1024))
        self.assertEqual(support.process_tree_rss(text, 999), (0, 0))

    def test_rss_parser_handles_process_cycles_without_looping(self):
        self.assertEqual(support.process_tree_rss("10 11 2\n11 10 3", 10), (2048, 3072))

    def test_summary_reports_sampled_not_summed_individual_peaks(self):
        sampler = support.MemorySampler()
        sampler.samples = [(1.0, 100, 50), (1.5, 90, 80)]
        summary = sampler.summary()
        self.assertEqual(summary["peak_tree_rss_bytes"], 170)
        self.assertEqual(summary["peak_gui_rss_bytes"], 100)
        self.assertEqual(summary["peak_descendants_rss_bytes"], 80)
        self.assertEqual(summary["baseline_gui_rss_bytes"], 100)
        self.assertEqual(summary["samples"], 2)

    def test_sampler_rejects_unsupported_platform_bad_interval_and_missing_samples(self):
        with patch.object(support.os, "name", "nt"), self.assertRaises(RuntimeError):
            support.MemorySampler()
        for interval in (0, -1, float("nan")):
            with self.assertRaises(ValueError):
                support.MemorySampler(interval)
        with self.assertRaises(RuntimeError):
            support.MemorySampler().summary()

    def test_sampler_records_subprocess_failure_without_crashing_thread(self):
        sampler = support.MemorySampler()
        with patch.object(support.subprocess, "Popen", side_effect=OSError("not available")), patch.object(
            sampler.stop_event, "is_set", side_effect=[False, True]
        ), patch.object(sampler.stop_event, "wait"):
            sampler._run()
        self.assertEqual(sampler.errors, 1)
        self.assertEqual(sampler.samples, [])


if __name__ == "__main__":
    unittest.main()
