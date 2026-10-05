"""Keep unattended publication gated on the same checks as ordinary CI."""

import shlex
from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
WRITE_CONSTRAINTS = (
    "printf '%s\\n' \"$CONSTRAINTS\" > PictologicsSlicer/constraints-pictologics.txt"
)


def load_workflow(name):
    # BaseLoader uses string keys, avoiding YAML 1.1's interpretation of 'on' as True.
    return yaml.load((WORKFLOWS / name).read_text(), Loader=yaml.BaseLoader)


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
