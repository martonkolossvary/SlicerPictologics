#!/usr/bin/env python3
"""Run the integration suite inside Slicer; never install or download anything.

Launch with Slicer --no-splash --no-main-window --disable-settings --ignore-slicerrc
--additional-module-path <repo>/PictologicsSlicer
--additional-module-path <repo>/PictologicsCLI
--python-script <repo>/scripts/run_slicer_integration.py.
Set SLICERPICTOLOGICS_RUN_REAL_CLI_TEST=1 to require the real worker gate.
"""

from __future__ import annotations

import sys
import traceback
import unittest
from pathlib import Path

import slicer


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "PictologicsSlicer"))
    sys.path.insert(0, str(root / "PictologicsSlicer" / "Testing" / "Python"))
    from PictologicsSlicerIntegrationTest import PictologicsSlicerIntegrationTest

    print(f"Slicer {slicer.app.applicationVersion}; Python {sys.version}", flush=True)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PictologicsSlicerIntegrationTest)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    try:
        code = main()
    except BaseException:
        traceback.print_exc()
        code = 1
    slicer.util.exit(code)
