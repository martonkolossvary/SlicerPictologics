# Developer guide

This page is for people who change, test, or package the extension. The
[README](../README.md) describes how to use it.

## Names

The catalog identifier is **Pictologics**; the source repository remains
`SlicerPictologics`, and the internal modules remain `PictologicsSlicer` and
`PictologicsCLI`. Existing module paths and private dependency environments do not
need to be renamed. The approved [catalog and module artwork](icon-design.md)
is included; [reusable raster and vector exports](../assets/branding/pictologics/README.md)
are retained separately from the installed module resources.

## Compatibility and package policy

The baseline is **3D Slicer 5.12+**. The adopted requirement is recorded in
[`requirements-pictologics.txt`](../PictologicsSlicer/requirements-pictologics.txt).
**Pictologics 0.5.1** is the baseline for automatic adoption. Normal install/update
retrieves the adopted binary wheel from [PyPI](https://pypi.org/project/pictologics/);
the sibling-source override is only for unpublished development changes.

The exact pin records the newest release accepted by the compatibility process.
The actual imported version is recorded in result provenance. The extension never
imports or upgrades Pictologics during Slicer startup.

Every push, pull request, and candidate release uses the same reusable
[`compatibility.yml`](../.github/workflows/compatibility.yml) gates:

- syntax, Ruff, strict library/worker typing, and unit tests with 100% scoped coverage;
- released-wheel API, full-JIT extraction, and oblique/anisotropic geometry parity on
  Linux, Windows, and Intel macOS with Python 3.12;
- real Slicer 5.12.4 on Linux: GUI/CLI discovery, approved-icon identity, transformed MRML/NIfTI staging,
  asynchronous CLI execution, result validation, and table commit; and
- catalog JSON syntax (not ExtensionsIndex acceptance).

The [adoption workflow](../.github/workflows/adopt-pictologics-release.yml) checks PyPI
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
the separate catalog submission described in
[`extensions-index-submission.md`](extensions-index-submission.md).

The release gate also compares the in-app lint's copy of the Pictologics step and
parameter names with `RadiomicsPipeline._VALID_STEPS`. A difference stops adoption
until the copy is updated.

### Why dependencies are private

See the [release-readiness review](release-readiness.md) for validation evidence
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

New environments are named `<version>-<8 hex>` so that the deepest package files stay
within the Windows 260-character path limit. After a new environment becomes active,
the older ones are deleted; while any job runs, the deletion waits for the next module
start or installation.

The background process sets `PICTOLOGICS_DISABLE_WARMUP=1` before importing
Pictologics, removes that setting after import, and then calls `warmup_jit()` once.
This keeps module discovery fast while still compiling kernels before extraction.

## Temporary files

The extension serializes temporary inputs as NIfTI (`.nii.gz`) because Pictologics
loads NIfTI directly. Temporary files and MRML nodes are removed after success,
failure, cancellation, or module teardown as soon as the worker exits. GUI and worker
PID markers protect staging used by another live Slicer instance. After a process
crash, dead-owner staging is purged once it is an hour old on module entry or before a
new job; a malformed marker is retained conservatively for at most seven days.

## In-app builder and upstream APIs

The full schema-driven, multi-step/multi-configuration builder is still deferred:
the current Pictologics source has presets and configuration serialization, but not
a complete public editor schema or structured-validation result API. Processing logs
do have a public JSON export (`save_log()`); what is missing is a public in-memory log
getter. The extension currently copies the private `_log` as a compatibility fallback
and retains it in provenance. Individually implemented advanced controls do not
require a complete upstream editor schema.

## Load a development checkout

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

## Configure and package the extension

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

## Testing

Quality tooling is configured in the tracked `pyproject.toml` and shared between the
local gate and CI:

- **ruff** — linting (E, F, W, I, B).
- **mypy** — strict type checking of the Slicer-neutral library and CLI worker (the GUI
  imports the Slicer runtime and is out of scope; it is checked only inside Slicer).
- **pytest + coverage** — enforced at **100% statement coverage** (`fail_under = 100`)
  over `PictologicsSlicer/PictologicsLib` and `PictologicsCLI`. The GUI is exercised by
  the in-Slicer `ScriptedLoadableModuleTest`.

The support tests use only `unittest`, because CTest also runs them in Slicer's
Python, which does not include pytest.

From the repository root, use Python 3.12+ in a development environment (not Slicer's
shared Python). These commands use only tracked repository files and match the
portable quality checks in CI:

```sh
python -m pip install pytest pytest-cov coverage packaging ruff mypy pyyaml
python -m compileall -q PictologicsSlicer PictologicsCLI scripts
python -m ruff check PictologicsSlicer PictologicsCLI/PictologicsCLI.py scripts conftest.py tests
python -m mypy
python -m pytest --cov --cov-report=term-missing
python -m json.tool Pictologics.json
```

These checks do not launch Slicer, install Pictologics, or establish packaged-install
acceptance. CI separately validates workflow syntax, released wheels, and real Slicer.

The in-Slicer integration test always runs its deterministic fixture, MRML-staging,
and GUI feedback methods under CTest. Its real CLI/JIT and end-to-end GUI extraction
methods are skipped by default, so Extension Factory testing needs neither network
access nor a pre-populated Pictologics cache. The test
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

## Validation status

Pictologics 0.5.1 has passed private PyPI installation, API and full-JIT probes,
and the integration suite in the reinstalled Slicer 5.12.4 (CPython 3.12,
x86_64 under Rosetta on macOS). CI additionally requires real Slicer on Linux and
released-wheel checks on all three desktop platforms. Interactive acceptance,
Slicer Preview, real Windows Slicer, and Extension Factory packaging remain
catalog-release gates; normal-Python checks do not establish those results.
