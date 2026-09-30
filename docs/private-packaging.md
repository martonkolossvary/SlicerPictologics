# Reusable private packaging environment

**Inactive / optional reference, not the release path.** On 2026-09-30 the maintainer
stopped local Xcode/Qt/Slicer build work. Do not provision those tools to complete
the current milestone. Use installed Slicer for functional/regression testing;
after separately authorized catalog submission, Slicer's Extension Factory will
produce the distribution packages. See the [submission handoff](extensions-index-submission.md).
The historical setup below is retained for a future explicit SDK-build request.

This workflow builds **only the extension** after a one-time Slicer SDK build.
It never submits a dashboard, uploads a package, changes Git, registers the
extension, or installs it into a user's Slicer. A passing archive audit is **not**
packaged-install acceptance. Runner outputs remain local; the runner itself never
publishes source or artifacts.

## Pins and reuse

[`packaging/slicer-5.12.4.json`](../packaging/slicer-5.12.4.json) records:

- Slicer **5.12.4**, full source commit
  `4e21c19d8360242d88d6ca2490bf52400441b8e1`, application revision `4e21c19`;
- CMake / CTest / CPack **3.31.10**;
- Slicer Python **3.12.10**, Qt **5.15.18**, Intel/x86_64;
- Release, Unix Makefiles, macOS or Linux. Windows/native ARM packaging is not
  implemented by this runner.

The Python/Qt/revision pins match the installed macOS Slicer, queried in a separate,
settings-disabled process on 2026-09-30. Qt **5.15.2**, mentioned in the upstream
generic build instructions, is not the Qt version of this installed app. The Linux
profile is a build target, not a claim of a completed Linux SDK or package test.

On its first build the runner also seals the local SDK metadata, launcher/Python/
compiler hashes, compiler/make versions, SDK paths, macOS deployment target/sysroot,
and host identity into `environment.json`. Later runs refuse environment drift;
they do not silently update that file. This is a version-pinned, drift-checked local
environment, **not a claim of bit-for-bit reproducible Slicer builds**. The OS SDK,
compiler, Qt provisioning, and upstream SuperBuild downloads remain external
prerequisites; their full supply chain is not vendored by this repository.

| What changes | Required work |
| --- | --- |
| Plugin source or adopted Pictologics pin | Reuse the SDK/tools; rerun the packaging command |
| Slicer version, Qt/Python baseline, CPU target | Review a new lock and provision a separate matching SDK |
| Compiler, OS SDK, build configuration, or sealed SDK files | Investigate drift and use a new empty packaging root |

## One-time tools setup

From this repository, use a normal Python 3.12+ interpreter, **not Slicer's Python**:

```sh
python3 -m venv dev/packaging-tools
dev/packaging-tools/bin/python -m pip install \
  --require-hashes --only-binary=:all: --no-deps \
  -r packaging/requirements-tools.txt
dev/packaging-tools/bin/cmake --version
dev/packaging-tools/bin/ctest --version
dev/packaging-tools/bin/cpack --version
dev/packaging-tools/bin/python scripts/package_extension.py tools
```

The requirements allow only the checksum-verified macOS universal2 and Linux
x86_64 wheels for the exact version. The ignored `dev/` environment is reusable;
do not recreate it for routine releases. It contains packaging tools, not Qt or
Slicer. No global packages or Slicer packages are changed.

The normal GitHub compatibility workflow **does not install or require these
packaging tools**. Portable tests still exercise the optional runner's safety and
failure contracts without a real SDK. No SDK provisioning job or package acceptance
job is part of that workflow.

## One-time Slicer SDK setup

The downloaded `Slicer.app` is an application, **not a development SDK**. This
CMake/CPack route needs a completed SuperBuild and its inner `Slicer-build` folder.
Python-only source development does not need this step.

