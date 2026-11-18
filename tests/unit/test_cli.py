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
    monkeypatch.setattr(cli, "require_target", lambda spack_config, target: calls.append(f"target={target}"))
    # The build caches answer; the tests of the access check cover a refusal.
    monkeypatch.setattr(cli, "require_cache_access", lambda command, env: None, raising=False)
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
    assert "activate" in out
    assert "seanerstack toolchain bootstrap" in out


def test_init_ends_with_how_to_activate_the_state_it_set_up(monkeypatch, tmp_path: Path, capsys):
    x, _ = _init_world(monkeypatch, tmp_path)
    monkeypatch.delenv("SEANERSTACK_STATE_DIR", raising=False)

    cli._run_init(_init_args(tmp_path))

    # Neither the default nor named by the variable, so activation names it.
    out = capsys.readouterr().out
    assert f'eval "$(seanerstack --state-dir {x.state} activate)"' in out
    # One instruction: the line for the shell profile is not offered next to it.
    assert "export PATH=" not in out


def test_init_needs_no_option_to_activate_the_state_that_the_variable_names(monkeypatch, tmp_path: Path, capsys):
    x, _ = _init_world(monkeypatch, tmp_path)
    monkeypatch.setenv("SEANERSTACK_STATE_DIR", str(x.state))

    cli._run_init(_init_args(tmp_path))

    assert 'eval "$(seanerstack activate)"' in capsys.readouterr().out


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


def _bootstrap_world(monkeypatch, tmp_path: Path, *, compilers=(), detected=None, system="rocky10"):
    """init's world, with a toolchain of gcc@15, rust and capnproto, recording what bootstrap does."""
    from seanerstack.config import Resource, Toolchain
    x, calls = _init_world(monkeypatch, tmp_path)
    toolchain = Toolchain(compiler="gcc@15", packages=("rust", "capnproto"), cache="cache", target="x86_64_v3", platforms={})
    cache = Resource(name="cache", kind="spack-buildcache", url="oci://registry.example.org/cache", credentials="registry", signed=False)
    monkeypatch.setattr(cli, "load_config", lambda path: Config(path=tmp_path / "config.toml", resources={"cache": cache}, toolchain=toolchain))
    monkeypatch.setattr(cli, "registered_compilers", lambda x: list(compilers))
    monkeypatch.setattr(cli, "load_detected", lambda x: dict(detected or {}))
    monkeypatch.setattr(cli.subprocess, "run", lambda args, **kwargs: cli.subprocess.CompletedProcess(args, 0, f"{system}\n", ""))

    def fake_bootstrap(compiler, **kwargs):
        calls.append(("bootstrap", compiler, kwargs["source_compiler"], kwargs["external"]))
        return BootstrapResult(compiler=compiler, installed=True, registered=True, languages=("c",), probe="zlib", probe_ok=True)

    monkeypatch.setattr(cli, "bootstrap", fake_bootstrap)
    monkeypatch.setattr(cli, "install_packages", lambda command, packages, env: calls.append(("install", list(packages))))
    monkeypatch.setattr(cli, "use_external_package", lambda command, name, prefix, env: calls.append(("external", name, prefix)))
    return calls


def _bootstrap_args(tmp_path: Path, **overrides):
    return _init_args(tmp_path, **{"compiler": None, "dry_run": False, **overrides})


def test_bootstrap_builds_the_compiler_then_rust_and_the_other_packages(monkeypatch, tmp_path: Path):
    calls = _bootstrap_world(monkeypatch, tmp_path)

    assert cli._run_bootstrap(_bootstrap_args(tmp_path)) == 0

    assert calls == ["target=x86_64_v3", ("bootstrap", "gcc@15", None, None), ("install", ["rust", "capnproto"])]


def test_bootstrap_gives_spack_the_stored_credentials_of_the_build_cache(monkeypatch, tmp_path: Path):
    import json
    import seanerstack.isolation
    _bootstrap_world(monkeypatch, tmp_path)
    credentials = seanerstack.isolation.layout(tmp_path / "state").credentials
    credentials.write_text(json.dumps({"credentials": {"registry": {"username": "reader", "token": "secret"}}}))
    environments = []

    def fake_bootstrap(compiler, **kwargs):
        environments.append(kwargs["env"])
        return BootstrapResult(compiler=compiler, installed=True, registered=True, languages=("c",), probe="zlib", probe_ok=True)

    monkeypatch.setattr(cli, "bootstrap", fake_bootstrap)
    monkeypatch.setattr(cli, "install_packages", lambda command, packages, env: environments.append(env))

    cli._run_bootstrap(_bootstrap_args(tmp_path))

    # The compiler and the packages both come from the cache, so both need them.
    for env in environments:
        assert env["SEANERSTACK_RESOURCE_CACHE_USERNAME"] == "reader"
        assert env["SEANERSTACK_RESOURCE_CACHE_PASSWORD"] == "secret"
    assert len(environments) == 2


def test_bootstrap_checks_the_build_caches_before_it_builds(monkeypatch, tmp_path: Path):
    calls = _bootstrap_world(monkeypatch, tmp_path)
    monkeypatch.setattr(cli, "require_cache_access", lambda command, env: calls.append(("access", command)))

    cli._run_bootstrap(_bootstrap_args(tmp_path))

    assert calls.index(("access", ["spack"])) < calls.index(("bootstrap", "gcc@15", None, None))


def test_bootstrap_builds_nothing_when_a_build_cache_refuses(monkeypatch, tmp_path: Path):
    import pytest
    calls = _bootstrap_world(monkeypatch, tmp_path)

    def refused(command, env):
        raise RuntimeError("cache: refuses the request: HTTP Error 401")

    monkeypatch.setattr(cli, "require_cache_access", refused)

    with pytest.raises(RuntimeError, match="HTTP Error 401"):
        cli._run_bootstrap(_bootstrap_args(tmp_path))
    assert not [call for call in calls if call[0] in ("bootstrap", "install")]


