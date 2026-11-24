# SPDX-License-Identifier: Apache-2.0
"""End-to-end test of `init` with Spack on the oldest Python it accepts.

Seanerstack needs a recent Python, but Spack runs with its own, which on a
login node of an older cluster is often the system Python 3.6 of RHEL 8 and
its relatives. The scripts that Seanerstack runs with `spack python` must run
there too. It needs no GitLab token: init gets a config.toml of no resources.

Environment, besides SEANERSTACK_E2E_SPACK and SEANERSTACK_E2E_REQUIRED of
conftest.py:

- SEANERSTACK_E2E_OLD_PYTHON: the Python that Spack runs with, such as
  /usr/bin/python3.6; it is given to Spack as SPACK_PYTHON.
- SEANERSTACK_E2E_DETECTED_PACKAGE: a toolchain package installed on PATH,
  such as rust, that init must find.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

from conftest import _unavailable, spack_options


def _setting(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        _unavailable(f"{name} is not set")
    return value


def test_init_detects_packages_with_spack_on_an_old_python(spack: Path | None, tmp_path: Path):
    python = _setting("SEANERSTACK_E2E_OLD_PYTHON")
    package = _setting("SEANERSTACK_E2E_DETECTED_PACKAGE")
    # A Python of 3.9 or later runs what fails on an older one, such as list[str].
    version = subprocess.run(
        [python, "-c", "import sys; print(*sys.version_info[:2])"], text=True, capture_output=True, check=True,
    ).stdout.split()
    assert tuple(map(int, version)) < (3, 9), f"{python} is Python {'.'.join(version)}, not older than 3.9"
    seanerstack = Path(sys.executable).parent / "seanerstack"
    if not seanerstack.is_file():
        pytest.fail(f"seanerstack is not installed in {seanerstack.parent}; run the tests through tests/e2e/run.sh")

    config = tmp_path / "config.toml"
    config.write_text("", encoding="utf-8")
    env = {key: value for key, value in os.environ.items() if not key.startswith("SEANERSTACK_")}
    env["SPACK_PYTHON"] = python
    result = subprocess.run(
        [str(seanerstack), "--state-dir", str(tmp_path / "state"), *map(str, spack_options(spack)),
         "--config-file", str(config), "init"],
        env=env, text=True, capture_output=True, check=False, timeout=1800,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    found = output.partition("packages found:")[2]
    assert f"{package}@" in found, output
