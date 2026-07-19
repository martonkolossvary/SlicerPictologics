"""In-process coverage for the standalone dependency probe.

The sibling ``test_dependency_probe.py`` exercises the probe end-to-end in a fresh
child process (which is what production does), so its coverage is not attributed to
this file.  These tests import the probe directly and drive every branch in-process,
carefully saving and restoring ``sys.path``/``sys.modules``/environment so the
site-package stripping performed by ``isolate_target`` never leaks into other tests.
"""

from __future__ import annotations

import contextlib
import importlib
import io
import sys
import tempfile
import types
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "PictologicsSlicer"))

from PictologicsLib import dependency_probe as dp  # noqa: E402

VERSION = "0.5.0"
STANDARD = [
    "standard_fbn_8",
    "standard_fbn_16",
    "standard_fbn_32",
    "standard_fbs_8",
    "standard_fbs_16",
    "standard_fbs_32",
]
COLUMNS = ("config", "feature_key", "feature_name", "ibsi_code", "family")


ONDISK_PACKAGE = """
__version__ = "0.5.0"


class _Catalog:
    columns = ("config", "feature_key", "feature_name", "ibsi_code", "family")
    empty = False

    def __len__(self):
        return 7


class RadiomicsPipeline:
    def get_all_standard_config_names(self):
        return [
            "standard_fbn_8", "standard_fbn_16", "standard_fbn_32",
            "standard_fbs_8", "standard_fbs_16", "standard_fbs_32",
        ]

    def describe_features(self):
        return _Catalog()

    def run(self, image, mask, subject_id, config_names):
        return {}

    def load_configs(self): pass
    def merge_configs(self): pass
    def list_configs(self): pass
    def to_dict(self): pass
    def clear_log(self): pass


def load_image(path, reference_image=None):
    return path


def warmup_jit():
    return None
"""

BROKEN_PACKAGE = 'raise ImportError("boom from candidate")\n'


class _Catalog:
    def __init__(self, columns=COLUMNS, empty=False, length=42):
        self.columns = columns
        self.empty = empty
        self._length = length

    def __len__(self):
        return self._length


def _good_run(image, mask, subject_id, config_names):
    return {}


def _good_pipeline():
    pipeline = types.SimpleNamespace()
    pipeline.get_all_standard_config_names = lambda: list(STANDARD)
    pipeline.describe_features = lambda: _Catalog()
    pipeline.run = _good_run
    pipeline.load_configs = lambda: None
    pipeline.merge_configs = lambda: None
    pipeline.list_configs = lambda: None
    pipeline.to_dict = lambda: None
    pipeline.clear_log = lambda: None
    return pipeline


def _good_module(target, version=VERSION, pipeline=None):
    module = types.ModuleType("pictologics")
    module.__version__ = version
    module.__file__ = str(Path(target) / "pictologics" / "__init__.py")
    pipe = _good_pipeline() if pipeline is None else pipeline
    module.RadiomicsPipeline = lambda: pipe
    module.load_image = lambda path, reference_image=None: path
    module.warmup_jit = lambda: None
    return module


def _write_dist(target: Path, version: str) -> None:
    dist = target / f"pictologics-{version}.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text(
        f"Metadata-Version: 2.1\nName: pictologics\nVersion: {version}\n",
        encoding="utf-8",
    )


def _make_target(
    root: Path,
    *,
    version: str = VERSION,
    dist: bool = True,
    duplicate: bool = False,
    package: str | None = None,
) -> Path:
    target = root / "private-target"
    package_dir = target / "pictologics"
    package_dir.mkdir(parents=True)
    if package is not None:
        (package_dir / "__init__.py").write_text(package, encoding="utf-8")
    if dist:
        _write_dist(target, version)
    if duplicate:
        _write_dist(target, "9.9.9")
    return target


class ProbeIsolationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_path = list(sys.path)
        self._saved_modules = {
            name: module
            for name, module in sys.modules.items()
            if name == "pictologics" or name.startswith("pictologics.")
        }
        for name in list(self._saved_modules):
            del sys.modules[name]
        self._saved_env = dp.os.environ.get("PICTOLOGICS_DISABLE_WARMUP")
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        sys.path[:] = self._saved_path
        for name in list(sys.modules):
            if name == "pictologics" or name.startswith("pictologics."):
                del sys.modules[name]
        sys.modules.update(self._saved_modules)
        if self._saved_env is None:
            dp.os.environ.pop("PICTOLOGICS_DISABLE_WARMUP", None)
        else:
            dp.os.environ["PICTOLOGICS_DISABLE_WARMUP"] = self._saved_env
        importlib.invalidate_caches()
        self._tmp.cleanup()

    # -- isolate_target -----------------------------------------------------

    def test_isolate_target_side_effect_free_with_explicit_search_path(self) -> None:
        target = _make_target(self.root, dist=False)
        resolved = str(Path(target).resolve(strict=True))
        search_path = [
            resolved,  # equals the target -> dropped (dedupe)
            "",  # falsy entry -> kept, exercises the ``if entry`` guard
            "/somewhere/site-packages/pkg",  # package dir -> dropped
            "/opt/normal/lib",  # ordinary entry -> kept
        ]
        before = list(sys.path)
        result = dp.isolate_target(target, search_path=search_path)
        self.assertEqual(sys.path, before, "explicit search_path must not mutate sys.path")
        self.assertEqual(result[0], resolved)
        self.assertEqual(result.count(resolved), 1)
        self.assertIn("", result)
        self.assertIn("/opt/normal/lib", result)
        self.assertNotIn("/somewhere/site-packages/pkg", result)

    def test_isolate_target_swallows_unresolvable_entries(self) -> None:
        target = _make_target(self.root, dist=False)
        sentinel = "<<boom-entry>>"
        real_path = dp.Path

        class _Boom:
            def resolve(self, strict=False):
                raise ValueError("cannot resolve")

            @property
            def parts(self):
                raise ValueError("cannot split")

        def fake_path(arg, *args, **kwargs):
            if arg == sentinel:
                return _Boom()
            return real_path(arg, *args, **kwargs)

        dp.Path = fake_path
        try:
            result = dp.isolate_target(target, search_path=[sentinel])
        finally:
            dp.Path = real_path
        # The unresolvable entry has no parts, so it is treated as a plain entry.
        self.assertIn(sentinel, result)

    def test_isolate_target_mutates_sys_path_in_place(self) -> None:
        target = _make_target(self.root, dist=False)
        resolved = str(Path(target).resolve(strict=True))
        sys.path[:] = ["/x/site-packages/foo", "/x/normal", resolved]
        result = dp.isolate_target(target)
        self.assertIsNot(result, sys.path)
        self.assertEqual(sys.path[0], resolved)
        self.assertEqual(sys.path, result)
        self.assertNotIn("/x/site-packages/foo", sys.path)
        self.assertIn("/x/normal", sys.path)

    def test_isolate_target_rejects_non_directory(self) -> None:
        marker = self.root / "not-a-dir"
        marker.write_text("x", encoding="utf-8")
        with self.assertRaises(dp.ProbeError) as ctx:
            dp.isolate_target(marker)
        self.assertIn("not a directory", str(ctx.exception))

    # -- probe() happy path -------------------------------------------------

    def test_probe_happy_path_runs_warmup_and_returns_row_count(self) -> None:
        target = _make_target(self.root)
        sys.modules["pictologics"] = _good_module(target)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            rows = dp.probe(target, VERSION, warmup=True)
        self.assertEqual(rows, 42)
        self.assertIn("private-environment probe passed", buffer.getvalue())

    # -- probe() metadata / distribution failures ---------------------------

    def test_probe_metadata_version_mismatch(self) -> None:
        target = _make_target(self.root, version=VERSION)
        with self.assertRaises(dp.ProbeError) as ctx:
            dp.probe(target, "9.9.9")
        self.assertIn("does not match adopted version", str(ctx.exception))

    def test_probe_missing_distribution(self) -> None:
        target = _make_target(self.root, dist=False)
        with self.assertRaises(dp.ProbeError) as ctx:
            dp.probe(target, VERSION)
        self.assertIn("found: none", str(ctx.exception))

    def test_probe_duplicate_distribution(self) -> None:
        target = _make_target(self.root, duplicate=True)
        with self.assertRaises(dp.ProbeError) as ctx:
            dp.probe(target, VERSION)
        self.assertIn("exactly one Pictologics distribution", str(ctx.exception))

    # -- probe() import + origin failures -----------------------------------

    def test_probe_import_failure(self) -> None:
        target = _make_target(self.root, package=BROKEN_PACKAGE)
        with self.assertRaises(dp.ProbeError) as ctx:
            dp.probe(target, VERSION)
        self.assertIn("cannot import Pictologics", str(ctx.exception))

    def test_probe_origin_without_file(self) -> None:
        target = _make_target(self.root)
        module = _good_module(target)
        module.__file__ = None
        sys.modules["pictologics"] = module
        with self.assertRaises(dp.ProbeError) as ctx:
            dp.probe(target, VERSION)
        self.assertIn("no filesystem origin", str(ctx.exception))

    def test_probe_origin_outside_target(self) -> None:
        target = _make_target(self.root)
        module = _good_module(target)
        module.__file__ = str(self.root / "elsewhere" / "pictologics" / "__init__.py")
        sys.modules["pictologics"] = module
        with self.assertRaises(dp.ProbeError) as ctx:
            dp.probe(target, VERSION)
        self.assertIn("outside the private target", str(ctx.exception))

    # -- probe() API contract failures --------------------------------------

    def test_probe_version_attribute_mismatch(self) -> None:
        target = _make_target(self.root)
        module = _good_module(target)
        module.__version__ = "1.2.3"
        sys.modules["pictologics"] = module
        with self.assertRaises(dp.ProbeError) as ctx:
            dp.probe(target, VERSION)
        self.assertIn("pictologics.__version__", str(ctx.exception))

    def test_probe_missing_pipeline(self) -> None:
        target = _make_target(self.root)
        module = _good_module(target)
        module.RadiomicsPipeline = None
        sys.modules["pictologics"] = module
        with self.assertRaises(dp.ProbeError) as ctx:
            dp.probe(target, VERSION)
        self.assertIn("does not expose RadiomicsPipeline", str(ctx.exception))

    def test_probe_missing_standard_config_getter(self) -> None:
        pipeline = _good_pipeline()
        pipeline.get_all_standard_config_names = None
        target = _make_target(self.root)
        sys.modules["pictologics"] = _good_module(target, pipeline=pipeline)
        with self.assertRaises(dp.ProbeError) as ctx:
            dp.probe(target, VERSION)
        self.assertIn("get_all_standard_config_names", str(ctx.exception))

    def test_probe_wrong_standard_config_set(self) -> None:
        pipeline = _good_pipeline()
        pipeline.get_all_standard_config_names = lambda: {"unexpected"}
        target = _make_target(self.root)
        sys.modules["pictologics"] = _good_module(target, pipeline=pipeline)
        with self.assertRaises(dp.ProbeError) as ctx:
            dp.probe(target, VERSION)
        self.assertIn("standard configuration contract changed", str(ctx.exception))

    def test_probe_missing_describe_features(self) -> None:
        pipeline = _good_pipeline()
        pipeline.describe_features = None
        target = _make_target(self.root)
        sys.modules["pictologics"] = _good_module(target, pipeline=pipeline)
        with self.assertRaises(dp.ProbeError) as ctx:
            dp.probe(target, VERSION)
        self.assertIn("describe_features", str(ctx.exception))

    def test_probe_catalog_missing_columns(self) -> None:
        pipeline = _good_pipeline()
        pipeline.describe_features = lambda: _Catalog(columns=("config", "family"))
        target = _make_target(self.root)
        sys.modules["pictologics"] = _good_module(target, pipeline=pipeline)
        with self.assertRaises(dp.ProbeError) as ctx:
            dp.probe(target, VERSION)
        self.assertIn("missing columns", str(ctx.exception))

    def test_probe_empty_catalog(self) -> None:
        pipeline = _good_pipeline()
        pipeline.describe_features = lambda: _Catalog(empty=True)
        target = _make_target(self.root)
        sys.modules["pictologics"] = _good_module(target, pipeline=pipeline)
        with self.assertRaises(dp.ProbeError) as ctx:
            dp.probe(target, VERSION)
        self.assertIn("feature catalog is empty", str(ctx.exception))

    def test_probe_missing_run(self) -> None:
        pipeline = _good_pipeline()
        pipeline.run = None
        target = _make_target(self.root)
        sys.modules["pictologics"] = _good_module(target, pipeline=pipeline)
        with self.assertRaises(dp.ProbeError) as ctx:
            dp.probe(target, VERSION)
        self.assertIn("run() is unavailable", str(ctx.exception))

    def test_probe_run_missing_parameters(self) -> None:
        pipeline = _good_pipeline()
        pipeline.run = lambda image, mask: {}
        target = _make_target(self.root)
        sys.modules["pictologics"] = _good_module(target, pipeline=pipeline)
        with self.assertRaises(dp.ProbeError) as ctx:
            dp.probe(target, VERSION)
        self.assertIn("missing parameters", str(ctx.exception))

    def test_probe_missing_pipeline_method(self) -> None:
        pipeline = _good_pipeline()
        pipeline.clear_log = None
        target = _make_target(self.root)
        sys.modules["pictologics"] = _good_module(target, pipeline=pipeline)
        with self.assertRaises(dp.ProbeError) as ctx:
            dp.probe(target, VERSION)
        self.assertIn("clear_log() is unavailable", str(ctx.exception))

    def test_probe_missing_load_image(self) -> None:
        target = _make_target(self.root)
        module = _good_module(target)
        module.load_image = None
        sys.modules["pictologics"] = module
        with self.assertRaises(dp.ProbeError) as ctx:
            dp.probe(target, VERSION)
        self.assertIn("load_image() is unavailable", str(ctx.exception))

    def test_probe_missing_warmup_jit(self) -> None:
        target = _make_target(self.root)
        module = _good_module(target)
        module.warmup_jit = None
        sys.modules["pictologics"] = module
        with self.assertRaises(dp.ProbeError) as ctx:
            dp.probe(target, VERSION)
        self.assertIn("warmup_jit() is unavailable", str(ctx.exception))

    def test_probe_warmup_failure(self) -> None:
        target = _make_target(self.root)
        module = _good_module(target)

        def _explode():
            raise RuntimeError("kernel compile failed")

        module.warmup_jit = _explode
        sys.modules["pictologics"] = module
        with self.assertRaises(dp.ProbeError) as ctx:
            dp.probe(target, VERSION, warmup=True)
        self.assertIn("JIT warmup failed", str(ctx.exception))

    # -- parse_arguments + main() ------------------------------------------

    def test_parse_arguments_defaults_and_skip_warmup(self) -> None:
        args = dp.parse_arguments([str(self.root), VERSION])
        self.assertEqual(args.target, str(self.root))
        self.assertEqual(args.expectedVersion, VERSION)
        self.assertFalse(args.skip_warmup)
        skipped = dp.parse_arguments([str(self.root), VERSION, "--skip-warmup"])
        self.assertTrue(skipped.skip_warmup)

    def test_main_success_with_real_ondisk_package(self) -> None:
        target = _make_target(self.root, package=ONDISK_PACKAGE)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = dp.main([str(target), VERSION])
        self.assertEqual(code, 0)
        self.assertIn("private-environment probe passed", buffer.getvalue())

    def test_main_success_skip_warmup(self) -> None:
        target = _make_target(self.root, package=ONDISK_PACKAGE)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = dp.main([str(target), VERSION, "--skip-warmup"])
        self.assertEqual(code, 0)

    def test_main_reports_probe_error(self) -> None:
        target = _make_target(self.root)
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            code = dp.main([str(target), "9.9.9"])
        self.assertEqual(code, 2)
        self.assertIn("dependency probe failed", buffer.getvalue())

    def test_main_reports_generic_exception(self) -> None:
        missing = self.root / "does-not-exist"
        buffer = io.StringIO()
        with contextlib.redirect_stderr(buffer):
            code = dp.main([str(missing), VERSION])
        self.assertEqual(code, 2)
        self.assertIn("dependency probe failed", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
