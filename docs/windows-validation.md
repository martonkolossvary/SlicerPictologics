# Windows application validation

Validation dates: 2026-10-02 to 2026-10-04. This report separates installed Windows Slicer
application tests from GitHub's Windows wheel and Linux Slicer jobs. It is not
ExtensionsIndex registration, Extension Factory package-install acceptance, or
clinical validation. New images, raw logs, downloads, environments, scenes and
exports remain in ignored local storage.

## Host and exact source

- Native x64 Windows 11 Pro 25H2, build 26200.8457; no ARM/emulation claim.
- AMD Ryzen 7 9800X3D, 33,396,543,488 bytes usable RAM (31.1 GiB).
- Approximately 57 GiB free on the checkout drive initially.
- Git 2.55.0.windows.1, developer Python 3.12.10, PowerShell 7.6.5.
- Checkout `C:\work\SlicerPictologics`, branch `codex/windows-acceptance`.
- `origin/main` exactly matched `bc0cd7cb1f7e7591fb5f8a6ddd2656f6714d2927`.
  No fetch/pull occurred during measurement runs. Local tooling fixes are
  described below. The worker and standalone dependency probe additionally fix
  Windows Numba cache paths; all requirements and constraints remain unchanged.
  The corrected source was committed as
  `1d4ef6f8d064990e2944c68629875e424ac91fcb`; subsequent changes only complete
  this report and readiness documentation. Preview and the normal GUI walkthrough
  used that exact commit. Earlier corrected Stable runs used the file hashes below.
- Stable: official Slicer 5.12.4, revision 34645 (`4e21c19`), built 2026-09-09;
  bundled Python 3.12.10, AMD64. Actual executable was located in the existing
  per-user installation; personal absolute paths are omitted from this report.
- Adopted Pictologics 0.5.1 and the committed constraints were used throughout.
  No Pictologics package was installed into Slicer's shared Python.

