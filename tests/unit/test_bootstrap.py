# SPDX-License-Identifier: Apache-2.0
import json
import subprocess

import pytest
import yaml

import seanerstack.bootstrap as bootstrap_module


COMMAND = ["/opt/spack/bin/spack", "-C", "/state/spack/config"]
ENV = {"SPACK_DISABLE_LOCAL_CONFIG": "true"}


def _fake_spack(monkeypatch):
    """Stand in for the isolated spack command, recording every call made to it."""
    calls: list[list[str]] = []

    def fake_run(args, *, check=True, env=None, timeout=None):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(bootstrap_module, "_run", fake_run)
    monkeypatch.setattr(bootstrap_module, "_run_streaming", lambda args, *, env=None: calls.append(args))
    return calls


def _packages(config):
    return yaml.safe_load((config / "packages.yaml").read_text())["packages"]


def test_the_target_requirement_replaces_an_earlier_one(tmp_path):
    (tmp_path / "packages.yaml").write_text("packages:: {}\n")

    bootstrap_module.require_target(tmp_path, "x86_64_v2")
    bootstrap_module.require_target(tmp_path, "x86_64_v3")

    assert _packages(tmp_path) == {"all": {"require": ["target=x86_64_v3"]}}


def _rule(language, compiler="gcc@15", name="gcc"):
    return {"any_of": [f"%{language}={compiler}"] * 2, "when": f"%{language}={name}"}


def test_the_target_requirement_keeps_the_compiler_rule(tmp_path):
    # init sets the target again after bootstrap has written the rule.
    bootstrap_module.require_target(tmp_path, "x86_64_v2")
    bootstrap_module._require_compiler_where_used(tmp_path, ("c", "cxx"), "gcc@15")

    bootstrap_module.require_target(tmp_path, "x86_64_v3")

    assert _packages(tmp_path)["all"]["require"] == ["target=x86_64_v3", _rule("c"), _rule("cxx")]


def test_the_compiler_is_required_on_every_package_that_takes_a_language_from_it(tmp_path):
    bootstrap_module._require_compiler_where_used(tmp_path, ("c", "cxx", "fortran"), "gcc@15")

    # The condition names the compiler on the edge: the bare %cxx also holds for a
    # C library built with CMake. Twice the same spec, because Spack warns about one.
    assert _packages(tmp_path) == {"all": {"require": [_rule("c"), _rule("cxx"), _rule("fortran")]}}


def test_the_compiler_rule_replaces_an_earlier_one_and_the_requirement_on_the_language(tmp_path):
    earlier = {
        "packages": {
            "all": {"require": ["target=x86_64_v3", _rule("c", "gcc@14"), {"spec": "+pic", "when": "+shared"}]},
            # What Seanerstack wrote before, which has no solution with a reused compiler.
            "c": {"require": ["gcc@14"]},
            "cxx": {"require": ["gcc@14"], "prefer": ["gcc@14"]},
            "gcc": {"externals": [{"spec": "gcc@14.4.1", "prefix": "/usr"}]},
        }
    }
    (tmp_path / "packages.yaml").write_text(yaml.safe_dump(earlier))

    bootstrap_module._require_compiler_where_used(tmp_path, ("c",), "gcc@15")
    bootstrap_module._require_compiler_where_used(tmp_path, ("c",), "gcc@15")

    assert _packages(tmp_path) == {
        "all": {"require": ["target=x86_64_v3", {"spec": "+pic", "when": "+shared"}, _rule("c")]},
        "cxx": {"prefer": ["gcc@14"]},
        "gcc": {"externals": [{"spec": "gcc@14.4.1", "prefix": "/usr"}]},
    }


def test_the_compiler_rule_names_the_package_of_the_compiler(tmp_path):
    bootstrap_module._require_compiler_where_used(tmp_path, ("c",), "llvm@19+clang")
    assert _packages(tmp_path)["all"]["require"] == [_rule("c", "llvm@19+clang", "llvm")]
    with pytest.raises(ValueError, match="cannot determine compiler package name"):
        bootstrap_module._require_compiler_where_used(tmp_path, ("c",), "@15")


def test_a_single_requirement_on_every_package_is_kept(tmp_path):
    (tmp_path / "packages.yaml").write_text("packages:\n  all:\n    require: target=x86_64_v3\n")
    bootstrap_module._require_compiler_where_used(tmp_path, ("c",), "gcc@15")
    assert _packages(tmp_path)["all"]["require"] == ["target=x86_64_v3", _rule("c")]


