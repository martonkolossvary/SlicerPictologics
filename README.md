# SlicerPictologics

[![CI](https://github.com/martonkolossvary/SlicerPictologics/actions/workflows/ci.yml/badge.svg)](https://github.com/martonkolossvary/SlicerPictologics/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/martonkolossvary/SlicerPictologics/graph/badge.svg)](https://codecov.io/gh/martonkolossvary/SlicerPictologics)

SlicerPictologics is a 3D Slicer extension for running
[Pictologics](https://github.com/martonkolossvary/pictologics) radiomic feature
extraction on scalar volumes, selected segmentation regions, and whole-volume
regions. The displayed module is **Pictologics** in Slicer's **Informatics**
category.

The development MVP provides:

- one 3D scalar-volume input;
- any number of independently processed segments from one segmentation, plus an
  optional whole-volume region;
- the six Pictologics standard presets, an in-app single-configuration builder
  (feature families, resampling, discretisation, and voxel-validity/sentinel mode),
  and optional custom YAML/JSON configuration with authoring aids;
- background execution in a scripted CLI process, progress, and cancellation;
- atomic long-form results in a `vtkMRMLTableNode`, with replace or append behavior;
- CSV export with a provenance sidecar, or a self-contained JSON export, with
  per-run provenance retained when tables are appended; and
- on-demand installation of Pictologics and its dependencies into a private target.

This is research software. It is not a medical device and must not be used for
clinical diagnosis or treatment decisions.

## Compatibility and package policy

The baseline is **3D Slicer 5.12+**. The provisional adopted version is
`pictologics==0.5.0`. [PyPI](https://pypi.org/project/pictologics/) publishes that
exact, non-yanked release as a `py3-none-any` wheel and source distribution. The
module's normal install/update action therefore installs the 0.5.0 wheel from PyPI.
The Slicer compatibility gate must still pass before catalog release; the explicit
sibling-source override is only for testing unpublished local Pictologics changes.

The exact private requirement records the newest release accepted by the extension's
compatibility process. On install/update, pip installs that adopted release and the
actual imported version is recorded in result provenance. The extension never imports
or upgrades Pictologics during Slicer startup. Release automation advances the adopted
version in
`PictologicsSlicer/requirements-pictologics.txt`, requires a binary wheel, installs it
into a private target, runs the API/JIT probe and a real anisotropic NIfTI extraction,
then opens a pull request; it never merges that pull request. Actual Slicer
Stable/Preview compatibility results remain a required human gate.

Every push and pull request also runs ordinary CI (`.github/workflows/ci.yml`): syntax,
unit and worker tests, catalog-metadata validation, and the real API/smoke/geometry-parity
checks against the adopted wheel. New upstream releases can propose a bump automatically:
the Pictologics repository dispatches a `pictologics-release` event to this repository
(sender workflow `notify-slicer-extension.yml`), which requires a
`SLICER_EXTENSION_DISPATCH_TOKEN` secret on the Pictologics repo and is otherwise inert.

Exact pinning is safe here because the entire dependency graph lives in a private
target used only by the worker; it cannot constrain or downgrade packages shared by
Slicer or other extensions. This makes “latest” mean the latest compatibility-qualified
release adopted by a reviewed wrapper change, not an untested upgrade loop at startup.

### Why dependencies are private

Pictologics is installed under an extension-owned user cache and made visible only to
the background job. Each accepted environment has an immutable versioned directory;
an atomic pointer selects it for new jobs, while already-running jobs keep their
original path. It is not installed into or allowed to replace Slicer's shared Python
packages. This is required for Slicer 5.12: its environment includes NumPy
2.4.6 while Pictologics' Numba 0.62.1 requires NumPy `<2.4`, and it includes Pillow 12
while the current Pictologics constraint is Pillow `<12`.

The background process sets `PICTOLOGICS_DISABLE_WARMUP=1` before importing
Pictologics, removes that setting after import, and then calls `warmup_jit()` once.
This keeps module discovery fast while still compiling kernels before extraction.

## Install

### Extensions Manager

`SlicerPictologics.json` is a Tier-1 ExtensionsIndex draft. Until it has been submitted,
accepted, and built by the Slicer extension factory, install from source as described
below. Once published, use **View → Extensions Manager**, search for Pictologics,
install it, and restart Slicer.

### Load a development checkout

Python-only Slicer modules do not require a local Slicer build for source development.

1. In Slicer, enable **Developer mode** under **Edit → Application Settings →
   Developer**.
2. Add the absolute `PictologicsSlicer` and `PictologicsCLI` directories to **Edit →
   Application Settings → Modules → Additional module paths**. Dragging the two
   directories into Slicer and choosing **Add Python scripted modules** is equivalent.
3. Restart Slicer and open **Informatics → Pictologics**.

Ordinary users should leave `PICTOLOGICS_DEV_SOURCE` unset so the installer retrieves
the exact adopted wheel from PyPI. For local development against unpublished changes
in the sibling Pictologics checkout, set that variable before starting Slicer, then use
**Install / update adopted release…** in the module. For this workspace on macOS/Linux:

```sh
export PICTOLOGICS_DEV_SOURCE="$(cd ../Pictologics && pwd)"
```

The normal user path accepts local files only for this override; remote VCS/URL
sources are rejected. Select the update action again whenever the checkout changes,
even if its declared version has not changed.

### Configure and package the extension

A build is useful for validating discovery and producing the same package layout as
the extension factory. `Slicer_DIR` must point to a Slicer build tree, not a downloaded
application bundle.

```sh
cmake -S . -B ../SlicerPictologics-build \
  -DSlicer_DIR=/absolute/path/to/Slicer-build \
  -DCMAKE_BUILD_TYPE=Release
cmake --build ../SlicerPictologics-build --config Release
ctest --test-dir ../SlicerPictologics-build -C Release --output-on-failure
cmake --build ../SlicerPictologics-build --config Release --target package
```

## Use

1. Load a 3D scalar volume and, for region-based extraction, a segmentation.
2. Open **Pictologics**, choose the volume, check one or more segments, and decide
   whether to include the whole volume. Overlapping segments remain independent.
3. Check one or more standard presets and/or add one more configuration via
   **Additional config**: *Build one in app* (choose feature families, resampling,
   discretisation, and voxel-validity/sentinel mode) or *Load from file* (browse to a
   custom Pictologics YAML/JSON, generate a starter with **New from preset…**, or run a
   structural **Validate** pre-check).
4. Choose or create an output table, then select **Run radiomics**.
5. On first use, review and approve installation into the private dependency target.
   No global Slicer package is replaced. The first run is slower because of JIT warmup.
6. Use **Cancel** to stop the background job. Cancellation or fatal failure preserves
   the previous table; completed results are committed to the scene together.
7. Select **Export table as CSV or JSON…** to save the current results table. Enable
   **Export wide layout** for one row per ROI with `configuration__feature` columns
   instead of the default long layout. JSON includes the complete per-run provenance
   history and feature data dictionary; CSV writes companion `.provenance.json` and
   `.dictionary.csv` files (the latter is the Slicer-side equivalent of Pictologics'
   `describe_features()`).

The extension serializes temporary inputs as NIfTI (`.nii.gz`) because Pictologics
loads NIfTI directly. Temporary files and MRML nodes are removed after success,
failure, cancellation, or module teardown as soon as the worker exits. GUI and worker
PID markers protect staging used by another live Slicer instance. After a process
crash, dead-owner staging is purged once it is an hour old on module entry or before a
new job; a malformed marker is retained conservatively for at most seven days.

## Current limitations

- One scalar 3D volume is processed per run; vector/4D and patient-batch workflows are
  out of scope.
- The MVP accepts segmentation regions and whole-volume mode, not multi-label labelmap
  selection.
- Nonlinear parent transforms are rejected. Resample with an explicit interpolation
  choice before running. Linear transforms are hardened into temporary geometry.
- Cancellation is at the CLI-process/job boundary. The current Pictologics 0.5.0 API
  has no cooperative progress/cancellation callback, so a running native kernel cannot
  report fine-grained progress.
- The in-app builder composes a single configuration (families, resample, discretise,
  source mode). The full schema-driven, multi-step/multi-configuration builder is still
  deferred: the current Pictologics source has presets and configuration serialization,
  but not the proposed public schema, structured-validation, or public processing-log
  APIs. Advanced steps (resegmentation, outlier filtering, IBSI-2 image filters, custom
  discretisation cut-offs) remain reachable through a custom YAML/JSON file. The
  in-app **Validate** aid is a structural pre-check only; the worker performs the
  authoritative validation.
- Retired immutable dependency environments are retained to avoid deleting libraries
  that another Slicer instance may still be using. They can be removed from the
  extension cache when every Slicer instance and worker is closed.
- Exported tables use the extension's own richer long-form schema (provenance columns
  plus a `configuration` column) and a wide pivot, which do **not** match Pictologics'
  own `format_results` / `save_results` layout (which uses a `config` column and no
  provenance). This is intentional so tables carry full provenance; it may be
  reconciled if Pictologics adopts a canonical result schema.
- The extension has not been exercised inside a Slicer executable in this development
  environment. `scripts/geometry_parity_check.py` now confirms the worker reproduces
  direct Pictologics values on an oblique, anisotropic NIfTI grid (the
  wrapper-vs-library half of numerical parity), but normal-Python unit and syntax
  checks are still not a substitute for the required Slicer 5.12 Stable/Preview
  geometry, package-install, and staging-round-trip (`saveNode`/labelmap export)
  parity tests.

Planning notes (the implementation decision, build plan, and original implementation
plan) are kept in the local, git-ignored `dev/` folder rather than tracked in the
repository.

## Testing

Quality tooling is configured in the tracked `pyproject.toml` and shared between the
local gate and CI:

- **ruff** — linting (E, F, W, I, B).
- **mypy** — strict type checking of the Slicer-neutral library and CLI worker (the GUI
  imports the Slicer runtime and is out of scope; it is checked only inside Slicer).
- **pytest + coverage** — enforced at **100% statement coverage** (`fail_under = 100`)
  over `PictologicsSlicer/PictologicsLib` and `PictologicsCLI`. The GUI is exercised by
  the in-Slicer `ScriptedLoadableModuleTest`.

Run everything locally with a Python that has `ruff`, `mypy`, `pytest`, `pytest-cov`,
and `coverage`:

```sh
python dev/pre_push.py                # ruff, mypy, syntax, tests + coverage
python -m pytest --cov --cov-report=term-missing   # just the tests
```

The git-ignored `dev/` and `.vscode/` workspace holds this pre-push gate and matching
VS Code tasks (see `dev/README.md`). `.github/workflows/ci.yml` runs the same
ruff / mypy / coverage gate on every push and pull request, uploads the coverage report
to [Codecov](https://codecov.io/gh/martonkolossvary/SlicerPictologics) (`codecov.yml`;
optional `CODECOV_TOKEN` repo secret, with a tokenless fallback for public repositories),
then runs the real API / worker-smoke / geometry-parity checks against the adopted
Pictologics wheel. As noted above, Slicer Stable/Preview load, geometry, and
staging-round-trip parity remain a manual release gate.

## License

SlicerPictologics is licensed under the Apache License 2.0. See [LICENSE](LICENSE) and
[NOTICE](NOTICE).

## References

- [3D Slicer extension user guide](https://slicer.readthedocs.io/en/latest/user_guide/extensions.html)
- [3D Slicer extension developer guide](https://slicer.readthedocs.io/en/latest/developer_guide/extensions.html)
- [Slicer ExtensionsIndex](https://github.com/Slicer/ExtensionsIndex)
- [SlicerRadiomics reference extension](https://github.com/AIM-Harvard/SlicerRadiomics)
