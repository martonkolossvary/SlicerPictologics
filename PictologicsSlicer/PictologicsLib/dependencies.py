"""Dependency management primitives for the Pictologics Slicer extension.

This module deliberately has no dependency on Slicer.  The GUI owns consent and the
actual pip invocation; the helpers here only parse the extension-owned requirement,
inspect its private target directory, and construct a constrained argument vector.
"""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Final

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

PICTOLOGICS_DISTRIBUTION: Final = "pictologics"
PICTOLOGICS_DEV_SOURCE_ENV: Final = "PICTOLOGICS_DEV_SOURCE"
_EXACT_STABLE_RELEASE: Final = re.compile(
    r"^(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)$"
)
ACTIVE_ENVIRONMENT_POINTER: Final = "active-environment"


class DependencyConfigurationError(ValueError):
    """Raised when dependency configuration is malformed or unsafe."""


@dataclass(frozen=True, slots=True)
class TargetInspection:
    """Result of inspecting one distribution in an isolated pip target."""

    target: Path
    requirement: Requirement
    installed_version: str | None
    installed_versions: tuple[str, ...]
    satisfied: bool

    @property
    def installed(self) -> bool:
        """Whether any matching distribution metadata was found."""

        return bool(self.installed_versions)

    @property
    def ambiguous(self) -> bool:
        """Whether stale metadata exposes more than one installed version."""

        return len(self.installed_versions) > 1


