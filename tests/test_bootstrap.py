# SPDX-License-Identifier: Apache-2.0
import subprocess

import seanstack.bootstrap as bootstrap_module


def test_bootstrap_uses_isolated_spack_command():
    calls: list[list[str]] = []

    def fake_run(args, *, check=True, env=None):
        calls.append(args)
        if args[-3:-1] == ["location", "-i"]:
            return subprocess.CompletedProcess(args, 1, "", "")
        if "spec" in args:
            return subprocess.CompletedProcess(args, 0, "gcc@15", "")
        return subprocess.CompletedProcess(args, 0, "", "")

    original = bootstrap_module._run
    bootstrap_module._run = fake_run
    try:
        command = ["/opt/spack/bin/spack", "-C", "/state/spack/config"]
        result = bootstrap_module.bootstrap(
            "gcc@15", languages=("c", "cxx"), probe="zlib", command=command, env={"SPACK_DISABLE_LOCAL_CONFIG": "true"}
        )
    finally:
        bootstrap_module._run = original

    assert result.compiler == "gcc@15"
    assert [*command, "install", "gcc@15"] in calls
    assert [*command, "config", "add", "packages:c:require:gcc@15"] in calls
    assert [*command, "config", "add", "packages:cxx:require:gcc@15"] in calls
