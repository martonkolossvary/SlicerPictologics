from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from packaging.requirements import Requirement

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "PictologicsSlicer"))

from PictologicsLib.dependencies import (
    DependencyConfigurationError,
    activate_dependency_target,
    build_pip_install_args,
    dependency_environment_path,
    dependency_paths,
    ensure_dependency_paths,
    inspect_target,
    parse_pictologics_requirement,
)


class RequirementParsingTests(unittest.TestCase):
    def test_parses_one_direct_pictologics_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "requirements.txt")
            path.write_text(
                "# adopted after compatibility testing\n"
                "pictologics==0.5.0\t# exact wrapper pin\n",
                encoding="utf-8",
            )

            requirement = parse_pictologics_requirement(path)

        self.assertEqual(requirement.name, "pictologics")
        self.assertEqual(str(requirement.specifier), "==0.5.0")

    def test_rejects_zero_or_multiple_direct_requirements(self) -> None:
        cases = ("# none\n", "pictologics==0.5\nnumpy==2\n")
        for contents in cases:
            with (
                self.subTest(contents=contents),
                tempfile.TemporaryDirectory() as directory,
            ):
                path = Path(directory, "requirements.txt")
                path.write_text(contents, encoding="utf-8")
                with self.assertRaises(DependencyConfigurationError):
                    parse_pictologics_requirement(path)

    def test_rejects_wrong_distribution_and_pip_options(self) -> None:
        cases = (
            "not-pictologics==0.5.0\n",
            "-r other.txt\n",
            "pictologics @ https://example.invalid/pictologics.whl\n",
            "pictologics>=0.5.0\n",
            "pictologics==0.6.0rc1\n",
            "pictologics==1!0.5.0\n",
            "pictologics==00.5.0\n",
            "pictologics[extra]==0.5.0\n",
            "pictologics==0.5.0; python_version >= '3.12'\n",
        )
        for contents in cases:
            with (
                self.subTest(contents=contents),
                tempfile.TemporaryDirectory() as directory,
            ):
                path = Path(directory, "requirements.txt")
                path.write_text(contents, encoding="utf-8")
                with self.assertRaises(DependencyConfigurationError):
                    parse_pictologics_requirement(path)


