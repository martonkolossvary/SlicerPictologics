# ExtensionsIndex submission handoff

Target: Tier 1, catalog name **Pictologics**, category **Informatics**.
The descriptor is [`Pictologics.json`](../Pictologics.json). This is a readiness
checklist, not a claim of catalog acceptance or packaged-install verification.

**Public submission waits for the maintainer's approval of the registration.**
Installed-Slicer tests are the active qualification path. The Extension Factory
builds the packages after the submission, so a local SDK build is not necessary.
The [pull request draft](extensions-index-pr-draft.md) holds the submission text.

## Completed repository preparation

- Matching CMake project/catalog identity, description, contributor, and Apache-2.0 license.
- GitHub `3d-slicer-extension` topic and public repository homepage.
- Public 128-pixel catalog icon and explicit 256-pixel runtime icon.
- Genuine screenshots using public MRHead sample data and a separate synthetic
  phantom, with source attribution and reproducible demo scripts.
- GUI and CLI discovery, real extraction, result-table display, and regression tests.
- Latest compatibility-qualified package adoption from PyPI; the runtime pin is 0.7.0
  (adopted on 2026-10-05).

## Validation evidence

On 2026-10-06, the upstream validator (ExtensionsIndex
`36508746632a78ab70f5bfb041c26dae8359a61d`) passed all checks against a fresh clone
of `main` at `e20ee7090e5e4ac0309f05bd3854dbe6c132eb71`, including both screenshot
URLs. The clone size was 71.5 MB (limit 100 MB). The schema, metadata,
name/category/topic, SCM, license, and dependency checks passed. The repository
structure checker also passed with `Pictologics.json` added. The same revision
passed [all five GitHub compatibility jobs](https://github.com/martonkolossvary/SlicerPictologics/actions/runs/37448759334).

Earlier local source-lifecycle testing found numeric rounding in Slicer
5.12.4 scene table storage. The published exact-value backup/restore fix passes
all four install/restart/same-version-replacement/restart phases: 340 values across
two ROIs survive scene reload exactly, and CSV/JSON exports retain full precision.
This is source-checkout acceptance on Stable macOS, not package or cross-platform
acceptance; see [current release readiness](release-readiness.md).

The upstream index's `main` (Preview) and `5.12` (Stable) branches were confirmed
on 2026-09-30; recheck the target branch and checklist at submission time.

## Remaining distribution gates

The maintainer approved both current catalog images on 2026-10-05. Before any
further tutorial or catalog image is pushed, obtain the maintainer's visual
approval; automated or agent visual checks are not approval.

### Source publication and registration approval

1. The source on `main` (`e20ee70`) passed all five GitHub jobs. At submission, the
   exact submitted revision must have green checks.
2. Retain the maintainer's 2026-09-30 declaration of **no known related patents**;
   update it if new information becomes known. The template asks to hide unused
   GitHub features: turn off Wiki and Projects (Discussions is already off), and turn
   off Releases and Packages in the About settings. The extension homepage points to
   the README; the empty GitHub About website field does not invalidate it.
3. Run the upstream
   [description validator](https://github.com/Slicer/ExtensionsIndex/blob/main/scripts/check_description_files.py)
   on `Pictologics.json` from a scratch ExtensionsIndex checkout again if the catalog
   data, icon or screenshots change. It must inspect a fresh clone of published
   `main`, not only the local working tree.
4. With explicit registration approval, open the ExtensionsIndex submission using
   the current [PR checklist](https://github.com/Slicer/ExtensionsIndex/blob/main/.github/PULL_REQUEST_TEMPLATE.md)
   and the branches `main` (Preview) and `5.12` (Stable). Adapt the draft, and state
   the untested platforms and builds. Do not mark this step complete only because
   the validator passes.

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

No ExtensionsIndex pull request is open. Package build and install acceptance follow
the submission; a local Slicer build tree is not necessary for this Python-only
extension. Catalog registration, tags or releases, new images, and public settings
changes need the maintainer's approval.
