# Release readiness

Review date: 2026-10-04. Extension version remains **0.1.0**; the existing job
manifest schema is **1** and result-payload schema is **2**. This review changes
none of those versions.

## Native Windows application validation (2026-10-02 to 2026-10-04)

The [Windows validation report](windows-validation.md) records actual official
Stable 5.12.4 application testing on native Windows x64, separately from GitHub's
Windows wheel check. The corrected Stable gate passed **56 tests, zero failures,
zero skips**, exit 0. Four source/dependency lifecycle phases passed, as did
Unicode input/export paths, exact scene persistence, public MRHead/CTLiver widget
runs, the 30-case mixed workload plus cancellation/recovery, and 10,000/100,000-row
table cases. The mixed workload retained 24,480 rows and three report histories.

Windows testing exposed long generated Numba cache filenames exceeding `MAX_PATH`.
The worker and installation probe now use extended absolute cache paths without
changing Windows policy. The public MRI demo timer also now stops with its module
widget. The development sampler measures owned Windows process-tree working sets;
its guard retains failures and sample gaps. Portable fixture corrections preserve
the 100% scoped coverage requirement: 596 collected items, pytest reporting
593 passed, five existing privilege-dependent symlink skips and 473 passed subtests.
Ruff, Mypy, syntax and metadata checks pass.

The separately installed Preview runtime is **5.13.0-2026-09-30**, revision 35317,
from the checksum-verified October 1 installer. Its **56-test integration gate**,
all four lifecycle phases, Unicode paths and both public widget demonstrations
passed with exit 0, zero integration failures/skips, and exact scene persistence.
Its private environment is separate and the adopted release remains **0.5.1**.

Stable's native walkthrough completed normal GUI installation/restart, 340/680-row
MRI runs, single-ROI busy feedback, live cancellation and recovery, range/sigma
refinement, profiles, result browsing, Unicode CSV/sidecars, 680-value exact scene
reload, a 340-row CT run, and privacy-safe diagnostics. Extractions after normal
restart succeeded with pip explicitly forbidden; shared NumPy/Pillow stayed
unchanged. The final public CT scene is open and exported on the original machine.

