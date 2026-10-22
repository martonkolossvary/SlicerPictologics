# macOS application acceptance with Pictologics 0.8.0

Record date: 2026-10-22. This record concerns the published PyPI wheel and the
installed Slicer application using the extension's source checkout. Extension
Factory package installation and Windows application acceptance are separate gates.

## Source and release

- Source base: `ee2e93667050ef3555c3806e3f8c48fd29fd2336`; local branch
  `pre-submission` fast-forwarded from `5da869f` to that qualified adoption commit.
- Published Pictologics: **0.8.0**.
- Wheel SHA-256 from PyPI:
  `948bce16a00587639e95447bd33d8f7416ebedaeeefe28dd3c961ec6aab50458`.
- [Adoption run 39680464506](https://github.com/martonkolossvary/SlicerPictologics/actions/runs/39680464506)
  passed all resolution, qualification and publication jobs. Its real Linux Slicer
  suite passed 57 tests; its portable suite passed 608 tests with 100% scoped coverage.
- Qualification source revision in the constraints:
  `573420a7281990d610d7897483115f37f7c13d42`.

## Local runtime and isolation

- Installed application: Slicer 5.12.4, `/Applications/Slicer.app`.
- Python: CPython 3.12.10 x86_64, running through Rosetta on Apple Silicon.
- All application checks use disposable processes with `--disable-settings` and
  `--ignore-slicerrc`; the developer-source dependency override is unset.
- Test dependency environments, compiler caches, exports, public-data scenes and
  logs are under ignored `local-output/acceptance-080-2026-10-22/`.
- Normal Slicer sessions and active per-user dependency environments are separate
  from these test targets. No new screenshot publication is included.

## Completed execution

All eight owned Slicer validation processes completed with exit code 0. The
report assertions and the final integration summary were inspected.

| Check | Status |
| --- | --- |
| Four-process fresh install/restart/replacement/restart lifecycle | Passed; all four processes exited 0 |
| Exact installed dependency closure | Passed; 17 exact distributions |
| Full installed-Slicer integration suite with real workers | Passed; 57 tests, zero failures/skips, 808.529 seconds, process exit 0 |
| Public MRHead widget extraction, two ROIs, exports and scene | Passed; process exited 0, 340 successful rows |
| Public CTLiver widget extraction, two ROIs, exports and scene | Passed; process exited 0, 340 successful rows |
| Mixed batch with actual worker cancellation and recovery | Passed; process exited 0, 10,880 rows and three exact report histories |
| Portable checks after documentation synchronization | Passed; 608 tests, 100% scoped coverage; Ruff/Mypy passed |

The four lifecycle reports record pip-call counts **1, 0, 1, 0** for install,
restart, same-version replacement, and restart after replacement. Each preserves
340 feature rows across two ROIs and reports zero binary64 scene-precision
mismatches. The final phase re-extracts 340 rows and checks numerical parity with
the saved result. Shared Slicer packages remain NumPy 2.4.6 and Pillow 12.2.0.
The private target uses Numba 0.62.1, llvmlite 0.45.1, NumPy 2.3.5 and Pillow 13.0.0.

This lifecycle exercises **replacement of the same 0.8.0 version**, not a live
0.7.x-to-0.8.0 upgrade. Installation consent is scripted in the test process;
restart explicitly forbids pip. It does not alter the normal per-user target.

Both public demonstrations use the actual widget run handler and standard FBN32,
with whole-volume mode disabled and two illustrative regions each. Each committed
340 successful rows, exported CSV plus provenance/catalog companions and JSON, and
saved its scene before exiting. They are automated widget checks, not a manual
visual walkthrough or clinical segmentation validation. Existing checksum-verified
MRHead and CTLiver caches were reused; no new screenshots were captured.

The two source sample hashes are:

- MRHead: `cc211f0dfd9a05ca3841ce1141b292898b2dd2d3f08286affadf823a7e58df93`.
- CTLiver: `e16eae0ae6fefa858c5c11e58f0f1bb81834d81b7102e021571056324ef6f37e`.

These runs and the integration suite may execute concurrently. Recorded times and
RSS are observations under that load, not dedicated performance benchmarks.

## Bounded mixed batch and recovery

The existing `soak_slicer_batches.py` harness ran two rounds on five size/modality
variants of the two public scans. Each successful case had two ROIs and two FBN
configurations (16 and 32 bins). They are repeated public fixtures, not independent
patients. The three phases passed:

| Phase | Case outcomes | Newly committed rows |
| --- | --- | --- |
| Mixed | 10 completed, two deliberately failed, one skipped | 6,800 |
| Cancellation | One completed, one cancelled live worker, one not started | 680 |
| Recovery in the same Slicer process | Five completed | 3,400 |

The cancellation report confirms that the worker was observed alive before the
request. Worker/staging cleanup completed before recovery. Prior rows and prior
batch histories stayed unchanged. The final 10,880 rows and all three report
documents were saved and reloaded exactly; terminal controls and timers recovered.
The injected failures were an invalid segmentation and an invalid worker manifest.

Only Stable is installed in `/Applications` for this run. No local Preview or
Windows application outcome is claimed here.

The integration suite includes configuration/profile and FBS scene migration,
readiness/run/elapsed-time controls, result browsing/provenance, exact scene
persistence, export recovery, transformed geometry, real asynchronous extraction,
real multi-case execution, crop parity, and real worker failure followed by a
successful run. Its controlled CLI tests exercise cancellation feedback; the
separate mixed batch above supplies the live-worker cancellation evidence.

## Evidence and limits

The ignored evidence root is `local-output/acceptance-080-2026-10-22/`:

- `lifecycle-install.log`, `lifecycle-restart.log`, `lifecycle-update.log`,
  `lifecycle-restart-update.log`; four corresponding JSON reports and exports in
  `lifecycle/`, with `synthetic-scene.mrb` and the settings profile.
- `dependency-audit.log`: 17 exact selected distributions and their transitive
  requirements passed against the adopted constraints.
- `integration-080.log`: all 57 tests completed without failures/skips.
- `portable-tests.log`: 608 tests, 2,658 scoped statements, 100% coverage.
- `public-MRHead/report.json` and `public-CTLiver/report.json`, their process logs,
  CSV/JSON exports with companions, and saved `demo.mrb` scenes.
- `mixed-batch/report.json`, `mixed-batch.log`, phase exports, and
  `mixed-batch/results-and-reports.mrb`: final success, exact rows/report histories,
  worker release, immutable previous results and bounded memory observations.

The mixed-batch sampler retained 390 samples and zero sample errors; the maximum
sample gap was 5.09 seconds. Its sampled process-tree maximum was 4,337,598,464
bytes (about 4.04 GiB), subject to RSS shared-page double counting and concurrent
validation load. This is neither an exact memory peak nor a hardware requirement.

Adopted constraints SHA-256:
`01947ca3480248437196325e826e9ecc3a6ed15c3f6f347bc8f3b8984a3d87a2`.

These are scripted source-checkout application checks on Stable macOS. They do
not establish manual visual approval, Preview/Windows 0.8.0 acceptance, a
cross-version 0.7.x upgrade, Extension Factory archive contents or Extensions
Manager installation. The normal per-user environment and other sessions were
not used as test targets. No package/extension release, tag, registration, public
image, upstream code change, commit or push was performed by this milestone.