def test_bootstrap_writes_the_compiler_rule_and_no_requirement_on_the_language(monkeypatch, tmp_path):
    calls, state = _toolchain_spack(monkeypatch, tmp_path)

    bootstrap_module.bootstrap("gcc@15", languages=("c", "cxx"), probe="zlib", **state)

    assert _packages(state["spack_config"]) == {"all": {"require": [_rule("c"), _rule("cxx")]}}
    assert not any("require" in " ".join(call) and "config" in call for call in calls)


def test_an_external_compiler_removes_the_rule_of_a_built_one(monkeypatch, tmp_path):
    # An external has no tree of its own, and is required on the language.
    _fake_spack(monkeypatch)
    bootstrap_module.require_target(tmp_path, "x86_64_v3")
    bootstrap_module._require_compiler_where_used(tmp_path, ("c",), "gcc@15")
    monkeypatch.setattr(bootstrap_module, "_bootstrap_external", lambda *args, **kwargs: "external")

    result = bootstrap_module.bootstrap(
        "gcc@16", languages=("c",), probe="zlib", command=COMMAND, env=ENV, external=str(tmp_path), spack_config=tmp_path
    )

    assert result == "external"
    assert _packages(tmp_path) == {"all": {"require": ["target=x86_64_v3"]}}


def test_an_external_compiler_takes_no_source_compiler(monkeypatch):
    _fake_spack(monkeypatch)
    with pytest.raises(ValueError, match="takes no source compiler"):
        bootstrap_module.bootstrap(
            "gcc@16", languages=("c",), probe="zlib", command=COMMAND, env=ENV, external="/usr", source_compiler="gcc@14"
        )


def test_an_external_package_is_registered_and_never_built(monkeypatch, tmp_path):
    calls = _fake_spack(monkeypatch)
    (tmp_path / "bin").mkdir()

    bootstrap_module.use_external_package(COMMAND, "rust", str(tmp_path), ENV)

    assert calls == [
        [*COMMAND, "external", "find", "--path", str(tmp_path / "bin"), "rust"],
        [*COMMAND, "config", "add", "packages:rust:buildable:false"],
    ]


def test_the_toolchain_packages_are_installed_together(monkeypatch):
    calls = _fake_spack(monkeypatch)
    bootstrap_module.install_packages(COMMAND, ["rust", "capnproto"], ENV)
    bootstrap_module.install_packages(COMMAND, [], ENV)
    assert calls == [[*COMMAND, "install", "rust", "capnproto"]]


HASH = "abcdefabcdefabcdefabcdefabcdefab"


def _probe(compiler_hash=HASH, external=False):
    """`spack spec --json zlib`: the probe, compiled by a gcc with that hash."""
    compiler = {"name": "gcc", "version": "15.3.0", "hash": compiler_hash}
    if external:
        compiler["external"] = {"path": "/usr"}
    root = {
        "name": "zlib", "version": "1.3", "hash": "zlibhash",
        "dependencies": [{"name": "gcc", "hash": compiler_hash, "parameters": {"virtuals": ["c"]}}],
    }
    return "==> Installing clingo-bootstrap\n" + json.dumps({"spec": {"nodes": [root, compiler]}})


BOOTSTRAP_COMMAND = ["/opt/spack/bin/spack", "-C", "/state/bootstrap/config"]
FIRST = "fffffffffffffffffffffffffffffff1"


