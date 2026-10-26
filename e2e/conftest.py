# SPDX-License-Identifier: Apache-2.0
"""Fixtures for the end-to-end tests.

The tests run the `seanerstack` and `keyloom` commands of the environment
that runs pytest, against the SEANERGYS GitLab instance. `e2e/run.sh` builds
the wheel of the current checkout and installs it into a fresh environment for
them; the tests do not import Seanerstack.

Environment:

- SEANERSTACK_E2E_TOKEN: GitLab token for Git and the container registry;
  CI_JOB_TOKEN in CI, a personal access token otherwise.
- SEANERSTACK_E2E_USERNAME: user name for the token (default: oauth2;
  gitlab-ci-token for a job token).
- SEANERSTACK_E2E_SPACK: Spack executable (default: spack on PATH).
- SEANERSTACK_E2E_REQUIRED: set to 1 to fail instead of skipping when the
  token or Spack is missing.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

PASSWORD = "e2e vault password"
REDACTED = "<token>"


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
        process = subprocess.run(
            [str(self.bin / name), *map(str, args)],
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
            pytest.fail(f"{name} is not installed in {bin}; run the tests through e2e/run.sh")
    return Commands(token=token, username=os.environ.get("SEANERSTACK_E2E_USERNAME", "oauth2"), bin=bin)


@pytest.fixture(scope="session")
def spack() -> Path:
    configured = os.environ.get("SEANERSTACK_E2E_SPACK") or shutil.which("spack")
    if not configured:
        _unavailable("no Spack executable; set SEANERSTACK_E2E_SPACK")
    return Path(configured).resolve()


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
