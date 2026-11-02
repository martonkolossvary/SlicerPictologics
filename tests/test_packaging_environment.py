"""Portable contract tests; mocked SDKs are NOT real build/install acceptance."""

from __future__ import annotations

import contextlib
import copy
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
with patch.dict(sys.modules):
    for name in ("check_extension_package", "package_extension"):
        spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    packaging = module


class PackagingEnvironmentTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.sdk = self.root / "sdk"
        self.sdk.mkdir()
        self.tools = self.root / "tools"
        self.tools.mkdir()
        self.source = self.root / "slicer-source"
        self.source.mkdir()
        self.system = patch.object(packaging.platform, "system", return_value="Darwin")
        self.system.start()
        self.addCleanup(self.system.stop)
        self.home = patch.object(Path, "home", return_value=self.root / "home")
        self.home.start()
        self.addCleanup(self.home.stop)
        self.env = patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.lock = packaging.read_lock(packaging.DEFAULT_LOCK)
        self.config = {
            "Slicer_WC_REVISION_HASH": self.lock["slicer_revision"], "Slicer_OS": "macosx",
            "Slicer_ARCHITECTURE": "amd64", "Slicer_REVISION": self.lock["slicer_revision"],
            "Slicer_WC_ROOT": "https://github.com/Slicer/Slicer.git",
            "Slicer_LAUNCHER_EXECUTABLE": str(self.sdk / "Slicer"),
        }
        self.cache = {
            "CMAKE_HOME_DIRECTORY": str(self.source), "CMAKE_BUILD_TYPE": "Release",
            "CMAKE_GENERATOR": "Unix Makefiles", "CMAKE_C_COMPILER": str(self.tools / "cc"),
            "CMAKE_CXX_COMPILER": str(self.tools / "c++"), "CMAKE_MAKE_PROGRAM": str(self.tools / "make"),
            "PYTHON_EXECUTABLE": str(self.sdk / "python"), "CMAKE_OSX_ARCHITECTURES": "x86_64",
            "CMAKE_OSX_DEPLOYMENT_TARGET": "14.0", "CMAKE_OSX_SYSROOT": str(self.root / "sysroot"),
        }
        (self.root / "sysroot").mkdir()
        for file in (self.sdk / "Slicer", self.sdk / "python", self.tools / "cc", self.tools / "c++", self.tools / "make"):
            file.write_text("Synthetic metadata fixture, not an executable")
        self.write_metadata()
        self.mock_capture = patch.object(packaging, "capture", side_effect=self.capture)
        self.mock_capture.start()
        self.addCleanup(self.mock_capture.stop)

    def write_metadata(self):
        (self.sdk / "SlicerConfig.cmake").write_text("\n".join(f'set({k} "{v}")' for k, v in self.config.items()))
        (self.sdk / "CMakeCache.txt").write_text("\n".join(f"{k}:STRING={v}" for k, v in self.cache.items()))
        (self.sdk / "vtkSlicerVersionConfigure.h").write_text('#define Slicer_VERSION_FULL "5.12.4"\n')

    def capture(self, command, **kwargs):
        if command[0] == "git":
            if command[-1] == "HEAD":
                return self.lock["slicer_commit"]
            if command[-1] == "--is-shallow-repository":
                return "false"
            return ""
        name = Path(command[0]).name
        if name in {"cmake", "ctest", "cpack"}:
            if "--show-only=json-v1" in command:
                return json.dumps({"tests": [{"name": "py_PictologicsSlicerIntegrationTest"}]})
            return f"{name} version {self.lock['cmake_version']}\n"
        if name == "Slicer":
            return 'PICTOLOGICS_SDK=' + json.dumps({"version": "5.12.4", "python": "3.12.10",
                                                   "qt": "5.15.18", "architecture": "x86_64", "revision": self.lock["slicer_revision"]})
        return "fixture compiler 1.0"

    def inspect(self):
        return packaging.preflight(self.sdk, self.tools, self.lock)

    def test_valid_metadata_preflight_is_read_only_and_uses_local_source(self):
        before = set(self.root.rglob("*"))
        report = self.inspect()
        self.assertEqual(set(self.root.rglob("*")), before)
        self.assertEqual(report["lock"]["slicer_commit"], self.lock["slicer_commit"])
        self.assertEqual(len(report["executable_hashes"]), 5)

    def test_missing_sdk_and_wrong_revision_architecture_os_version_fail(self):
        for key, value in (("Slicer_WC_REVISION_HASH", "a" * 40), ("Slicer_ARCHITECTURE", "arm64"),
                           ("Slicer_OS", "linux")):
            with self.subTest(key=key), patch.dict(self.config, {key: value}):
                self.write_metadata()
                with self.assertRaisesRegex(ValueError, "mismatch"):
                    self.inspect()
        self.write_metadata()
        (self.sdk / "vtkSlicerVersionConfigure.h").write_text('#define Slicer_VERSION_FULL "5.13.0"')
        with self.assertRaisesRegex(ValueError, "version header"):
            self.inspect()
        with self.assertRaisesRegex(ValueError, "not an SDK"):
            packaging.preflight(self.root, self.tools, self.lock)

    def test_wrong_cache_settings_fail(self):
        for key, value in (("CMAKE_BUILD_TYPE", "Debug"), ("CMAKE_GENERATOR", "Ninja"),
                           ("CMAKE_OSX_ARCHITECTURES", "arm64"), ("CMAKE_OSX_SYSROOT", "/missing"),
                           ("Slicer_FORCED_REVISION", "12345"), ("PYTHON_EXECUTABLE", ""),
                           ("CMAKE_HOME_DIRECTORY", ""), ("CMAKE_OSX_DEPLOYMENT_TARGET", "")):
            with self.subTest(key=key), patch.dict(self.cache, {key: value}):
                self.write_metadata()
                with self.assertRaises(ValueError):
                    self.inspect()

    def test_dirty_shallow_or_moved_sdk_source_and_wrong_tools_fail(self):
        for fail in ("HEAD", "--untracked-files=no", "--is-shallow-repository", "cmake"):
            def altered(command, fail=fail, **kwargs):
                if command[-1] == fail or Path(command[0]).name == fail:
                    return "wrong"
                return self.capture(command, **kwargs)
            with self.subTest(fail=fail), patch.object(packaging, "capture", side_effect=altered), self.assertRaises(ValueError):
                self.inspect()

    def test_overrides_rejected_secrets_and_python_paths_not_forwarded(self):
        for key in ("PICTOLOGICS_DEV_SOURCE", "Slicer_REVISION"):
            with patch.dict(os.environ, {key: "override"}), self.assertRaisesRegex(ValueError, "Unset"):
                self.inspect()
        with patch.dict(os.environ, {"PYTHONPATH": "bad", "PYTHONHOME": "bad", "SLICER_PACKAGE_MANAGER_API_KEY": "secret", "DISPLAY": ":9"}):
            self.assertEqual(packaging.clean_environment(), {"DISPLAY": ":9"})

    def test_runtime_identity_rejects_wrong_python_qt_arch_and_revision(self):
        sdk = self.inspect()
        self.assertEqual(packaging.runtime_check(sdk, {})["version"], "5.12.4")
        runtime = json.loads(self.capture(["Slicer"]).split("=", 1)[1])
        for key in runtime:
            with self.subTest(key=key), patch.object(packaging, "capture", return_value="PICTOLOGICS_SDK=" + json.dumps({**runtime, key: "wrong"})), self.assertRaises(ValueError):
                packaging.runtime_check(sdk, {})

    def test_environment_reuse_and_drift_rejection(self):
        sdk = self.inspect()
        work = self.root / "packaging"
        packaging.seal_environment(work, sdk, ROOT)
        packaging.seal_environment(work, sdk, ROOT)
        changed = copy.deepcopy(sdk)
        changed["tool_versions"]["c_compiler"] = "new compiler"
        with self.assertRaisesRegex(ValueError, "drift"):
            packaging.seal_environment(work, changed, ROOT)
        for unsafe in (self.sdk, self.sdk / "nested", ROOT, ROOT / "nested", Path.home()):
            with self.subTest(path=unsafe), self.assertRaises(ValueError):
                packaging.seal_environment(unsafe, sdk, ROOT)
        unowned = self.root / "unowned"
        unowned.mkdir()
        (unowned / "user-file").write_text("keep")
        with self.assertRaisesRegex(ValueError, "Unowned"):
            packaging.seal_environment(unowned, sdk, ROOT)
        self.assertEqual((unowned / "user-file").read_text(), "keep")

    def test_manifest_tracks_runtime_tests_and_lock_but_not_bytecode(self):
        manifest = packaging.source_manifest(ROOT)
        for name in ("scripts/package_extension.py", "packaging/slicer-5.12.4.json", "tests/test_packaging_environment.py", "PictologicsSlicer/PictologicsLib/persistence.py"):
            self.assertIn(name, manifest)
        self.assertFalse(any("__pycache__" in p or "dev/" in p for p in manifest))

    def fake_step(self, name, command, run, env, report):
        report["steps"].append({"name": name, "command": command})
        if name == "ctest":
            self.assertEqual(env["SLICERPICTOLOGICS_RUN_REAL_CLI_TEST"], "1")
        if name == "cpack":
            (run / "artifacts").mkdir()
            (run / "artifacts/fixture.tar.gz").write_bytes(b"not an installable archive")

    def test_pipeline_order_fresh_attempts_and_no_upload(self):
        sdk = self.inspect()
        with patch.object(packaging, "run_step", side_effect=self.fake_step), patch.object(packaging, "audit_package", return_value={"success": True}), contextlib.redirect_stdout(io.StringIO()):
            one = packaging.build(ROOT, self.root / "work", sdk, 2)
            two = packaging.build(ROOT, self.root / "work", sdk, 2)
        self.assertTrue(one["success"], one)
        self.assertTrue(two["success"], two)
        self.assertNotEqual(one["run"], two["run"])
        self.assertEqual([s["name"] for s in one["steps"]], ["configure", "build", "dependencies", "ctest", "cpack"])
        self.assertIn("NOT packaged-install", one["scope"])
        self.assertIn("-DSlicer_UPLOAD_EXTENSIONS:BOOL=OFF", one["steps"][0]["command"])
        self.assertFalse(any("Experimental" in word or "upload" in word for s in one["steps"] for word in s["command"]))
        self.assertTrue((Path(one["run"]) / "report.json").is_file())

    def test_failure_stops_before_packaging_and_keeps_report(self):
        sdk = self.inspect()
        def fail(name, command, run, env, report):
            self.fake_step(name, command, run, env, report)
            if name == "ctest":
                raise ValueError("intentional CTest failure")
        with patch.object(packaging, "run_step", side_effect=fail), contextlib.redirect_stdout(io.StringIO()):
            report = packaging.build(ROOT, self.root / "work", sdk, 2)
        self.assertFalse(report["success"])
        self.assertNotIn("cpack", [s["name"] for s in report["steps"]])
        self.assertTrue((Path(report["run"]) / "report.json").is_file())

    def test_no_tests_audit_failure_or_changed_source_cannot_pass(self):
        sdk = self.inspect()
        original_manifest = packaging.source_manifest(ROOT)
        for cause in ("no_tests", "audit", "source"):
            with self.subTest(cause=cause), contextlib.ExitStack() as stack:
                stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                stack.enter_context(patch.object(packaging, "run_step", side_effect=self.fake_step))
                stack.enter_context(patch.object(packaging, "audit_package", return_value={"success": cause != "audit"}))
                if cause == "no_tests":
                    def no_tests(command, **kwargs):
                        return '{"tests":[]}' if "--show-only=json-v1" in command else self.capture(command, **kwargs)
                    stack.enter_context(patch.object(packaging, "capture", side_effect=no_tests))
                if cause == "source":
                    stack.enter_context(patch.object(packaging, "source_manifest", side_effect=[original_manifest, {}]))
                report = packaging.build(ROOT, self.root / cause, sdk, 2)
                self.assertFalse(report["success"], report)

    def test_subprocess_failure_is_logged(self):
        report = {"steps": []}
        with patch.object(packaging.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)), contextlib.redirect_stdout(io.StringIO()), self.assertRaisesRegex(ValueError, "failed"):
            packaging.run_step("failed", ["not-executed"], self.root, {}, report)
        self.assertEqual(report["steps"][0]["returncode"], 1)

    def test_invalid_lock_and_cli_arguments(self):
        for value in ({"schema": 9}, {**self.lock, "cmake_version": "latest"}):
            path = self.root / "bad.json"
            path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):
                packaging.read_lock(path)
        for args in (["build", "--slicer-dir", str(self.sdk)], ["check", "--slicer-dir", str(self.sdk), "--jobs", "0"]):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(packaging.main(args), 1)

    def test_tools_command_needs_no_sdk_and_pins_match_requirements(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(packaging.main(["tools", "--tools-dir", str(self.tools)]), 0)
        report = json.loads(output.getvalue())
        self.assertIn("SDK NOT tested", report["scope"])
        requirements = (ROOT / "packaging/requirements-tools.txt").read_text()
        self.assertIn(f"cmake=={self.lock['cmake_version']}", requirements)
        self.assertEqual(requirements.count("--hash=sha256:"), 3)

    def test_archive_errors_and_missing_fresh_artifacts_keep_failure_report(self):
        sdk = self.inspect()
        for cause in ("invalid_archive", "no_archive"):
            def step(name, command, run, env, report, cause=cause):
                self.fake_step(name, command, run, env, report)
                if name == "cpack" and cause == "no_archive":
                    (run / "artifacts/fixture.tar.gz").rename(run / "artifacts/not-an-archive.txt")
            with self.subTest(cause=cause), patch.object(packaging, "run_step", side_effect=step), patch.object(packaging, "audit_package", side_effect=packaging.tarfile.ReadError("invalid archive")), contextlib.redirect_stdout(io.StringIO()):
                report = packaging.build(ROOT, self.root / cause, sdk, 2)
            self.assertFalse(report["success"])
            self.assertTrue(report["errors"])
            self.assertEqual(json.loads((Path(report["run"]) / "report.json").read_text()), report)


if __name__ == "__main__":
    unittest.main()