def _toolchain_spack(
    monkeypatch, state, *, installed=False, probe=None, probe_timeout=False, probe_stderr=None, records=None,
    earlier_first=None, cache_holds=True,
):
    """Stand in for Spack with a compiler environment and a bootstrap instance below `state`."""
    environment, config = state / "environments" / "compiler", state / "config"
    config.mkdir(parents=True)
    calls: list[list[str]] = []
    instance = bootstrap_module.BootstrapInstance(
        command=BOOTSTRAP_COMMAND, env={"SPACK_USER_CONFIG_PATH": "/state/bootstrap/config"},
        environment=state / "bootstrap" / "environments" / "compiler", store=state / "bootstrap" / "store",
    )
    if installed:
        environment.mkdir(parents=True)
        (environment / "spack.lock").write_text("{}")

    def fake_run(args, *, check=True, env=None, timeout=None):
        calls.append(args)
        if args[: len(BOOTSTRAP_COMMAND)] == BOOTSTRAP_COMMAND:
            output = ""
            if args[-3:-1] == ["find", "--json"]:
                output = json.dumps([{"hash": earlier_first}] if earlier_first else [])
            elif "location" in args:
                output = f"{instance.store}/gcc-15.3.0\n"
            return subprocess.CompletedProcess(args, 0, output, "")
        if args[-3:-1] == ["find", "--json"]:
            return subprocess.CompletedProcess(args, 0, json.dumps(records if records is not None else [{"hash": HASH}]), "")
        if "spec" in args:
            if probe_timeout:
                raise subprocess.TimeoutExpired(args, timeout or 0, output=b"==> Installing clingo-bootstrap\n", stderr=probe_stderr)
            return subprocess.CompletedProcess(args, 0, probe or _probe(), "")
        return subprocess.CompletedProcess(args, 0, "", "")

    def fake_run_streaming(args, *, env=None):
        calls.append(args)
        if args[: len(BOOTSTRAP_COMMAND)] == BOOTSTRAP_COMMAND:
            if args[-2:] == ["concretize", "--force"]:
                (instance.environment / "spack.lock").write_text(json.dumps({"roots": [{"hash": FIRST}]}))
            return
        if "--cache-only" in args and not cache_holds:
            raise subprocess.CalledProcessError(1, args)
        if args[-2:] == ["concretize", "--force"]:
            (environment / "spack.lock").write_text("{}")

    require = bootstrap_module._require_compiler_where_used

    def fake_require(spack_config, languages, compiler):
        # A step among the Spack commands, so that a test can tell when the rule is written.
        calls.append([*COMMAND, "require", str(compiler)])
        require(spack_config, languages, compiler)

    monkeypatch.setattr(bootstrap_module, "_run", fake_run)
    monkeypatch.setattr(bootstrap_module, "_run_streaming", fake_run_streaming)
    monkeypatch.setattr(bootstrap_module, "_require_compiler_where_used", fake_require)
    return calls, dict(command=COMMAND, env=ENV, environment=environment, spack_config=config, bootstrap_instance=instance)


def _steps(calls):
    """The Spack subcommands in the order they ran, without the command and the environment."""
    return [" ".join(call[len(COMMAND):]).replace(f"-e {call[len(COMMAND) + 1]} ", "") if call[len(COMMAND)] == "-e" else " ".join(call[len(COMMAND):]) for call in calls]


def test_bootstrap_installs_the_compiler_in_an_environment_of_its_own(monkeypatch, tmp_path):
    calls, state = _toolchain_spack(monkeypatch, tmp_path)

    result = bootstrap_module.bootstrap("gcc@15", languages=("c", "cxx"), probe="zlib", **state)

    manifest = yaml.safe_load((state["environment"] / "spack.yaml").read_text())["spack"]
    # A C compiler as dependency, so that a system gcc 15 is not taken instead of a build.
    assert manifest["specs"] == ["gcc@15 %c,cxx=gcc@15"] and manifest["view"] is False
    steps = _where(calls)
    # A fresh state has no compiler registered that could build the first stage.
    assert steps.index("bootstrap: compiler find") < steps.index("bootstrap: concretize --force")
    assert steps.index("actual: concretize --force") < steps.index("actual: install")
    assert (result.hash, result.registered, result.probe_ok) == (HASH, False, True)


def test_bootstrap_lets_the_concretizer_reuse_the_compiler_environment_and_nothing_else(monkeypatch, tmp_path):
    calls, state = _toolchain_spack(monkeypatch, tmp_path)

    bootstrap_module.bootstrap("gcc@15", languages=("c",), probe="zlib", **state)

    settings = yaml.safe_load((state["spack_config"] / "concretizer.yaml").read_text())
    # Only the compiler: what it was built with stays the system compiler's, and the stack builds its own.
    source = {"type": "environment", "path": str(state["environment"]), "include": ["gcc@15"]}
    assert settings == {"concretizer": {"reuse": {"from": [source]}}}
    # The built compiler is no external: only the first stage is registered by its prefix.
    registered = [step for step in _where(calls) if step.startswith("actual: compiler find ")]
    assert registered == [f"actual: compiler find {state['bootstrap_instance'].store}/gcc-15.3.0"]


