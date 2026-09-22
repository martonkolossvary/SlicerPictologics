# Catalog screenshots

Captured in 3D Slicer 5.12.4 on macOS (Intel/Rosetta), using the published
Pictologics 0.5.1 wheel in the extension's existing private environment.
Both PNGs are genuine, unretouched application-window captures, not mockups.

- `pictologics-workflow.png`: captured and visually approved by the maintainer on
  2026-09-22. Real public **MRHead MRI** with two selected demonstration ROIs,
  configuration controls, and completed extraction. Resolution: 3680 × 2280.
- `pictologics-results.png`: captured on 2026-09-21 from a **separate synthetic
  phantom run**, showing the actual result table and export controls. This image
  is unchanged; approval of the new workflow image does not approve other revisions.

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

Approved workflow PNG SHA-256:
`6d6e4ed47a2e6d1c33b305cafbc6c58aca30294b3ac0ec3871bba93ffb09e9a1`.

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

1. Maximize the Slicer window and select **Run radiomics**. Leave both demonstration
   ROIs and `standard_fbn_32` selected. Alternatively, set
   `PICTOLOGICS_DEMO_AUTORUN=1` before launch to invoke the same module workflow.
2. Wait for **340 feature rows** and 100% completion. This is a real background
   extraction; the script does not create synthetic result values.
3. After verifying that both ROIs have computed results, the script restores the
   Four-Up anatomy view. Keep the public-sample/demonstration-ROI title visible.
   Only the demo's list heights and view presentation are adjusted for readability;
   saved application preferences and calculated results are not changed.
4. Capture only the application window; exclude other applications and desktop
   content. Inspect each PNG for readability and unintended personal information.

To reproduce the separate synthetic results-table screenshot, use
`scripts/create_catalog_demo.py` instead. Keep all new captures in the Git-ignored
`local-output/catalog-review/` folder and obtain maintainer visual approval before
copying them into published documentation. Agent inspection is not maintainer approval.

Screenshots are documentation/catalog assets only. They are not included in the
installed Python module resources. `EXTENSION_SCREENSHOTURLS` in the root CMake
file points to their public raw GitHub URLs.