The existing Stable installer matched the SHA-512 on the
[official download page](https://download.slicer.org/):

```text
5ba320cb67f0acdaacf0a31380e9cf3b9f46d05f57a53da7e04ebcd9490251ecbe998bfefdbdab1f747e038653177868cdb0ad30986473b9d68efba0f4c6045c
```

## Portable checks and discovered portability issues

The baseline syntax, Ruff, Mypy and metadata JSON checks returned 0. Baseline
pytest returned 1, with Windows-specific failures and 98.65% scoped statement
coverage. The initial run is retained locally; it is not a passing baseline.

Corrections retain the existing safety assertions and 100% coverage requirement:

- ZIP audit uses the original entry name before Python's Windows separator
  normalization. A backslash entry must be rejected on every host.
- Portable fixtures no longer require `mkfifo`, a Unix home-directory fallback,
  or changing global `os.name` during NumPy's lazy imports.
- POSIX liveness error-path tests explicitly select that backend; actual Windows
  liveness remains exercised by the existing child-process test.
- Injected filesystem and directory-sync outcomes cover safety branches on
  Windows without granting symlink privileges or changing OS security policy.
- Synthetic distribution creation invalidates import caches before reinspection,
  avoiding a Windows directory-timestamp/cache race in the test fixture.

After these corrections and sampler tests, pytest reached **100% scoped
library/worker statement coverage**, with no failed tests. Five real-symlink
checks remain skipped under the account's existing privilege policy; injected
contract tests supplement them and do not represent actual symlink creation.
The final portable run collected **596 items**; pytest 9.1.1 reported
**593 passed, 5 skipped, 473 subtests passed** (9.12 s on the October 4 repeat), exit **0**, with all
**2,619 scoped statements covered**. Pytest's subtest outcomes are reported
verbatim rather than treating their totals as mutually exclusive collected tests.
The syntax, Ruff, Mypy (18 source files), and metadata JSON checks returned **0**.
The first final lint pass found one import-order issue; it was corrected and the
full Ruff gate passed.

## Actual Stable integration and path regression

The initial full application run completed 56 tests but failed seven assertions
across five real-worker tests, exit 1. Extraction logs showed Windows `MAX_PATH`
failures in Numba's generated cache filenames. The synthetic test root and ordinary
per-user storage can both leave too little space for those filenames.

The worker now gives Numba an extended absolute Windows path while keeping the
same cache location and ordinary path spelling in provenance. A separate diagnostic
reproduced the same failure in the installation JIT probe; that standalone process
uses the same correction. Local-drive, UNC, already-prefixed and non-Windows paths
have regression coverage. The two subprocess entry points intentionally remain
standalone and use only the standard library before importing private packages.
No registry, execution-policy or shared-package change is required. See Microsoft's
[extended path documentation](https://learn.microsoft.com/en-us/windows/win32/fileio/maximum-file-path-limitation).

The focused formerly failing real-worker scenario passed (90.670 seconds, exit 0).
The full repeat then passed **56 tests, zero failures, zero skips**, in **588.247
seconds**, exit **0**, using the unchanged long test directories. This exercises
actual GUI controls and the CLI worker inside installed Windows Slicer: readiness,
ROI/configuration selection, busy/progress/elapsed feedback, profiles, resegmentation
and invalid settings, browser details/filtering/pagination, exports, exact numeric
persistence, diagnostics, cancellation/failure recovery, and separate batch-report
histories including multiline errors. Automated widget checks are distinct from a
human visual walkthrough.

The synthetic paths check also passed, exit **0**. Input image, segmentation,
configuration, CSV/JSON exports and MRB scene paths contained spaces and `árvíz Ω`.
Two ROIs, all feature families, 1 mm spacing and FBN 16/32 produced **680 successful
rows**. Independent single-configuration runs produced 340 each and agreed within
`1e-12`; scene save/reload preserved every value's binary64 representation exactly.
CSV provenance/catalog sidecars and reopened JSON were verified. Slicer's installation
path itself remained ASCII; this does not qualify Unicode installation directories.

## Stable dependency lifecycle

Before the cache-path correction, all four separate-process phases at the baseline
returned 0 and wrote successful reports using their shorter test-owned root:

| Phase | pip calls | Existing rows | New extraction rows | Scene binary64 mismatches |
| --- | ---: | ---: | ---: | ---: |
| install | 1 | 340 | initial extraction | 0 |
| restart | 0 | 340 | 0 | 0 |
| update | 1 | 340 | 0 | 0 |
| restart-update | 0 | 340 | 340 | 0 |

Two synthetic ROIs and one `standard_fbn_32` configuration produced 340 successful
rows. Restart retained the private target; update selected a new target. Both
restart phases forbade pip. CSV, provenance JSON, catalog CSV and standalone JSON
were exported before scene closure. Settings-profile validation and exact scene
readback passed; independent re-extraction matched within `1e-12`.

Shared NumPy **2.4.6** and Pillow **12.2.0** were unchanged in every phase.
The lifecycle root is `local-output/win-lifecycle-01`; the dependency target was
read from the successful report, not inferred from an AppData convention.
This is disposable source/dependency acceptance with same-version replacement.
The normal GUI installation/restart walkthrough below independently checks the
ordinary per-user installation.

## Normal Stable installation and visible walkthrough

Developer mode and both source module paths were saved through Application
Settings. A normal restart discovered **Pictologics** and **Pictologics Worker
(internal)**. The GUI's **Install / update adopted release...** action installed
and qualified **0.5.1** in the extension's private environment. Its import/API and
JIT probes completed before the active target was inspected. No development-source
override or sibling checkout was used. Shared NumPy **2.4.6** and Pillow **12.2.0**
were identical before and after. An inspection attempted before atomic activation
completed was retried after the installer finished; that early harness assertion
is not treated as an installation failure.

The owned empty session was closed normally and reopened with saved settings.
The same qualified target remained active. In this owned process, a temporary
assertion guard rejected any call to Slicer's pip installer; all following
extractions passed without invoking it. The guard was restored before handoff.
The private target was read from `inspectDependencies()`, recorded locally, and
not guessed from an AppData path.

Native Windows controls and application-console assertions were used on exported,
test-owned public scenes. This complements the automated Qt integration suite;
these observations are not the maintainer's approval of new images.

| Visible check | Result |
| --- | --- |
| MRHead, two selected demonstration ROIs, whole volume off, `standard_fbn_32` | 340 successful rows; displayed elapsed 9 s |
| MRHead, same two ROIs, FBN 16 and FBN 32 presets | 680 successful rows; displayed elapsed 6 s; separate configuration identities |
| One ROI and FBN 32 | 170 successful rows; displayed elapsed 4 s; indeterminate busy feedback while the worker was active |
| Cancellation and recovery | A 100 ms Qt observer waited for a live worker, invoked the Cancel handler, and verified all earlier 170 rows were unchanged; a subsequent native Run completed 170 rows in 4 s |
| Invalid refinement | Minimum 501 and maximum 500 disabled Run and displayed the specific minimum/maximum explanation |
| Valid refinement | Minimum 0, maximum 500, sigma 1.5, both mask targets, 0.5 mm resampling and FBN 32 produced 170 successful `in_app` rows in 5 s |
| Public CTLiver-derived slab, two ROIs, crop enabled, whole volume off, FBN 32 | 340 successful rows; displayed elapsed 3 s |
| MRI scene round trip | All 680 saved values restored with zero binary64 mismatches |

The rounded GUI times include the reused private/JIT environment and are not
isolated benchmark measurements. An initial manual Cancel click arrived after a
four-second run had completed; only the later live-worker observer check is counted
as cancellation evidence. Deliberate worker-failure recovery, invalid sigma
settings and saved batch histories are covered by the full real-application gate
and mixed-workload check, rather than being claimed as separate mouse-driven tests.

The native results browser advanced from rows 1-200 to 201-340 and filtered
`GBPN_10` to two matching ROI rows. Details showed official IBSI code **GBPN**,
Pictologics-specific code **GBPN_10**, full name
`intensity_at_volume_fraction_0.10_GBPN_10`, the configuration-qualified key,
preprocessing, configuration hash and software provenance. Two-configuration
numerical independence is asserted by the separate Unicode-path gate, not inferred
merely from the 680-row count.

Profile Save, Save copy and Load were exercised through native dialogs, including
a filename containing spaces and `árvíz Ω`. Loading the saved single-preset profile
restored that selection after a second preset had been added. A native CSV export
used the same Unicode characters; both required sidecars were verified. Each
result checkpoint also exported standalone JSON and CSV with sidecars and saved
an MRB before its scene was replaced. The final CT scene remains open and exported.

**Refresh diagnostics** displayed the local allowlisted preview and the explicit
nothing-uploaded status. Assertions excluded the current subject/ROI names, local
paths, private target and Windows username. No diagnostics were copied or uploaded.
The existing sample-cache warning about a missing `.slicer-cache` sentinel was
retained; destructive cache operations stayed disabled.

## Preview (separate installation and environment)

The official Windows Preview installer named `Slicer-5.13.0-2026-10-01-win-amd64.exe`
was verified before installation with this official SHA-512:

```text
1d83eb380903462bf67fd4c1b05c80dbd2d1e6a7f99cd9091c9959920ea9793dbb389b93d0531397271e24cb86c7057b99366719be5f9f82c7f5e6709c192f0e
```

Its runtime identifies itself as **5.13.0-2026-09-30**, revision **35317**
(`2d6194e`), Python **3.12.10** (built Sep 30 2026 23:23:50), Qt **5.15.2**,
AMD64. Preserve the distinction between the October 1 download artifact date and
the September 30 runtime version/build label. The actual discovered launcher is
`C:\work\SlicerPreview-20261001\Slicer.exe`, alongside the preserved Stable install.

All four separate Preview lifecycle phases passed with exit **0**, using the new
`local-output/preview-lifecycle-01` root. Install/update each invoked pip once;
restart/restart-update invoked it zero times. Both extraction phases produced
340 successful rows. All scene comparisons had zero binary64 mismatches, exports
and profile readback passed, and same-version replacement selected a new qualified
target. Pictologics stayed at **0.5.1**. Shared NumPy **2.4.6** and Pillow **12.2.0**
remained unchanged; Preview did not reuse Stable's private environment.

The full Preview integration gate passed **56 tests, zero failures, zero skips**
in **599.837 s**, process exit **0**, on the corrected source commit. An earlier
launch was interrupted when the desktop session was lost and has no final process
report; it is not counted as a passing run. The completed repeat is
`local-output/windows-validation/preview-integration-02`.

The separate Unicode-path check passed with exit **0**: 680 successful rows for
two configurations and two ROIs, agreement with the independent configuration
runs, both CSV sidecars, and zero binary64 mismatches after scene reload. Public
MRHead and CTLiver demonstrations each produced **340 successful rows** through
the actual widget Run handler in separate visible Preview processes. They used
`standard_fbn_32`, two ROIs and whole-volume mode off, exported CSV/JSON and saved
MRB scenes before exiting **0**. Their elapsed observations were 102.159 s and
97.617 s, respectively; both had zero sampler errors. Stable remained open and
some interactive work overlapped, so these are functional observations, not
isolated Preview performance benchmarks.

Preview therefore passed the integration, key automated GUI, restart, export and
persistence checks with a separate qualified environment. No Preview-only defect
was found. The detailed native mouse/keyboard walkthrough was performed on Stable;
Preview's widget assertions and visible automated runs are identified separately.
The 30-case soak and 10,000/100,000-row benchmark were not repeated on Preview.

## Reproduction in PowerShell

Use the located official `Slicer.exe`; do not assume a default install path.
PowerShell 7 is used by the launcher to pass each argument separately, including
paths with spaces. No execution-policy changes are needed for local source files.
Keep `PICTOLOGICS_DEV_SOURCE` unset.

```powershell
Set-Location C:\work\SlicerPictologics
py -3.12 -m venv .venv
& .venv\Scripts\python.exe -m pip install pytest pytest-cov coverage packaging ruff mypy pyyaml numpy
& .venv\Scripts\python.exe -m compileall -q PictologicsSlicer PictologicsCLI scripts
& .venv\Scripts\python.exe -m ruff check PictologicsSlicer PictologicsCLI/PictologicsCLI.py scripts conftest.py tests
& .venv\Scripts\python.exe -m mypy
& .venv\Scripts\python.exe -m pytest --cov --cov-report=term-missing
& .venv\Scripts\python.exe -m json.tool Pictologics.json
# Check $LASTEXITCODE immediately after each command.

# Set $slicerExe to the executable discovered on this machine.
# Set $lifecycleRoot to a NEW, short, absolute test-owned directory.
foreach ($phase in @('install','restart','update','restart-update')) {
  & scripts/Invoke-SlicerValidation.ps1 -SlicerExe $slicerExe `
    -Script scripts/check_slicer_lifecycle.py `
    -OutputDirectory "local-output/new-run/lifecycle-$phase" `
    -Environment @{SLICERPICTOLOGICS_LIFECYCLE_ROOT=$lifecycleRoot;
                   SLICERPICTOLOGICS_LIFECYCLE_PHASE=$phase}
  if ($LASTEXITCODE -ne 0) { throw "Lifecycle phase failed: $phase" }
}
$target = (Get-Content "$lifecycleRoot/restart-update.json" -Raw | ConvertFrom-Json).dependency_target
& scripts/Invoke-SlicerValidation.ps1 -SlicerExe $slicerExe `
  -Script scripts/run_slicer_integration.py `
  -OutputDirectory local-output/new-run/integration `
  -Environment @{SLICERPICTOLOGICS_RUN_REAL_CLI_TEST='1';
                 SLICERPICTOLOGICS_TEST_DEPENDENCY_PATH=$target}
if ($LASTEXITCODE -ne 0) { throw 'Integration failed' }
# Also inspect the unittest summary: acceptance requires zero failures and skips.
```

The launcher starts and waits for one new process, saves stdout/stderr separately
and records the exit code in `process.json`. It never closes an existing Slicer.
By default it supplies `--no-splash --no-main-window --disable-settings
--ignore-slicerrc` and both absolute module paths. `-Visible` retains a main window
for disposable interactive demonstrations. Choose a new output directory each run.

For normal installation, enable Developer mode and add both source module folders
in Application Settings, then restart. Use **Install / update adopted release...**
and inspect `widget.logic.inspectDependencies().target` in Slicer's console.
Record shared versions before/after, export before closing a scene, reopen normally,
and verify an extraction reuses the installed target without pip.

## Additional reproducible checks

```powershell
& scripts/Invoke-SlicerValidation.ps1 -SlicerExe $slicerExe `
  -Script scripts/check_slicer_paths.py -OutputDirectory local-output/new-run/paths `
  -Environment @{PICTOLOGICS_PATHS_OUTPUT="$PWD/local-output/new-paths";
                 SLICERPICTOLOGICS_TEST_DEPENDENCY_PATH=$target}
# Require exit 0 and success=true in the new output's report.json.

foreach ($sample in @('MRHead','CTLiver')) {
  & scripts/Invoke-SlicerValidation.ps1 -SlicerExe $slicerExe `
    -Script scripts/check_slicer_public_demos.py -Visible `
    -OutputDirectory "local-output/new-run/demo-$sample" `
    -Environment @{PICTOLOGICS_DEMO_SAMPLE=$sample;
                   PICTOLOGICS_DEMO_OUTPUT="$PWD/local-output/new-demo-$sample";
                   PICTOLOGICS_SAMPLE_CACHE="$PWD/local-output/public-sample-cache";
                   SLICERPICTOLOGICS_TEST_DEPENDENCY_PATH=$target}
  if ($LASTEXITCODE -ne 0) { throw "Demo failed: $sample" }
}

