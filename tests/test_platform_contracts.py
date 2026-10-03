"""Exercise platform-dependent safety branches without Windows symlink privileges.

Real symlink tests remain enabled where permitted; these injected filesystem/API
outcomes additionally cover the rejection contracts on restricted Windows hosts.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from PictologicsLib import dependencies, jobs, results, staging


def test_directory_sync_success_and_failure_close_the_descriptor():
    spec = importlib.util.spec_from_file_location('sync_worker', Path(__file__).resolve().parents[1] / 'PictologicsCLI/PictologicsCLI.py')
    worker = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {spec.name: worker}):
        spec.loader.exec_module(worker)
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / 'file'
        for module in (dependencies, jobs, results, worker):
            for failure in (None, OSError('synthetic sync failure')):
                with patch.object(module.os, 'open', return_value=123) as opened, patch.object(
                    module.os, 'fsync', side_effect=failure
                ) as synced, patch.object(module.os, 'close') as closed:
                    module._fsync_parent_dir(path)
                opened.assert_called_once_with(str(path.parent), os.O_RDONLY)
                synced.assert_called_once_with(123)
                closed.assert_called_once_with(123)


def test_dependency_pointer_symlink_is_rejected_without_reading_target(tmp_path):
    pointer = tmp_path / 'active-environment'
    pointer.write_text('unsafe')
    with patch.object(Path, 'is_symlink', return_value=True), pytest.raises(
        dependencies.DependencyConfigurationError, match='regular file'
    ):
        dependencies._read_active_dependency_target(pointer, tmp_path / 'environments')


def test_resolved_environment_root_alias_is_rejected(tmp_path):
    root = tmp_path / 'environments'
    root.mkdir()
    target = root / 'candidate'
    target.mkdir()
    original_resolve = Path.resolve

    def resolve(path, *args, **kwargs):
        return tmp_path / 'outside' if path == root else original_resolve(path, *args, **kwargs)

    with patch.object(Path, 'resolve', resolve), pytest.raises(
        dependencies.DependencyConfigurationError, match='symlink'
    ):
        dependencies._validated_environment_target(root, target, must_exist=True)


def test_posix_liveness_branches_do_not_signal_a_real_process():
    # Patch only for the call; no pathlib/NumPy code runs with a foreign os.name.
    for outcome, expected in ((None, True), (ProcessLookupError(), False),
                              (PermissionError(), True), (OSError(), False),
                              (OverflowError(), False)):
        with patch.object(staging.os, 'name', 'posix'), patch.object(
            staging.os, 'kill', side_effect=outcome
        ) as probe:
            assert staging.process_is_alive(os.getpid() + 1) is expected
            probe.assert_called_once_with(os.getpid() + 1, 0)


def test_absolute_dependency_pointer_is_rejected(tmp_path):
    pointer = tmp_path / 'active-environment'
    pointer.write_text(str(tmp_path / 'outside'), encoding='utf-8')
    with pytest.raises(dependencies.DependencyConfigurationError, match='relative path'):
        dependencies._read_active_dependency_target(pointer, tmp_path / 'environments')