Use the [version-matched Slicer build instructions](https://github.com/Slicer/Slicer/tree/v5.12.4/Docs/developer_guide/build_instructions).
On macOS, provision a compatible compiler/SDK and **Qt 5.15.18 x86_64 including
WebEngine** before configuring. Do not substitute Homebrew's ARM Qt or a floating
Qt release. Qt provisioning/licensing is handled through the selected Qt source
or distribution; this runner does not install Qt or accept license terms.
Use short local paths outside OneDrive/iCloud, and retain the complete build tree
in place; it is not relocatable. Expect substantial build time and disk use.

### Historical Mac prerequisite investigation (not an active blocker)

The follow-up host check on 2026-09-30 found **48 GiB RAM, 14 logical CPUs and
approximately 465 GiB free disk space**. Rosetta can run x86_64 commands. However,
only Command Line Tools are installed: `xcodebuild -version` fails because the
selected developer directory is `/Library/Developer/CommandLineTools` rather than
a full Xcode installation. SDKs 26.5 and 27.0 are present; no Qt development files,
Ninja executable, or completed Slicer SDK were found. The detected Node executable
belongs to ARM Homebrew; it has not been qualified for the Intel Qt build recipe.

If this optional route is explicitly resumed, install full Xcode and open it once
to complete its first-launch setup and license prompts. Then verify
`xcodebuild -version` and `xcodebuild -showsdks`. If Command
Line Tools remain selected, the build can use a per-process `DEVELOPER_DIR` pointing
to the chosen Xcode; changing the machine-wide selection is not required. Do not
assume that the newest Xcode/SDK is already qualified for Qt 5.15.18: inspect the
available version and validate it before the long Qt/Slicer build. This is a
prerequisite for the selected Qt-source route, not for using the existing extension.

The upstream [Qt 5 build guide](https://wiki.qt.io/Building_Qt_5_from_Git#macOS)
requires a working Xcode setup. A matching Intel-on-Apple-Silicon recipe exists at
[`commontk/qt-easy-build` commit `64c9a5c`](https://github.com/commontk/qt-easy-build/tree/64c9a5ccbdf071f282bddd4acb532f57ed7c0b28).
Use that exact revision when preparing the Qt build, not the moving `5.15.18`
branch. It contains Qt 5.15.18 patches and uses QtWebEngine 5.15.19 internally.
It also builds private legacy Python 2.7/OpenSSL dependencies and contains a
floating zlib clone; those dependencies need explicit pinning/isolation before
calling this a reproducible Qt provisioning step. The upstream script was
reviewed, **not executed**. No Qt/Xcode license was accepted, global package manager
installed, SDK downloaded, or existing Slicer installation changed.

Example macOS setup, once those prerequisites are available (replace all paths):

```sh
# Full history, not --depth: preserve upstream build provenance.
git clone --branch v5.12.4 https://github.com/Slicer/Slicer.git /short/Slicer
git -C /short/Slicer rev-parse HEAD
# Must print 4e21c19d8360242d88d6ca2490bf52400441b8e1.

/absolute/SlicerPictologics/dev/packaging-tools/bin/cmake \
  -S /short/Slicer -B /short/Slicer-5.12.4-release -G "Unix Makefiles" \
  -DCMAKE_BUILD_TYPE:STRING=Release \
  -DSlicer_RELEASE_TYPE:STRING=Stable \
  -DSlicer_REVISION_TYPE:STRING=Hash \
  -DSlicer_USE_SYSTEM_QT:BOOL=ON \
  -DQt5_DIR:PATH=/absolute/Qt-5.15.18/lib/cmake/Qt5 \
  -DCMAKE_OSX_ARCHITECTURES:STRING=x86_64 \
  -DCMAKE_OSX_DEPLOYMENT_TARGET:STRING=14.0 \
  -DCMAKE_OSX_SYSROOT:PATH=/absolute/compatible/MacOSX.sdk
/absolute/SlicerPictologics/dev/packaging-tools/bin/cmake \
  --build /short/Slicer-5.12.4-release --parallel 4
```

Do not set `Slicer_FORCED_REVISION` or the `Slicer_REVISION` environment variable to
make an unrelated build look compatible. The runner checks both the full source
commit and abbreviated application revision. On Linux follow the matching Linux
prerequisites and omit the macOS-only flags. A Linux container produces Linux
acceptance, not macOS acceptance. This repository does not currently provision a
Docker image or claim compatibility with the current Mac's SDK for a full source
build; those prerequisites need actual build validation.

## Every packaging attempt

First inspect the build metadata without configuring or writing anything:

```sh
dev/packaging-tools/bin/python scripts/package_extension.py check \
  --slicer-dir /short/Slicer-5.12.4-release/Slicer-build
```

Then run the full private pipeline, choosing an empty, short, non-cloud root
outside both this repository and the SDK:

```sh
dev/packaging-tools/bin/python scripts/package_extension.py build \
  --slicer-dir /short/Slicer-5.12.4-release/Slicer-build \
  --work-root /short/pictologics-packages-5.12.4 \
  --jobs 4
```

Reuse the **same command and root** for later plugin/Pictologics releases. SDK
rebuilding is not part of this command. On a headless Linux host run it under
`xvfb-run -a`; the Slicer tests need a usable display even without a main window.

The runner:

1. Checks exact tools, SDK source/configuration, architecture and macOS settings;
   launches an isolated, settings-disabled SDK Slicer to verify runtime identity.
2. Creates a unique attempt directory; records source file hashes, Git HEAD/status
   (including pending local changes), and the sealed SDK identity.
3. Configures with testing enabled and uploads disabled, then builds the extension.
4. Requires the registered Slicer integration test, installs the adopted wheel and
   constraints into a **new private target using the SDK Python**, and runs CTest
   serially with the real-CLI gates enabled. Zero registered tests is an error.
5. Runs ordinary CPack, audits every produced ZIP/TGZ against the source, and
   rejects source or SDK changes during the attempt.

Each `run-*` folder retains command logs, a source manifest, CTest XML, private
test dependencies, an `artifacts/` folder, and `report.json`. A failed step stops
the pipeline; stale archives from previous attempts cannot make it pass. Dependencies
are fresh per attempt, while the expensive SDK and tooling are reused. Reports/logs
contain local paths; review them before sharing. There is no automatic cleanup of
these retained environments or files.

## Acceptance if this optional route is resumed

A successful report covers build-tree tests and archive contents. Before accepting
a package produced by this route, install the actual archive into a clean Slicer
profile **without source module paths**, restart, and repeat two-ROI extraction, export, lossless
scene reload, and private dependency reuse. Test the matching platform and version;
do not infer macOS/Windows/Preview success from Linux or portable tests.

On 2026-09-30 the tool environment and automation regression tests are validated
locally. No matching Slicer build tree or Qt development installation was found;
the actual SDK build and CPack output were not attempted. They are not pending
milestone tasks under the decision above. Clean packaged-install acceptance will
instead follow a future authorized Extension Factory build.
After the approval service recovered, all **15 packaging-runner regression tests
also passed under Slicer's own Python**. These tests still use synthetic metadata
and mocked build commands; they do not constitute an actual package build.
