# SPDX-License-Identifier: Apache-2.0
"""End-to-end tests of `toolchain bootstrap --external` with a distribution compiler.

They run the installed `seanerstack` against a real Spack on a machine whose
distribution provides the compiler, such as the GCC 16 packages of Ubuntu
26.04 or the GCC 14 packages of Ubuntu 24.04, and need no GitLab token.

Environment, besides SEANERSTACK_E2E_SPACK and SEANERSTACK_E2E_REQUIRED of
conftest.py:

- SEANERSTACK_E2E_EXTERNAL_COMPILER: the compiler spec installed in the
  prefix, such as gcc@16.
- SEANERSTACK_E2E_MISSING_COMPILER: a compiler spec the prefix does not
  have, such as gcc@14 on Ubuntu 26.04, which must be refused.
- SEANERSTACK_E2E_EXTERNAL_PREFIX: the prefix (default: /usr).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from conftest import _unavailable

# Small, and with no dependencies beyond the compiler runtime.
SPEC = "zlib"


def _setting(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        _unavailable(f"{name} is not set")
    return value


@pytest.fixture(scope="module")
def seanerstack() -> Path:
    # The command of the environment that runs pytest, which run.sh created
    # from the wheel.
    path = Path(sys.executable).parent / "seanerstack"
    if not path.is_file():
        pytest.fail(f"seanerstack is not installed in {path.parent}; run the tests through tests/e2e/run.sh")
    return path


@pytest.fixture(scope="module")
def prefix() -> str:
    return os.environ.get("SEANERSTACK_E2E_EXTERNAL_PREFIX") or "/usr"


def _environment() -> dict[str, str]:
    """The test environment, without an activated Seanerstack session."""
    return {key: value for key, value in os.environ.items() if not key.startswith("SEANERSTACK_")}


def _seanerstack(seanerstack: Path, spack: Path, state: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(seanerstack), "--state-dir", str(state), "--spack-executable", str(spack), *args],
        env=_environment(),
        text=True,
        capture_output=True,
        timeout=3600,
        check=False,
    )


def _spack(seanerstack: Path, spack: Path, state: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run spack in the isolated session of the state directory."""
    script = 'eval "$("$0" --state-dir "$1" --spack-executable "$2" activate)"; shift 2; spack "$@"'
    return subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script, str(seanerstack), str(state), str(spack), *args],
        env=_environment(),
        text=True,
        capture_output=True,
        timeout=3600,
        check=False,
    )


def _nodes(output: str) -> list[dict]:
    """The nodes of `spack find --json` or `spack spec --json` output."""
    for line in reversed(output.splitlines()):
        if line.startswith(("[", "{")):
            data = json.loads(line)
            return data["spec"]["nodes"] if isinstance(data, dict) else data
    raise AssertionError(f"no JSON in Spack's output:\n{output}")


def test_an_external_compiler_builds_a_package_and_no_compiler(
    seanerstack: Path, spack: Path, prefix: str, tmp_path: Path
):
    compiler = _setting("SEANERSTACK_E2E_EXTERNAL_COMPILER")
    state = tmp_path / "state"

    result = _seanerstack(seanerstack, spack, state, "toolchain", "bootstrap", compiler, "--external", prefix)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"compiler: {compiler} in {prefix}" in result.stdout
    assert "compiler probe (zlib): ok" in result.stdout

    install = _spack(seanerstack, spack, state, "install", "--fail-fast", SPEC)
    assert install.returncode == 0, install.stdout + install.stderr

    found = _spack(seanerstack, spack, state, "find", "--json", "--deps", SPEC)
    assert found.returncode == 0, found.stderr
    nodes = _nodes(found.stdout)
    compilers = [node for node in nodes if node["name"] == "gcc"]
    assert compilers, f"{SPEC} has no gcc node: {[node['name'] for node in nodes]}"
    for node in compilers:
        assert os.path.realpath(node["external"]["path"]) == os.path.realpath(prefix)
        assert node["version"].split(".")[0] == compiler.split("@")[1].split(".")[0]

    # Nothing but externals: no gcc was built.
    gcc = _spack(seanerstack, spack, state, "find", "--json", "gcc")
    built = [node for node in _nodes(gcc.stdout) if "external" not in node] if gcc.returncode == 0 else []
    assert built == []


def test_a_compiler_the_prefix_does_not_have_is_refused(
    seanerstack: Path, spack: Path, prefix: str, tmp_path: Path
):
    compiler = _setting("SEANERSTACK_E2E_MISSING_COMPILER")
    state = tmp_path / "state"

    result = _seanerstack(seanerstack, spack, state, "toolchain", "bootstrap", compiler, "--external", prefix)

    assert result.returncode != 0
    assert f"{compiler!r} does not name the compiler in {prefix}" in result.stderr
    assert "built from source" in result.stderr

    requirements = _spack(seanerstack, spack, state, "config", "get", "packages")
    assert requirements.returncode == 0, requirements.stderr
    assert f"require: {compiler}" not in requirements.stdout
