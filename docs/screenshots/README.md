# Catalog screenshots

## Anatomical workflow and results (approved 2026-10-22)

The maintainer approved both anatomical liver captures on 2026-10-22.
`pictologics-workflow.png` now uses the public **CTLiver** scan with its matching Medical Segmentation Decathlon
**Task03_Liver / liver_100** annotations instead of generated ellipsoids. The two
ROIs are **Liver tissue (MSD label 1)** and **Liver tumour (MSD label 2)**. Label 1
excludes the separately labelled tumour; it is not an inclusive whole-liver mask.
These are supplied research-dataset annotations, not segmentations newly validated
by this project or claims of clinical accuracy.

The workflow is a genuine, unretouched Slicer application-window capture, without
the operating-system title bar, at **3680 × 1988**. Its SHA-256 is
`6f87b5abd093fb6159b22c1ff0d36dbb26f084ccbfe7393ddacdf682ed234305`.
It replaces the earlier MRHead workflow described in the historical section below.
This approved capture predates the grouped-preset browser added later that day;
the separate new-control preview remains local pending visual approval.
`pictologics-results.png` is the matching, genuine read-only results/provenance
browser capture from the **same run**, showing 340 feature rows and the selected
feature's native identifiers, preprocessing and Pictologics 0.8.0 provenance.
Resolution: **2900 × 1900**; SHA-256:
`9c2859b6908cb16e065cbc16093f9c79cbf80636577fab354b6ddf1b1ab68194`.
It replaces the earlier synthetic results-table screenshot described below.

[`create_anatomical_ct_demo.py`](../../scripts/create_anatomical_ct_demo.py)
verifies both file hashes and checks all physical-grid corners (maximum allowed
disagreement 0.001 mm). It crops the native CT lattice around both annotations,
without resampling, changing intensities, or truncating labelled voxels. It runs
the actual module workflow for both ROIs, exports results and an MRB scene before
closing, and captures the workflow and read-only results/provenance browser from
that same extraction. It uses only an existing qualified dependency target; no
package installation or update is performed.

The image comes from Slicer's CTLiver sample, SHA-256
`e16eae0ae6fefa858c5c11e58f0f1bb81834d81b7102e021571056324ef6f37e`.
The matching label file is retrieved from a
[public mirror pinned to revision 6a5aad7](https://huggingface.co/datasets/MedOtter/msd-liver/blob/6a5aad7ca262f2420d1bd4c2517b37b265db53eb/labelsTr/liver_100.nii.gz),
SHA-256 `ab2d2f85c5143fed2a14480fe172cf7956defab078431ac5315b1d36fefd548c`.
The dataset is attributed to the [Medical Segmentation Decathlon](http://medicaldecathlon.com/),
under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/);
see [Antonelli et al., 2022](https://doi.org/10.1038/s41467-022-30695-9).
Retain this attribution and the dataset's reuse terms with any approved CT-derived
images. The mirror is a distribution source, not an independent annotation audit.

To reproduce, download the pinned annotation above to a temporary directory and
set these environment variables before an isolated, visible Slicer launch:

- `PICTOLOGICS_ANATOMICAL_DEMO_OUTPUT`: a **new** temporary output directory,
  outside the repository and synced folders.
- `PICTOLOGICS_ANATOMICAL_LABELS`: the downloaded `liver_100` annotation file.
- `PICTOLOGICS_SAMPLE_CACHE`: the directory containing the original checksum-verified
  `CTLiver.nrrd` (not the smaller derived performance fixture).
- `SLICERPICTOLOGICS_TEST_DEPENDENCY_PATH`: an existing qualified private package target.
- `NUMBA_NUM_THREADS=2` for a bounded demonstration run; keep `PICTOLOGICS_DEV_SOURCE` unset.

Use the same executable/module paths as the command below, substituting
`scripts/create_anatomical_ct_demo.py` as the Python script. The script refuses
to reuse an existing output directory or a scene containing a volume. Keep new
captures local until the maintainer has visually reviewed them. Both anatomical
workflow and matching results-browser replacements are approved; further image
replacements require their own approval.

Capture verification on 2026-10-22 used Slicer 5.12.4 (Intel/Rosetta),
Pictologics 0.8.0, and `standard_fbn_32`. The original annotation contains
5,003,071 label-1 voxels and 1,569,689 label-2 voxels; the display crop retained
all of them. Maximum physical-grid corner disagreement was 0.00004465 mm.
Actual extraction returned **170 features per ROI, 340 rows total, all `ok`**.
CSV (including provenance/catalog sidecars), JSON and the MRB scene were saved;
the disposable application exited successfully. Approved workflow and results-browser
captures are 3680 × 1988 and 2900 × 1900 respectively. These observations verify
the demonstration workflow, not clinical annotation accuracy or general performance.

## Earlier captures: historical workflow and results images

Captured on 2026-10-05 in 3D Slicer 5.12.4 on macOS (Intel/Rosetta), using the
published Pictologics 0.7.0 wheel with Numba 0.62.1 and NumPy 2.3.5. The extension
installed it with its normal first-run installer into a separate, temporary package
folder. Both PNGs are genuine, unretouched application-window captures, not mockups.
The maintainer visually approved both on 2026-10-05.

- Historical `pictologics-workflow.png` (replaced on 2026-10-22): captured with
  [`capture_sample_data_demo.py`](../../scripts/capture_sample_data_demo.py). Real
  public **MRHead MRI** with two selected demonstration ROIs, the input fields
  (including reader, extra columns, scanner details and crop), the configuration
  controls, the readiness line, the elapsed time, and completed extraction.
  Resolution: 3680 × 1916. The capture shows the Slicer window contents without the
  macOS title bar; the view annotations and segment names identify the public sample
  and the demonstration ROIs. It replaces the 2026-09-25 image, which showed the
  window before the reader, extra-column, scanner, crop, batch and diagnostics controls.
- Historical `pictologics-results.png` (replaced on 2026-10-22): captured from a **separate synthetic phantom run** with
  `standard_fbn_32` (340 rows, all `ok`). It shows the actual result table (columns L
  to R, with `pictologics_version` 0.7.0) and the output controls. Resolution: 3680 ×
  1916, without the macOS title bar. It replaces the 2026-09-21 image, which showed
  Pictologics 0.5.1 and an earlier window.

## Historical MRHead source and masks

The earlier workflow used Slicer's built-in **MRHead** sample, retrieved with
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

Earlier approved PNG SHA-256 values (both images have been replaced):

- `pictologics-workflow.png`:
  `c482097887461079c7c3023356d9ff431bc4d71704c327d3929563441956f73a`
- `pictologics-results.png`:
  `e4dfdebe72321afa0fd63b42e6a1a0eb5bbd1c24a5e7339f81a5859dc3fe6207`

## Historical synthetic results-table example

The CT-like phantom is generated mathematically by
[`create_catalog_demo.py`](../../scripts/create_catalog_demo.py), with random seed
`20260921`. It is illustrative, not realistic anatomy or clinical validation data.
It contains no patient information and requires no downloaded sample data.
The synthetic phantom script and its screenshot are distributed under this
repository's Apache-2.0 license; the real MRHead sample's reuse terms are described above.

## Reproduce the historical MRHead workflow

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
