"""Extra result columns: the reader, the scanner details, and the user's own columns.

The GUI gives these columns to the worker in the job manifest, and the worker adds
them to every row of the run. The GUI reads the scanner details from the DICOM
database, or from the JSON file that dcm2niix writes next to a NIfTI image.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Final

from .results import is_extra_column_name

# (column, DICOM tag, keys in a dcm2niix JSON file). All are acquisition settings;
# none identifies a patient.
SCANNER_COLUMNS: Final = (
    ("modality", "0008,0060", ("Modality",)),
    ("manufacturer", "0008,0070", ("Manufacturer",)),
    ("manufacturer_model_name", "0008,1090", ("ManufacturersModelName", "ManufacturerModelName")),
    ("convolution_kernel", "0018,1210", ("ConvolutionKernel",)),
    ("slice_thickness", "0018,0050", ("SliceThickness",)),
    ("kvp", "0018,0060", ("KVP",)),
    ("magnetic_field_strength", "0018,0087", ("MagneticFieldStrength",)),
)


def scanner_value(value: object) -> str:
    """Return a DICOM or JSON value as text; a list becomes backslash-separated."""

    if isinstance(value, (list, tuple)):
        return "\\".join(scanner_value(item) for item in value)
    return "" if value is None else str(value).strip()


def scanner_details_from_sidecar(data: Mapping[str, object]) -> dict[str, str]:
    """Return the scanner columns from a dcm2niix JSON file."""

    return {
        column: scanner_value(next((data[key] for key in keys if key in data), None))
        for column, _, keys in SCANNER_COLUMNS
    }


def sidecar_path(image_path: str) -> Path | None:
    """Return the JSON file that dcm2niix writes next to a NIfTI image."""

    for suffix in (".nii.gz", ".nii"):
        if image_path.lower().endswith(suffix):
            return Path(image_path[: -len(suffix)] + ".json")
    return None


def parse_extra_columns(text: str) -> list[tuple[str, str]]:
    """Parse one ``name = value`` pair per line; blank lines are skipped."""

    columns: list[tuple[str, str]] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        name, separator, value = line.partition("=")
        if not separator:
            raise ValueError(f"Extra columns, line {number}: write name = value.")
        columns.append((name.strip(), value.strip()))
    check_extra_columns(columns)
    return columns


def check_extra_columns(columns: Sequence[tuple[str, str]]) -> None:
    """Raise ValueError for a bad, repeated, or reserved extra column name."""

    names: set[str] = set()
    for name, value in columns:
        if name == "reader":
            raise ValueError("Use the Reader field for the reader column.")
        if not is_extra_column_name(name):
            raise ValueError(
                f"{name!r} cannot be a column name. Start with a letter, and use up to 64 "
                "letters, digits, and single underscores. Do not use a Pictologics "
                "column name."
            )
        if name in names:
            raise ValueError(f"The column {name!r} is given more than once.")
        if not isinstance(value, str):
            raise ValueError(f"The value of column {name!r} must be text.")
        names.add(name)


def build_result_columns(
    reader: str,
    scanner: Mapping[str, str],
    extra: Sequence[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Return the ordered extra columns: reader, scanner details, then the user's.

    A user column with a scanner column name replaces the value that was read.
    """

    check_extra_columns(extra)
    columns = {"reader": reader.strip()}
    columns.update((column, scanner.get(column, "")) for column, _, _ in SCANNER_COLUMNS)
    columns.update(extra)
    return list(columns.items())
