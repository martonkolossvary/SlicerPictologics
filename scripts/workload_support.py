"""Reproducible public-data fixtures and bounded process-tree memory sampling.

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


class WindowsMemory:
    """Read current WorkingSetSize with Toolhelp/PSAPI; no helper process/packages.

    Only the root and snapshot descendants are queried for counters. No command
    lines, paths or image names are retained. A process that exits mid-snapshot
    invalidates that sample instead of quietly reducing the measured tree.
    """

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        class Entry(ctypes.Structure):
            _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                        ("pid", wintypes.DWORD), ("heap", ctypes.c_size_t),
                        ("module", wintypes.DWORD), ("threads", wintypes.DWORD),
                        ("parent", wintypes.DWORD), ("priority", wintypes.LONG),
                        ("flags", wintypes.DWORD), ("exe", wintypes.WCHAR * 260)]

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in (
                    "peak_working_set", "working_set", "peak_paged", "paged",
                    "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile")]

        self.ctypes, self.Entry, self.Counters = ctypes, Entry, Counters
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateToolhelp32Snapshot": ([wintypes.DWORD, wintypes.DWORD], wintypes.HANDLE),
            "Process32FirstW": ([wintypes.HANDLE, ctypes.POINTER(Entry)], wintypes.BOOL),
            "Process32NextW": ([wintypes.HANDLE, ctypes.POINTER(Entry)], wintypes.BOOL),
            "OpenProcess": ([wintypes.DWORD, wintypes.BOOL, wintypes.DWORD], wintypes.HANDLE),
            "K32GetProcessMemoryInfo": ([wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD], wintypes.BOOL),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.api, name)
            function.argtypes, function.restype = arguments, result

    def sample(self, root_pid):
        c, api = self.ctypes, self.api
        snapshot = api.CreateToolhelp32Snapshot(2, 0)  # TH32CS_SNAPPROCESS
        if snapshot == c.c_void_p(-1).value:
            raise c.WinError(c.get_last_error())
        parents = {}
        try:
            entry = self.Entry()
            entry.dwSize = c.sizeof(entry)
            if not api.Process32FirstW(snapshot, c.byref(entry)):
                raise c.WinError(c.get_last_error())
            while True:
                parents[int(entry.pid)] = int(entry.parent)
                if not api.Process32NextW(snapshot, c.byref(entry)):
                    error = c.get_last_error()
                    if error != 18:  # ERROR_NO_MORE_FILES is the only clean end.
                        raise c.WinError(error)
                    break
        finally:
            api.CloseHandle(snapshot)
        if root_pid not in parents:
            raise RuntimeError("Owned root process missing from memory snapshot")
        selected = {root_pid}
        while True:
            children = {pid for pid, parent in parents.items() if parent in selected and pid > 0}
            if children <= selected:
                break
            selected.update(children)
        sizes = {}
        for pid in selected:
            handle = api.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION; counters only
            if not handle:
                raise c.WinError(c.get_last_error())
            try:
                counters = self.Counters()
                counters.cb = c.sizeof(counters)
                if not api.K32GetProcessMemoryInfo(handle, c.byref(counters), counters.cb):
                    raise c.WinError(c.get_last_error())
                sizes[pid] = int(counters.working_set)
            finally:
                api.CloseHandle(handle)
        return sizes[root_pid], sum(value for pid, value in sizes.items() if pid != root_pid)


def memory_method():
    metric = "Windows PSAPI WorkingSetSize (bytes), Toolhelp descendants; in-process sampler thread" if os.name == "nt" else "POSIX ps RSS (KiB converted to bytes); ps helper excluded"
    return (metric + "; nominal 0.5s samples; shared pages may be counted more than once; "
            "not exact peak or unique physical RAM; legacy rss_bytes fields hold this metric")


class MemorySampler:
    """Sample this Slicer and descendants every 0.5s, including during blocking work."""

    def __init__(self, interval=0.5):
        if os.name not in ("posix", "nt"):
            raise RuntimeError("Memory sampling supports Windows, macOS and Linux.")
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("Sampling interval must be finite and positive.")
        self.windows = WindowsMemory() if os.name == "nt" else None
        self.interval = interval
        self.stop_event = threading.Event()
        self.samples = []
        self.errors = 0
        self.error_types = {}
        self.method = memory_method()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _sample(self):
        if self.windows is not None:
            root, children = self.windows.sample(os.getpid())
        else:
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
        if root <= 0:
            raise RuntimeError("Owned root memory was unavailable")
        self.samples.append((time.perf_counter(), root, children))

    def _run(self):
        while not self.stop_event.wait(self.interval):
            try:
                self._sample()
            except (OSError, RuntimeError) as exc:
                self.errors += 1
                # Numeric error codes/classes only, never raw local exception text.
                key = f"{type(exc).__name__}:{getattr(exc, 'winerror', None) or getattr(exc, 'errno', None)}"
                self.error_types[key] = self.error_types.get(key, 0) + 1

    def ensure_recent(self, max_age=10):
        if not self.samples or time.perf_counter() - self.samples[-1][0] > max_age:
            raise RuntimeError("Memory guard unavailable: no recent successful sample")

    def __enter__(self):
        self._sample()  # Fail before work if monitoring is unavailable.
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop_event.set()
        self.thread.join(timeout=5)

    def summary(self):
        if not self.samples:
            raise RuntimeError("No RSS samples captured; memory qualification is unavailable.")
        return {"memory_method": self.method, "error_types": dict(self.error_types),
                "maximum_sample_gap_seconds": max((b[0] - a[0] for a, b in zip(self.samples, self.samples[1:], strict=False)), default=0),
                "sample_interval_seconds": self.interval, "samples": len(self.samples),
                "sample_errors": self.errors, "baseline_gui_rss_bytes": self.samples[0][1],
                "peak_gui_rss_bytes": max(row[1] for row in self.samples),
                "peak_descendants_rss_bytes": max(row[2] for row in self.samples),
                "peak_tree_rss_bytes": max(row[1] + row[2] for row in self.samples)}
