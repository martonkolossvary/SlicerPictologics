#!/usr/bin/env python3
"""Find the newest stable, non-yanked Pictologics wheel published on PyPI."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from urllib.request import Request, urlopen

from bump_pictologics_requirement import DEFAULT_REQUIREMENTS, bump_requirement, parse_release

PYPI_URL = "https://pypi.org/pypi/pictologics/json"


def resolve_release(payload: dict, requested: str = "") -> str:
    releases = payload.get("releases")
    if not isinstance(releases, dict):
        raise ValueError("PyPI response does not contain a releases mapping")
    available = {}
    for version, files in releases.items():
        try:
            normalized, key = parse_release(version)
        except ValueError:
            continue
        if normalized != version or not isinstance(files, list):
            continue
        usable_files = [entry for entry in files if not entry.get("yanked", False)]
        if usable_files:
            available[normalized] = (key, usable_files)
    if requested:
        version, _ = parse_release(requested)
        if version not in available:
            raise ValueError(f"Pictologics {version} is unpublished or entirely yanked")
    else:
        if not available:
            raise ValueError("PyPI has no usable stable Pictologics releases")
        version = max(available, key=lambda item: available[item][0])
    # An incomplete latest release fails visibly, rather than building an sdist.
    if not any(entry.get("packagetype") == "bdist_wheel" for entry in available[version][1]):
        raise ValueError(f"Pictologics {version} has no non-yanked binary wheel")
    return version


def fetch_release(requested: str = "", *, attempts: int = 10, delay: float = 60) -> str:
    """Resolve on PyPI. Retry a named release: PyPI's JSON view can lag its upload."""

    for attempt in range(1, attempts + 1):
        request = Request(PYPI_URL, headers={"User-Agent": "SlicerPictologics-release-qualification"})
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
        try:
            return resolve_release(payload, requested)
        except ValueError:
            if not requested or attempt == attempts:
                raise
            time.sleep(delay)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="", help="Optional explicit stable release")
    parser.add_argument("--requirements", type=Path, default=DEFAULT_REQUIREMENTS)
    args = parser.parse_args()
    version = fetch_release(args.version)
    changed = bump_requirement(args.requirements, version, dry_run=True)
    output = f"version={version}\nchanged={str(changed).lower()}\n"
    print(output, end="")
    if output_path := os.environ.get("GITHUB_OUTPUT"):
        with Path(output_path).open("a", encoding="utf-8") as handle:
            handle.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
