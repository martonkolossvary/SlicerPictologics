# Pictologics catalog submission draft — do not submit yet

Prepared on 2026-09-30. The maintainer authorized publishing the source milestone,
including this draft, but not submitting it to ExtensionsIndex. This is not an
opened pull request or approval from Slicer maintainers. Keep the [handoff checklist](extensions-index-submission.md)
and [validation record](release-readiness.md) alongside this draft.

## Proposed title

Add Pictologics (Tier 1, Informatics)

## Proposed description

Pictologics extracts radiomics features—quantitative measurements of image
intensity, shape, and texture—from 3D images and segmented regions. It provides
background extraction, multi-region and batch analysis, reusable settings,
readable results/provenance, and full-precision CSV/JSON export. It is research
software, not for clinical diagnosis or treatment decisions.

- Repository/homepage: <https://github.com/martonkolossvary/SlicerPictologics>
- Catalog identity: `Pictologics`; category: `Informatics`; tier: `1`.
- Descriptor: [`Pictologics.json`](../Pictologics.json), following repository `main`.
- License: Apache-2.0, in the root `LICENSE` file and identified in the README.
- Modules: **Pictologics** (GUI) and **Pictologics Worker (internal)** (CLI).
- Package integration: latest compatibility-qualified Pictologics release, currently
  `0.5.1`, with exact tested dependency constraints. New upstream releases are
  adopted only after compatibility gates pass; an untested PyPI update is not
  installed blindly.
- No other Slicer extensions are required. Python wheels are installed into a
  private environment after explicit user consent, without replacing Slicer's
  shared packages.

## Checklist mapping for maintainer review

Adapt this evidence to the upstream PR template current at submission time.
Checked items describe repository preparation, not catalog acceptance.

- [x] Catalog/repository naming, `3d-slicer-extension` topic, category, and SCM
  reference are consistent.
- [x] Plain-language description includes the research-only limitation.
- [x] Apache-2.0 distribution permission is present. The official validator accepts
  `LICENSE`; a duplicate `LICENSE.txt` is unnecessary.
- [x] CMake metadata and the JSON descriptor agree on identity and dependencies.
- [x] Raw catalog icon and two screenshot URLs are publicly reachable. The genuine
  MRHead workflow image has two illustrative ROIs; the results image is explicitly
  labeled as a separate synthetic-phantom run. Existing approved assets are reused.
- [x] README includes the extension name, purpose, both module descriptions,
  illustrated usage, limitations, license, and links to the package/documentation.
- [x] Runtime dependency installation requires explicit consent and uses constrained,
  wheel-only package requirements. The configured pip index is honored, including
  institutional mirrors; it is not forcibly locked to PyPI. Developers may explicitly
  select a local source checkout. No direct URL/VCS requirements are accepted.
- [x] The reviewed extension runtime processes images/results locally; it has no
  image/result upload or telemetry implementation. Package installation uses the
  network after consent. This is a scoped source review, not a guarantee about
  arbitrary external dependencies or a user's custom package mirror.
- [x] On 2026-09-30 the maintainer declared **no known related patents**. This records
  the maintainer's knowledge, not legal clearance or an exhaustive patent search.
- [ ] Add any relevant publication supplied by the maintainer, if available. No
  Pictologics publication has been supplied for this draft; do not invent one.
- [ ] Review unused GitHub features. Wiki/Projects are enabled and Discussions is
  disabled as of this review. No public settings were changed. Releases/Packages
  About visibility has not been verified.

## Validation and explicit limits

- The official catalog validator at
  `2a06251a679e3d5a04cccec549c5df2febc5c4b0` passes against a fresh published clone
  of `dd1c5fc6b7365022fdc54e63a093a34ba90a8a03` (2026-09-30). It checks schema,
  metadata, repository size/topic, license, dependencies, and raw image URLs.
- That published baseline has a green five-job GitHub qualification run:
  <https://github.com/martonkolossvary/SlicerPictologics/actions/runs/36523318487>.
  This newer source milestone is not covered by that older remote run. Consult its
  exact-commit GitHub results and the current validation record before writing the
  eventual PR's test summary.
- Installed-Slicer functional/regression tests use source module paths. They are
  **not** acceptance of an Extension Factory archive or Extensions Manager install.
  The 2026-09-30 local run passed all 41 tests without skips, four separate
  install/restart/replacement/restart processes, and independent exact-value
  CSV/JSON read-back. Portable checks passed 537 tests / 400 subtests with 100%
  scoped library/worker coverage. Refresh these counts after any source change.
- Stable macOS application testing and the published Linux Slicer CI are available;
  actual Windows Slicer and Preview application acceptance remain unverified.
  Cross-platform Python-wheel tests do not fill those gaps.
- No full local Slicer SDK build is required or being pursued. After submission is
  authorized, inspect the Extension Factory artifacts with
  `scripts/check_extension_package.py`, then install the actual packages without
  source paths and repeat restart/extraction/export/lossless-scene checks.

## Before copying this into a public PR

1. Source commit/push was authorized on 2026-09-30. Record successful GitHub checks
   for that exact published revision; registration still needs separate approval.
2. Review the remaining presentation items above and refresh the validator, URLs,
   source revision, and test evidence. Do not attach local logs containing user
   paths or unreviewed screenshots.
3. Obtain explicit authorization to register the extension. Recheck the index
   branches (`main` for Preview and currently `5.12` for Stable), use the current
   upstream template, and state testing gaps honestly. Do not claim Tier 3
   cross-platform packaged-build qualification.
