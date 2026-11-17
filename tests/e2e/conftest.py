# SPDX-License-Identifier: Apache-2.0
"""Fixtures for the end-to-end tests.

The tests run the `seanerstack` and `keyloom` commands of the environment
that runs pytest, against the SEANERGYS GitLab instance. `tests/e2e/run.sh` builds
the wheel of the current checkout and installs it into a fresh environment for
them; the tests do not import Seanerstack.

Environment:

- SEANERSTACK_E2E_TOKEN: GitLab token for Git and the container registry;
  CI_JOB_TOKEN in CI, a personal access token otherwise.
- SEANERSTACK_E2E_USERNAME: user name for the token (default: oauth2;
  gitlab-ci-token for a job token).
- SEANERSTACK_E2E_SPACK: Spack executable (default: spack on PATH).
- SEANERSTACK_E2E_REGISTRY: oci:// location under which each build-cache
  test pushes to its own repository, test-e2e-buildcache-<test>, such as
  oci://$CI_REGISTRY_IMAGE. The token needs write access to it.
- SEANERSTACK_E2E_REQUIRED: set to 1 to fail instead of skipping when any of
  the above is missing.

The build-cache test compiles a small package, so it needs a C compiler and
make in addition to Git.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

PASSWORD = "e2e vault password"
REDACTED = "<token>"


REPOSITORY = Path(__file__).resolve().parents[2]
REGISTRY_VARIABLES = (
    "SEANERSTACK_RESOURCE_SEANERSTACK_BUILDCACHE_USERNAME",
    "SEANERSTACK_RESOURCE_SEANERSTACK_BUILDCACHE_PASSWORD",
)
# Small, and with no dependencies beyond the compiler runtime.
E2E_SPEC = "zlib"


def environment() -> dict[str, str]:
    """The test environment, without any Seanerstack variables of the caller."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("SEANERSTACK_")}
    # Git must use the askpass helper of Seanerstack, not stored credentials.
    env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
    return env


def files_containing(root: Path, text: str) -> list[Path]:
    needle = text.encode("utf-8")
    return [path for path in root.rglob("*") if path.is_file() and needle in path.read_bytes()]


def _unavailable(reason: str) -> None:
    if os.environ.get("SEANERSTACK_E2E_REQUIRED") == "1":
        pytest.fail(f"{reason}, and SEANERSTACK_E2E_REQUIRED=1")
    pytest.skip(reason)


@dataclass(frozen=True)
class Result:
    """A finished command, with the token removed from its output."""

    returncode: int
    stdout: str
    stderr: str
    leaked: bool


@dataclass(frozen=True)
class Commands:
    token: str
    username: str
    bin: Path

    def run(self, name: str, *args: str | Path, input: str | None = None, env=None, timeout: float = 600) -> Result:
        return self._run([str(self.bin / name), *map(str, args)], input=input, env=env, timeout=timeout)

    def shell(self, script: str, *, env=None, timeout: float = 1800) -> Result:
        """Run a bash script with `seanerstack` and `keyloom` first on PATH."""
        env = dict(os.environ if env is None else env)
        env["PATH"] = f"{self.bin}{os.pathsep}{env.get('PATH', '')}"
        return self._run(["bash", "-euo", "pipefail", "-c", script], input=None, env=env, timeout=timeout)

    def _run(self, argv: list[str], *, input: str | None, env, timeout: float) -> Result:
        process = subprocess.run(
            argv,
            input=input,
            env=env,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        leaked = self.token in process.stdout or self.token in process.stderr
        return Result(
            returncode=process.returncode,
            stdout=process.stdout.replace(self.token, REDACTED),
            stderr=process.stderr.replace(self.token, REDACTED),
            leaked=leaked,
        )


@pytest.fixture(scope="session")
def commands() -> Commands:
    token = os.environ.get("SEANERSTACK_E2E_TOKEN", "")
    if not token:
        _unavailable("SEANERSTACK_E2E_TOKEN is not set")
    # The commands of the environment that runs pytest, which run.sh created
    # from the wheel; never whatever else is first on PATH.
    bin = Path(sys.executable).parent
    for name in ("seanerstack", "keyloom"):
        if not (bin / name).is_file():
            pytest.fail(f"{name} is not installed in {bin}; run the tests through tests/e2e/run.sh")
    return Commands(token=token, username=os.environ.get("SEANERSTACK_E2E_USERNAME", "oauth2"), bin=bin)


@pytest.fixture(scope="session")
def spack() -> Path:
    configured = os.environ.get("SEANERSTACK_E2E_SPACK") or shutil.which("spack")
    if not configured:
        _unavailable("no Spack executable; set SEANERSTACK_E2E_SPACK")
    return Path(configured).resolve()


@pytest.fixture
def buildcache_url(request) -> str:
    """The build cache of the requesting test, test-e2e-buildcache-<test>.

    The test name loses its `test_` prefix and is reduced to the lower-case
    letters, digits and hyphens an OCI repository name allows, so
    test_buildcache_round_trip pushes to test-e2e-buildcache-buildcache-round-trip.
    """
    registry = os.environ.get("SEANERSTACK_E2E_REGISTRY", "").rstrip("/")
    if not registry:
        _unavailable("SEANERSTACK_E2E_REGISTRY is not set")
    if not registry.startswith("oci://"):
        pytest.fail(f"SEANERSTACK_E2E_REGISTRY must be an oci:// URL: {registry}")
    name = re.sub(r"[^a-z0-9]+", "-", request.node.name.removeprefix("test_").lower()).strip("-")
    return f"{registry}/test-e2e-buildcache-{name}"


@pytest.fixture(scope="session")
def password_file(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("password") / "password"
    path.write_text(PASSWORD + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def write_secrets(commands: Commands, path: Path, password_file: Path, *, token: str) -> Path:
    """Write a secrets file as the documentation describes, with keyloom.

    The token is written into the wrappers in plaintext and encrypted in
    place, the non-interactive form of `keyloom encrypt`.
    """
    # JSON string escapes are valid TOML basic-string escapes.
    entry = (
        f"username = {json.dumps(commands.username)}\n"
        f'token = {{ __keyloom__ = "secret", value = {json.dumps(token)} }}\n'
    )
    path.touch(mode=0o600)
    path.write_text(
        f"[credentials.seanergys-gitlab]\n{entry}\n[credentials.seanergys-registry]\n{entry}",
        encoding="utf-8",
    )
    result = commands.run("keyloom", "encrypt", path, "--password-file", password_file)
    assert result.returncode == 0, result.stderr
    assert not result.leaked
    return path


@pytest.fixture(scope="session")
def secrets_file(commands: Commands, password_file: Path, tmp_path_factory) -> Path:
    return write_secrets(
        commands, tmp_path_factory.mktemp("secrets") / "secrets.toml", password_file, token=commands.token
    )