def _requirement_lines(path: Path) -> list[tuple[int, str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DependencyConfigurationError(
            f"Unable to read requirements file {path}: {exc}"
        ) from exc

    parsed: list[tuple[int, str]] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        # A requirements file controlled by the extension must stay declarative.  In
        # particular, recursive includes and index/configuration options must never be
        # forwarded to pip on a user's behalf.
        if line.startswith("-"):
            raise DependencyConfigurationError(
                f"Pip option or include is not allowed at {path}:{line_number}"
            )
        if line.endswith("\\"):
            raise DependencyConfigurationError(
                f"Line continuations are not supported at {path}:{line_number}"
            )

        # PEP 508 URLs can contain '#'; only a hash preceded by whitespace starts an
        # inline requirements-file comment.
        comment_at = next(
            (
                index
                for index, character in enumerate(line)
                if character == "#" and index > 0 and line[index - 1].isspace()
            ),
            -1,
        )
        if comment_at >= 0:
            line = line[:comment_at].rstrip()
        if line:
            parsed.append((line_number, line))
    return parsed


def parse_pictologics_requirement(path: str | os.PathLike[str]) -> Requirement:
    """Parse the single direct ``pictologics`` requirement in *path*.

    The wrapper intentionally owns exactly one direct dependency.  Pictologics' own
    dependencies are resolved transitively by pip, so additional requirement lines,
    recursive includes, and pip configuration flags are rejected.
    """

    requirements_path = Path(path)
    lines = _requirement_lines(requirements_path)
    if len(lines) != 1:
        raise DependencyConfigurationError(
            f"{requirements_path} must contain exactly one direct requirement; "
            f"found {len(lines)}"
        )

    line_number, requirement_text = lines[0]
    try:
        requirement = Requirement(requirement_text)
    except InvalidRequirement as exc:
        raise DependencyConfigurationError(
            f"Invalid requirement at {requirements_path}:{line_number}: {exc}"
        ) from exc

    if canonicalize_name(requirement.name) != canonicalize_name(
        PICTOLOGICS_DISTRIBUTION
    ):
        raise DependencyConfigurationError(
            f"The direct requirement at {requirements_path}:{line_number} must be "
            f"for {PICTOLOGICS_DISTRIBUTION!r}, not {requirement.name!r}"
        )
    if requirement.url is not None:
        raise DependencyConfigurationError(
            "Remote and direct-reference requirements are not allowed; use "
            f"{PICTOLOGICS_DEV_SOURCE_ENV} for an explicit local checkout"
        )
    specifiers = list(requirement.specifier)
    exact_version = specifiers[0].version if len(specifiers) == 1 else ""
    try:
        parsed_exact = Version(exact_version)
    except InvalidVersion:
        parsed_exact = None
    if (
        requirement.extras
        or requirement.marker is not None
        or len(specifiers) != 1
        or specifiers[0].operator != "=="
        or parsed_exact is None
        or len(parsed_exact.release) != 3
        or parsed_exact.is_prerelease
        or parsed_exact.is_devrelease
        or parsed_exact.is_postrelease
        or parsed_exact.local is not None
        or _EXACT_STABLE_RELEASE.fullmatch(exact_version) is None
    ):
        raise DependencyConfigurationError(
            "The adopted Pictologics requirement must be one exact stable X.Y.Z "
            "release (for example, pictologics==0.5.0)"
        )
    return requirement


def _version_sort_key(version: str) -> tuple[int, object]:
    try:
        return (1, Version(version))
    except InvalidVersion:
        return (0, version)


def _version_satisfies(requirement: Requirement, version: str) -> bool:
    if requirement.url is not None:
        # Direct references identify the artifact rather than constraining its metadata
        # version.  Finding one unambiguous matching distribution is sufficient here.
        return True
    try:
        parsed_version = Version(version)
    except InvalidVersion:
        return False
    if parsed_version.is_prerelease and requirement.specifier.prereleases is not True:
        return False
    return requirement.specifier.contains(
        parsed_version,
        prereleases=requirement.specifier.prereleases,
    )


def inspect_target(
    target: str | os.PathLike[str], requirement: Requirement
) -> TargetInspection:
    """Inspect *only* a private pip ``--target`` directory.

    Global and Slicer-bundled distributions are intentionally excluded.  Multiple
    matching ``.dist-info`` versions are treated as unsatisfied because import and
    metadata resolution would otherwise be ambiguous.
    """

    target_path = Path(target).expanduser().resolve(strict=False)
    if not target_path.is_dir():
        return TargetInspection(target_path, requirement, None, (), False)

    wanted_name = canonicalize_name(requirement.name)
    versions: list[str] = []
    for distribution in metadata.distributions(path=[str(target_path)]):
        try:
            name = distribution.metadata.get("Name")
            version = distribution.version
        except (KeyError, TypeError, UnicodeError):
            continue
        if name and canonicalize_name(name) == wanted_name and version:
            versions.append(str(version))

    ordered_versions = tuple(sorted(versions, key=_version_sort_key))
    installed_version = ordered_versions[-1] if ordered_versions else None
    satisfied = (
        len(ordered_versions) == 1
        and installed_version is not None
        and _version_satisfies(requirement, installed_version)
    )
    return TargetInspection(
        target_path,
        requirement,
        installed_version,
        ordered_versions,
        satisfied,
    )


def _local_development_source(value: str | os.PathLike[str]) -> Path:
    source_text = os.fspath(value).strip()
    if not source_text:
        raise DependencyConfigurationError(
            f"{PICTOLOGICS_DEV_SOURCE_ENV} is set but empty"
        )
    if "\x00" in source_text or source_text.startswith("-"):
        raise DependencyConfigurationError(
            "Development source is not a safe local path"
        )

    # Do not let the development escape hatch silently become a remote pip source.
    lowered = source_text.lower()
    if "://" in lowered or lowered.startswith(("git+", "hg+", "svn+", "bzr+")):
        raise DependencyConfigurationError(
            f"{PICTOLOGICS_DEV_SOURCE_ENV} must name an existing local path"
        )

    source = Path(source_text).expanduser().resolve(strict=False)
    if not source.exists():
        raise DependencyConfigurationError(
            f"Development source does not exist: {source}"
        )
    if not (source.is_dir() or source.is_file()):
        raise DependencyConfigurationError(
            f"Development source is not a directory or package artifact: {source}"
        )
    return source


def build_pip_install_args(
    requirement: Requirement,
    target: str | os.PathLike[str],
    dev_source: str | os.PathLike[str] | None = None,
    force_upgrade: bool = False,
) -> list[str]:
    """Build a safe argument vector for installing into an isolated target.

    PyPI installs are wheel-only to avoid compiling native dependencies inside Slicer.
    A local development checkout may be selected explicitly with ``dev_source`` or the
    ``PICTOLOGICS_DEV_SOURCE`` environment variable; local sources necessarily omit the
    wheel-only constraint.  The function never invokes pip.

    Scope of the "no remote sources" guarantee: this rejects VCS/URL *requirements* and
    dev sources, but does not pin ``--index-url``/``--no-index``. The effective package
    index is therefore whatever the ambient pip configuration (``pip.conf`` /
    ``PIP_INDEX_URL``) selects -- by design, so private mirrors keep working. Callers
    needing a locked index should set it in that ambient configuration.
    """

    if canonicalize_name(requirement.name) != canonicalize_name(
        PICTOLOGICS_DISTRIBUTION
    ):
        raise DependencyConfigurationError(
            f"Expected a {PICTOLOGICS_DISTRIBUTION!r} requirement, got {requirement.name!r}"
        )
    if requirement.url is not None:
        raise DependencyConfigurationError(
            "Remote and direct-reference requirements are not allowed"
        )

    target_path = Path(target).expanduser().resolve(strict=False)
    args = [
        "--target",
        str(target_path),
        "--ignore-installed",
        "--no-warn-script-location",
    ]
    if force_upgrade:
        args.append("--upgrade")

    configured_source: str | os.PathLike[str] | None = dev_source
    if configured_source is None:
        configured_source = os.environ.get(PICTOLOGICS_DEV_SOURCE_ENV)

    if configured_source is not None:
        args.append(str(_local_development_source(configured_source)))
    else:
        args.extend(["--only-binary=:all:", str(requirement)])
    return args


def _cache_layout(cache_root: str | os.PathLike[str]) -> dict[str, Path]:
    """Return paths which do not depend on the active-environment pointer."""

    root = Path(cache_root).expanduser().resolve(strict=False)
    return {
        "cache_root": root,
        "environments_root": root / "environments",
        "active_pointer": root / ACTIVE_ENVIRONMENT_POINTER,
        "jobs_root": root / "jobs",
        "numba_cache": root / "numba-cache",
        # This directory was used before immutable, versioned environments were
        # introduced.  It remains a read/write fallback until an active pointer is
        # created so existing installations continue to work.
        "legacy_dependency_target": root / "python-packages",
    }


def _validated_environment_target(
    environments_root: Path,
    target: str | os.PathLike[str],
    *,
    must_exist: bool,
) -> Path:
    """Resolve *target* and require it to be below ``environments_root``."""

    try:
        root = environments_root.resolve(strict=False)
        candidate = Path(target).expanduser().resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise DependencyConfigurationError(
            f"Unable to resolve dependency environment path: {exc}"
        ) from exc
    if root != environments_root:
        raise DependencyConfigurationError(
            f"Dependency environments root must not be a symlink: {environments_root}"
        )
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise DependencyConfigurationError(
            f"Dependency environment must be beneath {root}: {candidate}"
        ) from exc
    if relative == Path("."):
        raise DependencyConfigurationError(
            f"Dependency environment must be a child of {root}, not the root itself"
        )
    if must_exist and not candidate.is_dir():
        raise DependencyConfigurationError(
            f"Dependency environment does not exist or is not a directory: {candidate}"
        )
    return candidate


def _read_active_dependency_target(
    active_pointer: Path, environments_root: Path
) -> Path | None:
    """Read and validate the active pointer, returning ``None`` when absent."""

    if not os.path.lexists(active_pointer):
        return None
    if active_pointer.is_symlink() or not active_pointer.is_file():
        raise DependencyConfigurationError(
            f"Active dependency pointer is not a regular file: {active_pointer}"
        )
    try:
        pointer_text = active_pointer.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise DependencyConfigurationError(
            f"Unable to read active dependency pointer {active_pointer}: {exc}"
        ) from exc

    lines = pointer_text.splitlines()
    if len(lines) != 1 or not lines[0] or lines[0] != lines[0].strip():
        raise DependencyConfigurationError(
            f"Active dependency pointer is malformed: {active_pointer}"
        )
    try:
        relative_target = Path(lines[0])
    except (TypeError, ValueError) as exc:
        raise DependencyConfigurationError(
            f"Active dependency pointer is malformed: {active_pointer}"
        ) from exc
    if relative_target.is_absolute():
        raise DependencyConfigurationError(
            f"Active dependency pointer must contain a relative path: {active_pointer}"
        )

    return _validated_environment_target(
        environments_root,
        environments_root / relative_target,
        must_exist=True,
    )


def dependency_environment_path(
    cache_root: str | os.PathLike[str], version: str | Version
) -> Path:
    """Return the immutable environment path for one Pictologics *version*.

    The caller installs into a staging directory and publishes it at this path only
    after validation.  An existing environment must be reused or left untouched; this
    helper deliberately never creates, removes, or replaces it.
    """

    try:
        parsed_version = Version(str(version))
    except InvalidVersion as exc:
        raise DependencyConfigurationError(
            f"Invalid Pictologics environment version: {version!r}"
        ) from exc
    layout = _cache_layout(cache_root)
    target = layout["environments_root"] / f"pictologics-{parsed_version}"
    return _validated_environment_target(
        layout["environments_root"], target, must_exist=False
    )


def _fsync_parent_dir(path: Path) -> None:
    """Persist a rename by fsyncing the destination's directory.

    Directory fsync is unsupported on some platforms (notably Windows), so any
    failure to open/sync the directory is ignored.
    """

    try:
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(dir_fd)
    except OSError:
        pass
    finally:
        os.close(dir_fd)


def activate_dependency_target(
    cache_root: str | os.PathLike[str], target: str | os.PathLike[str]
) -> Path:
    """Atomically make an existing immutable environment the active target.

    The pointer stores a path relative to ``environments_root``.  Both writers and
    readers validate containment after resolving symlinks, preventing a corrupted or
    malicious pointer from selecting packages outside the extension-owned cache.
    """

    layout = _cache_layout(cache_root)
    root = layout["cache_root"]
    environments_root = layout["environments_root"]
    active_pointer = layout["active_pointer"]
    root.mkdir(parents=True, exist_ok=True)
    environments_root.mkdir(parents=True, exist_ok=True)
    candidate = _validated_environment_target(
        environments_root, target, must_exist=True
    )
    relative_target = candidate.relative_to(environments_root.resolve(strict=False))

    temporary_name: str | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{ACTIVE_ENVIRONMENT_POINTER}-",
            suffix=".tmp",
            dir=root,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(relative_target.as_posix())
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_name, active_pointer)
        temporary_name = None
        _fsync_parent_dir(active_pointer)
    except OSError as exc:
        raise DependencyConfigurationError(
            f"Unable to activate dependency environment {candidate}: {exc}"
        ) from exc
    finally:
        if temporary_name is not None:
            try:
                Path(temporary_name).unlink()
            except FileNotFoundError:
                pass

    return candidate


def dependency_paths(cache_root: str | os.PathLike[str]) -> dict[str, Path]:
    """Return deterministic extension cache paths and the current dependency target.

    A validated active pointer selects an immutable versioned environment.  If the
    pointer does not yet exist, ``dependency_target`` is the legacy
    ``python-packages`` directory for backward compatibility.  A present but invalid
    pointer is an error rather than an unsafe or surprising fallback.
    """

    paths = _cache_layout(cache_root)
    active_target = _read_active_dependency_target(
        paths["active_pointer"], paths["environments_root"]
    )
    paths["dependency_target"] = (
        active_target
        if active_target is not None
        else paths["legacy_dependency_target"]
    )
    return paths


def ensure_dependency_paths(cache_root: str | os.PathLike[str]) -> dict[str, Path]:
    """Create and return the extension's private cache directories."""

    paths = dependency_paths(cache_root)
    for key in (
        "cache_root",
        "environments_root",
        "jobs_root",
        "numba_cache",
        "dependency_target",
    ):
        path = paths[key]
        path.mkdir(parents=True, exist_ok=True)
    return paths
