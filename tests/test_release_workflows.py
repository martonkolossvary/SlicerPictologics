"""Keep unattended publication gated on the same checks as ordinary CI."""

import shlex
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
WRITE_CONSTRAINTS = (
    "printf '%s\\n' \"$CONSTRAINTS\" > PictologicsSlicer/constraints-pictologics.txt"
)


def load_workflow(name):
    # BaseLoader uses string keys, avoiding YAML 1.1's interpretation of 'on' as True.
    return yaml.load((WORKFLOWS / name).read_text(), Loader=yaml.BaseLoader)


def slicer_download_step():
    steps = load_workflow("compatibility.yml")["jobs"]["slicer"]["steps"]
    return next(step for step in steps
                if step.get("name") == "Download checksum-pinned official Slicer 5.12.4")


def slicer_download_arguments():
    commands = slicer_download_step()["run"].replace("\\\n", "").splitlines()
    return shlex.split(next(command for command in commands if command.lstrip().startswith("curl ")))


def test_slicer_download_retries_partial_transfers_with_bounded_time_and_checksum():
    step = slicer_download_step()
    arguments = slicer_download_arguments()
    assert arguments[:1] == ["curl"]
    assert {"--fail", "--location", "--retry-all-errors"} <= set(arguments)
    for option, value in {
        "--retry": "3",
        "--retry-max-time": "600",
        "--connect-timeout": "30",
        "--max-time": "300",
        "--speed-limit": "1024",
        "--speed-time": "60",
    }.items():
        assert arguments[arguments.index(option) + 1] == value
    assert step["timeout-minutes"] == "12"
    assert "continue-on-error" not in step
    assert "https://download.slicer.org/bitstream/6aa1beb7ce9de556d3010204" in arguments
    assert arguments[arguments.index("-o") + 1] == "$RUNNER_TEMP/slicer.tar.gz"
    assert "--insecure" not in arguments
    checksum = (
        'echo "ac76c5061a8fff20d4e59732855f74360930fd4891450085bcbc6a8eb1a1f4ade9a1ca4fc633142661b714dbe8c4604306079f9546e52053faa5e6f99410cf76'
        '  $RUNNER_TEMP/slicer.tar.gz" | sha512sum --check'
    )
    assert checksum in step["run"]
    assert step["run"].index(checksum) < step["run"].index('tar -xzf "$RUNNER_TEMP/slicer.tar.gz"')


