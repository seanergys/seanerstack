# SPDX-License-Identifier: Apache-2.0
"""What `seanerstack init` sets up in a state directory."""

from __future__ import annotations

from pathlib import Path
import shlex
import subprocess

from conftest import PASSWORD, REGISTRY_VARIABLES, Commands, environment, files_containing



def test_init_stores_the_registry_credentials_for_spack(commands: Commands, secrets_file: Path, spack: Path, tmp_path: Path):
    state = tmp_path / "state"
    # Only what init stores matters here, not whether every resource can be read.
    init = commands.run(
        "seanerstack", "--state-dir", state, "--spack-executable", spack,
        "--secrets-file", secrets_file, "--secrets-password-stdin", "init",
        input=PASSWORD + "\n", env=environment(),
    )
    assert "credentials: stored" in init.stdout, init.stdout + init.stderr
    assert not init.leaked

    # The spack wrapper loads these, as a user's shell would, and the values
    # are compared here rather than printed.
    exports = state / "spack" / "credentials.sh"
    names = " ".join(f'"${name}"' for name in REGISTRY_VARIABLES)
    shell = subprocess.run(
        ["bash", "-c", f". {shlex.quote(str(exports))} && printf '%s\\0' {names}"],
        capture_output=True, check=True, env=environment(),
    )
    username, token = shell.stdout.decode("utf-8").split("\0")[:2]
    assert username == commands.username
    assert token == commands.token

    # The token is in the two credentials files, readable only by their owner,
    # and nowhere else in the state.
    stored = {state / "credentials.json", exports}
    assert set(files_containing(state, commands.token)) == stored
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in stored)
