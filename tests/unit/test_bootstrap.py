# SPDX-License-Identifier: Apache-2.0
import json
import subprocess

import pytest

import seanerstack.bootstrap as bootstrap_module


COMMAND = ["/opt/spack/bin/spack", "-C", "/state/spack/config"]
ENV = {"SPACK_DISABLE_LOCAL_CONFIG": "true"}
PREFIX = "/state/spack/opt/linux-rocky9/gcc-15.3.0-abcdef"
HASH = "abcdef"


def _fake_spack(monkeypatch, *, installed=False, external=False, probe_stdout="gcc@15", probe_timeout=False):
    """Stand in for the isolated spack command, recording every call made to it."""
    calls: list[list[str]] = []
    exists = {"value": installed}

    def fake_run(args, *, check=True, env=None, timeout=None):
        calls.append(args)
        if args[-3:-1] == ["find", "--json"]:
            # A build that used the compiler leaves an external record for its prefix.
            records = [{"hash": "ext0001", "external": {"path": PREFIX}}] if external else []
            if exists["value"]:
                records.append({"hash": HASH})
            if not records:
                return subprocess.CompletedProcess(args, 1, "", "")
            return subprocess.CompletedProcess(args, 0, json.dumps(records), "")
        if args[-3:-1] == ["location", "-i"]:
            if args[-1] != f"/{HASH}" or not exists["value"]:
                return subprocess.CompletedProcess(args, 1, "", "")
            return subprocess.CompletedProcess(args, 0, PREFIX + "\n", "")
        if "spec" in args:
            if probe_timeout:
                raise subprocess.TimeoutExpired(args, timeout or 0)
            return subprocess.CompletedProcess(args, 0, probe_stdout, "")
        return subprocess.CompletedProcess(args, 0, "", "")

    def fake_run_streaming(args, *, env=None):
        calls.append(args)
        # The compiler exists once it has been installed.
        exists["value"] = True

    monkeypatch.setattr(bootstrap_module, "_run", fake_run)
    monkeypatch.setattr(bootstrap_module, "_run_streaming", fake_run_streaming)
    return calls


def _remove(calls: list[list[str]]) -> list[str]:
    """The call that removes registered compilers before the installed one is registered."""
    (call,) = [call for call in calls if call[len(COMMAND):len(COMMAND) + 3] == ["compiler", "remove", "-a"]]
    return call


def _install(calls: list[list[str]]) -> list[str] | None:
    """The call that installs gcc@15, whatever else it asks for."""
    for call in calls:
        if call[len(COMMAND):len(COMMAND) + 2] == ["install", "gcc@15"]:
            return call
    return None


def test_bootstrap_uses_isolated_spack_command(monkeypatch):
    calls = _fake_spack(monkeypatch)

    result = bootstrap_module.bootstrap(
        "gcc@15", languages=("c", "cxx"), probe="zlib", command=COMMAND, env=ENV
    )

    assert result.compiler == "gcc@15"
    assert _install(calls) is not None
    assert [*COMMAND, "config", "add", "packages:c:require:gcc@15"] in calls
    assert [*COMMAND, "config", "add", "packages:cxx:require:gcc@15"] in calls


def test_bootstrap_registers_the_compiler_as_an_external(monkeypatch):
    calls = _fake_spack(monkeypatch)

    result = bootstrap_module.bootstrap(
        "gcc@15", languages=("c",), probe="zlib", command=COMMAND, env=ENV
    )

    assert result.registered is True
    assert [*COMMAND, "compiler", "find", PREFIX] in calls


def test_bootstrap_registers_before_requiring(monkeypatch):
    # A requirement written before the compiler is an external cannot be
    # satisfied: it forbids reusing the compiler's own build tree.
    calls = _fake_spack(monkeypatch)

    bootstrap_module.bootstrap(
        "gcc@15", languages=("c",), probe="zlib", command=COMMAND, env=ENV
    )

    find = calls.index([*COMMAND, "compiler", "find", PREFIX])
    require = calls.index([*COMMAND, "config", "add", "packages:c:require:gcc@15"])
    assert find < require


def test_bootstrap_registers_a_system_compiler_before_installing(monkeypatch):
    # An isolated state directory starts with no compiler registered at all,
    # so nothing can satisfy the c/cxx virtuals needed to build the project's
    # own compiler unless a system one is found first.
    calls = _fake_spack(monkeypatch)

    bootstrap_module.bootstrap(
        "gcc@15", languages=("c",), probe="zlib", command=COMMAND, env=ENV
    )

    find_system = calls.index([*COMMAND, "compiler", "find"])
    install = calls.index(_install(calls))
    assert find_system < install


def test_bootstrap_skips_system_compiler_registration_when_already_installed(monkeypatch):
    calls = _fake_spack(monkeypatch, installed=True)

    bootstrap_module.bootstrap(
        "gcc@15", languages=("c",), probe="zlib", command=COMMAND, env=ENV
    )

    assert [*COMMAND, "compiler", "find"] not in calls


