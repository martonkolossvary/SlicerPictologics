"""Pytest configuration for the SlicerPictologics support-library test suite.

Puts the GUI package directory (for ``PictologicsLib``) and the CLI worker directory on
``sys.path`` so a bare ``pytest`` run works from the repository root, and pins a
writable Numba cache while suppressing import-time JIT warmup. These tests cover the
Slicer-neutral library and the standalone CLI worker; the GUI module imports the Slicer
runtime and is exercised only by the in-Slicer ScriptedLoadableModuleTest.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for _directory in (ROOT / "PictologicsSlicer", ROOT / "PictologicsCLI"):
    _entry = str(_directory)
    if _entry not in sys.path:
        sys.path.insert(0, _entry)

os.environ.setdefault("PICTOLOGICS_DISABLE_WARMUP", "1")
os.environ.setdefault("NUMBA_CACHE_DIR", str(ROOT / ".pytest_cache" / "numba"))
