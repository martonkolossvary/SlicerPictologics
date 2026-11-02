from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "PictologicsSlicer"))

from PictologicsLib.progress import ROI_PROGRESS_PREFIX, current_roi_index, elapsed_text
from test_extension_contracts import load_worker_module


class ElapsedTextTests(unittest.TestCase):
    def test_elapsed_text(self) -> None:
        for seconds, expected in (
            (-1, "00:00:00"),
            (0, "00:00:00"),
            (59.9, "00:00:59"),
            (60, "00:01:00"),
            (3661, "01:01:01"),
            (360000, "100:00:00"),
        ):
            with self.subTest(seconds=seconds):
                self.assertEqual(elapsed_text(seconds), f"Elapsed: {expected}")


class RoiMarkerTests(unittest.TestCase):
    def test_invalid_markers_do_not_replace_last_known_roi(self) -> None:
        previous = ROI_PROGRESS_PREFIX + json.dumps({"index": 0, "total": 2})
        for marker in (
            "{",
            "[]",
            "null",
            "{}",
            '{"index":true,"total":2}',
            '{"index":0,"total":true}',
            '{"index":0,"total":3}',
            '{"index":-1,"total":2}',
            '{"index":2,"total":2}',
            '{"index":0.0,"total":2}',
            '{"index":0,"total":2.0}',
        ):
            with self.subTest(marker=marker):
                self.assertEqual(
                    current_roi_index(previous + "\n" + ROI_PROGRESS_PREFIX + marker, 2), 0
                )
                self.assertIsNone(current_roi_index(ROI_PROGRESS_PREFIX + marker, 2))

    def test_unrelated_output_and_empty_jobs(self) -> None:
        self.assertIsNone(
            current_roi_index("normal logging\n<filter-progress>0.5</filter-progress>", 2)
        )
        self.assertIsNone(current_roi_index(ROI_PROGRESS_PREFIX + '{"index":0,"total":0}', 0))

    def test_worker_markers_are_readable_and_keep_sem_feedback(self) -> None:
        worker = load_worker_module()
        stream = io.StringIO()
        reporter = worker.ProgressReporter(stream)
        roi = worker.ROIManifest(
            roi_id="example", roi_name="A < B", roi_source="segment", mask_path=None, metadata={}
        )
        reporter.roi_started(0, 150, roi)
        reporter.roi_started(1, 150, roi)
        self.assertEqual(current_roi_index(stream.getvalue(), 150), 1)
        self.assertIn("Processing ROI 2 of 150: A &lt; B", stream.getvalue())
        self.assertIn("<filter-progress>", stream.getvalue())


if __name__ == "__main__":
    unittest.main()
