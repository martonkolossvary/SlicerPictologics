#!/usr/bin/env python3
"""Private, pinned CMake/CTest/CPack runner. Never uploads or installs an extension.

Requires a completed, matching Slicer build tree, not a downloaded Slicer.app.
`check` is read-only. `build` retains logs, reports and archives in an owned root.
The first build seals the local SDK/toolchain identity; subsequent runs reject drift.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

from check_extension_package import audit_package

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK = ROOT / "packaging/slicer-5.12.4.json"
EXCLUDED = {".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
INPUTS = ("CMakeLists.txt", "Pictologics.json", "LICENSE", "README.md", "pyproject.toml",
          "conftest.py", "PictologicsSlicer", "PictologicsCLI", "tests", "scripts", "packaging",
          "docs", "assets", ".github")
SCOPE = "CMake build, CTest and archive audit only; NOT packaged-install acceptance"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def identity(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def read_lock(path: Path) -> dict:
    lock = json.loads(path.read_text(encoding="utf-8"))
    if lock.get("schema") != 1 or not re.fullmatch(r"[0-9a-f]{40}", lock.get("slicer_commit", "")):
        raise ValueError("Invalid packaging lock schema or Slicer commit")
    if not re.fullmatch(r"[0-9a-f]{7,40}", lock.get("slicer_revision", "")) or not lock["slicer_commit"].startswith(lock["slicer_revision"]):
        raise ValueError("Slicer revision must be the pinned commit's unambiguous abbreviation")
    for key in ("slicer_version", "cmake_version", "qt_version", "python_version"):
        if not re.fullmatch(r"\d+\.\d+\.\d+", lock.get(key, "")):
            raise ValueError(f"Invalid exact version: {key}")
    if lock.get("build_type") != "Release" or lock.get("generator") != "Unix Makefiles":
        raise ValueError("Only Release / Unix Makefiles packaging is supported")
    if platform.system() not in lock.get("targets", {}):
        raise ValueError("No packaging target for this OS (Windows/native ARM qualification is separate)")
    return lock


def cache_values(path: Path) -> dict[str, str]:
    return dict(re.findall(r"^([^/#\n][^:\n]*):[^=\n]+=(.*)$", path.read_text(), re.MULTILINE))


def literal(text: str, key: str) -> str:
    matches = re.findall(r"^set\(" + re.escape(key) + r'\s+"([^"\n]*)"\s*\)', text, re.MULTILINE)
    if len(matches) != 1 or any(c in matches[0] for c in "$;\n"):
        raise ValueError(f"Missing/unsupported literal {key} in SlicerConfig.cmake")
    return matches[0]


def capture(command: list[str], *, env=None) -> str:
    result = subprocess.run(command, env=env, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, timeout=120, check=True)
    return result.stdout.strip()


def clean_environment() -> dict[str, str]:
    for key in ("PICTOLOGICS_DEV_SOURCE", "Slicer_REVISION"):
        if os.environ.get(key):
            raise ValueError(f"Unset {key}; development/revision overrides cannot qualify a package")
    return {key: value for key, value in os.environ.items()
            if key not in {"PYTHONPATH", "PYTHONHOME"}
            and not key.startswith(("SLICER_PACKAGE_MANAGER_", "MIDAS_"))}


def source_manifest(source: Path) -> dict[str, str]:
    files = {}
    for name in INPUTS:
        item = source / name
        if not item.exists():
            raise ValueError(f"Missing packaging input: {item}")
        for path in sorted(item.rglob("*") if item.is_dir() else [item]):
            relative = path.relative_to(source)
            if EXCLUDED.intersection(relative.parts) or path.suffix == ".pyc":
                continue
            if path.is_symlink():
                raise ValueError(f"Symlink in packaging inputs: {relative}")
            if path.is_file():
                files[relative.as_posix()] = digest(path)
    return files


def check_tools(tools_dir: Path, lock: dict) -> dict[str, str]:
    tools = {}
    for name in ("cmake", "ctest", "cpack"):
        path = tools_dir.resolve() / name
        output = capture([str(path), "--version"])
        if not output or output.splitlines()[0] != f"{name} version {lock['cmake_version']}":
            raise ValueError(f"{name} must be exactly {lock['cmake_version']}")
        tools[name] = str(path)
    return tools


def preflight(slicer_dir: Path, tools_dir: Path, lock: dict) -> dict:
    """Inspect build metadata without configuring, launching Slicer, or writing files."""
    clean_environment()
    slicer_dir = slicer_dir.resolve()
    tools_dir = tools_dir.resolve()
    for name in ("SlicerConfig.cmake", "CMakeCache.txt", "vtkSlicerVersionConfigure.h"):
        if not (slicer_dir / name).is_file():
            raise ValueError(f"Missing {slicer_dir / name}. A completed Slicer build tree is required; Slicer.app is not an SDK.")
    config = (slicer_dir / "SlicerConfig.cmake").read_text()
    header = (slicer_dir / "vtkSlicerVersionConfigure.h").read_text()
    cache = cache_values(slicer_dir / "CMakeCache.txt")
    target = lock["targets"][platform.system()]
    expected = {"Slicer_WC_REVISION_HASH": lock["slicer_revision"],
                "Slicer_REVISION": lock["slicer_revision"],
                "Slicer_OS": target["slicer_os"], "Slicer_ARCHITECTURE": target["architecture"]}
    for key, value in expected.items():
        if literal(config, key) != value:
            raise ValueError(f"Slicer build mismatch: {key} must be {value}")
    if f'#define Slicer_VERSION_FULL "{lock["slicer_version"]}"' not in header:
        raise ValueError("Slicer version header does not match the exact stable version")
    for key, value in {"CMAKE_BUILD_TYPE": lock["build_type"], "CMAKE_GENERATOR": lock["generator"]}.items():
        if cache.get(key) != value:
            raise ValueError(f"Slicer cache mismatch: {key} must be {value}")
    for key in ("Slicer_FORCED_REVISION", "Slicer_MAIN_PROJECT_FORCED_REVISION"):
        if cache.get(key):
            raise ValueError(f"SDK has a forbidden revision override: {key}")
    # WC_ROOT is the repository URL, not a local directory, in Slicer's FindGit.
    if not cache.get("CMAKE_HOME_DIRECTORY"):
        raise ValueError("SDK cache has no CMAKE_HOME_DIRECTORY")
    slicer_source = Path(cache["CMAKE_HOME_DIRECTORY"])
    if capture(["git", "-C", str(slicer_source), "rev-parse", "HEAD"]) != lock["slicer_commit"]:
        raise ValueError("Slicer source HEAD differs from pinned SDK revision")
    if capture(["git", "-C", str(slicer_source), "status", "--porcelain", "--untracked-files=no"]):
        raise ValueError("Slicer SDK source has tracked modifications")
    if capture(["git", "-C", str(slicer_source), "rev-parse", "--is-shallow-repository"]) != "false":
        raise ValueError("Slicer source must have full Git history for build provenance")
    tools = check_tools(tools_dir, lock)
    paths = {"launcher": literal(config, "Slicer_LAUNCHER_EXECUTABLE"),
             "python": cache.get("PYTHON_EXECUTABLE", ""),
             "c_compiler": cache.get("CMAKE_C_COMPILER", ""),
             "cxx_compiler": cache.get("CMAKE_CXX_COMPILER", ""),
             "make": cache.get("CMAKE_MAKE_PROGRAM", "")}
    for key, path in paths.items():
        if not path or not Path(path).is_file():
            raise ValueError(f"SDK executable missing: {key} = {path}")
    osx = {}
    if platform.system() == "Darwin":
        for key in ("CMAKE_OSX_ARCHITECTURES", "CMAKE_OSX_DEPLOYMENT_TARGET", "CMAKE_OSX_SYSROOT"):
            if not cache.get(key):
                raise ValueError(f"Explicit SDK setting required: {key}")
            osx[key] = cache[key]
        if osx["CMAKE_OSX_ARCHITECTURES"] != "x86_64":
            raise ValueError("Current macOS target is x86_64, matching the installed Slicer")
        if not Path(osx["CMAKE_OSX_SYSROOT"]).is_dir():
            raise ValueError("The SDK's macOS sysroot no longer exists")
    return {"lock": lock, "slicer_dir": str(slicer_dir), "tools": tools, "paths": paths,
            "osx": osx, "host": {"system": platform.system(), "release": platform.release(),
                                  "machine": platform.machine()},
            "metadata_hashes": {name: digest(slicer_dir / name) for name in
                                ("SlicerConfig.cmake", "CMakeCache.txt", "vtkSlicerVersionConfigure.h")},
            "tool_versions": {key: capture([path, "--version"]).splitlines()[0]
                              for key, path in paths.items() if key.endswith("compiler") or key == "make"},
            "executable_hashes": {key: digest(Path(path)) for key, path in paths.items()}}


def runtime_check(sdk: dict, env: dict) -> dict:
    code = ('import json,platform,sys,qt,slicer; '
            'print("PICTOLOGICS_SDK="+json.dumps({"version":slicer.app.applicationVersion,'
            '"revision":str(slicer.app.repositoryRevision),"architecture":platform.machine(),'
            '"python":".".join(map(str,sys.version_info[:3])),"qt":qt.qVersion()})); slicer.app.exit(0)')
    output = capture([sdk["paths"]["launcher"], "--no-splash", "--no-main-window",
                      "--disable-settings", "--ignore-slicerrc", "--disable-modules", "--python-code", code], env=env)
    matches = re.findall(r"^PICTOLOGICS_SDK=(.*)$", output, re.MULTILINE)
    if len(matches) != 1:
        raise ValueError("No unique runtime identity from the SDK's Slicer launcher")
    runtime = json.loads(matches[0])
    for key, value in {"version": sdk["lock"]["slicer_version"], "python": sdk["lock"]["python_version"],
                       "qt": sdk["lock"]["qt_version"], "architecture": "x86_64"}.items():
        if runtime.get(key) != value:
            raise ValueError(f"SDK runtime mismatch: {key} must be {value}, got {runtime.get(key)}")
    config = (Path(sdk["slicer_dir"]) / "SlicerConfig.cmake").read_text()
    if runtime["revision"] != literal(config, "Slicer_REVISION"):
        raise ValueError("SDK launcher revision does not match SlicerConfig.cmake")
    return runtime


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def seal_environment(work: Path, sdk: dict, source: Path) -> None:
    """Never delete or reuse an unowned directory, and never silently repin an SDK."""
    for protected in (source.resolve(), Path(sdk["slicer_dir"]).resolve()):
        if work == protected or work in protected.parents or protected in work.parents:
            raise ValueError("Packaging root must be separate from the source and SDK")
    if work == Path.home().resolve() or work in Path.home().resolve().parents:
        raise ValueError("Packaging root cannot be the home root or an ancestor")
    if any(part in {"CloudStorage", "OneDrive", "Dropbox"} for part in work.parts) or " " in str(work):
        raise ValueError("Use a short, non-cloud packaging root without spaces")
    marker = work / "environment.json"
    if work.exists() and any(work.iterdir()):
        if not marker.is_file() or json.loads(marker.read_text()) != sdk:
            raise ValueError("Unowned root or SDK/toolchain drift: use a new empty packaging root")
    else:
        work.mkdir(parents=True, exist_ok=True)
        write_json(marker, sdk)


def run_step(name: str, command: list[str], run: Path, env: dict, report: dict) -> None:
    print(f"{name}: {' '.join(command)}", flush=True)
    entry = {"name": name, "command": command, "log": str(run / f"{name}.log")}
    report["steps"].append(entry)
    with Path(entry["log"]).open("w", encoding="utf-8") as stream:
        result = subprocess.run(command, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                text=True, timeout=1800, check=False)
    entry["returncode"] = result.returncode
    if result.returncode:
        raise ValueError(f"{name} failed ({result.returncode}); see {entry['log']}")


def build(source: Path, work: Path, sdk: dict, jobs: int) -> dict:
    env = clean_environment()
    sdk = {**sdk, "runtime": runtime_check(sdk, env)}
    seal_environment(work, sdk, source)
    run = Path(tempfile.mkdtemp(prefix="run-", dir=work))
    report = {"success": False, "scope": SCOPE, "environment_id": identity(sdk),
              "run": str(run), "steps": [], "source": str(source), "errors": []}
    print(f"Local report: {run / 'report.json'}", flush=True)
    try:
        manifest = source_manifest(source)
        write_json(run / "source-manifest.json", manifest)
        report["source_sha256"] = identity(manifest)
        report["git_head"] = capture(["git", "-C", str(source), "rev-parse", "HEAD"])
        report["git_status"] = capture(["git", "-C", str(source), "status", "--porcelain"])
        cmake, ctest, cpack = (sdk["tools"][name] for name in ("cmake", "ctest", "cpack"))
        build_dir = run / "build"
        configure = [cmake, "-S", str(source), "-B", str(build_dir), "-G", sdk["lock"]["generator"],
                     f"-DSlicer_DIR:PATH={sdk['slicer_dir']}", "-DCMAKE_BUILD_TYPE:STRING=Release",
                     "-DBUILD_TESTING:BOOL=ON", "-DSlicer_UPLOAD_EXTENSIONS:BOOL=OFF"]
        configure += [f"-D{key}:STRING={value}" for key, value in sdk["osx"].items()]
        run_step("configure", configure, run, env, report)
        run_step("build", [cmake, "--build", str(build_dir), "--parallel", str(jobs)], run, env, report)
        tests = json.loads(capture([ctest, "--test-dir", str(build_dir), "--show-only=json-v1"], env=env))
        names = [test["name"] for test in tests["tests"]]
        if "py_PictologicsSlicerIntegrationTest" not in names:
            raise ValueError("CTest did not register the required real Slicer integration suite")
        report["ctest_tests"] = names
        # Each attempt gets a new private target. Never writes to Slicer's shared Python.
        dependency = run / "dependencies"
        run_step("dependencies", [sdk["paths"]["launcher"], "--launch", sdk["paths"]["python"],
                 "-m", "pip", "install", "--only-binary=:all:", "--target", str(dependency),
                 "-r", str(source / "PictologicsSlicer/requirements-pictologics.txt"),
                 "-c", str(source / "PictologicsSlicer/constraints-pictologics.txt")], run, env, report)
        env.update(SLICERPICTOLOGICS_RUN_REAL_CLI_TEST="1",
                   SLICERPICTOLOGICS_TEST_DEPENDENCY_PATH=str(dependency),
                   PICTOLOGICS_DISABLE_WARMUP="1", NUMBA_CACHE_DIR=str(run / "numba-cache"))
        run_step("ctest", [ctest, "--test-dir", str(build_dir), "--output-on-failure",
                 "--no-tests=error", "--output-junit", str(run / "ctest.xml"), "--parallel", "1"], run, env, report)
        artifacts = run / "artifacts"
        run_step("cpack", [cpack, "--config", str(build_dir / "CPackConfig.cmake"),
                           "-B", str(artifacts)], run, env, report)
        archives = sorted(p for p in artifacts.iterdir() if p.is_file()
                          and (p.name.endswith(".tar.gz") or p.suffix == ".zip"))
        if not archives:
            raise ValueError("CPack produced no supported archive in this fresh attempt")
        report["archives"] = [audit_package(path, source) for path in archives]
        if not all(item["success"] for item in report["archives"]):
            raise ValueError("Package content audit failed")
        if source_manifest(source) != manifest:
            raise ValueError("Source changed during packaging; repeat on a stable checkout")
        if preflight(Path(sdk["slicer_dir"]), Path(cmake).parent, sdk["lock"]) != {k: v for k, v in sdk.items() if k != "runtime"}:
            raise ValueError("SDK/toolchain changed during packaging")
        report["success"] = True
    except (OSError, ValueError, RuntimeError, tarfile.TarError, zipfile.BadZipFile, subprocess.SubprocessError) as exc:
        report["errors"].append(str(exc))
    finally:
        write_json(run / "report.json", report)
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("tools", "check", "build"))
    parser.add_argument("--slicer-dir", type=Path)
    parser.add_argument("--tools-dir", type=Path, default=ROOT / "dev/packaging-tools/bin")
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--source", type=Path, default=ROOT)
    parser.add_argument("--work-root", type=Path)
    parser.add_argument("--jobs", type=int, default=4)
    args = parser.parse_args(argv)
    try:
        if args.jobs < 1 or args.jobs > 64:
            raise ValueError("--jobs must be between 1 and 64")
        if args.action == "build" and args.work_root is None:
            raise ValueError("build requires an explicit --work-root")
        lock = read_lock(args.lock)
        if args.action == "tools":
            report = {"success": True, "scope": "Packaging tools only; Slicer SDK NOT tested",
                      "tools": check_tools(args.tools_dir, lock)}
        else:
            if args.slicer_dir is None:
                raise ValueError("check/build requires --slicer-dir")
            sdk = preflight(args.slicer_dir, args.tools_dir, lock)
            report = ({"success": True, "scope": "Read-only metadata preflight; runtime/build NOT tested", "sdk": sdk}
                      if args.action == "check" else build(args.source.resolve(), args.work_root.resolve(), sdk, args.jobs))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        report = {"success": False, "errors": [str(exc)]}
    print(json.dumps(report, indent=2))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
