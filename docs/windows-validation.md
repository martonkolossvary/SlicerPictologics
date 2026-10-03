# Windows application validation

Validation dates: 2026-10-02 to 2026-10-03. This report separates installed Windows Slicer
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
**593 passed, 5 skipped, 473 subtests passed** (7.48 s), exit **0**, with all
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
It does not substitute for the normal GUI installation/restart walkthrough.

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

Preview full integration, public-widget and Unicode export checks are in progress.

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

## Evidence and remaining application checks

Raw evidence is under `local-output/windows-validation/`; result roots include
`b1`, `s1`, `p1`, `d3-MRHead` and `d2-CTLiver` under `local-output/`.
Installer/downloads, private dependencies, logs, public images and derived scenes
stay ignored. Machine usernames, personal absolute paths and raw failure messages
are not publication evidence. Only curated aggregate values and source hashes
belong here.

Normal GUI installation/restart and separate Preview results are still being
gathered. Desktop interaction resumed long enough to enable Developer mode, add
both source-module paths, restart normally, and discover the GUI module and
internal worker. A later Windows input access-denied error paused further clicks;
the existing empty session was preserved. This is an intermediate report and does
not claim complete interactive acceptance.

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
