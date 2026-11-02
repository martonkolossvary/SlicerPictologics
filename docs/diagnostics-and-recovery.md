# Diagnostics and recovery

This local pre-catalog milestone adds a support-report preview and regression
coverage for failure recovery. It does not submit the extension, publish a release,
change dependencies, or require a Slicer SDK build. Extension and existing
job/result schema versions are unchanged.

## Privacy boundary

Diagnostics are constructed from explicitly selected runtime facts and structured
session state. The Slicer-neutral serializer uses fixed field names, enumerated
statuses/failure codes, bounded integer counts and restricted version formats.
Unknown fields are discarded; unknown strings are replaced. It does not redact or
serialize scene nodes, result provenance, worker output, exception messages,
environment variables, DICOM fields, file paths, or user-supplied names.

The collapsed panel is opt-in: **Refresh diagnostics** creates a read-only snapshot;
**Copy preview** copies that exact snapshot. State changes do not silently change
what gets copied. Reports are not uploaded or persisted in MRML/settings. Clipboard
contents are then subject to the user's operating-system/clipboard-manager behavior.
Refreshing checks distribution metadata only and never imports Pictologics in the
GUI, installs packages, starts a probe/worker, or needs network access.

Session failure codes distinguish dependency installation, run preparation, worker
failure, rejected result payloads, partial results and export failure. Recovery
suggestions are fixed text. A batch run summary refers to the latest case/run,
not a patient list or an aggregate batch report. Starting a new run resets its
counts; elapsed time freezes when it finishes. Restarting/reloading the module
starts a new diagnostic session. Detailed local error dialogs and processing logs
are outside the privacy-safe report and must be reviewed separately before sharing.

## Regression coverage

Portable tests cover malicious/unexpected strings in every report section,
patient/path-like strings, unsupported fields/types, non-finite or oversized counts,
deterministic JSON, preview versions and all recovery codes. Real-Slicer GUI tests
exercise the actual Designer controls, all dependency metadata states, inspection
failure, and a mocked clipboard so tests never replace the user's clipboard.

Failure-injection tests run only in disposable Slicer scenes/settings and
test-owned directories. They do not break the machine's network, fill its disk,
change directory permissions, or download packages:

| Failure | Required recovery |
| --- | --- |
| Offline/interrupted candidate install | Previous active pointer and files unchanged; partial candidate removed |
| Candidate metadata/import/JIT rejection | Candidate never activated; previous environment reused on simulated restart |
| Active-pointer replacement denied | Previous pointer unchanged; rejected candidate and temporary pointer removed |
| Fresh install declined or failed | No active pointer published; subsequent approved synthetic install succeeds |
| Worker failed/cancelled or missing/malformed/mismatched output | Previous values/provenance unchanged, controls unlocked, owned staging removed |
| JSON replacement denied/disk-full error | Previous archive and in-scene table unchanged; retry succeeds |
| CSV companion staging or publication failure | Complete previous file set restored; in-scene table unchanged; retry succeeds |
| CSV rollback also denied | Recovery copies retained; error warns not to use the incomplete export set |

The opt-in real-worker gate additionally launches a genuine CLI process with a
deliberately invalid manifest, confirms the GUI retains the completed table, then
runs a successful extraction into that same table. Existing geometry, batch,
configuration, persistence and extraction regressions remain in the full suite.

## Boundaries

Candidate interruption tests raise a catchable interruption; they are not a
power-loss or forced-process-kill test. No new remote release is simulated or
published by these tests. Mock package metadata proves installer orchestration,
not a wheel's scientific/API correctness; the existing released-wheel and real
worker gates provide that separate qualification.

CSV publication stages the CSV, provenance and (when present) catalog beside the
destination, copies existing files with their permissions for recovery, and rolls back already-published
files on caught replacement failures. Individual renames are atomic; the file set
is not a durable multi-file filesystem transaction. Power loss, forced termination
and concurrent edits by another application are not covered. JSON remains the
single-file archive option. Exports require space for the staged set and previous
copies. Retained recovery directories may contain patient data: they are not
included in diagnostics and should not be uploaded as support attachments.

## Running the checks

The portable regression command and installed-Slicer instructions are in
[development.md](development.md). The existing `scripts/run_slicer_integration.py`
runner includes the new GUI/recovery tests automatically. The real-worker tests
use `SLICERPICTOLOGICS_RUN_REAL_CLI_TEST=1` and an existing qualified private target;
all installer failure tests mock pip even when this opt-in gate is enabled.

On 2026-10-01, the full macOS Slicer 5.12.4 run passed all 49 tests with no skips;
the final fast rerun passed 42 tests with seven real-worker gates intentionally
disabled. All 547 portable tests passed with 100% scoped library/worker coverage.
The new portable modules also pass directly under Slicer's Python using `unittest`.
These are local source-checkout checks, not GitHub or packaged-install validation.