def test_bootstrap_requires_the_compiler_only_once_it_can_be_reused(monkeypatch, tmp_path):
    calls, state = _toolchain_spack(monkeypatch, tmp_path)
    written = []
    reuse = bootstrap_module._reuse_environment
    monkeypatch.setattr(bootstrap_module, "_reuse_environment", lambda *args: (written.append(len(calls)), reuse(*args)))

    bootstrap_module.bootstrap("gcc@15", languages=("c",), probe="zlib", **state)

    steps = _steps(calls)
    # A system gcc 15, or the external record of an earlier Seanerstack, would satisfy the requirement too.
    assert steps.index("install") < written[0] <= steps.index("compiler remove -a gcc@15")
    assert steps.index("compiler remove -a gcc@15") < steps.index("require gcc@15")


def test_bootstrap_builds_nothing_when_the_environment_has_the_compiler(monkeypatch, tmp_path):
    calls, state = _toolchain_spack(monkeypatch, tmp_path, installed=True)

    result = bootstrap_module.bootstrap("gcc@15", languages=("c",), probe="zlib", **state)

    steps = _steps(calls)
    assert "install" not in steps and "compiler find" not in steps
    assert "require gcc@15" in steps
    assert result.probe_ok


def test_bootstrap_builds_again_when_forced(monkeypatch, tmp_path):
    calls, state = _toolchain_spack(monkeypatch, tmp_path, installed=True)
    bootstrap_module.bootstrap("gcc@15", languages=("c",), probe="zlib", force=True, **state)
    assert "install" in _steps(calls)


def test_bootstrap_ignores_an_external_of_the_same_spec_in_the_environment(monkeypatch, tmp_path):
    records = [{"hash": "ext0001", "external": {"path": "/usr"}}, {"hash": HASH}]
    _, state = _toolchain_spack(monkeypatch, tmp_path, installed=True, records=records)
    assert bootstrap_module.bootstrap("gcc@15", languages=("c",), probe="zlib", **state).hash == HASH


def test_the_probe_fails_when_another_compiler_built_it(monkeypatch, tmp_path):
    for probe in (_probe(compiler_hash="another"), _probe(external=True)):
        _, state = _toolchain_spack(monkeypatch, tmp_path / probe[-8:-4].strip('"'), probe=probe)
        assert not bootstrap_module.bootstrap("gcc@15", languages=("c",), probe="zlib", **state).probe_ok


def test_bootstrap_reports_a_probe_that_never_finishes(monkeypatch, tmp_path):
    _, state = _toolchain_spack(monkeypatch, tmp_path, probe_timeout=True)
    with pytest.raises(RuntimeError, match="did not concretize compiler probe"):
        bootstrap_module.bootstrap("gcc@15", languages=("c",), probe="zlib", probe_timeout=1, **state)


def test_a_probe_that_never_finishes_reports_what_spack_printed_and_names_no_cause(monkeypatch, tmp_path):
    _, state = _toolchain_spack(monkeypatch, tmp_path, probe_timeout=True, probe_stderr="==> Warning: no index\n")
    with pytest.raises(RuntimeError) as error:
        bootstrap_module.bootstrap("gcc@15", languages=("c",), probe="zlib", probe_timeout=1, **state)
    message = str(error.value)
    # Captured output of a command that timed out arrives as bytes or as text.
    assert "Until then it printed:\n==> Installing clingo-bootstrap\n==> Warning: no index\n" in message
    assert "usually means" not in message
    assert "Run `spack spec zlib` in this state without a limit" in message


def test_a_probe_that_printed_nothing_says_so(monkeypatch, tmp_path):
    _, state = _toolchain_spack(monkeypatch, tmp_path, probe_timeout=True)
    monkeypatch.setattr(
        bootstrap_module, "_run", lambda args, **kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired(args, 1))
        if "spec" in args else subprocess.CompletedProcess(args, 0, json.dumps([{"hash": HASH}]), ""),
    )
    (state["environment"]).mkdir(parents=True)
    (state["environment"] / "spack.lock").write_text("{}")
    with pytest.raises(RuntimeError, match="It printed nothing until then."):
        bootstrap_module.bootstrap("gcc@15", languages=("c",), probe="zlib", probe_timeout=1, **state)