& scripts/Invoke-SlicerValidation.ps1 -SlicerExe $slicerExe `
  -Script scripts/soak_slicer_batches.py -OutputDirectory local-output/new-run/soak `
  -Environment @{PICTOLOGICS_SOAK_OUTPUT="$PWD/local-output/new-soak";
                 PICTOLOGICS_SOAK_ROUNDS='6';
                 PICTOLOGICS_SAMPLE_CACHE="$PWD/local-output/public-sample-cache";
                 SLICERPICTOLOGICS_TEST_DEPENDENCY_PATH=$target}
if ($LASTEXITCODE -ne 0) { throw 'Mixed workload failed' }

& scripts/Invoke-SlicerValidation.ps1 -SlicerExe $slicerExe `
  -Script scripts/benchmark_slicer_workloads.py -OutputDirectory local-output/new-run/benchmark `
  -Environment @{PICTOLOGICS_BENCHMARK_OUTPUT="$PWD/local-output/new-benchmark";
                 PICTOLOGICS_SAMPLE_CACHE="$PWD/local-output/public-sample-cache";
                 SLICERPICTOLOGICS_TEST_DEPENDENCY_PATH=$target}
if ($LASTEXITCODE -ne 0) { throw 'Benchmark failed' }
```

Use separate processes and avoid overlapping measured runs. The public-demo check
calls the tracked scripts and actual GUI run handler, reusing an inspected private
target; it is automated widget evidence, not normal GUI installation or visual
approval. Public fixtures, attribution and derivation follow [performance.md](performance.md).

## Windows memory method

The optional workload sampler now uses Toolhelp parent/PID snapshots and
[PSAPI WorkingSetSize](https://learn.microsoft.com/en-us/windows/win32/api/psapi/ns-psapi-process_memory_counters)
for the owned Slicer and its descendants. It requests only
[limited process-query rights](https://learn.microsoft.com/en-us/windows/win32/api/psapi/nf-psapi-getprocessmemoryinfo).
No package installation, WMI dependency, command-line capture, or external sampler
process is required. The sampling thread's small overhead remains inside Slicer;
there is no separate sampler process to count. Existing POSIX `ps` helpers remain
excluded from their process-tree sums.

Counters are current working-set bytes, not private bytes, commit charge, or an
exact peak of unique physical memory. Shared pages can be counted more than once,
trimmed/swapped pages are not included, and short peaks between samples may be
missed. Descendants are inferred from each parent/PID snapshot; very short-lived
processes, PID reuse and children orphaned between snapshots are limitations. Legacy `rss_bytes` field names retain compatibility; reports explicitly
identify the Windows metric. The nominal interval is 0.5 seconds. Reports retain
error counts/types and the maximum observed sample gap. A failing counter or
vanished process invalidates that sample; startup failure or samples older than
10 seconds stop the workload's memory guard. Synchronous staging/table calls still
cannot be interrupted by that guard. The existing 12 GiB threshold is unchanged.

Deterministic tests cover tree selection, byte units, handle closure, snapshot/
enumeration/counter errors, and unavailable/stale measurements. The native smoke
check measured an owned parent and child with touched 32 MiB arrays while excluding
an unrelated sibling. Reproduce it in the developer environment:

```powershell
& .venv\Scripts\python.exe scripts/check_windows_memory.py `
  --output local-output/new-memory-smoke.json
```

