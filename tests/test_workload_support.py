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

    @patch.object(support.os, "name", "posix")
    def test_summary_reports_sampled_not_summed_individual_peaks(self):
        sampler = support.MemorySampler()
        sampler.samples = [(1.0, 100, 50), (1.5, 90, 80)]
        summary = sampler.summary()
        self.assertEqual(summary["peak_tree_rss_bytes"], 170)
        self.assertEqual(summary["peak_gui_rss_bytes"], 100)
        self.assertEqual(summary["peak_descendants_rss_bytes"], 80)
        self.assertEqual(summary["baseline_gui_rss_bytes"], 100)
        self.assertEqual(summary["samples"], 2)

    @patch.object(support.os, "name", "posix")
    def test_sampler_rejects_unsupported_platform_bad_interval_and_missing_samples(self):
        with patch.object(support.os, "name", "unsupported"), self.assertRaises(RuntimeError):
            support.MemorySampler()
        for interval in (0, -1, float("nan")):
            with self.assertRaises(ValueError):
                support.MemorySampler(interval)
        with self.assertRaises(RuntimeError):
            support.MemorySampler().summary()

    @patch.object(support.os, "name", "posix")
    def test_sampler_records_subprocess_failure_without_crashing_thread(self):
        sampler = support.MemorySampler()
        with patch.object(support.subprocess, "Popen", side_effect=OSError("not available")), patch.object(
            sampler.stop_event, "wait", side_effect=[False, True]
        ):
            sampler._run()
        self.assertEqual(sampler.errors, 1)
        self.assertEqual(sampler.samples, [])

class WindowsMemoryContractTests(unittest.TestCase):
    def fake_sampler(self, *, failure=None):
        import ctypes
        from types import SimpleNamespace
        from unittest.mock import Mock

        sampler = support.WindowsMemory.__new__(support.WindowsMemory)
        records = iter([(99, 1), (11, 10), (10, 1), (12, 11), (42, 1)])
        error = [18]
        opened, closed = [], []

        def next_entry(handle, entry):
            try:
                entry.pid, entry.parent = next(records)
                return True
            except StopIteration:
                return False

        def open_process(access, inherit, pid):
            opened.append(pid)
            if failure == 'open' and pid == 11:
                error[0] = 5
                return None
            return pid

        def get_memory(handle, counters, size):
            if failure == 'counters' and handle == 11:
                error[0] = 5
                return False
            counters.working_set = handle * 1024
            return True

        sampler.ctypes = SimpleNamespace(
            c_void_p=ctypes.c_void_p, byref=lambda obj: obj, sizeof=lambda obj: 80,
            get_last_error=lambda: error[0], WinError=lambda code: OSError(code, 'synthetic'),
        )
        sampler.Entry = SimpleNamespace
        sampler.Counters = SimpleNamespace
        sampler.api = SimpleNamespace(
            CreateToolhelp32Snapshot=Mock(return_value=500), Process32FirstW=next_entry,
            Process32NextW=next_entry, OpenProcess=open_process,
            K32GetProcessMemoryInfo=get_memory, CloseHandle=closed.append,
        )
        return sampler, opened, closed, error

    def test_windows_selects_owned_tree_in_bytes_and_closes_every_handle(self):
        sampler, opened, closed, _ = self.fake_sampler()
        self.assertEqual(sampler.sample(10), (10240, 23552))
        self.assertEqual(set(opened), {10, 11, 12})
        self.assertEqual(set(closed), {500, 10, 11, 12})

    def test_windows_access_or_counter_failure_invalidates_whole_sample(self):
        for failure in ('open', 'counters'):
            with self.subTest(failure=failure):
                sampler, opened, closed, _ = self.fake_sampler(failure=failure)
                with self.assertRaises(OSError):
                    sampler.sample(10)
                self.assertIn(500, closed)
                self.assertIn(11, opened)
                if failure == 'counters':
                    self.assertIn(11, closed)

    def test_windows_snapshot_and_enumeration_failure_are_not_zero_memory(self):
        import ctypes
        from unittest.mock import Mock
        for failure in ('snapshot', 'first', 'next', 'missing_root'):
            sampler, _, closed, error = self.fake_sampler()
            error[0] = 5
            if failure == 'snapshot':
                sampler.api.CreateToolhelp32Snapshot.return_value = ctypes.c_void_p(-1).value
            elif failure == 'first':
                sampler.api.Process32FirstW = Mock(return_value=False)
            elif failure == 'missing_root':
                error[0] = 18
            with self.subTest(failure=failure), self.assertRaises((OSError, RuntimeError)):
                sampler.sample(404 if failure == 'missing_root' else 10)
            if failure != 'snapshot':
                self.assertIn(500, closed)

    @patch.object(support.os, 'name', 'posix')
    def test_memory_guard_rejects_missing_stale_and_zero_samples(self):
        from unittest.mock import Mock
        sampler = support.MemorySampler()
        with self.assertRaises(RuntimeError):
            sampler.ensure_recent()
        sampler.samples = [(0, 1234, 0)]
        with self.assertRaises(RuntimeError):
            sampler.ensure_recent()
        sampler.windows = Mock()
        sampler.windows.sample.return_value = (0, 0)
        with self.assertRaises(RuntimeError):
            sampler._sample()
        sampler.windows.sample.return_value = (1234, 5678)
        sampler._sample()
        sampler.ensure_recent()
        self.assertEqual(sampler.samples[-1][1:], (1234, 5678))


if __name__ == "__main__":
    unittest.main()
