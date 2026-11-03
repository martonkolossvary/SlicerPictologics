# Release readiness

This page gives the state of the first catalog release: extension 0.1.0 with
Pictologics 1.0.1. The job manifest schema is 1 and the result payload schema is 2.
Each check below names the Pictologics version and the date of that check. Later
Pictologics releases reach users after the adoption workflow qualifies them; the
extension reads the version from `requirements-pictologics.txt`.

## Checks with Pictologics 1.0.1 (2026-11-02 and 2026-11-03)

- The adoption workflow qualified 1.0.1 and pinned it on `main` (commit `015d8fe`).
  It resolved the dependencies and checked the released wheels on Linux x86_64,
  Windows x64, macOS x86_64 and macOS arm64. It ran all integration tests in a real
  Slicer 5.12.4 on Linux, and the unit tests with 100% scoped coverage. This was the
  first full run of the release chain in this repository.
- Two dependency jobs failed at first: 40 seconds after the release, their PyPI
  mirror did not list 1.0.1 yet. A rerun passed, and these jobs now try again for
  4 minutes.
- Stable Slicer 5.12.4 on macOS (Intel build under Rosetta) passed the install
  lifecycle (install, restart, update, restart after update) and all 70 integration
  tests with the real worker, 0 skipped. Each environment had its own Numba folder,
  and the cleanup deleted the old environment together with its Numba folder.
- Windows 11 x64 with Slicer 5.12.4 (2026-11-03), in Windows PowerShell 5.1 with the repository
  launcher (revision `aa90788`):

  | Check | Result |
  |---|---|
  | Unit-test files that CTest registers, with the Python of Slicer 5.12.4 | 31 of 31 files pass; 5 link tests skipped (they need a Windows privilege) |
  | Application check | 4 of 4 lifecycle phases pass, with 340 identical rows after each restart; 70 integration tests pass, 0 skipped |
  | Numba folder of each environment | One folder for each environment, no flat folders; the cleanup deleted the old environment and its folder |
  | Profile folder name of 40 characters (emulated) | 4 of 4 phases pass; the longest path is 286 characters; the cleanup and the deletion leave nothing |
  | Export over a CSV that Excel 16 has open | The "Could not replace … may have it open" message shows; nothing stays behind; the CSV does not change |
  | Window checklist (scripted) | Pass; after scene reload, 340 of 340 values are identical, and the rerun does not ask to install |

  Not covered on Windows: the 2D and 3D views, because the remote session
  disconnected before the window checklist. Check them when you install the
  Extension Factory package (open gate 2).

## Checks with Pictologics 1.0.0 (2026-11-01)

- Every push runs GitHub CI. It resolves the dependencies and checks the released
  wheels on Linux x86_64, Windows x64, macOS x86_64 and macOS arm64. It runs every
  in-app step and filter with the released wheel, all integration tests in a real
  Slicer 5.12.4 on Linux, and the lint, type and unit tests with 100% scoped coverage.
- Stable Slicer 5.12.4 on macOS (Intel build under Rosetta) passed all 70 integration
  tests, with the real worker, from a source checkout with the exact pins.
- The unit-test files that CTest registers pass with the Python of Slicer 5.12.4,
  as on the Extension Factory. That Python has no pytest.
- The catalog screenshots come from a real run with Pictologics 1.0.0.

## Checks on Windows x64 (2026-11-02)

The [Windows application check](development.md#windows-application-check) ran on
Windows 11 x64 with Pictologics 1.0.0. The computer had a Hungarian user interface,
a user without administrator rights, and the Windows long-path setting off.

| Check | Slicer 5.12.4 | Slicer Preview 5.13.0-2026-09-30 |
|---|---|---|
| Install lifecycle: install, restart, update, restart after update | 4 of 4 pass | 4 of 4 pass |
| Integration tests with the real worker | 70 pass, 0 skipped | 70 pass, 0 skipped |
| Unit-test files that CTest registers, with Slicer's Python | 30 of 31 files pass | not run |
| Window checklist | pass | not run |

The check found these problems. The Windows fixes of 2026-11-02 correct them:

- The deletion of private packages failed when a file path was longer than the
  Windows limit (`MAX_PATH`, 260 characters). This occurs below a profile folder
  name of 29 characters or more.
- An export over a read-only file left a hidden staging folder or temporary file,
  and the error message named the wrong file.
- An export over a file that another program (for example Excel) has open showed a
  raw Windows error that named a hidden temporary file.
- One unit test expected POSIX file modes. Windows keeps only the read-only flag.

The same computer ran the checks again with the fixes (revision `1ab4f82`):

| Check | Result |
|---|---|
| Lint, types and unit tests with normal Python | 639 pass, 100% coverage; 3 link tests skipped (they need a Windows privilege) |
| Unit-test files that CTest registers, with the Python of Slicer 5.12.4 | 31 of 31 files pass |
| Application check on Slicer 5.12.4 and on Preview 5.13.0-2026-09-30 | 4 of 4 lifecycle phases and 70 integration tests pass, 0 skipped |
| Profile folder name of 40 characters (emulated) | Install, restart and update pass. The old-version cleanup and **Remove private packages…** delete everything. |
| Export over a read-only CSV, and over a CSV that another program holds open | The real error shows, nothing stays behind, and the CSV does not change |
| Window checklist (scripted) on Slicer 5.12.4 | Pass; after scene reload, 340 of 340 values are identical |

With the fixes, Slicer 5.12.4 on macOS also passed all 70 integration tests with the
real worker, and every unit-test file with Slicer's Python.

## Earlier checks

- Windows x64: Stable 5.12.4 and Preview passed the integration tests, the install
  lifecycle, Unicode paths and the workloads with Pictologics 0.5.1 in October 2026.
- Workloads and memory use: see [performance](performance.md).

## Open gates

1. Get the catalog pull request
   [Slicer/ExtensionsIndex#2434](https://github.com/Slicer/ExtensionsIndex/pull/2434)
   merged. It was opened on 2026-11-03, and the official validator passed on a local
   run. A Preview newer than 2026-09-30 is not necessary (maintainer decision of
   2026-11-02).
2. Check each Extension Factory package with `scripts/check_extension_package.py`.
   Then install it in a clean Slicer on each platform, and check restart,
   extraction, export, scene reload and the 2D and 3D views.
3. Make sure that Extensions Manager shows and installs the extension before you
   announce it.