## Stable mixed-workload result

The six-round mixed CT/MRI soak passed, exit **0**, with two ROIs and two
1 mm/FBN 16/32 configurations across five size variants. These are repeated variants
of two public scans, not 30 independent patients. The 33-case mixed phase completed
30 cases, failed the deliberate unreadable segmentation and invalid worker manifest,
and skipped one missing segmentation: **20,400 committed rows**, in **229.54 s**.
The separate cancellation phase completed one case, cancelled a worker observed alive,
and left the next case unstarted. Recovery completed all five cases without restarting.

Final totals were **36 successful cases / 24,480 rows**. Every case report agreed with
the committed feature rows. Prior rows and report histories stayed unchanged; repeated
fixtures agreed within `1e-9`. All worker/staging paths were released. Temporary
volume, segmentation and CLI-node counts returned to zero after each case; the
fixture-setup storage-node count stayed at 21 until scene replacement. Exports preceded
closure, and saving/reopening the scene restored every exact row and all **three**
reports. Multiline report-text regression also passed in the full integration gate.

The sampler recorded **469 samples**, **zero errors**, and a **5.491 s maximum gap**
(nominal interval 0.5 s). Observed simultaneous process-tree peak: **1,921,134,592
bytes (1.79 GiB)**. Separate GUI/descendant maxima were 1,234,997,248 and 1,090,699,264
bytes; these occurred at different times and must not be added as a measured peak.
The GUI working set was 376,856,576 bytes initially and 505,061,376 after releasing the
owned scene. This bounded run does not establish an absence of all retention or an
exact physical-memory peak. No macOS figures are used as Windows measurements.

