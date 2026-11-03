# User guide

Detailed instructions for Pictologics in 3D Slicer. See the [README](../README.md)
for the sample images, feature overview and installation status.

- [Run an extraction](#use)
- [Build a custom configuration](#build-a-custom-configuration)
- [Apply image filters](#filter-the-image-ibsi-2)
- [Reduce memory use](#use-less-memory)
- [Browse results and provenance](#browse-results-and-provenance)
- [Save configuration profiles](#save-and-reuse-configuration-profiles)
- [Run a batch](#process-many-cases-in-the-batch-section)
- [Script extraction](#process-many-cases-with-a-script)
- [Current limitations](#current-limitations)

## Use

1. Load a 3D scalar volume and, for region-based extraction, a segmentation.
2. Open **Pictologics**, choose the volume, and check one or more segments. Each
   segment shows its color. **Select all** and **Select none** change every check.
   Overlapping segments remain independent. **Also analyze the whole volume** is off
   by default: the presets resample the entire scan, which can need several
   gigabytes of memory for a large CT. Open **Case details (optional)** to enter a
   subject ID, a reader and extra columns (see
   [Add columns for later analysis](#add-columns-for-later-analysis)).
3. In the preset tree, open **General**, **Coronary plaque** or **Myocardium** and
   check individual presets. A group shows how many of its presets are checked; check
   the group itself to select all of its presets. Click a preset to read its native
   identifier, resampling, HU range and feature settings. **Clear all presets**
   removes every check. Only checked configurations run, not the entire template
   collection. The default is `standard_fbn_32` in General. Optionally add
   configurations with **Custom configuration**: *Build in this panel* (see
   [Build a custom configuration](#build-a-custom-configuration)) or *Load from a
   file* (browse to a custom Pictologics YAML/JSON, generate a starter with
   **New from preset…**, or press **Validate** to load the file with Pictologics as a
   run does).
4. Choose or create an output table. Check the **Ready** summary of whole-volume,
   segment, and configuration selections, then select **Run radiomics**. Readiness
   checks the controls; geometry and custom configurations are checked again during
   preparation and worker execution. If one copy of the resampled scan needs more
   than about 1 GB of memory, the module asks before it starts.
5. On first use, review and approve installation into the private dependency target.
   No global Slicer package is replaced. The first run is slower because of JIT warmup.
6. Follow the current phase and **Processing ROI _n_ of _total_: _name_** message.
   **Elapsed** includes dependency checks, input preparation, and extraction; it is
   not an estimate of time remaining and stops at completion, failure, or cancellation.
   Multi-ROI percentages indicate completed regions, not estimated computation time.
   A single ROI uses an animated busy indicator. Use **Cancel** to stop the background
   job. Cancellation or fatal failure preserves
   the previous table; completed results are committed to the scene together.
7. Select **Export table as CSV or JSON…** to save the current results table. Enable
   **Export wide layout** for one row per ROI with Pictologics' exact
   `config__feature_key` columns instead of the default long layout. JSON
   includes the complete per-run provenance
   history and feature data dictionary; CSV writes companion `.provenance.json` and
   `_catalog.csv` files (the latter is the Slicer-side equivalent of Pictologics'
   `describe_features()`). For example, `features.csv` gets `features_catalog.csv`,
   the name that eigenradiomics finds automatically. Provenance contains local
   folder paths. The export writes your home folder as `~`, but check other paths
   before you share the file.
   In CSV files, a text cell that starts with `=`, `+`, `-`, `@`, a tab or a carriage
   return gets a leading `'`, so that a spreadsheet does not run it as a formula.
   Numbers do not change, and JSON keeps the original text.

CSV exports stage all companion files before replacing any destination. Caught
write/replacement failures restore earlier files; if restoration itself fails,
the error identifies a retained recovery folder. The result table is unchanged.
Multiple files cannot be replaced as one filesystem transaction: a power loss or
forced process termination during replacement is not covered by this rollback.
Prefer the single-file JSON bundle for an independent archive, and avoid editing
the destination files from another application during export.

The long table keeps the official `ibsi_code` and also reports the exact native
`feature_key`, Pictologics' disambiguated `pictologics_ibsi_code`, the package-wide
`pictologics_feature_name`, and `preprocessing_sequence`. For example, the official
IBSI code `BC2M` is paired with `BC2M_10` or `BC2M_90`, and a package-wide name such as
`standard_fbn_32__volume_at_intensity_fraction_0.10_BC2M_10`. The longer identifier is
Pictologics-specific, not a second official IBSI code. Complete preprocessing
parameters remain in the feature data dictionary.

The columns `config`, `family`, `feature_name`, `feature_key`, `ibsi_code`, and
`preprocessing_sequence` mean the same as in Pictologics' `describe_features()`:
`feature_key` is the full key with the IBSI code (`mean_intensity_Q4LE`), and
`feature_name` is the name without the code (`mean_intensity`). These columns form
result format 2 of the extension's initial `0.1.0` release. Tables in format 1, from
earlier development versions, cannot be appended, browsed, or exported; run the
extraction again.

One results column keeps one meaning. If you append a run to a table that already
holds a configuration of the same name with other settings, the new results go to a
new table, and the status line names the configuration. For example, the in-app
configuration without a filter is always named `in_app`, so changed in-app settings
start a new table.

### Build a custom configuration

Choose **Custom configuration → Build in this panel**. The steps run from top to
bottom. Check a step to use it; the other steps are skipped. These settings apply only
to the custom configuration, not to the checked presets.

1. **Image data:** which voxels hold image data. *All voxels except padding* leaves
   out a padding value, for example -2048 HU outside the field of view of a CT. Enter
   the **Padding value**, or leave it empty to let Pictologics find it.
2. **Resample:** the new voxel spacing in mm, with linear, nearest-neighbour or cubic
   interpolation.
3. **Grow or shrink the region:** a positive **Distance** grows each region, and a
   negative one shrinks it. **Ring starts at** leaves out the inner part, which keeps
   a ring: for example 0 and 3 give the 3 mm around the region.
4. **Normalise intensities:** z-score, or a percentile range that becomes 0 to 1,
   with the statistics of the whole image or of the region. Use it for MR images.
   Later steps use the new units.
5. **Intensity range:** keep the voxels from an inclusive minimum to a maximum, in
   the image's units at this step. A blank bound is unlimited; at least one bound is
   necessary.
6. **Outlier filtering:** keep the values within the region mean ± sigma times its
   population standard deviation.
7. **Keep the largest connected part** of each region.
8. **Image filter (IBSI 2):** see [Filter the image](#filter-the-image-ibsi-2).
9. **Discretise:** a fixed bin number (FBN), a fixed bin size (FBS), or fixed bin
   edges. FBS needs **First bin starts at**: a fixed start in the image's units
   *after* any filter or normalisation. The CT presets use **−1000 HU**; do not
   assume this value for MRI or filtered images. The extension never guesses it.
10. **Features:** the feature families. **Texture distance** sets the GLCM pair
    distance and the NGTDM and NGLDM neighbourhood distance; **NGLDM coarseness** sets
    the alpha of the NGLDM features. The IVH can use the intensities before
    discretisation.

The mask steps have an **Apply to** choice:

- **Both masks (changes shape):** change the intensity and the morphology masks.
- **Intensity only (preserves shape):** change only the intensity mask. This is the
  default of the intensity range and the outlier filter, as in Pictologics and IBSI.
- **Morphology only:** change only the morphology mask.

The steps change only the calculation masks and values, not the input image or
segmentation. If a mask becomes empty, the worker reports the ROI error instead of
falling back to the original mask. Invalid numbers and reversed bounds block Run with
an explanation in the readiness line. The effective steps, mask targets and parameters
are kept in the result provenance.

### Filter the image (IBSI 2)

Turn on **Image filter (IBSI 2)** in the in-app builder and choose a filter: mean,
Gaussian, Laplacian of Gaussian (LoG), Laws texture energy, Gabor, separable wavelet,
Simoncelli wavelet, or one of the three Riesz filters. The fields show the parameters
of the chosen filter, with the IBSI 2 reference settings as defaults. **Boundary** sets
how the filter treats the image border; *Pictologics default* is mirror, or periodic
for the Simoncelli wavelet and the Riesz filters.

The filter list can hold several filters, for example LoG with sigma 1, 2 and 3 mm.
**Add filter** adds a copy of the selected filter; then change its settings. Each
filter gives its own configuration, named for the filter type and its position, for
example `in_app_log_1`, `in_app_log_2` and `in_app_wavelet_1`. Check **Also compute the
features without a filter** to add `in_app` too. Pictologics computes the shared steps
before the filter only once.

The filter runs after resampling and ROI refinement, and before discretisation, as
IBSI 2 requires. The features are then computed from the filter response inside the
ROI; the masks do not change. IBSI 2 reports intensity features for response maps.

### Add columns for later analysis

Three kinds of text columns follow the fixed columns of every result row:

- **Reader** (`reader`): a label that you type, for example `R1`. Use it to pair the
  results of two readers.
- **Scanner details** (`modality`, `manufacturer`, `manufacturer_model_name`,
  `convolution_kernel`, `slice_thickness`, `kvp`, `magnetic_field_strength`): read
  from the DICOM database for a volume loaded from DICOM, or from the JSON file that
  dcm2niix writes next to a NIfTI image. **Case details** shows what it found.
  Empty when neither is available.
- **Extra columns**: one `name = value` per line, for example `center = A`. A name has
  letters, digits, and single underscores. A line with a scanner column name replaces
  the value that was read.

The wide export puts these columns before the feature columns.

### Use less memory

Pictologics resamples the whole scan for each region. Turn on **Crop around each
region**, above **Run radiomics**, to give Pictologics only a box around each region. The box has a margin for
interpolation, the filter, and the local-intensity features. The worker does not
crop for the *auto* voxel-validity mode, FFT-based filters (Simoncelli and Riesz),
periodic filter boundaries, cubic interpolation, an explicit filter-spacing
override, resampling after another step, normalization, mask growth, or an unknown
future operation. These need the whole image or a crop
model not yet supported. The provenance of each region keeps the crop box, or no
box when the worker did not crop. Memory warnings use the full-scan estimate because
cropping can fall back to the whole image or an entire axis.

Pictologics centers its resampling grid on the image that it gets. So along each
axis, the box grows until its grid lies on the grid of the whole scan; when that is
not possible by adding up to 256 voxels in total along that axis, the box keeps the
whole axis. The values then agree
with a whole-scan run to rounding precision. On Slicer's MRHead sample with a 12 mm
sphere away from the center, the worker used 0.48 GB instead of 2.4 GB, and all 170
values of `standard_fbn_32` agreed within one part in a billion (152 exactly).

**CPU threads** sets how many threads a run uses. *Automatic* uses the fast cores of
the computer; fewer threads keep Slicer more responsive during a run.

See [measured workloads and memory/timing guidance](performance.md) for CT/MRI,
multiple configurations, a ten-case batch, and large result tables. The 1 GB warning
estimates one image array, **not total peak RAM**; staging, worker arrays, masks,
result tables and the rest of Slicer require additional memory.

### Browse results and provenance

Select **Browse results and provenance…** in the Output section to open a resizable,
read-only results window. Search by feature name, IBSI code, native feature key, or
preprocessing text; combine ROI, configuration, family, and status filters. ROI
choices are scoped to a run, so appended runs with identical segment names remain
distinct. Large result sets are paged in groups of 200 rows.

Select a row to inspect its value, both IBSI identifiers, software versions, exact
run/configuration, configuration hash, preprocessing parameters, processing errors,
and feature-dictionary metadata. Requested/effective filter parameters appear when
present in the recorded processing log. Missing provenance is reported explicitly.

The browser is a **snapshot**: use **Refresh selected table** after a new run or
changing the output table. Filters never change the MRML table or export behavior:
**Export table as CSV or JSON… still exports the complete selected table**, not just
the visible matches. Closing the scene clears the browser's snapshot.

### Share privacy-safe diagnostics

Open **Diagnostics (privacy-safe)** below **Pictologics package**, then select
**Refresh diagnostics**. Review the read-only JSON and select **Copy preview**
only if you want to share it. Copy uses exactly that preview, not a silently
refreshed report. Nothing is uploaded automatically or saved to the scene.

The report contains allowlisted software versions, OS/process architecture,
dependency metadata status, and this module session's latest operation/run state,
ROI/feature-row counts and elapsed seconds. Fixed failure codes include a short
recovery suggestion. It excludes image data, subject/image/segment/configuration
names, file paths, DICOM metadata, environment variables, raw logs and exception
messages. Unrecognized version strings are replaced with `unknown`.

The dependency status is a **metadata check**, not an import/API/JIT health test;
refreshing never installs packages or launches a worker. For a failed installation,
check connectivity and disk space, then retry **Install / update adopted release…**.
A rejected candidate leaves the previous active environment intact.
**Remove private packages…** deletes the private packages (about 600 MB) and the
compiled code of this Slicer after you confirm; a later run installs them again. It
waits until no Pictologics job runs. After an update, the extension deletes the old
package version and its compiled code by itself when no job runs. For export
failure, keep the table open, check the destination and retry. Detailed errors and
processing logs remain available locally and may contain identifying information;
do not paste them publicly without reviewing them separately.

See the [diagnostics and recovery test scope](diagnostics-and-recovery.md).

### Save and reuse configuration profiles

In **Configuration profiles**, use **Save…** to name and save the checked grouped
presets and optional in-app configuration to a `.pictologics-profile.json` file.
Use **Load…** to restore them, or **Save copy…** to save the current settings under a
new name/file without replacing the original. Save again after editing settings;
changes are not automatically written back to the profile file.
Profiles include every step and the whole filter list.

Profiles do not capture image/segmentation selections, subject IDs, output tables,
or machine-specific dependency paths. Loading validates all settings before changing
the controls and rejects unsupported values instead of silently clamping them.
Profile names label saved settings; native configuration names (`in_app` and the
native preset names) and exported feature names are unchanged. Profiles can mix
General, coronary and myocardial selections.
Profiles do not pin a package version: each run uses the extension's adopted
Pictologics release and records its version and effective configuration in provenance.

These are **Slicer settings files**, not native Pictologics pipeline configuration
files. Advanced YAML/JSON pipelines still use **Custom configuration → Load from a
file**; profile saving is disabled in that mode.

In a custom YAML/JSON file, set `apply_to` in each `resegment` and
`filter_outliers` step. Without it, the step uses the default of the installed
Pictologics release, and that default can change in a new release.

### Process many cases in the Batch section

Put each case in its own subfolder of a study folder, with the same file names, for
example `image.nii.gz` and `segmentation.seg.nrrd`. In the **Batch** section, choose
the study folder and the two file names (a pattern such as `*.nrrd` is allowed), then
select **Run batch…**. The module shows the number of cases and the folders it
skips, and asks before it starts.

Each case uses the settings of the window. The folder name becomes the subject ID,
and every segment is a region. The rows of all cases go into the results table.
**Cancel** cancels the active case and stops the batch before the next case. At the end, the status line shows
how many cases added rows, and a message lists the cases that failed.

Every batch also creates a hidden **Saved batch report** table in the scene. It keeps
one row per eligible or skipped case, including elapsed time, ROI/feature-row counts,
result-table name, and a reason for failed, partial, cancelled, or interrupted cases.
Use **View report** to inspect it and **Export report…** for an atomic JSON or CSV
copy. Save the scene or export the report before closing; a report is not written to
an external location automatically. Reports may contain case identifiers and error
paths; review them before sharing. A saved snapshot of a running batch is shown as
interrupted after reload, and does not automatically resume extraction.
Report rows also have JSON storage in the scene, preserving multiline error text,
tabs, and exact elapsed times when Slicer's generic table storage cannot. Older
reports without this backup remain readable if their saved table is intact;
already-corrupted legacy tables need the independently exported JSON/CSV report.

### Process many cases with a script

Use Slicer's Python console (**View → Python Console**) to run many cases into one
table. Change the folder and the file names to match your data.

```python
from pathlib import Path

logic = slicer.util.getModuleLogic("PictologicsSlicer")
study = Path("/path/to/study")
table = None
for case in sorted(path for path in study.iterdir() if path.is_dir()):
    volume = slicer.util.loadVolume(str(case / "image.nii.gz"))
    segmentation = slicer.util.loadSegmentation(str(case / "segmentation.seg.nrrd"))
    table = logic.process(volume, segmentation, subjectID=case.name, outputTable=table)
    slicer.mrmlScene.RemoveNode(volume)
    slicer.mrmlScene.RemoveNode(segmentation)
logic.exportTable(table, study / "features.csv", wide=True)
```

- `logic.process` returns when the case is complete. Slicer does not respond during
  a case.
- All segments are regions by default. Use `segmentIDs=[...]` to select segments, and
  `includeWholeVolume=True` to add the whole scan.
- Use `standardConfigurations=[...]` to select native preset names (including
  `coronary_orig`, `coronary_cp_fbs_16`, or `lv_myo_orig`), and
  `customConfigurationPath="settings.yaml"` to add a configuration file.
- Use `reader="R1"`, `extraColumns={"center": "A"}`, and `cropToRegion=True` as in the
  window.
- A region that fails gets rows with a status that is not `ok`, and the loop
  continues. A case that cannot run stops the loop with an error.
- `wide=True` writes one row per region. The export also writes
  `features_catalog.csv`, so the files are ready for eigenradiomics (see below).

### Analyze the results with eigenradiomics

[eigenradiomics](https://github.com/martonkolossvary/eigenradiomics) reads the wide CSV
export and its catalog. Name the export `features.csv`, so that the catalog is
`features_catalog.csv`, which eigenradiomics finds automatically.

```python
from eigenradiomics import RadiomicsDataset

dataset = RadiomicsDataset.from_pictologics(
    "features.csv", drop_subject_id=False, group="subject_id"
)
```

`drop_subject_id=False` keeps the extension's `subject_id` column, which the loader
otherwise deletes. The feature columns have the same names as in Pictologics' own wide
output. The reader, scanner, and extra columns are metadata: for example, use
`batch="manufacturer"` for the batch-effect checks, and `roles={"observer": "reader"}`
for a two-reader study.

## Current limitations

- **Keep CSV/JSON exports as independent result archives.** New Pictologics result
  tables carry an exact-value backup in saved scenes; with the extension loaded,
  validated backups restore full numeric precision after scene reload. User edits
  update that backup. Older scenes without a backup cannot recover digits already
  rounded by Slicer's default table writer. Invalid/mismatched backups leave the
  loaded table unchanged and show a warning in **Browse results and provenance…**
  and before an export. Slicer's scene table files cannot keep `"`, `#`, tabs or
  line breaks in text. So the results table stores `"` and `#` as the full-width
  `＂` and `＃`, which look the same, stores tabs and line breaks as spaces, and
  drops spaces at the ends of names and IDs.
  Standalone tables saved through Slicer's generic TSV/CSV writer do not carry the
  backup—use the module's **Export table as CSV or JSON…** for full precision.
- One scalar 3D volume is processed per run; vector and 4D images are out of scope.
  To process many cases, use the Batch section or a script (see above).
- A batch reads files that Slicer can load (for example NIfTI and NRRD), not DICOM
  folders.
- The extension accepts segmentation regions and whole-volume mode, not multi-label
  labelmap selection.
- Nonlinear parent transforms are rejected. Resample with an explicit interpolation
  choice before running. Linear transforms are hardened into temporary geometry.
- Cancellation is at the CLI-process/job boundary. The Pictologics API has no
  cooperative progress/cancellation callback, so a running native kernel cannot
  report fine-grained progress. Multi-ROI jobs report completed-ROI percentages;
  single-ROI jobs display an indeterminate busy indicator until the package returns.
- The in-app builder has a fixed step order and one filter in each configuration.
  Mask binarization, rounding, separate texture distances for GLCM, NGTDM and NGLDM,
  IVH bins, more than one feature step, and a different step order need a custom
  YAML/JSON file. Before Pictologics is installed, **Validate** does only a quick
  structural check.
- Without the crop, Pictologics resamples the whole scan for each region. Large scans
  with fine resampling spacing can then need several gigabytes of memory. With the
  crop, an axis whose voxel size is not a whole multiple of the new spacing can need a
  wide box, or the whole axis, to keep the grid (see "Use less memory").
- The long table adds provenance columns (run, ROI, status, and versions) to the
  Pictologics names. Wide feature names match Pictologics exactly.
- `grow_mask(nearest_roi=true)` in a file is rejected, because this extension
  processes ROIs independently and cannot keep rings of touching ROIs apart.

Numba 0.63 and later have no Intel Mac builds, so Intel Slicer on macOS (also on Apple Silicon through Rosetta)
uses older Numba and NumPy versions than Linux, Windows and native Apple Silicon.
The exact versions for each system are in the
[runtime constraints](../PictologicsSlicer/constraints-pictologics.txt). The
release workflow publishes them only after all compatibility checks pass.
