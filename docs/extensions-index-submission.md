# ExtensionsIndex submission handoff

Target: Tier 1, catalog name **Pictologics**, category **Informatics**.
The descriptor is [`Pictologics.json`](../Pictologics.json). This is a readiness
checklist, not a claim of catalog acceptance or packaged-install verification.

**Public submission is on hold.** The maintainer stopped local Xcode/Qt/Slicer
SDK-build work on 2026-09-30. Installed-Slicer tests are the active qualification
path; Extension Factory packaging follows separately authorized submission. A
local SDK is not a prerequisite. The [local PR draft](extensions-index-pr-draft.md)
is preparation only and must be refreshed against the exact revision eventually
published.

## Completed repository preparation

- Matching CMake project/catalog identity, description, contributor, and Apache-2.0 license.
- GitHub `3d-slicer-extension` topic and public repository homepage.
- Public 128-pixel catalog icon and explicit 256-pixel runtime icon.
- Genuine screenshots using public MRHead sample data and a separate synthetic
  phantom, with source attribution and reproducible demo scripts.
- GUI and CLI discovery, real extraction, result-table display, and regression tests.
- Latest compatibility-qualified package adoption from PyPI; runtime pin remains 0.5.1.

## Validation evidence

On 2026-10-01, the complete upstream validator passed against a fresh clone of
published revision `9d72093f889486c9e96d255814178235803912b5`, including both
screenshot URLs. Its measured clone
size was 69.1 MiB (100 MiB limit). Schema, metadata, name/category/topic, SCM,
license, and dependency checks all passed. Validator checkout commit:
`2a06251a679e3d5a04cccec549c5df2febc5c4b0`. The remote `main` hash was unchanged
before and after validation. The exact published revision also passed
[all five GitHub compatibility jobs](https://github.com/martonkolossvary/SlicerPictologics/actions/runs/36767255998).
Later local diagnostics/recovery edits are not covered by that GitHub run.

Earlier local source-lifecycle testing found numeric rounding in Slicer
5.12.4 scene table storage. The published exact-value backup/restore fix passes
all four install/restart/same-version-replacement/restart phases: 340 values across
two ROIs survive scene reload exactly, and CSV/JSON exports retain full precision.
This is source-checkout acceptance on Stable macOS, not package or cross-platform
acceptance; see [current release readiness](release-readiness.md).

The upstream index's `main` (Preview) and `5.12` (Stable) branches were confirmed
on 2026-09-30; recheck the target branch and checklist at submission time.

## Remaining distribution gates

Before any further tutorial or catalog image is pushed, obtain the maintainer's
visual approval. The MRHead workflow replacement was explicitly approved on
2026-09-22. The prior synthetic results screenshot is unchanged; no unreviewed
replacement is included. Keep subsequent revisions local until approved; do not
treat automated or agent visual checks as approval.

### Source publication and registration approval

1. The authorized 2026-09-30 source publication and GitHub assessment are complete
   for `9d72093`. Publication of the diagnostics/recovery milestone was authorized
   on 2026-10-01; require green qualification for its exact pushed revision.
   No new screenshots are needed for this submission draft.
2. Retain the maintainer's 2026-09-30 declaration of **no known related patents**;
   update it if new information becomes known. Review optional GitHub
   presentation cleanup: Wiki and Projects are currently enabled, while Discussions
   is disabled. Do not change public repository settings under the present hold.
   The extension homepage already points to the README; an empty GitHub About
   website field does not invalidate that URL. These presentation items are not
   evidence of an unsafe or mechanically unusable catalog entry.
3. Re-run the upstream
   [description validator](https://github.com/Slicer/ExtensionsIndex/blob/main/scripts/check_description_files.py)
   on `Pictologics.json` from a scratch ExtensionsIndex checkout. It must inspect a
   fresh clone of published `main`, not only the local working tree, and verify
   repository size, schema, metadata, topic, license, and public image URLs. This
   passed for the revision above; repeat if submission assets or metadata change.
4. With explicit registration approval, open the ExtensionsIndex submission using
   the current [PR checklist](https://github.com/Slicer/ExtensionsIndex/blob/main/.github/PULL_REQUEST_TEMPLATE.md)
   and the appropriate Preview/Stable branches. Adapt the local draft and state
   unverified platforms/builds explicitly. Do not mark this step complete merely
   because the validator passes.

### After authorized submission: distribution acceptance

1. Follow Extension Factory build/package results for this Python-only extension.
   Do not substitute a hand-assembled archive or source-path test for a successful
   factory build. The retained [private packaging guide](private-packaging.md) is
   an inactive optional reference, not a required fallback.
2. Inspect the produced archive: both modules, GUI support library, `.ui`, selected
   PNG, CLI XML/script, the exact requirement file, and the tested-version constraints
   file must be present. Branding masters, screenshots, tests, and private dependency
   environments must not leak into runtime resources.
   Run `python scripts/check_extension_package.py <archive> --source <exact-checkout>`;
   retain its SHA256 report. The checker does not install the archive or replace
   the next application-acceptance gate.
3. Install the actual package into a clean Slicer profile with no source module
   paths. Check module discovery, dependency installation/reuse after restart,
   real extraction, result display, CSV/JSON export, and upgrade/restart behavior.
   Record Slicer version, OS/architecture, extension revision, package hash, and
   adopted Pictologics version. Repeat on the targeted Preview/Stable builds and
   supported desktop platforms; wheel-only Windows tests are not Windows Slicer tests.
4. Confirm catalog visibility and successful installation through Extensions
   Manager before announcing availability. Keep source tests, package-content
   auditing, and installed-package acceptance as separate evidence.

No ExtensionsIndex pull request has been opened by this task. Official package
build/install acceptance remains outstanding, but absence of a local Slicer build
tree does not block a Python-only submission. On 2026-09-30, the maintainer authorized
publication of this reviewed source milestone and assessment of GitHub tests.
Catalog registration, tags/releases, new imagery, and public settings changes
remain outside that authorization.