def test_bootstrap_registers_an_already_installed_compiler(monkeypatch):
    calls = _fake_spack(monkeypatch, installed=True)

    bootstrap_module.bootstrap(
        "gcc@15", languages=("c",), probe="zlib", command=COMMAND, env=ENV
    )

    assert _install(calls) is None
    assert [*COMMAND, "compiler", "find", PREFIX] in calls


def test_bootstrap_ignores_the_external_record_of_an_installed_compiler(monkeypatch):
    calls = _fake_spack(monkeypatch, installed=True, external=True)

    bootstrap_module.bootstrap(
        "gcc@15", languages=("c",), probe="zlib", command=COMMAND, env=ENV
    )

    assert _install(calls) is None
    assert [*COMMAND, "compiler", "find", PREFIX] in calls


def test_bootstrap_installs_when_only_an_external_record_exists(monkeypatch):
    calls = _fake_spack(monkeypatch, external=True)

    bootstrap_module.bootstrap(
        "gcc@15", languages=("c",), probe="zlib", command=COMMAND, env=ENV
    )

    assert _install(calls) is not None
    assert [*COMMAND, "compiler", "find", PREFIX] in calls


def test_bootstrap_reports_a_probe_that_never_finishes(monkeypatch):
    _fake_spack(monkeypatch, probe_timeout=True)

    with pytest.raises(RuntimeError, match="did not concretize compiler probe"):
        bootstrap_module.bootstrap(
            "gcc@15", languages=("c",), probe="zlib", command=COMMAND, env=ENV, probe_timeout=1
        )


def test_the_target_requirement_replaces_an_earlier_one(monkeypatch):
    calls = _fake_spack(monkeypatch)

    bootstrap_module.require_target(COMMAND, "x86_64_v3", ENV)

    assert calls == [
        [*COMMAND, "config", "remove", "packages:all:require"],
        [*COMMAND, "config", "add", "packages:all:require:target=x86_64_v3"],
    ]


def test_bootstrap_dry_run_changes_nothing(monkeypatch):
    calls = _fake_spack(monkeypatch)

    result = bootstrap_module.bootstrap(
        "gcc@15", languages=("c",), probe="zlib", command=COMMAND, env=ENV, dry_run=True
    )

    assert result.registered is False
    assert not any(call[-3:-1] == ["compiler", "find"] for call in calls)
    assert not any("require" in part for call in calls for part in call)


def test_bootstrap_builds_the_compiler_rather_than_take_a_system_one(monkeypatch):
    # A system compiler of the same version is registered as an external, and
    # an external satisfying the spec would be taken instead of a build. An
    # external has no dependencies, so asking for a C compiler rules it out.
    calls = _fake_spack(monkeypatch)

    bootstrap_module.bootstrap(
        "gcc@15", languages=("c",), probe="zlib", command=COMMAND, env=ENV
    )

    assert _install(calls) == [*COMMAND, "install", "gcc@15", "%c"]


def test_bootstrap_leaves_only_the_installed_compiler_registered(monkeypatch):
    # The system compiler that built it would satisfy the requirements too.
    calls = _fake_spack(monkeypatch)

    bootstrap_module.bootstrap(
        "gcc@15", languages=("c",), probe="zlib", command=COMMAND, env=ENV
    )

    remove = calls.index(_remove(calls))
    register = calls.index([*COMMAND, "compiler", "find", PREFIX])
    require = calls.index([*COMMAND, "config", "add", "packages:c:require:gcc@15"])
    assert remove < register < require


def test_bootstrap_leaves_only_an_already_installed_compiler_registered(monkeypatch):
    calls = _fake_spack(monkeypatch, installed=True)

    bootstrap_module.bootstrap(
        "gcc@15", languages=("c",), probe="zlib", command=COMMAND, env=ENV
    )

    assert calls.index(_remove(calls)) < calls.index(
        [*COMMAND, "compiler", "find", PREFIX]
    )


def test_bootstrap_dry_run_removes_no_compiler(monkeypatch):
    calls = _fake_spack(monkeypatch)

    bootstrap_module.bootstrap(
        "gcc@15", languages=("c",), probe="zlib", command=COMMAND, env=ENV, dry_run=True
    )

    assert not any(call[len(COMMAND):len(COMMAND) + 2] == ["compiler", "remove"] for call in calls)


def test_bootstrap_builds_the_compiler_with_the_source_compiler(monkeypatch):
    calls = _fake_spack(monkeypatch)

    bootstrap_module.bootstrap(
        "gcc@15", languages=("c",), probe="zlib", command=COMMAND, env=ENV, source_compiler="gcc@14.2.1"
    )

    assert _install(calls) == [*COMMAND, "install", "gcc@15", "%c,cxx=gcc@14.2.1"]


def test_bootstrap_removes_only_the_compilers_its_spec_matches(monkeypatch):
    # gcc@16 or clang, found by init, stay for --source-compiler.
    calls = _fake_spack(monkeypatch)

    bootstrap_module.bootstrap("gcc@15", languages=("c",), probe="zlib", command=COMMAND, env=ENV)

    assert _remove(calls) == [*COMMAND, "compiler", "remove", "-a", "gcc@15"]


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
