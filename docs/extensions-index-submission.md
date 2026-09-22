# ExtensionsIndex submission handoff

Target: Tier 1, catalog name **Pictologics**, category **Informatics**.
The descriptor is [`Pictologics.json`](../Pictologics.json). This is a readiness
checklist, not a claim of catalog acceptance or packaged-install verification.

## Completed repository preparation

- Matching CMake project/catalog identity, description, contributor, and Apache-2.0 license.
- GitHub `3d-slicer-extension` topic and public repository homepage.
- Public 128-pixel catalog icon and explicit 256-pixel runtime icon.
- Genuine screenshots using public MRHead sample data and a separate synthetic
  phantom, with source attribution and reproducible demo scripts.
- GUI and CLI discovery, real extraction, result-table display, and regression tests.
- Latest compatibility-qualified package adoption from PyPI; runtime pin remains 0.5.1.

## Validation evidence

On 2026-09-21, the complete upstream validator passed against a fresh clone of
published revision `74c7320`, including both screenshot URLs. Its measured clone
size was 64.4 MiB (100 MiB limit). Schema, metadata, name/category/topic, SCM,
license, and dependency checks all passed. Validator source Git blob:
`c22e9aba7cc32129398fe396f98830f1dcdc4bc4`.

The upstream index currently has `main` (Preview) and `5.12` (Stable) branches;
recheck the target branch and checklist at submission time.

## Remaining distribution gates

Before any further tutorial or catalog image is pushed, obtain the maintainer's
visual approval. The MRHead workflow replacement was explicitly approved on
2026-09-22. The prior synthetic results screenshot is unchanged; no unreviewed
replacement is included. Keep subsequent revisions local until approved; do not
treat automated or agent visual checks as approval.

1. Re-run the upstream
   [description validator](https://github.com/Slicer/ExtensionsIndex/blob/main/scripts/check_description_files.py)
   on `Pictologics.json` from a scratch ExtensionsIndex checkout. It must inspect a
   fresh clone of published `main`, not only the local working tree, and verify
   repository size, schema, metadata, topic, license, and public image URLs. This
   passed for the revision above; repeat if submission assets or metadata change.
2. Configure/build/package using a matching Slicer build tree and the
   [documented CMake commands](../README.md#configure-and-package-the-extension).
   A downloaded Slicer app is sufficient for source tests but not a build SDK.
   Do not substitute a hand-assembled archive for an Extension Factory build.
3. Inspect the produced archive: both modules, GUI support library, `.ui`, selected
   PNG, CLI XML/script, and the exact requirement file must be present. Branding
   masters, screenshots, tests, and private dependency environments must not leak
   into runtime resources.
4. Install the actual package into a clean Slicer profile with no source module
   paths. Check module discovery, dependency installation/reuse after restart,
   real extraction, result display, CSV/JSON export, and upgrade/restart behavior.
   Record Slicer version, OS/architecture, extension revision, package hash, and
   adopted Pictologics version. Repeat on the targeted Preview/Stable builds and
   supported desktop platforms; wheel-only Windows tests are not Windows Slicer tests.
5. Open the ExtensionsIndex submission using the current
   [PR checklist](https://github.com/Slicer/ExtensionsIndex/blob/main/.github/PULL_REQUEST_TEMPLATE.md)
   and the appropriate Preview/Stable branches. State unverified platforms/builds
   explicitly. Follow Extension Factory build results before calling the extension
   available through Extensions Manager.

No ExtensionsIndex pull request has been opened by this task. No Slicer build tree
is available on this machine as of 2026-09-21, so official package build/install
acceptance remains the main technical gate.
