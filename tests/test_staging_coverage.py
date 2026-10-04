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
from PictologicsLib.staging import (  # noqa: E402
    job_may_be_running,
    process_is_alive,
    read_pid_marker,
)


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

    @mock.patch.object(staging.os, "name", "posix")
    def test_process_lookup_error_means_dead(self) -> None:
        with mock.patch.object(staging.os, "kill", side_effect=ProcessLookupError):
            self.assertFalse(process_is_alive(os.getpid() + 1))

    @mock.patch.object(staging.os, "name", "posix")
    def test_permission_error_means_alive(self) -> None:
        with mock.patch.object(staging.os, "kill", side_effect=PermissionError):
            self.assertTrue(process_is_alive(os.getpid() + 1))

    @mock.patch.object(staging.os, "name", "posix")
    def test_other_os_error_means_dead(self) -> None:
        with mock.patch.object(staging.os, "kill", side_effect=OSError):
            self.assertFalse(process_is_alive(os.getpid() + 1))


class JobMayBeRunningTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.jobs = Path(self._tmp.name) / "jobs"
        self.jobs.mkdir()

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _job(self, marker: str | None, content: str = "") -> Path:
        job = Path(tempfile.mkdtemp(prefix="job-", dir=self.jobs))
        if marker is not None:
            (job / marker).write_text(content, encoding="utf-8")
        return job

    def test_missing_folder_means_no_job(self) -> None:
        self.assertFalse(job_may_be_running(self.jobs / "missing"))

    def test_unreadable_folder_counts_as_a_running_job(self) -> None:
        not_a_folder = Path(self._tmp.name) / "file"
        not_a_folder.write_text("", encoding="utf-8")
        self.assertTrue(job_may_be_running(not_a_folder))

    def test_only_live_or_unreadable_markers_count(self) -> None:
        self._job(None)
        self._job(".worker-active", "pid=1234")
        (self.jobs / "other").mkdir()
        (self.jobs / "job-file").write_text("", encoding="utf-8")
        with mock.patch.object(staging, "process_is_alive", return_value=False):
            self.assertFalse(job_may_be_running(self.jobs))
            self._job(".owner-active", "broken")
            self.assertTrue(job_may_be_running(self.jobs))

    def test_live_process_counts(self) -> None:
        self._job(".owner-active", f"pid={os.getpid()}")
        self.assertTrue(job_may_be_running(self.jobs))

    def test_symbolic_link_job_is_ignored(self) -> None:
        target = self._job(".owner-active", f"pid={os.getpid()}")
        link = self.jobs / "job-link"
        target.rename(Path(self._tmp.name) / "outside")
        try:
            link.symlink_to(Path(self._tmp.name) / "outside", target_is_directory=True)
        except OSError as exc:  # pragma: no cover - platform permission policy
            self.skipTest(f"Symbolic links are unavailable: {exc}")
        self.assertFalse(job_may_be_running(self.jobs))


if __name__ == "__main__":
    unittest.main()
