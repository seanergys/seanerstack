# SPDX-License-Identifier: Apache-2.0
"""End-to-end tests of the installed wheel against the SEANERGYS GitLab.

Each test reads its credentials from a keyloom secrets file, through the
`seanerstack` command, and talks to the real service: Git for the private
demobus recipe, and the container registry for the project build cache.
"""

from __future__ import annotations

import os
from pathlib import Path
import shlex
import subprocess
import sys

from conftest import PASSWORD, Commands, write_secrets

REPOSITORY = Path(__file__).resolve().parents[1]
BUILDCACHE = "seanerstack-buildcache"
REGISTRY_VARIABLES = (
    "SEANERSTACK_RESOURCE_SEANERSTACK_BUILDCACHE_USERNAME",
    "SEANERSTACK_RESOURCE_SEANERSTACK_BUILDCACHE_PASSWORD",
)


def _environment() -> dict[str, str]:
    """The test environment, without an activated Seanerstack session."""
    env = {key: value for key, value in os.environ.items() if not key.startswith("SEANERSTACK_")}
    # Git must use the askpass helper of Seanerstack, not stored credentials.
    env.update({"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
    return env


def _files_containing(root: Path, text: str) -> list[Path]:
    needle = text.encode("utf-8")
    return [path for path in root.rglob("*") if path.is_file() and needle in path.read_bytes()]


def test_seanerstack_is_installed_from_the_wheel(commands: Commands):
    result = commands.run("seanerstack", "paths", "share", env=_environment())

    assert result.returncode == 0, result.stderr
    share = Path(result.stdout.strip()).resolve()
    assert share.is_relative_to(Path(sys.prefix).resolve()), share
    assert not share.is_relative_to(REPOSITORY), f"{share} is the source checkout, not the installed wheel"


def test_secrets_file_holds_only_encrypted_tokens(commands: Commands, secrets_file: Path, password_file: Path):
    assert commands.token not in secrets_file.read_text(encoding="utf-8")
    result = commands.run("keyloom", "check", "--verify", "--password-file", password_file, secrets_file)
    assert result.returncode == 0, result.stderr


def test_package_update_authenticates_to_private_git(commands: Commands, secrets_file: Path, password_file: Path):
    # --dry-run lists the remote refs but changes nothing, and new upstream
    # releases do not fail the test.
    result = commands.run(
        "seanerstack",
        "--secrets-file", secrets_file,
        "--secrets-password-file", password_file,
        "package", "update", "demobus", "--dry-run",
        env=_environment(),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("demobus: "), result.stdout
    assert not result.leaked


def test_package_update_fails_with_an_invalid_token(commands: Commands, password_file: Path, tmp_path: Path):
    invalid = write_secrets(commands, tmp_path / "secrets.toml", password_file, token="invalid-e2e-token")

    result = commands.run(
        "seanerstack",
        "--secrets-file", invalid,
        "--secrets-password-file", password_file,
        "package", "update", "demobus", "--dry-run",
        env=_environment(),
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
        "package", "update", "demobus", "--dry-run",
        env=_environment(),
    )

    assert result.returncode == 2
    assert "wrong password" in result.stderr
    assert "Traceback" not in result.stderr


def test_activation_exports_registry_credentials(commands: Commands, secrets_file: Path, spack: Path, tmp_path: Path):
    state = tmp_path / "state"
    # The activation script exports the token by design, so its output is
    # kept out of assertion messages.
    activation = subprocess.run(
        [str(commands.bin / "seanerstack"), "--state-dir", str(state), "--spack-executable", str(spack),
         "--secrets-file", str(secrets_file), "--secrets-password-stdin", "activate"],
        input=(PASSWORD + "\n").encode("utf-8"), capture_output=True, env=_environment(), check=False,
    )
    assert activation.returncode == 0, activation.stderr.decode("utf-8").replace(commands.token, "<token>")

    # Evaluate the activation as a user's shell does, and compare the exported
    # values here rather than printing them.
    script = tmp_path / "activate.sh"
    script.touch(mode=0o600)
    script.write_bytes(activation.stdout)
    names = " ".join(f'"${name}"' for name in REGISTRY_VARIABLES)
    shell = subprocess.run(
        ["bash", "-c", f". {shlex.quote(str(script))} && printf '%s\\0' {names}"],
        capture_output=True, check=True, env=_environment(),
    )
    username, token = shell.stdout.decode("utf-8").split("\0")[:2]
    assert username == commands.username
    assert token == commands.token

    # The credentials live only in the session, never in the isolated state.
    assert _files_containing(state, commands.token) == []


def test_buildcache_check_reaches_the_registry(commands: Commands, secrets_file: Path, password_file: Path, spack: Path, tmp_path: Path):
    state = tmp_path / "state"
    common = (
        "--state-dir", state,
        "--spack-executable", spack,
        "--secrets-file", secrets_file,
        "--secrets-password-file", password_file,
    )

    configure = commands.run("seanerstack", *common, "buildcache", "configure", env=_environment())
    assert configure.returncode == 0, configure.stderr

    check = commands.run("seanerstack", *common, "buildcache", "check", env=_environment())
    assert check.returncode == 0, check.stdout + check.stderr
    assert f"[OK] buildcache:{BUILDCACHE}" in check.stdout, check.stdout
    assert not configure.leaked and not check.leaked

    # Spack's mirror configuration names the variables, never the token.
    mirrors = (state / "spack" / "config" / "mirrors.yaml").read_text(encoding="utf-8")
    assert all(name in mirrors for name in REGISTRY_VARIABLES), mirrors
    assert _files_containing(state, commands.token) == []
