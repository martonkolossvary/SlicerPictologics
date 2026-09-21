from __future__ import annotations

import ast
import importlib.util
import json
import re
import struct
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "PictologicsSlicer"))

from PictologicsLib.jobs import build_job_manifest  # noqa: E402

GUI_SOURCE = ROOT / "PictologicsSlicer/PictologicsSlicer.py"
GUI_CMAKE = ROOT / "PictologicsSlicer/CMakeLists.txt"
GUI_TEST_CMAKE = ROOT / "PictologicsSlicer/Testing/Python/CMakeLists.txt"
GUI_INTEGRATION_TEST = ROOT / "PictologicsSlicer/Testing/Python/PictologicsSlicerIntegrationTest.py"
UI_PATH = ROOT / "PictologicsSlicer/Resources/UI/PictologicsSlicer.ui"
WORKER_SOURCE = ROOT / "PictologicsCLI/PictologicsCLI.py"


def load_worker_module():
    spec = importlib.util.spec_from_file_location("pictologics_cli_contract_test", WORKER_SOURCE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def load_bump_module():
    path = ROOT / "scripts/bump_pictologics_requirement.py"
    spec = importlib.util.spec_from_file_location("pictologics_requirement_bump_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class ExtensionScaffoldTests(unittest.TestCase):
    def test_catalog_identity_matches_cmake_and_workflow(self) -> None:
        catalog_path = ROOT / "Pictologics.json"
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        cmake = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
        project = re.search(r"project\(([^)]+)\)", cmake)
        self.assertIsNotNone(project)
        self.assertEqual(project.group(1), catalog_path.stem)
        self.assertFalse(catalog_path.stem.lower().startswith("slicer"))
        self.assertFalse((ROOT / "SlicerPictologics.json").exists())
        self.assertEqual(catalog["category"], "Informatics")
        self.assertIn('set(EXTENSION_CATEGORY "Informatics")', cmake)
        self.assertEqual(catalog["scm_url"], "https://github.com/martonkolossvary/SlicerPictologics")
        self.assertEqual(catalog["scm_revision"], "main")
        self.assertEqual(catalog["tier"], 1)
        workflow = (ROOT / ".github/workflows/compatibility.yml").read_text(encoding="utf-8")
        self.assertIn(f"python -m json.tool {catalog_path.name}", workflow)
        self.assertNotIn("json.tool SlicerPictologics.json", workflow)

    def test_catalog_and_module_use_approved_png_assets(self) -> None:
        cmake = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
        relative_icon = "assets/branding/pictologics/slicer/Pictologics-128.png"
        self.assertIn(
            'set(EXTENSION_ICONURL "https://raw.githubusercontent.com/'
            f'martonkolossvary/SlicerPictologics/main/{relative_icon}")',
            cmake,
        )
        runtime_icon = ROOT / "PictologicsSlicer/Resources/Icons/PictologicsSlicer.png"
        approved_icon = ROOT / "assets/branding/pictologics/slicer/PictologicsSlicer.png"
        self.assertEqual(runtime_icon.read_bytes(), approved_icon.read_bytes())
        for path, size in ((ROOT / relative_icon, 128), (runtime_icon, 256)):
            with self.subTest(path=path):
                data = path.read_bytes()
                self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
                self.assertEqual(data[12:16], b"IHDR")
                self.assertEqual(struct.unpack(">II", data[16:24]), (size, size))
                self.assertEqual(data[24:26], bytes((8, 6)))  # 8-bit RGBA

    def test_gui_packages_only_the_selected_runtime_icon(self) -> None:
        cmake = GUI_CMAKE.read_text(encoding="utf-8")
        resources = cmake.split("set(MODULE_PYTHON_RESOURCES", 1)[1].split(")", 1)[0]
        self.assertEqual(
            [line.strip() for line in resources.splitlines() if "Icons/" in line],
            ["Resources/Icons/${MODULE_NAME}.png"],
        )
        self.assertNotIn("assets/branding", cmake)
        self.assertNotIn("GLOB", resources)

    def test_gui_never_imports_pictologics(self) -> None:
        tree = ast.parse(GUI_SOURCE.read_text(encoding="utf-8"))
        imported_roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_roots.add(node.module.split(".", 1)[0])
        self.assertNotIn("pictologics", imported_roots)

    def test_ui_exposes_the_functional_mvp_controls(self) -> None:
        root = ET.parse(UI_PATH).getroot()
        names = {element.attrib["name"] for element in root.iter() if "name" in element.attrib}
        expected = {
            "inputVolumeSelector",
            "segmentationSelector",
            "wholeVolumeCheckBox",
            "segmentListWidget",
            "standardConfigListWidget",
            "customConfigPathLineEdit",
            "outputTableSelector",
            "appendResultsCheckBox",
            "updatePackageButton",
            "runButton",
            "cancelButton",
            "exportButton",
            "progressBar",
        }
        self.assertEqual(expected - names, set())

    def test_top_level_build_registers_gui_and_cli(self) -> None:
        cmake = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
        self.assertIn("add_subdirectory(PictologicsSlicer)", cmake)
        self.assertIn("add_subdirectory(PictologicsCLI)", cmake)

    def test_gui_build_packages_every_support_module(self) -> None:
        cmake = GUI_CMAKE.read_text(encoding="utf-8")
        scripts = cmake.split("set(MODULE_PYTHON_SCRIPTS", 1)[1].split(")", 1)[0]
        support_root = ROOT / "PictologicsSlicer/PictologicsLib"
        for module in support_root.glob("*.py"):
            relative = module.relative_to(ROOT / "PictologicsSlicer").as_posix()
            with self.subTest(module=relative):
                self.assertIn(relative, scripts)

    def test_slicer_only_integration_fixture_is_registered_with_ctest(self) -> None:
        cmake = GUI_TEST_CMAKE.read_text(encoding="utf-8")
        self.assertIn("PictologicsSlicerIntegrationTest.py", cmake)
        self.assertIn("--additional-module-paths", cmake)
        self.assertNotIn("--additional-module-path\n", cmake)
        self.assertRegex(
            cmake,
            r"set_tests_properties\(\s*py_PictologicsSlicerIntegrationTest\s+"
            r"PROPERTIES\s+TIMEOUT\s+900\s*\)",
        )
        self.assertNotIn("SLICERPICTOLOGICS_RUN_REAL_CLI_TEST", cmake)

        integration_test = GUI_INTEGRATION_TEST.read_text(encoding="utf-8")
        self.assertIn("SLICERPICTOLOGICS_RUN_REAL_CLI_TEST", integration_test)
        self.assertIn("SLICERPICTOLOGICS_TEST_DEPENDENCY_PATH", integration_test)
        self.assertIn("@unittest.skipUnless", integration_test)
        self.assertIn('os.environ.get(RUN_REAL_CLI_TEST_ENV) == "1"', integration_test)
        self.assertNotIn("ensureDependencies(", integration_test)
        self.assertNotIn("pip_install(", integration_test)


class CrossProcessContractTests(unittest.TestCase):
    def test_support_manifest_is_accepted_unchanged_by_worker(self) -> None:
        worker = load_worker_module()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "image.nii.gz"
            mask = root / "mask.nii.gz"
            image.touch()
            mask.touch()
            manifest = build_job_manifest(
                image_path=image,
                image_name="CT",
                rois=[
                    {
                        "roi_id": "segment-1",
                        "roi_name": "Tumour",
                        "roi_source": "segmentation",
                        "mask_path": mask,
                    }
                ],
                configuration_document={
                    "standard_configurations": ["standard_fbn_32"],
                    "custom_configuration_path": None,
                    "custom_configuration_sha256": None,
                    "warmup": True,
                },
                metadata={
                    "numba_cache_path": root / "numba-cache",
                    "pictologics_version_at_submission": "0.5.0",
                    "input_volume_node_id": "vtkMRMLScalarVolumeNode1",
                },
                results_path=root / "results.json",
                provenance_path=root / "provenance.json",
                extension_version="0.1.0",
                pictologics_requirement="pictologics==0.5.0",
            )

            normalized = worker.validate_manifest(manifest, base_dir=root)

        self.assertEqual(normalized.to_dict(), manifest)


class ReleaseAdoptionTests(unittest.TestCase):
    def test_bump_advances_exact_pin_without_allowing_downgrade(self) -> None:
        bump = load_bump_module()
        with tempfile.TemporaryDirectory() as directory:
            requirement = Path(directory) / "requirements.txt"
            requirement.write_text(
                "# compatibility-qualified\npictologics==0.5.0\n",
                encoding="utf-8",
            )
            self.assertTrue(bump.bump_requirement(requirement, "v0.5.1"))
            self.assertIn("pictologics==0.5.1", requirement.read_text(encoding="utf-8"))
            with self.assertRaisesRegex(ValueError, "Refusing to lower"):
                bump.bump_requirement(requirement, "0.5.0")

    def test_bump_rejects_untrusted_non_release_input(self) -> None:
        bump = load_bump_module()
        for value in ("0.5.1; echo bad", "0.5.1\nmalicious", "latest", "v1.2.3rc1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                bump.parse_release(value)


if __name__ == "__main__":
    unittest.main()
