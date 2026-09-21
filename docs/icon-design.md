# Pictologics extension icon

Revision 4 is the selected artwork for the
[complete reusable export set](../assets/branding/pictologics/README.md).
The [ZIP archive](../assets/branding/pictologics-branding-assets.zip) includes
Slicer PNGs, native-resolution raster masters, traced SVG/PDF/EPS, and platform
icons. Vector exports are explicitly labeled as approximations of the raster.
The catalog uses the approved 128-pixel PNG; the module explicitly uses the
256-pixel `PictologicsSlicer.png`, which is the only icon included in its runtime
resources. The old `PictologicsSlicer.svg` and earlier proposals are retained in
source control as design history, not installed by CMake. Extraction behavior,
dependency paths, and version 0.1.0 are unchanged.
The revision notes below record the artwork-generation stages before integration.

## Revision 4: irregular color mosaic

The latest proposal distributes the existing top-slab palette irregularly across
the small boxes, with occasional clusters of similar colors. This replaces the
broad color-sorted regions while retaining the fine voxel-grid and CT-analysis
composition.

Files use the prefix `Pictologics-ct-v4-`: `master.png` (1254 × 1254), `256.png`,
`128.png`, `64.png`, and `32.png`. All files were checked for PNG decoding,
dimensions, RGBA format, and transparent corners. Previous proposals are retained.
No runtime/catalog configuration has been changed.

The built-in image editor used `Pictologics-ct-v3-master.png` as its sole
`referenced_image_paths` edit target with the
[revision 4 prompt](pictologics-icon-ct-v4-prompt.txt). No CLI flags were used.
Smaller exports were resampled with macOS `sips`, preserving alpha.

## Revision 3: finer feature grid

The latest proposal refines only the top slab into a dense grid of smaller colored
boxes, retaining the CT-to-feature-map composition and the established palette.
The edit prompt requests a 10 × 10 subdivision; this is generated logo artwork,
not a machine-counted data matrix. The lower two slice designs remain in place.

Files use the prefix `Pictologics-ct-v3-`: `master.png` (1254 × 1254), `256.png`,
`128.png`, `64.png`, and `32.png`. PNG decoding, dimensions, RGBA format, and
transparent corners were checked. The 128- and 256-pixel exports were visually
inspected. Previous designs are preserved, and no runtime/catalog configuration
has been changed.

The built-in image editor used `Pictologics-ct-v2-master.png` as its single
`referenced_image_paths` edit target, with the
[revision 3 prompt](pictologics-icon-ct-v3-prompt.txt). No CLI flags were used.
Smaller exports were resampled with macOS `sips`, preserving alpha.

## Revision 2: CT image to radiomic features

The revised proposal uses the same three-tier visual identity, but makes the
radiological image-analysis purpose explicit:

- Bottom: a synthetic, illustrative grayscale axial chest CT slice.
- Middle: the same anatomy partially discretized into a colored texture/feature map.
- Top: the original large colored blocks representing the resulting feature data.

The CT artwork is generated, not a patient scan, and is not a diagnostic image.
The anatomical details are illustrative; the feature map is conceptual, not a
computed radiomics output or a screenshot from Slicer.

New files are saved alongside the original proposal with the prefix
`Pictologics-ct-v2-`: `master.png` (1254 × 1254), `256.png`, `128.png`, `64.png`,
and `32.png`. The 128-pixel export is suitable for the proposed catalog asset;
the 256-pixel export provides more detail. At toolbar size the three-tier
silhouette remains visible, while anatomical detail is naturally reduced.
All five files passed PNG decoding, square-dimension, RGBA, and transparent-corner
checks; the 32-, 128-, and 256-pixel exports were visually inspected.

Generation used the built-in image editor because the explicitly requested
`imagegen` skill's CLI had no `OPENAI_API_KEY` configured. The only reference input
was the original generated `Pictologics-master.png`; no medical image was uploaded.
The [complete revision prompt](pictologics-icon-ct-v2-prompt.txt) is retained.
The tool arguments were `prompt` and `referenced_image_paths` (one edit target);
no CLI model/quality flags were used. The original output was preserved and the
smaller PNGs were resampled with macOS `sips`, preserving alpha.

