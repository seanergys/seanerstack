# SPDX-License-Identifier: Apache-2.0
"""Git access to the SEANERGYS GitLab with the credentials of a secrets file."""

from __future__ import annotations

from pathlib import Path

from conftest import Commands, environment, write_secrets



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
