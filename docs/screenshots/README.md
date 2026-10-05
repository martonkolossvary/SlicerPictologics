# Catalog screenshots

Captured on 2026-10-05 in 3D Slicer 5.12.4 on macOS (Intel/Rosetta), using the
published Pictologics 0.7.0 wheel with Numba 0.62.1 and NumPy 2.3.5. The extension
installed it with its normal first-run installer into a separate, temporary package
folder. Both PNGs are genuine, unretouched application-window captures, not mockups.
The maintainer visually approved both on 2026-10-05.

- `pictologics-workflow.png`: captured with
  [`capture_sample_data_demo.py`](../../scripts/capture_sample_data_demo.py). Real
  public **MRHead MRI** with two selected demonstration ROIs, the input fields
  (including reader, extra columns, scanner details and crop), the configuration
  controls, the readiness line, the elapsed time, and completed extraction.
  Resolution: 3680 × 1916. The capture shows the Slicer window contents without the
  macOS title bar; the view annotations and segment names identify the public sample
  and the demonstration ROIs. It replaces the 2026-09-25 image, which showed the
  window before the reader, extra-column, scanner, crop, batch and diagnostics controls.
- `pictologics-results.png`: captured from a **separate synthetic phantom run** with
  `standard_fbn_32` (340 rows, all `ok`). It shows the actual result table (columns L
  to R, with `pictologics_version` 0.7.0) and the output controls. Resolution: 3680 ×
  1916, without the macOS title bar. It replaces the 2026-09-21 image, which showed
  Pictologics 0.5.1 and an earlier window.

## MRHead source and masks

The workflow uses Slicer's built-in **MRHead** sample, retrieved with
`SampleData.downloadSample("MRHead")`. The
[SampleData acknowledgements](https://github.com/Slicer/Slicer/blob/v5.12.4/Modules/Scripted/SampleData/SampleData.py)
state that MRHead was donated by the person visible in the images for unrestricted
use. Original sample: `MR-head.nrrd`; SHA-256:
`cc211f0dfd9a05ca3841ce1141b292898b2dd2d3f08286affadf823a7e58df93`.

**Left ROI (demo)** and **Right ROI (demo)** are generated ellipsoidal masks over
the real MRI, not clinical segmentations, tumor annotations, or diagnostic findings.
Original MRI voxel intensities are unchanged. Each mask contains 26,122 input
voxels. Actual extraction produced **170 features per ROI, 340 rows total, all
statuses `ok`**, with `standard_fbn_32`. The image contains no fabricated results.
The sample volume itself is not included in this repository.

Approved PNG SHA-256 values:

- `pictologics-workflow.png`:
  `c482097887461079c7c3023356d9ff431bc4d71704c327d3929563441956f73a`
- `pictologics-results.png`:
  `e4dfdebe72321afa0fd63b42e6a1a0eb5bbd1c24a5e7339f81a5859dc3fe6207`

## Synthetic results-table example

The CT-like phantom is generated mathematically by
[`create_catalog_demo.py`](../../scripts/create_catalog_demo.py), with random seed
`20260921`. It is illustrative, not realistic anatomy or clinical validation data.
It contains no patient information and requires no downloaded sample data.
The synthetic phantom script and its screenshot are distributed under this
repository's Apache-2.0 license; the real MRHead sample's reuse terms are described above.

## Reproduce the MRHead workflow

Use a fresh Slicer session. Install the adopted package once through the normal
module interface before running this demonstration. The script may download the
public sample through Slicer's checksum-verified SampleData loader. It does not
install dependencies or upload data, and refuses to replace a scene containing volumes.

From the repository root on macOS:

```sh
/Applications/Slicer.app/Contents/MacOS/Slicer \
  --no-splash --disable-settings --ignore-slicerrc \
  --additional-module-paths "$PWD/PictologicsSlicer" "$PWD/PictologicsCLI" \
  --python-script "$PWD/scripts/create_sample_data_demo.py"
```

On Linux or Windows, substitute the Slicer executable and absolute module/script
paths. The isolated launch avoids changing saved application preferences.

To run the same demo and save the capture automatically, launch
`scripts/capture_sample_data_demo.py` instead, with `PICTOLOGICS_CAPTURE_PATH` set to
the PNG file to write. It waits for the real run to finish and then saves the window
contents, without the operating-system title bar.

1. Maximize the Slicer window and select **Run radiomics**. Leave both demonstration
   ROIs and `standard_fbn_32` selected. Alternatively, set
   `PICTOLOGICS_DEMO_AUTORUN=1` before launch to invoke the same module workflow.
2. Wait for **340 feature rows** and 100% completion. This is a real background
   extraction; the script does not create synthetic result values.
3. After verifying that both ROIs have computed results, the script restores the
   Four-Up anatomy view. Keep the public-sample/demonstration-ROI title visible.
   The demo fits the longer panel to the window (`fit_panel`): the lists match their
   items, the extra-columns box shows two lines, the profiles section is collapsed,
   and the panel is a little wider. This changes only the view, not saved application
   preferences or calculated results.
4. Capture only the application window; exclude other applications and desktop
   content. Inspect each PNG for readability and unintended personal information.

To reproduce the separate synthetic results-table screenshot, use
`scripts/create_catalog_demo.py` instead, then:

1. Select **Run radiomics** with `standard_fbn_32`, and select **Continue** at the
   large-run memory warning.
2. Wait for **340 feature rows**. Collapse **Feature configurations**, expand
   **Output**, and fit the panel as the MRHead demo does.
3. Show the results table in a layout with one table view, and scroll to the
   `ibsi_code` column.
4. Capture only the application window.

Keep new captures in a temporary folder outside the repository and outside synced
folders. Obtain maintainer visual approval before copying them into published
documentation. Agent inspection is not maintainer approval.

Screenshots are documentation/catalog assets only. They are not included in the
installed Python module resources. `EXTENSION_SCREENSHOTURLS` in the root CMake
file points to their public raw GitHub URLs.
