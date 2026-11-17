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

    args = parser.parse_args(["toolchain", "bootstrap"])
    assert (args.command, args.toolchain_command) == ("toolchain", "bootstrap")

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
        find=None,
        packages=[],
        target=None,
        os=None,
        source_compiler=None,
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


def _init_world(monkeypatch, tmp_path: Path, *, buildcache_ok=True, git_ok=True):
    """Stand in for Spack and the network around init, recording what it does."""
    import seanerstack.isolation
    from seanerstack.config import Resource, Toolchain
    calls = []
    x = seanerstack.isolation.prepare_isolation(tmp_path / "state", tmp_path / "spack")
    cache = Resource(name="cache", kind="spack-buildcache", url="oci://registry.example.org/cache", credentials="registry", signed=False)
    toolchain = Toolchain(compiler="gcc@15", packages=(), cache="cache", target="x86_64_v3", platforms={})
    monkeypatch.setattr(cli, "load_config", lambda path: Config(path=path or tmp_path / "shipped.toml", resources={"cache": cache}, toolchain=toolchain))
    monkeypatch.setattr(cli, "_spack_runtime", lambda args: (x, tmp_path / "spack", ["spack"], {}))
    monkeypatch.setattr(cli, "configure_buildcaches", lambda config, **kwargs: calls.append("configure"))
    monkeypatch.setattr(cli, "require_target", lambda command, target, env: calls.append(f"target={target}"))
    monkeypatch.setattr(cli, "check_buildcaches", lambda config, secrets, **kwargs: calls.append("check") or [("cache", buildcache_ok, "")])
    monkeypatch.setattr(cli, "check_git_access", lambda config, secrets: calls.append("git") or [("gitlab", git_ok, "")])
    # Nothing installed on the machine; the tests of discovery cover finding it.
    monkeypatch.setattr(cli, "find_compilers", lambda command, env, prefixes: None, raising=False)
    monkeypatch.setattr(cli, "registered_compilers", lambda x: [], raising=False)
    monkeypatch.setattr(cli, "detect_packages", lambda command, env, packages, prefixes: {}, raising=False)
    monkeypatch.setattr(cli, "save_detected", lambda x, detected: None, raising=False)

    def no_compiler(*args, **kwargs):
        raise AssertionError("init installs no compiler")

    monkeypatch.setattr(cli, "bootstrap", no_compiler)
    return x, calls


def test_init_takes_no_compiler():
    import pytest
    assert build_parser().parse_args(["init"]).command == "init"
    with pytest.raises(SystemExit):
        build_parser().parse_args(["init", "gcc@15"])


def test_init_sets_up_the_state_and_checks_access_without_a_compiler(monkeypatch, tmp_path: Path, capsys):
    import seanerstack.isolation
    x, calls = _init_world(monkeypatch, tmp_path)

    code = cli._run_init(_init_args(tmp_path))

    assert code == 0
    assert calls == ["configure", "target=x86_64_v3", "check", "git"]
    assert seanerstack.isolation.read_record(x.state)["config_file"] == tmp_path / "config.toml"
    out = capsys.readouterr().out
    assert f"export PATH={x.bin}:$PATH" in out
    assert "seanerstack toolchain bootstrap" in out


def test_init_stores_the_credentials_of_the_secrets_file(monkeypatch, tmp_path: Path):
    from seanerstack.secrets import SecretStore
    x, _ = _init_world(monkeypatch, tmp_path)
    vault = {"credentials": {"registry": {"token": "glpat"}, "unused": {"token": "other"}}}
    monkeypatch.setattr(cli, "SecretStore", lambda path, **kwargs: SecretStore(path, _data=vault))

    assert cli._run_init(_init_args(tmp_path, secrets_file=tmp_path / "vault")) == 0

    assert SecretStore.stored(x.credentials).credentials("registry") == {"token": "glpat"}
    assert not SecretStore.stored(x.credentials).has_credentials("unused")


