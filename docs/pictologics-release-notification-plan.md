# Implementation plan: notify SlicerPictologics after PyPI publication

Prepared on 2026-10-22 for the agents maintaining the **Pictologics package**.
This is an implementation specification; no upstream workflow was changed by
preparing it. The extension has already adopted 0.8.0 through its scheduled gate.

## Problem and verified evidence

Two upstream workflows currently listen independently to `release: types: [released]`:

- `.github/workflows/publish-pypi.yml` tests, builds and publishes the distribution.
- `.github/workflows/notify-slicer-extension.yml` immediately sends a
  `repository_dispatch` with event type `pictologics-release` and the release tag.

For 0.8.0 on 2026-10-21, the notification completed before publication:

| Event | UTC |
| --- | --- |
| Both upstream workflows created | 19:45:25 |
| Notification workflow completed | 19:45:34 |
| Extension discovery checked PyPI and rejected 0.8.0 | 19:45:45 |
| PyPI wheel upload | 19:56:15.374532 |
| PyPI sdist upload | 19:56:17.067972 |
| PyPI publishing workflow completed | 19:56:21 |

Evidence:

- [Early notification](https://github.com/martonkolossvary/pictologics/actions/runs/39664396958)
- [PyPI publication](https://github.com/martonkolossvary/pictologics/actions/runs/39664396896)
- [Failed extension discovery](https://github.com/martonkolossvary/SlicerPictologics/actions/runs/39664422736)
- [PyPI 0.8.0 metadata](https://pypi.org/pypi/pictologics/0.8.0/json)
- [Later successful adoption](https://github.com/martonkolossvary/SlicerPictologics/actions/runs/39680464506)

The extension correctly rejected a version absent from PyPI. The later scheduled
run resolved all three platforms, passed the shared compatibility gates and
published pin commit `ee2e93667050ef3555c3806e3f8c48fd29fd2336`.

## Required resulting behavior

The automatic sequence must be:

1. Stable release event.
2. Existing package tests, tag/version consistency checks and distribution build.
3. Successful upload to production PyPI.
4. Confirmation that the exact expected wheel is visible on production PyPI and
   is not yanked.
5. One automatic notification to SlicerPictologics.
6. Existing extension qualification; only its successful completion permits its
   automatic adopted-pin update.

Failed tests, failed upload, prereleases and TestPyPI uploads must not send this
notification. PyPI visibility failures must be reported explicitly. The existing
six-hour extension schedule remains a recovery path.

## Workflow changes in the Pictologics repository

### 1. Make notification depend on successful production publication

Use `.github/workflows/publish-pypi.yml` as the coordinating workflow. Add a
notification job with `needs: publish`, using the same stable-release condition.
Keep notification code reusable in `notify-slicer-extension.yml` through
`workflow_call`, or move its existing steps into the dependent job.

Remove the independent automatic `release` listener from the old notification
workflow. There must be exactly one automatic notification path. Do not keep both
the independent event and the new dependent job enabled.

Preserve Trusted Publisher configuration, the `pypi` environment, release tag/version
checks, package tests and distribution upload. Do not broaden this change into
compiler dependency policy or scientific feature changes.

### 2. Confirm the expected wheel is visible

Add a small standard-library helper, for example
`scripts/verify_pypi_release.py`, and call it after successful upload. It should:

- Accept the normalized stable `X.Y.Z` version and a trusted local wheel path.
- Validate the version and inspect the built wheel's distribution metadata without
  importing Pictologics or compiling kernels.
- Calculate that wheel's SHA-256 and record the expected filename and digest.
- Fetch `https://pypi.org/pypi/pictologics/<version>/json` with a finite request
  timeout and an identifying User-Agent.
- Require matching project name/version and the expected wheel filename, package
  type, SHA-256 and `yanked == false`.
- Retry only transient absence/network/server conditions, with a bounded total
  deadline, for example 180 seconds, and a capped retry interval. Respect a bounded
  `Retry-After` response. A timeout/error must not produce readiness output.
- Fail immediately on malformed versions, conflicting metadata/digests or a yanked
  expected artifact. Never substitute an older/newer release or accept only an sdist.
- Print a concise readiness record with version, filename and SHA-256. Do not
  include authorization headers, tokens or unrelated environment values.

An implementation that verifies in the publish job can pass validated outputs to
the dependent notification job. Another job must receive the built artifact or its
trusted filename/digest; it must not reconstruct expected hashes from the same
remote response it is supposed to verify.

### 3. Send the existing dispatch contract

Keep the receiver repository and event unchanged:

```json
{
  "event_type": "pictologics-release",
  "client_payload": {"version": "0.8.0"}
}
```

Use the verified version as a structured action input, rather than interpolating
unvalidated event text into shell code. The extension currently accepts an
optional `v` prefix; normalized output is sufficient.

Keep `SLICER_EXTENSION_DISPATCH_TOKEN` scoped to the notification step/job. Do not
print it. If it is absent, retain an explicit notice that publication succeeded
but notification was skipped and scheduled discovery remains available.

If dispatch fails, report the notification failure distinctly from publication.
The package is already published at that point. Recovery must not require uploading
the same distribution again. A manual notification entry point may reuse the same
stable-release/PyPI-readiness checks without invoking publication.

### 4. Correct the workflow comments and documentation

The old sender comments say the extension opens a review-only pull request and
never auto-merges. The actual extension policy automatically commits the exact
pin/constraints after successful compatibility checks. Document the actual
receiver behavior and its independent scheduled recovery path.

## Verification required before merging

Add meaningful helper tests with mocked HTTP/time behavior; do not publish test
releases to production PyPI to exercise failure paths.

| Case | Required result |
| --- | --- |
| Expected non-yanked wheel, matching version/hash | Ready, then dispatch |
| HTTP 404 initially, matching wheel appears before deadline | Bounded retry, then ready |
| Wheel remains absent or only sdist exists | Timeout/failure; no dispatch |
| Transient timeout, 429 or 5xx | Bounded retry; no unbounded loop |
| Yanked expected wheel | Failure; no dispatch |
| Wrong version/name, malformed JSON or conflicting hash | Failure; no dispatch |
| Invalid/prerelease version | Rejected before notification |
| Tests or upload fail | Dependent notification job skipped |
| TestPyPI workflow | No production extension notification |
| Missing dispatch token | Explicit skipped-notification notice |
| Dispatch API failure after upload | Publication remains identifiable as successful |

Run the repository's lint/type/test requirements and actionlint. Inspect workflow
dependencies and conditions to verify ordering; a helper test alone does not prove
the notification job waits for publication. Check that the independent old release
listener is absent and that existing publication protections remain present.

## Scope in the extension repository

No extension resolver relaxation is required to correct the proven ordering bug.
Keep rejecting unpublished, fully yanked and sdist-only candidates. Keep all
per-platform qualification gates, exact constraints and non-force publication.
The extension's existing scheduled discovery already recovered the 0.8.0 release.

Any receiver retry work is a separate hardening change: it must distinguish
transient visibility from rejection, retain a deadline, and must not make an
unavailable release appear qualified. This plan prioritizes ordering at the sender.

## Handoff deliverables

The upstream implementation should supply the reviewed workflow/helper changes,
test results, and a concise explanation of notification-failure recovery. No new
package version, release, tag, production upload, or extension registration is
authorized by this implementation plan alone.