This revision is not activated or published. If selected, use
`Pictologics-ct-v2-128.png` in the proposed raw catalog URL instead of
`Pictologics-128.png`, and the 256-pixel variant for the module UI.

## Design

The mark adapts the colorful interlocking voxel blocks in the
[Pictologics package branding](https://github.com/martonkolossvary/pictologics)
and the green/amber accents of its
[documentation website](https://martonkolossvary.github.io/pictologics/).
Three separated voxel layers suggest volumetric image slices. Large color fields,
no lettering, and a near-black rounded badge keep the symbol recognizable at small
sizes and against light or dark application backgrounds. The outer corners have
real alpha transparency.

## Assets

All files are in `PictologicsSlicer/Resources/Icons/` and are genuine, square,
8-bit RGBA PNGs, not JPEGs renamed with a PNG extension.

| File | Dimensions | Intended use |
| --- | --- | --- |
| `Pictologics-128.png` | 128 × 128 | Conservative Extensions Catalog size |
| `Pictologics-256.png` | 256 × 256 | Higher-resolution catalog/module icon |
| `Pictologics-64.png` | 64 × 64 | Small icon / visual verification |
| `Pictologics-32.png` | 32 × 32 | Toolbar-scale visual verification |
| `Pictologics-master.png` | 1254 × 1254 | Original generated raster master; not needed in the extension package |

PNG decoding, dimensions, RGBA mode, transparent corners, and nonempty image data
were checked for every file. The 32-, 128-, and 256-pixel exports were visually
inspected. Small nonzero interior transparency from generation was preserved;
the artwork is effectively opaque, with antialiased edges.

## Slicer integration

Slicer's [extension documentation](https://github.com/Slicer/Slicer/blob/main/Docs/developer_guide/extensions.md)
recommends PNG and 128 × 128 pixels. Its
[submission checklist](https://github.com/Slicer/ExtensionsIndex/blob/main/.github/PULL_REQUEST_TEMPLATE.md)
requires a direct, raw image URL. The current
[ExtensionsIndex validator](https://github.com/Slicer/ExtensionsIndex/blob/main/scripts/check_description_files.py)
accepts PNG/JPEG/GIF response types, but not SVG.

`EXTENSION_ICONURL` now points to the published approved revision 4 export:

```text
https://raw.githubusercontent.com/martonkolossvary/SlicerPictologics/main/assets/branding/pictologics/slicer/Pictologics-128.png
```

This URL was verified to return HTTP 200 with `Content-Type: image/png` and the
same SHA-256 as the approved asset.

For the module UI, the selected PNG is included in `MODULE_PYTHON_RESOURCES` and
`parent.icon` explicitly selects it. Slicer 5.12's
`ScriptedLoadableModule` searches for the module-named SVG before PNG, so merely
adding a PNG beside the existing SVG will not switch the displayed icon.
The previous SVG is retained for history but excluded from packaging. The master,
print/vector exports, archive, and design notes are not runtime resources.

These assets address the icon portion of submission readiness. They do not by
themselves complete catalog metadata, screenshots, packaging, or Index acceptance.

## Generation provenance

The requested `generate-image` skill was inspected. Its OpenRouter route could
not run because no `OPENROUTER_API_KEY` was configured in the environment or
project/ancestor `.env` files. The built-in image generator was used as the
announced fallback, with branding inspected from the package logo and stylesheet.
No repository data or medical images were uploaded as reference inputs.

The [complete generation prompt](pictologics-icon-prompt.txt) is retained for
future iterations. The prompt requested a 1024-pixel master; the generator
returned 1254 × 1254, which is preserved unchanged. The four smaller exports were
created by proportional resampling with macOS `sips`, preserving alpha.