## Stable public demonstrations and table scaling

The tracked MRHead and CTLiver demonstrations ran in disposable visible Slicer
windows through the actual GUI Run handler, with two ROIs, whole-volume mode off,
all feature families and only `standard_fbn_32`. Each produced **340 successful
rows**, exported CSV (with both sidecars) and JSON, saved its scene, and exited **0**.
The MRHead shutdown initially exposed a callback using already-destroyed widget
controls. Parenting its completion timer to the module widget fixed the teardown;
the repeated MRHead run had no traceback. A first harness launch without a main
window correctly could not select the GUI module; reproduction requires `-Visible`.
These are automated widget runs, not approval to publish new tutorial images.

The complete benchmark returned **0** and reported success for every case. Each
CT/MRI case used two ROIs and all feature families. Custom configurations used
1 mm spacing and FBN 32, except the explicitly named 0.5 mm case and two-configuration
FBN 16/32 case. The two-configuration case produced 680 rows, the others 340. The cold label means a new test-owned JIT cache, not a cold OS disk cache.

| Workload | Elapsed seconds | Sampled simultaneous tree working set, bytes |
| --- | ---: | ---: |
| CT, cold JIT cache | 89.096 | 1,942,343,680 |
| CT, subsequent run 1 | 2.641 | 968,646,656 |
| CT, subsequent run 2 | 2.811 | 984,076,288 |
| MRI | 3.022 | 1,372,913,664 |
| Large CT | 9.626 | 2,275,512,320 |
| Large CT with ROI cropping | 8.570 | 1,790,111,744 |
| CT, two configurations | 2.933 | 1,038,307,328 |
| CT, 0.5 mm spacing | 3.127 | 1,546,870,784 |
| Ten-case batch / 3,400 rows | 29.006 | 729,096,192 |

