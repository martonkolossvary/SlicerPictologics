from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "PictologicsSlicer/PictologicsLib/dependency_probe.py"


FAKE_PACKAGE = textwrap.dedent(
    """
    __version__ = "0.5.0"

    class Catalog:
        columns = ("config", "feature_key", "feature_name", "ibsi_code", "family")
        empty = False

        def __len__(self):
            return 6

    class RadiomicsPipeline:
        def get_all_standard_config_names(self):
            return [
                "standard_fbn_8", "standard_fbn_16", "standard_fbn_32",
                "standard_fbs_8", "standard_fbs_16", "standard_fbs_32",
            ]

        def describe_features(self):
            return Catalog()

        def run(self, image, mask, *, subject_id, config_names):
            return {}

        def load_configs(self): pass
        def merge_configs(self): pass
        def list_configs(self): pass
        def to_dict(self): pass
        def clear_log(self): pass

    def load_image(path, reference_image=None):
        return path

    def warmup_jit():
        raise AssertionError("--skip-warmup should suppress this call")
    """
).lstrip()


class DependencyProbeTests(unittest.TestCase):
    @staticmethod
    def _python_executable() -> str:
        # Slicer CTests execute this file inside the application process; in that
        # case sys.executable is Slicer, while PythonSlicer is the standalone child.
        return shutil.which("PythonSlicer") or sys.executable

    def _target(self, root: Path) -> Path:
        target = root / "private-target"
        package = target / "pictologics"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text(FAKE_PACKAGE, encoding="utf-8")
        metadata = target / "pictologics-0.5.0.dist-info"
        metadata.mkdir()
        (metadata / "METADATA").write_text(
            "Metadata-Version: 2.1\nName: pictologics\nVersion: 0.5.0\n",
            encoding="utf-8",
        )
        return target

    def test_valid_candidate_passes_in_fresh_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = self._target(Path(directory))
            completed = subprocess.run(
                [
                    self._python_executable(),
                    str(PROBE),
                    str(target),
                    "0.5.0",
                    "--skip-warmup",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("private-environment probe passed", completed.stdout)

    def test_version_mismatch_fails_before_import(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = self._target(Path(directory))
            completed = subprocess.run(
                [
                    self._python_executable(),
                    str(PROBE),
                    str(target),
                    "0.5.1",
                    "--skip-warmup",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("does not match adopted version", completed.stderr)


if __name__ == "__main__":
    unittest.main()