def test_bootstrap_says_when_the_compiler_is_installed_before_anything_requires_it(monkeypatch, tmp_path):
    for name, installed in (("built", False), ("found", True)):
        calls, state = _toolchain_spack(monkeypatch, tmp_path / name, installed=installed)
        bootstrap_module.bootstrap(
            "gcc@15", languages=("c",), probe="zlib", installed_compiler=lambda: calls.append([*COMMAND, "told"]), **state
        )
        steps = _steps(calls)
        assert steps.count("told") == 1
        if not installed:
            assert steps.index("install") < steps.index("told")
        assert steps.index("told") < steps.index("require gcc@15") < steps.index("spec --json zlib")


def test_a_dry_run_installs_nothing_to_tell_of(monkeypatch, tmp_path):
    calls, state = _toolchain_spack(monkeypatch, tmp_path)
    told = []
    bootstrap_module.bootstrap(
        "gcc@15", languages=("c",), probe="zlib", dry_run=True, installed_compiler=lambda: told.append(1), **state
    )
    assert told == []


def _lockfile(path, root="gcc@15 %c,cxx=gcc@15"):
    path.write_text(json.dumps({"roots": [{"hash": HASH, "spec": root}], "concrete_specs": {HASH: {"name": "gcc"}}}))
    return path


def test_bootstrap_installs_the_compiler_of_a_lockfile_without_concretizing(monkeypatch, tmp_path):
    calls, state = _toolchain_spack(monkeypatch, tmp_path)
    lockfile = _lockfile(tmp_path / "rocky10.lock")

    result = bootstrap_module.bootstrap("gcc@15", languages=("c",), probe="zlib", lockfile=lockfile, **state)

    steps = _steps(calls)
    # A machine without gfortran would concretize the compiler to a hash that no cache holds.
    assert "concretize --force" not in steps and "install --cache-only" in steps
    assert (state["environment"] / "spack.lock").read_text() == lockfile.read_text()
    assert yaml.safe_load((state["environment"] / "spack.yaml").read_text())["spack"]["specs"] == ["gcc@15 %c,cxx=gcc@15"]
    assert (result.hash, result.lockfile, result.probe_ok) == (HASH, lockfile, True)


def test_bootstrap_concretizes_when_the_lockfile_is_for_another_compiler(monkeypatch, tmp_path):
    for name, extra in (("other", {"lockfile": _lockfile(tmp_path / "gcc16.lock", "gcc@16 %c")}), ("none", {})):
        calls, state = _toolchain_spack(monkeypatch, tmp_path / name)
        result = bootstrap_module.bootstrap("gcc@15", languages=("c",), probe="zlib", **extra, **state)
        assert "concretize --force" in _steps(calls)
        assert result.lockfile is None


def test_bootstrap_concretizes_when_a_source_compiler_builds_the_compiler(monkeypatch, tmp_path):
    # The lockfile holds the compiler as Spack's own choice built it.
    calls, state = _toolchain_spack(monkeypatch, tmp_path)
    result = bootstrap_module.bootstrap(
        "gcc@15", languages=("c",), probe="zlib", source_compiler="gcc@14.2.1", lockfile=_lockfile(tmp_path / "rocky10.lock"), **state
    )
    assert "concretize --force" in _steps(calls)
    assert result.lockfile is None


def test_the_compiler_is_concretized_as_a_new_state_concretizes_it(monkeypatch, tmp_path):
    # With the rule in place and the earlier compiler reusable, the same spec gives another compiler.
    calls, state = _toolchain_spack(monkeypatch, tmp_path, installed=True)
    config = state["spack_config"]
    bootstrap_module.require_target(config, "x86_64_v3")
    bootstrap_module._require_compiler_where_used(config, ("c",), "gcc@15")
    bootstrap_module._reuse_environment(config, state["environment"], "gcc@15")
    seen = {}
    streaming = bootstrap_module._run_streaming

    def concretize(args, *, env=None):
        if args[-2:] == ["concretize", "--force"]:
            seen["packages"] = _packages(config)
            seen["concretizer"] = yaml.safe_load((config / "concretizer.yaml").read_text())
        streaming(args, env=env)

    monkeypatch.setattr(bootstrap_module, "_run_streaming", concretize)

    bootstrap_module.bootstrap("gcc@15", languages=("c",), probe="zlib", force=True, **state)

    assert seen == {"packages": {"all": {"require": ["target=x86_64_v3"]}}, "concretizer": {"concretizer": {"reuse": False}}}
    # Both are back once the compiler is installed.
    assert _packages(config)["all"]["require"] == ["target=x86_64_v3", _rule("c")]
    assert "reuse" in yaml.safe_load((config / "concretizer.yaml").read_text())["concretizer"]


