# SPDX-License-Identifier: Apache-2.0
"""What `seanerstack init` sets up in a state directory."""

from __future__ import annotations

from pathlib import Path
import re
import shlex
import subprocess

from conftest import PASSWORD, REGISTRY_VARIABLES, Commands, environment, files_containing, spack_options, write_secrets



def test_init_stores_the_registry_credentials_for_spack(commands: Commands, secrets_file: Path, spack: Path | None, tmp_path: Path):
    state = tmp_path / "state"
    # Only what init stores matters here, not whether every resource can be read.
    init = commands.run(
        "seanerstack", "--state-dir", state, *spack_options(spack),
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


def _e2e_config(path: Path, url: str) -> Path:
    path.write_text(
        f"""[resources.init-buildcache]
kind = "spack-buildcache"
url = "{url}"
credentials = "seanergys-registry"
signed = false
""",
        encoding="utf-8",
    )
    return path


def test_the_states_spack_runs_without_activation(commands: Commands, secrets_file: Path, spack: Path | None, tmp_path: Path):
    state = tmp_path / "state"
    commands.run(
        "seanerstack", "--state-dir", state, *spack_options(spack),
        "--secrets-file", secrets_file, "--secrets-password-stdin", "init",
        input=PASSWORD + "\n", env=environment(),
    )

    # A shell with nothing of Seanerstack in it, only the wrapper on PATH.
    env = environment()
    env["PATH"] = f"{state / 'spack' / 'bin'}:{env.get('PATH', '')}"
    mirrors = subprocess.run(["spack", "mirror", "list"], capture_output=True, text=True, env=env, check=False)
    target = subprocess.run(["spack", "config", "get", "packages"], capture_output=True, text=True, env=env, check=False)

    assert mirrors.returncode == 0, mirrors.stderr
    assert "seanerstack-buildcache" in mirrors.stdout, mirrors.stdout
    assert "target=x86_64_v3" in target.stdout, target.stdout


def test_init_again_needs_nothing_but_the_state(commands: Commands, secrets_file: Path, spack: Path | None, buildcache_url: str, tmp_path: Path):
    state = tmp_path / "state"
    config = _e2e_config(tmp_path / "config.toml", buildcache_url)
    first = commands.run(
        "seanerstack", "--state-dir", state, *spack_options(spack), "--config-file", config,
        "--secrets-file", secrets_file, "--secrets-password-stdin", "init",
        input=PASSWORD + "\n", env=environment(),
    )

    again = commands.run("seanerstack", "--state-dir", state, "init", env=environment())

    assert f"config: {config}" in again.stdout, again.stdout + again.stderr
    spack_line = next(line for line in first.stdout.splitlines() if line.startswith("spack: "))
    assert spack_line in again.stdout.splitlines(), again.stdout + again.stderr
    # The same access as the first time, from the stored credentials.
    assert again.returncode == first.returncode, again.stdout + again.stderr
    assert not first.leaked and not again.leaked


def test_init_fails_on_a_build_cache_it_cannot_read(commands: Commands, password_file: Path, spack: Path | None, buildcache_url: str, tmp_path: Path):
    invalid = write_secrets(commands, tmp_path / "secrets.toml", password_file, token="invalid-e2e-token")

    result = commands.run(
        "seanerstack", "--state-dir", tmp_path / "state", *spack_options(spack),
        "--config-file", _e2e_config(tmp_path / "config.toml", buildcache_url),
        "--secrets-file", invalid, "--secrets-password-file", password_file, "init",
        env=environment(),
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "[ERROR] buildcache:init-buildcache" in result.stdout, result.stdout
    assert "invalid-e2e-token" not in result.stdout + result.stderr


def test_init_refuses_another_spack_version(commands: Commands, tmp_path: Path):
    other = tmp_path / "spack"
    other.write_text("#!/bin/sh\necho '1.2.2 (0123456789abcdef)'\n", encoding="utf-8")
    other.chmod(0o755)

    result = commands.run("seanerstack", "--state-dir", tmp_path / "state", "--spack-executable", other, "init", env=environment())

    assert result.returncode == 2, result.stdout + result.stderr
    assert re.search(r"is Spack 1\.2\.2 at commit 0123456789, and Seanerstack needs Spack \S+ at commit [0-9a-f]{10}", result.stderr), result.stderr
