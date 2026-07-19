"""Branch coverage for the process-marker staging helpers.

The Windows ``OpenProcess`` path in ``process_is_alive`` cannot run on this POSIX CI
and is marked ``# pragma: no cover`` in the source; every other branch is exercised
here, using ``os.kill`` mocks for the deterministic error paths.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "PictologicsSlicer"))

from PictologicsLib import staging  # noqa: E402
from PictologicsLib.staging import process_is_alive, read_pid_marker  # noqa: E402


class ReadPidMarkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.marker = Path(self._tmp.name) / "marker"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_valid_marker_returns_pid(self) -> None:
        self.marker.write_text("pid=1234\n", encoding="utf-8")
        self.assertEqual(read_pid_marker(self.marker), 1234)

    def test_upper_bound_pid_is_valid(self) -> None:
        self.marker.write_text("pid=4294967295", encoding="utf-8")
        self.assertEqual(read_pid_marker(self.marker), 0xFFFFFFFF)

    def test_missing_file_returns_none(self) -> None:
        self.assertIsNone(read_pid_marker(Path(self._tmp.name) / "absent"))

    def test_undecodable_bytes_return_none(self) -> None:
        self.marker.write_bytes(b"\xff\xfe pid=1")
        self.assertIsNone(read_pid_marker(self.marker))

    def test_wrong_prefix_returns_none(self) -> None:
        self.marker.write_text("other=12", encoding="utf-8")
        self.assertIsNone(read_pid_marker(self.marker))

    def test_non_integer_returns_none(self) -> None:
        self.marker.write_text("pid=abc", encoding="utf-8")
        self.assertIsNone(read_pid_marker(self.marker))

    def test_out_of_range_pids_return_none(self) -> None:
        for text in ("pid=0", "pid=-1", "pid=4294967296"):
            self.marker.write_text(text, encoding="utf-8")
            self.assertIsNone(read_pid_marker(self.marker), text)


class ProcessIsAliveTests(unittest.TestCase):
    def test_non_positive_pid_is_not_alive(self) -> None:
        self.assertFalse(process_is_alive(0))
        self.assertFalse(process_is_alive(-1))

    def test_current_process_is_alive(self) -> None:
        self.assertTrue(process_is_alive(os.getpid()))

    def test_live_child_process_is_alive(self) -> None:
        child = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"]
        )
        try:
            self.assertTrue(process_is_alive(child.pid))
        finally:
            child.terminate()
            child.wait()

    def test_process_lookup_error_means_dead(self) -> None:
        with mock.patch.object(staging.os, "kill", side_effect=ProcessLookupError):
            self.assertFalse(process_is_alive(os.getpid() + 1))

    def test_permission_error_means_alive(self) -> None:
        with mock.patch.object(staging.os, "kill", side_effect=PermissionError):
            self.assertTrue(process_is_alive(os.getpid() + 1))

    def test_other_os_error_means_dead(self) -> None:
        with mock.patch.object(staging.os, "kill", side_effect=OSError):
            self.assertFalse(process_is_alive(os.getpid() + 1))


if __name__ == "__main__":
    unittest.main()