def test_a_lockfile_is_installed_with_the_configuration_as_it_is(monkeypatch, tmp_path):
    # Nothing is concretized, so nothing has to be taken out first.
    calls, state = _toolchain_spack(monkeypatch, tmp_path)
    taken_out = []
    monkeypatch.setattr(bootstrap_module, "_concretize_as_a_new_state_does", lambda spack_config: taken_out.append(spack_config))

    bootstrap_module.bootstrap("gcc@15", languages=("c",), probe="zlib", lockfile=_lockfile(tmp_path / "rocky10.lock"), **state)

    assert taken_out == []


def test_bootstrap_dry_run_changes_nothing(monkeypatch, tmp_path):
    calls, state = _toolchain_spack(monkeypatch, tmp_path)

    result = bootstrap_module.bootstrap("gcc@15", languages=("c",), probe="zlib", dry_run=True, **state)

    assert calls == [] and result.hash is None
    assert not state["environment"].exists() and not (state["spack_config"] / "concretizer.yaml").exists()


def test_bootstrap_needs_the_state_it_installs_into(monkeypatch):
    _fake_spack(monkeypatch)
    with pytest.raises(ValueError, match="compiler environment and the Spack configuration"):
        bootstrap_module.bootstrap("gcc@15", languages=("c",), probe="zlib", command=COMMAND, env=ENV)


def _where(calls):
    """The steps of `_steps`, each with the instance it ran in: bootstrap or actual."""
    return [("bootstrap: " if call[: len(BOOTSTRAP_COMMAND)] == BOOTSTRAP_COMMAND else "actual: ") + step for call, step in zip(calls, _steps(calls))]


def _manifest(environment):
    return yaml.safe_load((environment / "spack.yaml").read_text())["spack"]["specs"]


def test_the_first_stage_is_built_in_the_bootstrap_instance_for_c_and_cxx_only(monkeypatch, tmp_path):
    calls, state = _toolchain_spack(monkeypatch, tmp_path)

    bootstrap_module.bootstrap("gcc@15", languages=("c",), probe="zlib", **state)

    # Only what building the compiler needs, without GCC's own bootstrap: much quicker than a full GCC.
    assert _manifest(state["bootstrap_instance"].environment) == ["gcc@15 languages:=c,c++ ~bootstrap ~binutils %c"]
    steps = _where(calls)
    assert steps.index("bootstrap: compiler find") < steps.index("bootstrap: concretize --force") < steps.index("bootstrap: install")


def test_the_source_compiler_builds_the_first_stage(monkeypatch, tmp_path):
    _, state = _toolchain_spack(monkeypatch, tmp_path)
    bootstrap_module.bootstrap("gcc@15", languages=("c",), probe="zlib", source_compiler="gcc@14.2.1", **state)
    assert _manifest(state["bootstrap_instance"].environment) == ["gcc@15 languages:=c,c++ ~bootstrap ~binutils %c,cxx=gcc@14.2.1"]


def test_the_first_stage_is_the_only_gcc_that_builds_the_compiler(monkeypatch, tmp_path):
    calls, state = _toolchain_spack(monkeypatch, tmp_path)

    result = bootstrap_module.bootstrap("gcc@15", languages=("c",), probe="zlib", **state)

    prefix = f"{state['bootstrap_instance'].store}/gcc-15.3.0"
    assert _manifest(state["environment"]) == ["gcc@15 %c,cxx=gcc@15"]
    steps = _where(calls)
    # The system gcc would record itself in the compiler environment.
    assert steps.index("bootstrap: install") < steps.index("actual: compiler remove -a gcc")
    assert steps.index("actual: compiler remove -a gcc") < steps.index(f"actual: compiler find {prefix}")
    assert steps.index(f"actual: compiler find {prefix}") < steps.index("actual: concretize --force") < steps.index("actual: install")
    assert (result.first_stage, result.hash, result.probe_ok) == (prefix, HASH, True)


