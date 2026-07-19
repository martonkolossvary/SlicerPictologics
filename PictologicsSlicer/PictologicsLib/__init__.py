"""Pure-Python support library for the Pictologics Slicer extension.

Importing this package does not import Slicer or Pictologics and has no startup side
effects.  The GUI and scripted CLI can therefore share the same contracts safely.
"""

from .dependencies import (
    PICTOLOGICS_DEV_SOURCE_ENV,
    DependencyConfigurationError,
    TargetInspection,
    activate_dependency_target,
    build_pip_install_args,
    dependency_environment_path,
    dependency_paths,
    ensure_dependency_paths,
    inspect_target,
    parse_pictologics_requirement,
)
from .jobs import (
    JOB_MANIFEST_SCHEMA_VERSION,
    WHOLE_VOLUME_ROI_ID,
    JobManifestError,
    build_job_manifest,
    load_job_manifest,
    sha256_file,
    sha256_payload,
    validate_job_manifest,
    write_job_manifest,
)
from .results import (
    LONG_RESULT_COLUMNS,
    RESULT_PAYLOAD_SCHEMA_VERSION,
    WIDE_ID_COLUMNS,
    ResultPayloadError,
    build_result_payload,
    export_rows,
    export_rows_csv,
    export_rows_json,
    load_result_payload,
    normalise_result_row,
    rows_to_wide,
    validate_result_payload,
    validate_result_rows,
    write_result_payload,
)
from .staging import process_is_alive, read_pid_marker

__all__ = [
    "DependencyConfigurationError",
    "JOB_MANIFEST_SCHEMA_VERSION",
    "JobManifestError",
    "LONG_RESULT_COLUMNS",
    "PICTOLOGICS_DEV_SOURCE_ENV",
    "RESULT_PAYLOAD_SCHEMA_VERSION",
    "ResultPayloadError",
    "TargetInspection",
    "WHOLE_VOLUME_ROI_ID",
    "WIDE_ID_COLUMNS",
    "activate_dependency_target",
    "build_job_manifest",
    "build_pip_install_args",
    "build_result_payload",
    "dependency_paths",
    "dependency_environment_path",
    "ensure_dependency_paths",
    "export_rows",
    "export_rows_csv",
    "export_rows_json",
    "inspect_target",
    "load_job_manifest",
    "load_result_payload",
    "normalise_result_row",
    "parse_pictologics_requirement",
    "process_is_alive",
    "read_pid_marker",
    "rows_to_wide",
    "sha256_file",
    "sha256_payload",
    "validate_job_manifest",
    "validate_result_payload",
    "validate_result_rows",
    "write_job_manifest",
    "write_result_payload",
]
