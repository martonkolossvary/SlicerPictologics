# Catalog screenshots

Both images are genuine, unretouched Slicer captures from one real extraction on
2026-11-01, with Slicer 5.12.4 on macOS (Intel build under Rosetta), Pictologics 1.0.0
and the `standard_fbn_32` preset. They do not include the operating-system title bar.

- `pictologics-workflow.png` (3680 × 1988): the application window with the two
  regions and the module panel after the run. SHA-256:
  `7ff1e7b3e9f9e84331512c546535c84e407a0f15128ea039a0f45132895c3edc`.
- `pictologics-results.png` (2900 × 1900): the read-only results and provenance
  browser of the same run. SHA-256:
  `227f8fd04bc7a1f34d5bc2e756a07496ae2b466c02b991fc50c335a3ccecad9f`.

## Image and annotations

The scan is Slicer's public **CTLiver** sample with its matching Medical
Segmentation Decathlon **Task03_Liver / liver_100** annotations. The two regions are
**Liver tissue (MSD label 1)** and **Liver tumour (MSD label 2)**. Label 1 excludes
the separately labelled tumour; it is not an inclusive whole-liver mask. These are
supplied research-dataset annotations, not segmentations newly validated by this
project or claims of clinical accuracy.

The image comes from Slicer's CTLiver sample, SHA-256
`e16eae0ae6fefa858c5c11e58f0f1bb81834d81b7102e021571056324ef6f37e`.
The matching label file is retrieved from a
[public mirror pinned to revision 6a5aad7](https://huggingface.co/datasets/MedOtter/msd-liver/blob/6a5aad7ca262f2420d1bd4c2517b37b265db53eb/labelsTr/liver_100.nii.gz),
SHA-256 `ab2d2f85c5143fed2a14480fe172cf7956defab078431ac5315b1d36fefd548c`.
The dataset is attributed to the [Medical Segmentation Decathlon](http://medicaldecathlon.com/),
under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/);
see [Antonelli et al., 2022](https://doi.org/10.1038/s41467-022-30695-9).
Retain this attribution and the dataset's reuse terms with any approved CT-derived
images. The mirror is a distribution source, not an independent annotation audit.

## The run

[`create_anatomical_ct_demo.py`](../../scripts/create_anatomical_ct_demo.py) verifies
both file hashes and checks all physical-grid corners (maximum allowed disagreement
0.001 mm). It crops the native CT lattice around both annotations, without
resampling, changing intensities, or truncating labelled voxels. It runs the module
workflow for both regions, exports the results and an MRB scene, and captures the
window and the results browser of that same extraction. It installs nothing.

The crop kept all 5,003,071 label-1 voxels and 1,569,689 label-2 voxels; the largest
physical-grid corner disagreement was 0.00004465 mm. The extraction returned
**170 features per region, 340 rows, all `ok`**. These observations verify the
demonstration workflow, not clinical annotation accuracy or general performance.

## Reproduce

Download the pinned annotation above to a temporary directory and set these
environment variables:

- `PICTOLOGICS_ANATOMICAL_DEMO_OUTPUT`: a **new** temporary output directory,
  outside the repository and synced folders.
- `PICTOLOGICS_ANATOMICAL_LABELS`: the downloaded `liver_100` annotation file.
- `PICTOLOGICS_SAMPLE_CACHE`: the directory containing the original checksum-verified
  `CTLiver.nrrd`.
- `SLICERPICTOLOGICS_TEST_DEPENDENCY_PATH`: an existing private package folder with
  the adopted Pictologics release.
- `NUMBA_NUM_THREADS=2` for a bounded demonstration run; keep `PICTOLOGICS_DEV_SOURCE` unset.

Then launch a fresh, visible Slicer from the repository root (on macOS):

```sh
/Applications/Slicer.app/Contents/MacOS/Slicer \
  --no-splash --disable-settings --ignore-slicerrc \
  --additional-module-paths "$PWD/PictologicsSlicer" "$PWD/PictologicsCLI" \
  --python-script "$PWD/scripts/create_anatomical_ct_demo.py"
```

The script refuses to reuse an output directory or a scene that holds a volume.
Keep new captures outside the repository until the maintainer has looked at them.

Screenshots are documentation and catalog assets only. They are not in the installed
module resources. `EXTENSION_SCREENSHOTURLS` in the root CMake file points to their
raw GitHub URLs.
