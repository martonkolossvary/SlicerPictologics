"""Stable PyPI release selection and unattended-adoption safeguards."""

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
with patch.object(sys, "path", [str(SCRIPTS), *sys.path]):
    spec = importlib.util.spec_from_file_location("release_discovery", SCRIPTS / "resolve_pictologics_release.py")
    release_discovery = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(release_discovery)


def wheel(*, yanked=False):
    return {"packagetype": "bdist_wheel", "yanked": yanked}


class ReleaseDiscoveryTests(unittest.TestCase):
    def test_cli_outputs_candidate_without_mutating_requirements(self):
        with tempfile.TemporaryDirectory() as directory:
            requirement = Path(directory) / "requirements.txt"
            output = Path(directory) / "github-output"
            requirement.write_text("pictologics==0.5.0\n", encoding="utf-8")
            payload = {"releases": {"0.5.1": [wheel()]}}
            with (
                patch.object(sys, "argv", ["resolve", "--requirements", str(requirement)]),
                patch.dict(os.environ, {"GITHUB_OUTPUT": str(output)}),
                patch.object(release_discovery, "urlopen", return_value=io.BytesIO(json.dumps(payload).encode())) as fetch,
            ):
                self.assertEqual(release_discovery.main(), 0)
            self.assertEqual(output.read_text(), "version=0.5.1\nchanged=true\n")
            self.assertEqual(requirement.read_text(), "pictologics==0.5.0\n")
            self.assertEqual(fetch.call_args.kwargs["timeout"], 30)
            self.assertEqual(fetch.call_args.args[0].full_url, release_discovery.PYPI_URL)

    def test_equal_version_is_noop_and_downgrade_is_rejected(self):
        for current, expected in (("0.5.1", "changed=false"), ("0.5.2", None)):
            with self.subTest(current=current), tempfile.TemporaryDirectory() as directory:
                requirement = Path(directory) / "requirements.txt"
                requirement.write_text(f"pictologics=={current}\n")
                with (
                    patch.object(sys, "argv", ["resolve", "--requirements", str(requirement)]),
                    patch.dict(os.environ, {"GITHUB_OUTPUT": ""}),
                    patch.object(release_discovery, "urlopen", return_value=io.BytesIO(
                        json.dumps({"releases": {"0.5.1": [wheel()]}}).encode())),
                    patch.object(sys, "stdout", new_callable=io.StringIO) as output,
                ):
                    if expected is None:
                        with self.assertRaisesRegex(ValueError, "Refusing to lower"):
                            release_discovery.main()
                    else:
                        self.assertEqual(release_discovery.main(), 0)
                        self.assertIn(expected, output.getvalue())
                self.assertEqual(requirement.read_text(), f"pictologics=={current}\n")

    def test_latest_uses_numeric_order_and_ignores_prereleases(self):
        payload = {"releases": {
            "0.5.1": [wheel()], "0.9.0": [wheel()], "0.10.0": [wheel()],
            "1.0.0rc1": [wheel()], "1.0.0.dev1": [wheel()],
            "1.0.0": [wheel(yanked=True)], "2.0.0": [],
        }}
        self.assertEqual(release_discovery.resolve_release(payload), "0.10.0")

    def test_manual_version_normalized_and_must_be_published(self):
        payload = {"releases": {"0.5.1": [wheel()], "0.5.2": [wheel()]}}
        self.assertEqual(release_discovery.resolve_release(payload, "v0.5.1"), "0.5.1")
        for version in ("0.5.3", "0.5.1rc1", "0.5.1\nchanged=true", "$(uname)"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                release_discovery.resolve_release(payload, version)

    def test_latest_sdist_only_or_yanked_wheel_fails_closed(self):
        for files in ([{"packagetype": "sdist"}], [wheel(yanked=True), {"packagetype": "sdist"}]):
            with self.subTest(files=files), self.assertRaisesRegex(ValueError, "binary wheel"):
                release_discovery.resolve_release({"releases": {"0.5.1": [wheel()], "0.5.2": files}})

    def test_partial_yank_keeps_usable_wheel(self):
        self.assertEqual(release_discovery.resolve_release({"releases": {
            "0.5.1": [wheel(yanked=True), wheel()],
        }}), "0.5.1")

    def test_missing_empty_and_entirely_yanked_releases_fail(self):
        for payload in ({}, {"releases": []}, {"releases": {}},
                        {"releases": {"0.5.1": [wheel(yanked=True)]}},
                        {"releases": {"v0.5.1": [wheel()], "0.5.1": None}}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                release_discovery.resolve_release(payload)


if __name__ == "__main__":
    unittest.main()