Large-table cases preserved the calculated schema and exercised commit, browser,
filtering, pagination, JSON export and scene save:

| Rows | Commit s | Browser s | Filter s | Page s | Export s | Scene save s | Sampled tree working set, bytes |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 10,000 | 0.354 | 0.212 | 0.018 | 0.008 | 0.350 | 0.123 | 489,951,232 |
| 100,000 | 3.663 | 2.118 | 0.113 | 0.008 | 3.327 | 0.473 | 1,023,762,432 |

The 10,000/100,000-row table phases captured only 2/9 samples, with maximum gaps
0.737/1.988 s. All benchmark measurements had zero sampling errors and remained
below the unchanged 12 GiB guard. The largest observed gap across cases was
5.051 s. Table timings are synchronous and the guard cannot interrupt their
individual operations. These table scenes were saved; exact scene readback was
separately tested by the integration, Unicode-path, lifecycle and mixed-batch gates.

## Evidence, limits and machine handoff

Raw evidence is under `local-output/windows-validation/`; Stable result roots
include `b1`, `s1`, `p1`, `d3-MRHead`, `d2-CTLiver` and `normal-gui-01` under
`local-output/`. Preview roots include `preview-lifecycle-01`, `preview-p1`,
`preview-d1-MRHead` and `preview-d1-CTLiver`. Native walkthrough assertions and
checkpoints are in `normal-gui-01/observations.json`; the final saved CT scene is
`normal-gui-01/CT-two-ROI/scene.mrb`. These local paths are handoff references,
not tracked artifacts.