def test_the_system_compilers_come_back_once_the_compiler_is_built(monkeypatch, tmp_path):
    calls, state = _toolchain_spack(monkeypatch, tmp_path)

    bootstrap_module.bootstrap("gcc@15", languages=("c",), probe="zlib", **state)

    steps = _where(calls)
    after = steps[steps.index("actual: install"):]
    # The first stage leaves; what the system has comes back, without a gcc 15 that the rule would accept.
    assert after.index("actual: compiler remove -a gcc") < after.index("actual: compiler find")
    assert after.index("actual: compiler find") < after.index("actual: compiler remove -a gcc@15") < after.index("actual: require gcc@15")


def test_a_first_stage_of_another_system_compiler_leaves_its_path(monkeypatch, tmp_path):
    for earlier, uninstalled in (("0lderfirst", True), (FIRST, False)):
        calls, state = _toolchain_spack(monkeypatch, tmp_path / earlier, earlier_first=earlier)
        bootstrap_module.bootstrap("gcc@15", languages=("c",), probe="zlib", **state)
        steps = _where(calls)
        assert (f"bootstrap: uninstall --yes-to-all /{earlier}" in steps) is uninstalled
        if uninstalled:
            assert steps.index(f"bootstrap: uninstall --yes-to-all /{earlier}") < steps.index("bootstrap: install")


def _two_stage_lockfile(path, first_stage):
    path.write_text(json.dumps({
        "roots": [{"hash": HASH, "spec": "gcc@15 %c,cxx=gcc@15"}],
        "concrete_specs": {HASH: {"name": "gcc"}, FIRST: {"name": "gcc", "external": {"path": str(first_stage)}}},
    }))
    return path


def test_the_compiler_of_a_lockfile_comes_from_the_caches_without_a_first_stage(monkeypatch, tmp_path):
    calls, state = _toolchain_spack(monkeypatch, tmp_path)
    lockfile = _two_stage_lockfile(tmp_path / "rocky10.lock", "/ci/state/bootstrap/store/gcc-15.3.0")

    result = bootstrap_module.bootstrap("gcc@15", languages=("c",), probe="zlib", lockfile=lockfile, cache_only=True, **state)

    steps = _where(calls)
    assert "actual: install --cache-only" in steps and "actual: concretize --force" not in steps
    assert not any(step.startswith("bootstrap: ") for step in steps)
    assert (state["environment"] / "spack.lock").read_text() == lockfile.read_text()
    assert (result.lockfile, result.first_stage, result.probe_ok) == (lockfile, None, True)


def test_a_compiler_that_the_caches_lack_is_not_built_with_cache_only(monkeypatch, tmp_path):
    calls, state = _toolchain_spack(monkeypatch, tmp_path, cache_holds=False)
    lockfile = _two_stage_lockfile(tmp_path / "rocky10.lock", "/ci/state/bootstrap/store/gcc-15.3.0")

    with pytest.raises(RuntimeError, match="do not hold the compiler of the lockfile .* --concretize builds"):
        bootstrap_module.bootstrap("gcc@15", languages=("c",), probe="zlib", lockfile=lockfile, cache_only=True, **state)

    assert not any(step.startswith("bootstrap: ") for step in _where(calls))


def test_a_compiler_that_the_caches_lack_is_built_from_the_lockfile_in_its_state(monkeypatch, tmp_path):
    calls, state = _toolchain_spack(monkeypatch, tmp_path, cache_holds=False)
    lockfile = _two_stage_lockfile(tmp_path / "rocky10.lock", state["bootstrap_instance"].store / "gcc-15.3.0")

    result = bootstrap_module.bootstrap("gcc@15", languages=("c",), probe="zlib", lockfile=lockfile, **state)

    steps = _where(calls)
    assert steps.index("actual: install --cache-only") < steps.index("bootstrap: install") < steps.index("actual: install")
    assert "actual: concretize --force" not in steps
    assert result.first_stage == f"{state['bootstrap_instance'].store}/gcc-15.3.0"


