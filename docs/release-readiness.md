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

## Earlier checks

- Windows x64: Stable 5.12.4 and Preview passed the integration tests, the install
  lifecycle, Unicode paths and the workloads with Pictologics 0.5.1 in October 2026.
- Workloads and memory use: see [performance](performance.md).

## Open gates

1. Test the Windows Slicer application and Slicer Preview with Pictologics 1.0.0.
2. Open the catalog pull request. The text is in the
   [pull request draft](extensions-index-pr-draft.md).
3. Check each Extension Factory package with `scripts/check_extension_package.py`.
   Then install it in a clean Slicer on each platform, and check restart,
   extraction, export and scene reload.
4. Make sure that Extensions Manager shows and installs the extension before you
   announce it.
