#!/usr/bin/env python3
"""Read-only content audit of a real CMake/Extension Factory ZIP or tar package.

Compare against the exact source checkout used to build the archive. This does not
build, extract, install, or qualify a package in Slicer. Synthetic test fixtures
exercise the checker only; they are not installable extension packages.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

MAX_MEMBERS = 10_000
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 64 * 1024 * 1024
FORBIDDEN_PARTS = frozenset({
    ".git", ".venv", "assets", "docs", "testing", "tests", "screenshots",
    "site-packages", "private-dependencies", "environments", "numba-cache",
})


def safe_name(name: str) -> str:
    if "\\" in name or ":" in name or name.startswith("/"):
        raise ValueError(f"Unsafe archive path: {name!r}")
    parts = PurePosixPath(name).parts
    if not parts or ".." in parts:
        raise ValueError(f"Unsafe archive path: {name!r}")
    return str(PurePosixPath(*parts))


def expected_files(source: Path) -> dict[str, Path]:
    """Read the explicit runtime lists; fail closed if their CMake form changes."""
    module = source / "PictologicsSlicer"
    cmake = (module / "CMakeLists.txt").read_text(encoding="utf-8")
    result = {}
    for variable in ("MODULE_PYTHON_SCRIPTS", "MODULE_PYTHON_RESOURCES"):
        matches = re.findall(r"set\(" + variable + r"\s+([^)]*)\)", cmake)
        if len(matches) != 1:
            raise ValueError(f"Cannot read the explicit CMake list {variable}")
        values = re.sub(r"#[^\n]*", "", matches[0]).split()
        if not values:
            raise ValueError(f"Empty CMake runtime list {variable}")
        for value in values:
            value = value.replace("${MODULE_NAME}", "PictologicsSlicer")
            if any(character in value for character in '$";'):
                raise ValueError(f"Unsupported CMake expression: {value}")
            relative = safe_name(value)
            result[f"qt-scripted-modules/{relative}"] = module / relative
    for suffix in ("py", "xml"):
        relative = f"PictologicsCLI.{suffix}"
        result[f"cli-modules/{relative}"] = source / "PictologicsCLI" / relative
    for path in result.values():
        if not path.is_file():
            raise ValueError(f"Missing source runtime file: {path}")
    return result


def archive_hashes(archive: Path) -> dict[str, str]:
    """Hash bounded regular members without ever extracting an archive."""
    hashes: dict[str, str] = {}
    seen: set[str] = set()
    total = 0

    def inspect(name, size, directory, regular, opener):
        nonlocal total
        name = safe_name(name)
        if name.casefold() in seen:
            raise ValueError(f"Duplicate/case-colliding archive path: {name}")
        seen.add(name.casefold())
        if len(seen) > MAX_MEMBERS:
            raise ValueError("Too many archive entries")
        if not directory and not regular:
            raise ValueError(f"Link or special archive entry: {name}")
        if directory:
            return
        total += size
        if size < 0 or size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            raise ValueError("Archive exceeds the runtime-only size limits")
        if FORBIDDEN_PARTS.intersection(part.casefold() for part in PurePosixPath(name).parts):
            raise ValueError(f"Non-runtime content in package: {name}")
        with opener() as stream:
            content = stream.read(MAX_FILE_BYTES + 1)
        if len(content) != size:
            raise ValueError(f"Archive member size mismatch: {name}")
        hashes[name] = hashlib.sha256(content).hexdigest()

    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as package:
            for member in package.infolist():
                mode = member.external_attr >> 16
                kind = stat.S_IFMT(mode)
                regular = kind in (0, stat.S_IFREG)
                directory = member.is_dir() and kind in (0, stat.S_IFDIR)
                inspect(member.orig_filename, member.file_size, directory, regular,
                        lambda item=member: package.open(item))
    else:
        with tarfile.open(archive, "r:*") as package:
            for member in package:
                inspect(member.name, member.size, member.isdir(), member.isfile(),
                        lambda item=member: package.extractfile(item))
    return hashes


def audit_package(archive: Path, source: Path) -> dict:
    expected = expected_files(source)
    hashes = archive_hashes(archive)
    errors = []
    locations = {}
    for suffix, source_file in expected.items():
        matches = [name for name in hashes if name == suffix or name.endswith("/" + suffix)]
        if len(matches) != 1:
            errors.append(f"Expected exactly one {suffix}; found {len(matches)}")
            continue
        name = matches[0]
        group, relative = suffix.split("/", 1)
        locations.setdefault(group, set()).add(name[:-len(relative)])
        if hashes[name] != hashlib.sha256(source_file.read_bytes()).hexdigest():
            errors.append(f"Source content mismatch: {name}")
    for group, roots in locations.items():
        if len(roots) != 1:
            errors.append(f"Runtime files split across multiple {group} directories")
    for name in hashes:
        for group in ("qt-scripted-modules", "cli-modules"):
            marker = group + "/"
            if not (name.startswith(marker) or "/" + marker in name):
                continue
            relative = marker + name.split(marker, 1)[1]
            # CTK may install bytecode beside sources or in __pycache__. Only
            # permit bytecode for a source explicitly listed by this extension.
            source_relative = re.sub(
                r"/__pycache__/([^/]+)\.cpython-\d+(?:\.opt-\d+)?\.pyc$", r"/\1.py", relative
            )
            if source_relative.endswith(".pyc"):
                source_relative = source_relative[:-1]
            if source_relative not in expected:
                errors.append(f"Unexpected runtime file: {name}")
    with archive.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {
        "scope": "archive content only; NOT Slicer installation acceptance",
        "archive": str(archive.resolve()),
        "archive_sha256": digest,
        "source": str(source.resolve()),
        "expected_runtime_files": len(expected),
        "archive_files": len(hashes),
        "module_directories": {group: sorted(roots) for group, roots in locations.items()},
        "errors": errors,
        "success": not errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1])
    arguments = parser.parse_args()
    try:
        report = audit_package(arguments.archive, arguments.source)
    except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile, RuntimeError) as exc:
        report = {"success": False, "errors": [str(exc)]}
    print(json.dumps(report, indent=2))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