The code revision `1d4ef6f8d064990e2944c68629875e424ac91fcb` passed all five
[GitHub jobs](https://github.com/martonkolossvary/SlicerPictologics/actions/runs/37120085011);
[PR #6](https://github.com/martonkolossvary/SlicerPictologics/pull/6) contains the
fixes and final evidence. Those wheel/Linux jobs remain distinct from these actual
Windows application results. Preview's full native walkthrough and workload/table
benchmark were not repeated. Official package acceptance, ARM/emulation,
multi-hour/independent-patient qualification and privilege-dependent symlink checks
remain outside the completed scope. Registration, release publication and new
images remain on hold.

## Mixed CT/MRI batch qualification (2026-10-02)

This milestone extends the public-data benchmark with a reproducible 30-case mixed
batch (five CT/MRI size variants, six rounds), two ROIs and two configurations,
real load/worker failures, real-worker cancellation, and a five-case recovery
batch without restarting Slicer. These are variants of two public scans, not
30 independent patients. The successful repeat exited **0** and verified 36
successful cases / **24,480 rows**, exact scene round trips for every row and
three batch reports, unchanged prior results, repeat numerical parity, stable
temporary node counts, and released worker/staging state.

The initial run exposed a real persistence bug: multiline failure text was not
escaped by Slicer's generic TSV report writer. The fix stores authoritative
report rows as JSON in scene metadata and reconstructs the locked table on import
or module setup. Regression tests cover multiline/tabbed text, quoted/Unicode
names, exact elapsed times, invalid canonical metadata, and intact legacy reports.
Already-corrupted legacy report tables still require their independent exports.

The test harness also stopped using a call-recording spy that retained image
arguments and inflated RSS. Qualified measurements come only from the corrected
repeat: **3.96 GiB** sampled simultaneous process-tree peak; **2.56 GiB** GUI RSS
after scene release versus **1.86 GiB** initially. This is bounded memory evidence,
not proof of unlimited stability or absence of all memory retention. See the
[workload method, timings, and limitations](performance.md#mixed-batch-observations-on-2026-10-02).
Evidence and both runs are under `local-output/mixed-batch-2026-10-02/`.

Local quality: **584 portable tests**, **100% scoped library/worker statement
coverage**, Ruff, Mypy (18 source files), and whitespace checks. The installed-Slicer
fast suite passed **49 tests**, with seven opt-in checks skipped (56 total,
4.781 seconds); the separate real mixed workload is the end-to-end evidence for
this change. Source publication was authorized on 2026-10-02. Require green GitHub
qualification for the exact pushed revision; local results alone do not establish it.

Next priorities: actual Windows and Slicer Preview application acceptance, and a final report-UI user
walkthrough. Longer independent-patient/multi-hour memory profiling remains useful.
Registration, official packaging, and new public imagery remain on hold.

## Large-table feedback and batch reports (2026-10-01)

Source publication is authorized. This milestone adds painted operation/row-count
feedback and input locking during result loading, browsing, and export, plus a
separate locked batch-report table saved with the scene. Reports retain case
statuses, elapsed seconds, submitted ROI count/run ID, committed row count/table,
and failure/skip reasons. JSON/CSV export is explicit; unsaved scenes are not a
crash-recovery journal. Reports can contain case identifiers and error paths and
are distinct from the allowlisted privacy-safe diagnostics preview.

Pre-publication review fixed report selection/ownership across repeated batches,
automatic discovery after scene import/restore, delayed writes to a reused MRML ID,
and an unconfirmed-run fallback that could falsely report success. Recovery marks
running snapshots interrupted without inventing their actual finish time. Case
names preserve spaces, colons, and Unicode. Local checks cover these paths, report
scene round trips, cancellation/failure, and table-operation failure/scene changes.
The CMake runtime list contains 26 files, including the new report support module.

Local quality: **560 portable tests**, **100% scoped library/worker statement
coverage**, Ruff, Mypy (18 source files), and whitespace checks. The installed-Slicer
fast suite passed **47 tests**, with seven opt-in real-worker checks skipped (54
total; 4.683 seconds). Earlier in this
milestone, the full real-worker suite passed 50 tests in 538.822 seconds; later
review fixes require their own qualification at the published commit. Evidence is
retained under `local-output/feedback-reports-2026-10-01/`.

Published `a756dfff11df747dd935ff9032662bdae19042bc` subsequently passed
[all five GitHub jobs](https://github.com/martonkolossvary/SlicerPictologics/actions/runs/36924124303),
including all 54 real Linux Slicer checks with no skips (1023.149 seconds), 560
portable tests/100% scoped coverage, and released-wheel checks on three platforms.
The published catalog metadata also passed the upstream validator. This does not
qualify the later mixed-batch changes described above or an installed Factory package.

At publication, the next priorities included heterogeneous/longer batch testing;
the bounded mixed-batch run above now addresses that gap. Actual Windows and
Preview Slicer acceptance and a final user walkthrough of the report UI remain.
Resumable batches, failed-case retry, and asynchronous/chunked large-table
operations are useful future improvements, not prerequisites to source publication.
Official package build, archive auditing, and clean package installation remain
post-submission gates. Registration and unreviewed imagery remain on hold.

## Representative workloads (2026-10-01)

Published commit `85d766b927d385b015dc0c76cf5d99eddc83bd4e` adds a checksum-pinned
real CT example with two illustrative ROIs, a bounded installed-Slicer workload
harness, eight portable fixture/sampling tests, and [measured performance guidance](performance.md).
It passed [all five GitHub qualification jobs](https://github.com/martonkolossvary/SlicerPictologics/actions/runs/36873316872).
The measured runtime is unchanged from `067672f`. No new image binary or screenshot
was included.

The successful full matrix covered cold/warm CT, MRHead, a 50.3-million-voxel CT
with crop parity, two configurations, 0.5 mm spacing, ten actual GUI batch cases,
and 10,000/100,000-row result tables. All extraction statuses were `ok`; the process
exited 0. Both large saved scenes were independently reopened and all row fields
and binary64 values matched their prior JSON exports exactly. The first harness
run's Qt-deletion crash and its correction are documented, not hidden by its
completed measurements. The normal Slicer scene/settings were not modified.
After the temporary logic's module name was corrected, the focused batch/table
rerun also completed all ten cases and both table sizes with clean process exit.
The CT preview produced 340 `ok` rows and remains local pending visual approval.

Local quality for that milestone: **555 portable tests**, 100% scoped library/worker coverage, Ruff,
Mypy (17 source files), and whitespace checks. The eight added tests also passed under
Slicer's bundled Python. This does not expand Windows/Preview application or package
qualification. Registration and new public images still require explicit maintainer
approval.

## Diagnostics and failure-recovery source milestone (2026-10-01)

**Published and qualified; registration remains on hold.** The maintainer
authorized commit/push of this validated milestone on 2026-10-01. Commit
`067672f3949171a3484d408a43196a22d3976530` is on `main` and passed
[all five GitHub qualification jobs](https://github.com/martonkolossvary/SlicerPictologics/actions/runs/36839582292):
lint/types/coverage, released-wheel checks on Windows/Linux/Intel macOS, and
**49 real Linux Slicer tests, no skips** (1049.910 seconds). Added an opt-in,
read-only diagnostic preview with explicit copying, allowlisted technical fields,
metadata-only dependency status, session run counts and fixed failure/recovery
codes. No scene identifiers, file paths, DICOM metadata or raw error/log text are
included; diagnostics are not uploaded or saved to the scene. Batch outcome reports
are a separate, user-visible scene table and are only retained when the user saves
the scene or explicitly exports them. See the
[privacy boundary and failure matrix](diagnostics-and-recovery.md).

Installer failure tests now exercise offline/interrupted resolution, bad candidate
metadata, import/JIT rejection, activation failure, fresh-install decline/failure,
and successful retry. All pip calls are mocked and all environments are test-owned.
Worker failure/cancellation and invalid/incomplete result tests retain exact prior
values/provenance and unlock the controls. A real CLI failure/retry gate supplements
the simulated terminal-state checks.

Export recovery also exposed and fixed a CSV companion-file gap. All files are now
staged before publication, previous files are copied with their permissions, and
caught publication failures roll back earlier replacements. Failed rollback retains
recovery copies and warns explicitly. JSON remains the single-file archival option;
multi-file power-loss/forced-termination/concurrent-edit guarantees are not claimed.
The runtime file list now contains 25 files; no branding/test/private-environment
content was added to that list.

Local verification passed: **547 portable tests**, **100% scoped library/worker
statement coverage**, Ruff, Mypy (17 source files), syntax and whitespace checks.
The full installed **Slicer 5.12.4** suite passed **49 tests, no skips** (522.041
seconds), including the real failure/retry. After final rollback-permission and
diagnostic wording refinements, the fast suite passed again (42 tests; seven
opt-in real-worker checks skipped, 3.794 seconds). The two new portable modules
also passed all ten `unittest` methods under Slicer's bundled Python without
installing tooling. Logs are in the ignored
`local-output/diagnostics-recovery-2026-10-01` directory.

The first fast-run fixture placed synthetic failed jobs outside the extension's
owned `job-*` root and therefore expected cleanup that the safety guard correctly
refused. Correcting the fixture path resolved those assertions; cleanup safeguards
were not loosened. Both initial and successful retry logs are retained.

The GitHub run above qualifies the diagnostics/recovery commit, not subsequent
local workload/benchmark development. No package version or existing job/result schema was changed.
No normal Slicer scene/settings, shared packages, public images, GitHub settings,
tags or catalog submissions were changed.

## Published baseline (assessed 2026-10-01)

Commit `9d72093f889486c9e96d255814178235803912b5` was pushed to `main` and passed
[all five GitHub jobs](https://github.com/martonkolossvary/SlicerPictologics/actions/runs/36767255998):
537 portable tests / 400 subtests / 100% scoped coverage; 41 real Linux Slicer tests
with no skips; and released-wheel API, worker and geometry checks on Linux, Windows
and Intel macOS. The Codecov upload was accepted and queued using the already
configured secret; no secret was changed. A scheduled
[dependency discovery run](https://github.com/martonkolossvary/SlicerPictologics/actions/runs/36784216719)
succeeded with `0.5.1`, no change; qualification/publication were correctly skipped.
This does not exercise an actual newer-release adoption.

The official catalog validator also passed against that exact published revision
(69.1 MiB clone; metadata/icon/both screenshot checks), not a package or catalog
acceptance. Actual Windows/Preview Slicer and Factory-package installation remain
unverified. The stopped local SDK build is not a pending prerequisite.

## Historical pre-publication source review (2026-09-30)

**ExtensionsIndex registration remains on hold.** On 2026-09-30, after the local
acceptance run, the maintainer authorized reviewing, committing, and pushing this
source milestone and assessing its GitHub tests. That authorization does not include
a tag/release, new screenshot, public repository-settings change, or catalog
submission. The exact pushed revision must pass its own GitHub qualification;
the older green run below is not evidence for these changes.

**Distribution decision (2026-09-30):** the maintainer stopped the local
Xcode/Qt/Slicer SDK build. It is no longer a release gate. Qualification uses the
installed Slicer application; after explicit registration approval, the Extension
Factory will build the distribution archives. Archive auditing and clean-package
installation follow that build. The private SDK recipe is retained only as an
inactive reference, not a prerequisite or an unfinished action for this milestone.

- **Previous published baseline:** `dd1c5fc6b7365022fdc54e63a093a34ba90a8a03`, following the
  consolidated feature milestone `dd16e4d`. All five jobs in its
  [GitHub qualification run](https://github.com/martonkolossvary/SlicerPictologics/actions/runs/36523318487)
  passed: 507 portable tests / 328 subtests / 100% scoped coverage, all 32 real Linux
  Slicer tests, and released-wheel API/worker/geometry checks on Linux, Windows,
  and Intel macOS. The quality follow-up explicitly declared NumPy for crop tests.
- **Catalog metadata refreshed:** the official ExtensionsIndex validator at
  `2a06251a679e3d5a04cccec549c5df2febc5c4b0` passed on 2026-09-30 against a fresh
  clone of that published revision, including repository/topic, CMake, license, dependency,
  icon, and screenshot checks; clone size was 68.9 MiB. The published hash was
  unchanged before/after the check. The local [submission draft](extensions-index-pr-draft.md)
  and [ordered handoff](extensions-index-submission.md) now distinguish preparation,
  publication authorization, registration, and post-submission package acceptance.
  The maintainer declared no known related patents on 2026-09-30. Optional GitHub
  presentation cleanup is deferred; no public settings changed. This is not
  package-build, cross-platform application, or catalog acceptance.
- **Batch teardown fixed locally:** a queued next-case callback previously loaded
  the second case even after module cleanup. The regression failed on the original
  code and passes after cleanup removes owned case nodes and clears the queue.
  Additional actual-MRML tests cover partial case-load failure, cancellation, and
  scene close without restoring stale input nodes.
- **Fresh local quality:** **537 portable tests / 400 subtests** pass with 100% scoped
  coverage, Ruff, Mypy (15 files), syntax checks, actionlint 1.7.12, and whitespace
  checks. The new installed-application run passed **all 41 Slicer 5.12.4
  integration tests with no skips** (471.565 seconds, successful exit), including
  six real extraction checks against a disposable 0.5.1 environment. This includes
  real batch/crop/ROI-feedback/YAML workflows, plain MRML scenes, Scene View
  isolation, and observer replacement. Earlier checks also passed all eight
  archive-checker tests under Slicer's own Python interpreter. The application is
  revision `4e21c19`, x86_64/Rosetta on macOS, Python 3.12.10, Qt 5.15.18.
- **Fresh disposable lifecycle:** four separate Slicer 5.12.4 processes used only a new
  temporary dependency root and a synthetic two-segment scene. Install-call counts
  were **1, 0, 1, 0** for install/restart/update/restart-update. The same-version
  replacement activated a different private directory, and both restarts reused
  it without pip. Shared NumPy 2.4.6 and Pillow 12.2.0 were unchanged; Pictologics was
  never imported into the GUI interpreter. Fresh extraction after the final restart
  reproduced all **340 rows** to `1e-12` relative/absolute tolerance. **All four
  lifecycle phases now pass:** scene reloads preserve every value with exact
  binary64 comparison (zero mismatches), not an approximate tolerance. Each phase's
  CSV and JSON exports were independently read back (eight files, 340 feature
  values each) and retain every value exactly. Exports are written before the initial scene save/close. A read-only
  PyPI check still resolves 0.5.1 as the latest stable wheel. This tests same-version
  dependency replacement, not adoption of an unavailable newer release.
- **Supplemental released-wheel checks:** the API/catalog/configuration gate
  (1,020 described configuration-feature rows), real JIT/worker extraction, and
  geometry parity all pass under Slicer's Python using the same private 0.5.1 target
  and worker isolation. The first supplemental launch used only `PYTHONPATH`;
  Slicer's launcher put shared NumPy 2.4.6 ahead of the private copy, so Numba
  rejected that mixed environment. The corrected local harness calls the existing
  worker isolation before importing anything scientific and verifies the private
  NumPy 2.3.5/Pictologics paths. This was a test-launcher error, not a failure of the
  41 passing application tests; no runtime fix or shared-package change was needed.
  The initial failure and successful retry are both retained. Fresh lifecycle,
  integration, export-readback, catalog, and source-hash evidence is kept in the
  Git-ignored `local-output/source-acceptance-2026-09-30` directory. The normal Slicer
  session was not cleared, closed, or modified during this verification pass.
- **Lossless scene persistence implemented locally:** the original run exposed
  rounding of **246 of 340 feature values** in Slicer's default table writer
  (for example, `206.64972537299272` became `206.65`). New result tables now carry
  exact binary64 backups, synchronized with edits and append, and validated
  against all row identities, stored values, and a checksum before scene-load
  restoration. Repeat saves, signed zero, and missing-value sentinels are covered.
  Corrupt/stale backups leave loaded values unchanged and show a warning. Importing
  another scene or restoring a Scene View does not replace existing live edits.
  Legacy scenes warn rather than inventing lost digits. The normal Slicer window
  was left open; its scene was empty, and earlier full-precision test exports were
  retained. Additional copies of the synthetic exports, scene, and lifecycle reports
  are retained in the Git-ignored `local-output` folder. No result columns or public
  schema versions changed. After the maintainer restarted Slicer on 2026-09-30,
  the normal session was verified to load the current checkout with one active
  persistence observer manager. Loading the saved synthetic scene restored all
  340 values exactly, with no persistence warnings. The GUI details panel displayed
  the full mean `206.64972537299272`; new CSV/JSON exports independently read back
  identically. The normal session was not cleared or closed.
  A fresh normal-session GUI run then completed in 45 seconds with 340 successful
  feature rows across two ROIs, zero bitwise differences from the baseline, and
  the same private dependency target. It created a new table, preserving the
  restored one. Full-precision exports and a second scene backup were saved before
  handing the open session back to the maintainer.
- **Package auditing prepared:** the new read-only checker verifies the exact 23
  runtime files, source hashes, layout, and unwanted content in ZIP/tar packages.
  Its fixtures are synthetic checker tests, not installable packages. This machine
  has no matching Slicer build tree, so a real CMake/Factory package and clean
  packaged-install acceptance remain unverified. A fresh local search on 2026-09-30
  still found no SlicerConfig.cmake/build tree. The Docker
  client is installed, but its desktop daemon is not running; no containers or
  build images were started/downloaded.
- **Private packaging stopped / retained as optional tooling:** the previously
  prepared checksum-pinned CMake/CTest/CPack 3.31.10 environment, lock, runner,
  and [historical guide](private-packaging.md) remain intact. No Qt/Slicer SDK was
  built, no Xcode/Qt license was accepted, and no actual archive or packaged
  installation is claimed. Their synthetic regression tests remain useful, but
  the proposed packaging-tools installation step has been removed from normal CI.
  A workflow contract now verifies that the quality gate does not require those
  tools or an Xcode build while retaining the real installed-Linux-Slicer tests.
  All 15 optional runner tests previously passed under Slicer's Python (1.226
  seconds); they use synthetic metadata/mocked build commands, not a real SDK.
  Further SDK provisioning requires a new explicit request and is not next work.
- **Coverage reporting prepared:** both workflow callers now explicitly pass an
  optional `CODECOV_TOKEN` into the reusable upload step. No secret was created or
  changed. The prior tokenless upload was rejected for the protected branch; the
  enforced coverage gate passed independently. Local workflow tests cover the new
  wiring. At this pre-push review it has not yet been exercised on GitHub; verify
  the upload step for the exact published revision before claiming dashboard success.

### Remaining gates and authorization boundaries

1. Publish this reviewed source milestone under the maintainer's 2026-09-30
   authorization and assess all jobs for its exact commit. An earlier green run
   does not validate these changes. Source publication is not catalog deployment.
2. Additional actual application acceptance on Preview and Windows remains useful
   but unverified: this machine supplies Stable macOS. Windows wheel CI is not
   Windows Slicer, and no cross-platform packaged-build qualification is claimed.
3. Optional repository-presentation cleanup and Codecov authentication require
   authorization to change public settings. Coverage upload is not the enforced
   test/coverage gate and is not a blocker for the local milestone.
4. Open the prepared ExtensionsIndex submission only after explicit registration
   approval. Then follow Factory builds, audit the actual archives, and verify
   installation/restarts/extraction/export/lossless scenes without source paths.
   No local SDK build is required to reach submission. Until these later gates
   pass, do not announce availability in Extensions Manager.

## Historical pre-publication consolidation snapshot (2026-09-29)

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

## 2026-10-04: Windows milestone merged; 0.6 adoption held

PR #6 is merged at `b3376c7`; all five post-merge GitHub jobs passed. Windows
application qualification remains specific to 0.5.1 and the runtimes documented
in [windows-validation.md](windows-validation.md).

The focused local 0.6 compatibility update adds explicit FBS minima and safe
profile migration, version-correct templates, new API/file-option checks and
conservative crop/joint-ROI safeguards. See the [compatibility review](pictologics-060-compatibility.md)
for evidence and limits. The committed requirement and constraints still adopt
0.5.1: 0.6.0 requires Numba 0.67, which has no Python 3.12 macOS Intel wheel for
the installed Slicer. Native ARM developer checks do not override this blocker.
No public registration, release/tag or new image publication is authorized.

## 2026-10-05: Intel Mac path with the Pictologics 0.7.0 candidate

The local Pictologics 0.7.0 line (`b96af63`, not released) lets macOS x86_64 Python
use Numba 0.62.x. In the installed Slicer 5.12.4 on macOS, the wheel resolves to
Numba 0.62.1 and NumPy 2.3.5. All extension release checks and all 57 installed-Slicer
tests passed with it. Native Apple-silicon Python resolves to Numba 0.68.0, and the
same release checks passed. The real-GUI ROI test no longer depends on CLI event
timing. The [handoff record](macos-compatibility-handoff.md#13-update-after-the-upstream-dependency-change)
lists the evidence and the remaining steps. The adopted requirement stays 0.5.1
until 0.7.0 is published and the cross-platform adoption run passes.