def test_a_lockfile_of_another_state_directory_is_not_built_from(monkeypatch, tmp_path):
    # The lockfile names the first stage by its path, which another state does not have.
    calls, state = _toolchain_spack(monkeypatch, tmp_path, cache_holds=False)
    lockfile = _two_stage_lockfile(tmp_path / "rocky10.lock", "/ci/state/bootstrap/store/gcc-15.3.0")

    with pytest.raises(RuntimeError, match="records the first stage in /ci/state/bootstrap/store/gcc-15.3.0"):
        bootstrap_module.bootstrap("gcc@15", languages=("c",), probe="zlib", lockfile=lockfile, **state)

    assert "bootstrap: install" not in _where(calls)


def test_a_lockfile_of_two_stages_is_one_for_the_compiler(tmp_path):
    lockfile = _two_stage_lockfile(tmp_path / "rocky10.lock", "/ci/state/bootstrap/store/gcc-15.3.0")
    assert bootstrap_module.lockfile_for(lockfile, "gcc@15") == lockfile
    assert bootstrap_module.lockfile_for(lockfile, "gcc@16") is None


def test_an_installed_compiler_needs_no_first_stage(monkeypatch, tmp_path):
    calls, state = _toolchain_spack(monkeypatch, tmp_path, installed=True)
    result = bootstrap_module.bootstrap("gcc@15", languages=("c",), probe="zlib", **state)
    assert not any(step.startswith("bootstrap: ") for step in _where(calls))
    assert "actual: compiler remove -a gcc" not in _where(calls)
    assert (result.first_stage, result.probe_ok) == (None, True)


def test_installing_the_compiler_needs_the_bootstrap_instance(monkeypatch, tmp_path):
    calls, state = _toolchain_spack(monkeypatch, tmp_path)
    del state["bootstrap_instance"]
    with pytest.raises(ValueError, match="needs the bootstrap instance"):
        bootstrap_module.bootstrap("gcc@15", languages=("c",), probe="zlib", **state)
    assert calls == []
    # An installed compiler needs none.
    calls, state = _toolchain_spack(monkeypatch, tmp_path / "installed", installed=True)
    del state["bootstrap_instance"]
    assert bootstrap_module.bootstrap("gcc@15", languages=("c",), probe="zlib", **state).probe_ok


def test_both_instances_search_where_init_searched_for_compilers(monkeypatch, tmp_path):
    calls, state = _toolchain_spack(monkeypatch, tmp_path)
    instance = state["bootstrap_instance"]
    state["bootstrap_instance"] = bootstrap_module.BootstrapInstance(
        command=instance.command, env=instance.env, environment=instance.environment, store=instance.store,
        find=("/opt/rh/gcc-toolset-15/root/usr/bin",),
    )

    bootstrap_module.bootstrap("gcc@15", languages=("c",), probe="zlib", source_compiler="gcc@15.1.1", **state)

    steps = _where(calls)
    # Where the source compiler is, and where the system compilers come back.
    assert steps.index("bootstrap: compiler find /opt/rh/gcc-toolset-15/root/usr/bin") < steps.index("bootstrap: concretize --force")
    assert steps.index("actual: install") < steps.index("actual: compiler find /opt/rh/gcc-toolset-15/root/usr/bin")


def test_bootstrap_says_when_the_first_stage_is_installed_before_it_builds_the_compiler(monkeypatch, tmp_path):
    calls, state = _toolchain_spack(monkeypatch, tmp_path)

    bootstrap_module.bootstrap(
        "gcc@15", languages=("c",), probe="zlib", installed_first_stage=lambda: calls.append([*BOOTSTRAP_COMMAND, "told"]),
        **state,
    )

    steps = _where(calls)
    assert steps.count("bootstrap: told") == 1
    assert steps.index("bootstrap: install") < steps.index("bootstrap: told") < steps.index("actual: concretize --force")


def test_nothing_is_said_of_a_first_stage_when_the_caches_hold_the_compiler(monkeypatch, tmp_path):
    for name, cache_holds, told in (("cached", True, 0), ("built", False, 1)):
        calls, state = _toolchain_spack(monkeypatch, tmp_path / name, cache_holds=cache_holds)
        lockfile = _two_stage_lockfile(tmp_path / f"{name}.lock", state["bootstrap_instance"].store / "gcc-15.3.0")
        said = []
        bootstrap_module.bootstrap(
            "gcc@15", languages=("c",), probe="zlib", lockfile=lockfile, installed_first_stage=lambda: said.append(1), **state
        )
        assert len(said) == told
