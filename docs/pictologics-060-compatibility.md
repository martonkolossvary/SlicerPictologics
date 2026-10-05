# Pictologics 0.6 compatibility update

Follow-up (2026-10-05): the properly packaged 0.6.1 macOS compatibility candidate
now installs and passes focused local Slicer-Python checks. The adopted release is
still 0.5.1 pending full qualification and upstream publication. See
[implementation handoff](macos-compatibility-handoff.md) for the current state;
the original 0.6.0 blocker and evidence below remain historically accurate.

Review date: 2026-10-04. Windows acceptance PR #6 was merged as
`b3376c725f98cf67c7efbce7be22b54eaba63505`. Its application evidence remains
qualification of **0.5.1**, not of a different package version.
The post-merge [GitHub CI run 37203932959](https://github.com/martonkolossvary/SlicerPictologics/actions/runs/37203932959)
passed. That run covers the Windows merge, not the later uncommitted compatibility changes.

## Adoption remains blocked

The committed requirement and constraints remain at **Pictologics 0.5.1**.
The released 0.6.0 wheel requires `numba>=0.67.0,<0.68.0`. At this review,
[Numba 0.67.0 on PyPI](https://pypi.org/pypi/numba/0.67.0/json) publishes Python 3.12
wheels for macOS ARM64, Linux x86_64/aarch64 and Windows AMD64, but not macOS Intel.
The installed official Slicer 5.12.4 uses Python 3.12.10 **x86_64** under Rosetta.
Its isolated `pip install --only-binary=:all: pictologics==0.6.0` therefore fails
to resolve Numba. A successful native ARM developer test does not qualify this Slicer.

Do not loosen the package requirement, reuse an incompatible Numba, remove the
Intel qualification job, install into Slicer's shared Python, or build from source
to conceal this failure. An upstream Pictologics dependency policy/release that
supports the required wheels (with its own tests), or a separately qualified native
ARM Slicer distribution, is needed. Those changes are outside this wrapper update.

## Focused wrapper changes

- The structural API contract recognizes 0.6 steps/options while retaining an exact
  0.5.1 comparison during the transition. Filter `padding_value` and Gabor `response`
  need additional treatment: 0.6 validates filter function signatures, so its
  `_VALID_STEPS` list alone is incomplete.
- In-app FBS requires an explicit finite minimum, serialized as `min_val`. Profiles
  and scene settings preserve its entered value. Missing legacy minima stay unset;
  active FBS settings block Run until reviewed. Legacy FBN profiles remain usable.
  The GUI deliberately does not infer a lower bound, including from resegmentation.
- Editable standard templates follow the adopted version. 0.6 FBS CT templates use
  -1000 HU; 0.5.1 templates retain the old behavior during this hold. FBS preset
  tooltips disclose the semantic change. No universal MRI/filter minimum is assumed.
- File-based 0.6 FBS can inherit an earlier intensity/both-mask resegmentation lower
  bound; morphology-only bounds do not qualify. Filters and normalization clear the
  inherited start. FBS IVH discretization follows the same package rule. Worker
  validation warnings are errors, and API round-trip checks now enforce that too.
- Cropping falls back to the full image for `normalise`, `grow_mask` and unknown
  operations. This avoids biased normalization statistics and truncated grown masks.
  Before the fix, a synthetic mean changed from -0.8040 to approximately 0 after
  cropping with whole-image normalization; growth changed 73.4064 to 66.0.
- `nearest_roi=true` is rejected during structural and worker validation, including
  the check-file API. Independent ROI execution cannot implement shared growth rings.
- Existing column names, schema versions, results persistence and the public
  `get_log()` fallback already accommodate the relevant new result/log contracts.
  Deduplication stays disabled; replacing batch/ROI execution is not part of this work.

## Qualification gates

`scripts/check_release_compatibility.py` runs in every released-wheel job of the
shared compatibility workflow, including automatic adoption. It uses synthetic
NIfTI images and **two ROIs**, without downloading patient data, and checks:

- Two explicit FBS configurations against independent NumPy binning; cropped/full
  parity and exact JSON result/provenance round trips on both package versions.
- On 0.6: NIfTI RAS-to-LPS origin/direction; standard CT preset starts; public-log
  configuration hashes, environment, elapsed time and effective FBS minima.
- Effective resegmentation inheritance, invalid/missing FBS/IVH starts, filter and
  normalization invalidation, and rejection of joint-ROI growth.
- Normalization/growth full-image fallback with matching computed values; new
  Gaussian padding, Gabor response and local/spatial intensity option groups.
- Package long/wide result-name parity with the wrapper's feature keys.

The installed-Slicer suite covers actual FBS field/readiness behavior, profile
save/load, exact scene-setting restoration, old settings requiring review, and a
real two-ROI extraction with an independent histogram-bin oracle.

For a normal Python 3.12 environment with the released wheel and its dependencies
installed in an isolated target, run from the repository root (set `PYTHONPATH` to
that target and `NUMBA_CACHE_DIR` to a test-owned directory):

```sh
python scripts/check_pictologics_api.py
python scripts/smoke_pictologics_worker.py
python scripts/geometry_parity_check.py
python scripts/check_release_compatibility.py
```

This does not change the committed pin. For installed-Slicer regression, use
`scripts/run_slicer_integration.py` with the usual isolated launch flags, both module
paths, `SLICERPICTOLOGICS_RUN_REAL_CLI_TEST=1`, and
`SLICERPICTOLOGICS_TEST_DEPENDENCY_PATH` pointing to an inspected matching-version
private target. Keep the normal Slicer session and its active environment intact.

### Local evidence

Local output is retained under ignored `local-output/compatibility-060.gIrw8Y/`.
The initial direct PythonSlicer/PYTHONPATH probe incorrectly let bundled NumPy
shadow the private target; it failed. Repeating with `dependency_probe.isolate_target`
passed. The production worker already uses this isolation; no production fix was
needed for that harness error. The 0.6 installer failure is a separate real wheel
availability problem, not that harness error.

Completed local checks:

| Gate | Result |
| --- | --- |
| Portable suite (Python 3.12.10) | 601 passed; 2,643 scoped statements, 100% coverage |
| Ruff / Mypy / compileall / metadata JSON / diff whitespace | Passed; Mypy checks 18 files |
| Installed Slicer 5.12.4 / 0.5.1 full suite | 57 passed, zero skips/failures; 586.864 s; process exit 0 |
| Earlier fast Slicer suite | 50 passed, seven real-worker tests intentionally skipped; 28.392 s |
| 0.5.1 isolated API and expanded FBS checks | Passed with PythonSlicer and the existing private target |
| 0.6.0 native ARM developer API / full-JIT worker / geometry / expanded checks | Passed; 170 successful smoke rows and 170 geometry-parity features |
| 0.6.0 installed Intel Slicer dependency resolution | Failed: required Numba wheel unavailable |

The native ARM checks use the **released** 0.6.0 wheel (SHA-256
`29c0981a1411678c613d437950b97873e1589e6c604ff642bedb00de3666bf9b`), not the modified
sibling source checkout. They used Python 3.12.10, NumPy 2.5.3, Numba 0.67.0,
SciPy 1.17.0 and Pillow 11.3.0. They are not Intel Slicer application acceptance.
The updated cross-platform workflow has not yet run on these local compatibility
changes; the successful post-merge workflow above covers only the Windows milestone.
Requirements and constraints are unchanged, and no active dependency target was
replaced. All application tests ran in disposable sessions with disabled settings.

No raw logs, runtime environments, scans, scenes or images are tracked. Public
registration, releases/tags and new image publication remain on hold.
