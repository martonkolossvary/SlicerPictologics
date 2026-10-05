#!/usr/bin/env python3
"""Check the active runtime's exact pins and dependency closure in a private target."""
from __future__ import annotations

import argparse
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "PictologicsSlicer"))

from packaging.markers import default_environment  # noqa: E402
from packaging.requirements import Requirement  # noqa: E402
from packaging.utils import canonicalize_name  # noqa: E402
from PictologicsLib.dependencies import (  # noqa: E402
    _requirement_lines,
    check_dependency_constraints,
    parse_pictologics_requirement,
)


def check(target, constraints, requirement):
    check_dependency_constraints(constraints, requirement)
    environment = default_environment()
    installed = {}
    distributions = list(metadata.distributions(path=[str(target)]))
    for distribution in distributions:
        name = canonicalize_name(distribution.metadata["Name"])
        if name in installed:
            raise ValueError(f"Ambiguous installed distribution: {name}")
        installed[name] = distribution
    selected = {}
    for _, line in _requirement_lines(Path(constraints)):
        pin = Requirement(line)
        if pin.marker is None or pin.marker.evaluate(environment):
            selected[canonicalize_name(pin.name)] = pin
    if installed.keys() != selected.keys():
        raise ValueError(f"Installed/qualified distributions differ: {sorted(installed.keys() ^ selected.keys())}")
    for name, pin in selected.items():
        if installed[name].version not in pin.specifier:
            raise ValueError(f"Installed {name}=={installed[name].version} violates {pin}")
    # Traverse requested extras as well as base requirements. This never imports
    # the package, so it checks only this target rather than Slicer's shared stack.
    pending, visited = [(canonicalize_name(requirement.name), "")], set()
    while pending:
        name, extra = pending.pop()
        if (name, extra) in visited:
            continue
        visited.add((name, extra))
        for value in installed[name].requires or []:
            dependency = Requirement(value)
            if dependency.marker is not None and not dependency.marker.evaluate({**environment, "extra": extra}):
                continue
            child = canonicalize_name(dependency.name)
            if dependency.url or child not in installed or installed[child].version not in dependency.specifier:
                raise ValueError(f"Unsatisfied dependency of {name}: {dependency}")
            pending.extend((child, item) for item in {"", *dependency.extras})
    return len(installed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--constraints", type=Path, default=ROOT / "PictologicsSlicer/constraints-pictologics.txt")
    parser.add_argument("--requirements", type=Path, default=ROOT / "PictologicsSlicer/requirements-pictologics.txt")
    args = parser.parse_args()
    count = check(args.target, args.constraints, parse_pictologics_requirement(args.requirements))
    print(f"Runtime-qualified dependency closure passed: {count} exact distributions.")


if __name__ == "__main__":
    main()
