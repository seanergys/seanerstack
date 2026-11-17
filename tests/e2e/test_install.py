# SPDX-License-Identifier: Apache-2.0
"""The installed wheel, and the secrets file the other tests use."""

from __future__ import annotations

from pathlib import Path
import re
import sys

from conftest import REPOSITORY, Commands, environment



def test_seanerstack_is_installed_from_the_wheel(commands: Commands):
    result = commands.run("seanerstack", "paths", "share", env=environment())

    assert result.returncode == 0, result.stderr
    share = Path(result.stdout.strip()).resolve()
    assert share.is_relative_to(Path(sys.prefix).resolve()), share
    assert not share.is_relative_to(REPOSITORY), f"{share} is the source checkout, not the installed wheel"


def test_secrets_file_holds_only_encrypted_tokens(commands: Commands, secrets_file: Path, password_file: Path):
    assert commands.token not in secrets_file.read_text(encoding="utf-8")
    result = commands.run("keyloom", "check", "--verify", "--password-file", password_file, secrets_file)
    assert result.returncode == 0, result.stderr


def test_version_names_the_pinned_spack(commands: Commands):
    result = commands.run("seanerstack", "--version", env=environment())

    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("seanerstack "), result.stdout
    assert re.search(r"\(Spack \d+\.\d+\.\d+\)$", result.stdout.rstrip()), result.stdout
