# SPDX-License-Identifier: Apache-2.0
"""End-to-end tests of the installed wheel against the SEANERGYS GitLab.

Each test reads its credentials from a keyloom secrets file, through the
`seanerstack` command, and talks to the real service: Git for the seanerbroker
recipe, and the container registry for a build cache that the tests populate
themselves.
"""

from __future__ import annotations

import os
from pathlib import Path
import shlex
import subprocess
import sys

from conftest import PASSWORD, Commands, write_secrets

REPOSITORY = Path(__file__).resolve().parents[2]
BUILDCACHE = "seanerstack-buildcache"
REGISTRY_VARIABLES = (
    "SEANERSTACK_RESOURCE_SEANERSTACK_BUILDCACHE_USERNAME",
    "SEANERSTACK_RESOURCE_SEANERSTACK_BUILDCACHE_PASSWORD",
)
# The build cache of the round-trip test, declared in its own config.toml.
E2E_BUILDCACHE = "e2e-buildcache"
E2E_VARIABLES = (
    "SEANERSTACK_RESOURCE_E2E_BUILDCACHE_USERNAME",
    "SEANERSTACK_RESOURCE_E2E_BUILDCACHE_PASSWORD",
)
# Small, and with no dependencies beyond the compiler runtime.
E2E_SPEC = "zlib"


def _environment() -> dict[str, str]:
    """The test environment, without any Seanerstack variables of the caller."""
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


def test_package_update_reads_seanerbroker_with_credentials(commands: Commands, secrets_file: Path, password_file: Path):
    # --dry-run lists the remote refs but changes nothing, and new upstream
    # releases do not fail the test.
    result = commands.run(
        "seanerstack",
        "--secrets-file", secrets_file,
        "--secrets-password-file", password_file,
        "package", "update", "seanerbroker", "--dry-run",
        env=_environment(),
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
        "package", "update", "seanerbroker", "--dry-run",
        env=_environment(),
    )

    assert result.returncode == 2
    assert "wrong password" in result.stderr
    assert "Traceback" not in result.stderr


def test_init_stores_the_registry_credentials_for_spack(commands: Commands, secrets_file: Path, spack: Path, tmp_path: Path):
    state = tmp_path / "state"
    # Only what init stores matters here, not whether every resource can be read.
    init = commands.run(
        "seanerstack", "--state-dir", state, "--spack-executable", spack,
        "--secrets-file", secrets_file, "--secrets-password-stdin", "init",
        input=PASSWORD + "\n", env=_environment(),
    )
    assert "credentials: stored" in init.stdout, init.stdout + init.stderr
    assert not init.leaked

    # The spack wrapper loads these, as a user's shell would, and the values
    # are compared here rather than printed.
    exports = state / "spack" / "credentials.sh"
    names = " ".join(f'"${name}"' for name in REGISTRY_VARIABLES)
    shell = subprocess.run(
        ["bash", "-c", f". {shlex.quote(str(exports))} && printf '%s\\0' {names}"],
        capture_output=True, check=True, env=_environment(),
    )
    username, token = shell.stdout.decode("utf-8").split("\0")[:2]
    assert username == commands.username
    assert token == commands.token

    # The token is in the two credentials files, readable only by their owner,
    # and nowhere else in the state.
    stored = {state / "credentials.json", exports}
    assert set(_files_containing(state, commands.token)) == stored
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in stored)


def _write_e2e_config(path: Path, url: str) -> Path:
    path.write_text(
        f"""[resources.{E2E_BUILDCACHE}]
kind = "spack-buildcache"
url = "{url}"
credentials = "seanergys-registry"
signed = false
""",
        encoding="utf-8",
    )
    return path


def test_buildcache_round_trip(commands: Commands, secrets_file: Path, password_file: Path, spack: Path, buildcache_url: str, tmp_path: Path):
    """Build a package, push it to the test cache, and install it back from there."""
    state = tmp_path / "state"
    options = " ".join(
        shlex.quote(str(value))
        for value in (
            "--config-file", _write_e2e_config(tmp_path / "config.toml", buildcache_url),
            "--state-dir", state,
            "--spack-executable", spack,
            "--secrets-file", secrets_file,
            "--secrets-password-file", password_file,
        )
    )

    # The test cache may not exist before the first push, so only the setup
    # matters here; the second init below has to pass.
    commands.shell(f"seanerstack {options} init || true", env=_environment())
    wrapper = shlex.quote(str(state / "spack" / "bin"))

    # Build from source even if an earlier pipeline pushed the same spec, and
    # replace it in the cache. The system make spares building make itself.
    # Spack is the state's wrapper, with no activation.
    push = commands.shell(
        f"""
        export PATH={wrapper}:$PATH
        spack compiler find
        spack external find gmake
        spack install --no-cache {E2E_SPEC}
        spack buildcache push --force --unsigned --update-index {E2E_BUILDCACHE} {E2E_SPEC}
        """,
        env=_environment(),
    )
    assert push.returncode == 0, push.stdout[-4000:] + push.stderr[-4000:]

    # Everything init needs is in the state now: no config, Spack or secrets file.
    check = commands.shell(f"seanerstack --state-dir {shlex.quote(str(state))} init", env=_environment())
    assert check.returncode == 0, check.stdout + check.stderr
    assert f"[OK] buildcache:{E2E_BUILDCACHE}" in check.stdout, check.stdout
    assert f"{E2E_SPEC.partition('@')[0]}@" in check.stdout, check.stdout

    # With nothing installed any more, the spec can only come from the cache.
    pull = commands.shell(
        f"""
        export PATH={wrapper}:$PATH
        spack uninstall --all --yes-to-all
        spack install --use-buildcache only {E2E_SPEC}
        spack find {E2E_SPEC}
        """,
        env=_environment(),
    )
    assert pull.returncode == 0, pull.stdout[-4000:] + pull.stderr[-4000:]

    assert not any(result.leaked for result in (push, check, pull))
    # Spack's mirror configuration names the variables, never the token, which
    # is only in the two credentials files.
    mirrors = (state / "spack" / "config" / "mirrors.yaml").read_text(encoding="utf-8")
    assert all(name in mirrors for name in E2E_VARIABLES), mirrors
    assert set(_files_containing(state, commands.token)) == {state / "credentials.json", state / "spack" / "credentials.sh"}
