# SlicerPictologics handoff record

**Record date:** 2026-10-05  
**Purpose:** factual handoff of the current implementation state and the overall
pre-publication goal. This document records completed work and outstanding
qualification/publication requirements. It is not a release announcement and does
not claim that the candidate has been adopted or published.

**Update:** [Section 13](#13-update-after-the-upstream-dependency-change) replaces
Sections 1, 3, 5 and 7 and adds to Section 8.

## 1. Current release state

- The extension currently adopts **Pictologics 0.5.1** on every platform.
- `PictologicsSlicer/requirements-pictologics.txt` remains `pictologics==0.5.1`.
- `PictologicsSlicer/constraints-pictologics.txt` remains the existing 0.5.1
  constraint set.
- Pictologics 0.6.0 is available on PyPI, but it requires Numba 0.67.x.
- The installed official Slicer 5.12.4 on this Mac is an Intel/x86_64 application,
  including when the host hardware is Apple Silicon and Slicer is run through
  Rosetta. Its Python is CPython 3.12.10 x86_64.
- Numba 0.67.x has no macOS x86_64 wheel. Numba's Intel-macOS support ended with
  the 0.62.x line. The relevant upstream record is the
  [Numba 0.63 release note](https://numba.readthedocs.io/en/stable/release/0.63.0-notes.html).
- Therefore the published 0.6.0 package was not adopted by the extension.
- No Pictologics release was published by this work. No extension release or tag
  was created. No ExtensionsIndex registration was submitted.

## 2. Overall goal before public publishing

The pre-publication goal is a reproducible, reviewed, cross-platform release in
which:

1. one exact, published Pictologics version is selected for the extension;
2. dependency pins are resolved and recorded for each actual supported Python
   runtime;
3. macOS x86_64 means both Intel Macs and Apple Silicon Macs running the current
   Intel/Rosetta Slicer;
4. the Pictologics package metadata and the extension constraints agree with those
   runtime-specific dependency pins;
5. portable tests, real JIT checks, numerical/geometry checks, installed-Slicer
   application checks, and Windows/Linux/macOS CI checks all pass;
6. the exact package artifacts and source revisions used for those checks are
   recorded; and
7. only after that evidence exists, the upstream package release, extension pin,
   extension release, and ExtensionsIndex submission are handled.

The current record does not satisfy all of these publication requirements. It
records the work completed toward them and the evidence that exists.

## 3. Extension checkout and Git state

Workspace: this repository, the SlicerPictologics checkout.

Current extension branch:

`codex/pictologics-060-compatibility`

Current committed base:

`b3376c725f98cf67c7efbce7be22b54eaba63505`

That commit is the merge of Windows acceptance PR #6. The compatibility and
runtime-resolution changes described below are present as **uncommitted local
changes** in the extension checkout. They have not been pushed.

The root checkout contains these modified or new files:

- `.github/workflows/adopt-pictologics-release.yml`
- `.github/workflows/compatibility.yml`
- `PictologicsCLI/PictologicsCLI.py`
- `PictologicsCLI/Testing/test_worker_coverage.py`
- `PictologicsSlicer/PictologicsLib/dependencies.py`
- `PictologicsSlicer/PictologicsLib/inline_config.py`
- `PictologicsSlicer/PictologicsLib/profiles.py`
- `PictologicsSlicer/PictologicsSlicer.py`
- `PictologicsSlicer/Resources/UI/PictologicsSlicer.ui`
- `PictologicsSlicer/Testing/Python/CMakeLists.txt`
- `PictologicsSlicer/Testing/Python/PictologicsSlicerIntegrationTest.py`
- `README.md`
- `docs/release-readiness.md`
- `docs/pictologics-060-compatibility.md`
- `docs/macos-compatibility-handoff.md`
- `scripts/check_pictologics_api.py`
- `scripts/check_release_compatibility.py`
- `scripts/check_runtime_dependencies.py`
- `scripts/platform_constraints.py`
- `tests/test_dependencies_coverage.py`
- `tests/test_inline_config.py`
- `tests/test_inline_config_coverage.py`
- `tests/test_platform_constraints.py`
- `tests/test_profiles.py`
- `tests/test_release_workflows.py`

No destructive Git operation was performed. The active installed 0.5.1 Slicer
environment and normal Slicer settings were not replaced.

## 4. Windows milestone already completed

Windows acceptance PR #6 was merged:

- PR: <https://github.com/martonkolossvary/SlicerPictologics/pull/6>
- Windows source/documentation commit:
  `cdec079c146257b1abfdbd382a943ee2419e065e`
- Merge commit: `b3376c725f98cf67c7efbce7be22b54eaba63505`
- Post-merge CI run: [37203932959](https://github.com/martonkolossvary/SlicerPictologics/actions/runs/37203932959)

The post-merge workflow completed all five jobs successfully. The Windows report
covered Stable and Preview Slicer application behavior at Pictologics 0.5.1,
including installation/restart behavior, Unicode paths, mixed workloads, multiple
ROIs, large result tables, memory sampling and failure/recovery cases.

That evidence qualifies the merged Windows work with **0.5.1**. It is not evidence
for 0.6.0, 0.6.1 or 0.7.0.

## 5. Local upstream package workspaces

The original sibling checkout is `../Pictologics`, next to this repository.

It was left unchanged and clean. No upstream commit or push was made.

Two independent, ignored local clones contain the proposed package changes.

### 0.6.1 candidate clone

Path: `local-output/pictologics-061-compatibility`  
Branch: `codex/macos-061-compatibility`  
Base: `163b85a796830da71d9249e163ea6b0746af5e6f`

The 38 tracked package files at that base were compared byte-for-byte with the
released Pictologics 0.6.0 wheel and matched. The local clone changes the package
version to 0.6.1 and adds the conditional dependency metadata, lockfile, tests,
documentation, runtime JIT smoke and release workflow. Its wheel was built locally
but was not uploaded.

Local wheel SHA-256:

`98253dff23092305d7b7695e33a56232d9f8b11f79834aa2f28bd97cd9566d55`

### 0.7.0 carry-forward clone

Path: `local-output/pictologics-macos-compatibility`  
Branch: `codex/macos-runtime-compatibility`  
Base: sibling development line at commit `adc6972`

This clone retains package version 0.7.0 and applies the same runtime compatibility
policy and release checks to the newer development line. Its newly changed
algorithms were not fully qualified against the legacy Numba stack.

Local wheel SHA-256:

`1bc626c43d5a1e3a567ab904f69b59fc5599656652969dcbe465fe93816257e4`

Both clones contain uncommitted/untracked work. Their local `origin` points to the
local sibling repository, not to the GitHub repository. They are ignored by the
extension repository and must not be added to it.

## 6. Extension changes completed locally

### Runtime-specific dependency qualification

- `scripts/platform_constraints.py` records pip installation reports from actual
  CPython 3.12 Linux x86_64, Windows AMD64 and macOS x86_64 runners.
- Each snapshot records the candidate version, exact extension revision, runtime
  identity, resolved distribution versions and wheel SHA-256 values.
- Snapshot validation rejects wrong runtimes, duplicate distributions, missing
  scientific dependencies, yanked artifacts, source archives, missing hashes,
  incomplete matrices and revision/version mismatches.
- Snapshot merging creates deterministic PEP 508 constraints with runtime markers.
- The merge requires all three supported extension qualification runtimes.

### Installation and dependency auditing

- `PictologicsSlicer/PictologicsLib/dependencies.py` evaluates active dependency
  markers for the running Python process.
- It rejects overlapping active pins, non-exact pins, extras, direct URLs and
  unsupported runtime markers in the generated constraints.
- Existing unqualified 0.5.1 constraints remain accepted for the current installed
  release.
- `scripts/check_runtime_dependencies.py` audits the isolated target without
  importing Pictologics. It checks the exact distribution set, exact versions and
  the transitive dependency closure.
- The dependency audit is present in the wheel and real Linux-Slicer qualification
  jobs.

### Existing 0.6 compatibility work retained

- Explicit finite FBS minimum handling and readiness validation.
- Profile and scene migration for missing FBS minima.
- Version-aware standard FBS presets.
- 0.6 step/parameter API mirror and filter parameter handling.
- Full-image fallback for normalization and mask growth operations.
- Rejection of unsupported joint-ROI growth configuration.
- Expanded real-wheel numerical, geometry, provenance and result-format checks in
  `scripts/check_release_compatibility.py`.

## 7. Package changes completed in the local clones

The local package metadata contains these runtime markers:

| Runtime | Numba requirement | NumPy requirement | Status in current work |
|---|---|---|---|
| macOS x86_64 Python, including Rosetta Slicer | `>=0.62.1,<0.63` | `>=2.0,<2.4` | local candidate metadata and tests |
| Other modern supported runtimes | `>=0.67.0,<0.68` | existing Python-specific rules | local candidate metadata and tests |

The local package documentation records that selection is based on the Python
process architecture. The package workflow includes:

- built-wheel metadata tests for macOS x86_64, macOS ARM64, Linux x86_64 and
  Windows, across Python 3.12–3.14;
- binary-only installation and `pip check`;
- package unit tests;
- a separate full-JIT smoke outside the source checkout;
- a publication dependency on the runtime compatibility workflow.

These changes exist only in the two local clones described above. They are not
present in a published Pictologics release.

## 8. Completed validation evidence

### Extension repository

- Portable test suite: **608 passed**.
- Scoped statements: **2,658**.
- Scoped coverage: **100.00%**.
- Ruff: passed.
- Mypy: passed for 18 files.
- Compileall: passed.
- Diff whitespace check: passed.
- actionlint 1.7.12: passed for the changed extension workflows and both local
  package workflow copies.

### Local 0.6.1 candidate under installed Slicer Python

The released-style local 0.6.1 wheel was installed into a new disposable target
using Slicer Python 3.12.10, process architecture x86_64, binary-only pip
installation, Numba 0.62.1, NumPy 2.3.5 and llvmlite 0.45.1.

The existing 0.5.1 environment was not modified. The candidate target passed:

- API check with 1,020 described configuration-feature rows;
- full-JIT worker smoke with 170 successful feature rows;
- oblique anisotropic NIfTI geometry parity with 170 matching features;
- expanded FBS, IVH, preprocessing, provenance and crop-safety checks;
- two-ROI, all-feature-family full-JIT smoke with an independent binning oracle;
- exact dependency closure audit for 23 distributions.

The existing adopted 0.5.1 target passed the read-only dependency closure audit for
25 distributions.

### Validation not completed

- The candidate did not receive the complete installed-Slicer GUI/lifecycle suite.
- The planned disposable GUI invocation was not executed because the command
  approval service reached its usage limit before launch. No command ran and no
  Slicer state changed.
- The local 0.7.0 carry-forward did not receive complete legacy-stack algorithmic
  qualification.
- The new cross-platform GitHub matrices have not run on these uncommitted changes.
- Windows and Linux dependency snapshots for these uncommitted changes do not exist.
- Upstream full IBSI qualification for the local 0.6.1/0.7.0 package changes was
  not completed.

## 9. Evidence files

Ignored evidence directory:

`local-output/macos-compatibility-validation/`

Relevant files and directories:

- `install-061.log`
- `resolution-061.json`
- `snapshot-macos-061.json`
- `portable-tests.log`
- `real-061.log`
- `target-061/` — disposable candidate dependency target
- `numba-cache-061/` — disposable compiler cache
- `constraints-061.txt` and `requirements-061.txt` — disposable audit inputs
- `actionlint` and `actionlint.tar.gz` — local workflow validation tools

No patient scans, runtime environments, Slicer scenes or raw application logs are
tracked in Git.

## 10. Publication gate description

Before any public release, the required evidence set is:

1. A reviewed upstream Pictologics release containing the runtime metadata and
   package tests, with its exact wheel and source hashes recorded.
2. A reviewed extension revision containing the compatibility implementation and
   tests.
3. Native dependency-resolution snapshots for every runtime included in the
   extension qualification matrix.
4. A merged, deterministic constraints file produced from those snapshots.
5. Passing portable, API, full-JIT, numerical, geometry, provenance and result
   persistence checks.
6. Passing installed-Slicer application checks, including fresh install, restart,
   two-ROI CT/MRI extraction, profile/scene restoration, cancellation/recovery and
   export behavior.
7. Passing GitHub CI for Linux, Windows and macOS, using the exact reviewed source
   revision and constraints.
8. Reproducible release artifacts and a review of the catalog metadata, icon,
   screenshots, license, privacy statements and known limitations.
9. Explicit approval to publish the upstream package/release and extension release.
10. Only after those records exist: update the adopted extension pin, publish the
    extension release, and submit the ExtensionsIndex metadata.

The automatic-adoption workflow is not evidence by itself. Its publication job is
intended to write the exact qualified Pictologics pin and constraints only after the
qualification workflow succeeds. It has not published anything in this milestone.

## 11. Publication holds and preservation requirements

- Keep the extension adopted version at 0.5.1 until the publication gate is fully
  evidenced.
- Do not use `--no-deps`, relaxed published metadata, a source-built Numba/LLVM,
  disabled JIT, or a skipped macOS job as qualification evidence.
- Do not overwrite the active 0.5.1 Slicer environment with a candidate target.
- Preserve the ignored local package clones until their changes are explicitly
  transferred or discarded by an authorized maintainer.
- Do not push the local clones' `origin` without checking the remote first.
- Do not create a public release, tag, ExtensionsIndex entry or new public image
  from this handoff alone.
- The local Xcode/Qt/Slicer build path remains outside this work; installed Slicer
  validation is the relevant application path.

## 12. Reproduction references

Developer Python:

`../Pictologics/.venv/bin/python`

Installed Slicer Python:

`/Applications/Slicer.app/Contents/bin/PythonSlicer`

Installed Slicer application:

`/Applications/Slicer.app/Contents/MacOS/Slicer`

The previously executed portable commands were:

```sh
../Pictologics/.venv/bin/python -m pytest --cov --cov-report=term-missing
../Pictologics/.venv/bin/python -m ruff check PictologicsSlicer PictologicsCLI/PictologicsCLI.py scripts conftest.py tests
../Pictologics/.venv/bin/python -m mypy
```

The candidate dependency audit used the disposable target, constraints and
requirements files listed above. The earlier real PythonSlicer numerical checks
used `dependency_probe.isolate_target` before importing scientific packages. A
plain `PYTHONPATH` override was not treated as sufficient isolation because Slicer's
bundled NumPy can otherwise shadow the candidate target.

This document is the handoff record. It does not change the adopted version or
authorize any commit, push, release, registration or publication.

## 13. Update after the upstream dependency change

**Record date:** 2026-10-05, later the same day.

### Extension state

- Pull request #7 merged the extension changes into `main` as `5b207a7`.
- Adoption run 37331419353 then qualified Pictologics 0.7.0 on Linux, Windows and
  Intel macOS, and it committed the new pin and runtime constraints as `d6e2bed`.
- Pull request #8 (`61a4b3f`) removed the local folder paths from this record. Its
  CI run passed all five jobs on the same files as `main`.

### Upstream package state

- The sibling checkout `../Pictologics` is at `b96af63` on `main`, version 0.7.0.
  It is 22 commits ahead of `origin/main`. Nothing is pushed or released.
- `6dd5504` makes the tests work with pandas 3 and allows the SciPy 1.18 FFT thread
  split in the warm-up test.
- `fab59c6` sets the Numba rules below. It removes the upper limits of SciPy,
  Pillow, PyWavelets and tqdm, and it adds an Intel Mac CI job and a weekly
  workflow with the newest versions.
- `b96af63` makes Matplotlib the optional extra `viz`. The extension does not use
  Matplotlib, so it installs the plain package.

| Runtime | Numba requirement |
|---|---|
| macOS x86_64 Python, including Rosetta Slicer | `>=0.62.1,<0.63` |
| Other runtimes, Python 3.12 and 3.13 | `>=0.62.1` |
| Other runtimes, Python 3.14 | `>=0.63.0` |

- NumPy stays `>=2.0` (`>=2.3.2` on Python 3.14). Numba 0.62.1 itself limits NumPy
  to `<2.4`.
- These rules replace the candidate metadata of Section 7. The adoption does not
  need the two clones in `local-output/`.
- After `adc6972`, the package code changes only a docstring, a CSV column
  selection and the Matplotlib import. The feature code is the same.

### Evidence on this Mac

The wheel was built from `b96af63` and was not uploaded. Its SHA-256 is
`49518b74b81a2ca9aede6a7bb7beb09300b12586fb7d28ea997684871504802c`.

| Check | Result |
|---|---|
| Installed Slicer 5.12.4 Python (x86_64), binary-only resolution | 17 distributions: Numba 0.62.1, llvmlite 0.45.1, NumPy 2.3.5, SciPy 1.18.1, pandas 3.0.6, Pillow 12.3.0, no Matplotlib; 459 MB |
| Native Apple-silicon Python 3.12, binary-only resolution | Numba 0.68.0, llvmlite 0.50.0, NumPy 2.5.3 |
| Dependency closure audit, Slicer Python | Passed: 17 exact distributions |
| API, worker smoke, geometry parity and expanded checks, Slicer Python with the isolated target | All passed: 1,020 described rows, 170 rows, 170 features |
| The same four checks, native Python with Numba 0.68.0 | All passed |
| Full installed-Slicer suite with the timing-test fix | 57 of 57 passed |
| 1,885 feature values from 13 settings, Slicer Python | Identical to the earlier 0.7.0 candidate, bit for bit |
| The same values, Numba 0.68.0 against Numba 0.67.0 (Apple silicon) | Identical, bit for bit |
| The same values, Numba 0.62.1 against Numba 0.68.0 (Apple silicon) | 14 values differ, only in the 16th digit |

The Linux and Windows wheel jobs did not run with this candidate. The logs of these
checks are in a temporary folder and are not kept.

### Timing-test fix

- `test_real_gui_run_reports_roi_and_freezes_elapsed_time` required a short status
  line. A fast second ROI can start and end between two CLI events, so the line can
  be missing. The test failed on Linux CI with 0.6.0 and on this Mac with 0.7.0. It
  passed on this Mac with 0.6.1.
- The test now reads the worker's own ROI marker with the GUI's parser.
  `test_elapsed_roi_feedback_and_cancellation_preserve_terminal_state` still checks
  each status line with a controlled CLI node.

### Evidence with the published 0.7.0

- PyPI publishes the 0.7.0 wheel from tag `v0.7.0` (`8787cb2`). Its SHA-256 is
  `2585cc293249f950507d08dcf559a5e22711b4751486ef2175e65e4397fac655`.
- Its 42 package files are identical to the tested local build. Only the `WHEEL`
  file differs: it names poetry-core 2.2.1, not 2.5.0.
- Slicer's pip installed it from PyPI with 17 distributions, Numba 0.62.1 and NumPy
  2.3.5. The dependency audit, the 4 release checks and all 57 installed-Slicer tests
  passed.
- A local simulation of the new adoption pin step merged three resolutions into
  one constraints file. The Intel Mac resolution was real. pip resolved Linux and
  Windows on this Mac, so their runner environments were set by hand.
- The merged file pins Numba 0.62.1 for Intel macOS and Numba 0.68.0 for Linux and
  Windows. With it, the portable tests, the Intel-emulation install with the audit
  and the 4 checks, and the Slicer-Python install with the audit all passed.
- The simulation found one test fault. The contract test checked the merged file
  only for the computer that runs it, so it failed on Apple silicon. The test now
  checks each runtime that the file lists.

### Remaining before publication

1. Run the installed-Slicer suite with the published wheel on Windows, Stable and
   Preview. On macOS, Stable 5.12.4 and Preview 5.13.0 passed it on 2026-10-06.
2. Install a built extension package, restart Slicer and run it.
3. Submit the ExtensionsIndex entry for Preview and Stable.
- The maintainer approved new catalog screenshots with 0.7.0 on 2026-10-05.
- The release notice from Pictologics needs the `SLICER_EXTENSION_DISPATCH_TOKEN`
  secret. Without it, only the six-hourly schedule starts the adoption run.
