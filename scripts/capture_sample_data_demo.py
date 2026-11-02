"""Run the MRHead demo, then save one capture of the Slicer window.

Launch it like create_sample_data_demo.py, in a fresh --disable-settings session,
with PICTOLOGICS_CAPTURE_PATH set to the PNG file to write. The demo script is
unchanged: it presses Run radiomics through the module (autorun), and this script
only waits for the real run to finish before it saves the window contents. The
capture does not include the operating-system title bar.
"""

from __future__ import annotations

import os
import runpy
from pathlib import Path

import ctk
import qt
import slicer

OUTPUT = os.environ["PICTOLOGICS_CAPTURE_PATH"]
os.environ["PICTOLOGICS_DEMO_AUTORUN"] = "1"
DEMO = runpy.run_path(
    str(Path(__file__).with_name("create_sample_data_demo.py")), run_name="pictologics_demo"
)


def save() -> None:
    slicer.app.processEvents()
    image = ctk.ctkWidgetsUtils.grabWidget(slicer.util.mainWindow())
    saved = image.save(OUTPUT)
    print(f"CAPTURE_SAVED {saved} {image.width()}x{image.height()}", flush=True)
    slicer.util.exit(0 if saved else 1)


def wait_for_results() -> None:
    widget = slicer.modules.pictologicsslicer.widgetRepresentation().self()
    if widget._lastPayload is None or widget._activeJob is not None:
        qt.QTimer.singleShot(1000, wait_for_results)
        return
    # The demo restores the Four-Up anatomy view after it checks the results.
    qt.QTimer.singleShot(3000, save)


def start() -> None:
    DEMO["create_demo"]()
    slicer.util.mainWindow().resize(1840, 1140)
    qt.QTimer.singleShot(2000, wait_for_results)


if __name__ == "__main__":
    qt.QTimer.singleShot(0, start)
