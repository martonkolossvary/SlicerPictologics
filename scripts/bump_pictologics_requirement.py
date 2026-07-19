#!/usr/bin/env python3
"""Advance the adopted Pictologics version in the extension requirements file."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REQUIREMENTS = (
    REPOSITORY_ROOT / "PictologicsSlicer/requirements-pictologics.txt"
)
RELEASE_PATTERN = re.compile(
    r"^(?:v)?(?P<version>(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))$"
)
REQUIREMENT_PATTERN = re.compile(
    r"^(?P<prefix>\s*pictologics\s*==\s*)"
    r"(?P<version>(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*))"
    r"(?P<suffix>\s*(?:#.*)?)$",
    flags=re.IGNORECASE | re.MULTILINE,
)


def parse_release(value: str) -> tuple[str, tuple[int, int, int]]:
    """Return a normalized stable release and its comparable integer tuple."""

    match = RELEASE_PATTERN.fullmatch(value.strip())
    if match is None:
        raise ValueError(
            f"Invalid release {value!r}; expected a stable X.Y.Z version (an optional v prefix is allowed)"
        )
    normalized = match.group("version")
    return normalized, tuple(int(part) for part in normalized.split("."))  # type: ignore[return-value]


def bump_requirement(
    requirements_path: Path, release: str, *, dry_run: bool = False
) -> bool:
    """Update exactly one ``pictologics==X.Y.Z`` line without permitting a downgrade."""

    normalized, requested_tuple = parse_release(release)
    try:
        contents = requirements_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ValueError(
            f"Requirements file does not exist: {requirements_path}"
        ) from exc

    matches = list(REQUIREMENT_PATTERN.finditer(contents))
    if len(matches) != 1:
        raise ValueError(
            f"Expected exactly one pictologics==X.Y.Z requirement in {requirements_path}; "
            f"found {len(matches)}"
        )

    match = matches[0]
    current = match.group("version")
    current_tuple = tuple(int(part) for part in current.split("."))
    if requested_tuple < current_tuple:
        raise ValueError(
            f"Refusing to lower the adopted Pictologics version from {current} to {normalized}"
        )
    if requested_tuple == current_tuple:
        return False

    replacement = f"{match.group('prefix')}{normalized}{match.group('suffix')}"
    updated = contents[: match.start()] + replacement + contents[match.end() :]
    if not dry_run:
        requirements_path.write_text(updated, encoding="utf-8")
    return True


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "version", help="Stable Pictologics release, for example 0.5.1 or v0.5.1"
    )
    parser.add_argument(
        "--requirements",
        type=Path,
        default=DEFAULT_REQUIREMENTS,
        help=f"Requirements file to edit (default: {DEFAULT_REQUIREMENTS})",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Validate without writing the file"
    )
    return parser


def main() -> int:
    args = build_argument_parser().parse_args()
    try:
        changed = bump_requirement(
            args.requirements, args.version, dry_run=args.dry_run
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    action = (
        "Would update"
        if args.dry_run and changed
        else "Updated"
        if changed
        else "Already at"
    )
    normalized, _ = parse_release(args.version)
    print(f"{action} adopted Pictologics version {normalized} in {args.requirements}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
