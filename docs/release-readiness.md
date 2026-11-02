# Release readiness

This page gives the state of the first catalog release: extension 0.1.0 with
Pictologics 1.0.0. The job manifest schema is 1 and the result payload schema is 2.

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

With the fixes, Slicer 5.12.4 on macOS passed all 70 integration tests with the real
worker, and every unit-test file passed with Slicer's Python (2026-11-02). The
Windows rerun is open gate 1.

## Earlier checks

- Windows x64: Stable 5.12.4 and Preview passed the integration tests, the install
  lifecycle, Unicode paths and the workloads with Pictologics 0.5.1 in October 2026.
- Workloads and memory use: see [performance](performance.md).

## Open gates

1. Do the Windows checks again with the Windows fixes: the unit-test files with
   Slicer's Python, the application check on Stable 5.12.4 and a current Preview,
   a profile folder name of 40 characters, and an export over a read-only file and
   over a file that is open in Excel. The first check passed on 2026-11-02 (above).
2. Open the catalog pull request. The text is in the
   [pull request draft](extensions-index-pr-draft.md).
3. Check each Extension Factory package with `scripts/check_extension_package.py`.
   Then install it in a clean Slicer on each platform, and check restart,
   extraction, export and scene reload.
4. Make sure that Extensions Manager shows and installs the extension before you
   announce it.
