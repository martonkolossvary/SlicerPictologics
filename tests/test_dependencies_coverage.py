"""Standalone statement-coverage tests for ``PictologicsLib.dependencies``.

This module is self-contained: on its own it drives every branch in
``dependencies.py``, concentrating on requirement parsing, target inspection, the
pip argument builder, and the atomic active-environment pointer logic.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from packaging.requirements import Requirement

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "PictologicsSlicer"))

from PictologicsLib import dependencies
from PictologicsLib.dependencies import (
    ACTIVE_ENVIRONMENT_POINTER,
    PICTOLOGICS_DEV_SOURCE_ENV,
    DependencyConfigurationError,
    TargetInspection,
    _fsync_parent_dir,
    _local_development_source,
    _read_active_dependency_target,
    _validated_environment_target,
    activate_dependency_target,
    build_pip_install_args,
    dependency_environment_path,
    dependency_paths,
    ensure_dependency_paths,
    inspect_target,
    parse_pictologics_requirement,
)


def _write_distribution(target: Path, version: str, *, name: str = "pictologics") -> None:
    dist_info = target / f"{name}-{version}.dist-info"
    dist_info.mkdir(parents=True)
    (dist_info / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
        encoding="utf-8",
    )


class RequirementParsingTests(unittest.TestCase):
    def _parse(self, contents: str) -> Requirement:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "requirements.txt")
            path.write_text(contents, encoding="utf-8")
            return parse_pictologics_requirement(path)

    def test_valid_requirement_with_comments_and_blank_lines(self) -> None:
        requirement = self._parse(
            "# leading comment\n"
            "\n"
            "pictologics==0.5.0  # inline comment after whitespace\n"
        )
        self.assertEqual(requirement.name, "pictologics")
        self.assertEqual(str(requirement.specifier), "==0.5.0")

    def test_missing_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(DependencyConfigurationError, "Unable to read"):
                parse_pictologics_requirement(Path(directory, "absent.txt"))

    def test_rejects_line_level_problems(self) -> None:
        cases = {
            "zero": "# only a comment\n",
            "multiple": "pictologics==0.5.0\nnumpy==2.0.0\n",
            "pip-option": "-r other.txt\n",
            "continuation": "pictologics==0.5.0 \\\n",
            "invalid-requirement": "==1.0\n",
        }
        for label, contents in cases.items():
            with self.subTest(label=label):
                with self.assertRaises(DependencyConfigurationError):
                    self._parse(contents)

    def test_rejects_non_adopted_requirement_forms(self) -> None:
        cases = {
            "wrong-name": "not-pictologics==0.5.0\n",
            "url": "pictologics @ https://example.invalid/pictologics.whl\n",
            "no-specifier": "pictologics\n",
            "range": "pictologics>=0.5.0\n",
            "prerelease": "pictologics==0.6.0rc1\n",
            "devrelease": "pictologics==0.5.0.dev1\n",
            "postrelease": "pictologics==0.5.0.post1\n",
            "local": "pictologics==0.5.0+local\n",
            "epoch": "pictologics==1!0.5.0\n",
            "leading-zero": "pictologics==00.5.0\n",
            "two-part": "pictologics==0.5\n",
            "extras": "pictologics[extra]==0.5.0\n",
            "marker": "pictologics==0.5.0; python_version >= '3.12'\n",
        }
        for label, contents in cases.items():
            with self.subTest(label=label):
                with self.assertRaises(DependencyConfigurationError):
                    self._parse(contents)


class TargetInspectionTests(unittest.TestCase):
    def test_missing_target_directory_is_unsatisfied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            inspection = inspect_target(
                Path(directory, "absent"), Requirement("pictologics==0.5.0")
            )
        self.assertFalse(inspection.installed)
        self.assertFalse(inspection.satisfied)
        self.assertIsNone(inspection.installed_version)
        self.assertEqual(inspection.installed_versions, ())

    def test_single_matching_distribution_is_satisfied(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            _write_distribution(target, "0.5.0")
            inspection = inspect_target(target, Requirement("pictologics==0.5.0"))
        self.assertTrue(inspection.installed)
        self.assertFalse(inspection.ambiguous)
        self.assertTrue(inspection.satisfied)
        self.assertEqual(inspection.installed_version, "0.5.0")

    def test_wrong_version_and_foreign_distributions_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            _write_distribution(target, "0.4.0")
            _write_distribution(target, "9.9.9", name="unrelated")
            inspection = inspect_target(target, Requirement("pictologics==0.5.0"))
        self.assertEqual(inspection.installed_version, "0.4.0")
        self.assertEqual(inspection.installed_versions, ("0.4.0",))
        self.assertFalse(inspection.satisfied)

    def test_multiple_versions_are_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            _write_distribution(target, "0.5.0")
            _write_distribution(target, "0.5.1")
            inspection = inspect_target(target, Requirement("pictologics>=0.5"))
        self.assertTrue(inspection.ambiguous)
        self.assertEqual(inspection.installed_version, "0.5.1")
        self.assertFalse(inspection.satisfied)

    def test_prerelease_not_adopted_by_stable_specifier(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            _write_distribution(target, "0.6.0rc1")
            inspection = inspect_target(target, Requirement("pictologics>=0.5"))
        self.assertFalse(inspection.satisfied)

    def test_unparsable_version_sorts_and_never_satisfies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            _write_distribution(target, "not-a-version")
            inspection = inspect_target(target, Requirement("pictologics==0.5.0"))
        self.assertTrue(inspection.installed)
        self.assertEqual(inspection.installed_version, "not-a-version")
        self.assertFalse(inspection.satisfied)

    def test_direct_reference_requirement_matches_any_metadata_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            _write_distribution(target, "0.5.0")
            inspection = inspect_target(
                target, Requirement("pictologics @ file:///tmp/pictologics")
            )
        self.assertTrue(inspection.satisfied)

    def test_distribution_metadata_errors_are_skipped(self) -> None:
        class _BadDistribution:
            @property
            def metadata(self):
                raise UnicodeError("undecodable metadata")

            @property
            def version(self):  # pragma: no cover - never reached
                return "1.0"

        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            with mock.patch.object(
                dependencies.metadata,
                "distributions",
                return_value=iter([_BadDistribution()]),
            ):
                inspection = inspect_target(target, Requirement("pictologics==0.5.0"))
        self.assertFalse(inspection.installed)
        self.assertFalse(inspection.satisfied)


class LocalDevelopmentSourceTests(unittest.TestCase):
    def test_valid_directory_and_file_sources(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(_local_development_source(root), root.resolve())
            artifact = root / "pictologics-0.5.0-py3-none-any.whl"
            artifact.write_bytes(b"wheel")
            self.assertEqual(_local_development_source(artifact), artifact.resolve())

    def test_rejection_paths(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fifo = root / "pipe"
            os.mkfifo(fifo)
            cases = [
                ("empty", "   "),
                ("null-byte", "some\x00path"),
                ("option-injection", "--target"),
                ("url", "https://example.invalid/pictologics"),
                ("vcs", "git+https://example.invalid/pictologics.git"),
                ("missing", str(root / "does-not-exist")),
                ("special-file", str(fifo)),
            ]
            for label, value in cases:
                with self.subTest(label=label):
                    with self.assertRaises(DependencyConfigurationError):
                        _local_development_source(value)


class PipArgumentTests(unittest.TestCase):
    def test_pypi_install_is_wheel_only_and_optionally_upgraded(self) -> None:
        with (
            tempfile.TemporaryDirectory() as directory,
            mock.patch.dict(os.environ, {}, clear=True),
        ):
            target = Path(directory, "target")
            args = build_pip_install_args(
                Requirement("pictologics==0.5.0"), target, force_upgrade=True
            )
        self.assertEqual(args[:1], ["--target"])
        self.assertIn(str(target.resolve()), args)
        self.assertIn("--upgrade", args)
        self.assertIn("--ignore-installed", args)
        self.assertIn("--no-warn-script-location", args)
        self.assertIn("--only-binary=:all:", args)
        self.assertEqual(args[-1], "pictologics==0.5.0")

    def test_explicit_dev_source_omits_wheel_constraint(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "checkout"
            source.mkdir()
            with mock.patch.dict(os.environ, {}, clear=True):
                args = build_pip_install_args(
                    Requirement("pictologics==0.5.0"), root / "target", dev_source=source
                )
        self.assertNotIn("--only-binary=:all:", args)
        self.assertEqual(args[-1], str(source.resolve()))

    def test_environment_variable_dev_source_is_used(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "env-checkout"
            source.mkdir()
            with mock.patch.dict(
                os.environ, {PICTOLOGICS_DEV_SOURCE_ENV: str(source)}, clear=True
            ):
                args = build_pip_install_args(
                    Requirement("pictologics==0.5.0"), root / "target"
                )
        self.assertEqual(args[-1], str(source.resolve()))

    def test_rejects_wrong_name_and_url_requirements(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory, "target")
            with self.assertRaisesRegex(DependencyConfigurationError, "Expected"):
                build_pip_install_args(Requirement("numpy==1.0.0"), target)
            with self.assertRaisesRegex(
                DependencyConfigurationError, "direct-reference"
            ):
                build_pip_install_args(
                    Requirement("pictologics @ file:///tmp/pictologics"), target
                )


class CacheLayoutTests(unittest.TestCase):
    def test_legacy_fallback_and_directory_creation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, "cache")
            paths = dependency_paths(root)
            expected = root.resolve()
            self.assertEqual(paths["cache_root"], expected)
            self.assertEqual(paths["environments_root"], expected / "environments")
            self.assertEqual(
                paths["active_pointer"], expected / ACTIVE_ENVIRONMENT_POINTER
            )
            self.assertEqual(paths["jobs_root"], expected / "jobs")
            self.assertEqual(paths["numba_cache"], expected / "numba-cache")
            self.assertEqual(
                paths["legacy_dependency_target"], expected / "python-packages"
            )
            self.assertEqual(
                paths["dependency_target"], paths["legacy_dependency_target"]
            )

            created = ensure_dependency_paths(root)
            for key in (
                "cache_root",
                "environments_root",
                "jobs_root",
                "numba_cache",
                "dependency_target",
            ):
                self.assertTrue(created[key].is_dir())
            self.assertFalse(created["active_pointer"].exists())

    def test_environment_path_versioned_and_invalid_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, "cache")
            target = dependency_environment_path(root, "v0.5.0")
            self.assertEqual(
                target, root.resolve() / "environments" / "pictologics-0.5.0"
            )
            with self.assertRaisesRegex(
                DependencyConfigurationError, "Invalid Pictologics environment version"
            ):
                dependency_environment_path(root, "../../outside")

    def test_validated_environment_target_resolution_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            environments_root = Path(directory, "environments")
            with self.assertRaisesRegex(
                DependencyConfigurationError, "Unable to resolve"
            ):
                _validated_environment_target(
                    environments_root, "bad\x00target", must_exist=False
                )

    def test_symlinked_environments_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary_root = Path(directory)
            root = temporary_root / "cache"
            root.mkdir()
            outside = temporary_root / "outside"
            outside.mkdir()
            try:
                (root / "environments").symlink_to(outside, target_is_directory=True)
            except OSError as exc:  # pragma: no cover - platform permission policy
                self.skipTest(f"Symbolic links are unavailable: {exc}")
            with self.assertRaisesRegex(
                DependencyConfigurationError, "must not be a symlink"
            ):
                dependency_environment_path(root, "0.5.0")


class ActivationTests(unittest.TestCase):
    def test_activation_and_pointer_round_trip(self) -> None:
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
            self.assertEqual(
                list(root.resolve().glob(".active-environment-*.tmp")), []
            )

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

    def test_activation_replace_failure_cleans_up_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, "cache")
            target = dependency_environment_path(root, "0.5.0")
            target.mkdir(parents=True)
            with (
                mock.patch(
                    "PictologicsLib.dependencies.os.replace",
                    side_effect=OSError("simulated"),
                ),
                self.assertRaises(DependencyConfigurationError),
            ):
                activate_dependency_target(root, target)
            self.assertEqual(
                list(root.resolve().glob(".active-environment-*.tmp")), []
            )

    def test_activation_replace_and_cleanup_both_fail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, "cache")
            target = dependency_environment_path(root, "0.5.0")
            target.mkdir(parents=True)
            with (
                mock.patch(
                    "PictologicsLib.dependencies.os.replace",
                    side_effect=OSError("simulated"),
                ),
                mock.patch(
                    "PictologicsLib.dependencies.Path.unlink",
                    side_effect=FileNotFoundError("already gone"),
                ),
                self.assertRaises(DependencyConfigurationError),
            ):
                activate_dependency_target(root, target)


class ActivePointerReadTests(unittest.TestCase):
    def test_absent_pointer_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, "cache")
            environments_root = root / "environments"
            environments_root.mkdir(parents=True)
            self.assertIsNone(
                _read_active_dependency_target(
                    root / ACTIVE_ENVIRONMENT_POINTER, environments_root
                )
            )

    def test_pointer_directory_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, "cache")
            environments_root = root / "environments"
            environments_root.mkdir(parents=True)
            pointer = root / ACTIVE_ENVIRONMENT_POINTER
            pointer.mkdir()
            with self.assertRaisesRegex(
                DependencyConfigurationError, "not a regular file"
            ):
                _read_active_dependency_target(pointer, environments_root)

    def test_non_utf8_pointer_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, "cache")
            root.mkdir()
            (root / ACTIVE_ENVIRONMENT_POINTER).write_bytes(b"\xff\xfe invalid")
            with self.assertRaisesRegex(DependencyConfigurationError, "Unable to read"):
                dependency_paths(root)

    def test_malformed_and_unsafe_pointer_contents_never_fall_back(self) -> None:
        malformed = (
            "../outside\n",
            "/absolute/outside\n",
            "missing\n",
            "two\nlines\n",
            " surrounded \n",
            "\n",
        )
        for pointer_text in malformed:
            with (
                self.subTest(pointer_text=pointer_text),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory, "cache")
                root.mkdir()
                (root / ACTIVE_ENVIRONMENT_POINTER).write_text(
                    pointer_text, encoding="utf-8"
                )
                with self.assertRaises(DependencyConfigurationError):
                    dependency_paths(root)

    def test_pointer_that_cannot_become_a_path_is_malformed(self) -> None:
        # ``Path(lines[0])`` only raises for pathological inputs; force that defensive
        # branch by making the Path constructor itself fail on the pointer value.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory, "cache")
            environments_root = root / "environments"
            environments_root.mkdir(parents=True)
            pointer = root / ACTIVE_ENVIRONMENT_POINTER
            pointer.write_text("pictologics-0.5.0\n", encoding="utf-8")
            with mock.patch(
                "PictologicsLib.dependencies.Path", side_effect=ValueError("boom")
            ):
                with self.assertRaisesRegex(
                    DependencyConfigurationError, "malformed"
                ):
                    _read_active_dependency_target(pointer, environments_root)


class FsyncParentDirTests(unittest.TestCase):
    def test_all_branches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "file.txt")
            path.write_text("x", encoding="utf-8")
            _fsync_parent_dir(path)
            with mock.patch(
                "PictologicsLib.dependencies.os.open", side_effect=OSError
            ):
                _fsync_parent_dir(path)
            with mock.patch(
                "PictologicsLib.dependencies.os.fsync", side_effect=OSError
            ):
                _fsync_parent_dir(path)


class TargetInspectionDataclassTests(unittest.TestCase):
    def test_properties(self) -> None:
        requirement = Requirement("pictologics==0.5.0")
        none = TargetInspection(Path("/tmp"), requirement, None, (), False)
        self.assertFalse(none.installed)
        self.assertFalse(none.ambiguous)
        one = TargetInspection(Path("/tmp"), requirement, "0.5.0", ("0.5.0",), True)
        self.assertTrue(one.installed)
        self.assertFalse(one.ambiguous)
        many = TargetInspection(
            Path("/tmp"), requirement, "0.5.1", ("0.5.0", "0.5.1"), False
        )
        self.assertTrue(many.installed)
        self.assertTrue(many.ambiguous)


if __name__ == "__main__":
    unittest.main()
