"""Synthetic fixtures test the auditor, not Factory packaging or installation."""

from __future__ import annotations

import importlib.util
import io
import json
import stat
import subprocess
import sys
import tarfile
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("package_audit", ROOT / "scripts/check_extension_package.py")
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


class PackageAuditTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.entries = {
            "Pictologics/lib/Slicer-5.12/" + name: path.read_bytes()
            for name, path in audit.expected_files(ROOT).items()
        }

    def write_zip(self, entries=None):
        path = self.root / "synthetic-fixture.zip"
        with zipfile.ZipFile(path, "w") as archive:
            for name, content in (self.entries if entries is None else entries).items():
                archive.writestr(name, content)
        return path

    def test_zip_and_tar_match_source_and_report_hash(self):
        paths = [self.write_zip(), self.root / "synthetic-fixture.tar.gz"]
        with tarfile.open(paths[1], "w:gz") as archive:
            for name, content in self.entries.items():
                member = tarfile.TarInfo(name)
                member.size = len(content)
                archive.addfile(member, io.BytesIO(content))
        for path in paths:
            with self.subTest(format=path.suffix):
                report = audit.audit_package(path, ROOT)
                self.assertTrue(report["success"])
                self.assertEqual(report["expected_runtime_files"], 23)
                self.assertEqual(report["archive_files"], 23)
                self.assertEqual(len(report["archive_sha256"]), 64)
                self.assertIn("NOT Slicer installation", report["scope"])
                self.assertEqual(len(report["module_directories"]), 2)

    def test_missing_altered_and_split_runtime_files_fail(self):
        names = list(self.entries)
        for kind in ("missing", "altered", "duplicate", "split"):
            with self.subTest(kind=kind):
                entries = dict(self.entries)
                if kind == "missing":
                    del entries[names[0]]
                elif kind == "altered":
                    entries[names[0]] = b"wrong source revision"
                elif kind == "duplicate":
                    entries["other/" + names[0]] = entries[names[0]]
                else:
                    entries["other/" + names[0]] = entries.pop(names[0])
                report = audit.audit_package(self.write_zip(entries), ROOT)
                self.assertFalse(report["success"])
                self.assertTrue(report["errors"])

    def test_private_and_nonruntime_files_are_rejected(self):
        for directory in ("Testing", "docs", "assets", ".git", ".venv", "site-packages", "environments"):
            with self.subTest(directory=directory):
                entries = {**self.entries, directory + "/unexpected.txt": b"not runtime"}
                with self.assertRaisesRegex(ValueError, "Non-runtime"):
                    audit.archive_hashes(self.write_zip(entries))

    def test_only_known_runtime_files_and_their_bytecode_are_allowed(self):
        prefix = "Pictologics/lib/Slicer-5.12/qt-scripted-modules/"
        for name in ("unexpected.py", "numpy/__init__.py", "__pycache__/unexpected.cpython-312.pyc"):
            report = audit.audit_package(self.write_zip({**self.entries, prefix + name: b"extra"}), ROOT)
            self.assertFalse(report["success"])
            self.assertIn("Unexpected runtime file", report["errors"][-1])
        for name in ("PictologicsSlicer.pyc", "PictologicsLib/__pycache__/jobs.cpython-312.opt-1.pyc"):
            report = audit.audit_package(self.write_zip({**self.entries, prefix + name: b"bytecode"}), ROOT)
            self.assertTrue(report["success"])

    def test_unsafe_paths_duplicate_names_and_zip_links_are_rejected(self):
        for name in ("../outside", "/absolute", "C:/drive", "nested/../../escape", "windows\\escape"):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "Unsafe"):
                audit.archive_hashes(self.write_zip({name: b"bad"}))
        for second in ("same.txt", "SAME.txt"):
            path = self.write_zip({"same.txt": b"one"})
            with zipfile.ZipFile(path, "a") as archive, warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                archive.writestr(second, b"two")
            with self.assertRaisesRegex(ValueError, "Duplicate/case-colliding"):
                audit.archive_hashes(path)
        path = self.root / "link.zip"
        with zipfile.ZipFile(path, "w") as archive:
            link = zipfile.ZipInfo("link")
            link.create_system = 3
            link.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(link, "../../outside")
        with self.assertRaisesRegex(ValueError, "Link or special"):
            audit.archive_hashes(path)

    def test_tar_links_and_special_members_are_rejected(self):
        for kind in (tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE):
            path = self.root / "special.tar"
            with tarfile.open(path, "w") as archive:
                member = tarfile.TarInfo("special")
                member.type = kind
                member.linkname = "outside"
                archive.addfile(member)
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, "Link or special"):
                audit.archive_hashes(path)

    def test_archive_limits_are_enforced_before_reading_members(self):
        path = self.write_zip({"first": b"data", "second": b"data"})
        for option, value in (("MAX_MEMBERS", 1), ("MAX_FILE_BYTES", 3), ("MAX_TOTAL_BYTES", 7)):
            with self.subTest(option=option), patch.object(audit, option, value), self.assertRaises(ValueError):
                audit.archive_hashes(path)

    def test_cli_success_and_failure_exit_codes(self):
        path = self.write_zip()
        for source in (ROOT, self.root / "missing"):
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/check_extension_package.py"), str(path), "--source", str(source)],
                check=False, capture_output=True, text=True,
            )
            report = json.loads(result.stdout)
            self.assertEqual(report["success"], source == ROOT)
            self.assertEqual(result.returncode, 0 if source == ROOT else 1)


if __name__ == "__main__":
    unittest.main()
