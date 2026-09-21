# Pictologics for 3D Slicer

[![CI](https://github.com/martonkolossvary/SlicerPictologics/actions/workflows/ci.yml/badge.svg)](https://github.com/martonkolossvary/SlicerPictologics/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/martonkolossvary/SlicerPictologics/graph/badge.svg)](https://codecov.io/gh/martonkolossvary/SlicerPictologics)

Pictologics is a 3D Slicer extension for running
[Pictologics](https://github.com/martonkolossvary/pictologics) radiomic feature
extraction on scalar volumes, selected segmentation regions, and whole-volume
regions. The displayed module is **Pictologics** in Slicer's **Informatics**
category.

The catalog identifier is **Pictologics**; the source repository remains
`SlicerPictologics`, and the internal modules remain `PictologicsSlicer` and
`PictologicsCLI`. Existing module paths and private dependency environments do not
need to be renamed. The approved [catalog and module artwork](docs/icon-design.md)
is included; [reusable raster and vector exports](assets/branding/pictologics/README.md)
are retained separately from the installed module resources.

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

The baseline is **3D Slicer 5.12+**. The adopted requirement is recorded in
[`requirements-pictologics.txt`](PictologicsSlicer/requirements-pictologics.txt).
**Pictologics 0.5.1** is the baseline for automatic adoption. Normal install/update
retrieves the adopted binary wheel from [PyPI](https://pypi.org/project/pictologics/);
the sibling-source override is only for unpublished development changes.

The exact pin records the newest release accepted by the compatibility process.
The actual imported version is recorded in result provenance. The extension never
imports or upgrades Pictologics during Slicer startup.

Every push, pull request, and candidate release uses the same reusable
[`compatibility.yml`](.github/workflows/compatibility.yml) gates:

- syntax, Ruff, strict library/worker typing, and unit tests with 100% scoped coverage;
- released-wheel API, full-JIT extraction, and oblique/anisotropic geometry parity on
  Linux, Windows, and Intel macOS with Python 3.12;
- real Slicer 5.12.4 on Linux: GUI/CLI discovery, approved-icon identity, transformed MRML/NIfTI staging,
  asynchronous CLI execution, result validation, and table commit; and
- catalog JSON syntax (not ExtensionsIndex acceptance).

The [adoption workflow](.github/workflows/adopt-pictologics-release.yml) checks PyPI
every six hours. It can also be run manually (empty version means latest) or receive
an optional `pictologics-release` repository dispatch. Scheduled discovery needs no
cross-repository secret or upstream sender. Prereleases, entirely yanked releases,
sdist-only candidates, invalid version strings, and downgrades are never adopted.
All gates run against one exact wrapper revision. A separate write-enabled job
rechecks publication status and automatically publishes only the requirement change
to the default branch. Failed checks leave the last qualified pin unchanged.
It never force-pushes: a concurrent wrapper change requires fresh qualification.
The bot commit does not trigger another CI run; it already passed the shared gates.
Repository rules must permit the workflow's `GITHUB_TOKEN` to push that pin change.

Exact pinning is safe because dependencies live in a private target used only by the
worker; they cannot constrain or downgrade packages shared by Slicer or other
extensions. “Latest” means **latest compatibility-qualified stable release**, not an
untested upgrade loop at startup. An existing installation still needs an extension
update (or `git pull` for a source checkout), followed by
**Install / update adopted release…** when the pin changes. This automation does not
replace Slicer's extension distribution service: Extensions Manager delivery requires
the separate catalog submission described below.

### Why dependencies are private

See the [release-readiness review](docs/release-readiness.md) for validation evidence
and the remaining catalog-distribution and application-acceptance work.

Pictologics is installed under extension-owned, per-user application data and made
visible only to the background job. It is deliberately kept outside Slicer's managed
I/O cache, which is size-limited and may be pruned. Each accepted environment has an
immutable versioned directory; an atomic pointer selects it for new jobs, while
already-running jobs keep their original path. It is not installed into or allowed to
replace Slicer's shared Python packages. This is required for Slicer 5.12: its
environment includes NumPy
2.4.6 while Pictologics' Numba 0.62.1 requires NumPy `<2.4`, and it includes Pillow 12
while the current Pictologics constraint is Pillow `<12`.

The background process sets `PICTOLOGICS_DISABLE_WARMUP=1` before importing
Pictologics, removes that setting after import, and then calls `warmup_jit()` once.
This keeps module discovery fast while still compiling kernels before extraction.

## Install

### Extensions Manager

[`Pictologics.json`](Pictologics.json) is a Tier-1 ExtensionsIndex draft. Until it has been submitted,
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
   **Export wide layout** for one row per ROI with Pictologics' exact
   `configuration__feature_key` columns instead of the default long layout. JSON
   includes the complete per-run provenance
   history and feature data dictionary; CSV writes companion `.provenance.json` and
   `.dictionary.csv` files (the latter is the Slicer-side equivalent of Pictologics'
   `describe_features()`).

The long table keeps the official `ibsi_code` and also reports the exact native
`feature_key`, Pictologics' disambiguated `pictologics_ibsi_code`, the package-wide
`pictologics_feature_name`, and `preprocessing_sequence`. For example, the official
IBSI code `BC2M` is paired with `BC2M_10` or `BC2M_90`, and a package-wide name such as
`standard_fbn_32__volume_at_intensity_fraction_0.10_BC2M_10`. The longer identifier is
Pictologics-specific, not a second official IBSI code. Complete preprocessing
parameters remain in the feature data dictionary. These columns are part of the
extension's initial `0.1.0` result contract.

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
- Cancellation is at the CLI-process/job boundary. The current Pictologics 0.5.1 API
  has no cooperative progress/cancellation callback, so a running native kernel cannot
  report fine-grained progress. Multi-ROI jobs report completed-ROI percentages;
  single-ROI jobs display an indeterminate busy indicator until the package returns.
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
  extension's application-data directory when every Slicer instance and worker is
  closed.
- Exported tables use the extension's own richer long-form schema (provenance and
  feature-identity columns plus `configuration`) and therefore do **not** match
  Pictologics' long `format_results` / `save_results` layout (which uses `config` and
  omits provenance). Wide feature names do match Pictologics exactly. This is
  intentional so tables carry full provenance; it may be reconciled if Pictologics
  adopts a canonical result schema.
- Pictologics 0.5.1 has passed private PyPI installation, API and full-JIT probes,
  and the integration suite in the reinstalled Slicer 5.12.4 (CPython 3.12,
  x86_64 under Rosetta on macOS). CI additionally requires real Slicer on Linux and
  released-wheel checks on all three desktop platforms. Interactive acceptance,
  Slicer Preview, real Windows Slicer, and Extension Factory packaging remain
  catalog-release gates; normal-Python checks do not establish those results.

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

The in-Slicer integration test always runs its deterministic fixture and MRML-staging
methods under CTest. Its real CLI/JIT method is skipped by default, so Extension Factory
testing needs neither network access nor a pre-populated Pictologics cache. The test
never installs or downloads dependencies. Run that release gate against an existing
qualified private target with:

```sh
SLICERPICTOLOGICS_RUN_REAL_CLI_TEST=1 \
SLICERPICTOLOGICS_TEST_DEPENDENCY_PATH=/absolute/path/to/private-target \
ctest --test-dir ../SlicerPictologics-build -C Release \
  -R '^py_PictologicsSlicerIntegrationTest$' --output-on-failure
```

Omit `SLICERPICTOLOGICS_TEST_DEPENDENCY_PATH` to use the extension's active private
target. Once the gate is enabled, a missing, ambiguous, or wrong-version target fails
instead of skipping; only the exact adopted requirement is accepted. Job staging and
Numba cache writes stay inside a disposable test cache.

The git-ignored `dev/` and `.vscode/` workspace holds this pre-push gate and matching
VS Code tasks (see `dev/README.md`). `.github/workflows/ci.yml` runs the same
ruff / mypy / coverage gate on every push and pull request, uploads the coverage report
to [Codecov](https://codecov.io/gh/martonkolossvary/SlicerPictologics) (`codecov.yml`;
optional `CODECOV_TOKEN` repo secret, with a tokenless fallback for public repositories),
then runs the real API / worker-smoke / geometry-parity checks against the adopted
Pictologics wheel. The real in-Slicer CLI method stays opt-in under CTest and is explicitly enabled
in the shared Linux CI/adoption gate. Slicer Preview, real Windows Slicer, and
interactive-workflow qualification remain manual.

## License

SlicerPictologics is licensed under the Apache License 2.0. See [LICENSE](LICENSE) and
[NOTICE](NOTICE).

## References

- [3D Slicer extension user guide](https://slicer.readthedocs.io/en/latest/user_guide/extensions.html)
- [3D Slicer extension developer guide](https://slicer.readthedocs.io/en/latest/developer_guide/extensions.html)
- [Slicer ExtensionsIndex](https://github.com/Slicer/ExtensionsIndex)
- [SlicerRadiomics reference extension](https://github.com/AIM-Harvard/SlicerRadiomics)
