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
        concretize=False,
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
    spack = f"{seanerstack.pins.SPACK_VERSION} at commit {seanerstack.pins.SPACK_COMMIT[:10]}"
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
    # `spack arch --operating-system`, which bootstrap asks for the lockfile of the platform.
    monkeypatch.setattr(cli.subprocess, "run", lambda args, **kwargs: cli.subprocess.CompletedProcess(args, 0, "rocky10\n", ""))
    # The build cache has no compiler lockfile for it; the tests of the lockfile give one.
    monkeypatch.setattr(cli, "find_compiler_lockfile", lambda config, env, **kwargs: None)
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
    monkeypatch.setattr(cli, "install_packages", lambda command, packages, env, **kwargs: calls.append(("install", list(packages))))
    monkeypatch.setattr(cli, "use_external_package", lambda command, name, prefix, env: calls.append(("external", name, prefix)))
    return calls


def _bootstrap_args(tmp_path: Path, **overrides):
    return _init_args(tmp_path, **{"compiler": None, "dry_run": False, **overrides})


def test_bootstrap_builds_the_compiler_then_rust_and_the_other_packages(monkeypatch, tmp_path: Path):
    calls = _bootstrap_world(monkeypatch, tmp_path)

    assert cli._run_bootstrap(_bootstrap_args(tmp_path)) == 0

    assert calls == ["target=x86_64_v3", ("bootstrap", "gcc@15", None, None), ("install", ["rust", "capnproto"])]


def test_bootstrap_installs_the_compiler_of_the_lockfile_for_this_operating_system(monkeypatch, tmp_path: Path, capsys):
    _bootstrap_world(monkeypatch, tmp_path, system="rocky10")
    given = []
    shipped = {"rocky10": tmp_path / "rocky10.lock"}
    monkeypatch.setattr(cli, "find_compiler_lockfile", lambda config, env, **kwargs: shipped.get(kwargs["operating_system"]))

    def fake_bootstrap(compiler, **kwargs):
        given.append(kwargs["lockfile"])
        return BootstrapResult(
            compiler=compiler, installed=True, registered=False, languages=("c",), probe="zlib", probe_ok=True,
            hash="abcdefabcdef", lockfile=kwargs["lockfile"],
        )

    monkeypatch.setattr(cli, "bootstrap", fake_bootstrap)

    assert cli._run_bootstrap(_bootstrap_args(tmp_path)) == 0
    assert "concretized: by the lockfile of rocky10" in capsys.readouterr().out
    # For a new lockfile, or on purpose with the system compiler of this machine.
    assert cli._run_bootstrap(_bootstrap_args(tmp_path, concretize=True)) == 0
    assert "concretized: on this machine" in capsys.readouterr().out

    assert given == [tmp_path / "rocky10.lock", None]


def test_bootstrap_builds_the_compiler_in_two_stages_and_takes_a_locked_one_from_the_caches_only(monkeypatch, tmp_path: Path, capsys):
    _bootstrap_world(monkeypatch, tmp_path)
    given = []

    def fake_bootstrap(compiler, **kwargs):
        given.append(kwargs)
        return BootstrapResult(
            compiler=compiler, installed=True, registered=False, languages=("c",), probe="zlib", probe_ok=True,
            hash="abcdefabcdef", first_stage="/state/bootstrap/store/gcc-15.3.0",
        )

    monkeypatch.setattr(cli, "bootstrap", fake_bootstrap)

    assert cli._run_bootstrap(_bootstrap_args(tmp_path)) == 0

    instance = given[0]["bootstrap_instance"]
    bootstrap = tmp_path / "state" / "bootstrap"
    # init searched nothing off PATH here.
    assert instance.find == ()
    assert instance.command[-2:] == ["-C", str(bootstrap / "config")]
    assert (instance.environment, instance.store) == (bootstrap / "environments" / "compiler", bootstrap / "store")
    # A build of the compiler takes hours; a machine takes the locked one from the caches or stops.
    assert given[0]["cache_only"] is True
    assert "built: in two stages, by the first stage in /state/bootstrap/store/gcc-15.3.0" in capsys.readouterr().out


def test_bootstrap_concretizes_where_no_lockfile_is_shipped(monkeypatch, tmp_path: Path):
    _bootstrap_world(monkeypatch, tmp_path, system="debian13")
    given = []
    shipped = {"rocky10": tmp_path / "rocky10.lock"}
    monkeypatch.setattr(cli, "find_compiler_lockfile", lambda config, env, **kwargs: shipped.get(kwargs["operating_system"]))
    monkeypatch.setattr(
        cli, "bootstrap",
        lambda compiler, **kwargs: given.append(kwargs["lockfile"]) or BootstrapResult(
            compiler=compiler, installed=True, registered=False, languages=("c",), probe="zlib", probe_ok=True
        ),
    )

    assert cli._run_bootstrap(_bootstrap_args(tmp_path)) == 0
    assert given == [None]


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
    monkeypatch.setattr(cli, "install_packages", lambda command, packages, env, **kwargs: environments.append(env))

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


