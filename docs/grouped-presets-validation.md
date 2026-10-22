# Grouped preset browser: local validation (2026-10-22)

This records a local working-tree milestone based on `ee2e936`, not a published
release, a GitHub CI run for these changes, or clinical validation. Pictologics
remains pinned to **0.8.0**. Extension version 0.1.0 and the existing manifest,
profile and result schemas are unchanged.

## Implemented

- **General**: the existing six standard presets, with `standard_fbn_32` still
  checked by default.
- **Coronary plaque**: 30 individually selectable configurations from the
  package's `coronary` template collection.
- **Myocardium**: 30 individually selectable configurations from its `lv`
  template collection.
- Readable cardiac names, native identifiers, tooltips and a description panel
  covering resampling, retained HU range, discretisation and feature families.
- Group switching retains checkboxes in the other groups. The cross-group count
  reports those selections; **Clear all presets** clears all groups, not just the
  visible group. No template collection is automatically selected as a whole.
- Profiles and MRB scene parameters retain individual native IDs, including mixed
  General/cardiac selections. General-only profiles still load.

The GUI carries only patient-free display/preflight metadata. Actual cardiac
pipeline definitions are loaded in the isolated worker from the installed
Pictologics wheel using `RadiomicsPipeline.from_template`. The worker executes
only the requested native names and records their effective configurations in
provenance. Unavailable templates/configurations raise errors; there is no silent
fallback. The existing `standard_configurations` manifest field and
`standardConfigurations` scripting argument accept cardiac names without a new
structural schema. Older extension versions reject cardiac profile selections.

The release API check now compares all 66 names, resampling spacings and cardiac
HU ranges with the candidate wheel. A mismatch stops qualification/adoption.
The starter-file **New from preset…** aid remains General-only; the new browser
does not require custom files to use cardiac presets.

## Completed checks

- Ruff passed the repository's normal source/script/test scope.
- Mypy passed all **19** scoped source files.
- Portable tests: **614 passed**, **2692 scoped statements, 100% coverage**.
- Expanded wrapper API check passed against the already-qualified private
  Pictologics 0.8.0 wheel in Slicer Python.
- Installed **Slicer 5.12.4**, revision `4e21c19`, Python 3.12.10 x86_64 under
  Rosetta on this Mac: **59 tests passed in 867.694 seconds**, zero failures/skips,
  process exit 0. The fresh process used `--disable-settings --ignore-slicerrc`,
  `NUMBA_NUM_THREADS=2`, unset development source override, and an existing
  qualified target. No installation or shared-package replacement was performed.
- The new GUI test verified group visibility (6/30/30), hidden checked items,
  descriptions, clearing, mixed-group profile loading and exact native-ID
  selection after MRB save/reload.
- The new real-worker test ran only `standard_fbn_8`, `coronary_orig`,
  `coronary_fbn_16`, `coronary_fbs_16`, `lv_myo_orig` and `lv_myo_fbs_16` on a
  deterministic synthetic ROI. All rows were `ok`; result/provenance configuration
  sets contained exactly those six names. CSV/JSON exports succeeded. This tests
  integration and selection, not anatomical suitability or clinical performance.
- Existing asynchronous extraction, crop parity, batch, failure/recovery,
  readiness, elapsed-time, precision/persistence and YAML validation tests also
  passed in that full suite.

Ignored evidence: `local-output/grouped-presets-2026-10-22/integration.log` and
`portable.log`. A separate disposable Slicer window was visually inspected using
the previously exported public anatomical CT scene. Its new-control screenshot
remains outside Git pending visual approval; it does not represent a cardiac
extraction on the liver demonstration. The separately approved anatomical
workflow and matching results/provenance images are retained in the documentation.

## Remaining scope

### PR #9 live-worker retention follow-up (2026-10-22)

Copilot identified a missing cleanup guard in the new real cardiac test. If its
wait raises while the worker remains alive, the test now retains its temporary
directory and sets the class-level failure flag, matching the existing real-GUI
test. Subsequent tests skip before clearing the scene or creating fixtures.

A new regression injects wait failures with both a released worker and a
still-live worker (without starting a real timed-out process). It verifies normal
cleanup in the former case, retained files/no scene clearing in the latter, and
the subsequent-test skip. The probe restores its own flags afterward because
there is no live process to protect.

Installed Slicer 5.12.4/Rosetta passed **three focused tests in 129.101 seconds**:
the injected failure/recovery guard, grouped selection/profile/scene persistence,
and the normal real six-configuration cardiac extraction/export path. Zero
failures/skips, process exit 0. All **614 portable tests** still pass with **100%
scoped coverage**; lint and typing pass. This focused follow-up does not claim a
new full 60-test installed-Slicer run. Its log is retained under ignored
`local-output/pr9-worker-retention-2026-10-22/focused.log`.

The maintainer authorized moving the milestone and this fix onto `main` and
removing branches whose commits are preserved there. This does not authorize a
release, tag or ExtensionsIndex registration.

This record describes local validation completed before the maintainer authorized
commit/push on 2026-10-22. It does not establish GitHub CI or native Windows and
Preview application acceptance for the published revision. No new
representative cardiac-scan workload or all-60-cardiac-configuration extraction
acceptance is claimed. Existing public registration/release holds remain in place.
