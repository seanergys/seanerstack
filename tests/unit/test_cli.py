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


def test_init_parses_compiler_and_skip_flags():
    parser = build_parser()

    args = parser.parse_args(["init", "gcc@15", "--skip-buildcache-check", "--skip-validate"])

    assert args.command == "init"
    assert args.compiler == "gcc@15"
    assert args.skip_buildcache_check is True
    assert args.skip_validate is True


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
        skip_buildcache_check=False,
        skip_validate=False,
    )
    defaults.update(overrides)
    return cli.argparse.Namespace(**defaults)


def test_run_init_orchestrates_bootstrap_buildcache_and_validate(monkeypatch, tmp_path: Path):
    (tmp_path / "config.toml").write_text("", encoding="utf-8")
    calls = []

    monkeypatch.setattr(cli, "load_config", lambda path: Config(path=path, resources={}))
    monkeypatch.setattr(cli, "_spack_runtime", lambda args: (None, None, ["spack"], {}))
    monkeypatch.setattr(
        cli,
        "bootstrap",
        lambda compiler, **kwargs: calls.append(("bootstrap", compiler)) or BootstrapResult(
            compiler=compiler, installed=True, registered=True, languages=("c",), probe="zlib", probe_ok=True
        ),
    )
    monkeypatch.setattr(cli, "configure_buildcaches", lambda config, **kwargs: calls.append(("configure", config)))
    monkeypatch.setattr(cli, "buildcaches", lambda config: ())
    monkeypatch.setattr(cli, "check_buildcaches", lambda config, secrets, **kwargs: calls.append(("check",)) or [("cache", True, "")])
    monkeypatch.setattr(cli, "validate", lambda **kwargs: calls.append(("validate",)) or [Finding("ok", "compiler:c", "requires gcc@15")])

    code = cli._run_init(_init_args(tmp_path))

    assert code == 0
    assert [call[0] for call in calls] == ["bootstrap", "configure", "check", "validate"]


def test_run_init_fails_when_buildcache_check_fails(monkeypatch, tmp_path: Path):
    (tmp_path / "config.toml").write_text("", encoding="utf-8")

    monkeypatch.setattr(cli, "load_config", lambda path: Config(path=path, resources={}))
    monkeypatch.setattr(cli, "_spack_runtime", lambda args: (None, None, ["spack"], {}))
    monkeypatch.setattr(
        cli,
        "bootstrap",
        lambda compiler, **kwargs: BootstrapResult(
            compiler=compiler, installed=True, registered=True, languages=("c",), probe="zlib", probe_ok=True
        ),
    )
    monkeypatch.setattr(cli, "configure_buildcaches", lambda config, **kwargs: None)
    monkeypatch.setattr(cli, "buildcaches", lambda config: ())
    monkeypatch.setattr(cli, "check_buildcaches", lambda config, secrets, **kwargs: [("cache", False, "denied")])

    code = cli._run_init(_init_args(tmp_path, skip_validate=True))

    assert code == 1


def test_run_init_skips_buildcache_check_and_validate_when_asked(monkeypatch, tmp_path: Path):
    (tmp_path / "config.toml").write_text("", encoding="utf-8")

    monkeypatch.setattr(cli, "load_config", lambda path: Config(path=path, resources={}))
    monkeypatch.setattr(cli, "_spack_runtime", lambda args: (None, None, ["spack"], {}))
    monkeypatch.setattr(
        cli,
        "bootstrap",
        lambda compiler, **kwargs: BootstrapResult(
            compiler=compiler, installed=True, registered=True, languages=("c",), probe="zlib", probe_ok=True
        ),
    )
    monkeypatch.setattr(cli, "configure_buildcaches", lambda config, **kwargs: None)
    monkeypatch.setattr(cli, "buildcaches", lambda config: ())

    def fail(*args, **kwargs):
        raise AssertionError("should not be called")

    monkeypatch.setattr(cli, "check_buildcaches", fail)
    monkeypatch.setattr(cli, "validate", fail)

    code = cli._run_init(_init_args(tmp_path, skip_buildcache_check=True, skip_validate=True))

    assert code == 0
