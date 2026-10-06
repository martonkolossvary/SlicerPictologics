# Pictologics catalog submission draft (do not submit yet)

Updated on 2026-10-06. This is the draft text for the ExtensionsIndex pull request.
It is not an opened pull request or approval from Slicer maintainers. Submit it only
after the maintainer approves the registration. Keep the
[submission checklist](extensions-index-submission.md) and the
[validation record](release-readiness.md) with this draft.

## Proposed title

Add Pictologics (Tier 1, Informatics)

## Proposed description

Pictologics extracts radiomics features (quantitative measurements of image
intensity, shape and texture) from 3D images and segmented regions. It runs the
extraction in the background, analyzes several regions and batches of cases, saves
reusable settings, shows the results with their provenance, and exports
full-precision CSV or JSON. It is research software, not for clinical diagnosis or
treatment decisions.

- Repository and homepage: <https://github.com/martonkolossvary/SlicerPictologics>
- Catalog name `Pictologics`, category `Informatics`, tier 1.
- Descriptor: [`Pictologics.json`](../Pictologics.json), which follows the branch `main`.
- License: Apache-2.0, in the root `LICENSE` file and named in the README.
- Modules: **Pictologics** (the window) and **Pictologics Worker (internal)** (the
  background command-line module).
- Package: the latest compatibility-qualified Pictologics release, now 0.7.0, with
  exact tested dependency versions for each platform. Intel macOS, including Apple
  silicon under Rosetta, uses Numba 0.62.1; Linux and Windows use Numba 0.68.0. A new
  upstream release is adopted only after all compatibility checks pass.
- No other Slicer extension is required. Python wheels go into a private folder
  after the user agrees; Slicer's shared packages do not change.

## Checklist (upstream template of 2026-10-04)

- [x] The name `Pictologics` is specific and does not start with `Slicer`.
- [x] The repository name is `SlicerPictologics`.
- [x] The repository has the `3d-slicer-extension` topic.
- [x] The description gives the use in two sentences, with the research-only limit.
- [x] Known related patents: none. The maintainer declared this on 2026-09-30. It
  records the maintainer's knowledge, not a legal search.
- [x] License: Apache-2.0 in `LICENSE`. The official validator accepts `LICENSE`, so
  a `LICENSE.txt` copy is not necessary.
- [x] `scm_url` and `scm_revision` (`main`) are correct.
- [x] The icon and the two screenshot URLs are raw download URLs, and they load.
- [x] `Pictologics.json` and the top-level `CMakeLists.txt` agree; there are no
  extension dependencies.
- [x] The homepage (README) gives the name, a short description, images, and one
  description for each module.
- [ ] Publication: add a link if the maintainer supplies one. Do not invent one.
- [ ] Unused GitHub features: Wiki and Projects are on, and Discussions is off. Turn
  off Wiki and Projects, and turn off Releases and Packages in the About settings.
- [x] Safe: the extension downloads no binaries from unreliable sources. Wheels come
  from PyPI, or from the pip index that the user configured, after consent. Images
  and results stay on the computer, and the extension sends no data anywhere.

## Validation and limits

- The official validator (ExtensionsIndex `3650874`, 2026-10-04) passed all checks
  on a fresh clone of `main` at `e20ee70` on 2026-10-06. It checked the repository
  size (71.5 MB of 100 MB), the schema, name, category, topic, license, dependencies,
  and the icon and screenshot URLs. The structure checker also passed.
- GitHub run [37448759334](https://github.com/martonkolossvary/SlicerPictologics/actions/runs/37448759334)
  passed all five jobs for `e20ee70`: released-wheel checks on Linux, Windows and
  Intel macOS, real Slicer 5.12.4 on Linux, and unit tests with 100% coverage.
- The adoption run [37331419353](https://github.com/martonkolossvary/SlicerPictologics/actions/runs/37331419353)
  qualified Pictologics 0.7.0 on Linux, Windows and Intel macOS.
- Installed Slicer on macOS (Intel, Rosetta), with the published 0.7.0: Stable 5.12.4
  and Preview 5.13.0 (2026-10-01 build) each passed all 57 integration tests on
  2026-10-06. These tests load the modules from the source folder, not from an
  Extension Factory package.
- Windows Slicer Stable 5.12.4 and Preview 5.13.0 passed with Pictologics 0.5.1 on
  2026-10-04. Windows with 0.7.0 is not tested yet.
- A local Slicer SDK build is not necessary. After the submission, check the
  Extension Factory packages with `scripts/check_extension_package.py`. Then install
  the real packages, and repeat the restart, extraction, export and scene checks.

## Before copying this into a public pull request

1. Run the Windows Slicer check with 0.7.0, and update the results above.
2. Turn off the unused GitHub features, and add a publication link if one exists.
3. Run the validator again if the catalog data, icon or screenshots change.
4. Get the maintainer's approval to register. Use the ExtensionsIndex branches
   `main` (Preview) and `5.12` (Stable) and the current template, and name the
   untested platforms.