def test_bootstrap_takes_the_packages_compiler_and_target_given(monkeypatch, tmp_path: Path):
    calls = _bootstrap_world(monkeypatch, tmp_path)

    cli._run_bootstrap(_bootstrap_args(tmp_path, packages=["rust"], compiler="gcc@16.2.0", target="x86_64_v4"))

    assert calls == ["target=x86_64_v4", ("bootstrap", "gcc@16.2.0", None, None), ("install", ["rust"])]


def test_bootstrap_builds_with_a_source_compiler_that_init_found(monkeypatch, tmp_path: Path):
    from seanerstack.discovery import Found
    found = [Found("gcc@11.5.0", "/usr"), Found("gcc@14.2.1", "/opt/rh/gcc-toolset-14/root/usr")]
    calls = _bootstrap_world(monkeypatch, tmp_path, compilers=found)

    cli._run_bootstrap(_bootstrap_args(tmp_path, source_compiler="gcc@14"))

    assert ("bootstrap", "gcc@15", "gcc@14.2.1", None) in calls


def test_bootstrap_uses_an_external_compiler_and_package_and_warns(monkeypatch, tmp_path: Path, capsys):
    from seanerstack.discovery import Found
    calls = _bootstrap_world(
        monkeypatch, tmp_path, compilers=[Found("gcc@16.2.1", "/usr")], detected={"rust": [Found("rust@1.97.1", "/usr")]}
    )

    assert cli._run_bootstrap(_bootstrap_args(tmp_path, external=["gcc@16", "rust"])) == 0

    assert calls == [
        "target=x86_64_v3", ("bootstrap", "gcc@16.2.1", None, "/usr"), ("external", "rust", "/usr"), ("install", ["capnproto"]),
    ]
    out = capsys.readouterr().out
    assert "gcc@16.2.1, rust@1.97.1 came from this machine" in out
    assert "filesystem build cache" in out


def test_bootstrap_names_what_init_found_when_nothing_matches(monkeypatch, tmp_path: Path):
    import pytest
    from seanerstack.discovery import Found
    _bootstrap_world(monkeypatch, tmp_path, compilers=[Found("gcc@16.2.1", "/usr")], detected={})

    with pytest.raises(ValueError, match=r"(?s)--external rust matches none of the compilers and packages that init found.*gcc@16.2.1"):
        cli._run_bootstrap(_bootstrap_args(tmp_path, external=["rust"]))
    with pytest.raises(ValueError, match=r"(?s)--source-compiler clang matches none of the compilers.*gcc@16.2.1  /usr"):
        cli._run_bootstrap(_bootstrap_args(tmp_path, source_compiler="clang"))


def test_bootstrap_refuses_an_ambiguous_choice(monkeypatch, tmp_path: Path):
    import pytest
    from seanerstack.discovery import Found
    _bootstrap_world(monkeypatch, tmp_path, compilers=[Found("gcc@14.2.1", "/usr"), Found("gcc@14.3.1", "/opt/x")])

    with pytest.raises(ValueError, match="matches more than one"):
        cli._run_bootstrap(_bootstrap_args(tmp_path, source_compiler="gcc@14"))


def test_bootstrap_fails_on_another_operating_system(monkeypatch, tmp_path: Path):
    import pytest
    calls = _bootstrap_world(monkeypatch, tmp_path, system="fedora44")

    with pytest.raises(ValueError, match="this machine is fedora44, not rocky10"):
        cli._run_bootstrap(_bootstrap_args(tmp_path, os="rocky10"))
    assert not any(isinstance(call, tuple) for call in calls)


def test_an_external_compiler_excludes_building_one(monkeypatch, tmp_path: Path):
    import pytest
    from seanerstack.discovery import Found
    _bootstrap_world(monkeypatch, tmp_path, compilers=[Found("gcc@16.2.1", "/usr"), Found("gcc@14.2.1", "/usr")])

    with pytest.raises(ValueError, match="--compiler and --source-compiler do not apply"):
        cli._run_bootstrap(_bootstrap_args(tmp_path, external=["gcc@16"], source_compiler="gcc@14"))


def test_buildcache_update_index_rebuilds_the_toolchain_cache(monkeypatch, tmp_path: Path):
    _init_world(monkeypatch, tmp_path)
    rebuilt = []
    monkeypatch.setattr(cli, "update_index", lambda resource, **kwargs: rebuilt.append((resource.name, kwargs["env"])))
    monkeypatch.setattr(cli, "spack_resource_environment", lambda resource, secrets: {"SEANERSTACK_RESOURCE_CACHE_PASSWORD": "glpat"})
    args = _init_args(tmp_path, buildcache_command="update-index", cache=None)

    assert cli._run_buildcache(args) == 0
    assert rebuilt == [("cache", {"SEANERSTACK_RESOURCE_CACHE_PASSWORD": "glpat"})]


def test_init_pads_the_state_only_when_told_to(monkeypatch, tmp_path: Path):
    x, _ = _init_world(monkeypatch, tmp_path)
    padded = []
    monkeypatch.setattr(cli, "pad_install_tree", lambda config, length, **kwargs: padded.append((config, length)))

    cli._run_init(_init_args(tmp_path))
    assert padded == []
    cli._run_init(_init_args(tmp_path, padded_length=256))
    cli._run_init(_init_args(tmp_path, padded_length=0))
    assert padded == [(x.config, 256), (x.config, 0)]
    assert build_parser().parse_args(["init", "--padded-length", "256"]).padded_length == 256
    assert build_parser().parse_args(["init"]).padded_length is None
