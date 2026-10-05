#!/usr/bin/env python3
"""Freeze wheel-only resolutions per runtime, then merge before qualification.

Use actual interpreters on each runner: pip's cross-platform flags do not replace
the host environment used when evaluating every dependency marker.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from packaging.utils import canonicalize_name
from packaging.version import Version

RUNTIMES = {
    "linux": ("cpython", "3.12", "linux", "x86_64"),
    "windows": ("cpython", "3.12", "win32", "AMD64"),
    # Both Intel hardware and Apple Silicon running Intel Slicer through Rosetta.
    "macos": ("cpython", "3.12", "darwin", "x86_64"),
}
FIELDS = ("implementation_name", "python_version", "sys_platform", "platform_machine")
RUNTIME_PREFIX = "# slicerpictologics-runtime: "


def stable_version(value):
    if not isinstance(value, str) or not re.fullmatch(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)", value):
        raise ValueError("Candidate must be one stable X.Y.Z version")
    return value


def snapshot(report, runtime, version, revision):
    stable_version(version)
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("Qualification requires an exact Git revision")
    expected = RUNTIMES[runtime]
    environment = report.get("environment", {})
    if tuple(environment.get(field) for field in FIELDS) != expected:
        raise ValueError(f"Resolver is not running the expected {runtime} interpreter")
    pins, hashes = {}, {}
    for item in report.get("install", []):
        metadata = item["metadata"]
        name = canonicalize_name(metadata["name"])
        value = str(Version(metadata["version"]))
        if name in pins:
            raise ValueError(f"Duplicate distribution: {name}")
        download = item["download_info"]
        digest = download.get("archive_info", {}).get("hashes", {}).get("sha256", "")
        if item.get("is_yanked") or not download["url"].split("?", 1)[0].endswith(".whl"):
            raise ValueError(f"Resolution contains a yanked or non-wheel artifact: {name}")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"Missing SHA-256 for {name}")
        pins[name], hashes[name] = value, digest
    if pins.get("pictologics") != version:
        raise ValueError("Resolved Pictologics does not match the candidate")
    if not {"numpy", "numba", "llvmlite"} <= pins.keys():
        raise ValueError("Incomplete scientific dependency resolution")
    return {"schema_version": 1, "runtime": runtime, "environment": dict(zip(FIELDS, expected, strict=True)),
            "version": version, "revision": revision, "pins": pins, "wheel_sha256": hashes}


def merge(snapshots, version, revision):
    stable_version(version)
    collected = {}
    for item in snapshots:
        runtime = item["runtime"]
        if runtime not in RUNTIMES or runtime in collected:
            raise ValueError("Unknown or duplicate runtime snapshot")
        # Revalidate serialized artifacts instead of trusting a renamed file.
        report = {"environment": item["environment"], "install": [
            {"metadata": {"name": name, "version": value}, "download_info": {
                "url": "https://validated.invalid/package.whl",
                "archive_info": {"hashes": {"sha256": item["wheel_sha256"][name]}}}}
            for name, value in item["pins"].items()]}
        checked = snapshot(report, runtime, version, revision)
        if item != checked:
            raise ValueError("Snapshot schema, candidate or revision mismatch")
        collected[runtime] = item["pins"]
    if collected.keys() != RUNTIMES.keys():
        raise ValueError("Every supported runtime must resolve before qualification")
    lines = ["# Generated from wheel-only resolutions; publish only after all gates pass.",
             f"# Qualified wrapper revision: {revision}"]
    lines.extend(RUNTIME_PREFIX + "|".join(runtime) for runtime in RUNTIMES.values())
    for name in sorted(set().union(*(pins.keys() for pins in collected.values()))):
        versions = sorted({pins[name] for pins in collected.values() if name in pins})
        for value in versions:
            selected = [key for key in RUNTIMES if collected[key].get(name) == value]
            line = f"{name}=={value}"
            if len(selected) != len(RUNTIMES):
                markers = [" and ".join(f'{field} == "{entry}"' for field, entry in zip(FIELDS, RUNTIMES[key], strict=True)) for key in selected]
                line += "; " + " or ".join(f"({marker})" for marker in markers)
            lines.append(line)
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--report", type=Path)
    group.add_argument("--snapshots", nargs="+", type=Path)
    parser.add_argument("--runtime", choices=RUNTIMES)
    args = parser.parse_args()
    if args.report:
        if args.runtime is None:
            parser.error("--report requires --runtime")
        result = json.dumps(snapshot(json.loads(args.report.read_text(encoding="utf-8")), args.runtime,
                                     args.version, args.revision), indent=2, sort_keys=True) + "\n"
    else:
        result = merge([json.loads(path.read_text(encoding="utf-8")) for path in args.snapshots],
                       args.version, args.revision)
    args.output.write_text(result, encoding="utf-8")


if __name__ == "__main__":
    main()
