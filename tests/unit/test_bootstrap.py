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


def _toolchain_spack(monkeypatch, state, *, installed=False, probe=None, probe_timeout=False, probe_stderr=None, records=None):
    """Stand in for Spack with a compiler environment below `state`."""
    environment, config = state / "environments" / "compiler", state / "config"
    config.mkdir(parents=True)
    calls: list[list[str]] = []
    if installed:
        environment.mkdir(parents=True)
        (environment / "spack.lock").write_text("{}")

    def fake_run(args, *, check=True, env=None, timeout=None):
        calls.append(args)
        if args[-3:-1] == ["find", "--json"]:
            return subprocess.CompletedProcess(args, 0, json.dumps(records if records is not None else [{"hash": HASH}]), "")
        if "spec" in args:
            if probe_timeout:
                raise subprocess.TimeoutExpired(args, timeout or 0, output=b"==> Installing clingo-bootstrap\n", stderr=probe_stderr)
            return subprocess.CompletedProcess(args, 0, probe or _probe(), "")
        return subprocess.CompletedProcess(args, 0, "", "")

    def fake_run_streaming(args, *, env=None):
        calls.append(args)
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
    return calls, dict(command=COMMAND, env=ENV, environment=environment, spack_config=config)


def _steps(calls):
    """The Spack subcommands in the order they ran, without the command and the environment."""
    return [" ".join(call[len(COMMAND):]).replace(f"-e {call[len(COMMAND) + 1]} ", "") if call[len(COMMAND)] == "-e" else " ".join(call[len(COMMAND):]) for call in calls]


def test_bootstrap_installs_the_compiler_in_an_environment_of_its_own(monkeypatch, tmp_path):
    calls, state = _toolchain_spack(monkeypatch, tmp_path)

    result = bootstrap_module.bootstrap("gcc@15", languages=("c", "cxx"), probe="zlib", **state)

    manifest = yaml.safe_load((state["environment"] / "spack.yaml").read_text())["spack"]
    # A C compiler as dependency, so that a system gcc 15 is not taken instead of a build.
    assert manifest["specs"] == ["gcc@15 %c"] and manifest["view"] is False
    steps = _steps(calls)
    # A fresh state has no compiler registered that could build it.
    assert steps.index("compiler find") < steps.index("concretize --force") < steps.index("install")
    assert (result.hash, result.registered, result.probe_ok) == (HASH, False, True)


def test_bootstrap_lets_the_concretizer_reuse_the_compiler_environment_and_nothing_else(monkeypatch, tmp_path):
    calls, state = _toolchain_spack(monkeypatch, tmp_path)

    bootstrap_module.bootstrap("gcc@15", languages=("c",), probe="zlib", **state)

    settings = yaml.safe_load((state["spack_config"] / "concretizer.yaml").read_text())
    # Only the compiler: what it was built with stays the system compiler's, and the stack builds its own.
    source = {"type": "environment", "path": str(state["environment"]), "include": ["gcc@15"]}
    assert settings == {"concretizer": {"reuse": {"from": [source]}}}
    # The built compiler is no external: nothing registers its prefix.
    assert not any(step.startswith("compiler find ") for step in _steps(calls))


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


def test_bootstrap_builds_the_compiler_with_the_source_compiler(monkeypatch, tmp_path):
    _, state = _toolchain_spack(monkeypatch, tmp_path)

    bootstrap_module.bootstrap("gcc@15", languages=("c",), probe="zlib", source_compiler="gcc@14.2.1", **state)

    manifest = yaml.safe_load((state["environment"] / "spack.yaml").read_text())["spack"]
    assert manifest["specs"] == ["gcc@15 %c,cxx=gcc@14.2.1"]


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


def _lockfile(path, root="gcc@15 %c"):
    path.write_text(json.dumps({"roots": [{"hash": HASH, "spec": root}], "concrete_specs": {HASH: {"name": "gcc"}}}))
    return path


def test_bootstrap_installs_the_compiler_of_a_lockfile_without_concretizing(monkeypatch, tmp_path):
    calls, state = _toolchain_spack(monkeypatch, tmp_path)
    lockfile = _lockfile(tmp_path / "rocky10.lock")

    result = bootstrap_module.bootstrap("gcc@15", languages=("c",), probe="zlib", lockfile=lockfile, **state)

    steps = _steps(calls)
    # A machine without gfortran would concretize the compiler to a hash that no cache holds.
    assert "concretize --force" not in steps and "install" in steps
    assert (state["environment"] / "spack.lock").read_text() == lockfile.read_text()
    assert yaml.safe_load((state["environment"] / "spack.yaml").read_text())["spack"]["specs"] == ["gcc@15 %c"]
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
