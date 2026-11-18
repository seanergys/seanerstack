# SPDX-License-Identifier: Apache-2.0
import subprocess

import pytest

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


def test_the_target_requirement_replaces_an_earlier_one(monkeypatch):
    calls = _fake_spack(monkeypatch)

    bootstrap_module.require_target(COMMAND, "x86_64_v3", ENV)

    assert calls == [
        [*COMMAND, "config", "remove", "packages:all:require"],
        [*COMMAND, "config", "add", "packages:all:require:target=x86_64_v3"],
    ]


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