def test_init_fails_when_a_build_cache_cannot_be_read(monkeypatch, tmp_path: Path):
    _init_world(monkeypatch, tmp_path, buildcache_ok=False)
    assert cli._run_init(_init_args(tmp_path)) == 1


def test_init_fails_when_a_git_resource_cannot_be_read(monkeypatch, tmp_path: Path):
    _init_world(monkeypatch, tmp_path, git_ok=False)
    assert cli._run_init(_init_args(tmp_path)) == 1


def test_init_again_keeps_the_recorded_config(monkeypatch, tmp_path: Path):
    import seanerstack.isolation
    x, _ = _init_world(monkeypatch, tmp_path)
    cli._run_init(_init_args(tmp_path, config_file=tmp_path / "site.toml"))
    cli._run_init(_init_args(tmp_path, config_file=None))
    assert seanerstack.isolation.read_record(x.state)["config_file"] == tmp_path / "site.toml"


def test_toolchain_bootstrap_installs_the_compiler_of_the_config(monkeypatch, tmp_path: Path):
    _init_world(monkeypatch, tmp_path)
    installed = []
    monkeypatch.setattr(
        cli, "bootstrap",
        lambda compiler, **kwargs: installed.append(compiler) or BootstrapResult(
            compiler=compiler, installed=True, registered=True, languages=("c",), probe="zlib", probe_ok=True
        ),
    )
    args = _init_args(tmp_path, compiler=None, dry_run=False)

    assert cli._run_bootstrap(args) == 0
    assert installed == ["gcc@15"]


def test_activate_exports_the_credentials_that_init_stored(monkeypatch, tmp_path: Path, capsys):
    import seanerstack.isolation
    from seanerstack.config import Resource
    x = seanerstack.isolation.prepare_isolation(tmp_path / "state", tmp_path / "spack")
    x.credentials.write_text('{"credentials": {"registry": {"token": "glpat"}}}', encoding="utf-8")
    cache = Resource(name="cache", kind="spack-buildcache", url="oci://registry.example.org/cache", credentials="registry", signed=False)
    monkeypatch.setattr(cli, "load_config", lambda path: Config(path=tmp_path / "config.toml", resources={"cache": cache}))
    monkeypatch.setattr(cli, "resolve_real_spack", lambda explicit, state_dir: tmp_path / "spack")
    monkeypatch.delenv("SEANERSTACK_ACTIVE", raising=False)

    with __import__("pytest").raises(SystemExit) as stop:
        cli.main(["--state-dir", str(tmp_path / "state"), "activate"])

    assert stop.value.code == 0
    out = capsys.readouterr().out
    assert "export SEANERSTACK_RESOURCE_CACHE_PASSWORD=glpat" in out
    assert f"export PATH={x.bin}:" in out


def test_init_prints_the_compilers_and_packages_it_found_and_records_find(monkeypatch, tmp_path: Path, capsys):
    import seanerstack.isolation
    from seanerstack.discovery import Found
    x, _ = _init_world(monkeypatch, tmp_path)
    searched = []
    monkeypatch.setattr(cli, "find_compilers", lambda command, env, prefixes: searched.append(prefixes))
    monkeypatch.setattr(cli, "registered_compilers", lambda x: [Found("gcc@16.2.1", "/usr")])
    monkeypatch.setattr(cli, "detect_packages", lambda command, env, packages, prefixes: {"rust": [Found("rust@1.91.0", "/usr")]})
    toolset = tmp_path / "toolset"

    assert cli._run_init(_init_args(tmp_path, find=[toolset])) == 0

    out = capsys.readouterr().out
    assert "compilers found:\n  gcc@16.2.1  /usr\n" in out
    assert "packages found:\n  rust@1.91.0  /usr\n" in out
    assert searched == [[toolset]]
    assert seanerstack.isolation.recorded_find(x.state) == [toolset.resolve()]

    # A later init searches there again without being told.
    cli._run_init(_init_args(tmp_path, find=None))
    assert searched[-1] == [toolset.resolve()]