class TargetInspectionTests(unittest.TestCase):
    @staticmethod
    def _write_distribution(target: Path, version: str) -> None:
        dist_info = target / f"pictologics-{version}.dist-info"
        dist_info.mkdir()
        (dist_info / "METADATA").write_text(
            f"Metadata-Version: 2.1\nName: pictologics\nVersion: {version}\n",
            encoding="utf-8",
        )

    def test_inspects_only_requested_target_and_checks_specifier(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._write_distribution(target, "0.5.0")

            inspection = inspect_target(target, Requirement("pictologics>=0.5,<0.6"))

        self.assertTrue(inspection.installed)
        self.assertTrue(inspection.satisfied)
        self.assertEqual(inspection.installed_version, "0.5.0")
        self.assertEqual(inspection.installed_versions, ("0.5.0",))

    def test_missing_or_wrong_version_is_unsatisfied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            missing = inspect_target(target, Requirement("pictologics==0.5.0"))
            self._write_distribution(target, "0.4.9")
            wrong = inspect_target(target, Requirement("pictologics==0.5.0"))

        self.assertIsNone(missing.installed_version)
        self.assertFalse(missing.satisfied)
        self.assertEqual(wrong.installed_version, "0.4.9")
        self.assertFalse(wrong.satisfied)

    def test_broad_stable_requirement_does_not_adopt_a_prerelease(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._write_distribution(target, "0.6.0rc1")

            inspection = inspect_target(target, Requirement("pictologics>=0.5"))

        self.assertFalse(inspection.satisfied)

    def test_duplicate_metadata_is_ambiguous_and_unsatisfied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._write_distribution(target, "0.5.0")
            self._write_distribution(target, "0.5.1")

            inspection = inspect_target(target, Requirement("pictologics>=0.5"))

        self.assertTrue(inspection.ambiguous)
        self.assertEqual(inspection.installed_version, "0.5.1")
        self.assertFalse(inspection.satisfied)

    def test_duplicate_metadata_for_same_version_is_also_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self._write_distribution(target, "0.5.0")
            duplicate = target / "alternate-0.5.0.dist-info"
            duplicate.mkdir()
            (duplicate / "METADATA").write_text(
                "Metadata-Version: 2.1\nName: pictologics\nVersion: 0.5.0\n",
                encoding="utf-8",
            )

            inspection = inspect_target(target, Requirement("pictologics==0.5.0"))

        self.assertEqual(inspection.installed_versions, ("0.5.0", "0.5.0"))
        self.assertTrue(inspection.ambiguous)
        self.assertFalse(inspection.satisfied)


class PipArgumentTests(unittest.TestCase):
    def test_pypi_install_is_isolated_wheel_only_and_optionally_upgraded(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.dict(os.environ, {}, clear=True),
        ):
            target = Path(directory, "target")
            args = build_pip_install_args(
                Requirement("pictologics>=0.5"), target, force_upgrade=True
            )

        self.assertIn("--target", args)
        self.assertIn(str(target.resolve()), args)
        self.assertIn("--upgrade", args)
        self.assertIn("--ignore-installed", args)
        self.assertIn("--no-warn-script-location", args)
        self.assertIn("--only-binary=:all:", args)
        self.assertEqual(args[-1], "pictologics>=0.5")

    def test_local_development_override_omits_binary_constraint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "Pictologics"
            source.mkdir()
            with mock.patch.dict(
                os.environ, {"PICTOLOGICS_DEV_SOURCE": str(source)}, clear=True
            ):
                args = build_pip_install_args(
                    Requirement("pictologics==0.5.0"), root / "target"
                )

        self.assertNotIn("--only-binary=:all:", args)
        self.assertEqual(args[-1], str(source.resolve()))
        self.assertNotIn("pictologics==0.5.0", args)

    def test_development_override_must_be_an_existing_local_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(DependencyConfigurationError):
                build_pip_install_args(
                    Requirement("pictologics"),
                    Path(directory, "target"),
                    dev_source="https://example.invalid/Pictologics",
                )

    def test_dependency_path_helpers_use_legacy_fallback_without_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, "cache")
            paths = dependency_paths(root)
            expected_root = root.resolve()
            self.assertEqual(paths["cache_root"], expected_root)
            self.assertEqual(paths["environments_root"], expected_root / "environments")
            self.assertEqual(
                paths["active_pointer"], expected_root / "active-environment"
            )
            self.assertEqual(paths["jobs_root"], expected_root / "jobs")
            self.assertEqual(paths["numba_cache"], root.resolve() / "numba-cache")
            self.assertEqual(
                paths["legacy_dependency_target"], expected_root / "python-packages"
            )
            self.assertEqual(
                paths["dependency_target"], paths["legacy_dependency_target"]
            )
            self.assertFalse(paths["dependency_target"].exists())

            created = ensure_dependency_paths(root)
            self.assertTrue(created["cache_root"].is_dir())
            self.assertTrue(created["environments_root"].is_dir())
            self.assertTrue(created["jobs_root"].is_dir())
            self.assertTrue(created["dependency_target"].is_dir())
            self.assertTrue(created["numba_cache"].is_dir())
            self.assertFalse(created["active_pointer"].exists())

    def test_environment_path_is_versioned_and_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, "cache")

            target = dependency_environment_path(root, "v0.5.0")

        self.assertEqual(
            target,
            root.resolve() / "environments" / "pictologics-0.5.0",
        )

    def test_environment_path_rejects_invalid_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(DependencyConfigurationError):
                dependency_environment_path(directory, "../../outside")

    def test_atomic_activation_selects_versioned_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, "cache")
            target = dependency_environment_path(root, "0.5.0")
            target.mkdir(parents=True)

            activated = activate_dependency_target(root, target)
            paths = dependency_paths(root)

            self.assertEqual(activated, target)
            self.assertEqual(paths["dependency_target"], target)
            self.assertEqual(
                paths["active_pointer"].read_text(encoding="utf-8"),
                "pictologics-0.5.0\n",
            )
            self.assertTrue(paths["active_pointer"].is_file())
            self.assertEqual(list(root.resolve().glob(".active-environment-*.tmp")), [])

    def test_activation_switches_pointer_without_mutating_old_environment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, "cache")
            old_target = dependency_environment_path(root, "0.5.0")
            new_target = dependency_environment_path(root, "0.5.1")
            old_target.mkdir(parents=True)
            new_target.mkdir()
            marker = old_target / "keep.txt"
            marker.write_text("immutable", encoding="utf-8")

            activate_dependency_target(root, old_target)
            activate_dependency_target(root, new_target)

            self.assertEqual(dependency_paths(root)["dependency_target"], new_target)
            self.assertEqual(marker.read_text(encoding="utf-8"), "immutable")
            self.assertTrue(old_target.is_dir())

    def test_activation_rejects_outside_missing_and_root_targets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, "cache")
            paths = ensure_dependency_paths(root)
            outside = root / "outside"
            outside.mkdir()
            missing = paths["environments_root"] / "missing"

            for target in (outside, missing, paths["environments_root"]):
                with (
                    self.subTest(target=target),
                    self.assertRaises(DependencyConfigurationError),
                ):
                    activate_dependency_target(root, target)

            self.assertFalse(paths["active_pointer"].exists())

    def test_present_unsafe_or_dangling_pointer_never_falls_back(self) -> None:
        malformed_values = (
            "../outside\n",
            "/tmp/outside\n",
            "missing\n",
            "two\nlines\n",
            " surrounded \n",
            "bad\x00path\n",
            "\n",
        )
        for pointer_text in malformed_values:
            with (
                self.subTest(pointer_text=pointer_text),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory, "cache")
                root.mkdir()
                (root / "active-environment").write_text(pointer_text, encoding="utf-8")

                with self.assertRaises(DependencyConfigurationError):
                    dependency_paths(root)

    def test_active_pointer_and_environments_root_must_not_be_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary_root = Path(directory)
            root = temporary_root / "cache"
            root.mkdir()
            outside = temporary_root / "outside"
            outside.mkdir()
            pointer_source = temporary_root / "pointer.txt"
            pointer_source.write_text("pictologics-0.5.0\n", encoding="utf-8")
            try:
                (root / "active-environment").symlink_to(pointer_source)
            except OSError as exc:  # pragma: no cover - platform permission policy
                self.skipTest(f"Symbolic links are unavailable: {exc}")

            with self.assertRaises(DependencyConfigurationError):
                dependency_paths(root)

            (root / "active-environment").unlink()
            (root / "environments").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(DependencyConfigurationError):
                dependency_environment_path(root, "0.5.0")

    def test_activation_failure_preserves_old_pointer_and_removes_temporary_file(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, "cache")
            old_target = dependency_environment_path(root, "0.5.0")
            new_target = dependency_environment_path(root, "0.5.1")
            old_target.mkdir(parents=True)
            new_target.mkdir()
            activate_dependency_target(root, old_target)
            pointer = dependency_paths(root)["active_pointer"]
            old_contents = pointer.read_text(encoding="utf-8")

            with (
                mock.patch(
                    "PictologicsLib.dependencies.os.replace",
                    side_effect=OSError("simulated replacement failure"),
                ),
                self.assertRaises(DependencyConfigurationError),
            ):
                activate_dependency_target(root, new_target)

            self.assertEqual(pointer.read_text(encoding="utf-8"), old_contents)
            self.assertEqual(list(root.resolve().glob(".active-environment-*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
