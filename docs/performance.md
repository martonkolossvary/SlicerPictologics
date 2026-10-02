# Public examples and performance qualification

The optional developer scripts run actual Pictologics extraction in an installed
Slicer, without building Slicer or installing packages. They do not upload data.
Use separate disposable Slicer processes; never run them in a clinical/research
scene that you need to keep. This is performance observation, not clinical or IBSI
validation, and it does not qualify an Extensions Manager installation.

## Small CT example with two ROIs

[`create_ct_sample_demo.py`](../scripts/create_ct_sample_demo.py) complements the
[existing MRI demonstration](screenshots/README.md). It prepares a real CT image
and two non-overlapping ellipsoidal masks named **ROI A (demo)** and **ROI B (demo)**.
These are illustrative geometric regions, not organ, tumor, or clinical annotations.

The source is Slicer's **CTLiver** sample: Medical Segmentation Decathlon,
`Task03_Liver/imagesTr/liver_100.nii.gz`, distributed under **CC BY-SA 4.0** according
to the [pinned Slicer SampleData acknowledgements](https://github.com/Slicer/Slicer/blob/v5.12.4/Modules/Scripted/SampleData/SampleData.py).
The prepared image is an adaptation of that source and retains its CC BY-SA 4.0
terms; this repository's Apache-2.0 code license does not replace the data license.
Keep the generated `source.json` attribution with the image when sharing it.
See the [CC BY-SA 4.0 terms](https://creativecommons.org/licenses/by-sa/4.0/).

The first download is the full approximately **279 MiB** source, not a tiny network
download. Slicer's downloader checks its SHA-256:
`e16eae0ae6fefa858c5c11e58f0f1bb81834d81b7102e021571056324ef6f37e`.
The script selects 96 axial slices around 55% of the original stack and keeps every
second voxel along all three axes: **256 × 256 × 48**, approximately **1.4 mm** spacing.
The saved compressed image is about **4.8 MiB**; the two masks add about 8 KiB.
Its physical position/orientation are preserved. This nearest-neighbour lattice
decimation changes the sampling grid: do not treat its features as measurements
from the original full-resolution scan. The derivation and exact ROI voxel counts
are recorded in `source.json`. No image binary is added to Git.

From the repository root, with the adopted dependencies already installed:

```sh
PICTOLOGICS_CT_DEMO_OUTPUT="$PWD/local-output/ct-demo-review" \
PICTOLOGICS_SAMPLE_CACHE="$PWD/local-output/public-sample-cache" \
/Applications/Slicer.app/Contents/MacOS/Slicer \
  --no-splash --disable-settings --ignore-slicerrc \
  --additional-module-paths "$PWD/PictologicsSlicer" "$PWD/PictologicsCLI" \
  --python-script "$PWD/scripts/create_ct_sample_demo.py"
```

The output directory must not exist. Substitute the executable path for your
platform. Select the desired configuration, keep both segments checked, then use
**Run radiomics** and export the results before closing. The script does not install
dependencies or start an extraction automatically. It also does not take screenshots.
New captures must remain under ignored `local-output/` until the maintainer has
visually reviewed and approved them; the existing catalog screenshots are unchanged.

## Reproduce the workload matrix

[`benchmark_slicer_workloads.py`](../scripts/benchmark_slicer_workloads.py) uses an
existing qualified private dependency target, with a separate, initially empty
Numba cache. It refuses package installation or updates. The current RSS sampler
requires **macOS or Linux** (`ps`); Windows memory benchmarking is not implemented.

```sh
env -u PYTHONPATH -u PYTHONHOME -u PICTOLOGICS_DEV_SOURCE \
  SLICERPICTOLOGICS_TEST_DEPENDENCY_PATH="/absolute/path/to/existing/private/target" \
  PICTOLOGICS_BENCHMARK_OUTPUT="$PWD/local-output/workload-run-01" \
  PICTOLOGICS_SAMPLE_CACHE="$PWD/local-output/public-sample-cache" \
  /Applications/Slicer.app/Contents/MacOS/Slicer \
  --no-splash --no-main-window --disable-settings --ignore-slicerrc \
  --additional-module-paths "$PWD/PictologicsSlicer" "$PWD/PictologicsCLI" \
  --python-script "$PWD/scripts/benchmark_slicer_workloads.py"
```

Choose a new output directory each time. Optional `PICTOLOGICS_BENCHMARK_CASES`
selects comma-separated `cold,warm,mri,large,crop,multiple,fine,batch,tables` cases.
All are selected by default. `warm` or `tables` also runs the initial CT case.
Every extraction requires actual results for **two ROIs** and no ROI failures.
Repeated CT values and the large-volume crop/uncropped pair must agree within
`1e-9` relative/absolute tolerance. JSON/CSV exports precede removal of the tables;
large-table MRB scenes are also saved. Reports include exact configurations,
versions, source/script hashes, timings, row statuses, and sampled memory.

Most cases deliberately use a controlled **1 mm linear resampling / FBN 32**
configuration with intensity, morphology, texture, histogram, and IVH families.
These are not the named standard presets, which use **0.5 mm**. The separate
fine-spacing case measures 0.5 mm. The multiple-configuration case uses FBN 16
and FBN 32. The MRI benchmark uses MRHead with the same fixture generator as the
CT benchmark, not the differently sized masks in the approved MRI screenshot.

The batch uses ten copies of the same CT fixture through the actual GUI batch
workflow, not ten independent patients. Large-table tests duplicate calculated
values into 10,000 and 100,000 explicitly labelled synthetic rows; they measure
table handling, not additional radiomics extraction. They exercise the real
commit, results browser, filter, pagination, JSON export and scene-save paths.

## Measurement boundaries

- Extraction time includes staging, worker launch/import/JIT, result-table commit
  and JSON/CSV export. Dependency installation, source download/loading, fixture
  preparation and Slicer startup are excluded and must not be inferred from it.
- "Cold" means a new empty private Numba cache, **not** cold operating-system
  filesystem caches. Every extraction still launches a fresh worker process.
- Memory is sampled every 0.5 seconds using numeric PID/parent/RSS columns only.
  Root Slicer RSS and descendant RSS are recorded separately. Their sum can
  double-count shared pages and miss brief peaks; it is not exact peak usage or
  unique physical RAM; compressed/swapped-out pages are not a complete workload
  footprint either. The interval is nominal: scheduling and Python's GIL can delay
  samples. Reported GUI baseline includes other fixture nodes loaded
  in that benchmark scene and normal allocator retention.
- Worker waits have a 15-minute timeout and a 12 GiB sampled process-tree guard;
  the ten-case batch has a 30-minute timeout. These are harness safeguards, not
  hard OS resource limits. Synchronous staging/table operations cannot be
  interrupted mid-call by the guard. No production memory limit is added.
- This bounded matrix does not prove unlimited batch stability, whole-body CT
  capacity, all-filter performance, or results for other hardware/platforms.

## Reproduce mixed CT/MRI batch recovery and memory testing

[`soak_slicer_batches.py`](../scripts/soak_slicer_batches.py) extends the repeated-CT
benchmark through the real GUI batch workflow. It uses five size/modality variants
of the same two checksum-pinned public scans, not independent patients:

- CT slabs: 256 × 256 × 48, 256 × 256 × 96, and 512 × 512 × 192.
- MRHead: its native lattice and every-second-voxel decimation, with origin and
  orientation preserved and spacing doubled.
- Two illustrative ROIs and two all-family configurations per successful case:
  1 mm resampling with FBN 16 and FBN 32 (680 rows for qualified Pictologics 0.5.1).

```sh
env -u PYTHONPATH -u PYTHONHOME -u PICTOLOGICS_DEV_SOURCE \
  SLICERPICTOLOGICS_TEST_DEPENDENCY_PATH="/absolute/path/to/existing/private/target" \
  PICTOLOGICS_SOAK_OUTPUT="$PWD/local-output/mixed-batch-run-01" \
  PICTOLOGICS_SAMPLE_CACHE="$PWD/local-output/public-sample-cache" \
  /Applications/Slicer.app/Contents/MacOS/Slicer \
  --no-splash --no-main-window --disable-settings --ignore-slicerrc \
  --additional-module-paths "$PWD/PictologicsSlicer" "$PWD/PictologicsCLI" \
  --python-script "$PWD/scripts/soak_slicer_batches.py"
```

The output directory must be new. The default six rounds run 30 successful cases,
plus a malformed segmentation, a deliberately invalid worker manifest, and a
missing-segmentation folder. Both real failures must be reported and followed by
successful cases. A second batch completes one case, cancels an observed live
worker, and leaves the next case unstarted. A third batch must then complete all
five variants without restarting Slicer. `PICTOLOGICS_SOAK_ROUNDS=2` through `20`
selects 10–100 successful mixed cases; all three phases still run.

The harness requires exact agreement between reports and feature rows, full
ROI/configuration matrices, no duplicated feature keys, unchanged prior rows and
reports across batches, repeat-value parity within `1e-9`, worker/staging release,
and restored controls. It exports JSON/CSV before closing and saves/reloads all
results and reports in a scene, checking every row and the report selector.

Reports retain per-case timing and scene-node counts, nominal 0.5-second RSS
samples across all three phases, idle checkpoints, fixture attribution/hashes,
configurations, and source hashes. Cases hard-link the read-only fixture files to
avoid multiplying disk storage. Each phase has a 45-minute timeout and the same
12 GiB sampled process-tree guard. These guards cannot interrupt synchronous
staging/commit calls. RSS includes growing result/provenance tables and allocator
retention, so growth alone is not proof of a leak. A successful `report.json` must
also be accompanied by a clean Slicer process exit.

This is opt-in developer testing, not a CI workload or clinical validation. It
does not install dependencies, modify the user's existing Slicer scene, upload
data, capture images, or register the extension.

The first exploratory mixed run (`local-output/mixed-batch-2026-10-02/run-01/`)
completed extraction, expected failures, cancellation, and recovery, but failed
its final saved-report readback. Slicer's generic TSV storage did not escape the
real multiline load-error message. Batch reports now retain authoritative JSON
rows in their scene metadata and reconstruct the locked display table on import;
focused tests also cover tabs, quoted/Unicode names, exact elapsed times, and
legacy reports without JSON rows. Existing damaged legacy reports cannot be
reconstructed from an already-corrupted TSV; retain their independent exports.

That first run's memory numbers are not qualification evidence: a call-recording
test spy retained every input image wrapper after scene cleanup. The corrected
harness uses plain method replacements that do not retain arguments. It also
preserves the original failure if a best-effort recovery export subsequently
fails. Initial logs/results are retained rather than overwritten.

### Mixed-batch observations on 2026-10-02

The corrected full run is in `local-output/mixed-batch-2026-10-02/run-02/`, with
its launch log alongside that directory. It used the same host/runtime documented
below, source based on `a756dff` plus the report-persistence fix, and an initially
empty private Numba cache. Script/runtime hashes are in `report.json`. The process
exited **0**, with all assertions passing.

| Phase | Verified outcomes | New feature rows | Seconds |
| --- | --- | ---: | ---: |
| Mixed CT/MRI, six rounds | 30 completed, two expected failures, one skipped | 20,400 | 243.95 |
| Cancellation | One completed, one live worker cancelled, one not started | 680 | 15.18 |
| Recovery without restart | All five size/modality variants completed | 3,400 | 35.01 |

The phase times include verification and JSON/CSV exports; fixture preparation,
sample loading, idle checkpoints, and final scene round trip are separate. The
first cold case took **82.70 seconds**. Subsequent mixed-batch case timings include
file loading, staging, worker execution and table commit, but not phase-end exports:

| Reused-cache fixture | Median seconds | Observed range, seconds |
| --- | ---: | ---: |
| Small CT | 3.45 | 3.15–3.93 |
| Medium CT | 3.97 | 3.55–4.43 |
| Larger CT, 50.3 million voxels | 11.87 | 11.33–12.35 |
| Coarse MRHead | 3.03 | 2.81–3.59 |
| Native MRHead | 3.81 | 3.45–4.37 |

All **24,480 rows** from 36 successful cases and all **three reports** survived
scene save/reload exactly, including the multiline load error. Previous rows and
reports were unchanged by later batches. Repeated fixture values agreed within
`1e-9`. Workers exited and staging directories were removed before recovery began.
Case-boundary volume, segmentation, CLI and display node counts returned to zero;
storage-node counts stayed flat. Final owned-scene cleanup left none of the
monitored node classes behind.

There were **462 RSS samples** with one failed sampling attempt. The simultaneous
Slicer-plus-descendant peak was **3.96 GiB**; individual Slicer and descendant
peaks were **2.58 GiB** and **1.51 GiB** (do not add separately timed peaks).
Slicer idle RSS was **1.86 GiB** initially, **2.43 GiB** after the mixed phase,
**2.50 GiB** after recovery, and **2.56 GiB** after final scene release. Descendant
RSS was zero at idle checkpoints. The retained GUI RSS is not explained solely by
live scene nodes and must not be called a proven leak-free plateau; allocator,
runtime, and UI retention need longer dedicated profiling to distinguish them.
This bounded run supports several-GiB working-memory guidance, not a minimum RAM
specification or a guarantee for hundreds of independent patients.

## Observations on 2026-10-01

Host: **Apple M4 Pro, 48 GiB RAM, 14 logical CPUs**, macOS 27.0.1. The installed
**Slicer 5.12.4 (`4e21c19`) runs x86_64 under Rosetta**, with Python 3.12.10 and Qt
5.15.18; this is not a native ARM performance claim. Extension 0.1.0 and its
qualified private Pictologics 0.5.1 wheel were used. Runtime source was the published
diagnostics milestone `067672f`; only developer scripts/documentation/tests were added.

The complete successful repeat is retained locally in
`local-output/performance-2026-10-01/matrix-02/`, with its launch log alongside it.
Every extraction returned `ok` rows; repeat and cropped/uncropped comparisons passed.
The process exited **0** after all exports, scene saves, and cleanup.

| Actual extraction workload (two ROIs) | Rows | End-to-end seconds | Sampled worker-tree peak, GiB | Sampled Slicer + workers peak, GiB |
| --- | ---: | ---: | ---: | ---: |
| Small CT, empty Numba cache, 1 mm | 340 | 86.62 | 1.69 | 3.37 |
| Same CT, reused cache, repeat 1 | 340 | 3.12 | 0.43 | 2.13 |
| Same CT, reused cache, repeat 2 | 340 | 2.86 | 0.55 | 2.27 |
| MRHead, 256 × 256 × 130, 1 mm | 340 | 3.46 | 0.63 | 2.44 |
| Larger CT, 512 × 512 × 192, 1 mm | 340 | 11.07 | 1.79 | 3.89 |
| Same larger CT, crop enabled | 340 | 9.66 | 1.46 | 3.55 |
| Small CT, two configurations, 1 mm | 680 | 3.46 | 0.53 | 2.64 |
| Small CT, finer 0.5 mm spacing | 340 | 4.09 | 1.29 | 3.40 |
| Ten-case CT batch, 1 mm, crop enabled | 3,400 | 56.24 | 0.37 | 2.50 |

The large CT contains **50.3 million input voxels**. Each of its two masks contains
an independently extracted region; the small CT masks contain **3,702 voxels each**.
The larger CT pair each had one failed RSS sampling attempt during staging, so its
memory figures are particularly approximate. No other case in this run had a
sampling error. Cropping kept all 340 values within `1e-9` tolerance, but it did not
remove full-volume staging: staging alone took about **4.5 seconds** in both runs.
Worker execution fell from **6.48 to 5.09 seconds**. Crop savings depend on the grid
and the configuration and should not be promised as a fixed percentage.

| Synthetic table scale | Commit | Browser load | Search | Next page | JSON export | MRB save |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 10,000 rows | 0.55 s | 0.31 s | 0.065 s | 0.016 s | 0.49 s | 0.17 s |
| 100,000 rows | 5.83 s | 3.07 s | 0.182 s | 0.015 s | 5.17 s | 0.55 s |

The 100,000-row JSON was approximately **80 MiB**; the compressed scene, which also
contains the small public CT fixture, was **41 MiB**. Slicer RSS grew by about
**325 MiB** between the first and highest samples of that table case. Absolute GUI
RSS fell during the preceding batch as macOS reclaimed/compressed pages; therefore
the table's lower absolute RSS is not evidence that its total memory demand was
lower than the earlier extraction cases.

A separate fresh Slicer reopened both saved scenes and compared every row field
and every numeric value to the prior JSON exports: **10,000 and 100,000 rows, zero
binary64 mismatches**. Load plus exhaustive comparison took 0.69 and 5.14 seconds,
respectively. These are observed combined check times, not pure file-load timings.

The initial full run (`matrix-01`) completed its measurements but crashed during
shutdown: its standalone parentless Qt dialog was explicitly deleted by the test
harness. The harness now uses the normal application-owned results browser and
cleans up its observers before exit; the full repeat above exited successfully.
Scene readback also exposed an empty singleton name in the temporary logic subclass;
the harness now preserves the normal `PictologicsSlicer` module name. These are
developer-harness corrections, not changes to the shipped module. Initial logs
are retained, and an internal `report.json` success flag alone must never be used
as proof of successful process exit.

The final focused check after preserving the normal module name also exited 0:
ten batch cases completed in 32.64 seconds, and the 100,000-row table took
5.12 seconds to commit, 2.84 seconds to open, and 4.52 seconds to export. Its
evidence is retained under `local-output/performance-2026-10-01/final-ui-check/`.

## Practical guidance and follow-up

- **Allow roughly 1–2 minutes for first extraction** on this host after an empty
  compilation cache; measured successful cold starts were about 84–87 seconds.
  Installation/download time is additional. Repeating the small CT used about
  3 seconds. A package/compiler/cache change can require compilation again;
  do not promise the same times for other images, machines or filters.
- **Budget several GiB beyond the image file size.** The measured extraction
  process-tree peak approached 4 GiB, before accounting for other applications,
  OS memory, missed transient peaks or compressed pages. This does not establish
  a minimum supported RAM size. The module's 1 GB prompt estimates one floating-point
  image array, not total RAM. Leave substantial headroom and avoid extrapolating
  these results to whole-body CT or larger 0.5 mm scans.
- **Start with two ROIs and one configuration.** Check the output, then add
  configurations or batch cases. Halving spacing can multiply the resampled voxel
  count by eight; the small example does not qualify all fine-spacing workloads.
  Inspect provenance to see whether cropping actually occurred.
- **Use batches, but retain exports.** All ten cases completed and produced two
  ROIs each. The first exploratory matrix took about 31 seconds for the same batch,
  compared with 56 seconds in the successful full repeat, showing background-host
  variability. Neither run is a controlled statistical benchmark or an unlimited
  leak/soak test. Hundreds of heterogeneous cases remain unqualified.
- **Large tables are usable, with explicit operation feedback.** Pagination and
  search stayed fast at 100,000 rows; committing, opening and exporting took seconds.
  The module now locks controls, shows the operation and row count, and restores the
  prior state after each synchronous table operation. A persistent per-case batch
  report records outcomes and elapsed times; it is saved with the scene or exportable
  as JSON/CSV. These operations remain synchronous, so the feedback is status and
  cancellation-safe locking rather than a fabricated percentage. Do not change
  feature precision to gain speed.

The public CT preview and all generated images/data remain local. This work does
not submit ExtensionsIndex, build a distribution archive, or authorize new catalog
images for publication.
