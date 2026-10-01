"""Failure injection never changes the real disk's permissions or fills it."""

import errno
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "PictologicsSlicer"))

from PictologicsLib.exports import export_file_set  # noqa: E402


def write_set(path):
    paths = [path, path.with_suffix(".provenance.json"), path.with_name(path.stem + "_catalog.csv")]
    for item in paths:
        item.write_text("new " + item.name)
    return paths


def originals(root):
    for name in ("features.csv", "features.provenance.json", "features_catalog.csv"):
        (root / name).write_text("old " + name)
        (root / name).chmod(0o600)


def contents(root):
    return {p.name: (p.read_bytes(), p.stat().st_mode) for p in root.iterdir() if p.is_file()}


class ExportRecoveryTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_complete_set_and_new_folder(self):
        root = self.root / "exports"
        paths = export_file_set(root / "features.csv", write_set)
        self.assertEqual(len(paths), 3)
        self.assertTrue(all(p.read_text() == "new " + p.name for p in paths))
        self.assertFalse(list(root.glob(".pictologics-export-*")))
        self.assertEqual(export_file_set(root / "features.csv", write_set), paths)

    def test_failed_writes_restore_complete_set_and_retry(self):
        for phase in ("sidecar", "backup", "publish_first", "publish_second", "publish_third", "interrupted"):
            for existing in (True, False):
                with self.subTest(phase=phase, existing=existing):
                    root = self.root / f"{phase}-{existing}"
                    root.mkdir()
                    if existing:
                        originals(root)
                    before = contents(root)
                    replace = os.replace
                    copyfile = shutil.copy2

                    def writer(path, phase=phase):
                        result = write_set(path)
                        if phase == "sidecar":
                            raise OSError(errno.ENOSPC, "Synthetic disk full")
                        return result

                    def replace_with_failure(source, target, phase=phase, replace=replace):
                        failing_name = {"publish_first": "features.csv", "publish_second": "features.provenance.json",
                                        "publish_third": "features_catalog.csv", "interrupted": "features.provenance.json"}.get(phase)
                        if Path(source).parent.name == "new" and Path(target).name == failing_name:
                            if phase == "interrupted":
                                raise KeyboardInterrupt()
                            raise PermissionError("Synthetic export publication failure")
                        return replace(source, target)

                    def copy_with_failure(source, target, phase=phase, copyfile=copyfile):
                        if phase == "backup":
                            raise OSError(errno.ENOSPC, "Synthetic backup failure")
                        return copyfile(source, target)

                    with patch("PictologicsLib.exports.os.replace", side_effect=replace_with_failure), patch(
                        "PictologicsLib.exports.shutil.copy2", side_effect=copy_with_failure
                    ):
                        if phase == "backup" and not existing:
                            export_file_set(root / "features.csv", writer)
                        else:
                            with self.assertRaises((OSError, KeyboardInterrupt)):
                                export_file_set(root / "features.csv", writer)
                            self.assertEqual(contents(root), before)
                    self.assertFalse(list(root.glob(".pictologics-export-*")))
                    self.assertEqual(len(export_file_set(root / "features.csv", write_set)), 3)

    def test_incomplete_rollback_retains_previous_files_for_recovery(self):
        replace = os.replace
        for error_type in (PermissionError, KeyboardInterrupt):
            with self.subTest(error=error_type.__name__):
                root = self.root / error_type.__name__
                root.mkdir()
                originals(root)

                def fail(source, target, error_type=error_type):
                    if Path(source).name == "features.provenance.json" or Path(source).parent.name == "previous":
                        raise error_type("Synthetic publication and recovery failure")
                    return replace(source, target)

                with patch("PictologicsLib.exports.os.replace", side_effect=fail), self.assertRaisesRegex(RuntimeError, "rollback was incomplete"):
                    export_file_set(root / "features.csv", write_set)
                retained = list(root.glob(".pictologics-export-*"))
                self.assertEqual(len(retained), 1)
                self.assertEqual((retained[0] / "previous" / "features.csv").read_text(), "old features.csv")
                self.assertEqual((root / "features.provenance.json").read_text(), "old features.provenance.json")

    def _symlink(self, source, target):
        try:
            source.symlink_to(target)
        except OSError:
            self.skipTest("Creating symlinks is unavailable on this platform/account.")

    def test_invalid_writer_files_fail_before_publication(self):
        for invalid in ("empty", "duplicate", "outside", "missing", "symlink", "directory"):
            with self.subTest(invalid=invalid):
                root = self.root / invalid
                root.mkdir()
                originals(root)
                before = contents(root)

                def writer(path, invalid=invalid, root=root):
                    files = write_set(path)
                    if invalid == "empty":
                        return []
                    if invalid == "duplicate":
                        return files * 2
                    if invalid == "outside":
                        return [root / "features.csv"]
                    files[0].unlink()
                    if invalid == "symlink":
                        self._symlink(files[0], root / "features.csv")
                    if invalid == "directory":
                        files[0].mkdir()
                    return files

                with self.assertRaisesRegex(ValueError, "invalid file set"):
                    export_file_set(root / "features.csv", writer)
                self.assertEqual(contents(root), before)
                self.assertFalse(list(root.glob(".pictologics-export-*")))

    def test_nonregular_destination_is_not_replaced(self):
        for kind in ("symlink", "directory"):
            with self.subTest(kind=kind):
                root = self.root / kind
                root.mkdir()
                target = root / "features.csv"
                if kind == "symlink":
                    self._symlink(target, root / "absent")
                else:
                    target.mkdir()
                with self.assertRaisesRegex(ValueError, "regular file"):
                    export_file_set(target, write_set)
                self.assertTrue(target.is_symlink() if kind == "symlink" else target.is_dir())


if __name__ == "__main__":
    unittest.main()
