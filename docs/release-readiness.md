# Release readiness

Review date: 2026-09-29. Extension version remains **0.1.0**; the existing job
manifest schema is **1** and result-payload schema is **2**. This review changes
none of those versions.

## Pre-publication consolidation snapshot (2026-09-29)

- **Published versus local at review:** GitHub's live `main`, read on 2026-09-28, was
  [`7a912cc`](https://github.com/martonkolossvary/SlicerPictologics/commit/7a912cc0ac4b6686753e96e7b148217921bdc208).
  The local base was `b0b5f62`, **14 commits ahead**, plus the changes
  reviewed here. Existing green GitHub runs did not qualify this newer local code.
  The dated entries below are historical evidence, not a claim that all current
  functionality has been published.
- **Implemented locally:** ROI intensity/outlier refinement, six image filters,
  reader/scanner/custom result columns, optional grid-aligned ROI cropping, and GUI
  batch processing. Profiles, readable results/provenance, and run feedback are
  already part of the earlier published milestone.
- **Consolidation fixes:** filter defaults no longer share mutable parameter state;
  profiles reject malformed or unrepresentable filter values even when filtering
  is disabled; invalid/duplicate result-column names fail cleanly. Cropping falls
  back to the full image for cubic interpolation, periodic filter boundaries,
  filter-spacing overrides, and non-leading/repeated resampling. Memory warnings
  use a conservative full-volume estimate and reappear for larger batch cases.
  Batch processing restores the previous inputs and rejects blank/unreadable
  study folders; restoration is discarded when the original scene closes.
- **Validation:** 506 portable tests and 328 subtests pass, with 100% scoped
  library/worker coverage. Ruff, Mypy (14 source files), syntax checks, and
  `git diff --check` pass. The published Pictologics 0.5.1 API gate passes with
  1,020 described configuration-feature rows, all six filter smoke checks, and
  numerical ROI-refinement checks. **All 32 Slicer 5.12.4 integration tests passed
  on macOS with no skips** (506 seconds, successful exit), including real
  asynchronous extraction, GUI/scripted batches, crop parity, refinement, and
  YAML validation. After removing the now-unused optimistic crop estimator,
  the final fast suite passed again (26 passed, six opt-in extraction checks
  skipped). Tests used isolated scenes/settings, not the normal Slicer session.
- **Publication boundary:** no commits, pushes, new images, ExtensionsIndex PRs,
  or public releases were made during this consolidation review.

The maintainer subsequently authorized committing and pushing this milestone on
2026-09-29. Qualification must be assessed on the exact pushed revision. This does
not authorize ExtensionsIndex submission, a tagged public release, or new imagery;
the previously approved 2026-09-25 workflow screenshot is included unchanged.

## Catalog identity, icon, and screenshots

- Catalog identifier and CMake project name: **Pictologics**, with the Tier-1
  descriptor in [`Pictologics.json`](../Pictologics.json). The repository remains
  `SlicerPictologics`; internal modules and private dependency paths are unchanged.
- CMake and the catalog agree on **Informatics**. The catalog description explains
  intensity, shape, and texture measurements, provenance, and research-only use.
  The module contributor now matches the extension metadata.
- The GitHub repository has the required `3d-slicer-extension` topic (updated and
  read back through the GitHub API).
- The catalog references the published 128-pixel approved PNG. The GUI explicitly
  selects the matching 256-pixel PNG; only that icon is listed in the module's
  CMake resources. Previous designs and reusable exports remain in source control,
  outside the installed runtime resources. The bundle ZIP and all manifest hashes
  have been checked after the documentation update.
- Local validation: **498 tests and 151 subtests passed**, 100% scoped library/worker
  coverage, scoped Ruff, Mypy, and syntax checks. **Sixteen integration tests passed in Slicer
  5.12.4 on macOS**, including actual GUI/CLI discovery, icon identity at
  16/32/128/256 pixels, real asynchronous extraction, actual table-view binding,
  readiness recovery, timer/cancellation/failure cleanup, profile save/load/copy,
  read-only results filtering, and a real multi-ROI GUI run loaded from a saved
  profile, with both ROI names observed live and actual processing logs inspected
  through the results browser. The Slicer process exited successfully. A subsequent
  fast run also passed after the final UI sizing and overwrite-confirmation changes
  (14 passed, the two opt-in extraction tests skipped).
- The published identity/icon changes (`dc63b86`) passed all five GitHub CI jobs:
  [qualification run](https://github.com/martonkolossvary/SlicerPictologics/actions/runs/35590611518).
- Two high-resolution [catalog screenshots](screenshots/README.md) show genuine
  extraction workflows. The maintainer-approved workflow image uses Slicer's public
  MRHead MRI with two illustrative ROIs (170 features each; all 340 rows successful).
  The unchanged results-table image is from a separate synthetic CT-like phantom
  run. Captions distinguish the examples, and both reproduction scripts are
  included. Screenshots and branding masters are not runtime module resources.
- Screenshot acceptance exposed a first-run results-display bug: table selection
  was propagated before the table view existed. The view is now created first.
  The new Slicer regression test fails on the original implementation and passes
  on the fix, checking both first display and replacement with another table.
- Native visual acceptance: the new icon is visible in Slicer's module selector;
  light/dark previews at the four sizes were inspected. These were isolated test
  sessions, not changes to the user's saved Slicer settings.
- The new discovery assertion exposed an old launcher gap: repeating the singular
  `--additional-module-path` only supplied the last path. CI, CTest, and the runner
  instructions now use one plural `--additional-module-paths` followed by both
  directories. The existing CLI tests could pass without GUI discovery; the new
  regression test explicitly requires both modules.
- The full upstream ExtensionsIndex validator passed against a fresh clone of
  published commit `74c7320`: schema, format, name, category, repository name/topic,
  SCM URL, CMake metadata, license, dependencies, public icon, and both screenshot
  URLs. The clone measured **64.4 MiB**, below its 100 MiB limit. The validator was
  identical to upstream `main` (Git blob `c22e9aba7cc32129398fe396f98830f1dcdc4bc4`).
  This validates submission metadata, not binary packaging or catalog acceptance.
- The screenshots and table fix are published as `74c7320`; their GitHub
  [qualification run](https://github.com/martonkolossvary/SlicerPictologics/actions/runs/35629958644)
  passed all five jobs: quality/coverage, released wheels on three desktop
  platforms, and real Slicer on Linux, including the new table-view regression.
- Maintainer visual approval is required before publishing any further tutorial
  or catalog images. The MRHead workflow replacement received explicit visual
  approval on 2026-09-22. Its exact approved bytes replace the original workflow
  PNG. The earlier results screenshot is unchanged; no unreviewed replacement is
  included in this update.

Packaged installation/update testing and the ExtensionsIndex pull request remain
outstanding. Source-module acceptance is not an Extension Factory package build.
This Python-only extension does not require a local Slicer build tree before
submission; the factory-produced packages still need clean-install verification.
See the [packaging/submission checklist](extensions-index-submission.md).
The original stabilization evidence below is retained as the 2026-09-19 baseline.

## Stabilized baseline

- Pictologics **0.5.1**, installed from the published PyPI wheel into immutable,
  extension-owned environments. Slicer's shared packages are not replaced.
- Reinstalled **Slicer 5.12.4**, Python 3.12, Intel/Rosetta on macOS:
  private installation, API/full-JIT probes, and fresh-process reuse without a
  reinstall passed. No Pictologics module was imported into the GUI interpreter.
- All six real Slicer integration tests passed, including oblique anisotropic
  geometry, shared linear transforms, NIfTI staging, asynchronous worker PID
  observation, result validation, table commit, and cleanup.
- Slicer's CLI node returns integer percentage progress; the widget must not scale
  it by 100 again. The regression test checks 0, 1, 25, 50, 75, and 100. A single ROI
  retains an indeterminate indicator because upstream has no progress callback.
- The existing official/native IBSI identifiers, long package feature names,
  preprocessing metadata, and export contracts are preserved.
- 429 local tests passed, with 100% coverage of the Slicer-neutral library and CLI
  worker (not 100% GUI coverage); Ruff and strict scoped Mypy passed.
- The complete [GitHub qualification run](https://github.com/martonkolossvary/SlicerPictologics/actions/runs/35464267250)
  passed all five jobs: quality/coverage, released-wheel checks on Windows, macOS
  and Linux, and all six real Slicer integration tests on Linux. The download is
  pinned to Slicer 5.12.4 and verified against its official SHA512 checksum.
- Repository-only YAML/workflow tests stay in normal-Python CI, not CTest:
  a clean Slicer does not include PyYAML, and no extra GUI dependency is installed.

## Release adoption

The [adoption workflow](../.github/workflows/adopt-pictologics-release.yml) polls PyPI
every six hours, and also supports manual and repository-dispatch triggers.
Its live [0.5.1 discovery/no-op run](https://github.com/martonkolossvary/SlicerPictologics/actions/runs/35464119046)
passed. At the baseline review there was no newer stable release with which to
demonstrate a real automatic version-advancing publication.

Each candidate must pass the same [qualification workflow](../.github/workflows/compatibility.yml)
as ordinary CI: workflow lint, unit/coverage/type checks, private-wheel API/JIT and
numerical parity on Linux/Windows/Intel macOS, and actual Slicer on Linux. Publication
has its own write-enabled job, changes only the exact requirement, rechecks yank
status, and fails if the validated main-branch revision has been superseded.
No cross-repository PAT is needed. No repository protection settings were changed.

This updates the extension repository, not already installed source copies.
Development users pull the new extension code; catalog users will update the extension
through Slicer once catalog distribution is available. Then the module installs the
new adopted wheel. Startup never silently upgrades dependencies.

## Readiness and run-feedback usability pass

- Input readiness now has its own label, including a summary of whole-volume,
  selected-segment, and configuration selections. Correcting invalid inputs clears
  that validation message without overwriting the previous run's outcome.
- Runs show setup/execution/result-loading phases, exact current ROI number/name,
  and monotonic elapsed wall time including setup. The clock freezes on terminal
  outcomes and is stopped on scene close or module cleanup. Cancellation feedback
  is not overwritten by late progress updates.
- Existing ROI-boundary percentages and single-ROI indeterminate progress remain;
  no estimated completion time or within-kernel progress is claimed. A compact
  worker stdout marker bridges Slicer's missing Python progress-message accessor.
- README processing-log wording now distinguishes public `save_log()` JSON export
  from the missing public in-memory getter. The worker's private `_log` fallback
  remains unchanged; replacing it is a separate compatibility change.
- Local quality instructions now contain the tracked commands used by CI, without
  relying on the ignored `dev/pre_push.py` helper. Neither result schema nor package
  pin has changed. No catalog/tutorial screenshot was modified.
- This usability pass has been validated locally; GitHub CI and published catalog
  validation linked above describe earlier commits. The usability milestone was
  subsequently published as `7a912cc`; all five jobs in its
  [GitHub CI run](https://github.com/martonkolossvary/SlicerPictologics/actions/runs/35881923998)
  passed, including real Slicer on Linux and released wheels on three platforms.

## Results inspection and saved profiles

- **Browse results…** opens a read-only snapshot of the selected table, with
  feature/code/preprocessing search and conjunctive ROI, configuration, family,
  and status filters. Pages contain up to 200 rows. ROI identity includes the run,
  so appended runs with identical ROI names remain distinguishable.
- Selecting a row shows feature values, both IBSI identifiers, the package's
  feature key and long name, preprocessing, configuration hash, software versions,
  matching processing logs, requested/effective parameters where recorded, and
  ROI errors. Missing or ambiguous provenance is reported rather than borrowing
  details from another run. Patient-derived text is displayed as plain text.
- Browsing never modifies the canonical table or its schema. Existing exports
  still include the entire selected table, not just the filtered snapshot. Refresh
  reloads the selected table and resets filters; scene close clears the snapshot.
- **Configuration profiles** provides named **Load…**, **Save…**, and **Save copy…**
  actions for selected standard presets and the optional in-app configuration.
  Loading validates every setting before changing controls and leaves patient,
  image, ROI, and output selections untouched. Save copy protects the original
  file; filename-extension normalization also checks before overwriting a file.
- Profiles use a separate settings-only JSON format. They are not upstream
  pipeline configuration files, dependency pins, or a multi-configuration editor.
  Advanced YAML/JSON files remain reusable through the existing file mode. Profile
  names do not rename native configurations in results, and edits require an
  explicit save. No patient/scene identifiers are automatically stored in profiles.
- Extension/result contract **0.1.0**, the Pictologics **0.5.1** requirement, and all
  catalog/tutorial images remain unchanged. On 2026-09-23, the normal Slicer session
  discovered both modules through saved paths, opened the new controls, and reused
  its existing private 0.5.1 installation. The maintainer authorized publishing this
  milestone to the existing GitHub repository, while holding catalog submission
  and broader release until after the next functional improvements.

## Guided ROI refinement (local follow-up)

- The in-app builder now offers optional intensity-range resegmentation and
  sigma-based outlier filtering, with independent explicit `both`, `intensity`,
  and `morph` mask targets. Both steps default to disabled, so existing presets
  and default in-app calculations are unchanged.
- Controls explain inclusive bounds, image intensity units, effects on morphology,
  and the fixed resample/refine/discretise/extract order. Invalid active settings
  block Run; original images and segmentations are not modified. Empty required
  masks remain worker-reported errors rather than silently reverting to the ROI.
- Settings persist in the scene parameter node and named profiles. Original
  version-1 profiles migrate with refinement disabled; invalid or partly specified
  new profile fields are rejected before changing the UI.
- **534 portable tests and 151 subtests passed**, with 100% scoped library/worker
  statement coverage; Ruff, Mypy, and syntax checks passed. **All 17 Slicer 5.12.4
  integration tests passed**, including the new controls, legacy-profile loading,
  actual two-ROI extraction, readable refinement logs, and independent checks of
  mean intensity and voxel-counting volume after refinement.
- The released **0.5.1** wheel passed the expanded API/configuration gate in Slicer's
  standalone Python. Independent mean/volume expectations verified all three mask
  targets and confirmed source arrays were not changed. This gate is used by the
  existing multi-platform release-adoption workflow when these local changes are
  eventually published.
- This follow-up does not change the extension/result version, package pin, or any
  tutorial/catalog images.

## Correctness and packaging fixes (2026-09-25)

- **Shared results.** Pictologics 0.5.1 can copy wrong values from one configuration
  to another when its deduplication reuses results. Example: an in-app configuration
  that differs from a checked preset only in voxel validity got all 170 preset values.
  The worker now creates the pipeline with `deduplicate=False`. The in-app values then
  match an independent run (170 of 170). The package fix is in the sibling Pictologics
  working tree for a later release; the extension does not depend on it.
- **Whole volume off by default.** The presets resample the entire scan for a
  whole-volume region, which can need several gigabytes of memory for a large CT.
- **FBN bin count.** The in-app builder rejects a decimal bin count. Before, it cut
  the decimals off without a warning.
- **Short folder names.** New private environments use `<version>-<8 hex>`. The
  deepest package file then stays within the Windows 260-character path limit for user
  names up to about 36 characters. Existing environments keep working through the
  active pointer.
- **Old versions removed.** After a new environment becomes active, the extension
  deletes the older ones. While a job runs, the deletion waits; module start and the
  next installation try again.
- **Build-farm tests.** Four test files used pytest-only syntax, which the CTest
  runner in Slicer cannot import or collect. They now use `unittest`.
- **Catalog text.** The description names radiomics, and the module help links the
  documentation.
- **Memory warning.** Before a run, the module estimates the resampled scan size for
  the checked presets and the in-app or file configuration. When one copy needs more
  than about 1 GB, it asks before anything starts.
- **Worker module title.** Slicer cannot hide a CLI module, so its title is now
  **Pictologics Worker (internal)**.
- **Step-list check.** The release gate compares the in-app lint's copy of the step
  and parameter names with `RadiomicsPipeline._VALID_STEPS` and stops adoption on a
  difference. It passed against the released 0.5.1 wheel and caught a planted
  difference.
- **Homepage.** The README now starts with use; developer details moved to
  [`development.md`](development.md).
- **Catalog check.** The official ExtensionsIndex check script (blob
  `c22e9aba7cc32129398fe396f98830f1dcdc4bc4`) passed on the published `main`. On the
  local `catalog-readiness` branch, all repository-content checks passed (69.6 MB);
  only the URL-scheme check failed, because that run used a local `file://` address.
  Run it again on the pushed commit.
- **Column names.** The long table now uses `config` and `family`, the names of
  Pictologics' `describe_features()`, instead of `configuration` and
  `feature_family`. The result format number is 2. Tables in format 1 cannot be
  appended, browsed, or exported. A planned Pictologics release renames the full-key
  column of its long `format_results` layout from `feature_name` to `feature_key`, so
  that all names agree.
- **Validation.** 463 portable tests and 241 subtests passed, with 100% scoped
  library/worker coverage, Ruff, and Mypy. The worker smoke and geometry-parity
  scripts passed against the local Pictologics source. All 20 Slicer 5.12.4
  integration tests passed on macOS, including both real-worker tests with the
  installed Pictologics 0.5.1 wheel.
- **Real update run.** In the isolated `--disable-settings` profile, the update
  action installed Pictologics 0.5.1 from PyPI, passed both environment probes,
  activated `0.5.1-c8ea659d`, and deleted the older environment.
- **Workflow screenshot.** A new MRHead capture (real run, 340 rows, all `ok`) was
  approved by the maintainer on 2026-09-25 and replaces the earlier image. It shows
  the profiles section, the readiness line, and the elapsed time. The Qt capture has
  no macOS title bar.

## Batch scripts, file check, and tested versions (2026-09-25)

- **Batch scripts.** `PictologicsSlicerLogic.process()` runs one case to the end
  through the same worker path as **Run radiomics** and returns the table. Each call
  adds its rows and one provenance record. The README example ran unchanged on two
  synthetic cases with three regions: 510 rows, all `ok`, the CSV with its
  provenance and dictionary files, two provenance records, and no image or
  segmentation nodes left in the scene.
- **File check.** **Validate** now runs the worker with `--check-configuration`. The
  worker loads the file as a run does, so YAML and JSON files get the Pictologics
  checks. One check takes about 2 seconds. For a YAML file, the memory estimate uses
  the effective configuration from the check. Before Pictologics is installed,
  **Validate** does the structural lint only.
- **Tested versions.** Two private installs of Pictologics 0.5.1 on the same Mac had
  different fonttools (4.65.0, 4.66.0) and pyparsing (3.3.2, 3.3.3) versions.
  `constraints-pictologics.txt` now pins all 25 distributions to the versions that
  the integration suite used. The installer and the CI gates give the file to pip
  with `--constraint`. For each candidate release, the adoption workflow resolves a
  new file once, runs every gate with it, and publishes it with the pin. A real
  install through the module's installer, into an empty temporary folder, got
  exactly the 25 pinned versions and passed both environment probes.
- **Validation.** 478 portable tests and 248 subtests passed, with 100% scoped
  library/worker coverage, Ruff, and Mypy. actionlint 1.7.12 with ShellCheck 0.10.0
  passed on the workflows; it caught a planted shell mistake. The API check, the
  worker smoke (170 rows), and the geometry parity (170 features) passed on the
  released 0.5.1 wheel. All 23 Slicer 5.12.4 integration tests passed on macOS,
  including the four tests that use the installed Pictologics 0.5.1 wheel.

## Columns, filters, crop, and batch (2026-09-26)

- **One meaning per column.** An append whose configuration name the table already
  holds with other effective settings now goes to a new table. Before, one
  `config__feature_key` column could hold values of two settings.
- **Catalog file name.** The CSV export writes `<name>_catalog.csv`, so
  `features.csv` gets `features_catalog.csv`, which eigenradiomics finds. The README
  recipe loaded a real export with the catalog found automatically, 170 features, and
  grouping by patient.
- **Result columns.** Every row gets `reader`, seven scanner columns, and the user's
  `name = value` columns after the fixed columns. The scanner details came out right
  from a real DICOM import (a synthetic CT series in a temporary DICOM database) and
  from a dcm2niix JSON file. eigenradiomics reads these columns as row information,
  for example `batch="manufacturer"` and `roles={"observer": "reader"}`.
- **Image filters.** The in-app builder offers mean, LoG, Laws, Gabor, separable
  wavelet, and Simoncelli filters, after ROI refinement and before discretisation. The
  release gate builds each filter, loads it with warnings as errors, and runs it on
  the released 0.5.1 wheel and requires a finite mean-intensity result. This is a
  compatibility smoke check, not independent numerical validation of every filter.
- **Crop around each region.** A plain crop moved the resampling grid: on MRHead
  with an off-center 12 mm sphere, only 15 of 170 values stayed equal (median
  difference 0.65%, largest 20%). A grid tolerance of 0.001 voxel still left 0.2%
  differences. With the final grid rule (error below 1e-9 voxel), 152 of 170 values
  were equal and all 170 agreed within one part in a billion, and the worker used
  0.48 GB instead of 2.4 GB. The crop is off by default.
- **Batch in the window.** The Batch section runs every case folder through the
  normal background run and removes each case from the scene afterwards. A real
  two-case batch added the rows of both cases, with the reader column, to one table.
- **Validation.** 503 portable tests and 302 subtests passed, with 100% scoped
  library/worker coverage, Ruff, and Mypy. The API gate, including the filter check,
  passed on the released 0.5.1 wheel. All 30 Slicer 5.12.4 integration tests passed on
  macOS, including the 6 that use the installed Pictologics 0.5.1 wheel. The README
  batch example ran unchanged: 3 regions, 170 feature columns, and all 3 export files.

## Refinement regression recheck (2026-09-28)

- The released-wheel gate now checks all nine combinations of the range and
  outlier mask targets, including different targets for the two steps. Each
  mask's expected values are calculated independently with NumPy.
- Checks cover mean, population variance, minimum, maximum, and voxel-counting
  volume, as well as unchanged input arrays. The additional intensity statistics
  catch missing outlier removal even when the ROI is symmetric and its mean
  remains unchanged.
- The expanded gate passed against the installed, published **Pictologics 0.5.1**
  wheel in Slicer's standalone Python. A deliberately omitted intensity-only
  outlier step was rejected by the variance assertion.
- The current working tree passed **503 portable tests and 302 subtests**, with
  100% scoped library/worker coverage, Ruff, Mypy, and syntax checks. Existing
  batch, crop, filter, and result-column changes were preserved. These regression
  additions do not change runtime behavior, dependency versions, or images.
- **All 30 Slicer 5.12.4 integration tests passed**, with no skips and a successful
  process exit (429 seconds). This includes the real two-ROI refinement run,
  profile persistence and legacy loading, numerical results, batch runs, and
  cleanup. The tests used an isolated scene/settings profile.
- The normal Slicer session discovered and opened Pictologics. Interactive visual
  review was initially interrupted by the Mac locking. After unlocking, a
  temporary settings-only profile opened the builder: both refinement groups,
  their enabled/disabled states, range fields, and independent mask-target
  selectors were inspected. No publication or new screenshot was made.

## Interactive decimal-entry fix (2026-09-28)

- Typing `1.5` in the sigma editor produced `1.000`: each GUI change wrote to the
  parameter node, whose observer immediately reformatted the active editor. The
  same refresh also recreated dynamic image-filter editors while they were in use.
- GUI-originated write-back now suppresses only its own immediate GUI refresh,
  keeping the live editors intact. External parameter-node changes and profile
  loads continue to refresh the controls normally; the guard resets in `finally`.
- A real Qt key-event regression reproduced `1.0 != 1.5` before the fix and passed
  afterward. It also checks typing `2.75` into a filter editor without replacing
  that widget and confirms an external scene update still changes the sigma.
- After the fix, **25 non-extraction Slicer integration tests passed** (six opt-in
  real-worker checks skipped), along with **503 portable tests and 302 subtests**,
  100% scoped coverage, Ruff, and Mypy. The earlier full 30-test real-worker run
  above predates this UI-only fix.
- With explicit maintainer permission, the normal Slicer session reloaded the
  corrected module. Native keyboard entry retained **1.500** in the outlier sigma
  field and **2.7500** in the image-filter sigma field after moving focus. This
  completes the post-fix visual verification, in addition to the Qt regression.
- The temporary settings-only review profile was reloaded to restore defaults:
  both refinement steps and image filtering are off, bounds are blank, both mask
  targets are `both`, and outlier sigma is 3.0. The refinement panel remains open.
  The scene was empty throughout; no images or results were changed. Source
  changes remain local, with no publication or new tutorial/catalog images.

## Reassessment: next priorities

The requested functionality now forms a usable local release candidate. Prioritize
release qualification and delivery over adding more controls. The maintainer's hold
on catalog submission and broader release remains in force.

1. **Save and synchronize this milestone, with maintainer approval.** Include the
   new helper/test files, not just tracked modifications. Keep runtime changes and
   their tests together, then the readiness/documentation update. Do not rewrite
   the existing 14 local commits. Push only after approval and require all five
   qualification jobs on the resulting GitHub revision; scheduled dependency
   checks on the older `main` are not sufficient.
2. **Complete acceptance before catalog submission.** Validate actual Slicer on
   Windows and Slicer Preview, plus a clean package install/restart/update. Check
   multiple ROIs, profile loading, filtering, batch failure/cancel/scene-close,
   append/export, and memory warnings. Test packaged module discovery/resources,
   not only a checkout added to Additional module paths.
3. **Finish distribution when authorized.** Revalidate the final catalog JSON,
   approved icon and screenshot URLs at the exact published revision; verify
   Extension Factory packaging; then submit ExtensionsIndex for Preview and the
   supported Stable branch. Extensions Manager install/update is the remaining
   link between tested automatic dependency adoption and delivery to users.
4. **Next functional iteration, after qualification:** add an ROI quality summary
   (voxel counts before/after refinement and empty/tiny-ROI warnings), then batch
   preflight and a persistent per-case success/failure report. These would help
   users audit exclusions and recover failed cases. Fine-grained extraction
   progress still needs an upstream callback API. A general multi-step editor is
   lower priority; six guided image filters are already implemented locally.

The sibling Pictologics package is already at published 0.5.1. Its untracked
`notify-slicer-extension.yml` draft was left untouched: the independent schedule makes
that secret-dependent sender unnecessary. Existing Dependabot proposals for checkout,
setup-python, and Codecov are superseded by the adopted action majors; the
create-pull-request action is no longer used.

References: [Slicer distribution guide](https://slicer.readthedocs.io/en/latest/developer_guide/extensions.html#distribute-an-extension),
[submission checklist](https://github.com/Slicer/ExtensionsIndex/blob/main/.github/PULL_REQUEST_TEMPLATE.md),
[Pictologics changelog](https://github.com/martonkolossvary/pictologics/blob/main/CHANGELOG.md).
