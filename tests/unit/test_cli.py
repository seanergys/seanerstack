# SPDX-License-Identifier: Apache-2.0
from pathlib import Path

import seanerstack.cli as cli
from seanerstack.bootstrap import BootstrapResult
from seanerstack.cli import build_parser
from seanerstack.config import Config
from seanerstack.validate import Finding


def test_reorganized_cli():
    parser = build_parser()

    args = parser.parse_args(["package", "update", "demo", "--check"])
    assert (args.command, args.package_command, args.package) == ("package", "update", "demo")

    args = parser.parse_args(["toolchain", "bootstrap", "gcc@15"])
    assert (args.command, args.toolchain_command, args.compiler) == ("toolchain", "bootstrap", "gcc@15")

    args = parser.parse_args(["paths", "env", "--package", "properdocs"])
    assert (args.command, args.paths_command, args.package) == ("paths", "env", "properdocs")


def _init_args(tmp_path: Path, **overrides) -> "cli.argparse.Namespace":
    defaults = dict(
        config_file=tmp_path / "config.toml",
        secrets_file=None,
        secrets_password_file=None,
        secrets_password_stdin=False,
        state_dir=tmp_path / "state",
        spack_executable=None,
        compiler="gcc@15",
        language=None,
        probe="zlib",
        probe_timeout=300.0,
        force=False,
        external=None,
        skip_buildcache_check=False,
        skip_validate=False,
    )
    defaults.update(overrides)
    return cli.argparse.Namespace(**defaults)


def test_version_names_seanerstack_and_its_pinned_spack(capsys):
    import importlib.metadata
    import pytest
    with pytest.raises(SystemExit) as stop:
        build_parser().parse_args(["--version"])
    assert stop.value.code == 0
    import seanerstack.pins
    spack = seanerstack.pins.SPACK_VERSION.removeprefix("v")
    assert capsys.readouterr().out == f"seanerstack {importlib.metadata.version('seanerstack')} (Spack {spack})\n"


def test_commands_take_the_config_and_credentials_that_init_recorded(monkeypatch, tmp_path: Path):
    import seanerstack.isolation
    x = seanerstack.isolation.prepare_isolation(tmp_path / "state", tmp_path / "spack")
    seanerstack.isolation.write_record(x, config_file=tmp_path / "site.toml", spack_executable=None)
    x.credentials.write_text('{"credentials": {"registry": {"token": "glpat"}}}', encoding="utf-8")
    monkeypatch.setattr(cli, "load_config", lambda path: Config(path=path, resources={}))

    config, secrets = cli._runtime(_init_args(tmp_path, config_file=None))

    assert config.path == tmp_path / "site.toml"
    assert secrets.credentials("registry") == {"token": "glpat"}


def test_a_secrets_file_given_wins_over_the_stored_credentials(monkeypatch, tmp_path: Path):
    import seanerstack.isolation
    x = seanerstack.isolation.prepare_isolation(tmp_path / "state", tmp_path / "spack")
    x.credentials.write_text('{"credentials": {}}', encoding="utf-8")
    monkeypatch.setattr(cli, "load_config", lambda path: Config(path=path, resources={}))

    _, secrets = cli._runtime(_init_args(tmp_path, secrets_file=tmp_path / "vault"))

    assert secrets.path == tmp_path / "vault"
