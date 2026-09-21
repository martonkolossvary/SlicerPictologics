# Catalog screenshots

Captured on 2026-09-21 in 3D Slicer 5.12.4 on macOS (Intel/Rosetta), using the
published Pictologics 0.5.1 wheel in the extension's existing private environment.
Both PNGs are genuine application-window captures, not rendered mockups.

- `pictologics-workflow.png`: the synthetic volume, two selected regions, and
  feature-configuration controls after successful extraction.
- `pictologics-results.png`: the same run's actual result table and export controls.

The CT-like phantom is generated mathematically by
[`create_catalog_demo.py`](../../scripts/create_catalog_demo.py), with random seed
`20260921`. It is illustrative, not realistic anatomy or clinical validation data.
It contains no patient information and requires no downloaded sample data.
The images are distributed under this repository's Apache-2.0 license.

## Reproduce

Use a fresh Slicer session. Install the adopted package once through the normal
module interface before running this demonstration. The script does not install
dependencies and refuses to replace a scene containing volumes.

From the repository root on macOS:

```sh
/Applications/Slicer.app/Contents/MacOS/Slicer \
  --no-splash --disable-settings --ignore-slicerrc \
  --additional-module-paths "$PWD/PictologicsSlicer" "$PWD/PictologicsCLI" \
  --python-script "$PWD/scripts/create_catalog_demo.py"
```

On Linux or Windows, substitute the Slicer executable and absolute module/script
paths. The isolated launch avoids changing saved application preferences.

1. Maximize the Slicer window and select **Run radiomics**. Leave both synthetic
   regions and `standard_fbn_32` selected.
2. Wait for **340 feature rows** and 100% completion. This is a real background
   extraction; the script does not create synthetic result values.
3. Capture the workflow and results views, with the synthetic-data title visible.
   Collapse configuration controls or scroll the table to reveal feature columns
   as needed. Do not edit table values or add fabricated overlays.
4. Capture only the application window; exclude other applications and desktop
   content. Inspect each PNG for readability and unintended personal information.

Screenshots are documentation/catalog assets only. They are not included in the
installed Python module resources. `EXTENSION_SCREENSHOTURLS` in the root CMake
file points to their public raw GitHub URLs.
