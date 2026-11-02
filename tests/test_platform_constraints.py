"""Release-only scripts: not installed as Slicer application tests."""
import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from packaging.markers import default_environment
from packaging.requirements import Requirement


def load_script(name):
    path = Path(__file__).resolve().parents[1] / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


constraints = load_script("platform_constraints")
runtime_check = load_script("check_runtime_dependencies")
REVISION = "a" * 40


def report(runtime):
    versions = {"pictologics": "0.6.1", "numpy": "2.3.5" if runtime == "macos" else "2.5.3",
                "numba": "0.62.1" if runtime == "macos" else "0.67.0",
                "llvmlite": "0.45.1" if runtime == "macos" else "0.49.0"}
    return {"environment": dict(zip(constraints.FIELDS, constraints.RUNTIMES[runtime], strict=True)),
            "install": [{"metadata": {"name": name, "version": version},
                         "download_info": {"url": "https://example.invalid/package.whl",
                                           "archive_info": {"hashes": {"sha256": "b" * 64}}}}
                        for name, version in versions.items()]}


class PlatformConstraintTests(unittest.TestCase):
    def snapshots(self):
        return [constraints.snapshot(report(runtime), runtime, "0.6.1", REVISION)
                for runtime in constraints.RUNTIMES]

    def test_reproducible_complete_merge_selects_one_exact_pin_per_runtime(self):
        snapshots = self.snapshots()
        content = constraints.merge(snapshots, "0.6.1", REVISION)
        self.assertEqual(content, constraints.merge(list(reversed(snapshots)), "0.6.1", REVISION))
        for item in snapshots:
            environment = {**default_environment(), **item["environment"]}
            selected = {}
            for line in content.splitlines():
                if line.startswith("#"):
                    continue
                pin = Requirement(line)
                if pin.marker is None or pin.marker.evaluate(environment):
                    self.assertNotIn(pin.name, selected)
                    selected[pin.name] = next(iter(pin.specifier)).version
            self.assertEqual(selected, item["pins"])
        self.assertIn("# slicerpictologics-runtime: cpython|3.12|darwin|x86_64", content)

    def test_failure_of_any_platform_prevents_merge(self):
        snapshots = self.snapshots()
        for items in ([], snapshots[:2], [*snapshots, snapshots[0]]):
            with self.assertRaises(ValueError):
                constraints.merge(items, "0.6.1", REVISION)
        for field, value in (("revision", "c" * 40), ("version", "0.7.0"),
                             ("schema_version", 2), ("runtime", "arm64")):
            changed = copy.deepcopy(snapshots)
            changed[0][field] = value
            with self.assertRaises(ValueError):
                constraints.merge(changed, "0.6.1", REVISION)

    def test_rejects_wrong_interpreter_bad_artifacts_and_incomplete_resolution(self):
        source = report("macos")
        mutations = [lambda r: r["environment"].update(platform_machine="arm64"),
                     lambda r: r["install"].append(copy.deepcopy(r["install"][0])),
                     lambda r: r["install"][0].update(is_yanked=True),
                     lambda r: r["install"][0]["download_info"].update(url="https://example.invalid/source.tar.gz"),
                     lambda r: r["install"][0]["download_info"]["archive_info"].update(hashes={}),
                     lambda r: r["install"][0]["metadata"].update(version="0.7.0"),
                     lambda r: r["install"].pop()]
        for mutate in mutations:
            candidate = copy.deepcopy(source)
            mutate(candidate)
            with self.assertRaises(ValueError):
                constraints.snapshot(candidate, "macos", "0.6.1", REVISION)
        for version in ("0.6", "0.6.1rc1", "0.6.1\nEVIL", "01.6.1"):
            with self.assertRaises(ValueError):
                constraints.snapshot(source, "macos", version, REVISION)
        with self.assertRaises(ValueError):
            constraints.snapshot(source, "macos", "0.6.1", "main")

    def test_cli_snapshot_and_merge(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = []
            for runtime in constraints.RUNTIMES:
                source, output = root / "report.json", root / f"{runtime}.json"
                source.write_text(json.dumps(report(runtime)))
                arguments = ["script", "--version", "0.6.1", "--revision", REVISION,
                             "--output", str(output), "--report", str(source), "--runtime", runtime]
                with patch.object(sys, "argv", arguments):
                    constraints.main()
                paths.append(str(output))
            output = root / "constraints.txt"
            with patch.object(sys, "argv", ["script", "--version", "0.6.1", "--revision", REVISION,
                              "--output", str(output), "--snapshots", *paths]):
                constraints.main()
            self.assertEqual(output.read_text(), constraints.merge(self.snapshots(), "0.6.1", REVISION))


class DependencyClosureTests(unittest.TestCase):
    def test_exact_selected_pins_and_transitive_extras(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, version, requires in (("pictologics", "0.6.1", "Requires-Dist: parent[extra]>=1\n"),
                                             ("parent", "1.0", 'Requires-Dist: child==2; extra == "extra"\n'),
                                             ("child", "2", "")):
                info = root / f"{name}-{version}.dist-info"
                info.mkdir()
                (info / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n{requires}")
            path = root / "constraints.txt"
            valid = "pictologics==0.6.1\nparent==1.0\nchild==2\n"
            path.write_text(valid)
            self.assertEqual(runtime_check.check(root, path, Requirement("pictologics==0.6.1")), 3)
            for content in (valid.replace("child==2\n", ""), valid.replace("parent==1.0", "parent==2.0")):
                path.write_text(content)
                with self.assertRaises(ValueError):
                    runtime_check.check(root, path, Requirement("pictologics==0.6.1"))
            path.write_text(valid)
            (root / "parent-1.0.dist-info/METADATA").write_text("Name: parent\nVersion: 1.0\nRequires-Dist: child==3\n")
            with self.assertRaisesRegex(ValueError, "Unsatisfied dependency"):
                runtime_check.check(root, path, Requirement("pictologics==0.6.1"))


if __name__ == "__main__":
    unittest.main()
