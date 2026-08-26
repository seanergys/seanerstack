# SPDX-License-Identifier: Apache-2.0
import subprocess

import seanstack.bootstrap as bootstrap_module


def test_bootstrap_uses_runtime_compiler_and_native_spack_scope(monkeypatch):
    calls: list[list[str]] = []

    monkeypatch.setattr(bootstrap_module.shutil, "which", lambda name: "/usr/bin/spack")

    def fake_run(args, *, check=True):
        calls.append(args)
        if args[:3] == ["spack", "location", "-i"]:
            return subprocess.CompletedProcess(args, 1, "", "")
        if args[:2] == ["spack", "spec"]:
            return subprocess.CompletedProcess(args, 0, "gcc@15", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(bootstrap_module, "_run", fake_run)

    result = bootstrap_module.bootstrap("gcc@15", languages=("c", "cxx"), probe="zlib", scope="user")

    assert result.compiler == "gcc@15"
    assert ["spack", "install", "gcc@15"] in calls
    assert ["spack", "config", "--scope", "user", "add", "packages:c:require:gcc@15"] in calls
    assert ["spack", "config", "--scope", "user", "add", "packages:cxx:require:gcc@15"] in calls