def test_prepare_without_a_container_builds_with_the_bootstrap_instance_of_the_state(monkeypatch, tmp_path: Path):
    import seanerstack.isolation
    x = seanerstack.isolation.prepare_isolation(tmp_path / "state", tmp_path / "spack")
    monkeypatch.setattr(cli, "_runtime", lambda args: (Config(path=tmp_path / "config.toml", resources={}), None))
    monkeypatch.setattr(cli, "_spack_runtime", lambda args: (x, tmp_path / "spack", ["spack"], {}))
    given = []
    monkeypatch.setattr(cli, "prepare_here", lambda config, secrets, **kwargs: given.append(kwargs) or 0)

    args = build_parser().parse_args(["buildcache", "prepare", "--no-container", "--platform", "rocky10"])
    assert cli._run_buildcache(args) == 0

    instance = given[0]["bootstrap_instance"]
    assert instance.command == [str(tmp_path / "spack"), "-C", str(x.state / "bootstrap" / "config")]
    assert instance.store == x.state / "bootstrap" / "store"


def test_the_bootstrap_instance_searches_where_init_searched_for_compilers(tmp_path: Path):
    import json
    import seanerstack.isolation
    x = seanerstack.isolation.prepare_isolation(tmp_path / "state", tmp_path / "spack")
    toolset = tmp_path / "gcc-toolset-15"
    (toolset / "bin").mkdir(parents=True)
    x.record.write_text(json.dumps({"find": [str(toolset), str(tmp_path / "no-bin")]}), encoding="utf-8")

    instance = cli._bootstrap_instance(x, tmp_path / "spack", {})

    assert instance.find == (str(toolset / "bin"), str(tmp_path / "no-bin"))


def test_the_bootstrap_instance_reads_the_bootstrap_cache_and_builds_for_the_target(monkeypatch, tmp_path: Path):
    import seanerstack.isolation
    from seanerstack.config import Resource, Toolchain
    x = seanerstack.isolation.prepare_isolation(tmp_path / "state", tmp_path / "spack")
    boot = Resource(name="boot", kind="spack-buildcache", url="oci://registry.example.org/cache-bootstrap", credentials="c", signed=False)
    toolchain = Toolchain(compiler="gcc@15", packages=(), cache="cache", target="x86_64_v3", platforms={}, bootstrap_cache="boot")
    configured = []
    monkeypatch.setattr(cli, "configure_buildcache", lambda resource, *, command, env: configured.append((resource.name, command)))

    instance = cli._bootstrap_instance(
        x, tmp_path / "spack", {}, Config(path=tmp_path / "config.toml", resources={"boot": boot}, toolchain=toolchain), "x86_64_v3"
    )

    assert configured == [("boot", instance.command)]
    assert (instance.config, instance.target) == (x.state / "bootstrap" / "config", "x86_64_v3")


def test_bootstrap_checks_the_bootstrap_cache_only_where_it_builds_the_compiler(monkeypatch, tmp_path: Path):
    _bootstrap_world(monkeypatch, tmp_path)
    asked = []
    monkeypatch.setattr(cli, "require_cache_access", lambda command, env: asked.append(command))
    bootstrap_config = str(tmp_path / "state" / "bootstrap" / "config")

    # No lockfile: the compiler is built, and its first stage comes from the bootstrap cache.
    assert cli._run_bootstrap(_bootstrap_args(tmp_path)) == 0
    assert any(command[-1] == bootstrap_config for command in asked)

    asked.clear()
    monkeypatch.setattr(cli, "find_compiler_lockfile", lambda config, env, **kwargs: tmp_path / "rocky10.lock")
    assert cli._run_bootstrap(_bootstrap_args(tmp_path)) == 0
    assert not any(command[-1] == bootstrap_config for command in asked)


def test_bootstrap_asks_the_build_cache_for_the_lockfile_of_this_compiler_target_and_system(monkeypatch, tmp_path: Path):
    _bootstrap_world(monkeypatch, tmp_path, system="fedora45")
    asked = []
    monkeypatch.setattr(cli, "find_compiler_lockfile", lambda config, env, **kwargs: asked.append(kwargs))

    assert cli._run_bootstrap(_bootstrap_args(tmp_path)) == 0

    (kwargs,) = asked
    assert (kwargs["compiler"], kwargs["target"], kwargs["operating_system"]) == ("gcc@15", "x86_64_v3", "fedora45")
    assert kwargs["directory"] == tmp_path / "state" / "spack" / "environments" / "compiler-lockfiles"


