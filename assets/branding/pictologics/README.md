# Pictologics approved icon export set

Source: the approved revision 4 CT / feature-map / randomized color-grid artwork.
This is illustrative, synthetic anatomy, not patient data or a diagnostic image.

## Which file to use

| Purpose | File(s) | Notes |
| --- | --- | --- |
| Slicer Extensions Catalog | `slicer/Pictologics-128.png` | Conservative 128-pixel PNG recommendation |
| Higher-density Slicer display | `slicer/Pictologics-256.png` | Same approved raster artwork |
| Slicer module resource | `slicer/PictologicsSlicer.png` | 256-pixel PNG; activation still requires packaging/module updates |
| Exact archival source | `raster/pictologics-master-1254.png` | Byte-identical original RGBA PNG |
| Lossless editing / web masters | `raster/pictologics-master-1254.tiff`, `.webp` | Original 1254-pixel resolution and alpha; decoded pixels verified |
| Broad image compatibility / print | `raster/pictologics-white-1254.jpg` | Quality 98, no chroma subsampling; transparent exterior flattened onto white |
| Common image sizes | `raster/pictologics-{size}.png` | 16, 24, 32, 48, 64, 128, 256, 512, 1024 pixels; alpha preserved |
| Editable scalable shapes | `vector/pictologics-traced.svg` | Genuine paths, no embedded PNG; automatic trace, not an exact raster copy |
| Vector print / illustration tools | `vector/pictologics-traced.pdf`, `.eps` | Derived from the traced SVG, not a bitmap wrapped in PDF/EPS |
| Large rasterized vector | `raster/pictologics-vector-render-4096.png` | 4096-pixel rendering of the traced artwork, NOT additional original image detail |
| Windows / macOS convenience | `platform/pictologics.ico`, `.icns` | Multi-resolution files; not required for Slicer extension submission |

The TIFF and JPEG carry 300-DPI metadata. This does not add pixels: the original
1254-pixel image corresponds to approximately 4.18 inches / 106 mm at 300 DPI.
Use the vector files when scaling beyond the native raster resolution is needed.

## Vector fidelity

SVG, PDF, and EPS contain actual vector paths. Colors, silhouettes, grid geometry,
and recognizable CT structures are traced from the approved image. Fine CT noise,
subtle shading, antialiasing, and soft alpha are simplified. Prefer the original
PNG/TIFF/WebP when exact visual fidelity matters. The SVG includes named paths
for editing; these are automatically traced regions, not hand-organized semantic
layers. Its transparent exterior is retained; EPS does not support soft alpha.

## Slicer submission notes

The [Slicer extension documentation](https://github.com/Slicer/Slicer/blob/main/Docs/developer_guide/extensions.md)
recommends a PNG icon at 128 x 128 pixels. The
[submission checklist](https://github.com/Slicer/ExtensionsIndex/blob/main/.github/PULL_REQUEST_TEMPLATE.md)
requires a direct raw image URL. PNG/JPEG/GIF are accepted response types by the
[current validator](https://github.com/Slicer/ExtensionsIndex/blob/main/scripts/check_description_files.py);
these are alternatives, not a requirement to submit all three. Use PNG to retain
alpha. SVG, PDF, EPS, TIFF, WebP, ICO, and ICNS are extra reusable assets, not
required catalog uploads. Do not supply the 4096-pixel derivative as the catalog icon.

Committing and pushing this folder publishes the catalog-ready icon at:

```text
https://raw.githubusercontent.com/martonkolossvary/SlicerPictologics/main/assets/branding/pictologics/slicer/Pictologics-128.png
```

The icon is not yet connected to `EXTENSION_ICONURL`; verify HTTP 200 and
`Content-Type: image/png` after publishing. The existing module-named SVG
takes precedence over PNG in Slicer 5.12, so adding a PNG alone will not activate
the new design. Include only the selected runtime resource(s) in CMake packaging,
not the full archive, print exports, or source master. Screenshots and the other
ExtensionsIndex checklist items remain separate work.

## Reproduction and verification

`scripts/export_branding_assets.py` reproduces this set from the approved source.
It requires Pillow, vtracer 0.6.15, CairoSVG 2.8.2, pypdf, and a system Cairo
library. These are developer-only tools, not extension/runtime dependencies.
For this export they were used in an isolated temporary environment; no new
image-generation call was made and no cloud upload was needed.

`manifest.json` records source/output SHA-256 hashes, dimensions, tool versions,
trace settings, path count, and the absence of raster images in SVG/PDF. The
vector PDF was rendered with Poppler for visual review. The ZIP alongside this
folder contains the complete set and passed an archive integrity check.

All earlier icon proposals are preserved. Publishing this asset bundle does not
change application settings, extension behavior, or catalog configuration, and
does not activate the new icon in Slicer.