The Stable source paths and Developer mode remain configured. Its final public
CT scene is open, with no active extraction; all results are exported and the
local pip assertion guard has been removed. Preview is installed alongside Stable.
For new disposable launches, discover the appropriate qualified target from the
normal installation or that runtime's lifecycle report and choose new output
roots. Do not overwrite the retained evidence or reuse an existing scene for
failure tests. The normal installation and lifecycle targets are distinct.

Only curated aggregate values, reproducible commands and source hashes are
published. Downloads, dependencies, raw logs, public images, derived scenes and
exports remain ignored. Published additions were reviewed for personal paths,
usernames and credentials. No new screenshots or tutorial images are included.

Remaining scope limits are explicit:

- Five real-symlink portable checks require privileges this account does not have;
  policy was unchanged and the skips are not claimed as passes.
- Source loading and private-dependency replacement passed. Extension Factory or
  Extensions Manager package installation/update was not tested.
- Native x64 and ASCII Slicer installation paths were tested. ARM/emulation and
  Unicode Slicer installation directories are not qualified.
- Stable memory observations cover bounded repeated variants of two public scans,
  with sampled working sets and documented sample gaps. They do not establish
  multi-hour, independent-patient or exact physical-peak qualification.
- Preview did not repeat the full manual walkthrough or Stable workload/table
  benchmark. Its completed application gates are enumerated above.
- Public extension registration, releases/tags and new image publication remain
  on hold. No repository settings were changed.

The changes are submitted in [PR #6](https://github.com/martonkolossvary/SlicerPictologics/pull/6).
All five jobs passed for the code commit in
[GitHub run 37120085011](https://github.com/martonkolossvary/SlicerPictologics/actions/runs/37120085011).
GitHub checks the released wheel on three operating systems and actual Slicer on
Linux; it does not replace the local Windows application evidence in this report.
The PR checks identify the latest documentation commit independently.

## Tested local source hashes

SHA-256 of the local file bytes used for the corrected application checks, on top
of baseline `bc0cd7cb1f7e7591fb5f8a6ddd2656f6714d2927`. The initial four Stable
lifecycle phases preceded these fixes; the corrected Stable integration, workloads
and long-path probe evidence are identified above. Hashes are independent of
private data and environment paths.

| Source | SHA-256 |
| --- | --- |
| `PictologicsCLI/PictologicsCLI.py` | `cd7472da66417d31fec3ff52ce05be7c493775ddce6f3c75f501a384ba4872d7` |
| `PictologicsSlicer/PictologicsLib/dependency_probe.py` | `29b42e568b0e464f1ee23bedd43e74c1df273c4a286fe67953df469bb7a7aa67` |
| `scripts/workload_support.py` | `dba89fc27c958b13898cea252bcdfd60e1cf9d83757918dcb108390bd7fe9393` |
| `scripts/benchmark_slicer_workloads.py` | `8457219e0f8f3a5e277b468cf92eae7159ebd89542833bdaf4bf6b68e31270e7` |
| `scripts/create_sample_data_demo.py` | `498d53ba6727ffc23a63fc2ba016b5d8dab94c350f6e261aed898a7e418b567b` |
| `scripts/Invoke-SlicerValidation.ps1` | `151790916c6913596168e9ab1570ac314ac132f51a39c82deb54acf43dade562` |
| `scripts/check_slicer_paths.py` | `972bc0efe4b9853e6f757fa351496c0db6889c626ecbe57b62cf5ce5e703caad` |
| `scripts/check_slicer_public_demos.py` | `0dc0102959ec15138674241ebdf9500c23ae3b718c8a67c7591ca72aa07eb3ba` |
| `scripts/check_windows_memory.py` | `44e8dbc071717c675d6028e5ea122035112ae371cc46e771aa716d2eafdb761c` |
