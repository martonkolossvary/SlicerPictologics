# Pictologics catalog submission draft (do not submit yet)

Updated on 2026-11-01. This is the draft text for the ExtensionsIndex pull request.
It is not an opened pull request or approval from Slicer maintainers. Submit it only
after the maintainer approves the registration. Keep the
[release readiness](release-readiness.md) with this draft.

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
- Package: the latest compatibility-qualified Pictologics release, with exact
  tested dependency versions for Linux, Windows, Intel macOS (also Apple silicon
  under Rosetta) and native Apple silicon. Intel macOS uses Numba 0.62.x, because
  newer Numba has no Intel Mac builds. A new upstream release is adopted only after
  all compatibility checks pass.
- Exact versions: they apply only in the private folder and in the separate worker
  process, so they cannot change or conflict with Slicer's own packages.
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
- [x] Publication: none yet. The README "How to cite" section cites Pictologics.
- [ ] Unused GitHub features: Wiki, Projects and Discussions are off (checked on
  2026-11-01). Also hide Releases and Packages in the About settings.
- [x] Safe: the extension downloads no binaries from unreliable sources. Wheels come
  from PyPI, or from the pip index that the user configured, after consent. Images
  and results stay on the computer, and the extension sends no data anywhere.

## Validation (Pictologics 1.0.0)

- The adoption workflow qualified Pictologics 1.0.0 on 2026-11-01: dependency
  resolution and released-wheel checks on Linux, Windows, Intel macOS and native
  Apple silicon, all real Slicer 5.12.4 tests on Linux, and the unit tests with
  100% scoped coverage.
- On Stable Slicer 5.12.4 for macOS (Intel, Rosetta), all integration tests
  passed with 1.0.0 from a source checkout on 2026-11-01.
- The unit-test files that CTest registers pass with the Python of Slicer 5.12.4,
  which has no pytest, as on the Extension Factory.
- Not tested with 1.0.0 yet: the Windows Slicer application, Slicer Preview, and
  Extension Factory packages.
- See the [release readiness](release-readiness.md).

## Before opening the pull request

1. Hide Releases and Packages in the About settings of the repository.
2. Run the ExtensionsIndex validator on a fresh clone of `main` (limit 100 MB).
3. Open the pull request against ExtensionsIndex `main` (Preview), with the current
   template. Ask the reviewers whether to add it to `5.12` (Stable) too.
4. When the Extension Factory builds the packages, check each one with
   `scripts/check_extension_package.py`. Then install it in a clean Slicer on each
   platform, and check restart, extraction, export and scene reload.
