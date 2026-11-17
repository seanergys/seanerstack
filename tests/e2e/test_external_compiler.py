# SPDX-License-Identifier: Apache-2.0
"""End-to-end tests of `toolchain bootstrap --external` with a distribution compiler.

They run the installed `seanerstack` against a real Spack on a machine whose
distribution provides the compiler, such as the GCC 16 packages of Ubuntu
26.04 or the GCC 14 packages of Ubuntu 24.04, and need no GitLab token:
`init` finds the compiler, and `toolchain bootstrap --external` chooses it by
name.

Environment, besides SEANERSTACK_E2E_SPACK and SEANERSTACK_E2E_REQUIRED of
conftest.py:

- SEANERSTACK_E2E_EXTERNAL_COMPILER: the compiler spec installed in the
  prefix, such as gcc@16.
- SEANERSTACK_E2E_MISSING_COMPILER: a compiler spec the prefix does not
  have, such as gcc@14 on Ubuntu 26.04, which must be refused.
- SEANERSTACK_E2E_EXTERNAL_PREFIX: the prefix (default: /usr); init is told
  to search it when it is not on PATH.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys

import pytest

from conftest import _unavailable, spack_options

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


def _init(seanerstack: Path, spack: Path | None, state: Path, prefix: str, tmp_path: Path) -> None:
    """Set up the state with a config.toml of no resources, which needs no credentials."""
    config = tmp_path / "config.toml"
    config.write_text("", encoding="utf-8")
    find = [] if prefix == "/usr" else ["--find", prefix]
    result = _seanerstack(seanerstack, spack, state, "--config-file", str(config), "init", *find)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "compilers found:" in result.stdout


def _seanerstack(seanerstack: Path, spack: Path | None, state: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(seanerstack), "--state-dir", str(state), *map(str, spack_options(spack)), *args],
        env=_environment(),
        text=True,
        capture_output=True,
        timeout=3600,
        check=False,
    )


def _spack(seanerstack: Path, state: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run spack in the isolated session of the state directory, with the Spack init recorded."""
    script = 'eval "$("$0" --state-dir "$1" activate)"; shift; spack "$@"'
    return subprocess.run(
        ["bash", "-euo", "pipefail", "-c", script, str(seanerstack), str(state), *args],
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
    seanerstack: Path, spack: Path | None, prefix: str, tmp_path: Path
):
    compiler = _setting("SEANERSTACK_E2E_EXTERNAL_COMPILER")
    state = tmp_path / "state"
    _init(seanerstack, spack, state, prefix, tmp_path)

    # The package to install instead of the toolchain's rust and capnproto.
    result = _seanerstack(seanerstack, spack, state, "toolchain", "bootstrap", "--external", compiler, SPEC)

    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(rf"^compiler: {re.escape(compiler)}[.\d]* in {re.escape(prefix)}$", result.stdout, re.M), result.stdout
    assert "compiler probe (zlib): ok" in result.stdout
    assert "match nothing in the project build cache" in result.stdout

    found = _spack(seanerstack, state, "find", "--json", "--deps", SPEC)
    assert found.returncode == 0, found.stderr
    nodes = _nodes(found.stdout)
    compilers = [node for node in nodes if node["name"] == "gcc"]
    assert compilers, f"{SPEC} has no gcc node: {[node['name'] for node in nodes]}"
    for node in compilers:
        assert os.path.realpath(node["external"]["path"]) == os.path.realpath(prefix)
        assert node["version"].split(".")[0] == compiler.split("@")[1].split(".")[0]

    # Nothing but externals: no gcc was built.
    gcc = _spack(seanerstack, state, "find", "--json", "gcc")
    built = [node for node in _nodes(gcc.stdout) if "external" not in node] if gcc.returncode == 0 else []
    assert built == []


def test_a_compiler_init_did_not_find_is_refused(
    seanerstack: Path, spack: Path | None, prefix: str, tmp_path: Path
):
    compiler = _setting("SEANERSTACK_E2E_MISSING_COMPILER")
    state = tmp_path / "state"
    _init(seanerstack, spack, state, prefix, tmp_path)

    result = _seanerstack(seanerstack, spack, state, "toolchain", "bootstrap", "--external", compiler)

    assert result.returncode != 0
    assert f"--external {compiler} matches none of the compilers and packages that init found" in result.stderr

    requirements = _spack(seanerstack, state, "config", "get", "packages")
    assert requirements.returncode == 0, requirements.stderr
    assert f"require: {compiler}" not in requirements.stdout