def test_slicer_download_recovers_from_a_real_partial_http_transfer(tmp_path):
    curl = shutil.which("curl")
    if curl is None:
        pytest.skip("curl is required to exercise the CI download command")
    payload = b"checksum-pinned Slicer download fixture\n" * 1024
    request_count = 0

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal request_count
            request_count += 1
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            # The first response reproduces curl exit 18: close before the
            # advertised Content-Length. The retry must replace, not append.
            self.wfile.write(payload[:128] if request_count == 1 else payload)
            self.close_connection = True

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    output = tmp_path / "slicer.tar.gz"
    arguments = slicer_download_arguments()
    arguments[0] = curl
    arguments[arguments.index("-o") + 1] = str(output)
    url_index = next(index for index, argument in enumerate(arguments)
                     if argument.startswith("https://download.slicer.org/"))
    arguments[url_index] = f"http://127.0.0.1:{server.server_port}/slicer.tar.gz"
    try:
        result = subprocess.run(
            [*arguments, "--noproxy", "127.0.0.1"],
            capture_output=True, text=True, timeout=15, check=False,
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
    assert result.returncode == 0, result.stderr
    assert "curl: (18)" in result.stderr
    assert request_count == 2
    assert output.read_bytes() == payload


def test_quality_setup_declares_dependencies_and_matches_documentation():
    quality = load_workflow("compatibility.yml")["jobs"]["quality"]
    command = next(step["run"] for step in quality["steps"] if step.get("name") == "Install tooling")
    arguments = shlex.split(command)
    assert arguments[:4] == ["python", "-m", "pip", "install"]
    assert {"pytest", "pytest-cov", "coverage", "packaging", "ruff", "mypy", "pyyaml", "numpy"} <= set(arguments[4:])
    documentation = (WORKFLOWS.parents[1] / "docs/development.md").read_text()
    assert command in documentation


def test_coverage_secret_is_optional_explicit_and_reporting_remains_nonblocking():
    qualification = load_workflow("compatibility.yml")
    assert qualification["on"]["workflow_call"]["secrets"]["CODECOV_TOKEN"]["required"] == "false"
    for name, job in (("ci.yml", "compatibility"), ("adopt-pictologics-release.yml", "qualify")):
        assert load_workflow(name)["jobs"][job]["secrets"] == {
            "CODECOV_TOKEN": "${{ secrets.CODECOV_TOKEN }}"
        }
    upload = next(step for step in qualification["jobs"]["quality"]["steps"]
                  if step.get("uses", "").startswith("codecov/codecov-action@"))
    assert upload["with"]["token"] == "${{ secrets.CODECOV_TOKEN }}"
    assert upload["with"]["fail_ci_if_error"] == "false"
    assert qualification["permissions"] == {"contents": "read"}


def test_python_extension_qualification_does_not_require_a_local_sdk_build():
    quality = load_workflow("compatibility.yml")["jobs"]["quality"]
    commands = "\n".join(step.get("run", "") for step in quality["steps"])
    assert "packaging/requirements-tools.txt" not in commands
    assert "package_extension.py" not in commands
    assert "xcodebuild" not in commands
    assert "python -m pytest" in commands
    slicer = load_workflow("compatibility.yml")["jobs"]["slicer"]
    assert "run_slicer_integration.py" in slicer["steps"][-1]["run"]


def test_ci_and_adoption_share_qualification():
    slicer_test_registration = (
        WORKFLOWS.parents[1] / "PictologicsSlicer/Testing/Python/CMakeLists.txt"
    ).read_text()
    assert 'EXCLUDE REGEX "/test_release_workflows[.]py$"' in slicer_test_registration
    ci = load_workflow("ci.yml")
    adoption = load_workflow("adopt-pictologics-release.yml")
    shared = "./.github/workflows/compatibility.yml"
    assert ci["jobs"]["compatibility"]["uses"] == shared
    assert adoption["jobs"]["qualify"]["uses"] == shared
    assert adoption["jobs"]["publish"]["needs"] == ["discover", "constraints", "qualify"]
    assert adoption["jobs"]["qualify"]["if"] == "needs.discover.outputs.changed == 'true'"
    assert adoption["on"]["schedule"] == [{"cron": "17 */6 * * *"}]
    assert adoption["permissions"] == {"contents": "read"}
    assert adoption["jobs"]["publish"]["permissions"] == {"contents": "write"}
    publication = adoption["jobs"]["publish"]["steps"][-1]["run"]
    assert "--force" not in publication
    assert 'git push origin "HEAD:refs/heads/$DEFAULT_BRANCH"' in publication
    assert (
        "git add -- PictologicsSlicer/requirements-pictologics.txt "
        "PictologicsSlicer/constraints-pictologics.txt"
    ) in publication
    assert WRITE_CONSTRAINTS in publication
    assert adoption["jobs"]["publish"]["steps"][-1]["env"]["CONSTRAINTS"] == (
        "${{ needs.constraints.outputs.constraints }}"
    )


def test_adoption_resolves_tested_versions_once_for_every_gate():
    adoption = load_workflow("adopt-pictologics-release.yml")
    resolve = adoption["jobs"]["resolve"]
    assert resolve["needs"] == "discover"
    assert resolve["if"] == "needs.discover.outputs.changed == 'true'"
    assert {row["runtime"] for row in resolve["strategy"]["matrix"]["include"]} == {"linux", "windows", "macos"}
    commands = "\n".join(step.get("run", "") for step in resolve["steps"])
    assert "--ignore-installed --only-binary=:all:" in commands
    assert '--report "$RUNNER_TEMP/resolution.json"' in commands
    assert "platform_constraints.py" in commands
    assert "pip freeze" not in commands
    assert adoption["jobs"]["constraints"]["needs"] == ["discover", "resolve"]
    assert adoption["jobs"]["constraints"]["outputs"]["constraints"] == "${{ steps.constraints.outputs.constraints }}"
    assert adoption["jobs"]["qualify"]["with"]["constraints"] == (
        "${{ needs.constraints.outputs.constraints }}"
    )
    assert adoption["jobs"]["qualify"]["needs"] == ["discover", "constraints"]


def test_all_candidate_gates_use_the_validated_revision_and_pin():
    qualification = load_workflow("compatibility.yml")
    assert set(qualification["jobs"]) == {"quality", "wheel", "slicer"}
    for job in qualification["jobs"].values():
        assert all("runner." not in value for value in job.get("env", {}).values())
        checkout = job["steps"][0]
        assert checkout["with"]["ref"] == "${{ inputs.revision }}"
        assert checkout["with"]["persist-credentials"] == "false"
        apply = next(step for step in job["steps"] if step.get("name") == "Apply candidate locally")
        assert "bump_pictologics_requirement.py" in apply["run"]
        assert WRITE_CONSTRAINTS in apply["run"]
        assert apply["env"]["CONSTRAINTS"] == "${{ inputs.constraints }}"
        assert "continue-on-error" not in job
    for name in ("wheel", "slicer"):
        installs = [
            step["run"] for step in qualification["jobs"][name]["steps"]
            if "--only-binary=:all:" in step.get("run", "")
        ]
        assert len(installs) == 1
        assert "-c PictologicsSlicer/constraints-pictologics.txt" in installs[0]
    slicer = qualification["jobs"]["slicer"]
    assert slicer["env"]["SLICERPICTOLOGICS_RUN_REAL_CLI_TEST"] == "1"
    assert "run_slicer_integration.py" in slicer["steps"][-1]["run"]
    slicer_launch = slicer["steps"][-1]["run"]
    assert slicer_launch.count("--additional-module-paths") == 1
    assert (
        '--additional-module-paths "$GITHUB_WORKSPACE/PictologicsSlicer" '
        '"$GITHUB_WORKSPACE/PictologicsCLI"'
    ) in slicer_launch
    assert set(qualification["jobs"]["wheel"]["strategy"]["matrix"]["os"]) == {
        "ubuntu-24.04", "windows-latest", "macos-15-intel",
    }