def test_bootstrap_asks_for_no_lockfile_where_it_would_not_use_one(monkeypatch, tmp_path: Path):
    _bootstrap_world(monkeypatch, tmp_path)
    asked = []
    monkeypatch.setattr(cli, "find_compiler_lockfile", lambda config, env, **kwargs: asked.append(kwargs))
    for overrides in ({"concretize": True}, {"dry_run": True}):
        assert cli._run_bootstrap(_bootstrap_args(tmp_path, **overrides)) == 0
    assert asked == []


def test_bootstrap_with_a_config_of_no_resources_has_no_bootstrap_cache(monkeypatch, tmp_path: Path):
    # The end-to-end tests set up a state with a config.toml of no resources, which takes the shipped [toolchain].
    import seanerstack.isolation
    from seanerstack.config import load_config
    path = tmp_path / "config.toml"
    path.write_text("", encoding="utf-8")
    config = load_config(path)
    x = seanerstack.isolation.prepare_isolation(tmp_path / "state", tmp_path / "spack")
    configured = []
    monkeypatch.setattr(cli, "configure_buildcache", lambda resource, **kwargs: configured.append(resource.name))

    instance = cli._bootstrap_instance(x, tmp_path / "spack", {}, config, config.toolchain.target)

    assert config.toolchain.bootstrap_cache == "seanerstack-buildcache-bootstrap" and configured == []
    assert instance.target == "x86_64_v3"


def _publish_world(monkeypatch, tmp_path: Path, *, bootstrap_cache=True, compiler_lock=True):
    """init's world with a bootstrap cache and a compiler environment, recording what publish sends."""
    import json
    from seanerstack.config import Resource, Toolchain
    x, _ = _init_world(monkeypatch, tmp_path)
    cache = Resource(name="cache", kind="spack-buildcache", url="oci://registry.example.org/cache", credentials="registry", signed=False)
    boot = Resource(name="boot", kind="spack-buildcache", url="oci://registry.example.org/cache-bootstrap", credentials="registry", signed=False)
    toolchain = Toolchain(
        compiler="gcc@15", packages=(), cache="cache", target="x86_64_v3", platforms={},
        bootstrap_cache="boot" if bootstrap_cache else None,
    )
    monkeypatch.setattr(cli, "load_config", lambda path: Config(path=tmp_path / "config.toml", resources={"cache": cache, "boot": boot}, toolchain=toolchain))
    sent = []
    monkeypatch.setattr(cli, "configure_buildcache", lambda resource, **kwargs: None)
    monkeypatch.setattr(cli, "push_installed", lambda resource, *, command, env: sent.append(("push", resource.name, command)) or 3)
    monkeypatch.setattr(
        cli, "publish_compiler_lockfile",
        lambda resource, path, env, **kwargs: sent.append(("lockfile", resource.name, path, kwargs)) or ("compiler-tag", True),
    )
    if compiler_lock:
        environment = x.environments / "compiler"
        environment.mkdir(parents=True)
        (environment / "spack.lock").write_text(json.dumps({"roots": [{"hash": "abc", "spec": "gcc@15 %c,cxx=gcc@15"}]}))
    return x, sent


def test_publish_pushes_the_first_stage_and_publishes_the_compiler_lockfile(monkeypatch, tmp_path: Path, capsys):
    x, sent = _publish_world(monkeypatch, tmp_path)

    assert cli._run_publish(_init_args(tmp_path)) == 0

    push, lock = sent
    assert push[:2] == ("push", "boot") and push[2][-2:] == ["-C", str(x.state / "bootstrap" / "config")]
    assert lock[:3] == ("lockfile", "cache", x.environments / "compiler" / "spack.lock")
    # `spack arch --operating-system` of the stand-in answers rocky10.
    assert lock[3] == {"compiler": "gcc@15", "target": "x86_64_v3", "operating_system": "rocky10"}
    out = capsys.readouterr().out
    assert "first stage: 3 specs of the bootstrap instance in oci://registry.example.org/cache-bootstrap" in out
    assert "compiler lockfile: compiler-tag in oci://registry.example.org/cache" in out


def test_publish_leaves_out_what_the_state_or_the_config_does_not_have(monkeypatch, tmp_path: Path, capsys):
    _, sent = _publish_world(monkeypatch, tmp_path / "a", bootstrap_cache=False)
    assert cli._run_publish(_init_args(tmp_path / "a")) == 0
    assert [entry[0] for entry in sent] == ["lockfile"]
    assert "first stage: config.toml names no bootstrap cache" in capsys.readouterr().out

    _, sent = _publish_world(monkeypatch, tmp_path / "b", compiler_lock=False)
    assert cli._run_publish(_init_args(tmp_path / "b")) == 0
    assert [entry[0] for entry in sent] == ["push"]
    assert "compiler lockfile: none, the compiler environment holds no gcc@15 of two stages" in capsys.readouterr().out


def test_toolchain_publish_is_a_command():
    args = build_parser().parse_args(["toolchain", "publish"])
    assert (args.command, args.toolchain_command) == ("toolchain", "publish")
