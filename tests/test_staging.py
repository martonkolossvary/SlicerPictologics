from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "PictologicsSlicer"))

from PictologicsLib.staging import process_is_alive, read_pid_marker  # noqa: E402


class StagingMarkerTests(unittest.TestCase):
    def test_reads_only_positive_pid_markers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "marker"
            marker.write_text(f"pid={os.getpid()}\n", encoding="utf-8")
            self.assertEqual(read_pid_marker(marker), os.getpid())
            for text in (
                "",
                "pid=0",
                "pid=-1",
                "pid=abc",
                "pid=999999999999999999999999999999999999",
                "other=12",
            ):
                marker.write_text(text, encoding="utf-8")
                self.assertIsNone(read_pid_marker(marker))

    def test_missing_marker_is_invalid(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(read_pid_marker(Path(directory) / "missing"))

    def test_current_process_is_alive_and_invalid_pids_are_not(self) -> None:
        self.assertTrue(process_is_alive(os.getpid()))
        self.assertFalse(process_is_alive(0))
        self.assertFalse(process_is_alive(-1))


if __name__ == "__main__":
    unittest.main()
