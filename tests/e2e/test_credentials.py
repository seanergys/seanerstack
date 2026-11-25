# SPDX-License-Identifier: Apache-2.0
"""Git access to the SEANERGYS GitLab with the credentials of a secrets file."""

from __future__ import annotations

import os
from pathlib import Path
import shlex
import subprocess

from conftest import PASSWORD, Commands, environment, files_containing, spack_options, write_secrets

# A recipe of a private repository, which Spack clones with Git itself.
PRIVATE_RECIPE = "seanerbus-msg"
PRIVATE_REPOSITORY = "https://gitlab.seanergys.fz-juelich.de/software/seanerbus-msg.git"
# Variables through which a caller hands Git configuration or credentials.
GIT_ENVIRONMENT = ("GIT_ASKPASS", "SSH_ASKPASS", "GIT_CONFIG_PARAMETERS", "GIT_DIR", "GIT_WORK_TREE")



def test_package_update_reads_seanerbroker_with_credentials(commands: Commands, secrets_file: Path, password_file: Path):
    # --dry-run lists the remote refs but changes nothing, and new upstream
    # releases do not fail the test.
    result = commands.run(
        "seanerstack",
        "--secrets-file", secrets_file,
        "--secrets-password-file", password_file,
        "package", "update", "seanerbroker", "--dry-run",
        env=environment(),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("seanerbroker: "), result.stdout
    assert not result.leaked


def test_package_update_fails_with_an_invalid_token(commands: Commands, password_file: Path, tmp_path: Path):
    # Seanerstack sends the credentials with the first request, so GitLab
    # rejects an invalid token even for a repository anyone can read.
    invalid = write_secrets(commands, tmp_path / "secrets.toml", password_file, token="invalid-e2e-token")

    result = commands.run(
        "seanerstack",
        "--secrets-file", invalid,
        "--secrets-password-file", password_file,
        "package", "update", "seanerbroker", "--dry-run",
        env=environment(),
    )

    assert result.returncode == 2, result.stdout + result.stderr
    assert "invalid-e2e-token" not in result.stdout + result.stderr


def test_wrong_vault_password_is_reported(commands: Commands, secrets_file: Path, tmp_path: Path):
    wrong = tmp_path / "password"
    wrong.write_text("not the vault password\n", encoding="utf-8")

    result = commands.run(
        "seanerstack",
        "--secrets-file", secrets_file,
        "--secrets-password-file", wrong,
        "package", "update", "seanerbroker", "--dry-run",
        env=environment(),
    )

    assert result.returncode == 2
    assert "wrong password" in result.stderr
    assert "Traceback" not in result.stderr


def test_spack_clones_a_private_recipe_with_the_credentials_of_the_secrets_file(
    commands: Commands, secrets_file: Path, spack: Path | None, tmp_path: Path,
):
    # A Git with nothing of its own: no configuration of the checkout the
    # tests run in, which a CI runner clones with the job token, no
    # ~/.netrc, and no configuration passed through the environment. The
    # repository refuses it, so the clone below proves that Seanerstack
    # handed the credentials to Spack's Git.
    home = tmp_path / "home"
    home.mkdir()
    bare = {key: value for key, value in environment().items() if key not in GIT_ENVIRONMENT and not key.startswith("GIT_CONFIG_")}
    bare.update({"HOME": str(home), "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1", "GIT_TERMINAL_PROMPT": "0"})
    own = subprocess.run(
        ["git", "ls-remote", PRIVATE_REPOSITORY], capture_output=True, text=True, check=False, env=bare, cwd=tmp_path,
    )
    assert own.returncode != 0, f"{PRIVATE_REPOSITORY} is readable without credentials"

    state = tmp_path / "state"
    init = commands.run(
        "seanerstack", "--state-dir", state, *spack_options(spack),
        "--secrets-file", secrets_file, "--secrets-password-stdin", "init",
        input=PASSWORD + "\n", env=environment(),
    )
    assert init.returncode == 0, init.stdout + init.stderr

    # The state's spack, as a user runs it: no activation, no secrets file.
    fetch = commands.shell(
        f"cd {shlex.quote(str(tmp_path))} && {shlex.quote(str(state / 'spack' / 'bin' / 'spack'))} fetch {PRIVATE_RECIPE}",
        env=bare,
    )

    assert fetch.returncode == 0, fetch.stdout + fetch.stderr
    assert not init.leaked and not fetch.leaked
    # The clone, its Git configuration and Spack's records hold no token.
    holding = {state / "credentials.json", state / "spack" / "credentials.sh", state / "spack" / "git-credentials" / "seanergys-gitlab"}
    assert set(files_containing(state, commands.token)) <= holding
