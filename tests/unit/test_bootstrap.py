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


def test_bootstrap_uses_isolated_spack_command(monkeypatch):
    calls = _fake_spack(monkeypatch)

    result = bootstrap_module.bootstrap(
        "gcc@15", languages=("c", "cxx"), probe="zlib", command=COMMAND, env=ENV
    )

    assert result.compiler == "gcc@15"
    assert [*COMMAND, "install", "gcc@15"] in calls
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
    install = calls.index([*COMMAND, "install", "gcc@15"])
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

    assert [*COMMAND, "install", "gcc@15"] not in calls
    assert [*COMMAND, "compiler", "find", PREFIX] in calls


def test_bootstrap_ignores_the_external_record_of_an_installed_compiler(monkeypatch):
    calls = _fake_spack(monkeypatch, installed=True, external=True)

    bootstrap_module.bootstrap(
        "gcc@15", languages=("c",), probe="zlib", command=COMMAND, env=ENV
    )

    assert [*COMMAND, "install", "gcc@15"] not in calls
    assert [*COMMAND, "compiler", "find", PREFIX] in calls


def test_bootstrap_installs_when_only_an_external_record_exists(monkeypatch):
    calls = _fake_spack(monkeypatch, external=True)

    bootstrap_module.bootstrap(
        "gcc@15", languages=("c",), probe="zlib", command=COMMAND, env=ENV
    )

    assert [*COMMAND, "install", "gcc@15"] in calls
    assert [*COMMAND, "compiler", "find", PREFIX] in calls


def test_bootstrap_reports_a_probe_that_never_finishes(monkeypatch):
    _fake_spack(monkeypatch, probe_timeout=True)

    with pytest.raises(RuntimeError, match="did not concretize compiler probe"):
        bootstrap_module.bootstrap(
            "gcc@15", languages=("c",), probe="zlib", command=COMMAND, env=ENV, probe_timeout=1
        )


def test_bootstrap_dry_run_changes_nothing(monkeypatch):
    calls = _fake_spack(monkeypatch)

    result = bootstrap_module.bootstrap(
        "gcc@15", languages=("c",), probe="zlib", command=COMMAND, env=ENV, dry_run=True
    )

    assert result.registered is False
    assert not any(call[-3:-1] == ["compiler", "find"] for call in calls)
    assert not any("require" in part for call in calls for part in call)
