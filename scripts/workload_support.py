"""Reproducible public-data fixtures and bounded, POSIX-only RSS sampling.

Development tooling, not packaged runtime. No extra Python dependencies beyond
NumPy (already in Slicer). Memory figures are sampled resident sets, not exact
peaks or unique physical RAM; shared pages can be counted more than once.
"""

from __future__ import annotations

import math
import os
import subprocess
import threading
import time

import numpy as np

SAMPLES = {
    "MRHead": {"filename": "MR-head.nrrd", "sha256": "cc211f0dfd9a05ca3841ce1141b292898b2dd2d3f08286affadf823a7e58df93",
               "source": "3D Slicer MRHead sample; donated for unrestricted use"},
    "CTLiver": {"filename": "CTLiver.nrrd", "sha256": "e16eae0ae6fefa858c5c11e58f0f1bb81834d81b7102e021571056324ef6f37e",
                "source": "Medical Segmentation Decathlon Task03_Liver, imagesTr/liver_100.nii.gz via 3D Slicer; CC BY-SA 4.0"},
}


def demonstration_masks(shape_kji, spacing_ijk, *, sample="CTLiver"):
    """Two disjoint physical ellipsoids, not organ or disease annotations."""
    if len(shape_kji) != 3 or min(shape_kji) < 16 or len(spacing_ijk) != 3 or any(
        not math.isfinite(value) or value <= 0 for value in spacing_ijk
    ):
        raise ValueError("Expected a nontrivial 3D image and positive spacing.")
    if sample not in SAMPLES:
        raise ValueError("Only the documented public samples are supported.")
    k, j, i = np.ogrid[tuple(slice(size) for size in shape_kji)]
    centres = []
    masks = []
    for fraction in (0.38, 0.62):
        centre = np.array([(shape_kji[2] - 1) * fraction, (shape_kji[1] - 1) * 0.50,
                           (shape_kji[0] - 1) * (0.55 if sample == "CTLiver" else 0.70)])
        # Scale the ellipsoids for very small/resampled fixtures, keeping them apart.
        extent = np.array(shape_kji[::-1]) * np.array(spacing_ijk)
        radii = np.minimum([15.0, 20.0, 15.0], extent * [0.08, 0.12, 0.12])
        mask = sum(((axis - c) * spacing / radius) ** 2 for axis, c, spacing, radius in
                   zip((i, j, k), centre, spacing_ijk, radii, strict=True)) < 1
        if np.count_nonzero(mask) < 8:
            raise ValueError("Demonstration ROI has too few voxels.")
        centres.append(centre.tolist())
        masks.append(mask.astype(np.uint8))
    if np.any(masks[0] & masks[1]):
        raise ValueError("Demonstration ROIs must not overlap.")
    return masks, centres


def process_tree_rss(text, root_pid, *, excluded_pid=None):
    """Parse only numeric pid/ppid/rss columns; never read command lines."""
    processes = {}
    for line in text.splitlines():
        try:
            pid, parent, rss_kib = map(int, line.split())
        except ValueError:
            continue
        if pid > 0 and rss_kib >= 0 and pid != excluded_pid:
            processes[pid] = (parent, rss_kib * 1024)
    selected = {root_pid}
    while True:
        children = {pid for pid, (parent, _) in processes.items() if parent in selected}
        if children <= selected:
            break
        selected.update(children)
    root = processes.get(root_pid, (0, 0))[1]
    descendants = sum(processes[pid][1] for pid in selected - {root_pid} if pid in processes)
    return root, descendants


class MemorySampler:
    """Sample this Slicer and descendants every 0.5s, including during blocking work."""

    def __init__(self, interval=0.5):
        if os.name != "posix":
            raise RuntimeError("RSS sampling currently requires macOS or Linux ps.")
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("Sampling interval must be finite and positive.")
        self.interval = interval
        self.stop_event = threading.Event()
        self.samples = []
        self.errors = 0
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        while not self.stop_event.is_set():
            try:
                with subprocess.Popen(["ps", "-axo", "pid=,ppid=,rss="], stdin=subprocess.DEVNULL,
                                      stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True) as process:
                    try:
                        output, _ = process.communicate(timeout=2)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.communicate()
                        raise RuntimeError("Memory sampler ps timed out") from None
                    if process.returncode:
                        raise RuntimeError("Memory sampler ps failed")
                    root, children = process_tree_rss(output, os.getpid(), excluded_pid=process.pid)
                self.samples.append((time.perf_counter(), root, children))
            except (OSError, RuntimeError):
                self.errors += 1
            self.stop_event.wait(self.interval)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop_event.set()
        self.thread.join(timeout=5)

    def summary(self):
        if not self.samples:
            raise RuntimeError("No RSS samples captured; memory qualification is unavailable.")
        return {"sample_interval_seconds": self.interval, "samples": len(self.samples),
                "sample_errors": self.errors, "baseline_gui_rss_bytes": self.samples[0][1],
                "peak_gui_rss_bytes": max(row[1] for row in self.samples),
                "peak_descendants_rss_bytes": max(row[2] for row in self.samples),
                "peak_tree_rss_bytes": max(row[1] + row[2] for row in self.samples)}
