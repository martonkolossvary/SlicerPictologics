"""Export the approved raster icon and explicitly labeled path-based derivatives.

Developer-only dependencies: Pillow, vtracer==0.6.15, CairoSVG==2.8.2, pypdf.
These tools are not required by Slicer or the extension runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import shutil
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import cairosvg
import vtracer
from PIL import Image
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
PNG_SIZES = (16, 24, 32, 48, 64, 128, 256, 512, 1024)
TRACE_OPTIONS = {
    "colormode": "color",
    "hierarchical": "stacked",
    "mode": "spline",
    "filter_speckle": 6,
    "color_precision": 6,
    "layer_difference": 12,
    "corner_threshold": 60,
    "length_threshold": 3.5,
    "max_iterations": 10,
    "splice_threshold": 45,
    "path_precision": 3,
}
SVG_NS = "http://www.w3.org/2000/svg"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export_assets(source: Path, output: Path) -> None:
    folders = {name: output / name for name in ("raster", "vector", "slicer", "platform")}
    for folder in folders.values():
        folder.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as original:
        if original.format != "PNG" or original.mode != "RGBA":
            raise ValueError("Expected an RGBA PNG master")
        image = original.copy()
    if image.size != (1254, 1254):
        raise ValueError(f"Unexpected approved master dimensions: {image.size}")

    raster = folders["raster"]
    master = raster / "pictologics-master-1254.png"
    shutil.copyfile(source, master)  # Preserve the approved bytes exactly.
    for size in PNG_SIZES:
        resized = image.resize((size, size), Image.Resampling.LANCZOS)
        resized.save(raster / f"pictologics-{size}.png", optimize=True)
    image.save(raster / "pictologics-master-1254.tiff", compression="tiff_lzw", dpi=(300, 300))
    image.save(raster / "pictologics-master-1254.webp", lossless=True, exact=True, method=6)
    white = Image.new("RGBA", image.size, "white")
    white.alpha_composite(image)
    white.convert("RGB").save(
        raster / "pictologics-white-1254.jpg", quality=98, subsampling=0,
        optimize=True, dpi=(300, 300),
    )

    for size in (128, 256):
        shutil.copyfile(raster / f"pictologics-{size}.png", folders["slicer"] / f"Pictologics-{size}.png")
    # A convenient module-named resource; activating it is a separate code change.
    shutil.copyfile(raster / "pictologics-256.png", folders["slicer"] / "PictologicsSlicer.png")

    icon_sizes = [(size, size) for size in (16, 24, 32, 48, 64, 128, 256)]
    image.save(folders["platform"] / "pictologics.ico", sizes=icon_sizes)
    image.save(folders["platform"] / "pictologics.icns")

    vector = folders["vector"]
    svg_path = vector / "pictologics-traced.svg"
    with tempfile.TemporaryDirectory(prefix="pictologics-vector-") as scratch:
        # Tracing cannot retain smooth alpha exactly. Binarize only the temporary
        # trace input to prevent invisible RGB fringes becoming stray paths.
        trace_image = image.copy()
        trace_image.putalpha(image.getchannel("A").point(lambda alpha: 255 if alpha >= 128 else 0))
        trace_input = Path(scratch) / "trace-input.png"
        trace_image.save(trace_input)
        vtracer.convert_image_to_svg_py(str(trace_input), str(svg_path), **TRACE_OPTIONS)

    ET.register_namespace("", SVG_NS)
    tree = ET.parse(svg_path)
    root = tree.getroot()
    root.set("viewBox", "0 0 1254 1254")
    root.set("role", "img")
    root.set("aria-labelledby", "title description")
    title = ET.Element(f"{{{SVG_NS}}}title", {"id": "title"})
    title.text = "Pictologics: CT images to radiomic feature data"
    description = ET.Element(f"{{{SVG_NS}}}desc", {"id": "description"})
    description.text = "Path-only automatic trace of approved artwork; CT texture is simplified."
    root.insert(0, title)
    root.insert(1, description)
    paths = root.findall(f".//{{{SVG_NS}}}path")
    for index, path in enumerate(paths):
        path.set("id", f"shape-{index + 1:05d}")
    if not paths or root.findall(f".//{{{SVG_NS}}}image"):
        raise ValueError("Vector export must contain paths and no embedded raster images")
    tree.write(svg_path, encoding="utf-8", xml_declaration=True)
    cairosvg.svg2pdf(url=str(svg_path), write_to=str(vector / "pictologics-traced.pdf"))
    cairosvg.svg2eps(url=str(svg_path), write_to=str(vector / "pictologics-traced.eps"))

    # A clearly named large rasterization of vector artwork, not a claim of
    # additional detail in the original 1254-pixel raster source.
    cairosvg.svg2png(
        url=str(svg_path), write_to=str(raster / "pictologics-vector-render-4096.png"),
        output_width=4096, output_height=4096,
    )

    # Reopen the final files rather than merely trusting successful save calls.
    for path in sorted(output.rglob("*.png")):
        with Image.open(path) as candidate:
            candidate.verify()
        with Image.open(path) as candidate:
            assert candidate.format == "PNG" and candidate.mode == "RGBA", path
            assert candidate.width == candidate.height, path
            alpha = candidate.getchannel("A")
            assert alpha.getextrema() == (0, 255), path
            assert alpha.getpixel((0, 0)) == 0, path
    for name in ("pictologics-master-1254.tiff", "pictologics-master-1254.webp"):
        with Image.open(raster / name) as candidate:
            assert candidate.convert("RGBA").tobytes() == image.tobytes(), name
    assert sha256(master) == sha256(source)
    pdf = PdfReader(vector / "pictologics-traced.pdf")
    assert len(pdf.pages) == 1 and len(pdf.pages[0].images) == 0
    with Image.open(folders["platform"] / "pictologics.ico") as ico:
        assert ico.ico.sizes() == set(icon_sizes)
    with Image.open(folders["platform"] / "pictologics.icns") as icns:
        icns.load()
        assert icns.size == (1024, 1024)

    metadata = {
        "source": str(source.relative_to(ROOT)) if source.is_relative_to(ROOT) else source.name,
        "source_sha256": sha256(source),
        "source_pixels": list(image.size),
        "vector_is_exact_raster_copy": False,
        "vector_path_count": len(paths),
        "vector_embedded_images": 0,
        "pdf_embedded_images": 0,
        "vector_trace_alpha_threshold": 128,
        "vector_trace_options": TRACE_OPTIONS,
        "tools": {name: importlib.metadata.version(name) for name in ("Pillow", "vtracer", "CairoSVG", "pypdf")},
        "files": [
            {"path": str(path.relative_to(output)), "bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in sorted(output.rglob("*"))
            if path.is_file() and path.name != "manifest.json"
        ],
    }
    (output / "manifest.json").write_text(json.dumps(metadata, indent=2) + "\n")
    archive = output.parent / "pictologics-branding-assets.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in sorted(output.rglob("*")):
            if path.is_file():
                bundle.write(path, arcname=Path(output.name) / path.relative_to(output))
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
    print(json.dumps({"output": str(output), "archive": str(archive), "vector_paths": len(paths), "checks": "passed"}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "PictologicsSlicer/Resources/Icons/Pictologics-ct-v4-master.png")
    parser.add_argument("--output", type=Path, default=ROOT / "assets/branding/pictologics")
    args = parser.parse_args()
    export_assets(args.source.resolve(), args.output.resolve())
