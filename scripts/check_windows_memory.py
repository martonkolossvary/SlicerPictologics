"""Smoke-test native Windows WorkingSetSize tree sampling with owned processes.

Run in the isolated developer Python, not Slicer's shared environment. Uses the
base Python executable to avoid venv redirectors. Every child is terminated by
its owner. No command lines or unrelated process details enter the report.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from workload_support import WindowsMemory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    output = parser.parse_args().output
    if os.name != 'nt':
        raise RuntimeError('This native smoke check requires Windows.')
    if output.exists():
        raise RuntimeError('Choose a new report path.')
    child_code = "import os,time; data=bytearray(32*1024*1024); print(os.getpid(),flush=True); time.sleep(90)"
    root_code = (
        "import os,subprocess,sys; data=bytearray(32*1024*1024); "
        "p=subprocess.Popen([sys.executable,'-c'," + repr(child_code) + "],stdout=subprocess.PIPE,text=True); "
        "print(str(os.getpid())+' '+p.stdout.readline().strip(),flush=True); "
        "sys.stdin.readline(); p.terminate(); p.wait()"
    )
    executable = sys._base_executable
    with subprocess.Popen([executable, '-c', root_code], stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE, text=True) as root:
        try:
            with subprocess.Popen([executable, '-c', child_code], stdout=subprocess.PIPE, text=True) as sibling:
                try:
                    root_pid, grandchild = map(int, root.stdout.readline().split())
                    sibling_pid = int(sibling.stdout.readline())
                    backend = WindowsMemory()
                    samples = [backend.sample(root_pid) for _ in range(3)]
                    assert all(a > 32 * 1024**2 and 32 * 1024**2 < b < 64 * 1024**2 for a, b in samples), samples
                    report = {'success': True, 'metric': 'Windows PSAPI WorkingSetSize bytes',
                              'root_pid': root_pid, 'grandchild_pid': grandchild,
                              'excluded_sibling_pid': sibling_pid, 'samples': samples}
                    output.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
                    print(json.dumps(report))
                finally:
                    sibling.terminate()
                    sibling.wait(timeout=15)
        finally:
            root.communicate('\n', timeout=15)


if __name__ == '__main__':
    main()
